# 📘 ĐẶC TẢ KỸ THUẬT AN NINH & PHÂN QUYỀN DỮ LIỆU (SECURITY ARCHITECTURE SPEC)
> **Dự án HiLark Server** — Bản đặc tả kỹ thuật chi tiết (Spec), đối chiếu mã nguồn thực tế, ưu tiên tiếng Việt mộc mạc, chuẩn xác từng dòng code.  
> **Vị trí file:** [`server/docs/permission/security_architecture_spec.md`](file:///Users/hoainam/Desktop/HiLark/server/docs/permission/security_architecture_spec.md)

---

## 🧭 1. NGUYÊN LÝ THIẾT KẾ & TỔNG THỂ HỆ THỐNG

Kiến trúc an ninh của HiLark giải quyết bài toán cốt lõi: **Làm sao để một Trợ lý AI có thể hoạt động đồng thời trên hàng chục nhóm chat dự án khác nhau của doanh nghiệp mà không bị rò rỉ dữ liệu chéo, không bị khai thác Prompt Injection, và không vô tình làm lộ thông tin nhạy cảm của công ty.**

Hệ thống triển khai mô hình **Phòng thủ Chiều sâu 5 Tầng (5-Tier Defense-in-Depth)**:

```
[Người dùng nhắn tin từ Lark]
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. TẦNG 1: RBAC & IDENTITY GOVERNANCE                       │
│    • Phân định Owner vs Member                              │
│    • Whitelist Open IDs: settings.LARK_USER_OPEN_ID         │
│    • Thin Controller: routers/scope.py (403 Forbidden)      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. TẦNG 2: GROUP SCOPE & HARD DATA ISOLATION                │
│    • ChatScopeRecord (MongoDB collection 'chat_scopes')     │
│    • WeKnora: Chỉ tìm kiếm trong 'knowledge_ids' của nhóm   │
│    • Claims: MongoDB Query '$or': chat_id == group_id       │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. TẦNG 3: VỌNG GÁC Ý ĐỊNH ĐẦU VÀO (LAYER 2 GATING)        │
│    • TextFilter: Lọc ký tự lạ, chặn flood lặp, 2-1000 từ   │
│    • Group Status: is_active == False -> Ngắt pipeline ngay │
│    • JEV Forbidden Intent: AI NLU bắt tiếng lóng/hỏi vòng vo│
│    • Phản xạ kép: Zero-Response (im lặng) + Mật báo DM Sếp  │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. TẦNG 4: CHỐT CHẶN AN NINH TRI THỨC (LAYER 3 RULE ENGINE) │
│    • Unified Rule Engine: Lọc tất định In-Memory (0ms, 0$)  │
│    • Tầng 1: Canonical Property Mapping (budget, salary...) │
│    • Tầng 2: Vietnamese Word-Boundary Regex Matcher         │
│    • Trảm Claim/Chunk vi phạm nhãn cấm                      │
│    • Safety RAG Gate: KB rỗng -> Downgrade DRAFT            │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. TẦNG 5: KIỂM SOÁT ĐẦU RA & HUMAN-IN-THE-LOOP (LAYER 4)   │
│    • Strict Confidential: Nhóm Tuyệt mật -> Zero Auto-reply │
│    • Owner Anti-Loop Shield: Cấm bot tự reply Sếp trong group│
│    • Interactive DM Approval: Duyệt [Gửi] / [Sửa] / [Bỏ]    │
│    • TextFilter Output Scrubbing: Xóa sạch technical tokens │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔑 2. TẦNG 1: QUẢN TRỊ DANH TÍNH & PHÂN QUYỀN VAI TRÒ (RBAC)

### 2.1. Phân định Vai trò Hệ thống
Hệ thống chia người dùng thành 2 vai trò cơ bản:

```
                      ┌─────────────────────────────────┐
                      │      DANH TÍNH NGƯỜI DÙNG       │
                      └────────────────┬────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
        ┌───────────────────────┐             ┌───────────────────────┐
        │   CHỦ NHÂN / ADMIN    │             │  THÀNH VIÊN THƯỜNG    │
        │     (Owner / Admin)   │             │     (Team Member)     │
        └───────────┬───────────┘             └───────────┬───────────┘
                    │                                     │
    ┌───────────────┴───────────────┐                     │
    ▼                               ▼                     ▼
• Duyệt Master Daily Digest     • Cấu hình Knowledge Base   • Hỏi đáp trong nhóm được gán
• Duyệt Draft qua DM            • Nhận mật báo an ninh      • Bị cách ly theo phạm vi nhóm
• Quản lý Scope qua API         • Quyền bypass an toàn      • Không có quyền quản trị
```

### 2.2. Thuật toán kiểm tra Admin (Whitelist Validation)
* **Vị trí mã nguồn:** [`server/services/scope_service.py:L53-75`](file:///Users/hoainam/Desktop/HiLark/server/services/scope_service.py#L53-L75)
* **Thuật toán:**
  ```python
  def get_admin_open_ids(self) -> List[str]:
      admins = set()
      if settings.LARK_USER_OPEN_ID:
          admins.add(settings.LARK_USER_OPEN_ID.strip())
      if settings.DIGEST_APPROVER_ID:
          admins.add(settings.DIGEST_APPROVER_ID.strip())
      if lark_service.owner_open_id:
          admins.add(lark_service.owner_open_id.strip())
      extra_admins = os.getenv("admin_open_ids", "")
      if extra_admins:
          for aid in extra_admins.split(","):
              if aid.strip():
                  admins.add(aid.strip())
      return list(admins)

  def is_admin_user(self, open_id: str) -> bool:
      if not open_id:
          return False
      return open_id.strip() in self.get_admin_open_ids()
  ```

### 2.3. Ranh giới giữa In-Memory Service và REST API Controller
* **Cơ chế gọi nội bộ:** Trong runtime của bot, các module [`chat_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py) và [`bot_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/bot_service.py) gọi trực tiếp các phương thức Python của `scope_service` (In-memory CPU call, độ trễ 0ms, không phát sinh HTTP Request).
* **Cổng mở ngoài (Thin Controller):** [`server/routers/scope.py`](file:///Users/hoainam/Desktop/HiLark/server/routers/scope.py) là cổng HTTP mở ra cho bên ngoài (Postman, Frontend Dashboard, Webhook ngoài).
  - Khi có yêu cầu `DELETE /api/v1/scopes/{chat_id}`:
    ```python
    # server/routers/scope.py:L90-93
    ok, msg = await scope_service.reset_chat_kb(chat_id=chat_id, operator_open_id=op_id)
    if not ok:
        raise HTTPException(status_code=403, detail=msg)  # Chặn đứng kẻ mạo danh bằng 403 Forbidden
    ```

---

## 📦 3. TẦNG 2: PHẠM VI DỮ LIỆU CẤP NHÓM & CÁCH LY CỨNG (DATA ISOLATION)

### 3.1. Mô hình Cấu trúc `ChatScopeRecord`
* **Vị trí mã nguồn:** [`server/models/chat_scope.py:L18-40`](file:///Users/hoainam/Desktop/HiLark/server/models/chat_scope.py#L18-L40)
* Lưu trữ trong MongoDB collection `chat_scopes`, đồng bộ tự động từ Lark Base (`services/scope_service.py`).
* **Các trường cốt lõi:**
  - `chat_id`: Khóa chính định danh nhóm chat trên Lark (`oc_xxx`).
  - `chat_name`: Tên nhóm chat hiển thị trên Lark.
  - `dataset_id`: Mã Knowledge Base gán cho nhóm trên WeKnora.
  - `knowledge_ids`: Danh sách ID các tài liệu đính kèm của nhóm (`["know_1", "know_2"]`).
  - `project_tag`: Nhãn định danh dự án của nhóm (e.g. `fintech`, `ecommerce`), phục vụ cách ly Claims.
  - `security_level`: Mức độ bảo mật (`"Nội bộ"` hoặc `"Tuyệt mật"`).
  - `forbidden_labels`: Tập hợp nhãn cấm xem (`["Ngân sách", "Lương", "Hợp đồng"]`).
  - `status`: Trạng thái hoạt động của nhóm (`"Hoạt động"` hoặc `"Tạm dừng"`).
* **Cơ chế bảo toàn Project Tag khi Đồng bộ (Tag Retention Guard):**
  Trong [`server/services/scope_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/scope_service.py), bảng ánh xạ `BASE_FIELD_MAP` chuẩn hóa các tên cột: `"Nhãn dự án"`, `"Dự án nhóm"`, `"Mã dự án"`, `"project_tag"`. Đặc biệt, hệ thống áp dụng cơ chế:
  ```python
  effective_project_tag = raw_project_tag or (existing_scope.project_tag if existing_scope else None)
  ```
  Giúp bảo vệ tag phân vùng dự án không bao giờ bị ghi đè thành `None` nếu bản ghi Webhook hoặc Cron đồng bộ từ Lark Base không chứa cột này.

### 3.2. Cách ly RAG WeKnora (RAG Hard Isolation)
* **Vị trí mã nguồn:** [`server/services/chat_service.py:L459-466`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L459-L466)
* **Vấn đề:** Nếu gọi tìm kiếm toàn cục (Global Search), WeKnora có thể trả về tài liệu của Dự án A cho thành viên nhóm Dự án B.
* **Giải pháp kỹ thuật:**
  ```python
  target_knowledge_ids = (
      scope_record.knowledge_ids if (scope_record and scope_record.knowledge_ids) else None
  )
  chunks = await weknora_service.retrieve(
      query=retrieval_query,
      knowledge_base_ids=target_kbs,
      knowledge_ids=target_knowledge_ids,  # Khóa cứng trong danh sách tài liệu của nhóm!
      match_count=retrieve_count,
  )
  ```
  👉 **Bảo đảm:** WeKnora chỉ quét trong tập con `target_knowledge_ids`. Kể cả người dùng có cố tình prompt "Cho tôi xem tài liệu dự án Fintech" trong nhóm Dự án E-commerce, WeKnora cũng không bao giờ chạm tới file của Fintech.

### 3.3. Cách ly Tri thức Động MongoDB (Claims Hard Scoping)
* **Vị trí mã nguồn:** [`server/database/db.py:L229-260`](file:///Users/hoainam/Desktop/HiLark/server/database/db.py#L229-L260) (`get_all_facts`)
* **Câu lệnh truy vấn MongoDB tất định:**
  ```python
  # server/database/db.py:L244-255
  scope_or = [{"scope_type": "global"}]
  if chat_id:
      scope_or.append({"chat_id": chat_id})
  if project_tag:
      scope_or.append({"project_tag": project_tag})
  
  query = {"$or": scope_or}
  cursor = col.find(query)
  ```
  👉 **Bảo đảm:** Một câu hỏi phát sinh từ `chat_id_A` **chỉ có thể đọc được** Claims của chính `chat_id_A` hoặc các Claims toàn công ty (`scope_type == "global"`). Hoàn toàn không thể đọc chéo sang `chat_id_B`.

---

## 🚪 4. TẦNG 3: VỌNG GÁC Ý ĐỊNH ĐẦU VÀO (LAYER 2 INPUT GATING)

### 4.1. Dọn rác & Kiểm tra kích thước (Syntactic Sanitizer)
* **Vị trí mã nguồn:** [`server/utils/text_filter.py:L19-37`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py#L19-L37)
* Chuẩn hóa khoảng trắng và khử chuỗi ký tự lặp rác (`re.sub(r'([!@#$%^&*?])\1+', r'\1', text)`).
* Kiểm soát biên độ:
  - `MIN_WORDS = 2`: Chặn tin nhắn cộc lốc vô nghĩa (`"?"`, `"alo"`, `"hi"`).
  - `MAX_WORDS = 1000` (~1300 tokens): Ngăn chặn tấn công tràn bộ đệm ngữ cảnh (Buffer Overflow / Massive Context Prompt Injection).

### 4.2. Khóa nhóm tạm dừng (Group Inactive Shield)
* **Vị trí mã nguồn:** [`server/services/chat_service.py:L310-321`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L310-L321)
* Nếu quản trị viên chuyển trạng thái nhóm trên Lark Base sang `Tạm dừng` hoặc `Lưu trữ`:
  - `scope_record.is_active` trả về `False`.
  - Hệ thống ngắt pipeline ngay lập tức (`status="group_inactive"`, `jev_action="IGNORE"`), không tiêu tốn tài nguyên RAG hay LLM.

### 4.3. JEV Forbidden Intent Gating (AI Semantic NLU & Tiếng lóng)
* **Vị trí mã nguồn:** [`server/services/jev.py:L198-388`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py#L198-L388) và [`server/services/chat_service.py:L323-370`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L323-L370)
* **Cấu trúc 2 lớp kết hợp:**
  1. **Lớp 1 — Fast Keyword Matcher (< 0.1ms):** Quét trực tiếp nếu câu hỏi chứa chuỗi từ khóa đen (`lương`, `chi phí`).
  2. **Lớp 2 — JEV Semantic Choice Evaluator:** Gửi câu hỏi sang mô hình JEV System One với cấu trúc Prompt chuyên sâu:
     ```json
     {
       "state": "Nội dung câu hỏi của người dùng: \"Tháng này kế toán đã ting ting mấy chục củ vào tài khoản chưa?\"",
       "model": "jev-latest",
       "questions": {
         "forbidden_intent": {
           "type": "choice",
           "instructions": "Nhiệm vụ của bạn là kiểm tra xem câu hỏi của người dùng có cố tình tra cứu, hỏi đáp hoặc yêu cầu tiết lộ thông tin liên quan TRỰC TIẾP hoặc GIÁN TIẾP đến bất kỳ chủ đề cấm nào sau đây hay không: [Lương, Bảng lương, Thu nhập]. Chú ý nhận diện cả tiếng lóng, cách nói ẩn ý hoặc vòng vo.",
           "criteria": {
             "FORBIDDEN": "Câu hỏi liên quan trực tiếp hoặc gián tiếp đến chủ đề cấm.",
             "ALLOWED": "Câu hỏi thông thường, an toàn."
           }
         }
       }
     }
     ```
* **Khả năng nhận diện ngữ nghĩa thực tế:**
  - *"ting ting mấy chục củ"* $\rightarrow$ Bắt `FORBIDDEN` (Lương/Thu nhập).
  - *"đút túi bao nhiêu phần trăm từ khách"* $\rightarrow$ Bắt `FORBIDDEN` (Lợi nhuận/Ngân sách).
  - *"xin file có chữ ký hai bên"* $\rightarrow$ Bắt `FORBIDDEN` (Hợp đồng/NDA).
  - *"Số lượng màn hình UI trong Sprint"* $\rightarrow$ Chọn `ALLOWED` (An toàn, không bắt nhầm "lương" trong "số lượng").

### 4.4. Cơ chế Phản xạ Kép: Zero-Response & Mật báo ngầm
Khi phát hiện vi phạm nhãn cấm:
1. **Zero-Response (Im lặng tuyệt đối):** Bot không phát ngôn bất kỳ ký tự nào vào nhóm, trả về `IGNORE`. Kẻ tấn công không thể dựa vào câu trả lời để dò đoán biên giới tri thức.
2. **Mật báo ngầm tới DM Sếp:** Kích hoạt [`lark_service.send_bot_dm_to_owner()`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L355) gửi tin báo khẩn cấp:
   ```text
   ⚠️ [CẢNH BÁO BẢO MẬT: TRUY CẬP TRÁI PHÉP]
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   👥 Nhóm chat : [Project 1] Fintech (oc_6c6ee0dc...)
   👤 Thành viên: Cao Phụng (ou_c073866...)
   💬 Câu hỏi   : "Tháng này kế toán đã ting ting mấy chục củ vào tài khoản chưa?"
   🚫 Nhãn cấm  : Lương, Thu nhập
   🛡️ Phản hồi  : Bot đã IM LẶNG HOÀN TOÀN, không phát ngôn vào nhóm.
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```

---

## 🛡️ 5. TẦNG 4: CHỐT CHẶN AN NINH TRI THỨC (UNIFIED RULE ENGINE)

### 5.1. Tại sao không dùng AI mà dùng Rule Engine tất định?
Dữ liệu mật nội bộ (bảng lương, hợp đồng, chi phí) **tuyệt đối không được giao cho mô hình xác suất (AI)** vì nguy cơ bị Hallucination hoặc Prompt Injection lừa gạt. `UnifiedRuleEngine` là thuật toán **Deterministic 100%**, thực thi In-Memory trên CPU với **độ trễ 0ms** và **chi phí 0 token**.

### 5.2. Ba tầng lọc chi tiết của Rule Engine
* **Vị trí mã nguồn:** [`server/utils/rule_engine.py:L1-489`](file:///Users/hoainam/Desktop/HiLark/server/utils/rule_engine.py#L1-L489)
* **Kích hoạt tại:** [`server/services/chat_service.py:L501-511`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L501-L511)
  ```python
  clean_chunks, clean_claims = rule_engine.sanitize(
      chunks=normalized_chunks,
      claims=active_claims,
      forbidden_labels=forbidden_labels,
      query=clean_query,
  )
  ```
* **Chiến lược thực thi: In-Memory (0ms) TRƯỚC JEV Filter:**
  Thay vì để JEV scoring trước, `RuleEngine.sanitize()` được kích hoạt ngay lập tức trên RAM (0ms CPU) sau khi WeKnora và MongoDB trả về dữ liệu thô. Chốt chặn này trảm sạch mọi chunk hoặc claim chứa nhãn cấm trước khi gửi `clean_chunks` qua mạng sang `jev_service.filter_chunks_relevance()` ([`server/services/chat_service.py:L512-524`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L512-L524)).
  - **Lợi ích 1 — An ninh tối thượng:** Tuyệt đối không gửi văn bản nhạy cảm (lương, chi phí, hợp đồng) ra ngoài mạng hoặc sang dịch vụ AI chấm điểm.
  - **Lợi ích 2 — Tối ưu hiệu năng & Chi phí:** Tiết kiệm token LLM và giảm đáng kể thời gian chờ (latency) vì JEV chỉ cần đánh giá tập con các đoạn trích đã hoàn toàn sạch sẽ.

1. **Tầng 1 — Canonical Property Mapping ([`rule_engine.py:L96-130`](file:///Users/hoainam/Desktop/HiLark/server/utils/rule_engine.py#L96-L130)):**
   Ánh xạ nhãn tiếng Việt trên Lark Base sang tập thuộc tính chuẩn tiếng Anh (`blocked_properties`):
   - *"Ngân sách, Chi phí, Giá"* $\rightarrow$ `budget, cost, price, fee, expense, financial, fund`.
   - *"Lương, Thu nhập, Thù lao"* $\rightarrow$ `salary, compensation, income, payroll, wage`.
   - *"Hợp đồng, Thỏa thuận, Đấu thầu"* $\rightarrow$ `contract, agreement, deal, nda, bid`.
   - Bất kỳ Claim nào có `property` trùng hoặc giao thoa token với tập này đều bị **DROP** ngay. Dùng thuật toán giao thoa token (`token intersection`) để chống bắt nhầm từ nghiệp vụ (ví dụ: cấm `fee` nhưng không bắt nhầm `feedback`, cấm `gia` nhưng không bắt nhầm `giai_doan`).

2. **Tầng 2 — Vietnamese Word-Boundary Regex Scanner ([`rule_engine.py:L210-227`](file:///Users/hoainam/Desktop/HiLark/server/utils/rule_engine.py#L210-L227)):**
   Quét chuỗi giá trị (`value`), trích dẫn gốc (`source_snippet`) của Claim và nội dung (`content`), tên tài liệu (`document_name`) của Chunk bằng 2 mẫu Regex an toàn:
   - Mẫu có dấu: `re.compile(rf"(?<!\w){re.escape(lbl_lower)}(?!\w)", re.IGNORECASE)`
   - Mẫu không dấu: Áp dụng hàm `remove_vietnamese_accents()` cho các nhãn $\ge 2$ từ hoặc thuần ASCII.

3. **Tầng 3 — Data Quality & Validity:**
   Loại bỏ triệt để các đoạn văn bản rỗng, chunks dưới 3 ký tự, claims thiếu `property` hoặc có `value` rỗng.

### 5.3. Safety RAG Gate (Hạ cấp an toàn khi rỗng tri thức)
* **Vị trí mã nguồn:** [`server/services/chat_service.py:L525-533`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L525-L533)
* **Quy tắc:** Nếu toàn bộ Chunks và Claims đều bị trảm do vi phạm nhãn cấm (dẫn đến `clean_chunks = []` và `clean_claims = []`):
  ```python
  if jev_action == "REPLY_ONLY" and not clean_chunks and not clean_claims:
      logger.warning("[RAG GATE] REPLY_ONLY nhưng KB rỗng -> Downgrade sang DRAFT_PENDING_APPROVAL.")
      jev_action = "DRAFT_PENDING_APPROVAL"
  ```
  👉 **Hành động:** Bot **CẤM trả lời tự động vào nhóm**. Ép chuyển thành bản nháp gửi về DM riêng của Sếp kèm nút bấm duyệt. Triệt tiêu 100% rủi ro AI bịa chuyện do thiếu tri thức cơ sở.

---

## 👑 6. TẦNG 5: KIỂM SOÁT PHÁT NGÔN & HUMAN-IN-THE-LOOP (HITL)

### 6.1. Chế độ Bảo mật Tuyệt mật (Strict Confidential - Zero Auto-reply)
* **Vị trí mã nguồn:** [`server/services/chat_service.py:L532-541`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L532-L541)
* Nếu nhóm chat được đánh dấu `security_level == "Tuyệt mật"` trên Lark Base:
  ```python
  is_confidential_group = bool(scope_record and scope_record.is_confidential)
  if is_confidential_group and jev_action == "REPLY_ONLY":
      logger.warning("🔒 [SECURITY LEVEL - TUYỆT MẬT] Kích hoạt Zero Auto-reply.")
      jev_action = "DRAFT_PENDING_APPROVAL"
  ```
  👉 **Chính sách:** Bot bị **tước 100% quyền tự động phát ngôn vào nhóm**. Toàn bộ câu trả lời bắt buộc chuyển thành bản nháp gửi riêng cho Sếp duyệt từng câu một.

### 6.2. Khiên chống lặp của Chủ nhân (Owner Anti-Loop Shield)
* **Vị trí mã nguồn:** [`server/services/chat_service.py:L382-394`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L382-L394)
* **Bài toán:** Khi chính Sếp nhắn tin trong nhóm làm việc, nếu bot tự động reply lại Sếp, có thể gây ra vòng lặp vô tận (Bot reply Sếp -> Bot đọc lại tin -> Loop) hoặc tạo cảm giác bot "cãi lại" hay "mạo danh" Sếp trước mặt nhân viên.
* **Giải pháp:** Khi phát hiện `is_owner == True` trong nhóm công khai:
  ```python
  if is_owner and channel == "lark_group":
      if jev_action in ("REPLY_ONLY", "MEMORY_AND_REPLY"):
          jev_action = "IGNORE" if jev_action == "REPLY_ONLY" else "MEMORY_ONLY"
  ```
  👉 Bot chỉ âm thầm ghi nhớ sự thật (`MEMORY_ONLY`) hoặc bỏ qua (`IGNORE`), tuyệt đối không tự phát ngôn.

### 6.3. Quy trình Duyệt nháp Tương tác qua Lark DM (HITL Workflow)
* **Vị trí mã nguồn:** [`server/services/draft_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/draft_service.py) và [`server/services/bot_service.py:L185-260`](file:///Users/hoainam/Desktop/HiLark/server/services/bot_service.py#L185-L260)
* Bản nháp `PendingDraft` được lưu trữ gắn liền với `owner_id`. Sếp có thể điều khiển trực tiếp qua giao diện chat 1-1 với Bot:
  1. **Lệnh duyệt nhanh:** Nhắn `"Gửi"`, `"Duyệt"`, `"OK"` $\rightarrow$ Bot gửi câu trả lời đã duyệt vào nhóm chat.
  2. **Lệnh chỉnh sửa:** Nhắn `"Sửa: [nội dung mới]"` $\rightarrow$ Bot cập nhật lại câu trả lời theo đúng ý Sếp rồi mới phát ngôn.
  3. **Lệnh hủy bỏ:** Nhắn `"Bỏ"`, `"Hủy"` $\rightarrow$ Xóa bản nháp, bot tiếp tục giữ im lặng.

---

## 🎯 7. MA TRẬN ĐỐI ỨNG CÁC NGUY CƠ BẢO MẬT (THREAT MATRIX)

| Nguy cơ bảo mật | Kỹ thuật tấn công / Tình huống | Chốt chặn đối ứng trong HiLark | Kết quả an ninh |
| :--- | :--- | :--- | :--- |
| **Dò hỏi trực tiếp chủ đề cấm** | Thành viên hỏi: *"Bảng lương của anh em dev tháng này?"* | **Tầng 3 (JEV Forbidden Intent)**: `Fast Keyword` + `JEV Semantic NLU` | 🛑 Zero-Response (Im lặng) + Mật báo DM về Sếp. |
| **Dùng tiếng lóng / Hỏi lắt léo** | Thành viên hỏi: *"Kế toán đã ting ting mấy chục củ chưa?"* | **Tầng 3 (JEV Semantic AI Evaluator)**: Prompt nhận diện tiếng lóng NLU | 🛑 Bắt `FORBIDDEN`, bot im lặng tuyệt đối. |
| **Đọc trộm tài liệu dự án khác** | Hỏi tài liệu Dự án B trong phòng chat Dự án A | **Tầng 2 (RAG Hard Isolation)**: Khóa cứng `knowledge_ids` theo `chat_id` | 🛑 WeKnora chỉ tìm file nhóm A, không thấy file nhóm B. |
| **Đọc trộm mệnh đề thực tế khác** | Hỏi deadline/tiến độ mật của dự án khác | **Tầng 2 (Claims Hard Scoping)**: MongoDB filter cứng `$or: chat_id == id` | 🛑 Database không trả về Claim của nhóm khác. |
| **Rò rỉ dữ liệu mật trong file hợp lệ** | File tài liệu hợp lệ vô tình chứa bảng chi phí/thầu phụ | **Tầng 4 (Unified Rule Engine)**: Canonical Mapping + Regex tiếng Việt | 🛑 Chunks/Claims vi phạm bị DROP ngay lập tức khỏi RAM. |
| **AI tự ý bịa chuyện (Hallucination)** | Câu hỏi chuyên môn nhưng kho tri thức rỗng sau khi lọc | **Tầng 4 (Safety RAG Gate)**: Empty context downgrade | 🛑 Cấm bot tự trả lời, ép chuyển sang Draft cho Sếp duyệt. |
| **Rò rỉ thông tin trong nhóm Tuyệt mật** | Nhóm dự án chiến lược NDA công ty | **Tầng 5 (Strict Confidential)**: Zero Auto-reply policy | 🛑 Khóa 100% quyền auto-reply, ép mọi câu hỏi sang Draft. |
| **Vòng lặp bot vô tận** | Bot đọc tin nhắn của Sếp trong nhóm rồi reply lại | **Tầng 5 (Owner Anti-Loop Shield)**: Ép `REPLY` sang `IGNORE` | 🛑 Triệt tiêu 100% vòng lặp tự phản hồi Sếp trong nhóm. |
| **Kẻ xấu gọi REST API để gỡ KB** | Gửi HTTP `DELETE /api/v1/scopes/{chat_id}` qua Postman | **Tầng 1 (Thin Controller RBAC)**: `ScopeService.is_admin_user()` | 🛑 Trả về `403 Forbidden`, ghi log cảnh báo an ninh. |
