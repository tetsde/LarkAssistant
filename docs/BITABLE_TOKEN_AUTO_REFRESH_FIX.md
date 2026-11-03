# Fix: Bitable Service Auto-Refresh Token

## Vấn đề

User Access Token trong `LarkBaseService` bị hết hạn và không tự động làm mới, gây ra lỗi:

```
PermissionError: [Lark Base Error 99991668] User Access Token đã hết hạn hoặc không hợp lệ.
-> Chi tiết từ Lark: Invalid access token for authorization. Please make a request with token attached.
```

Mặc dù đã có refresh token trong MongoDB, `LarkBaseService` không tích hợp với `token_service.py` để tự động làm mới token khi hết hạn.

## Nguyên nhân gốc

1. **Thiếu tích hợp với Token Service**: `LarkBaseService.__init__()` chỉ lấy token từ MongoDB một lần duy nhất lúc khởi tạo
2. **Không kiểm tra hết hạn**: Method `_get_headers()` sử dụng trực tiếp `self.user_access_token` mà không kiểm tra thời hạn
3. **Không tự động refresh**: Không có logic gọi `token_service.get_valid_user_token()` để lấy token mới

So sánh với `messenger.py`, đã có cơ chế auto-refresh token đúng cách trong `_prepare_user_msg_payload_async()`.

## Giải pháp

### 1. Thêm method `_get_valid_user_token()`

Tạo method helper để lấy valid user token với auto-refresh:

```python
def _get_valid_user_token(self, tenant_key: Optional[str] = None) -> str:
    """
    Lấy User Access Token còn hiệu lực, TỰ ĐỘNG REFRESH nếu đã hết hạn hoặc sắp hết hạn.
    Sử dụng token_service để đảm bảo token luôn mới.
    
    Xử lý cả sync và async context an toàn.
    """
    try:
        from services.auth.token_service import token_service
        from database.db import get_current_tenant_key
        
        eff_tenant = tenant_key or get_current_tenant_key()
        
        # Kiểm tra xem có đang chạy trong async event loop không
        try:
            loop = asyncio.get_running_loop()
            # Đang trong async context - dùng ThreadPoolExecutor
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    lambda: asyncio.run(token_service.get_valid_user_token(tenant_key=eff_tenant))
                )
                valid_token = future.result(timeout=15.0)
        except RuntimeError:
            # Không có running loop - chạy trực tiếp
            valid_token = asyncio.run(token_service.get_valid_user_token(tenant_key=eff_tenant))
        
        if valid_token:
            self.user_access_token = valid_token
            logger.info("✅ [BITABLE AUTO-REFRESH] User token đã được làm mới hoặc vẫn còn hạn")
            return valid_token
        else:
            raise PermissionError("User Access Token đã hết hạn...")
    except Exception as e:
        logger.error(f"Lỗi khi lấy/refresh user token: {e}", exc_info=True)
        # Fallback về token hiện tại nếu refresh thất bại
        if self.user_access_token:
            logger.warning("⚠️ Fallback về user_access_token hiện tại")
            return self.user_access_token
        raise
```

**Điểm quan trọng:**
- ✅ Xử lý cả sync và async context an toàn
- ✅ Dùng `ThreadPoolExecutor` để tránh conflict khi chạy `asyncio.run()` trong async context
- ✅ Tự động cập nhật `self.user_access_token` sau khi refresh thành công
- ✅ Có fallback về token cũ nếu refresh thất bại (cho phép retry)

### 2. Cập nhật `_get_headers()` để sử dụng auto-refresh

```python
def _get_headers(self, use_tenant_token: bool = False, tenant_key: Optional[str] = None) -> Dict[str, str]:
    """Tạo header xác thực với User Access Token hoặc Tenant Access Token."""
    self._validate_config(use_tenant_token=use_tenant_token)
    if use_tenant_token:
        # ... (logic tenant token giữ nguyên)
    
    # ✅ TỰ ĐỘNG REFRESH USER TOKEN NẾU HẾT HẠN
    valid_token = self._get_valid_user_token(tenant_key=tenant_key)
    return {
        "Authorization": f"Bearer {valid_token}",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "HiLark-Base-Reader/1.0",
    }
```

## Cách hoạt động

### Flow auto-refresh

1. **Mọi API call đều qua `_get_headers()`** 
   - `get_records()` → `_request()` → `_get_headers()`
   - `create_record()` → `_request()` → `_get_headers()`
   - `update_record()` → `_request()` → `_get_headers()`

2. **`_get_headers()` gọi `_get_valid_user_token()`**
   - Kiểm tra xem token có sắp hết hạn không (< 10 phút)
   - Tự động gọi `token_service.refresh_user_token()` nếu cần
   - Trả về token mới và cập nhật cache

3. **Token Service xử lý refresh**
   - Kiểm tra expires_at trong MongoDB
   - Gọi Lark API `/oidc/refresh_access_token` nếu cần
   - Lưu cặp (access_token, refresh_token) mới vào MongoDB (Single-Use Token Rotation)
   - Trả về access_token mới

### Xử lý Sync/Async Context

Code được thiết kế để hoạt động cả trong:

**Sync context** (CLI, script):
```python
service = LarkBaseService()
records = service.get_all_records()  # ✅ Auto-refresh hoạt động
```

**Async context via `asyncio.to_thread()`** (FastAPI):
```python
# Từ base_provision_service.py hoặc bot_runner.py
await asyncio.to_thread(lark_base_service.sync_bot_chats)  # ✅ Auto-refresh hoạt động
```

Method `_get_valid_user_token()` tự động detect running loop:
- Có loop → Dùng ThreadPoolExecutor + `asyncio.run()` trong thread riêng
- Không có loop → Chạy trực tiếp `asyncio.run()`

## Test & Verification

### Trước khi fix
```
PermissionError: [Lark Base Error 99991668] User Access Token đã hết hạn
```

### Sau khi fix
```
✅ [BITABLE AUTO-REFRESH] User token đã được làm mới hoặc vẫn còn hạn
🔄 [TOKEN ROTATED] Đã làm mới thành công User Token! Access token mới hạn 7200s
```

## Lợi ích

1. **Không cần can thiệp thủ công**: User không cần login lại khi token hết hạn
2. **Tương thích ngược**: Code cũ vẫn hoạt động bình thường
3. **Nhất quán với codebase**: Dùng cùng pattern với `messenger.py`
4. **An toàn**: Có fallback và error handling đầy đủ
5. **Support multi-tenant**: Tích hợp với tenant isolation của hệ thống

## Files thay đổi

- ✅ `/Users/hoainam/Desktop/HiLark/server/services/lark/bitable.py`
  - Thêm method `_get_valid_user_token()`
  - Cập nhật method `_get_headers()` để gọi `_get_valid_user_token()`

## Related

- Token Service: `server/services/auth/token_service.py`
- Messenger (tham khảo): `server/services/lark/messenger.py` dòng 289-310
- Token refresh loop: `token_service.start_token_refresh_loop()`

---

**Date**: 2026-11-02  
**Author**: Kiro Agent  
**Status**: ✅ Implemented & Tested
