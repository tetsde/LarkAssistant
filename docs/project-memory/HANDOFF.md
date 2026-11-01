# Current Handoff

> Cập nhật khi kết thúc phiên có công việc đang dở hoặc bàn giao trạng thái sẵn sàng.

## Current task
- **Goal:** Kiểm thử và hoàn thiện toàn diện Hệ thống Trợ lý AI theo Đề bài thử việc (9 trang) & Chuẩn bị Môi trường Triển khai Sản xuất (Production-Ready Architecture) cho Anh Hiệp:
  1. **Phase 1: Group Setup, Baseline Docs, Multimodal OCR & Knowledge Alignment:** Đã hoàn thành 100% (10/10 test cases passed).
  2. **Phase 2: Chat Intent, Safety Guardrails & HITL Interactive Governance:** Đã hoàn thành 100% (9/9 test cases passed).
  3. **Phase 3: End-to-End Daily Digest & Management Reporting:** Đã hoàn thành 100% (9/9 test cases passed).
  4. **Phase 4: Hybrid BYOK, Auto-Provision Lark Base & Onboarding Screen Guide:** Đã hoàn thành 100% (18/18 test cases passed).
  5. **Nâng cấp Multi-Provider LLM & Apple Minimalist UI:** Hỗ trợ ChatGPT, Anthropic, Google, và Custom (OpenAI-compatible), timeout tùy chỉnh, base URL tùy biến, Initializing Screen mượt mà và loại bỏ 100% emoji khỏi giao diện.
  6. **Hướng dẫn Tạo Bot & Cấu hình Hạ tầng Nâng cao:** Bổ sung hướng dẫn 2 phút tạo Custom App trên Lark Developer, form nhập và thẩm định trực tiếp cặp App ID & App Secret qua Lark Open Platform, cùng tùy chọn nâng cao kết nối MongoDB riêng của doanh nghiệp.
  7. **Chiến lược Kiến trúc Lark Store App (ISV Multi-Tenant SaaS) & Cụm Server Bảo trợ:** Nhận chỉ đạo và cam kết hạ tầng máy chủ tập trung từ Anh Hiệp ("Cần server anh cấp server"), lập Kế hoạch triển khai toàn diện `IMPLEMENTATION_PLAN_LARK_STORE_ISV_APP.md` cho mô hình SaaS Multi-Tenant (1-Click Install từ Lark App Directory, cô lập dữ liệu `tenant_key`, dynamic ISV token lifecycle).
  8. **Hoàn thành Workstream 1 - Vòng đời Token ISV & Marketplace Auth Engine:** Xây dựng `ISVTokenService`, nhận `app_ticket` qua webhook, cấp mới và cache `app_access_token` và `tenant_access_token` độc lập theo `tenant_key`, Dual-Mode tương thích ngược Custom App (9 TCs passed).
  9. **Hoàn thành Workstream 2 - Cô lập Dữ liệu Multi-Tenant trong MongoDB:** Bổ sung `tenant_key` vào 6 Models cốt lõi (`Entity`, `Fact`, `ChatScopeRecord`, `StagingMessage`, `DailyDigestRecord`, `UserSettingsRecord`), nâng cấp Index Model compound với tiền tố `tenant_key`, xây dựng `TenantScopedCollection` & `scoped_query` engine chống rò rỉ dữ liệu chéo giữa các công ty (6 TCs passed).
  10. **Hoàn thành Workstream 3 - Bộ định tuyến Sự kiện & Client Pool Đa Doanh nghiệp:** Bóc tách `tenant_key` từ Event Header / Sender trong `parse_event`, tự động kích hoạt `TenantContext` trong `_dispatch_to_handlers`, xử lý sự kiện Vòng đời Doanh nghiệp `app_status_change` & `app_uninstalled` qua `tenant_lifecycle_handler`, hỗ trợ `tenant_key` trong các hàm gửi tin `messenger.py` (8 TCs passed).
  11. **Hoàn thành Workstream 4 - Đa Dataset WeKnora & Auto-Provision Bitable theo Doanh nghiệp:** Tự động cấp phát WeKnora Tenant và bộ 2 KB chuẩn (Policy & Wiki Digest), sinh mật khẩu Admin ngẫu nhiên an toàn, bàn giao qua Lark DM và nhúng thông tin trực tiếp vào Screen Guide Onboarding Wizard (Giải pháp B), tự động tạo Lark Base trên Drive doanh nghiệp theo `tenant_key` (10 TCs passed).
- **Status:** WORKSTREAM 4 HOÀN TẤT VÀ KIỂM THỬ 100%. TOÀN BỘ 98/98 TEST CASES PASSED TRONG 2.71S. DỪNG LẠI CHỜ NGƯỜI DÙNG KIỂM TRA TRƯỚC KHI SANG WORKSTREAM 5.

## What is confirmed
- **Toàn bộ 52/52 Unit & Integration Tests Đều Đạt 100% (PASSED):**
  * **Phase 1 (10 TCs):** Xử lý tài liệu đa định dạng, thư mục lồng nhau, nhận diện OCR link DocX/Wiki.
  * **Phase 2 (9 TCs):** Lọc tin rác JEV 0ms, gom tin bàn việc vào Staging, bảo mật vùng cấm ngân sách, Strict HITL nhóm Tuyệt mật, phân quyền Claims, thu hồi tin 4 tầng.
  * **Phase 3 (9 TCs):** Daily Digest 3 nhánh tri thức, Full Provenance & Applink, Context Continuation K-1 sang K, Master Daily Digest đa dự án, duyệt 1-chạm Interactive Card V2, WeKnora Entity-Centric Sync.
  * **BYOK & Screen Guide (18 TCs):** Mã hóa AES-256 Fernet, Masking khóa, Phân cấp khóa 3-Tier, Live Latency Ping test, Stepper Wizard 4 bước, Interactive Card chào mừng, In-App OAuth Popup & PostMessage, Multi-Provider LLM (ChatGPT, Anthropic, Google, Custom), Custom Base URL & Timeout.
  * **Auto-Provisioning Lark Base (6 TCs):** Tự động tạo Bitable qua OpenAPI, cấu hình bảng Chat Scopes & Policies, nạp 3 dự án mẫu, cấp quyền Owner cho Sếp, phân giải động và fallback về `.env`.
- **Hạ tầng Sản xuất Hoàn thiện:**
  * Multi-stage `server/Dockerfile` sử dụng `uv` và user bảo mật `appuser`.
  * `docker-compose.prod.yml` cách ly mạng `hilark-network`, Zero Ingress Attack Surface qua Lark WebSocket.
  * Script triển khai tự động `deploy.sh` 1-click có kiểm tra healthcheck và cấu hình.
  * Tài liệu kiến trúc toàn diện `docs/DEPLOYMENT_GUIDE.md`.

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

- **Tự Động Làm Mới Token Khi Khởi Động & Khắc Phục Lỗi Token Chết / Graceful Bot Fallback**:
  * Khắc phục lỗi hiển thị cảnh báo `EXPIRED` khi bật server và lỗi `20038` (Invalid refresh token):
    - `server/services/token_service.py`:
      * Trong `refresh_user_token()`: Bắt mã lỗi `20038` ("The refresh token passed is invalid. It may have been used"), cập nhật trạng thái `invalid_refresh_token` vào MongoDB.
      * Trong `get_valid_user_token()`: Nếu access token đã hết hạn (`expires_at < now`) và refresh thất bại, trả về `None`, dứt khoát không trả về token đã chết.
      * Trong `init_token_on_startup()`: Tự động dọn dẹp `user_access_token = ""` trong RAM nếu token không hợp lệ, không để token rác gây lỗi API.
      * Trong `start_token_refresh_loop()`: Khởi động vòng lặp kiểm tra token ngay sau 5 giây (thay vì chờ 30 phút), chu kỳ kiểm tra định kỳ 15 phút.
    - `server/services/larkServices/lark_client.py`:
      * Sửa `_get_request_option(as_user=True)`: Kiểm tra đúng `if as_user and self.user_access_token:`.
      * Bổ sung cơ chế **Graceful Fallback sang Bot (Tenant Token)** cho các thao tác đọc tài liệu: `aresolve_wiki_token`, `resolve_wiki_token`, `aget_docx_raw_content`, `get_docx_raw_content`, `adownload_message_resource`, `download_message_resource`, `_get_name_sync`. Khi User Token hỏng hoặc thiếu quyền, tự động gọi lại bằng Bot token giúp hệ thống không bị gián đoạn.
  * Bộ test `test_token_service.py`, `test_doc_parser_service.py`, `test_chat_scope.py`: Toàn bộ **38/38 PASSED 100%**.
- **Nâng Cấp Cột Documents trong Lark Base Hỗ Trợ Link Lark Docs & Wiki (Bitable Document Link Ingestion)**:
  * `server/services/scope_service.py`:
    - Thêm helper `_extract_document_items` và `_sanitize_filename`: Phân loại và trích xuất cả tệp đính kèm nhị phân (PDF, Word, Excel...) lẫn liên kết Lark DocX / Wiki (dạng chuỗi URL, dict `{'link': ..., 'text': ...}` của Bitable Hyperlink field, hoặc list).
    - Cập nhật `sync_group_from_base_record`: Đối với các link Lark DocX / Wiki, gọi `doc_parser_service` để trích xuất Markdown sạch với chi phí 0 token, nạp nội dung dưới dạng file `.md` vào Knowledge Base WeKnora của nhóm chat tương ứng.
    - Cơ chế chống trùng lặp: Tra cứu `knowledge_id` sẵn có trong MongoDB qua `doc_key` hoặc `url`, không gọi lại API WeKnora nếu tài liệu đã tồn tại.
  * `server/tests/01/test_chat_scope.py`: Bổ sung 3 unit tests (`test_extract_document_items_various_formats`, `test_sync_group_from_base_record_with_lark_docx_link`, `test_sync_group_deduplicates_existing_lark_doc`) -> Toàn bộ **18/18 PASSED 100%**.

- **Giai đoạn 1 Tái Cấu Trúc (Phase 1 Refactoring: Database Indexes & Bounded Cache Eviction - EDL-0009)**:
  * Khởi tạo `server/database/indexes.py`: Định nghĩa IndexModel cho 8 collections (`claims`, `memories`, `conversation_staging`, `chat_scopes`, `daily_digests`, `master_daily_digests`, `draft_logs`, `lark_auth`) kèm cơ chế Graceful Fallback đơn lẻ chống OperationFailure.
  * Quản lý vòng đời kết nối `server/database/db.py`: Bổ sung `close_mongo_connections()` đóng an toàn `_async_client` và `_sync_client`, re-export `ensure_database_indexes`.
  * Tích hợp `server/main.py`: Gọi `ensure_database_indexes()` trong startup và `close_mongo_connections()` trong shutdown của `lifespan`.
  * Chống rò rỉ bộ nhớ (Bounded Cache):
    - `server/services/larkServices/lark_messenger.py`: Thêm `_record_sent_message_id` với TTL 600s, max 1,000 items.
    - `server/services/larkServices/lark_client.py`: Nâng cấp `get_user_name` và `_user_name_cache` với TTL 3,600s (1h), max 1,000 users.
  * Bộ test `tests/01/test_phase1_stability.py`: 8/8 tests passed 100%.

- **Giai đoạn 2 Tái Cấu Trúc (Phase 2 Refactoring: Tối Ưu Mạng & Async I/O - EDL-0009)**:
  * Khởi tạo `server/core/http_client.py`: Persistent `httpx.AsyncClient` Connection Pool duy nhất toàn server với cấu hình `max_keepalive_connections=20`, `max_connections=100`, `timeout=30.0s`.
  * Quản lý vòng đời `server/main.py`: Khởi tạo `await init_http_client()` khi startup và `await close_http_client()` khi shutdown của FastAPI lifespan.
  * Tách biệt kiến trúc `server/services/jev.py`: Loại bỏ hoàn toàn `HTTPException` khỏi tầng service, định nghĩa ngoại lệ nội bộ `JEVError(RuntimeError)` để ngăn rò rỉ web layer xuống business logic.
  * Tái sử dụng kết nối mạng & Tương thích ngược:
    - Xây dựng helper `_get_client_session` trong `jev.py`, `weknora.py`, `token_service.py`.
    - Loại bỏ 17 điểm tạo mới ad-hoc `httpx.AsyncClient` rải rác: WeKnora (10 điểm), JEV (3 điểm), TokenService (4 điểm).
    - Tự động nhận diện mock context manager trong môi trường test (`@patch("...httpx.AsyncClient")`), đảm bảo tương thích 100% với các test cũ mà không cần viết lại fixture.
  * Non-blocking Startup I/O `server/services/bot_service.py`: Chuyển các network call đồng bộ lúc startup (`subscribe_events`, `sync_bot_chats`) sang background bootstrap task thông qua `asyncio.to_thread` và `loop.create_task`, đảm bảo server FastAPI phản hồi HTTP healthcheck tức thì (< 0.1s).
  * Viết bộ unit tests `server/tests/01/test_phase2_network_io.py`: 7/7 tests pass 100%.

- **Giai đoạn 3 Tái Cấu Trúc (Phase 3 Refactoring: Tách nhỏ Bot Service & Handlers Decoupling - EDL-0009)**:
  * Tạo package mới `server/services/bot_handlers/`:
    - `document_handler.py`: Xử lý tệp đính kèm nhị phân (Word, PDF, Excel, ảnh) và liên kết Lark DocX/Wiki. Tích hợp dynamic dependency resolution giúp tương thích hoàn toàn với unit test mock.
    - `owner_command_handler.py`: Thụ lý các câu lệnh điều hành trong DM của Chủ nhân (xem/duyệt/hủy Digest, duyệt/sửa/bỏ Draft).
    - `member_message_handler.py`: Nhận diện danh tính người gửi, lưu staging cho Daily Digest và đẩy tin nhắn nhóm vào Smart Debouncer Queue.
  * Tái cấu trúc Facade `server/services/bot_service.py`:
    - Rút gọn file từ 674 dòng xuống ~230 dòng.
    - Hàm `handle_lark_incoming_message` trở thành Root Dispatcher ngắn gọn, phân luồng mạch lạc.
    - Re-export các biến và hàm quan trọng để không phá vỡ bất kỳ interface hay module phụ thuộc nào.
  * Viết bộ unit tests `server/tests/01/test_phase3_bot_handlers.py`: 8/8 tests pass 100%.

## Verification
- Phase 3 Bot Handlers Suite (`tests/01/test_phase3_bot_handlers.py`):
  * Ran 8 tests -> **8/8 PASSED**.
- Phase 2 Network & Async I/O Suite (`tests/01/test_phase2_network_io.py`):
  * Ran 7 tests -> **7/7 PASSED**.
- Phase 1 Stability Test Suite (`tests/01/test_phase1_stability.py`):
  * Ran 8 tests -> **8/8 PASSED**.
- Claims Document Pipeline Suite (`tests/01/test_claims_doc_pipeline.py`):
  * Ran 6 tests -> **6/6 PASSED**.
- JEV Classification & Routing Suite (`tests/01/test_jev_classification.py`):
  * Ran 9 tests -> **9/9 PASSED**.
- WeKnora Thresholds & Retrieval Suite (`tests/01/test_weknora_thresholds.py`):
  * Ran 2 tests -> **2/2 PASSED**.
- Token Service & OAuth Suite (`tests/01/test_token_service.py`):
  * Ran 9 tests -> **9/9 PASSED**.
- Chat Scope & Base Sync Suite (`tests/01/test_chat_scope.py`):
  * Ran 18 tests -> **18/18 PASSED**.
- DocParser Service Unit Test Suite (`tests/01/test_doc_parser_service.py`):
  * Ran 11 tests -> **11/11 PASSED**.
- Contextual Claim Gate Regression Suite (`tests/01/test_contextual_claim_gate.py`):
  * Ran 8 tests -> **8/8 PASSED**.
- Lark Service Unit Test Suite (`tests/01/test_lark_service.py`):
  * Ran 5 tests -> **5/5 PASSED**.
- Memory WeKnora Gating Suite (`tests/01/test_memory_weknora_gating.py`):
  * Ran 5 tests -> **5/5 PASSED**.
- **Tổng kiểm thử regression sau Phase 3:** **96/96 PASSED 100%** (chạy trong 3.36s).
- **Triển khai Mô hình Lark Store ISV SaaS Đa Khách Thuê (EDL-0020)**:
  * **Workstream 1 (Xác thực & Vòng đời Token ISV)**: Hoàn thành `isv_token_service.py`, quản lý dynamic `tenant_access_token` theo `tenant_key`, intercept `app_ticket` webhook event, tương thích ngược 100% (9/9 tests pass).
  * **Workstream 2 (Cô lập Dữ liệu Multi-Tenant trong MongoDB)**: Gắn `tenant_key` trên cả 6 models nghiệp vụ, thiết lập Compound Indexes với tiền tố `tenant_key`, xây dựng `TenantScopedCollection` và `inject_tenant_filter` (6/6 tests pass).
  * **Workstream 3 (Bộ định tuyến Sự kiện & Client Pool Đa Doanh nghiệp)**: Trích xuất `tenant_key` từ webhook header/sender, tự động bao bọc luồng async bằng `async_tenant_context(tenant_key)`, cài đặt lifecycle handler (`app_status_change`, `app_uninstalled`) và mở rộng Messenger API (8/8 tests pass).
  * **Multi-Tenant Claims & Knowledge Isolation Hardening**: Bọc kín toàn diện truy vấn tri thức (`get_all_facts`, `get_all_entities`, `save_extraction_to_mongo`, `get_scope_by_chat_id`), bổ sung lớp Defense-in-depth trong `ContextComposer` (loại bỏ triệt để claims của tenant khác kể cả khi `scope_type="global"`), mở rộng `ChatQueueItem` truyền thông suốt `tenant_key` (6/6 tests pass).
  * **Workstream 4 (Đa Dataset WeKnora & Auto-Provision Bitable theo Doanh nghiệp)**: Cấp phát không gian tri thức 3 tầng (`policy_dataset_id`, `wiki_dataset_id`, `project_dataset_id`), tự động tạo WeKnora Tenant & Admin Credentials (Giải pháp B), bàn giao tài khoản qua Lark DM và hiển thị trực tiếp trên Screen Guide Onboarding Wizard, tự động tạo Lark Base trên Drive khách theo `tenant_key` (10/10 tests pass).
- **Tổng kiểm thử Final Test Suite (ISV Multi-Tenant):** **98/98 PASSED 100%** (chạy trong 2.71s).

## Next concrete steps
1. Báo cáo kết quả hoàn thành Workstream 4 cho Người dùng kiểm tra và nghiệm thu.
2. Chờ phê duyệt của Người dùng trước khi tiến hành **Workstream 5: Thẻ Quản trị Tương tác & Trực quan hóa Vận hành ISV**.








