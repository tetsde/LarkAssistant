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
1. **Lớp 1: Cổng sự kiện Lark (Gateway & Dispatcher):** Nhận tin nhắn/sự kiện qua WebSocket (`services/bot_service.py`) hoặc Webhook HTTP, lọc trùng tin nhắn (deduplication).
2. **Lớp 2: Bộ kiểm soát ý định JEV (System 1 Gatekeeper):** Phản xạ nhanh phân loại ý định người dùng (chào hỏi xã giao, tra cứu Q&A, giao việc, out-of-scope) để ngắt sớm hoặc điều hướng xử lý, tránh lãng phí token LLM.
3. **Lớp 3: Động cơ nhận thức & Giải quyết xung đột tri thức:**
   - **Tầng Phân Giải Đa Phương Tiện (Document Parsing Layer):** Chuẩn hóa file đính kèm (PDF, DOCX, XLSX, PPTX) qua WeKnora AnyDoc gRPC (`WeKnora-docreader:50051`), file hình ảnh (PNG, JPG, JPEG, WEBP) qua Gemini Vision Multimodal OCR (`gemini_client.py`), và Lark DocX/Wiki URL qua Lark OpenAPI thành Markdown thuần với 0 token cost cho văn bản và trích xuất cấu trúc bảng/nội dung ảnh hoàn chỉnh, cung cấp đầu vào cho `llm_extractor`.
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
| Configuration | `server/core/config.py` | Load `.env` từ repo root, cấu hình MongoDB, Lark, WeKnora, JEV, Gemini | Đã xác minh |
| Lark Bot Service & Handlers | `server/services/bot_service.py`, `server/services/lark/handlers/` | Root Dispatcher Facade & tách nhỏ các handlers: document, owner_command, member_message, card_action (EDL-0009, EDL-0013) | Đã xác minh qua unit test |
| Core Chat Orchestration | `server/services/workflows/chat_workflow.py` | Pipeline xử lý tin nhắn, gọi JEV, RAG Scoping, Claims, LLM, duyệt nháp, batching proposed claims (EDL-0010, EDL-0013) | Đã xác minh |
| Intent Classifier (JEV) | `server/services/ai/jev_classifier.py` | Giao tiếp API JEV phân loại mục tiêu tin nhắn, dùng JEVError (EDL-0009) | Đã xác minh |
| Hybrid RAG Client | `server/services/knowledge/weknora_client.py` | Tìm kiếm ngữ nghĩa/từ khóa trên WeKnora dataset, scoped knowledge_ids isolation | Đã xác minh qua test thực tế |
| Context Composer | `server/services/knowledge/context_composer.py` | Hợp nhất RAG chunks + Claims, ưu tiên Claims mới hơn tài liệu | Đã xác minh qua unit test (6/6 pass) |
| Document Parsing Layer & OCR | `server/services/knowledge/doc_parser.py`, `server/services/ai/gemini_client.py` | Chuyển đổi file đính kèm, Lark Doc URL và hình ảnh qua Gemini Vision OCR sang Markdown (EDL-0010, EDL-0013) | Đã xác minh qua unit test (16/16 pass) |
| AnyDoc gRPC Client | `server/services/knowledge/docreader_client.py` | Kết nối `WeKnora-docreader:50051` parse nhị phân sang Markdown | Đã xác minh qua unit test (8/8 pass) |
| Rule Engine | `server/services/knowledge/rule_engine.py` | Line-level Redaction & Kiểm duyệt từ khóa nhạy cảm trên Chunks và Claims | Đã xác minh qua unit test (7/7 pass) |
| Daily Digest & Staging | `server/services/workflows/digest_workflow.py` | Lưu staging tin nhắn, tổng hợp digest ngày, xuất Thẻ báo cáo tương tác | Đã xác minh |
| Chat Scope Isolation | `server/services/knowledge/chat_scopes.py` | Quản lý quyền truy cập dataset và dữ liệu theo chat_id | Đã xác minh qua unit test |
| Draft Approval (HITL) | `server/services/workflows/draft_workflow.py` | Quản lý vòng đời bản nháp (Pending, Approved, Rejected) | Đã xác minh |
| Interactive Card Builder | `server/services/lark/card_builder.py` | Dựng các Thẻ tin nhắn tương tác chuẩn Lark (Draft, Claim, Master Digest với bảng Claims đề xuất và nút 1 chạm) (EDL-0012, EDL-0013) | Đã xác minh qua unit test (7/7 pass) |
| AI Draft Rewriter | `server/services/ai/draft_rewriter.py` | LLM viết lại bản nháp theo chỉ đạo Lãnh đạo, làm sạch icon/emoji (EDL-0012) | Đã xác minh |
| Claim Workflow & Service | `server/services/workflows/claim_workflow.py`, `server/services/claim_service.py` | Quản lý vòng đời Claims, truy vấn claims chờ duyệt theo ngày và thăng hạng hàng loạt (EDL-0012, EDL-0013) | Đã xác minh qua unit test (9/9 pass) |
| Card Action Handler | `server/services/lark/handlers/card_action_handler.py` | Xử lý sự kiện bấm nút trên Thẻ tương tác (`approve_all_digest_claims`, `view_digest_detail`, `view_master_digest`, draft actions) và cập nhật thẻ tại chỗ (EDL-0012, EDL-0013) | Đã xác minh qua unit test (12/12 pass) |
| Cost Telemetry Decorators | `server/decorators/` (`cost_telemetry.py`) | Bộ decorator đo lường chi phí, token, latency cho Gemini LLM và JEV System 1 (EDL-0014) | Đã xác minh qua unit test (9/9 pass) |
| Token Loop | `server/core/token_loop.py` | MỘT daemon thread + MỘT event loop cho mọi việc lấy token; `submit()` cho caller sync, `asubmit()` cho caller async, dừng trong lifespan shutdown. Sửa deadlock cross-loop của `asyncio.run()` + `asyncio.Lock` | `tests/auth/test_token_loop_concurrency.py` (T1) |
| Tenant/Token Errors | `server/core/tenant_errors.py` | Exception có kiểu, tự mang `error_code` + `http_status`: `TenantContextMissing` 400, `TenantNotFound`/`TenantNotReady`/`TenantConfigIncomplete`/`AppCredentialMissing` 409, `UserTokenMissing` 401, `TokenUnavailable` 503. Handler đăng ký một lần ở `main.py` | `tests/final_test/test_tenant_error_http_mapping.py` |
| TokenBroker (EDL-0070, thay TenantTokenManager EDL-0068) | `server/services/auth/tenant_token_manager.py` | `get/get_sync/invalidate`, cache key **3 chiều** `(tenant_key, app_id, kind)`, single-flight theo key + double-check, buffer hết hạn 300s, provider không cache/không fallback, **không bao giờ trả `""`** | `tests/auth/test_token_broker.py` (T3/T4) |
| TenantResourceResolver | `server/services/tenancy/tenant_resolver.py` | Chỗ duy nhất trả `TenantResources` theo hợp đồng 6 bước fail-closed; cache RAM 60s + `invalidate()`; `resolve_credentials()` là lối vào của tầng token; `resolve_current()` theo ContextVar | `tests/tenancy/test_tenant_resolver.py` (T7/T8/C1) |
| Tenant State Machine & Invalidation Hub | `server/services/tenancy/tenant_state.py` | Nơi duy nhất đổi `tenants.status`; `mark_ready()` chạy kiểm tra resolver trước khi set `ready`; mọi chuyển trạng thái + `register_app` + `link_tenant` vô hiệu cache resolver + broker | `tests/tenancy/test_tenant_state_machine.py` |
| OAuth State Registry | `server/services/auth/oauth_state_service.py` | Collection `oauth_states`: state do server phát hành, dùng **một lần** (`find_one_and_update`), gắn `(tenant_key, app_id, purpose)`, TTL index 10 phút | `tests/auth/test_oauth_state_service.py` |
| Tenant Refresh Sweeper | `server/services/auth/tenant_refresh_sweeper.py` | Thay `start_token_refresh_loop()`: mỗi 10 phút duyệt `tenants` có `status="ready"` và gọi `token_broker.get(tk, "user")`; lỗi chỉ log, không dừng vòng | `tests/auth/test_tenant_refresh_sweeper.py` |
| Friendly Tenant Errors (chat) | `server/services/lark/tenant_error_reply.py` | Dịch lỗi có kiểu thành tin nhắn trong chat ("chưa hoàn tất cài đặt" / "cần uỷ quyền lại"); không bao giờ raise | `tests/lark/test_tenant_error_reply.py` |
| Token Service | `server/services/auth/token_service.py` | Lark OAuth user token refresh via MongoDB, guarded by IS_ISV_MODE to disable legacy fallback in multi-tenant production | Updated WS5 with IS_ISV_MODE guards at lines ~605, ~720 (126/128 tests pass) |
| ISV Service | `server/services/auth/isv_token_service.py` | Bot/ISV tenant_access_token lifecycle management, per-tenant isolation | 9 integration tests (9/9 pass) |
| Test suite | `server/tests/01/` & `server/tests/` | Bộ kiểm thử chức năng, OCR, modular services, interactive cards, telemetry, tenancy & hồi quy toàn diện | `pytest tests -q` → **250 passed, 3 warnings** (2026-11-02, DB test `LarkAssistant_test`) |

## 5. Contracts and constraints
- **Lark API:** Dùng `lark-oapi` kết nối WebSocket mode (không cần public IP/webhook proxy khi dev).
- **Quy tắc giải quyết xung đột:** Sự thật (Claim) có hiệu lực mới nhất trong nhóm chat luôn được ưu tiên cao hơn tài liệu tĩnh từ WeKnora.
- **RAG Hard Isolation:** Dataset truy xuất phải được giới hạn chặt chẽ theo `chat_id` và quyền của người dùng; cấm truy xuất chéo nhóm trái phép.
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
- **Date:** 2026-11-02 (EDL-0070 / WS8 — Tenant Resolution & Token Flow)
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
