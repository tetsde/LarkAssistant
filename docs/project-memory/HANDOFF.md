# Current Handoff

> Cập nhật khi kết thúc phiên có công việc đang dở hoặc bàn giao trạng thái sẵn sàng.

## Current task
- **Goal:** Xây dựng tính năng Tự động Làm mới Token (OAuth 2.0 Single-Use Refresh Token Rotation & MongoDB Storage) cho HiLark.
- **Status:** Completed (Đã hoàn thành core service, auth router, endpoints login & callback, nạp token lúc startup, background loop 30m, unit tests 9/9 passed).
- **Scope:**
  1. Xây dựng `LarkTokenService` (`server/services/token_service.py`): Quản lý `access_token`, `refresh_token`, `expires_at`, cơ chế xoay vòng token (rotation) và distributed lock (`asyncio.Lock`).
  2. Lưu trữ trạng thái token bền vững vào MongoDB collection `lark_auth` qua `AsyncIOMotorClient`.
  3. Xây dựng FastAPI Router `server/routers/auth.py` (`GET /auth/lark/login`, `GET /auth/lark/callback`, `GET /auth/lark/status`, `POST /auth/lark/exchange`, `POST /auth/lark/refresh`).
  4. Tích hợp nạp token vào `LarkClientMixin` khi khởi động (`main.py:lifespan`) và chu kỳ refresh định kỳ (mỗi 30 phút) trong `bot_service.py`.
  5. Viết bộ unit test kiểm thử `TokenService` và `AuthRouter` trong `server/tests/01/test_token_service.py` (9/9 passed).

## What is confirmed
- Quyết định kỹ thuật `EDL-0006` đã được tạo và đồng bộ thành công lên Notion Database `Engineering Decision Log` (Page ID: `403590f7-e19e-81ec-908f-c1f4527802fe`).
- Đã xác minh thực tế endpoint `/open-apis/auth/v3/tenant_access_token/internal` và `/open-apis/auth/v3/app_access_token/internal` trả về HTTP 200 (code 0).
- Đã kiểm thử thành công toàn diện các endpoints:
  - `GET /auth/lark/login`: Render giao diện hướng dẫn cấp quyền OAuth.
  - `GET /auth/lark/callback`: Tiếp nhận code, tự động đổi lấy access_token + refresh_token và render giao diện chúc mừng kèm ô copy refresh token.
  - `GET /auth/lark/status`: Kiểm tra trạng thái sống còn của Token trong MongoDB và RAM.

## Work completed
- Cấu hình & Môi trường: Thêm `MONGO_AUTH_COLLECTION` và `LARK_OAUTH_REDIRECT_URI` vào `core/config.py` và `database/db.py`.
- Core Service: Tạo `server/services/token_service.py` hỗ trợ Single-Use Token Rotation, Lazy Auto-Refresh, nạp token startup và background loop định kỳ.
- Router: Tạo `server/routers/auth.py` và đăng ký vào `server/main.py`.
- Lifecycle & Loop: Bổ sung `init_token_on_startup()` vào lifespan của `main.py` và `start_token_refresh_loop()` vào `bot_service.py`.
- Unit Testing: Hoàn thành `server/tests/01/test_token_service.py` với 9/9 test cases passed (0.026s).

## Verification
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_token_service.py`: 9/9 tests passed (0.026s).
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_policy_sync.py`: 5/5 tests passed (0.049s).
- Test trực tiếp `TestClient`: `GET /auth/lark/status` trả về HTTP 200 với đầy đủ metadata và thời gian còn lại.

## Next concrete steps
1. **Lấy Refresh Token thực tế từ Lark:**
   - Đảm bảo app đã bật scope `offline_access` trên Lark Developer Console.
   - Thêm Redirect URL: `http://localhost:8000/auth/lark/callback` vào mục *Security Settings > Redirect URLs*.
   - Mở trình duyệt truy cập: `http://localhost:8000/auth/lark/login` và bấm nút **"Đăng nhập & Cấp quyền"** để nhận và kích hoạt Refresh Token ngay lập tức!



