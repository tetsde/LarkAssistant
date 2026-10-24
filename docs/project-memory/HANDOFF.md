# Current Handoff

> Cập nhật khi kết thúc phiên có công việc đang dở hoặc bàn giao trạng thái sẵn sàng.

## Current task
- **Goal:** Xây dựng Pipeline Đồng bộ Chính sách Tự động từ Lark Base (`tblZphzEZPLQAy24`) sang WeKnora Data Source với cơ chế trích xuất token, chống trùng lặp đa tầng, so sánh diff và webhook real-time.
- **Status:** Completed (Đã triển khai code, viết unit test 5/5 passed, đồng bộ Notion EDL-0005)
- **Scope:** 
  1. Thêm cấu hình `.env` và `core/config.py`: `WEKNORA_POLICY_DATASOURCE_ID`, `POLICY_SYNC_ENABLED`, `POLICY_SYNC_INTERVAL_SECONDS`.
  2. Bổ sung các phương thức quản lý WeKnora Data Source trong `services/weknora.py`: `get_datasource_info`, `update_datasource_resources`, `trigger_datasource_sync`, `get_datasource_sync_status`.
  3. Xây dựng `services/policy_sync_service.py`: trích xuất Lark Token, khử trùng lặp token bằng `set()`, so sánh Diff với `resource_ids` hiện tại của WeKnora, kích hoạt sync an toàn với `asyncio.Lock()`.
  4. Tạo router FastAPI `routers/policy.py` (`GET /policy/status`, `POST /policy/sync`).
  5. Tích hợp triggers: Startup & Periodic loop trong `services/bot_service.py`, phân luồng webhook `drive.file.bitable_record_changed_v1` trong `services/scope_service.py`.
  6. Viết bộ unit test `tests/01/test_policy_sync.py` (5 test cases), đạt 100% pass.

## What is confirmed
- WeKnora Data Source API hỗ trợ danh sách `resource_ids` dạng mảng, cho phép quản lý đồng thời nhiều folder/docs.
- Đã giải quyết triệt để lỗi `99991672`: Chuyển connector sang `lark_drive` (`f2e986fc-9650-473e-84b0-99c2c55cefef`) và cấp scope `drive:export:readonly` trên Lark Developer Platform.
- Cơ chế Diff Checking trong `PolicySyncService` ngăn ngừa 100% các cuộc gọi API và re-sync dư thừa khi danh sách tài liệu trên Base không thay đổi.
- Toàn bộ 5 tài liệu chính sách docx từ thư mục Lark `Vxojf3r33lzu0tdlHX9jd0pUpFd` đã được WeKnora export, chunking và embedding thành công vào KB `[Policy] Hilark Assistant` (`d715d7ee-1853-4bd9-b22d-779b1ec1e28f`).
- Quyết định kiến trúc `EDL-0005` (Pipeline Đồng bộ Policy Tự động) đã được tạo và đồng bộ thành công lên Notion Database `Engineering Decision Log` (Page ID: `403590f7-e19e-8125-8ed3-e2b2eb444f9c`).

## Work completed
- **Cấu hình & Môi trường:** Cập nhật `.env` và `server/core/config.py`.
- **WeKnora Service Client:** Bổ sung 4 methods tương tác Data Source API trong `server/services/weknora.py`.
- **Core Policy Sync Engine:** Hoàn thành `server/services/policy_sync_service.py` với regex bóc tách token (hỗ trợ folder, docx, wiki, file, raw token), deduplication, diff checking, xử lý direct attachments, và `start_policy_sync_loop()`.
- **REST API Endpoints:** Hoàn thành `server/routers/policy.py` và đăng ký vào `server/main.py`.
- **Event-Driven & Lifespan:** Tích hợp kiểm tra `table_id == LARK_BASE_POLICY_TABLE_ID` trong `scope_service.py` và background loop trong `bot_service.py`.
- **Unit Testing:** Hoàn thành `server/tests/01/test_policy_sync.py` với 5/5 tests passed (0.056s).
- **Project Memory & Notion:** Đồng bộ `EDL-0005` lên Notion và cập nhật `DECISIONS.md`.

## Verification
- **Commands actually run:**
  - `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_policy_sync.py`: 5/5 tests passed (0.056s).
  - `PYTHONPATH=server server/.venv/bin/python -m unittest discover -s server/tests/01 -p "test_*.py"`: 84/85 tests passed (3.516s, 1 pre-existing failure in `test_master_digest.py`).
  - Kiểm thử live Data Source WeKnora: `status: active`, `error: None`, `total_items: 5`.
  - Kiểm thử truy xuất RAG live trên KB Policy: Truy vấn *"Sổ tay nhân viên hoặc làm việc từ xa"* trả về 9 chunks chuẩn xác từ cả 5 tài liệu (`01_So_Tay_Nhan_Vien`, `02_Quy_Tac_Ung_Xu`, `03_Chinh_Sach_An_Toan_Thong_Tin_AI`, `04_Quy_Che_Lam_Viec_Tu_Xa`, `05_Cam_Ket_Bao_Mat_NDA_IP`).

## Next concrete steps
1. **Kiểm tra End-to-End Chatbot trên Lark Chat:**
   - Trải nghiệm chat trực tiếp với bot trên nhóm Lark hoặc DM: hỏi thử *"Quy định thử việc ra sao?"*, *"Thời gian làm việc từ xa như thế nào?"* để kiểm chứng luồng trả lời hoàn chỉnh từ RAG Policy.


