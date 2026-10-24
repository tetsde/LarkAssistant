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
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_output_sanitizer.py`: 6/6 tests passed (0.003s).
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_policy_sync.py`: 6/6 tests passed (0.053s) (bao gồm cả test case `test_sync_policies_force_no_diff`).
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_contextual_claim_gate.py`: 8/8 tests passed (0.017s).
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_policy_qa.py`: 1/1 test passed (0.514s).
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_token_service.py`: 9/9 tests passed (0.026s).
- Simulation Test Thực tế:
  * Query 1: `@Hoài Nam có cần báo HR không anh?` -> Trả lời plain text thuần túy, không markdown, không lời chào khách sáo, vào thẳng trọng tâm và xưng hô tự nhiên.
  * Query 2: `anh ơi cho em hỏi chính sách nghỉ phép của công ty mình thế nào?` -> Trả lời dạng plain text đánh số 1. 2., không in đậm, không chào khách sáo, xưng anh - em tự nhiên.
  * Sync WeKnora Trigger: Đã test kích hoạt thành công tác vụ sync incremental sang WeKnora với `status: running` và `last_sync_at` được cập nhật chính xác.

## Next concrete steps
1. Hệ thống đã hoàn tất và xác minh 100% toàn bộ các hạng mục: Token Service, Policy RAG Multi-dataset, Contextual Claim Gate, Plain Text Persona & Output Sanitizer, Policy Sync Engine.
2. Chu kỳ sync nền đặt ổn định ở mức 3600s (1 tiếng); khi cần sync tức thì có thể gọi `POST /policy/sync?force=true`.
3. Sẵn sàng tiếp nhận các yêu cầu phát triển hoặc kiểm thử tiếp theo.



