# Current Handoff

> Cập nhật khi kết thúc phiên có công việc đang dở hoặc bàn giao trạng thái sẵn sàng.

## Current task
- **Goal:** Xây dựng tính năng Tự động Làm mới Token và Khắc phục lỗi Truy xuất Tri thức Chính sách Công ty (Policy RAG Bug).
- **Status:** Completed (Cả 2 hạng mục Token Auto-Refresh và Policy RAG Bug Fix đều đã hoàn tất và kiểm thử thành công 100%).
- **Scope:**
  1. Xây dựng `LarkTokenService` (`server/services/token_service.py`): Quản lý `access_token`, `refresh_token`, `expires_at`, cơ chế xoay vòng token (rotation) và distributed lock (`asyncio.Lock`).
  2. Lưu trữ trạng thái token bền vững vào MongoDB collection `lark_auth` qua `AsyncIOMotorClient`.
  3. Xây dựng FastAPI Router `server/routers/auth.py` (`GET /auth/lark/login`, `GET /auth/lark/callback`, `GET /auth/lark/status`, `POST /auth/lark/exchange`, `POST /auth/lark/refresh`).
  4. Tích hợp nạp token vào `LarkClientMixin` khi khởi động (`main.py:lifespan`) và chu kỳ refresh định kỳ (mỗi 30 phút) trong `bot_service.py`.
  5. Sửa routing đa kho trong `chat_service.py` tách bạch 3 kho: `project_dataset_id`, `policy_dataset_id` (`WEKNORA_POLICY_DATASET_ID`), và `wiki_dataset_id`.
  6. Miễn trừ nhãn cấm dự án đối với tài liệu chính sách công ty (`is_policy_doc`), giải quyết triệt để lỗi false-positive chunk drop của `RuleEngine`.
  7. Viết bộ kiểm thử chuyên biệt `test_policy_qa.py` và cập nhật các unit test liên quan.

## What is confirmed
- Quyết định kỹ thuật `EDL-0006` và `EDL-0007` đã được ghi nhận và đồng bộ thành công lên Notion Database `Engineering Decision Log`:
  - `EDL-0006`: [Page ID `403590f7-e19e-81ec-908f-c1f4527802fe`](https://app.notion.com/p/EDL-0006-T-ng-L-m-m-i-Lark-User-Token-OAuth2-Single-Use-Refresh-Token-Rotation-MongoDB-Stora-403590f7e19e81ec908fc1f4527802fe)
  - `EDL-0007`: [Page ID `403590f7-e19e-8175-9524-ffcc0fc15288`](https://app.notion.com/p/EDL-0007-nh-tuy-n-RAG-a-kho-Mi-n-tr-Nh-n-c-m-D-n-cho-V-n-b-n-Ch-nh-s-ch-C-ng-ty-403590f7e19e81759524ffcc0fc15288)
- Đã xác minh thực tế endpoint `/open-apis/auth/v3/tenant_access_token/internal` và `/open-apis/auth/v3/app_access_token/internal` trả về HTTP 200 (code 0).
- Đã kiểm thử thành công toàn diện các endpoints OAuth:
  - `GET /auth/lark/login`: Render giao diện hướng dẫn cấp quyền OAuth.
  - `GET /auth/lark/callback`: Tiếp nhận code, tự động đổi lấy access_token + refresh_token và render giao diện chúc mừng kèm ô copy refresh token.
  - `GET /auth/lark/status`: Kiểm tra trạng thái sống còn của Token trong MongoDB và RAM.

## Work completed
- Cấu hình & Môi trường: Thêm `MONGO_AUTH_COLLECTION` và `LARK_OAUTH_REDIRECT_URI` vào `core/config.py` và `database/db.py`.
- Core Service: Tạo `server/services/token_service.py` hỗ trợ Single-Use Token Rotation, Lazy Auto-Refresh, nạp token startup và background loop định kỳ.
- Router: Tạo `server/routers/auth.py` và đăng ký vào `server/main.py`.
- Lifecycle & Loop: Bổ sung `init_token_on_startup()` vào lifespan của `main.py` và `start_token_refresh_loop()` vào `bot_service.py`.
- RAG Routing Fix: Cập nhật `server/services/chat_service.py` phân tầng rõ ràng 3 kho dữ liệu (`project_dataset_id`, `policy_dataset_id`, `wiki_dataset_id`), query đồng thời kho chính sách và kho wiki thay vì dùng toán tử `or`.
- Rule Engine Exemption: Gắn nhãn `is_policy_doc` để bỏ qua bộ lọc `forbidden_labels` của dự án khi context là tài liệu chính sách công ty.
- Unit Testing: Hoàn thành 100% tests cho `token_service`, `policy_sync`, `policy_qa` và `jev_classification`.

## Verification
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_token_service.py`: 9/9 tests passed (0.026s).
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_policy_sync.py`: 5/5 tests passed (0.049s).
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_policy_qa.py`: 1/1 test passed (0.007s).
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_jev_classification.py`: 13/13 tests passed (0.008s).
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_token_ping.py`: 4/4 tests passed (0.001s).

## Next concrete steps
1. Server đang chạy nền (`uv run main.py`) với đầy đủ cơ chế auto-refresh token và RAG fix.
2. Khi người dùng đặt câu hỏi về chính sách (ví dụ: ngày nghỉ phép, bảo hiểm, chế độ đãi ngộ), bot sẽ truy xuất chính xác từ kho chính sách `d715d7ee-...` mà không bị drop bởi nhãn cấm của nhóm dự án.



