# HiLark Multi-Tenant Data Isolation Security Audit

**Date:** 2025-01-XX  
**Auditor:** AI Assistant (Kiro)  
**Scope:** Toàn bộ codebase HiLark Server  
**Objective:** Xác định và đánh giá rủi ro rò rỉ dữ liệu chéo giữa các tenant

---

## Executive Summary

### 🔴 CRITICAL FINDINGS (Phải Fix Ngay)

**1. MongoDB Delete Operations KHÔNG CÓ Tenant Filter**
- **File:** `server/services/knowledge/chat_scopes.py:406`
- **Code:**
  ```python
  res = await coll.delete_one({"chat_id": chat_id})  # ❌ MISSING TENANT FILTER
  ```
- **Risk:** Tenant A có thể xóa chat scope của Tenant B nếu biết chat_id
- **Impact:** **HIGH** - Data deletion across tenant boundaries
- **Fix Required:** 
  ```python
  query = inject_tenant_filter({"chat_id": chat_id}, tenant_key)
  res = await coll.delete_one(query)
  ```

**2. WeKnora Retrieve Calls - Phụ Thuộc tenant_id Được Resolve Đúng**
- **File:** `server/services/workflows/chat_workflow.py:944-1040`
- **Issue:** Tất cả 9 WeKnora retrieve calls đều truyền `tenant_id=weknora_tenant_id`
- **Risk:** Nếu `weknora_tenant_id` resolve sai → Query vào sai WeKnora tenant workspace
- **Impact:** **CRITICAL** - Direct cross-tenant document access
- **Dependencies:**
  - `tenant_cfg = await get_tenant_config(eff_tenant)` phải trả về đúng tenant
  - `weknora_tenant_id = tenant_cfg.get("weknora_tenant_id")` phải có giá trị
  - WeKnora backend phải enforce X-Tenant-ID header isolation

**3. Digest Get By ID KHÔNG CÓ Tenant Filter**
- **File:** `server/services/workflows/digest_workflow.py:621, 884, 1099, 1171`
- **Code:**
  ```python
  doc = await coll.find_one({"id": digest_id})  # ❌ NO TENANT CHECK
  ```
- **Risk:** Tenant A có thể đọc digest của Tenant B nếu biết digest_id (UUID guessable)
- **Impact:** **HIGH** - Cross-tenant information disclosure
- **Fix Required:**
  ```python
  query = inject_tenant_filter({"id": digest_id}, tenant_key)
  doc = await coll.find_one(query)
  ```

---

## 🟡 MEDIUM RISK FINDINGS

**4. User Settings Query By open_id (No Tenant Isolation)**
- **File:** `server/services/user_settings_service.py:187`
- **Code:**
  ```python
  doc = await coll.find_one({"open_id": open_id})
  ```
- **Analysis:** User settings collection không có tenant_key field
- **Risk:** Nếu cùng 1 user làm việc ở nhiều tenant, settings có thể conflict
- **Mitigation:** Hiện tại open_id là unique per user, nhưng cần review use case multi-tenant per user

**5. System Config Queries (Intentionally Global)**
- **Files:** Multiple locations accessing `system_config` collection
- **Analysis:** System config (bot credentials, admin config) là global by design
- **Risk:** **LOW** - These are shared configs, not tenant-specific data
- **Recommendation:** Document clearly which collections are global vs tenant-scoped

**6. Fallback Query Without Tenant Filter**
- **File:** `server/services/knowledge/chat_scopes.py:227`
- **Code:**
  ```python
  if not doc and tenant_key:
      # Fallback tự động sửa lỗi bản ghi cũ chưa gắn tenant_key
      doc = await coll.find_one({"chat_id": chat_id})  # ❌ NO TENANT FILTER
  ```
- **Analysis:** Đây là migration helper để patch old records
- **Risk:** **MEDIUM** - Could return wrong tenant's data during migration
- **Recommendation:** Thêm check `doc.get("tenant_key")` is None before patching

---

## 🟢 SECURE IMPLEMENTATIONS (Good Practices)

**7. Scoped Query Collections Using inject_tenant_filter** ✅
- **Files:** 
  - `chat_scopes.py:224, 351, 427`
  - `draft_store.py:41`
  - `claim_workflow.py:65`
  - `digest_workflow.py:102, 232, 272`
- **Pattern:**
  ```python
  query = inject_tenant_filter({"chat_id": chat_id}, tenant_key)
  doc = await coll.find_one(query)
  ```
- **Status:** ✅ SECURE - Properly isolated

**8. Auto-Inject tenant_key On Insert** ✅
- **File:** `database/scoped_query.py:112-118`
- **Pattern:**
  ```python
  async def insert_one(self, document: Dict[str, Any], *args, **kwargs):
      doc = dict(document)
      eff = self.effective_tenant
      if eff and not doc.get("tenant_key"):
          doc["tenant_key"] = eff  # ✅ AUTO-TAG
      return await self._raw_col.insert_one(doc, *args, **kwargs)
  ```
- **Status:** ✅ SECURE - Prevents untagged documents

**9. Tenant Context Propagation via ContextVar** ✅
- **File:** `database/scoped_query.py:19-35`
- **Pattern:** Uses `contextvars.ContextVar` for async task isolation
- **Status:** ✅ SECURE - Per-request isolation guaranteed

---

## 🔍 DEPENDENCY ANALYSIS

### WeKnora Tenant Isolation Chain

```
1. Lark Webhook → Extract tenant_key
   ↓
2. set_current_tenant_key(tenant_key)
   ↓
3. get_tenant_config(tenant_key) → MongoDB tenants collection
   ↓
4. weknora_tenant_id = tenant_cfg["weknora_tenant_id"]
   ↓
5. _weknora.retrieve(..., tenant_id=weknora_tenant_id)
   ↓
6. HTTP Header: X-Tenant-ID = weknora_tenant_id
   ↓
7. WeKnora Backend Enforces Isolation (EXTERNAL DEPENDENCY)
```

**Critical Points:**
- ❓ **Step 1:** Tenant extraction from Lark webhook - cần verify logic
- ❓ **Step 3:** `get_tenant_config()` query không có tenant filter (vì query BY tenant_key)
- ❓ **Step 7:** **WeKnora backend PHẢI enforce X-Tenant-ID** - nếu không sẽ bị rò rỉ

**Verification Needed:**
1. Check Lark webhook handler extractsự tenant_key từ đâu (app_id mapping?)
2. Verify WeKnora backend source code có enforce X-Tenant-ID không
3. Test: Gửi request với X-Tenant-ID của tenant khác → Phải bị từ chối

---

## 📋 COLLECTIONS TENANT ISOLATION STATUS

| Collection | Tenant Isolated? | Notes |
|------------|-----------------|-------|
| `tenants` | ❌ Global | Chứa config tất cả tenants, query by tenant_key |
| `system_config` | ❌ Global | Bot credentials, admin config (shared) |
| `auth_tokens` | ❌ Global | ISV tokens, query by tenant_key |
| `chat_scopes` | ✅ YES | Field: `tenant_key`, queries use inject_tenant_filter |
| `user_settings` | ⚠️ Partial | Query by open_id only (no tenant field) |
| `draft_messages` | ✅ YES | Field: `tenant_key`, scoped queries |
| `claims` / `facts` | ✅ YES | Field: `tenant_key`, scoped queries |
| `daily_digests` | ⚠️ PARTIAL | **MISSING tenant filter on get_by_id** |
| `master_daily_digests` | ⚠️ PARTIAL | **MISSING tenant filter on get_by_id** |
| `staging_messages` | ✅ YES | Scoped by chat_id which has tenant isolation |

---

## 🛠️ RECOMMENDED FIXES

### Priority 1: CRITICAL (Must Fix Before Production)

**Fix 1: Add Tenant Filter to delete_one in chat_scopes**
```python
# File: server/services/knowledge/chat_scopes.py:406
async def unlink_kb_from_chat(self, chat_id: str, requester_open_id: str) -> Tuple[bool, str]:
    # ... existing auth check ...
    try:
        coll = _get_active_scopes_col()
        eff_tenant = get_current_tenant_key()
        query = inject_tenant_filter({"chat_id": chat_id}, eff_tenant)  # ← ADD THIS
        res = await coll.delete_one(query)  # ← USE query
        # ... rest of code ...
```

**Fix 2: Add Tenant Filter to digest get_by_id**
```python
# File: server/services/workflows/digest_workflow.py:621
async def get_digest_by_id(self, digest_id: str, tenant_key: Optional[str] = None) -> Optional[DailyDigestRecord]:
    try:
        coll = _get_daily_digests_coll()
        eff_tenant = tenant_key or get_current_tenant_key()
        query = inject_tenant_filter({"id": digest_id}, eff_tenant)  # ← ADD THIS
        doc = await coll.find_one(query)  # ← USE query
        # ... rest of code ...
```

Apply same fix to:
- `digest_workflow.py:884` (get_master_digest_by_id)
- `digest_workflow.py:1099` (approve_master_digest)
- `digest_workflow.py:1171` (reject_master_digest)

**Fix 3: Improve Fallback Query Safety**
```python
# File: server/services/knowledge/chat_scopes.py:227
if not doc and tenant_key:
    doc = await coll.find_one({"chat_id": chat_id})
    if doc:
        # ← ADD: Verify it's actually untagged (not from another tenant)
        if doc.get("tenant_key") and doc["tenant_key"] != tenant_key:
            logger.warning(f"Chat {chat_id} belongs to tenant {doc['tenant_key']}, not {tenant_key}")
            return None  # ← Don't return cross-tenant data
        # Only patch if truly untagged
        if not doc.get("tenant_key"):
            await coll.update_one({"_id": doc["_id"]}, {"$set": {"tenant_key": tenant_key}})
```

### Priority 2: MEDIUM (Security Hardening)

**Fix 4: Add Tenant Context Validation Middleware**
```python
# New file: server/middleware/tenant_validator.py
async def validate_tenant_context(request: Request, call_next):
    """Ensure tenant_key is set for all authenticated requests"""
    tenant_key = get_current_tenant_key()
    path = request.url.path
    
    # Skip validation for public endpoints
    if path in ["/health", "/webhook/lark", "/auth/callback"]:
        return await call_next(request)
    
    # Enforce tenant_key for protected routes
    if not tenant_key:
        logger.warning(f"Request to {path} without tenant context")
        # Could return 403 or set default tenant based on policy
    
    response = await call_next(request)
    return response
```

**Fix 5: Add WeKnora Tenant ID Validation**
```python
# File: server/services/knowledge/weknora_client.py
async def retrieve(self, ..., tenant_id: Optional[int] = None):
    # ← ADD: Verify tenant_id matches current context
    current_tenant = get_current_tenant_key()
    if current_tenant and tenant_id:
        # Lookup expected tenant_id for current_tenant
        from database.db import get_tenant_config
        cfg = await get_tenant_config(current_tenant)
        expected_id = cfg.get("weknora_tenant_id") if cfg else None
        
        if expected_id and tenant_id != expected_id:
            logger.error(f"⚠️ SECURITY: Tenant {current_tenant} trying to access WeKnora tenant {tenant_id}, expected {expected_id}")
            raise ValueError(f"Invalid WeKnora tenant_id for current tenant")
    
    # ... proceed with retrieve ...
```

---

## 🧪 TESTING RECOMMENDATIONS

### Test Case 1: Cross-Tenant Data Access Attempt
```python
async def test_cross_tenant_isolation():
    # Setup: Create 2 tenants with data
    with tenant_context("tenant_A"):
        scope_A = await scope_service.link_kb_to_chat("chat_123", ...)
    
    with tenant_context("tenant_B"):
        scope_B = await scope_service.link_kb_to_chat("chat_456", ...)
    
    # Attack: Tenant B tries to read Tenant A's scope
    with tenant_context("tenant_B"):
        result = await scope_service.get_scope_by_chat_id("chat_123")
        assert result is None, "❌ SECURITY BREACH: Cross-tenant read succeeded!"
    
    # Attack: Tenant B tries to delete Tenant A's scope
    with tenant_context("tenant_B"):
        success, msg = await scope_service.unlink_kb_from_chat("chat_123", admin_id)
        assert not success, "❌ SECURITY BREACH: Cross-tenant delete succeeded!"
```

### Test Case 2: WeKnora Tenant ID Spoofing
```python
async def test_weknora_tenant_spoofing():
    with tenant_context("tenant_A"):
        # Get legit tenant_id for A
        cfg_A = await get_tenant_config("tenant_A")
        tenant_id_A = cfg_A["weknora_tenant_id"]
    
    with tenant_context("tenant_B"):
        # Tenant B tries to query with Tenant A's tenant_id
        try:
            chunks = await weknora_service.retrieve(
                query="confidential info",
                knowledge_base_ids=["kb_123"],
                tenant_id=tenant_id_A  # ← SPOOFED
            )
            assert False, "❌ SECURITY BREACH: Tenant ID spoofing succeeded!"
        except ValueError:
            pass  # ✅ Expected: Should be blocked
```

### Test Case 3: Digest Cross-Tenant Access
```python
async def test_digest_isolation():
    # Tenant A creates digest
    with tenant_context("tenant_A"):
        digest_A = await digest_service.create_daily_digest(...)
        digest_id_A = digest_A.id
    
    # Tenant B tries to read it
    with tenant_context("tenant_B"):
        result = await digest_service.get_digest_by_id(digest_id_A)
        assert result is None, "❌ SECURITY BREACH: Cross-tenant digest read!"
```

---

## 📊 RISK SCORING

| Issue | Likelihood | Impact | Risk Score | Priority |
|-------|-----------|--------|-----------|----------|
| Delete without tenant filter | Medium | High | **🔴 CRITICAL** | P0 |
| Digest get_by_id no filter | Medium | High | **🔴 CRITICAL** | P0 |
| WeKnora tenant_id spoofing | Low | Critical | **🔴 HIGH** | P1 |
| Fallback query unsafe | Low | Medium | **🟡 MEDIUM** | P2 |
| User settings no tenant | Low | Low | **🟢 LOW** | P3 |

---

## ✅ ACTION ITEMS

- [ ] **P0:** Fix `delete_one` in chat_scopes.py (ETA: 1 hour)
- [ ] **P0:** Fix digest `get_by_id` queries (ETA: 2 hours)
- [ ] **P1:** Add WeKnora tenant_id validation (ETA: 3 hours)
- [ ] **P1:** Write security test suite (ETA: 1 day)
- [ ] **P2:** Improve fallback query safety (ETA: 1 hour)
- [ ] **P2:** Add tenant context validation middleware (ETA: 2 hours)
- [ ] **P3:** Document global vs tenant-scoped collections (ETA: 1 hour)
- [ ] **P3:** Review WeKnora backend tenant isolation (External dependency)

---

## 🔐 CONCLUSION

**Overall Security Posture:** ⚠️ **MODERATE RISK**

**Strengths:**
- ✅ Core isolation mechanism (`inject_tenant_filter`, `ContextVar`) is well-designed
- ✅ Majority of queries use tenant filtering correctly
- ✅ Auto-inject tenant_key on insert prevents untagged documents

**Critical Gaps:**
- 🔴 Delete operations missing tenant filter (data loss risk)
- 🔴 Digest queries bypass tenant isolation (information disclosure)
- 🔴 WeKnora tenant_id relies on external enforcement (unverified)

**Recommendation:** **DO NOT DEPLOY TO PRODUCTION** until P0 fixes are applied and security tests pass.

**Timeline:** All P0 and P1 fixes can be completed within 1 working day.

---

**Prepared by:** Kiro AI Agent  
**Review Required:** Senior Security Engineer + DevOps Lead  
**Next Review Date:** After implementing fixes + before production deployment
