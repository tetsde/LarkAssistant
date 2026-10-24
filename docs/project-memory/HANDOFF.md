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

## Verification
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_contextual_claim_gate.py`: 8/8 tests passed (0.007s).
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_policy_qa.py`: 1/1 test passed (0.514s).
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_token_service.py`: 9/9 tests passed (0.026s).
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_jev_classification.py`: 9/9 tests passed (0.392s).
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_policy_sync.py`: 5/5 tests passed (0.048s).
- `PYTHONPATH=server server/.venv/bin/python server/tests/01/test_token_ping.py`: 4/4 tests passed (0.388s).
- Simulation Test Thực tế: Chạy query `@Hoài Nam có cần báo HR không anh?` trả lời chuẩn xác về quy định báo HR từ Sổ tay nhân viên/Quy tắc ứng xử, không còn bất kỳ dấu vết nào của câu đề xuất làm lead ngoài lề.

## Next concrete steps
1. Server chạy ổn định, hệ thống RAG và Memory Claims đã đạt độ sạch tuyệt đối (zero context pollution).
2. Sẵn sàng nhận câu hỏi kiểm thử tiếp theo từ người dùng trong Lark.



