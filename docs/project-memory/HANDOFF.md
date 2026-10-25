# Current Handoff

> Cập nhật khi kết thúc phiên có công việc đang dở hoặc bàn giao trạng thái sẵn sàng.

## Current task
- **Goal:** Khắc phục lỗi cắt cụt ngữ cảnh Sổ tay Nhân viên (Salary Date Truncation Bug), Thiết kế Kiến trúc Tầng Phân Giải Tài Liệu Đa Phương Tiện (Document Parsing Layer via AnyDoc gRPC & Lark OpenAPI), và Chuẩn hóa Cơ chế Xử lý Xung đột Tri thức (EDL-0010).
- **Status:** Architecture Approved & Documented (Đã phê duyệt và đồng bộ lên Notion EDL-0010; đã sửa xong lỗi cắt cụt ngữ cảnh lương trong `context_composer.py`).
- **Scope:**
  1. Điều tra & Fix Bug Lương: Sửa `max_chunk_chars: int = 16000` trong `server/utils/context_composer.py` đảm bảo không bị cắt cụt tài liệu Sổ tay Nhân viên (`01_So_Tay_Nhan_Vien_Employee_Handbook.docx`).
  2. Brainstorm & Thống nhất Cơ chế Xử lý Xung đột: Giữ nguyên tài liệu gốc (Project Charter) trên WeKnora làm Baseline bất biến; trích xuất các quyết định họp/chốt việc thành Dynamic Claims (MongoDB) làm Overlay; `ContextComposer` hợp nhất với rule `CURRENT Claims > Static WeKnora Documents`.
  3. Thiết kế Tầng Phân Giải Đa Phương Tiện: Tách biệt `doc_parser_service.py` (chuyển đổi PDF, Word, Excel, PPTX, ảnh sang Markdown bằng WeKnora AnyDoc gRPC `WeKnora-docreader:50051`, và Lark Doc URL qua Lark OpenAPI) đứng trước `llm_extractor.py` (chỉ nhận Markdown sạch để bóc tách Claims).
  4. Ghi nhận quyết định kỹ thuật `EDL-0010` lên Notion Engineering Decision Log và cập nhật bộ nhớ dự án (`DECISIONS.md`, `HANDOFF.md`, `PROJECT_CONTEXT.md`).

## What is confirmed
- Quyết định kỹ thuật `EDL-0006`, `EDL-0007`, `EDL-0008`, `EDL-0009` và `EDL-0010` đã được ghi nhận và đồng bộ thành công lên Notion Database `Engineering Decision Log`:
  - `EDL-0006`: [Page ID `403590f7-e19e-81ec-908f-c1f4527802fe`](https://app.notion.com/p/EDL-0006-T-ng-L-m-m-i-Lark-User-Token-OAuth2-Single-Use-Refresh-Token-Rotation-MongoDB-Stora-403590f7e19e81ec908fc1f4527802fe) (Approved)
  - `EDL-0007`: [Page ID `403590f7-e19e-8175-9524-ffcc0fc15288`](https://app.notion.com/p/EDL-0007-nh-tuy-n-RAG-a-kho-Mi-n-tr-Nh-n-c-m-D-n-cho-V-n-b-n-Ch-nh-s-ch-C-ng-ty-403590f7e19e81759524ffcc0fc15288) (Approved)
  - `EDL-0008`: [Page ID `403590f7-e19e-81d7-9957-cd187c3df8fa`](https://app.notion.com/p/EDL-0008-Ki-n-tr-c-Contextual-Claim-Gate-Ki-m-so-t-N-p-Claims-ng-v-Ch-ng-nhi-m-Ng-c-nh-RAG-403590f7e19e81d79957cd187c3df8fa) (Approved)
  - `EDL-0009`: [Page ID `403590f7-e19e-81a3-b443-e08deef4e925`](https://app.notion.com/p/EDL-0009-nh-Gi-Ch-t-L-ng-Codebase-Ph-n-Lo-i-Code-Dirty-v-Chi-n-L-c-Gi-i-Quy-t-N-K-Thu-t-403590f7e19e81a3b443e08deef4e925) (Approved)
  - `EDL-0010`: [Page ID `403590f7-e19e-811a-9a02-cd8ddff7c38b`](https://app.notion.com/p/EDL-0010-Ki-n-tr-c-T-ng-Ph-n-Gi-i-T-i-Li-u-a-Ph-ng-Ti-n-AnyDoc-gRPC-Lark-OpenAPI-Tr-ch-Xu--403590f7e19e811a9a02cd8ddff7c38b) (Approved)

## Work completed
- Khắc phục lỗi cắt cụt ngữ cảnh lương Sổ tay Nhân viên:
  * Phát hiện `01_So_Tay_Nhan_Vien_Employee_Handbook.docx` trên WeKnora chứa đúng ngày 25 ("Ngày 25 hàng tháng" tại ký tự thứ `10,578`).
  * Phát hiện `context_composer.py` hardcode `max_chunk_chars: int = 4000` làm mất toàn bộ đoạn văn từ ký tự 4000 trở đi.
  * Đã nâng giới hạn lên `max_chunk_chars: int = 16000` trong `server/utils/context_composer.py`. Xác minh với Gemini trả về đúng "ngày 25 hàng tháng".
- Ghi nhận Kiến trúc Quyết định `EDL-0010` vào Notion và `DECISIONS.md`.
- **Hoàn tất Giai đoạn 1 (Phase 1: Thiết lập Môi trường & Hạ tầng gRPC - EDL-0010)**:
  * Mở mapping cổng `127.0.0.1:50051:50051` cho service `docreader` trong `WeKnora/docker-compose.yml`, restart container `WeKnora-docreader` thành công.
  * Cập nhật `server/pyproject.toml` bổ sung `grpcio`, `protobuf`, `grpcio-tools`; đồng bộ môi trường bằng `uv sync`.
  * Bổ sung cấu hình `DOCREADER_GRPC_HOST="127.0.0.1"`, `DOCREADER_GRPC_PORT=50051`, `DOCREADER_TIMEOUT_SECONDS=60` vào `server/core/config.py`.
  * Khởi tạo thư mục `server/proto/`, sao chép `docreader.proto` và biên dịch sinh mã Python stubs `docreader_pb2.py`, `docreader_pb2_grpc.py`.
  * Chạy kiểm thử smoke test `test_grpc_smoke.py`: Kết nối thành công tới `WeKnora-docreader:50051`, nhận diện 3 engines (`builtin`, `markitdown`, `opendataloader`) và chuyển đổi văn bản sang Markdown 100% không lỗi.
- **Hoàn tất Giai đoạn 2 (Phase 2: DocReader Service, Lark Client Extension & DocParserService - EDL-0010)**:
  * **Bước 2.1 (Core gRPC Wrapper & Models)**:
    - File Extension Gate: Kiểm tra nghiêm ngặt 17 định dạng tệp hợp lệ (`.docx`, `.pdf`, `.xlsx`, `.pptx`, `.md`, `.txt`, `.png`, `.jpg`...). Chặn sớm các file không hợp lệ (`.exe`, `.zip`, `.py`...).
    - File Size Gate: Giới hạn tệp tối đa 50MB và chặn tệp rỗng 0 bytes.
    - Kênh kết nối gRPC tái sử dụng (`grpc.aio.insecure_channel`) kèm cấu hình buffer 50MB và keepalive tối ưu.
    - Định nghĩa cấu trúc dữ liệu trong `server/models/docreader.py`: `DocReaderResult`, `DocParseResult`, `SUPPORTED_DOCUMENT_EXTENSIONS`, `MAX_FILE_SIZE_BYTES`.
    - Viết bộ kiểm thử `server/tests/01/test_docreader_service.py` (8/8 test cases passed 100% trong 0.096s).
  * **Bước 2.2 & 2.3 (Mở rộng Lark Client & Unified DocParserService)**:
    - Mở rộng `LarkClientMixin` (`server/services/larkServices/lark_client.py`):
      * `adownload_message_resource` / `download_message_resource`: Tải nhị phân tệp/ảnh đính kèm từ Lark IM qua `client.im.v1.message_resource.aget`.
      * `aget_docx_raw_content` / `get_docx_raw_content`: Đọc Markdown sạch từ Lark DocX qua OpenAPI `client.docx.v1.document.araw_content` (0 token cost).
      * `aresolve_wiki_token` / `resolve_wiki_token`: Giải mã node token sang docx token qua Wiki API `client.wiki.v2.space.aget_node`.
    - Xây dựng `server/services/doc_parser_service.py`:
      * Tự động phát hiện URL Lark DocX và Wiki từ văn bản tin nhắn qua Regex (`DOCX_URL_PATTERN`, `WIKI_URL_PATTERN`).
      * Điều phối phân giải: Gọi OpenAPI lấy Markdown đối với link DocX/Wiki; kiểm tra Extension Gate -> tải binary -> gọi AnyDoc gRPC `docreader_service.read()` đối với file đính kèm.
      * Chuẩn hóa đầu ra thành `DocParseResult`.
    - Viết bộ test `server/tests/01/test_doc_parser_service.py` (11/11 test cases passed 100% trong 0.019s).
- **Hoàn tất Giai đoạn 3 (Phase 3: Tích hợp Claims Pipeline & Dispatcher - EDL-0010)**:
  * **Tích hợp Claims Pipeline (`server/services/chat_service.py`)**:
    - Xây dựng `process_document_to_claims`: Nhận `DocParseResult`, gọi `llm_extractor.extract_async(...)` bóc tách Entities và Facts/Claims, bổ sung metadata (`source_doc`, `source_type`, `document_id`), lưu bền vững vào MongoDB với `scope_type="chat"` và `chat_id`.
  * **Tích hợp Bot Dispatcher (`server/services/bot_service.py`)**:
    - Mở rộng `LarkMessage` (`server/models/lark.py`) với các thuộc tính: `file_key`, `file_name`, `image_key`.
    - Bắt sự kiện tệp đính kèm (`msg.message_type in ("file", "image")`): Kiểm tra Extension Gate, gửi thông báo đang đọc, gọi `doc_parser_service.parse_attachment`, nạp Claims vào MongoDB và thông báo kết quả.
    - Bắt sự kiện liên kết Lark DocX / Wiki: Quét regex trong tin nhắn text, gọi OpenAPI lấy Markdown, trích xuất Claims vào MongoDB.
  * **Kiểm thử Unit Test**:
    - Viết `server/tests/01/test_claims_doc_pipeline.py` (6/6 test cases passed 100%).
- **Hoàn tất Giai đoạn 4 (Phase 4: Kiểm thử Mô phỏng Toàn Diện End-to-End - EDL-0010)**:
  * Xây dựng `server/tests/01/test_e2e_document_knowledge_overlay.py` mô phỏng toàn trình:
    1. Parse trực tiếp DOCX qua live gRPC AnyDoc container (`127.0.0.1:50051`) ra Markdown trong 1.5s.
    2. Bóc tách và nạp Claims vào MongoDB có gắn `source_doc="Meeting_Notes_Policy_Update.docx"`.
    3. `ContextComposer` hợp nhất WeKnora Handbook (ngày 25) và Claims động (ngày 28).
    4. Xác minh Grounded QA: Rule `CURRENT Claims > Static WeKnora Documents` đảm bảo thông tin lương trả về ngày 28 và giải thích lịch sử rõ ràng.
  * Tinh chỉnh `server/utils/context_composer.py`:
    - Hỗ trợ `RetrievedChunk` trực tiếp trong `normalize_retriever_data`.
    - Chuẩn hóa đồng nghĩa trạng thái (`accepted`, `active`, `approved` -> `current`) và trích xuất nguồn từ `source_doc`.
    - Điều kiện `auto_align`: Chỉ lọc claims theo query khi query được truyền vào.
- **Tính năng Mới: Duy Trì Mạch Ngữ Cảnh Digest Liên Tục Giữa Các Ngày (Digest Context Continuation)**:
  * Cơ chế: `Digests Ngày K = overview_summary của Ngày K-1 + Dữ liệu Ngày K`.
  * `server/models/digest.py`: Bổ sung `previous_overview_summary`, `previous_digest_date` vào `DailyDigestRecord`, và `previous_executive_summary`, `previous_master_date` vào `MasterDailyDigestRecord`. Render mạch tiếp nối tự nhiên vào `to_weknora_markdown()`.
  * `server/services/digest_service.py`: Thêm `get_previous_digest` & `get_previous_master_digest`, tự động nạp bối cảnh K-1 vào prompt trích xuất LLM để đảm bảo không bị đứt gãy diễn biến công việc, cam kết và blockers giữa các ngày.
  * `server/tests/01/test_digest_continuation.py`: Viết bộ 5 unit test kiểm thử toàn diện tính năng (5/5 tests pass).

- **Tự Động Làm Mới Token Khi Khởi Động (Token Startup Auto-Refresh)**:
  * Khắc phục lỗi hiển thị cảnh báo `EXPIRED` khi bật server: Cập nhật `init_token_on_startup()` trong `server/services/token_service.py` gọi `get_valid_user_token()`, tự động kích hoạt OAuth2 refresh xoay vòng ngay lúc khởi động nếu access token đã hết hạn, nạp token mới vào RAM và MongoDB.
  * Bộ test `test_token_service.py`: 9/9 test cases passed.
- **Nâng Cấp Cột Documents trong Lark Base Hỗ Trợ Link Lark Docs & Wiki (Bitable Document Link Ingestion)**:
  * `server/services/scope_service.py`:
    - Thêm helper `_extract_document_items` và `_sanitize_filename`: Phân loại và trích xuất cả tệp đính kèm nhị phân (PDF, Word, Excel...) lẫn liên kết Lark DocX / Wiki (dạng chuỗi URL, dict `{'link': ..., 'text': ...}` của Bitable Hyperlink field, hoặc list).
    - Cập nhật `sync_group_from_base_record`: Đối với các link Lark DocX / Wiki, gọi `doc_parser_service` để trích xuất Markdown sạch với chi phí 0 token, nạp nội dung dưới dạng file `.md` vào Knowledge Base WeKnora của nhóm chat tương ứng.
    - Cơ chế chống trùng lặp: Tra cứu `knowledge_id` sẵn có trong MongoDB qua `doc_key` hoặc `url`, không gọi lại API WeKnora nếu tài liệu đã tồn tại.
  * `server/tests/01/test_chat_scope.py`: Bổ sung 3 unit tests (`test_extract_document_items_various_formats`, `test_sync_group_from_base_record_with_lark_docx_link`, `test_sync_group_deduplicates_existing_lark_doc`) -> Toàn bộ **18/18 PASSED 100%**.

## Verification
- Context Truncation Fix:
  * Chạy kịch bản mô phỏng kiểm thử sinh câu trả lời với chunk đầy đủ: Gemini trích dẫn chính xác "ngày 25 hàng tháng" từ Sổ tay Nhân viên.
- AnyDoc gRPC Phase 1 Smoke Test:
  * Chạy script `test_grpc_smoke.py`: Kết nối thành công 100%.
- DocReader Service Unit Test Suite (`tests/01/test_docreader_service.py`):
  * Ran 8 tests in 0.096s -> **8/8 PASSED**.
- DocParser Service Unit Test Suite (`tests/01/test_doc_parser_service.py`):
  * Ran 11 tests in 0.019s -> **11/11 PASSED**.
- Claims Doc Pipeline Unit Test Suite (`tests/01/test_claims_doc_pipeline.py`):
  * Ran 6 tests in 5.059s -> **6/6 PASSED**.
- E2E Document Knowledge Overlay Test Suite (`tests/01/test_e2e_document_knowledge_overlay.py`):
  * Ran 4 tests in 1.543s -> **4/4 PASSED**.
- Contextual Claim Gate Regression Suite (`tests/01/test_contextual_claim_gate.py`):
  * Ran 8 tests in 0.007s -> **8/8 PASSED**.
- Digest Continuation Test Suite (`tests/01/test_digest_continuation.py`):
  * Ran 5 tests in 0.021s -> **5/5 PASSED**.
- Chat Scope & Base Sync Suite (`tests/01/test_chat_scope.py`):
  * Ran 18 tests in 2.48s -> **18/18 PASSED**.
- Token Service & OAuth Suite (`tests/01/test_token_service.py`):
  * Ran 9 tests in 2.57s -> **9/9 PASSED**.
- **Tổng kiểm thử hợp nhất toàn bộ hệ thống:** **69/69 PASSED 100%**.

## Next concrete steps
1. Thông báo kết quả nâng cấp cột `Documents` hỗ trợ link Lark Docs/Wiki cho User.
2. Tiếp tục các yêu cầu tiếp theo của User.






