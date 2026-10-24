# Current Handoff

> Cập nhật khi kết thúc phiên có công việc đang dở hoặc bàn giao trạng thái sẵn sàng.

## Current task
- **Goal:** Xây dựng tính năng Tự động Làm mới Token, Khắc phục lỗi Truy xuất Tri thức Chính sách Công ty (Policy RAG Bug), và Triển khai Kiến trúc Contextual Claim Gate (EDL-0008).
- **Status:** Completed (Hoàn tất 100% cả 3 hạng mục; kiểm thử 8/8 tests Contextual Claim Gate passed).
- **Scope:**
  1. Xây dựng `LarkTokenService` (`server/services/token_service.py`): Quản lý `access_token`, `refresh_token`, `expires_at`, cơ chế xoay vòng token (rotation) và distributed lock (`asyncio.Lock`).
  2. Lưu trữ trạng thái token bền vững vào MongoDB collection `lark_auth` qua `AsyncIOMotorClient`.
  3. Xây dựng FastAPI Router `server/routers/auth.py` (`GET /auth/lark/login`, `GET /auth/lark/callback`, `GET /auth/lark/status`, `POST /auth/lark/exchange`, `POST /auth/lark/refresh`).
  4. Sửa routing đa kho trong `chat_service.py` tách bạch 3 kho: `project_dataset_id`, `policy_dataset_id` (`WEKNORA_POLICY_DATASET_ID`), và `wiki_dataset_id`.
  5. Triển khai Kiến trúc Contextual Claim Gate (EDL-0008): Phân tách domain (chặn Project Claims khi hỏi chính sách), thắt chặt `align_claims_with_retriever`, xóa bỏ `Safe Scoped Fallback` mù quáng, cô lập đề xuất cá nhân (`PROPOSED`), chuẩn hóa Persona Prompt và bổ sung Fact Sanitizer trong `llm_extractor.py`.

## What is confirmed
- Quyết định kỹ thuật `EDL-0006`, `EDL-0007` và `EDL-0008` đã được ghi nhận và đồng bộ thành công lên Notion Database `Engineering Decision Log`:
  - `EDL-0006`: [Page ID `403590f7-e19e-81ec-908f-c1f4527802fe`](https://app.notion.com/p/EDL-0006-T-ng-L-m-m-i-Lark-User-Token-OAuth2-Single-Use-Refresh-Token-Rotation-MongoDB-Stora-403590f7e19e81ec908fc1f4527802fe) (Approved)
  - `EDL-0007`: [Page ID `403590f7-e19e-8175-9524-ffcc0fc15288`](https://app.notion.com/p/EDL-0007-nh-tuy-n-RAG-a-kho-Mi-n-tr-Nh-n-c-m-D-n-cho-V-n-b-n-Ch-nh-s-ch-C-ng-ty-403590f7e19e81759524ffcc0fc15288) (Approved)
  - `EDL-0008`: [Page ID `403590f7-e19e-81d7-9957-cd187c3df8fa`](https://app.notion.com/p/EDL-0008-Ki-n-tr-c-Contextual-Claim-Gate-Ki-m-so-t-N-p-Claims-ng-v-Ch-ng-nhi-m-Ng-c-nh-RAG-403590f7e19e81d79957cd187c3df8fa) (Approved)

## Work completed
- Core Service & Router Token: `server/services/token_service.py`, `server/routers/auth.py`.
- RAG Routing Fix: Cập nhật `chat_service.py` phân tầng rõ ràng 3 kho dữ liệu (`project_dataset_id`, `policy_dataset_id`, `wiki_dataset_id`) và miễn trừ `forbidden_labels` cho tài liệu chính sách.
- Contextual Claim Gate (EDL-0008):
  - `server/utils/context_composer.py`: Xóa bỏ Fallback mù quáng, cô lập đề xuất `PROPOSED` khi không được hỏi, lọc bỏ các thực thể generic (`GENERIC_ENTITY_WORDS`), so khớp thuộc tính/từ khóa chuẩn xác.
  - `server/services/chat_service.py`: Thêm `DOMAIN SEPARATION GATE` chặn hoàn toàn Project Claims khi hỏi `COMPANY_POLICY`; điều chỉnh Persona Prompt không tự chêm đề xuất ngoài lề.
  - `server/utils/llm_extractor.py`: Bổ sung Fact Sanitizer và luật cấm bóc tách câu hỏi nghi vấn ("báo ai ạ") và việc riêng ("mai em ốm") thành fact dự án.
  - MongoDB Cleanup: Dọn dẹp 2 claims rác (`fact_371a9d83`, `fact_700d61be`).
- Plain Text & Natural Reply Persona (Phản hồi không Markdown, không chào khách sáo):
  - `server/services/chat_service.py`:
    * Cập nhật `GROUNDED_QA_USER_PERSONA_PROMPT` và `GROUNDED_QA_SYSTEM_PROMPT`: Cấm mở đầu bằng lời chào khách sáo ("Chào [Tên],", "Hi...", "Xin chào,"). Cấm định dạng Markdown (.md) như in đậm (`**`), in nghiêng (`*`), bullet lists (`*`, `-`, `+`), headers (`#`).
    * Bắt buộc trả lời plain text tự nhiên, trực tiếp xưng hô "anh" - "em", reply đúng người hỏi ({user_name}).
    * Đảm bảo `target_user` tự động fallback lấy từ `sender` nếu `user_name` chưa được truyền trực tiếp.
  - `server/utils/text_filter.py`:
    * Thêm hàm `strip_markdown`: Tự động loại bỏ code blocks, inline code, bold, italic, headers, bullet list marks và markdown link tags.
    * Thêm hàm `strip_greetings`: Tự động cắt bỏ lời chào mở đầu khách sáo (nếu LLM vô tình sinh ra), giữ nguyên cách xưng hô tự nhiên trong thân bài ("Phước kiểm tra giúp anh...").
    * Tích hợp vào `clean_output` đảm bảo 2 lớp bảo vệ (Layer 1: Prompt instruction, Layer 2: Sanitizer filter).
- Policy Sync Engine & Lark Drive Incremental Trigger Fix:
  - `server/services/policy_sync_service.py`:
    * Khắc phục cơ chế Diff Check: Khi token thư mục không đổi (`has_diff=False`), hệ thống bỏ qua bước update cấu hình DataSource nhưng **vẫn kích hoạt `trigger_datasource_sync(force=True)`** để WeKnora tự động quét các file mới/sửa đổi từ Lark Drive vào Knowledge Base.
    * Cập nhật background worker `start_policy_sync_loop` gọi sync định kỳ với `force=True`.
  - Cấu hình chu kỳ đồng bộ: Đặt `POLICY_SYNC_INTERVAL_SECONDS = 3600` (1 tiếng) trong cả `.env` và `config.py` để tối ưu tài nguyên, kèm hỗ trợ kích hoạt tức thì qua API `POST /policy/sync?force=true`.

## Verification
- Full Test Suite Execution:
  * `PYTHONPATH=server server/.venv/bin/python -m unittest discover tests/01`: 110 tests (109 passed, 1 failed do chuỗi assertion tiêu đề cũ trong `test_master_digest.py`).
- Rà soát Nợ Kỹ Thuật & Code Smells:
  * Đã hoàn thành quét mã nguồn toàn diện và lập tài liệu: `docs/project-memory/TECHNICAL_DEBT.md` (Điểm đánh giá hệ thống: 6.8/10).
  * Phát hiện 0 database index trên 7 collections MongoDB (nguy cơ COLLSCAN).
  * Phát hiện 2 cache tăng vô hạn gây Memory Leak (`_sent_message_ids`, `_user_name_cache`).
  * Phát hiện 11+ vị trí khởi tạo `httpx.AsyncClient()` rải rác không tái sử dụng TCP/TLS pool.
  * Phát hiện 24 vị trí `except Exception: pass` nuốt lỗi im lặng.

## Next concrete steps
1. **Ưu tiên 1 (Khẩn cấp):** Xử lý nợ Database & Memory Leak (`docs/project-memory/TECHNICAL_DEBT.md` - Phase 1):
   - Tạo hàm `ensure_database_indexes()` trong `database/db.py` đánh index cho cả 7 collections MongoDB lúc startup.
   - Giới hạn kích thước và thêm TTL cho `_sent_message_ids` trong `lark_messenger.py` và `_user_name_cache` trong `lark_client.py`.
2. **Ưu tiên 2 (Hiệu năng):** Thiết lập Shared Persistent `httpx.AsyncClient` cho WeKnora và JEV trong FastAPI lifespan.
3. **Ưu tiên 3 (Clean Code):** Hợp nhất Token Management (`LarkTokenManager`), di dời từ điển tĩnh sang `core/lexicons.py`.
4. **Ưu tiên 4 (Test Tooling):** Bổ sung `pytest.ini` và sửa chuỗi assertion trong `test_master_digest.py` để đạt 110/110 tests pass.




