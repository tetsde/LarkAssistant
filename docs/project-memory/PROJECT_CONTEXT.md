# Project Context

> Trạng thái: Verified từ code, config (`server/pyproject.toml`, `server/core/config.py`), tài liệu `README.md` và kiểm thử thực tế.

## 1. Project summary
- **Tên dự án:** HiLark (LarkAssistant)
- **Mục đích:** Hệ thống trợ lý điều hành doanh nghiệp AI thông minh tích hợp sâu nền tảng Lark / Feishu. Xử lý tin nhắn nhóm, tra cứu tri thức RAG, bóc tách ký ức động (Claims) để giải quyết mâu thuẫn dữ liệu thời gian thực, duyệt nháp câu trả lời nhạy cảm (Human-in-the-loop), và tự động tổng hợp báo cáo ngày (Daily Digest).
- **Người dùng / hệ thống phụ thuộc:** Nhân sự, quản lý và ban điều hành trên Lark/Feishu; kết nối Lark Open API, MongoDB, WeKnora (RAG Engine), JEV (System 1 Intent Classifier), Google Gemini API.
- **Trạng thái hiện tại:** Hoạt động dạng modular monolith (`server/`), đang trong giai đoạn phát triển và tối ưu tính năng.

## 2. Tech stack
- **Language/runtime:** Python >= 3.13
- **Frameworks:** FastAPI >= 0.143.0, Uvicorn >= 0.54.0, Pydantic >= 2.14.0
- **Database/storage:** MongoDB Atlas Cloud Cluster & Motor >= 3.7.1 cho async, PyMongo >= 4.18.3 cho sync (13 collections, compound index tenant_key)
- **External services/APIs:**
  - Lark Open Platform (`lark-oapi` >= 1.7.3)
  - WeKnora Hybrid RAG API
  - JEV Intent Classifier API (System 1)
  - Multi-Provider LLM Engine (Google Gemini, OpenAI ChatGPT, Anthropic Claude, Custom OpenAI-Compatible)
- **Build/package manager:** `uv`
- **Libraries hỗ trợ:** `flashtext` (lọc từ khóa cấm), `httpx` (HTTP client), `python-docx`, `reportlab` (xử lý tài liệu), `python-dotenv`

## 3. Architecture
Kiến trúc vận hành 4 lớp tuần tự:
1. **Lớp 1: Cổng sự kiện Lark (Webhook Gateway & Dispatcher):** Nhận toàn bộ sự kiện và tương tác thẻ qua HTTP Webhook (`/api/lark/events`, `/api/lark/card-action` tại `server/routers/lark.py` -> `server/services/lark/messenger.py`), xác thực Verification Token / giải mã AES theo từng Custom App (`server/services/lark/runtime.py`) và lọc trùng/chống loop trước khi đẩy vào `LarkDispatcherMixin`.
2. **Lớp 2: Bộ kiểm soát ý định JEV (System 1 Gatekeeper):** Phản xạ nhanh phân loại ý định người dùng (chào hỏi xã giao, tra cứu Q&A, giao việc, out-of-scope) để ngắt sớm hoặc điều hướng xử lý, tránh lãng phí token LLM.
3. **Lớp 3: Động cơ nhận thức & Giải quyết xung đột tri thức:**
   - **Tầng Phân Giải Đa Phương Tiện (Document Parsing Layer):** Chuẩn hóa file đính kèm (PDF, DOCX, XLSX, PPTX) qua WeKnora AnyDoc gRPC (`WeKnora-docreader:50051`), file hình ảnh (PNG, JPG, JPEG, WEBP) qua LLM Vision Multimodal OCR (`server/services/ai/llm_client.py`), và Lark DocX/Wiki URL qua Lark OpenAPI thành Markdown thuần với 0 token cost cho văn bản và trích xuất cấu trúc bảng/nội dung ảnh hoàn chỉnh, cung cấp đầu vào cho `llm_extractor`.
   - **WeKnora RAG (Baseline Layer):** Tìm kiếm hybrid (vector + BM25 keyword) trên kho tài liệu tĩnh bất biến có phân vùng theo nhóm chat (`chat_scopes`).
   - **MongoDB Claims (Claims Overlay):** Lưu trữ các sự thật mới chốt trong đoạn chat hoặc bóc tách từ tài liệu họp. Cơ chế `ContextComposer` giải quyết xung đột theo nguyên tắc: `CURRENT Claims > Static WeKnora Baseline`.
   - **Quy Trình Ghi Nhận Tri Thức & Gom Nhóm Đề Xuất (Batching Proposed Claims - EDL-0013):** Khi thành viên gửi tài liệu hoặc tin nhắn trao đổi trong ngày, các thông tin bóc tách được lưu tự động ở trạng thái `proposed` trong MongoDB và không gửi thông báo lẻ tẻ làm phiền Lãnh đạo. Chỉ những thông tin do Lãnh đạo phát ngôn mới được gắn cờ `current`. Cuối ngày, toàn bộ đề xuất được gom vào Thẻ báo cáo Master Daily Digest để Lãnh đạo duyệt 1 chạm.
   - **Rule Engine & Contextual Claim Gate:** Lọc bỏ dữ liệu nhạy cảm bằng cơ chế Line-level Redaction (che thông tin cấm mà không làm mất bối cảnh nghiệp vụ) và ngăn chặn ô nhiễm ngữ cảnh chéo domain trước khi đưa vào prompt LLM.
4. **Lớp 4: Cổng thực thi & Phê duyệt (Execution & HITL Gateway):**
   - Trả lời trực tiếp nếu thông tin đầy đủ và an toàn.
   - Cơ chế duyệt nháp (HITL): Gửi bản nháp dạng interactive card vào DM của người duyệt khi thiếu dữ liệu hoặc cần xác nhận.
   - Thẻ Tương Tác Master Daily Digest & Điều Hành (EDL-0013): Tổng hợp toàn bộ hoạt động các nhóm và bảng sự thật đề xuất trong ngày; cung cấp nút bấm 1 chạm `[Duyệt toàn bộ thông tin hôm nay]` (`approve_all_digest_claims`), nút xem chi tiết từng nhóm (`view_digest_detail`), nút nhờ AI tóm tắt ngắn (`summarize_digest`) và hủy báo cáo. Tự động thăng hạng toàn bộ claims sang `current` và đồng bộ WeKnora ngay trên thẻ.
   - Trung Tâm Điều Phối 100% Nút Bấm Thẻ Tương Tác (Executive Control Hub Card V2 - EDL-0023): Thay thế toàn bộ dòng lệnh văn bản bằng Thẻ điều hành tương tác trong DM 1-1, tích hợp 2 hàng nút bấm 1-Click mở Lark Base Quản trị, WeKnora Console, Screen Guide, Báo Cáo Ngày, Trạng Thái Vận Hành và Tài Khoản WeKnora.

## 4. Important code paths
| Area | Path | Responsibility | Evidence / notes |
|---|---|---|---|
| Entry point | `server/main.py` | Khởi tạo FastAPI app, lifespan quản lý bot service, đăng ký routers | Đã xác minh |
| Persistent HTTP Client | `server/core/http_client.py` | Persistent Connection Pool cho WeKnora, JEV, TokenService (EDL-0009) | Đã xác minh qua unit test (7/7 pass) |
| Configuration | `server/core/config.py` | Load `.env` từ repo root, cấu hình MongoDB, Lark, WeKnora, JEV, OpenAI/Anthropic/Gemini & bảng giá/tỷ giá Cost Telemetry (`USD_TO_VND_RATE`, `LLM_*_PRICING_JSON`) | Đã xác minh |
| Lark Webhook Gateway, Bot Runner & Handlers | `server/routers/lark.py`, `server/services/lark/messenger.py`, `server/services/lark/dispatcher.py`, `server/services/lark/bot_runner.py` (facade `server/services/bot_service.py`), `server/services/lark/handlers/` | Tiếp nhận HTTP Webhook multi-tenant, xác thực/giải mã AES, Root Dispatcher & các handlers chuyên biệt: document, owner_command, member_message, card_action, recall, tenant_lifecycle (EDL-0009, EDL-0013, EDL-0072) | Đã xác minh qua unit test |
| Core Chat Orchestration | `server/services/workflows/chat_workflow.py` | Pipeline xử lý tin nhắn, gọi JEV, RAG Scoping, Claims, LLM, duyệt nháp, batching proposed claims (EDL-0010, EDL-0013) | Đã xác minh |
| Intent Classifier (JEV) | `server/services/ai/jev_classifier.py` | Giao tiếp API JEV (`jev-latest`) phân loại ý định/thread & lọc chunks RAG; hỗ trợ JEV BYOK độc lập qua `ai_config_manager.resolve_jev_key()`, per-request headers, `ping_key()`, Fail-Closed `BYOKConfigurationError` (EDL-0009, EDL-0075) | Đã xác minh qua unit test (mock `httpx`) |
| LLM & Telemetry Models | `server/models/llm.py`, `server/models/telemetry.py` | `LLMModelOption`, frozen `LLMRequest`, `LLMUsage` (`thinking_tokens`, `thinking_included_in_output`), `ModelPricing`, `TelemetryRecord` (EDL-0076) | Đã xác minh qua unit test |
| Multi-Provider LLM Engine | `server/services/ai/llm_client.py` | Thay `gemini_client.py` (đã xóa cứng): `LLMClient` với 3 pure payload builders (`_build_google_payload`, `_build_openai_payload`, `_build_anthropic_payload`), Fail-Closed BYOK, đo usage & `@track_llm_cost` (EDL-0076) | Đã xác minh qua unit test (mock `httpx`) |
| Model Catalog | `server/services/ai/model_catalog.py` | Single Source of Truth cho `DEFAULT_GEMINI_MODEL` (`gemini-flash-latest`), `GEMINI_MODEL_SPECS` (`LLMModelOption`) Gemini 2.5 → 3.8 và `normalize_provider` (EDL-0075, EDL-0076) | Đã xác minh qua unit test |
| AI Config Manager & BYOK Facade | `server/services/ai/ai_config_manager.py`, `server/services/user_settings_service.py`, `server/models/user_settings.py` | Nguồn chân lý quản lý AES-256 Fernet (`encrypted_llm_api_key`, `masked_llm_api_key`), RAM cache TTL 60s + invalidation, dọn rác `llm_base_url`/`llm_model`, phân giải Fail-Closed LLM & JEV BYOK; `UserSettingsService` là thin compatibility facade (EDL-0075, EDL-0076) | Đã xác minh qua unit test |
| Onboarding & BYOK Setup UI | `server/routers/onboarding.py`, `server/models/onboarding.py`, `server/templates/onboarding_wizard.html`, `server/templates/setup_one_click.html`, `server/services/setup/one_click_setup_service.py` | API `/onboarding/api/models`, `/api/test-key`, `/api/save` (`raw_llm_key`, HTTP 400 trên `BYOKConfigurationError`); dropdown Gemini 2.5 → 3.8 + `__custom__`, cấu hình & Test Key JEV BYOK riêng; bảo vệ re-run Setup không ghi đè BYOK (EDL-0075, EDL-0076) | Đã xác minh FastAPI TestClient & HTML template (chưa E2E Webview thật) |
| Hybrid RAG Client | `server/services/knowledge/weknora_client.py` | Tìm kiếm ngữ nghĩa/từ khóa trên WeKnora dataset, scoped knowledge_ids isolation | Đã xác minh qua test thực tế |
| Context Composer | `server/services/knowledge/context_composer.py` | Hợp nhất RAG chunks + Claims, ưu tiên Claims mới hơn tài liệu | Đã xác minh qua unit test (6/6 pass) |
| Document Parsing Layer & OCR | `server/services/knowledge/doc_parser.py`, `server/services/ai/llm_client.py` | Chuyển đổi file đính kèm, Lark Doc URL và hình ảnh qua Multimodal Vision OCR (`llm_vision_ocr`, `ai_config_manager.resolve_llm_client` theo `tenant_key`, Fail-Closed BYOK) sang Markdown (EDL-0010, EDL-0013, EDL-0074, EDL-0075, EDL-0076) | Đã xác minh qua unit test |
| AnyDoc gRPC Client | `server/services/knowledge/docreader_client.py` | Kết nối `WeKnora-docreader:50051` parse nhị phân sang Markdown | Đã xác minh qua unit test (8/8 pass) |
| Rule Engine | `server/services/knowledge/rule_engine.py` | Line-level Redaction & Kiểm duyệt từ khóa nhạy cảm trên Chunks và Claims | Đã xác minh qua unit test (7/7 pass) |
| Daily Digest & Staging | `server/services/workflows/digest_workflow.py` | Lưu staging tin nhắn, tổng hợp digest ngày, xuất Thẻ báo cáo tương tác | Đã xác minh |
| Chat Scope Isolation | `server/services/knowledge/chat_scopes.py` | Quản lý quyền truy cập dataset và dữ liệu theo chat_id | Đã xác minh qua unit test |
| Draft Approval (HITL) | `server/services/workflows/draft_workflow.py` | Quản lý vòng đời bản nháp (Pending, Approved, Rejected) | Đã xác minh |
| Interactive Card Builder | `server/services/lark/card_builder.py` | Dựng các Thẻ tin nhắn tương tác chuẩn Lark (Draft, Claim, Master Digest tổng hợp chi phí đa provider + `thinking_tokens` và nút 1 chạm) (EDL-0012, EDL-0013, EDL-0076) | Đã xác minh qua unit test |
| AI Draft Rewriter | `server/services/ai/draft_rewriter.py` | LLM viết lại bản nháp theo chỉ đạo Lãnh đạo, làm sạch icon/emoji (EDL-0012) | Đã xác minh |
| Claim Workflow & Service | `server/services/workflows/claim_workflow.py`, `server/services/claim_service.py` | Quản lý vòng đời Claims, truy vấn claims chờ duyệt theo ngày và thăng hạng hàng loạt (EDL-0012, EDL-0013) | Đã xác minh qua unit test (9/9 pass) |
| Card Action Handler | `server/services/lark/handlers/card_action_handler.py` | Xử lý sự kiện bấm nút trên Thẻ tương tác (`approve_all_digest_claims`, `view_digest_detail`, `view_master_digest`, draft actions) và cập nhật thẻ tại chỗ (EDL-0012, EDL-0013) | Đã xác minh qua unit test (12/12 pass) |
| Cost Telemetry Decorators | `server/decorators/` (`cost_telemetry.py`) | Đo lường chi phí, token (`prompt_tokens`, `output_tokens`, `thinking_tokens` chống double-counting), latency qua `calculate_llm_cost` đọc từ `.env` cho đa provider (`google`, `openai`, `anthropic`, `custom`, `jev`), kèm `tenant_key`, `provider`, `is_byok` (EDL-0014, EDL-0075, EDL-0076) | Đã xác minh qua unit test |
| Token Loop | `server/core/token_loop.py` | MỘT daemon thread + MỘT event loop cho mọi việc lấy token; `submit()` cho caller sync, `asubmit()` cho caller async, dừng trong lifespan shutdown. Sửa deadlock cross-loop của `asyncio.run()` + `asyncio.Lock` | `tests/auth/test_token_loop_concurrency.py` (T1) |
| Tenant/Token Errors | `server/core/tenant_errors.py` | Exception có kiểu, tự mang `error_code` + `http_status`: `TenantContextMissing` 400, `BYOKConfigurationError` 400 (`byok_config_error`), `TenantNotFound`/`TenantNotReady`/`TenantConfigIncomplete`/`AppCredentialMissing` 409, `UserTokenMissing` 401, `TokenUnavailable` 503. Handler đăng ký một lần ở `main.py` | `tests/final_test/test_tenant_error_http_mapping.py`, `tests/final_test/test_ai_config_and_jev_byok.py` |
| TokenBroker (EDL-0070, thay TenantTokenManager EDL-0068) | `server/services/auth/tenant_token_manager.py` | `get/get_sync/invalidate`, cache key **3 chiều** `(tenant_key, app_id, kind)`, single-flight theo key + double-check, buffer hết hạn 300s, provider không cache/không fallback, **không bao giờ trả `""`** | `tests/auth/test_token_broker.py` (T3/T4) |
| TenantResourceResolver | `server/services/tenancy/tenant_resolver.py` | Chỗ duy nhất trả `TenantResources` theo hợp đồng 6 bước fail-closed; cache RAM 60s + `invalidate()`; `resolve_credentials()` là lối vào của tầng token; `resolve_current()` theo ContextVar | `tests/tenancy/test_tenant_resolver.py` (T7/T8/C1) |
| Tenant State Machine & Invalidation Hub | `server/services/tenancy/tenant_state.py` | Nơi duy nhất đổi `tenants.status`; `mark_ready()` chạy kiểm tra resolver trước khi set `ready`; mọi chuyển trạng thái + `register_app` + `link_tenant` vô hiệu cache resolver + broker | `tests/tenancy/test_tenant_state_machine.py` |
| OAuth State Registry | `server/services/auth/oauth_state_service.py` | Collection `oauth_states`: state do server phát hành, dùng **một lần** (`find_one_and_update`), gắn `(tenant_key, app_id, purpose)`, TTL index 10 phút | `tests/auth/test_oauth_state_service.py` |
| Tenant Refresh Sweeper | `server/services/auth/tenant_refresh_sweeper.py` | Thay `start_token_refresh_loop()`: mỗi 10 phút duyệt `tenants` có `status="ready"` và gọi `token_broker.get(tk, "user")`; lỗi chỉ log, không dừng vòng | `tests/auth/test_tenant_refresh_sweeper.py` |
| Friendly Tenant Errors (chat) | `server/services/lark/tenant_error_reply.py` | Dịch lỗi có kiểu thành tin nhắn trong chat (`chưa hoàn tất cài đặt` / `cần uỷ quyền lại` / `BYOK_CONFIG_ERROR_REPLY`); không bao giờ raise | `tests/lark/test_tenant_error_reply.py`, `tests/final_test/test_ai_config_and_jev_byok.py` |
| Token Service | `server/services/auth/token_service.py` | Lark OAuth user token refresh via MongoDB, guarded by IS_ISV_MODE to disable legacy fallback in multi-tenant production | Updated WS5 with IS_ISV_MODE guards at lines ~605, ~720 (126/128 tests pass) |
| ISV Service | `server/services/auth/isv_token_service.py` | Bot/ISV tenant_access_token lifecycle management, per-tenant isolation | 9 integration tests (9/9 pass) |
| Schema Migration Script | `scripts/migrate_llm_schema.py` | Backfill `user_settings` (`*_gemini_api_key` -> `*_llm_api_key`) & `cost_telemetry` (`candidates_tokens` -> `output_tokens`, `service='gemini'` -> `'google'`); `--dry-run` mặc định, `--apply` `$unset` field cũ trừ `--keep-legacy` | Pass CLI `--help` & unit tests `FakeSyncDB` |
| Test suite | `server/tests/01/` & `server/tests/` | Bộ kiểm thử chức năng, OCR, modular services, interactive cards, telemetry (`.env` pricing & `thinking_tokens`), schema migration, tenancy, AI Config & BYOK và hồi quy toàn diện | `pytest tests -q` → **348 passed, 4 warnings** (2026-11-09, DB test `LarkAssistant_test`, external HTTP mocked) |

## 5. Contracts and constraints
- **Lark API:** Dùng `lark-oapi` (API client + `EventDispatcherHandler`) qua HTTP Webhook Gateway (`/api/lark/events`, `/api/lark/card-action`, cùng biến thể path-based `/{app_id}`); đã gỡ bỏ hoàn toàn chế độ WebSocket và DM Polling.
- **Quy tắc giải quyết xung đột:** Sự thật (Claim) có hiệu lực mới nhất trong nhóm chat luôn được ưu tiên cao hơn tài liệu tĩnh từ WeKnora.
- **RAG Hard Isolation:** Dataset truy xuất phải được giới hạn chặt chẽ theo `chat_id` và quyền của người dùng; cấm truy xuất chéo nhóm trái phép.
- **AI Config, Model Default, Provider-Agnostic Schema & Fail-Closed BYOK (`EDL-0075`, `EDL-0076`):**
  - Model Google Gemini mặc định toàn hệ thống là `gemini-flash-latest` (khai báo duy nhất tại `server/services/ai/model_catalog.py` dưới dạng `LLMModelOption`); UI cung cấp dropdown từ Gemini `2.5` → `3.8` + `__custom__`. Không dùng heuristic đoán mò theo tên model để tự ép `thinkingConfig` hoặc `thinking_budget`.
  - Schema runtime & MongoDB chuẩn hóa về `encrypted_llm_api_key`, `masked_llm_api_key`, `raw_llm_key`, `output_tokens`, `thinking_tokens`, `service="google"`, sử dụng pure per-provider payload builders trên `LLMClient` (`server/services/ai/llm_client.py`) với `LLMRequest`/`LLMUsage` từ `server/models/llm.py`.
  - Bảng giá, tỷ giá USD->VND và chi phí JEV được cấu hình qua `.env` (`server/core/config.py`), tra cứu theo độ ưu tiên `provider/model` -> exact -> longest-prefix -> provider default -> global default, chống double-count `reasoning_tokens` / `thinking_tokens`.
  - Toàn bộ đọc/lưu/mã hóa/phân giải LLM & JEV BYOK đi qua `ai_config_manager` (`server/services/ai/ai_config_manager.py`, RAM cache TTL 60s + auto-invalidate khi save); khi đổi provider hoặc xóa rỗng trên UI phải dọn `llm_base_url`/`llm_model`.
  - `.env` System Key (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `JEV_API_KEY`) **chỉ** dùng khi user không bật BYOK (`is_byok_enabled=False` / `is_jev_byok_enabled=False`). Khi BYOK bật mà thiếu/lỗi giải mã key, bị từ chối `401`/`403`/`400-auth`, hoặc toàn bộ model `400`/`404` -> phải raise `BYOKConfigurationError` (HTTP 400 / chat `BYOK_CONFIG_ERROR_REPLY`), không fallback về `.env`, `chat_scope` key, `request_api_key`, WeKnora Chat hay `FAST_APPROVE_SET`.
  - `OneClickSetupService` bảo toàn cấu hình BYOK/JEV/Digest nếu `user_settings` của `(admin_open_id, tenant_key)` đã tồn tại.
- **Tra cứu có hợp đồng (EDL-0070, supersede một phần EDL-0068):** thiếu dữ liệu luôn là exception có kiểu, **không bao giờ** có giá trị thay thế. Cấm `or settings.*`, cấm "App/tenant bất kỳ trong DB", cấm trả `""` khi token lỗi. `.env` không còn là nguồn cấu hình tenant, kể cả dev — dev tạo tenant qua luồng setup như production.
- **Token & App identity:** mọi truy cập token đi qua `token_broker` (chạy trên token loop riêng) với cache key `(tenant_key, app_id, kind)`; mọi tài nguyên Base/WeKnora đi qua `tenant_resolver` (cache 60s). `LarkBaseService` không còn là singleton bị ghi đè: dùng `for_tenant()/for_policy_table()`, instance không tenant phải raise `TenantContextMissing`.
- **OAuth:** `/auth/lark/login` bắt buộc `tenant_key`; `state` do server phát hành và dùng một lần, gắn `(tenant_key, app_id, purpose)`; `exchange_code_for_token` bắt buộc `app_id + app_secret + expected_tenant_key` và từ chối profile thuộc tenant khác. Không còn document danh tính dùng chung `primary_user_token`.
- **Vòng đời tenant:** `status` chỉ đổi qua `tenant_state` (provisioning → ready | provisioning_failed; ready → inactive | uninstalled; start lại từ `inactive` **không** provision lại). UI setup có nút **"Thử lại"** cho tenant `provisioning_failed`.
- **Refresh sweeper:** chỉ an toàn với **1 container / 1 uvicorn worker** (cache RAM). Nếu scale ≥ 2 replica phải thêm lease Mongo cho `refresh_token` trước khi bật sweeper.
- **Human-in-the-Loop:** Khi độ tin cậy thấp hoặc thông tin nhạy cảm, bot không trả lời công khai mà gửi nháp kèm nút bấm duyệt qua DM cá nhân.
- **Lịch sử (superseded một phần bởi EDL-0070) — Token Management (WS1-WS6, EDL-0068):** Multi-tenant centralized token orchestration via `TenantTokenManager` singleton. Per-tenant caching + per-tenant asyncio.Lock to eliminate scattered refresh logic and zero `.env` fallback in production. Preemptive refresh with 300s buffer before expiry; bot token via `isv_token_service` delegation, user token via `token_service` delegation. **Hai điểm không còn đúng:** cache chỉ 2 chiều `(tenant_key, token_type)` (nay là `(tenant_key, app_id, kind)`), và "single-tenant dev vẫn dùng `.env`" (nay fail-closed cho mọi môi trường).

## 6. Developer workflow
- **Setup môi trường:**
  ```bash
  cd server
  uv venv
  uv sync
  ```
- **Chạy server (Dev mode):**
  ```bash
  cd server
  PYTHONPATH=. .venv/bin/python main.py
  # Hoặc: uv run uvicorn main:app --reload
  ```
- **Chạy kiểm thử:**
  ```bash
  cd server
  PYTHONPATH=. .venv/bin/python -m unittest discover -s tests/01 -p "test_*.py"
  ```

## 7. Important decisions
Liên kết tới `docs/project-memory/DECISIONS.md` và Notion Database `Engineering Decision Log` (ID: `402590f7-e19e-80cd-8873-f3b12a9a0a72`).

## 8. Known issues and unknowns
- **Resolved issues:**
  1. `access_token_user`: Đã giải quyết triệt để qua `EDL-0006` (hệ thống tự động xoay vòng refresh token và lưu trữ bền vững MongoDB).
  2. `Contextual Claim Gate`: Đã giải quyết triệt để qua `EDL-0008` (cô lập đề xuất proposed và phân tách domain).
  3. `Policy Sync Diff Guard`: Đã khắc phục việc WeKnora không kéo tệp từ Lark Drive định kỳ khi token folder giữ nguyên.
  4. `test_master_digest_dm_text_format`: Đã đồng bộ tiêu đề hiển thị chuẩn hóa, 100% test suites pass.
- **Verified issues:** Hiện không có issue nào đang tồn đọng trên bộ test.
- **Open questions:**
  - Kế hoạch triển khai Docker/Container hóa cho môi trường Production.
- **Assumptions requiring confirmation:**
  - Giả định MongoDB cục bộ hoặc cloud URI đã sẵn sàng khi chạy bot service thực tế.

## 9. Last verified
- **Date:** 2026-11-09 (Loại bỏ hoàn toàn legacy WebSocket & DM Polling, giữ nguyên HTTP Webhook Gateway multi-tenant)
- **What was checked:**
  1. Đã xóa `server/services/lark/runner.py`, `server/services/larkServices/lark_runner.py`, bỏ `ENABLE_LARK_WEBSOCKET` / `ENABLE_DM_POLLING` / `DM_POLL_INTERVAL`, gỡ bỏ `start_bitable_ws_listener` / `--listen`, `parse_list_message_item`, `_ws_thread`, `run_standalone_bot` và cập nhật docs/deploy sang HTTP Webhook Gateway.
  2. Biên dịch bytecode: `python3 -m compileall -q server/core server/database server/decorators server/models server/routers server/services server/tests scripts` → **exit code 0**.
  3. Quét mã nguồn, scripts, deploy configs & tài liệu (loại `.venv`, `uv.lock`, `WeKnora`, `docs/project-memory` lịch sử) → **0** tham chiếu WebSocket / DM Polling còn sót.
  4. Full regression suite: `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 .venv/bin/python -m pytest tests/ -q` → **348 passed, 4 warnings in 7.62s** (2 cảnh báo `DeprecationWarning` từ `lark_oapi/ws/...` là import nội bộ của package `lark-oapi`, không từ mã HiLark).
- **By / source:** Antigravity Agent (nhánh `main`, chưa commit).

### Lịch sử trước đó: 2026-11-09 (`EDL-0076` — Refactor `LLMClient` đa provider, chuẩn hóa Models & Schema MongoDB, đưa Cost Telemetry ra `.env` và đo `thinking_tokens`)
- **What was checked:**
  1. Biên dịch bytecode: `python3 -m compileall -q server/core server/database server/decorators server/models server/routers server/services server/tests scripts` → **exit code 0**.
  2. Quét ký hiệu cũ (`gemini_client`, `GeminiClient`, `encrypted_gemini_api_key`, `masked_gemini_api_key`, `candidates_tokens`, `raw_gemini_key`, `test_gemini_key`, `_call_gemini`, `calculate_gemini_cost`, `thinking_budget`, `is_gemini_3_or_newer`, `is_gemini_25_pro`, `_apply_gemini_thinking_config`) trong runtime `server/` (loại `__pycache__`, `tests`, `docs`, `.venv`, `.pytest_cache`) → **0 kết quả còn sót**; đã xóa cứng `server/services/ai/gemini_client.py`.
  3. Test suites trọng tâm (Step 6A + 6B, gồm `test_byok_onboarding.py`, `test_ai_config_and_jev_byok.py`, `test_phase_3_daily_digest_reporting.py`, `test_card_builder_schema.py`): **107 passed, 2 warnings in 2.76s**.
  4. Full regression suite: `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 /Users/hoainam/Desktop/HiLark/server/.venv/bin/python -m pytest tests -q` → **348 passed, 4 warnings in 7.21s** (trên **MongoDB local** `LarkAssistant_test`).
  5. Migration CLI: `/Users/hoainam/Desktop/HiLark/server/.venv/bin/python scripts/migrate_llm_schema.py --help` → **exit code 0**; `--dry-run`, `--apply` (`$unset`), `--apply --keep-legacy` pass trên `FakeSyncDB`.
  6. Notion sync: đã tạo và xác minh qua `API-retrieve-a-page` cho [EDL-0076](https://app.notion.com/p/EDL-0076-Refactor-LLMClient-a-provider-chu-n-h-a-Models-Schema-MongoDB-a-Cost-Telemetry-ra--413590f7e19e814cb219c7328239f002).
- **Chưa verify live (Assumption / Scope Boundary):**
  - Toàn bộ HTTP calls tới Google Gemini, OpenAI, Anthropic và JEV System 1 trong pytest đều mock qua `httpx`; **chưa** chạy live paid API calls tới các endpoint thật ngoài Internet.
  - **Chưa** chạy `scripts/migrate_llm_schema.py --apply` trên MongoDB Atlas production hay thao tác click E2E trực tiếp bên trong Lark Webview modal thật.
- **By / source:** Antigravity Agent (Step 1–6 trên nhánh `main`, chưa commit, chưa deploy).

### Lịch sử trước đó: 2026-11-09 (`EDL-0075` — Unified Fail-Closed BYOK, AI Config Manager, Mặc định `gemini-flash-latest` & JEV BYOK)
- **What was checked:**
  1. Biên dịch bytecode: `cd server && python3 -m compileall -q core database decorators models routers services tests/final_test/test_ai_config_and_jev_byok.py tests/final_test/test_byok_onboarding.py` → **exit code 0**.
  2. Test Onboarding & BYOK UI (Step 6A): `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 .venv/bin/python -m pytest tests/final_test/test_byok_onboarding.py -v` → **33 passed**.
  3. Test Unified AI Config, Model Catalog, Multi-Provider Engine & JEV BYOK (Step 6B): `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 .venv/bin/python -m pytest tests/final_test/test_ai_config_and_jev_byok.py -v` → **55 passed, 0 failed, 2 warnings in 2.86s**.
  4. Full regression suite: `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 .venv/bin/python -m pytest tests -q` → **342 passed, 4 warnings in 7.02s** (trên **MongoDB local** `LarkAssistant_test`).
  5. Kiểm tra runtime default cũ `gemini-2.5-flash` trong `server/`: chỉ còn nằm có chủ đích trong danh sách dropdown catalog (`model_catalog.py`, `onboarding_wizard.html`, `setup_one_click.html`).
  6. Notion sync: đã tạo và xác minh qua `API-retrieve-a-page` & `API-get-block-children` cho [EDL-0075](https://app.notion.com/p/EDL-0075-Unified-Fail-Closed-BYOK-AI-Config-Manager-t-p-trung-M-c-nh-gemini-flash-latest-JEV--413590f7e19e814f8786ca5ca1b1c737).
- **Chưa verify live (Assumption / Scope Boundary):**
  - Toàn bộ HTTP calls tới Google Gemini (`3.8`/`2.5`/`flash-latest`), OpenAI, Anthropic và JEV System 1 trong pytest đều được mock qua `httpx`; **chưa** chạy live paid API calls tới các endpoint thật ngoài Internet.
  - **Chưa** chạy smoke test trên MongoDB Atlas production hay thao tác click E2E trực tiếp bên trong Lark Webview modal thật.
- **By / source:** Antigravity Agent (Step 1–6 trên nhánh `main`, chưa commit, chưa deploy).

### Lịch sử trước đó: 2026-11-02 (EDL-0070 / WS8 — Tenant Resolution & Token Flow)
- **What was checked:** Kiến trúc "tra cứu có hợp đồng" sau GĐ5 + GĐ6:
  1. `import main` chạy sạch; `app.exception_handlers` gồm `TenantResolutionError`, `TokenUnavailable`, `OAuthStateError`; `compileall core services routers database models` exit 0.
  2. Full regression: `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 .venv/bin/python -m pytest tests -q` → **250 passed, 3 warnings in 25.04s** (baseline GĐ0: 117 passed / 11 failed / 37 errors).
  3. Test mới theo từng mục của Test Plan: T1 (token loop), T3/T4 (broker), T7/T8/C1 (resolver), Sentinel (`.env` không leak), C3 (Base isolation), T5/T6 (OAuth login/exchange + `oauth_states`), GĐ5 (state machine, sweeper, lỗi chat + lỗi HTTP), owner open_id theo tenant.
  4. `scripts/audit_tenant_config_readonly.py` (mục 9: state machine + `app_id` khớp) và `scripts/cleanup_test_tenant.py` (`--dry-run` mặc định; `--apply` xoá 6 document trên DB seed local, còn 0) — verify trên **MongoDB local**.
  5. `docker compose --env-file /tmp/empty.env -f docker-compose.prod.yml config` → EXIT=1 (`required variable MONGO_URL is missing a value`): container fail khi thiếu secret thay vì mượn credential trong file.
- **Chưa verify:** Atlas thật (máy dev bị `SSL: TLSV1_ALERT_INTERNAL_ERROR`), deploy production, E2E hai tenant song song trên môi trường thật, đồng bộ Notion (không có Notion MCP).
- **By / source:** Qoder agent (WS8, nhánh `fix/tenant-resolution-token`, chưa commit).

### Lịch sử (superseded một phần bởi EDL-0070): WS1-WS6 centralized token management (2026-11-02)
- **What was checked:** Refactor EDL-0068 theo từng bước WS1–WS6:
  1. **WS1:** `TenantTokenManager` singleton (650 lines) with per-tenant cache + asyncio.Lock, zero .env fallback design.
  2. **WS2:** 30 unit tests covering cache hits/misses, expiry, concurrency, error recovery, lock creation (30/30 PASSED).
  3. **WS3:** Refactored `bitable.py` service layer (-50 lines, 41/41 tests PASSED) to use centralized TenantTokenManager.
  4. **WS4:** Refactored `client.py` Lark client builder (-57 lines, 39/39 tests PASSED) to use centralized token manager.
  5. **WS5:** Removed .env fallback paths via IS_ISV_MODE guards in `token_service.py` (126/128 tests PASSED). Production (IS_ISV_MODE=True) blocks legacy PRIMARY_TOKEN_DOC_ID fallback; single-tenant (IS_ISV_MODE=False) retains backward compatibility.
  6. **WS6:** E2E integration tests (7 test suites, 7/7 PASSED) covering multi-tenant isolation, concurrent access, cache persistence, bot/user token isolation, error recovery, service delegation parameters, monitoring stats.
  7. **Full test suite:** 46/46 tests pass (30 unit + 7 integration + 9 final ISV tests) with zero regressions.
- **Bằng chứng đã thay đổi từ WS8:** cache chỉ 2 chiều `(tenant_key, token_type)` → nay 3 chiều `(tenant_key, app_id, kind)`; "single-tenant retains backward compatibility" (`.env`) → nhánh đó đã bị xoá; hai file `tests/auth/test_tenant_token_manager*.py` ở trên → đã xoá, thay bằng `test_token_broker.py` + `tests/tenancy/test_tenant_resolver.py`.
- **By / source:** Antigravity Agent (WS1-WS6).

### Multi-Custom-App deployment note (2026-11-01)
HiLark is being migrated from the legacy single `.env` Lark App to a shared-server model where each customer registers its own Custom App. The current implementation has a tenant-aware credential registry and per-App runtime client foundation; the legacy singleton remains only as a backward-compatible fallback. See `docs/IMPLEMENTATION_PLAN_MULTI_CUSTOM_APP.md` and decision `EDL-0041` for the rollout boundary and remaining hardening work.
