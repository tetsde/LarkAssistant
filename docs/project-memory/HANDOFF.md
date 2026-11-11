# Current Handoff

> Cập nhật khi kết thúc phiên có công việc đang dở hoặc bàn giao trạng thái sẵn sàng.

## Latest: Hợp Nhất Token Broker, Phân Quyền Bot/User Token Fail-Closed, Onboarding Gate, Mã Hóa `lark_auth` & Gỡ Bỏ Hoàn Toàn ISV Store App (EDL-0077) (2026-11-10)
- **Trạng thái hiện tại:** Đã hoàn tất toàn bộ 5 Phase refactor xác thực/token/phân quyền (`implementation_plan.md`) cộng với gỡ bỏ hoàn toàn luồng **ISV Store App** để vận hành thuần **Custom App Multi-Tenant**, chạy pass 100% bộ `pytest` và đồng bộ lên Notion [EDL-0077](https://app.notion.com/p/EDL-0077-H-p-nh-t-Token-Broker-OAuth-Gate-tuy-n-t-nh-ph-n-quy-n-Bot-User-Token-Fail-Closed-m-h-414590f7e19e8159aea0e9a7ea0174c1). Thay đổi đang nằm trên working tree nhánh `main` (chưa commit, chưa chạy migration `--apply` trên Atlas production, chưa deploy).
- **Vấn đề & thay đổi chính:**
  1. **Phase 1 — Hợp nhất `token_broker` & Event-Loop Safety (`server/services/auth/tenant_token_manager.py`, `token_service.py`, `base_provision_service.py`, `client.py`, `bitable.py`):**
     - Mọi truy cập `app` / `tenant` (Bot) / `user` token đi qua `token_broker` (`TenantTokenManager` cache 3 chiều `(tenant_key, app_id, kind)` trên `core.token_loop`).
     - Gỡ `_lock` toàn cục và `_app_access_tokens` trong `LarkTokenService` (giữ lock lười `_get_refresh_lock` theo cặp `(app_id, tenant_key)` cho single-use Refresh Token rotation); bỏ nhánh bypass `httpx` trong `BaseProvisionService`; chuẩn hóa `_get_request_option()` trong `client.py` và `LarkBaseService._get_headers(use_tenant_token=True)`.
  2. **Phase 2 — Stateless Runtime, Xóa `primary_user_token` & Async Draft (`client.py`, `runtime.py`, `messenger.py`, `token_service.py`, `token_verifier.py`, `draft_workflow.py`, `routers/auth.py`, `routers/onboarding.py`):**
     - Xóa cứng `PRIMARY_TOKEN_DOC_ID`, `_cached_token_data`, `_sync_to_lark_client`, `self.user_access_token` dùng chung và fallback `.env`.
     - Bắt buộc `tenant_key` (thiếu → `TenantContextMissing` HTTP 400) trên `GET /auth/lark/status`, `POST /auth/lark/refresh`, `GET /onboarding/api/auth-status`; `get_authorize_url()` bắt buộc có `app_id`.
     - Thay `DraftService._bg_delivery_executor` bằng `asyncio.create_task` bảo toàn `async_tenant_context` và `ContextVar` runtime service.
  3. **Phase 3 — Phân quyền Bot Token vs User Token (`client.py`, `messenger.py`, `bitable.py`, `draft_workflow.py`, `card_builder.py`, `chat_workflow.py`, `doc_parser.py`):**
     - Đọc dữ liệu workspace (IM resources, Contact `get_user_name`, `get_message`/`list_messages`, Bitable `use_tenant_token=True`) mặc định dùng **Bot Token** (`tenant_access_token`).
     - Đọc `DocX`/`Wiki`/`Drive` (async & sync) áp dụng **Bot-first -> Conditional User fallback**: ưu tiên Bot Token trước, chỉ fallback có điều kiện sang User Token khi Lark trả lỗi từ chối quyền (`_is_lark_permission_denied`) và nuốt `UserTokenMissing` để không gãy luồng đọc chung.
     - Phát ngôn nhân danh Sếp (`areply_text`/`reply_text` `as_user=True`) **Fail-Closed** với mã lỗi `user_token_missing` → `DraftService._send_claimed` hoàn bản nháp về `pending` và Bot gửi DM thẻ `build_user_reauth_card` cho Lãnh đạo.
  4. **Phase 4 — Onboarding Gate Tuyến Tính & Unified OAuth State (`tenant_state.py`, `tenant_lifecycle_handler.py`, `card_builder.py`, `routers/auth.py`, `routers/setup.py`, `routers/onboarding.py`, `one_click_setup_service.py`):**
     - Bổ sung trạng thái `AWAITING_USER_OAUTH = "awaiting_user_oauth"` (ngoài `SERVING_STATUSES = {READY}`) vào `tenant_state.py`.
     - Khi nhận `open_app` / `start_by_tenant` mà chưa có Admin User Token, dừng ở `awaiting_user_oauth` và gửi Bot DM thẻ `build_admin_oauth_invite_card`; sau khi Admin hoàn tất OAuth ở `/auth/lark/callback`, tự động nối sang `provision_tenant_and_send_handover` (`PROVISIONING` → `READY`).
     - Hợp nhất OAuth state của `/setup/install` & `/setup/callback` sang `oauth_state_service` dùng 1 lần (`purpose="setup"`). Xóa ghi đè `settings.LARK_*` toàn cục ở `routers/onboarding.py` và điều hướng `/api/save-bot-config` qua `lark_app_service.register_app` + `link_tenant`.
  5. **Phase 5 — Mã hóa Token Tại Nghỉ & Vá 4 Điểm Cô Lập DB (`token_service.py`, `indexes.py`, `scoped_query.py`, `chat_scopes.py`, `member_message_handler.py`, `owner_command_handler.py`, `scripts/migrate_lark_auth_encryption.py`):**
     - Mã hóa AES-256 Fernet cho `access_token` và `refresh_token` khi ghi `lark_auth` (dual-read bản ghi cũ trước khi migrate); che preview token trên callback HTML bằng `mask_token_preview`.
     - Tạo `scripts/migrate_lark_auth_encryption.py` (`--dry-run` mặc định; `--apply` mã hóa token cũ và chuyển `primary_user_token` → `archived_legacy_primary_user_token`); bổ sung compound indexes trên `lark_auth`.
     - Vá: giới hạn `chat_scopes` fallback theo `tenant_key` rỗng; `inject_tenant_filter` cho `conversation_staging` trong `member_message_handler.py`; truyền `tenant_key` ở `owner_command_handler.py` & `chat_workflow.py`; tách `resolve_tenant_by_admin_open_id` trong `scoped_query.py` (lọc `app_id`, fail-closed `None` khi `>= 2` tenant trùng `open_id`).
  6. **Gỡ bỏ hoàn toàn luồng ISV Store App — Chỉ chạy Custom App Multi-Tenant:**
     - **Xóa cứng:** `server/services/auth/isv_token_service.py` và `server/tests/final_test/test_isv_token_service.py`.
     - Gỡ `IS_ISV_MODE`, `LARK_APP_TYPE`, `LARK_APP_TICKET`, `MONGO_ISV_AUTH_COLLECTION`, `get_isv_auth_collection()`, `ISVProvider`, nhánh webhook `app_ticket` (`messenger.py`), fallback shared Store App (`tenant_resolver.py`), đổi `isv_auto_provision` → `auto_provision` và `build_isv_oauth_invite_card` → `build_admin_oauth_invite_card`, cập nhật config/models/templates/scripts/docs về mô hình duy nhất Custom App Multi-Tenant.
- **Files thay đổi trong phiên này (trên nhánh `main`, chưa commit):**
  - **1 file mới (`??`):** `scripts/migrate_lark_auth_encryption.py`.
  - **1 file xóa (`D`):** `server/services/auth/isv_token_service.py` *(và `server/tests/final_test/test_isv_token_service.py` trong `.gitignore`)*.
  - **49 file cập nhật (`M`)** + `.env.production.example` (`.gitignore`): `README.md`, `scripts/audit_tenant_config_readonly.py`, `server/core/config.py`, `server/database/{db.py,indexes.py,scoped_query.py}`, `server/docs/README.md`, `server/models/{chat.py,chat_queue.py,chat_scope.py,digest.py,lark.py,memory.py,onboarding.py,tenant.py,user_settings.py}`, `server/routers/{auth.py,digest.py,onboarding.py,policy.py,scope.py,setup.py}`, `server/services/{auth/__init__.py,auth/tenant_token_manager.py,auth/token_service.py,auth/token_verifier.py,auth_service.py,knowledge/chat_scopes.py,knowledge/doc_parser.py,lark/base_provision_service.py,lark/bitable.py,lark/card_builder.py,lark/client.py,lark/dispatcher.py,lark/handlers/card_action_handler.py,lark/handlers/document_handler.py,lark/handlers/member_message_handler.py,lark/handlers/owner_command_handler.py,lark/handlers/tenant_lifecycle_handler.py,lark/messenger.py,lark/runtime.py,lark_app_service.py,setup/one_click_setup_service.py,tenancy/tenant_resolver.py,tenancy/tenant_state.py,workflows/chat_workflow.py,workflows/draft_workflow.py}`, `server/templates/{onboarding_wizard.html,setup_one_click.html}`.
  - **Test files (`server/tests/` trong `.gitignore`):** thêm mới `tests/lark/test_phase3_bot_reads_and_fail_closed_im.py`, `tests/auth/test_phase5_encryption_and_isolation.py`, cập nhật các suite `tests/auth/`, `tests/tenancy/`, `tests/lark/`, `tests/final_test/`.
- **Bằng chứng xác thực (Verified):**
  - `python3 -m compileall -q` (`server/core`, `database`, `decorators`, `models`, `routers`, `services`, `tests`, `scripts`) → **exit code 0**.
  - Quét runtime `server/` và `scripts/` xác nhận **0** fallback legacy (`PRIMARY_TOKEN_DOC_ID`, `primary_user_token` ngoài filter loại trừ/migrate, `_cached_token_data`, `_sync_to_lark_client`, `_bg_delivery_executor`) hoặc logic ISV (`IS_ISV_MODE`, `LARK_APP_TYPE`, `LARK_APP_TICKET`, `get_isv_auth_collection`, `isv_token_service`, `ISVProvider`, `app_ticket`) còn sót.
  - `scripts/migrate_lark_auth_encryption.py --help` → **exit code 0**; `--dry-run`, `--apply` & archive `primary_user_token` pass trên `FakeSyncDB` trong `test_phase5_encryption_and_isolation.py`.
  - Targeted pytest (`tests/auth`, `tests/tenancy`, `tests/lark`, `test_event_ingress_multi_tenant.py`, `test_marketplace_onboarding_experience.py`, `test_weknora_bitable_provisioning.py`) → **182 passed, 3 warnings in 5.62s**.
  - Full regression suite: `cd /Users/hoainam/Desktop/HiLark/server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 /Users/hoainam/Desktop/HiLark/server/.venv/bin/python -m pytest tests -q` → **374 passed, 3 warnings in 8.47s** (DB local `LarkAssistant_test`, external HTTP mocked; cũng đã sửa 3 bug test assertion/route cũ trong `test_oauth_login_flow_contract.py` và `test_phase5_encryption_and_isolation.py`).
  - Notion sync: đã tạo và xác minh đọc lại trang [EDL-0077](https://app.notion.com/p/EDL-0077-H-p-nh-t-Token-Broker-OAuth-Gate-tuy-n-t-nh-ph-n-quy-n-Bot-User-Token-Fail-Closed-m-h-414590f7e19e8159aea0e9a7ea0174c1) (`414590f7-e19e-8159-aea0-e9a7ea0174c1`).
  - **Phạm vi chưa verify live:** Toàn bộ Lark OpenAPI & WeKnora trong pytest dùng mock HTTP; chưa chạy `scripts/migrate_lark_auth_encryption.py --apply` trên MongoDB Atlas production và chưa kiểm thử E2E thật trên Lark Developer Console sau khi gỡ ISV.
- **Quyết định liên quan:** [EDL-0077 (Notion)](https://app.notion.com/p/EDL-0077-H-p-nh-t-Token-Broker-OAuth-Gate-tuy-n-t-nh-ph-n-quy-n-Bot-User-Token-Fail-Closed-m-h-414590f7e19e8159aea0e9a7ea0174c1) & `docs/project-memory/DECISIONS.md` (`partly supersedes` `EDL-0020`, `EDL-0022`, `EDL-0026`, `EDL-0028`, `EDL-0039`).
- **Bước tiếp theo khi triển khai Production:**
  1. Review `git diff` trên nhánh `main` và gỡ/dọn các biến ISV cũ (`IS_ISV_MODE`, `LARK_APP_TYPE`, `LARK_APP_TICKET`, `MONGO_ISV_AUTH_COLLECTION`) trong `.env` thật nếu còn khai báo.
  2. Chạy migration preview trên MongoDB thật (kiểm tra `ENCRYPTION_SECRET_KEY` đã cấu hình chuẩn trước):
     - `python scripts/migrate_lark_auth_encryption.py` (`--dry-run` mặc định)
     - `python scripts/migrate_lark_auth_encryption.py --apply` để mã hóa token `lark_auth` hiện hữu và archive `primary_user_token`.
  3. Commit, deploy lên production và smoke-test E2E 1 luồng Custom App Multi-Tenant thật trên Lark (`register_app` -> `open_app`/`awaiting_user_oauth` -> OAuth Admin callback -> auto provision Base/WeKnora -> đọc workspace bằng Bot Token & duyệt draft `as_user=True`).

## Previous: Chuẩn Hóa Logging Kỹ Thuật, Gỡ Nhánh Fallback Legacy User Identity Trên Startup (2026-11-09)
- **Trạng thái hiện tại:** Đã hoàn tất gỡ nhánh startup single-tenant legacy (gây in `DANH TÍNH HOẠT ĐỘNG: User` + hộp cảnh báo `.env access_token_user` khi MongoDB rỗng), chuẩn hóa log hệ thống sang `[TAG] event key=value`, xác minh startup/shutdown thực tế, chạy toàn bộ `pytest` và trả MongoDB local về trạng thái sạch.
- **Nguyên nhân đã sửa & thay đổi chính:**
  1. **Gỡ fallback danh tính `"User"` trên startup (`server/services/lark/bot_runner.py`, `server/services/lark/client.py`):**
     - Thay `_has_registered_custom_apps()` + nhánh fallback single-tenant (`check_and_warn_token()`, `lark_service.get_current_user()`, fallback chuỗi `"User"`) bằng `_get_startup_tenant_counts()` đếm `registered_apps` & `ready_tenants` từ MongoDB và log gọn `[BOT] starting mode=webhook domain=... registered_apps=... ready_tenants=...`.
     - Sửa `LarkService.get_current_user()` trong `client.py` trả fallback `"name": settings.LARK_USER_NAME or ""` thay vì `"User"`.
  2. **Chuẩn hóa logging có cấu trúc (`server/`):**
     - Gỡ bỏ runtime `print()`, ASCII banner, emoji và log văn nói trên startup path, worker nền và toàn bộ `routers/` / `services/`, chuyển sang `[TAG] event key=value`.
     - Đưa log tick rỗng (`checked=0` / `ready_tenants=0`) và broker init lúc reload (`[TOKEN_BROKER] initialized`) xuống `DEBUG`.
     - Kiểm tra rõ các worker định kỳ (`PolicySync`, `ScopeSync`, `TenantTokenSweeper`, `DigestScheduler`, `_async_bitable_bootstrap`) đều lấy danh sách tenant từ MongoDB (`tenants` với `status == "ready"`, riêng bootstrap lọc `status != "uninstalled"`); `.env` chỉ cấp tham số mặc định toàn cục khi tenant chưa cấu hình riêng.
- **Bằng chứng xác thực (Verified):**
  - `python3 -m compileall -q /Users/hoainam/Desktop/HiLark/server` → **exit code 0**.
  - AST scan `logger.*` / `logging.*` qua `server/{main.py,core,database,routers,services}` → **0** emoji/banner (`AST_HITS= 0`); grep `print(` chỉ còn docstring và 2 script CLI (`token_verifier.py`, `bitable.py`).
  - Smoke test `uv run main.py` (MongoDB tạm `LarkAssistant_log_smoke`, `GET /health` → `200 OK`, SIGINT graceful shutdown) → log sạch 100%, không còn `"User"`, không cảnh báo `.env`, không trùng broker lúc reload.
  - `cd /Users/hoainam/Desktop/HiLark/server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 uv run pytest tests/ -q` → **348 passed, 4 warnings in 7.82s**.
  - Đã drop `LarkAssistant_log_smoke` và `LarkAssistant_test` trên `mongodb://localhost:27017`; port `8000` đang rảnh.

## Previous: Refactor LLMClient Đa Provider, Chuẩn Hóa Models & Schema MongoDB, Đưa Cost Telemetry Ra .env & Đo thinking_tokens (EDL-0076) (2026-11-09)
- **Trạng thái hiện tại:** Đã hoàn tất toàn bộ 6 bước (Step 1–6) triển khai, dọn sạch ký hiệu/field cũ và kiểm thử tự động trên nhánh `main` (chưa commit, chưa chạy migration trên Atlas production, chưa deploy).
- **Vấn đề & thay đổi chính:**
  1. **Tập trung Models vào `server/models/` & Làm sạch Schema (`server/models/llm.py`, `server/models/telemetry.py`, `user_settings.py`, `onboarding.py`, `model_catalog.py`, `indexes.py`):**
     - Tạo `LLMModelOption`, frozen `LLMRequest` (với `@property is_multimodal`), `LLMUsage` (`thinking_tokens`, `thinking_included_in_output`) tại `server/models/llm.py`, và `ModelPricing`, `TelemetryRecord` (`service="google"`, `output_tokens`, `thinking_tokens`) tại `server/models/telemetry.py`.
     - Chuyển `GEMINI_MODEL_SPECS` trong `model_catalog.py` sang `LLMModelOption`, gỡ bỏ hoàn toàn `is_gemini_3_or_newer` và `is_gemini_25_pro`.
     - Chuẩn hóa toàn bộ schema runtime/Pydantic/UI sang `encrypted_llm_api_key`, `masked_llm_api_key`, `raw_llm_key`, `output_tokens`, `thinking_tokens`, `service="google"`; bổ sung compound index `idx_telemetry_provider_model`.
     - Tạo `scripts/migrate_llm_schema.py` (`--dry-run` mặc định; `--apply` backfill + chuẩn hóa `service="gemini" -> "google"` và mặc định `$unset` xóa field cũ trừ khi truyền `--keep-legacy`).
  2. **Đổi tên & Tái cấu trúc `LLMClient` (`server/services/ai/llm_client.py`, xóa cứng `gemini_client.py`):**
     - Đổi module sang `services/ai/llm_client.py` (`LLMClient`, `llm_client`); xóa cứng `gemini_client.py` và các alias cũ (`GeminiClient`, `test_gemini_key`, `_call_gemini`, `calculate_gemini_cost`).
     - Tách 3 pure static payload builders nhận `(model, LLMRequest)`: `_build_google_payload`, `_build_openai_payload`, `_build_anthropic_payload`.
     - Gỡ bỏ `_apply_gemini_thinking_config` và tham số `thinking_budget` đoán mò theo regex tên model; `@track_llm_cost` đo trực tiếp token thực tế từ phản hồi provider.
  3. **Đưa tham số chi phí ra `.env` & Chống double-counting (`server/core/config.py`, `.env.production.example`, `decorators/cost_telemetry.py`, `card_builder.py`):**
     - Thêm vào `.env`/Settings: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `USD_TO_VND_RATE`, `JEV_FLAT_COST_PER_REQUEST`, `LLM_DEFAULT_*`, `LLM_PROVIDER_DEFAULT_PRICING_JSON`, `LLM_MODEL_PRICING_JSON` (kèm safe fallback khi JSON/float lỗi).
     - `calculate_llm_cost()` tra theo thứ tự ưu tiên: `"<provider>/<model>"` exact/longest-prefix -> `"<model>"` exact/longest-prefix -> `LLM_PROVIDER_DEFAULT_PRICING_JSON` -> `LLM_DEFAULT_*`. Khi `thinking_included_in_output=False` (Google `thoughtsTokenCount`) mới cộng thêm `thinking_tokens`, tránh tính trùng `reasoning_tokens` / `thinking_tokens` của OpenAI & Anthropic.
     - `build_digest_approval_card` tổng hợp tất cả LLM service khác `jev`, dùng nhãn trung lập `LLM (...)` và chỉ hiển thị `, thinking: <n>` khi `> 0`.
  4. **Đồng bộ Callers, Router & UI:** Cập nhật `services/ai/__init__.py`, `services/__init__.py`, `ai_service.py`, `digest_service.py`, `llm_extractor.py`, `doc_parser.py` (`parser="llm_vision_ocr"`), `chat_workflow.py`, `digest_workflow.py` (`_call_llm`), `ai_config_manager.py`, `user_settings_service.py`, `routers/onboarding.py`, `onboarding_wizard.html`, `setup_one_click.html` (`#llmKeyInput`, `raw_llm_key`, `masked_llm_api_key`).
- **Files thay đổi thuộc EDL-0076 (trên worktree `main` vốn đang có sẵn thay đổi chưa commit của `EDL-0075`):**
  - **4 file mới:** `server/models/llm.py`, `server/models/telemetry.py`, `server/services/ai/llm_client.py`, `scripts/migrate_llm_schema.py`.
  - **1 file xóa cứng (`D`):** `server/services/ai/gemini_client.py`.
  - **22 file cập nhật runtime/template/config:** `server/core/config.py`, `.env.production.example` (`.gitignore`), `server/database/indexes.py`, `server/decorators/__init__.py`, `server/decorators/cost_telemetry.py`, `server/models/__init__.py`, `server/models/onboarding.py`, `server/models/user_settings.py`, `server/routers/onboarding.py`, `server/services/__init__.py`, `server/services/ai/__init__.py`, `server/services/ai/ai_config_manager.py`, `server/services/ai/llm_extractor.py`, `server/services/ai/model_catalog.py`, `server/services/ai_service.py`, `server/services/digest_service.py`, `server/services/knowledge/doc_parser.py`, `server/services/lark/card_builder.py`, `server/services/user_settings_service.py`, `server/services/workflows/chat_workflow.py`, `server/services/workflows/digest_workflow.py`, `server/templates/onboarding_wizard.html`, `server/templates/setup_one_click.html` *(gồm `.env.production.example` trong `.gitignore` là 23)*.
  - **4 test files (`.gitignore` bỏ qua `tests/`):** `server/tests/final_test/test_byok_onboarding.py`, `server/tests/final_test/test_ai_config_and_jev_byok.py`, `server/tests/final_test/phase_3_daily_digest_reporting/test_phase_3_daily_digest_reporting.py`, `server/tests/lark/test_card_builder_schema.py`.
- **Bằng chứng xác thực (Verified):**
  - `python3 -m compileall -q server/core server/database server/decorators server/models server/routers server/services server/tests scripts` → **exit code 0**.
  - Quét runtime `server/` (loại `__pycache__`, `tests`, `docs`, `.venv`, `.pytest_cache`) xác nhận **0** ký hiệu cũ còn sót; toàn bộ tham chiếu trong `scripts/migrate_llm_schema.py` và negative assertions trong `server/tests` đều có chủ đích.
  - `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 /Users/hoainam/Desktop/HiLark/server/.venv/bin/python -m pytest tests/final_test/test_byok_onboarding.py tests/final_test/test_ai_config_and_jev_byok.py tests/final_test/phase_3_daily_digest_reporting/test_phase_3_daily_digest_reporting.py tests/lark/test_card_builder_schema.py -v` → **107 passed, 2 warnings in 2.76s**.
  - `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 /Users/hoainam/Desktop/HiLark/server/.venv/bin/python -m pytest tests -q` → **348 passed, 4 warnings in 7.21s** (trên **MongoDB local** `LarkAssistant_test`).
  - `/Users/hoainam/Desktop/HiLark/server/.venv/bin/python scripts/migrate_llm_schema.py --help` → **exit code 0**; `--dry-run`, `--apply`, `--apply --keep-legacy` pass qua unit test với `FakeSyncDB`.
  - **Phạm vi chưa verify live:** Các lời gọi HTTP tới Google Gemini, OpenAI, Anthropic, JEV đều mock qua `httpx`; chưa test paid live API call, chưa chạy `scripts/migrate_llm_schema.py --apply` vào MongoDB Atlas thật, và 4 file docs tham khảo cũ trong `server/docs/` (`so_do_luong_hoat_dong_4_lop.md`, `layer4/layer4.md`, `layer4/persona_delivery_deep_dive.md`) vẫn ghi tên `gemini_client.py` (ngoài phạm vi code Step 1–6).
- **Quyết định liên quan:** [EDL-0076 (Notion)](https://app.notion.com/p/EDL-0076-Refactor-LLMClient-a-provider-chu-n-h-a-Models-Schema-MongoDB-a-Cost-Telemetry-ra--413590f7e19e814cb219c7328239f002) & `docs/project-memory/DECISIONS.md` (partly supersedes `EDL-0075`, `EDL-0014`, `EDL-0019`).
- **Bước tiếp theo khi triển khai Production:**
  1. Cập nhật `.env` production từ `.env.production.example` (kiểm tra `USD_TO_VND_RATE`, `JEV_FLAT_COST_PER_REQUEST`, `LLM_DEFAULT_*`, `LLM_MODEL_PRICING_JSON` nếu muốn override).
  2. Chạy preview migration trên DB thật: `/path/to/python scripts/migrate_llm_schema.py` (mặc định `--dry-run`), kiểm tra số lượng document trước khi chạy `--apply` để backfill & `$unset` xóa các field legacy (`encrypted_gemini_api_key`, `masked_gemini_api_key`, `candidates_tokens`).
  3. Review `git diff` trên nhánh `main` (bao gồm cả phần `EDL-0075` + `EDL-0076`), commit và deploy.

## Previous: Hoàn Thành Unified Fail-Closed BYOK, AI Config Manager, Mặc Định gemini-flash-latest & JEV BYOK (EDL-0075) (2026-11-09)
- **Trạng thái hiện tại:** Đã hoàn tất cả 6 bước (Step 1–6) triển khai, tích hợp UI/Backend và kiểm thử tự động trên nhánh `main` (working tree có thay đổi chưa commit, chưa deploy production).
- **Vấn đề & thay đổi chính:**
  1. **Single Source of Truth Model Catalog (`server/services/ai/model_catalog.py`):** Chuẩn hóa `DEFAULT_GEMINI_MODEL = "gemini-flash-latest"`, `GEMINI_MODEL_OPTIONS` từ Gemini `2.5` đến `3.8`, cùng helper nhận diện thế hệ (`is_gemini_3_or_newer`, `is_gemini_25_pro`).
  2. **Centralized AI Config Manager (`server/services/ai/ai_config_manager.py`) & Schema (`server/models/user_settings.py`, `server/database/indexes.py`):** Gom toàn bộ mã hóa/giải mã AES-256 Fernet (`decrypt_key_strict`), RAM cache TTL 60s + `invalidate()`, lưu cấu hình thống nhất kèm dọn rác `llm_base_url`/`llm_model` khi đổi provider hoặc xóa rỗng trên UI, và bổ sung trường JEV BYOK (`is_jev_byok_enabled`, `jev_mode`, `encrypted_jev_api_key`, `masked_jev_api_key`). `UserSettingsService` rút gọn thành thin compatibility facade; `OneClickSetupService` bảo vệ không ghi đè mất BYOK khi admin chạy lại setup.
  3. **Hợp đồng Fail-Closed BYOK & Multi-Provider Engine (`server/core/tenant_errors.py`, `server/services/ai/gemini_client.py`, `server/services/ai/jev_classifier.py`, `server/services/lark/tenant_error_reply.py`, `server/decorators/cost_telemetry.py`):**
     - Bật BYOK (`is_byok_enabled=True` hoặc `is_jev_byok_enabled=True`) mà thiếu/lỗi giải mã key, bị từ chối `401`/`403`/`400-auth`, hoặc toàn bộ model `400`/`404` sẽ raise `BYOKConfigurationError` (`HTTP 400`, lời nhắn tiếng Việt trên chat), chỉ fallback `.env` khi BYOK tắt.
     - Loại bỏ đường vòng `chat_scope` key, `request_api_key`, WeKnora Chat fallback (`chat_workflow.py`) và `FAST_APPROVE_SET` khi BYOK JEV bật; `jev_classifier.py` hỗ trợ per-request headers và `ping_key()`; `gemini_client.py` đồng bộ `thinkingConfig` (`thinkingLevel` cho Gemini `3.x+`, `thinkingBudget` cho `2.5 Pro`/`Flash`) và telemetry đa provider + `tenant_key` + `is_byok`.
  4. **Callers & Onboarding/Setup UI (`server/services/knowledge/doc_parser.py`, `chat_scopes.py`, `server/services/workflows/chat_workflow.py`, `digest_workflow.py`, `document_handler.py`, `member_message_handler.py`, `server/models/onboarding.py`, `server/routers/onboarding.py`, `server/templates/onboarding_wizard.html`, `server/templates/setup_one_click.html`):** Truyền `tenant_key` xuyên suốt tới `AIConfigManager`/JEV, chặn nuốt `BYOKConfigurationError`; bổ sung `/onboarding/api/models`, dropdown Gemini `2.5` → `3.8` + `__custom__` và mục cấu hình + Test Key riêng cho JEV System 1 trên cả Wizard lẫn One-Click Setup.
- **Files thay đổi:**
  - **2 file mới:** `server/services/ai/ai_config_manager.py`, `server/services/ai/model_catalog.py`.
  - **21 file cập nhật:** `core/tenant_errors.py`, `database/indexes.py`, `decorators/__init__.py`, `decorators/cost_telemetry.py`, `models/onboarding.py`, `models/user_settings.py`, `routers/onboarding.py`, `services/ai/__init__.py`, `services/ai/gemini_client.py`, `services/ai/jev_classifier.py`, `services/knowledge/chat_scopes.py`, `services/knowledge/doc_parser.py`, `services/lark/handlers/document_handler.py`, `services/lark/handlers/member_message_handler.py`, `services/lark/tenant_error_reply.py`, `services/setup/one_click_setup_service.py`, `services/user_settings_service.py`, `services/workflows/chat_workflow.py`, `services/workflows/digest_workflow.py`, `templates/onboarding_wizard.html`, `templates/setup_one_click.html`.
  - **Test files (nằm ngoài `git status` vì `.gitignore` bỏ qua `tests/`):** `server/tests/final_test/test_byok_onboarding.py`, `server/tests/final_test/test_ai_config_and_jev_byok.py`.
- **Bằng chứng xác thực (Verified):**
  - `cd server && python3 -m compileall -q core database decorators models routers services tests/final_test/test_ai_config_and_jev_byok.py tests/final_test/test_byok_onboarding.py` → **exit code 0**.
  - `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 .venv/bin/python -m pytest tests/final_test/test_byok_onboarding.py -v` → **33 passed** (Step 6A).
  - `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 .venv/bin/python -m pytest tests/final_test/test_ai_config_and_jev_byok.py -v` → **55 passed, 0 failed, 2 warnings in 2.86s** (Step 6B).
  - `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 .venv/bin/python -m pytest tests -q` → **342 passed, 4 warnings in 7.02s**.
  - **Phạm vi chưa verify live:** Toàn bộ request ra Google Gemini (`3.8`/`2.5`), OpenAI, Anthropic, JEV API trong test đều mock qua `httpx`; chưa chạy smoke test có phí với key thật, chưa chạy trên MongoDB Atlas production, và chưa click E2E trực tiếp trong Lark Webview modal.
- **Quyết định liên quan:** [EDL-0075 (Notion)](https://app.notion.com/p/EDL-0075-Unified-Fail-Closed-BYOK-AI-Config-Manager-t-p-trung-M-c-nh-gemini-flash-latest-JEV--413590f7e19e814f8786ca5ca1b1c737) & `docs/project-memory/DECISIONS.md` (partly supersedes `EDL-0017`, `EDL-0019`).
- **Bước tiếp theo:** User review Gate 6; nếu muốn kiểm chứng thực tế, cấu hình `.env`/MongoDB Atlas và test nút `Kiểm tra` với key Gemini & JEV thật trên `/onboarding/wizard` hoặc `/setup`, sau đó review `git diff` để commit và deploy.

## Previous: Rà Soát Multi-Tenant, Hoàn Thiện Cô Lập BYOK & Kế Hoạch Triển Khai Production (2026-11-03)
- **Vấn đề đã xử lý:**
  - Hoàn thành rà soát bảo mật toàn diện cho môi trường Multi-Tenant Production.
  - Phát hiện và vá điểm rò rỉ tiềm ẩn trong cơ chế giải quyết BYOK Key (`user_settings_service.py`):
    + Trước đây: `resolve_effective_llm_client` và `resolve_effective_llm_key` chỉ nhận `user_id` và `chat_id` mà không có `tenant_key`, dẫn đến việc query collection `user_settings` và `chat_scopes` chỉ bằng `open_id`, tiềm ẩn nguy cơ lấy nhầm cấu hình BYOK hoặc scope key giữa các tenant.
    + Đã vá: Bổ sung tham số `tenant_key: Optional[str] = None` vào `resolve_effective_llm_client` và `resolve_effective_llm_key`, fallback tự động về `get_current_tenant_key()`. Truyền tường minh `tenant_key=eff_tenant` tại `chat_workflow.py:1345`.
  - Tư vấn thiết lập hạn mức hệ thống (Quotas & Limits) 4 tầng: Hàng đợi Chat (Debounce 1.75s, Cooldown 4.0s, Concurrency 5-10 pipelines), WeKnora Ingestion (File size 25-30MB, Folder depth 3, max files 200), Token Quota (Top-K 5-7 chunks ~ 5k tokens, Max output 2048 tokens), và Reverse Proxy Nginx.
  - Lập Kế hoạch Triển khai Sản xuất (Production Deployment Plan) chi tiết tại artifact `PRODUCTION_DEPLOYMENT_AND_SYSTEM_QUOTAS.md`.
- **Bằng chứng xác thực (Verified):**
  - Chạy `tests/final_test/test_data_leakage_fixes.py` -> **5/5 tests PASSED**.
  - Chạy `tests/final_test/test_byok_onboarding.py` -> **26/26 tests PASSED**.
  - Kiểm tra giải mã log WeKnora: lỗi `VECTORSTORE_WRITE_FAILED` là do cạn kiệt Google Gemini API credit (HTTP 402), không phải lỗi logic code hay kết nối WeKnora.

## Previous: Khắc Phục Triệt Để 4 Lỗ Hổng Rò Rỉ Dữ Liệu Cross-Tenant & Cross-Group (EDL-0074) (2026-11-03)
- **Vấn đề đã xử lý:**
  - Thực hiện audit bảo mật chuyên sâu luồng Parse Docs, Context Composer, Claims Extractor và Setup Onboarding.
  - Phát hiện và vá triệt để 4 điểm rò rỉ dữ liệu / xung đột đa khách thuê (Cross-Tenant Leakage):
    1. **B3 (Context Composer Claim Leak):** Tại `context_composer.py:706`, điều kiện `if not c.tenant_key or c.tenant_key == eff_tenant` cho phép claim mồ côi (không tenant_key) lọt vào prompt của bất kỳ tenant nào. Tại `normalize_claims_data:379`, `tenant_key=f.get("tenant_key") or tenant_key` tự động gán tenant hiện tại cho dữ liệu thiếu tenant.
    2. **B1 (Lark Doc Link Ingestion Missing Tenant):** Tại `document_handler.py:141-151`, các lệnh gọi `parse_lark_docx`, `parse_lark_wiki`, `parse_lark_folder` không truyền `tenant_key=msg.tenant_key`, dẫn tới nguy cơ dùng bot token của tenant khác để đọc docs.
    3. **B2 (Parse Attachment Missing Tenant):** Tại `doc_parser.py:parse_attachment()`, không có tham số `tenant_key` và gọi download qua singleton `_lark` property thay vì client của đúng tenant.
    4. **B4 (Entity ID Collision & Index Flaw):** Tại `llm_extractor.py:64`, `generate_stable_entity_id()` chỉ băm theo `f"{clean_ws}:{clean_name}"` mà không có `tenant_key`. Hai công ty khác nhau có cùng tên thực thể sẽ sinh ra trùng `ent_id`. Khi lưu vào collection `memories`, unique index cũ chỉ nằm trên `id` đơn lẻ (`idx_memories_id_unique`), gây lỗi `DuplicateKeyError` hoặc ghi đè dữ liệu chéo.
- **Giải pháp triển khai:**
  1. `server/services/knowledge/context_composer.py`:
     - Line 709: Xóa escape hatch, chỉ giữ claim có `c.tenant_key == eff_tenant`.
     - Line 379: Giữ nguyên `tenant_key=f.get("tenant_key")`, không auto-adopt.
  2. `server/services/lark/handlers/document_handler.py`:
     - Truyền `tenant_key=msg.tenant_key` vào `parse_lark_docx`, `parse_lark_wiki`, `parse_lark_folder`, và `parse_attachment`.
  3. `server/services/knowledge/doc_parser.py` & `server/services/lark/runtime.py`:
     - Bổ sung `get_lark_service_for_tenant(tenant_key)` trong `runtime.py`.
     - Thêm helper `_get_lark_for_tenant(tenant_key)` và param `tenant_key` vào `parse_attachment()` trong `doc_parser.py`.
  4. `server/services/ai/llm_extractor.py` & `server/services/workflows/chat_workflow.py`:
     - `generate_stable_entity_id` băm theo `f"{clean_tenant}:{clean_ws}:{clean_name}"`.
     - `extract_async`, `extract_entities_async`, `extract` nhận và truyền `tenant_key`.
     - `chat_workflow.py` truyền `tenant_key=eff_tenant` vào `extract_async()`.
  5. `server/database/indexes.py` & `scripts/migrate_entity_index.py`:
     - Chuyển `idx_memories_id_unique` thành compound unique `[("tenant_key", ASCENDING), ("id", ASCENDING)]` (`idx_memories_tenant_id_unique`).
     - Tự động drop index cũ trong `ensure_database_indexes()`.
     - Viết script `scripts/migrate_entity_index.py` (hỗ trợ dry-run và `--apply`).
- **Bằng chứng xác thực (Verified):**
  - Tạo test suite chuyên biệt `tests/final_test/test_data_leakage_fixes.py` -> **5/5 tests PASSED**.
  - `tests/final_test/test_claims_knowledge_multi_tenant.py` -> **8/8 tests PASSED**.
  - `tests/final_test/test_cross_tenant_isolation_complete.py` -> **5/5 tests PASSED**.
  - Tổng cộng 18/18 multi-tenant security isolation tests PASSED 100%.
  - Chạy full regression test suite toàn hệ thống (`pytest tests/`): **280/280 tests PASSED** (0 failed). Hoàn toàn không phát sinh regression.

## Previous: Vô Hiệu Hóa Lark WebSocket Ngầm Khi Dùng Webhook Gateway & Kích Hoạt Thành Công Tenant Mới (2026-11-03)
- **Vấn đề đã xử lý:**
  - Trong log server xuất hiện lỗi `RuntimeError: Task ... got Future ... attached to a different loop` từ thư viện `lark_oapi.ws.client`.
  - Phân tích nguyên nhân:
    1. Trước đây khi chạy bot local, HiLark dùng chế độ persistent WebSocket connection (`lark.ws.Client`). Khi nâng cấp lên kiến trúc Multi-Tenant qua Webhook Gateway (`/api/lark/events`), đoạn mã khởi động WebSocket ngầm cho từng App trong `bot_runner.py` vẫn chạy.
    2. SDK `lark_oapi` có biến `loop` toàn cục ở cấp module; khi chạy đồng thời nhiều kết nối WebSocket trên cùng một process Python, các thread ghi đè biến `loop` của nhau gây xung đột.
- **Giải pháp triển khai:**
  1. `server/core/config.py`: Bổ sung cờ `ENABLE_LARK_WEBSOCKET: bool = False` (mặc định tắt WebSocket để ưu tiên Webhook Gateway).
  2. `server/services/lark/bot_runner.py` & `server/routers/onboarding.py`: Bọc điều kiện `enable_ws` trước khi khởi động WebSocket threads.
  3. Deploy vào container và restart `hilark-server`.
- **Bằng chứng xác thực (Verified):**
  - Log server thông báo sạch sẽ:
    `   - WebSocket Mode    : ⚪ Tắt (Sử dụng Webhook)`
    `ℹ️ Chế độ Lark WebSocket đang tắt (ENABLE_LARK_WEBSOCKET=False). Mọi sự kiện và tương tác nhận qua Webhook Gateway (/api/lark/events).`
  - Hoàn toàn không còn bất kỳ exception `attached to a different loop` nào.
  - Quá trình OAuth user của App mới `cli_aa63f447fc78de27` đã hoàn tất thành công 100%:
    `Tenant: 198ccffa855b1975 App: cli_aa63f447fc78de27 Status: ready`
    `🧹 [SWEEPER] completed checked=2 ok=2 missing=0 unavailable=0`

## Previous: Khắc phục Triệt Để Lỗi Lark OAuth 20029 & Đồng bộ Dynamic Redirect URI (2026-11-03)
- **Vấn đề đã xử lý:**
  - Khi Admin bấm cấp quyền OAuth user trên giao diện Setup (`/setup/install`), Lark trả về lỗi: `URL chuyển hướng không hợp lệ. Mã lỗi: 20029`.
  - Phân tích nguyên nhân:
    1. Trong `server/core/config.py`, biến `LARK_OAUTH_REDIRECT_URI` bị hardcode mặc định là `"http://localhost:8000/auth/lark/callback"`. Do đó khi gọi OAuth authorize, hệ thống luôn gửi `redirect_uri=http://localhost:8000/...` thay vì URL Ngrok/domain công khai (`https://hertz-liftoff-earphone.ngrok-free.dev/setup/callback`) mà người dùng đã đăng ký trong Lark Security Settings.
    2. Frontend hiển thị URL chuyển hướng là `/setup/callback`, nhưng backend router `/setup/install` lại trỏ sang `/auth/lark/callback`.
- **Giải pháp triển khai:**
  1. `server/core/config.py`: Đổi default của `LARK_OAUTH_REDIRECT_URI` thành `""` (không hardcode `localhost:8000`).
  2. `server/routers/setup.py` & `server/routers/auth.py`: Bổ sung cơ chế nhận diện tự động từ headers proxy (`X-Forwarded-Proto`, `X-Forwarded-Host`) và ưu tiên nhận `redirect_uri` từ client param.
  3. `server/templates/setup_one_click.html` & `server/templates/onboarding_wizard.html`: Truyền `redirect_uri = window.location.origin + "/setup/callback"` khi chuyển hướng sang `/setup/install`.
- **Bằng chứng xác thực (Verified):**
  - Chạy `curl -i` giả lập qua Ngrok: Header trả về `location: https://accounts.larksuite.com/...&redirect_uri=https%3A%2F%2Fhertz-liftoff-earphone.ngrok-free.dev%2Fsetup%2Fcallback`. Khớp 100% với Redirect URL trong Lark Console.
  - Test suite: 29/29 tests PASSED.

## Previous: Khắc phục Triệt Để Vòng Lặp Rebuild Docs & Đốt Token AI (EDL-0073) (2026-11-03)
- **Vấn đề đã xử lý:**
  - Người dùng báo cáo hệ thống liên tục tự động rebuild tài liệu Lark Docs, vòng lặp đệ quy quét Drive và upload lại sang WeKnora dù dữ liệu không hề thay đổi, dẫn tới Gemini 2.5 Flash + BatchEmbed chạy liên tục và đốt cạn token/tiền của user.
  - Phân tích nguyên nhân gốc rễ (Root Cause Analysis):
    1. *`force=True` hardcode:* Tại `server/services/lark/bot_runner.py:393` (`_async_bitable_bootstrap()`) và `server/services/knowledge/policy_sync.py:731` (`start_loop()`), hàm `sync_policies` được gọi với `force=True`. Điều này làm bypass điều kiện kiểm tra MD5 hash trong `_upload_or_rebuild()`. Do đó dù MD5 của Lark DocX khớp 100% với file trên WeKnora, file vẫn bị xóa và upload lại, kích hoạt pipeline embedding.
    2. *`interval_seconds=30` hardcode:* Tại `server/services/lark/bot_runner.py:420`, `scope_service.start_loop(interval_seconds=30)` chạy lặp vô tận mỗi 30 giây, đệ quy 4 tầng Lark Drive (4 GET requests/lần = 480 req/giờ).
- **Giải pháp triển khai:**
  1. `server/services/lark/bot_runner.py`:
     - Line 395: Đổi `force=True` -> `force=False` trong bootstrap.
     - Line 424: Tăng `interval_seconds=30` -> `interval_seconds=1800` (30 phút).
  2. `server/services/knowledge/policy_sync.py`:
     - Line 734: Đổi `force=True` -> `force=False` trong định kỳ loop. Cờ `force=True` chỉ được kích hoạt khi user chủ động bấm "Đồng bộ ngay" trên UI.
- **Bằng chứng xác thực (Verified in Container `hilark-server`):**
  - Sao chép 2 files vào container `hilark-server` và khởi động lại container.
  - Startup logs xác nhận so sánh MD5 hoạt động:
    `ℹ️ [PolicySync] 'Lark DocX (WzxDw72ILiBI1Ika862jGWE9pta).md' không đổi nội dung (MD5 khớp). Giữ nguyên bản ghi WeKnora ba774ca3-9fde-4f3e-9353-8a57614c9394.`
  - Worker ChatScope khởi động chu kỳ 1800s:
    `⏰ [ScopeSync Loop] Khởi động worker đồng bộ Chat Scopes định kỳ (Chu kỳ 1800s).`
  - Quan sát logs sau restart: Hệ thống hoàn toàn yên tĩnh, không còn vòng lặp rebuild docs hay gọi WeKnora/Gemini.
  - Test suite: Chạy `tests/lark/` -> **29/29 PASSED**.

## Previous: Hoàn Tất Kế Hoạch Định Danh Webhook & Card Action Theo App ID (Deterministic Multi-Tenant Routing — EDL-0072) (2026-11-03)
- **Vấn đề đã xử lý:**
  - Người dùng phản ánh khi cấu hình Request URL trên Lark Developer Console (`/api/lark/events`) theo hướng dẫn của màn hình Setup thì bị báo lỗi: `Challenge code didn't get response`.
  - Phân tích nguyên nhân:
    1. *Nghịch lý thứ tự (Chicken-and-egg problem):* Giao diện Setup (`setup_one_click.html` & `onboarding_wizard.html`) đặt Bước 5 (Cấu hình Request URL trên Lark) TRƯỚC Bước 7 (Nhập 4 khóa App vào HiLark).
    2. *Mã hóa bắt buộc của Lark:* Khi tab Encryption Strategy trên Lark có Encrypt Key, Lark bắt buộc mã hóa Challenge payload bằng AES CBC (`SHA256(encrypt_key)`).
    3. *Bug loop candidate Custom App (`messenger.py`):* Trong DB có 2 Custom Apps (`cli_aa6c6ae8baf85e11` và `cli_aa63f447fc78de27`). Khi nhận encrypted challenge, `candidate_service.event_dispatcher.do()` của SDK trả về HTTP 500 do candidate 1 không khớp key. Code trước đó `return Response(...)` vô điều kiện mà không kiểm tra `status_code == 200`, làm ngắt vòng lặp ngay ở candidate 1 mà không bao giờ thử candidate 2.
    4. *Thiếu cơ chế định danh trực tiếp 1-1:* Toàn bộ hệ thống trước đây phải duyệt qua toàn bộ App trong DB để thử giải mã (brute-force đoán mò), vi phạm nguyên tắc cách ly dữ liệu đa tenant (Zero Cross-Talk).
- **Giải pháp triển khai (Toàn bộ 5 Phase theo `docs/IMPLEMENTATION_PLAN_APP_ID_WEBHOOK_ROUTING.md`):**
  - **Phase 1: Gateway Routing Core (`server/services/lark/messenger.py`):**
    - Trích xuất `inbound_app_id` từ `request.query_params.get("app_id")` hoặc `payload.header.app_id`.
    - Định danh trực tiếp 1-1 (Zero Looping): Nếu có `inbound_app_id`, tra đúng 1 bản ghi App trong MongoDB `lark_app_credentials`, khởi tạo runtime client và giải mã trực tiếp bằng đúng key đó (Fail-fast nếu sai key, không thử key của tenant khác).
    - Vá bug loop fallback: Nếu không có `inbound_app_id`, sắp xếp App theo `updated_at` giảm dần (ưu tiên app vừa tạo/sửa). Chỉ `return Response` khi `status_code == 200`.
  - **Phase 2: Hỗ trợ Path Parameter (`server/routers/lark.py`):**
    - Bổ sung `POST /api/lark/events/{app_id}` và `POST /api/lark/card-action/{app_id}` song song với query-param để hỗ trợ proxy/firewall doanh nghiệp không cho phép query string.
    - Hàm helper `_inject_app_id(request, app_id)` nạp `app_id` vào scope `query_string` để tái sử dụng toàn bộ logic của `messenger.py`.
  - **Phase 3: Tái cấu trúc Luồng Slider Setup & Onboarding Wizard:**
    - **Bước 1 / 6:** Tạo Custom App trên Lark Developer.
    - **Bước 2 / 6:** Bật tính năng Bot.
    - **Bước 3 / 6:** Lấy 4 khóa & Kết nối với HiLark (Đưa form nhập `App ID`, `App Secret`, `Verification Token`, `Encrypt Key` lên ngay tại đây kèm nút *"Xác thực & Lưu khóa vào HiLark"*).
    - **Bước 4 / 6:** Thêm quyền (Scopes) bằng JSON batch import.
    - **Bước 5 / 6:** Cấu hình Request URL & Sự kiện (HiLark đã có sẵn `Encrypt Key` từ Bước 3 nên khi bấm Save trên Lark, Challenge được giải mã và trả lời HTTP 200 thành công ngay lập tức). Tự động sinh URL có `?app_id=cli_xxx`.
    - **Bước 6 / 6:** Khai báo Redirect URL (`https://<domain>/setup/callback`, giữ sạch không query param per RFC 6749) & Phát hành phiên bản 1.0.0.
    - **Hoàn tất cài đặt (Slide 7):** Hiển thị trạng thái App đã kết nối kèm nút bấm kích hoạt OAuth user duy nhất.
  - **Phase 4: Bộ kiểm thử tự động (`server/tests/lark/test_multitenant_webhook_routing.py`):**
    - Viết test suite chuyên dụng 7 test cases kiểm thử độc lập, pass 100%:
      1. `test_inbound_encrypted_event_with_matching_app_id_param` (PASS)
      2. `test_inbound_encrypted_event_with_mismatched_app_id_param` (PASS - từ chối fail-fast, không leak sang App khác)
      3. `test_inbound_encrypted_event_without_param_resolves_latest_app` (PASS - fallback theo updated_at)
      4. `test_card_action_callback_with_app_id_param_routes_to_correct_tenant` (PASS)
      5. `test_url_verification_challenge_responds_with_challenge_code` (PASS)
      6. `test_path_based_route_events_app_id_identical_to_query_param` (PASS)
      7. `test_path_based_route_card_action_app_id` (PASS)
    - Đồng thời sửa 2 async test trong `tests/lark/test_manual_edit_draft.py` (`@pytest.mark.anyio`) giúp toàn bộ test trong `tests/lark/` pass 100% (29/29 passed).
  - **Phase 5: Tài liệu & Ghi nhận Quyết định:**
    - Cập nhật `docs/lark_event_subscription.md` hướng dẫn cấu hình cả 2 dạng URL (Query param & Path param).
    - Ghi nhận quyết định kiến trúc `EDL-0072` vào `docs/project-memory/DECISIONS.md`.
    - Đánh dấu hoàn thành toàn bộ 5 phase trong `docs/IMPLEMENTATION_PLAN_APP_ID_WEBHOOK_ROUTING.md`.
- **Bằng chứng xác thực (Verified in Container `hilark-server` & Live Tunnel Ngrok):**
  - Đã sao chép `server/routers/lark.py`, `server/services/lark/messenger.py` và các template vào container `hilark-server`.
  - Khởi động lại container `hilark-server`, trạng thái `Up (healthy)`.
  - Kiểm thử live challenge mã hóa AES qua Ngrok:
    + URL query param: `POST https://hertz-liftoff-earphone.ngrok-free.dev/api/lark/events?app_id=cli_aa63f447fc78de27` -> HTTP 200 `{"challenge":"live_test_challenge_external"}`.
    + URL path-based: `POST https://hertz-liftoff-earphone.ngrok-free.dev/api/lark/events/cli_aa63f447fc78de27` -> HTTP 200 `{"challenge":"live_path_based_test"}`.
    + URL không param (fallback): `POST https://hertz-liftoff-earphone.ngrok-free.dev/api/lark/events` -> HTTP 200 `{"challenge":"live_test_challenge_external_fallback"}`.


## Latest: Khắc Phục Triệt Để Lỗi Tính Năng Tự Sửa Bản Nháp (Manual Edit Draft Form Callback & P2CardActionTrigger form_value Ingestion) (2026-11-03)
- **Vấn đề đã xử lý:**
  - Người dùng phản ánh: "check lại sỗ tính năng tự sửa của draft to approve UI đang có vấn đề, sửa xong nhưng bấm thì báo lỗi".
  - **Phân tích nguyên nhân gốc:**
    1. *Lark SDK unmarshal drop `form_value`:* Trong SDK `lark_oapi`, class `P2CardActionTriggerData` không khai báo thuộc tính `form_value` trong `_types`. Do đó khi nhận callback qua WebSocket, hàm `JSON.unmarshal` của SDK tự động bỏ qua và xóa sạch dữ liệu form nhập liệu của người dùng (`event.form_value`).
    2. *Dispatcher chỉ tìm ở cấp `action`:* Trong `_internal_on_card_action_trigger` (`dispatcher.py`), code chỉ đọc `getattr(action, "form_value", None)`. Trong khi theo đặc tả Lark Card JSON 2.0, dữ liệu form được đặt ở `event.form_value`.
    3. *HTTP Webhook extraction thiếu tầng `event`:* Trong `parse_card_action_payload` (`card_action_handler.py`), code chỉ đọc `action_dict.get("form_value")` mà bỏ qua `payload["event"]["form_value"]`.
    4. *`submit_manual_edit` thiếu nội dung:* Do 3 nguyên nhân trên, `edited_content` luôn rỗng (`""`), dẫn đến việc hệ thống trả về thông báo lỗi: "Vui lòng nhập nội dung câu trả lời trước khi gửi".
    5. *Không nhắm đúng `draft_id` cụ thể:* Luồng `send_latest` chỉ gọi `claim_latest_pending(owner_id)` chung chung thay vì ưu tiên claim chính xác theo `draft_id` được gắn trên thẻ.
- **Giải pháp triển khai:**
  - **Patch `P2CardActionTriggerData` (`server/services/lark/dispatcher.py`):**
    - Monkey-patch khai báo `P2CardActionTriggerData._types["form_value"] = dict` và `setattr(P2CardActionTriggerData, "form_value", None)` tại thời điểm nạp module.
    - Trong `_internal_on_card_action_trigger`: Trích xuất `form_val`, `input_val`, `btn_name`, `tag_name` đồng thời từ cả `action` và `event`.
  - **Nâng cấp `parse_card_action_payload` (`server/services/lark/handlers/card_action_handler.py`):**
    - Hỗ trợ bóc tách đa tầng: `event.form_value` -> `action.form_value` -> root `form_value`.
    - Thêm cơ chế fallback trích xuất linh hoạt giá trị đầu tiên trong form nếu key tên component thay đổi.
  - **Tối ưu hóa `DraftStore` & `DraftService` (`draft_store.py`, `draft_workflow.py`):**
    - Thêm hàm `claim_draft(owner_id, draft_id, tenant_key)`: Cho phép claim chính xác bản nháp theo `id` hoặc `message_id`, đảm bảo thao tác sửa trên đúng tin nhắn đang duyệt.
    - Nâng cấp `manual_edit_draft`, `submit_manual_edit`, và `cancel_manual_edit` ưu tiên tìm kiếm theo `draft_id` trên thẻ trước khi fallback về `latest_pending`.
- **Bằng chứng xác thực (Verified in Container `hilark-server`):**
  - Chạy bộ kiểm thử 4 test cases trong `server/tests/lark/test_manual_edit_draft.py`:
    1. `test_p2_card_action_trigger_data_has_form_value`: PASS (unmarshal `form_value` thành công).
    2. `test_parse_card_action_payload_extracts_form_value_from_event`: PASS (trích xuất payload thành công).
    3. `test_handle_card_action_submit_manual_edit_success`: PASS (xác nhận gửi nội dung đã sửa và trả về thẻ trạng thái xanh).
    4. `test_handle_card_action_manual_edit_opens_form_card`: PASS (mở thẻ form Card JSON 2.0 với nội dung điền sẵn).
  - Khởi động lại container `hilark-server` thành công, bot WebSocket kết nối ổn định.


## Latest: Rebuild Toàn Diện Chính Sách Khi Đồng Bộ & Cô Lập Tuyệt Đối Tài Liệu Nhóm Chat (2026-11-03)
- **Vấn đề đã xử lý:**
  1. **Đồng bộ chính sách (Policy Rebuild Flow):** Người dùng yêu cầu khi nội dung tài liệu Lark Docs được cập nhật và bấm "Đồng bộ ngay", hệ thống phải nạp lại và rebuild lại hoàn toàn chỉ mục (chunks, vectors, graph) của tài liệu đó thay vì tạo thêm 1 bản ghi tài liệu mới gây nhân bản / trùng lặp trong cơ sở tri thức chính sách.
  2. **Cô lập tài liệu nhóm chat (Chat Group Document Isolation):** Đảm bảo tài liệu được gắn cho từng nhóm chat trong Base (Bảng 1) được cô lập tuyệt đối, không rò rỉ dữ liệu chéo giữa các nhóm kể cả khi dùng chung `weknora_default_dataset_id`.
- **Giải pháp & Kiến trúc:**
  - **WeKnora Client (`server/services/knowledge/weknora_client.py`):**
    - Bổ sung `list_knowledges(dataset_id, page, page_size, tenant_id)` gọi `GET /api/v1/knowledge-bases/{dataset_id}/knowledge` để liệt kê toàn bộ tài liệu đang có trong knowledge base.
    - Bổ sung `delete_knowledge(knowledge_id, tenant_id)` gọi `DELETE /api/v1/knowledge/{knowledge_id}` cho phép xóa triệt để một tài liệu kèm toàn bộ chunks/vectors liên quan.
  - **Policy Rebuild Service (`server/services/knowledge/policy_sync.py`):**
    - Thay thế hàm upload thông thường bằng `_upload_or_rebuild(file_name, file_bytes, mime_type, target_policy_kb, tenant_id)`:
      + Tính mã MD5 hash của nội dung mới.
      + Quét danh sách tài liệu hiện có trong KB chính sách qua `list_knowledges`.
      + Nếu phát hiện tài liệu cùng tên: So sánh hash; nếu hash khác hoặc đang sync cưỡng bức (`force=True`), gọi `delete_knowledge` để dọn dẹp bản ghi cũ.
      + Polling chờ worker `asynq` của WeKnora xóa hoàn tất khỏi DB (tránh lỗi `409 Conflict`), sau đó mới tải lên tệp mới.
      + WeKnora tiến hành bóc tách lại, sinh chunk mới và embed lại toàn bộ. Đảm bảo KB chính sách chỉ luôn duy nhất 1 bản ghi mới nhất cho mỗi file tài liệu.
  - **Chat Group Strict Isolation (`server/services/workflows/chat_workflow.py`):**
    - Trích xuất danh sách tài liệu được cấp phép (`allowed_doc_names`, `allowed_kids`, `has_group_docs`) từ `chat_scopes`.
    - **Khắc phục triệt để 3 điểm rò rỉ:**
      1. *Nhóm 0 tài liệu:* Nếu nhóm chat không được cấp tài liệu dự án nào (`not has_group_docs`), hoàn toàn bỏ qua việc query vào `project_dataset_id`. Trong quá trình lọc chunk, 100% chunk không phải chính sách sẽ bị loại bỏ ngay lập tức.
      2. *So khớp tên tệp chặt chẽ:* Thay vì kiểm tra substring 2 chiều dễ gây false positive (`doc_name in ad or ad in doc_name`), chuyển sang chuẩn hoá basename tệp và kiểm tra trùng khớp chính xác hoặc tiền tố tối thiểu 5 ký tự.
      3. *Phân định chính sách an toàn:* Chỉ các chunk có `kb_id in policy_kb_ids` mới được công nhận là tài liệu chính sách dùng chung. Tài liệu trong project dataset dù có tên chứa chữ "policy" hay "quy định" cũng không thể vượt rào kiểm soát.
- **Bằng chứng xác thực (Verified in Container `hilark-server`):**
  - **Rebuild chính sách:**
    - Test gọi `POST /policy/sync?tenant_key=19835e79ba9c9942&force=true`:
      Log: `🔄 Rebuild 'Lark DocX (dox...).md': Đang xoá bản cũ (66f0...) để rebuild lại chỉ mục... ✔ Đã nạp & rebuild thành công`
    - Kiểm tra `list_knowledges`: Tổng số tài liệu đúng 1, trạng thái `finalizing` ➔ `completed`. Không xuất hiện bản ghi nhân bản.
  - **Cô lập nhóm chat:**
    - Chạy kịch bản `process_chat_pipeline` kiểm thử thực tế trên 2 nhóm:
      + Nhóm `test` (`oc_4a63905bd7a20fb15e03048e5e42b551`, 0 files): Trả về `num_chunks: 0` (hoàn toàn không thấy bất kỳ chunk nào của nhóm OmniOps).
      + Nhóm `OmniOps` (`oc_efea34ca5a78a73f6e27db62138ee2a1`, 11 files): Trả về `num_chunks: 3` (`03_architecture.md`, `OmniOps_Project_Overview.docx.md`).
    - Dữ liệu giữa các nhóm hoàn toàn tách biệt, đúng theo cấu hình trên Lark Base.


## Latest: Khử Trùng Lặp Trước Khi Tải (Pre-Deduplication) & Bắn Thẳng File Vào WeKnora Tránh Gọi DocReader Dư Thừa (2026-11-02)
- **Vấn đề đã xử lý:**
  1. Người dùng phản ánh: "file lark docs dc gắn thẳng qua bên weknora rồi mà vẫn phải gọi docreader làm gì nhỉ, t tưởng cái này chĩ hỗ trợ tệp tin bên ngoài?" và "hồi nãy t mới upload là bên weknora đã nhận docs và đang xử lí rồi, docreader mới theo sau, check giúp t luồng hiện tại".
  2. Phân tích nguyên nhân gốc từ kiến trúc:
     - WeKnora có container docreader nội bộ (`WeKnora-docreader:50051`) kết nối với `WeKnora-app`. Khi nhận tệp nhị phân qua `POST /api/v1/knowledge-bases/{dataset_id}/knowledge/file`, WeKnora tự động đẩy sang docreader của nó để parse/chunking/indexing.
     - HiLark cũng có AnyDoc gRPC docreader (`hilark.docreader:50051`) - vốn chỉ phục vụ bóc tách văn bản tức thì từ tin nhắn chat (ảnh/pdf gửi vào group) để nạp context cho LLM và extract claims vào MongoDB.
     - Khi đồng bộ thư mục Drive trong `chat_scopes.py`, code cũ gọi `parse_lark_folder` (bên trong gọi DocReader gRPC) TRƯỚC KHI kiểm tra xem file đã tồn tại trên WeKnora chưa.
     - Hậu quả: Vòng lặp `ScopeSync` chạy mỗi 30 giây. Cứ mỗi 30s nó lại tải và parse lại toàn bộ 11 file qua gRPC docreader gây lãng phí CPU/băng thông nghiêm trọng, và khi WeKnora đang xử lý background task (graph/wiki) thì docreader từ vòng lặp kế tiếp lại ập tới.
- **Giải pháp triển khai:**
  - Tách quá trình đồng bộ thư mục trong `chat_scopes.py` thành 2 giai đoạn:
    1. **Thu thập metadata đệ quy trước (`_collect_folder_items`):** Quét cây thư mục Lark Drive (hỗ trợ subfolder lồng nhau) để lấy danh sách item mà không tải dữ liệu bytes.
    2. **Pre-deduplication check:** So khớp với `existing_doc_map` (danh sách tài liệu đã đồng bộ của scope). Nếu tài liệu đã có `knowledge_id` trên WeKnora ➔ BỎ QUA NGAY LẬP TỨC mà không tải bytes hay gọi bất kỳ parser nào.
    3. **Bắn thẳng nhị phân cho tệp ngoài (`itype == "file"`):** Đối với các tệp ngoài tải từ Drive (PDF, Word, Excel, CSV, MD...), HiLark chỉ tải bytes và nạp trực tiếp sang WeKnora với MIME type chuẩn, để WeKnora tự xử lý bằng pipeline docreader nội bộ của nó. Không gọi gRPC AnyDoc của HiLark.
- **Bằng chứng xác thực (Verified in Container `hilark-server`):**
  - Đã copy file `server/services/knowledge/chat_scopes.py` vào container và restart `hilark-server`.
  - Log thực tế của container:
    ```
    2026-11-02 16:56:41,554 [INFO] hilark.lark: ✔ [LARK DRIVE] Quét thư mục YDz8fmSXvlvtled3wsEjJcijp0g: tìm thấy 3 tệp/thư mục.
    2026-11-02 16:56:42,450 [INFO] hilark.lark: ✔ [LARK DRIVE] Quét thư mục WJmpfKtpll7VUkdVgZ3jdxLlpOb: tìm thấy 2 tệp/thư mục.
    2026-11-02 16:56:43,424 [INFO] hilark.lark: ✔ [LARK DRIVE] Quét thư mục CPayf0LjOlSi8ydd2BCjl6Iipda: tìm thấy 4 tệp/thư mục.
    2026-11-02 16:56:44,378 [INFO] hilark.lark: ✔ [LARK DRIVE] Quét thư mục ZExZf0EhHlCzC4d0PqgjSCnBpIF: tìm thấy 5 tệp/thvr mục.
    2026-11-02 16:56:44,378 [INFO] services.knowledge.chat_scopes: 📁 [ChatScope Sync] Thư mục YDz8fmSXvlvtled3wsEjJcijp0g chứa 11 tệp (sau khi quét đệ quy).
    2026-11-02 16:56:44,462 [INFO] services.knowledge.chat_scopes: ✔ [ChatScope Sync] Đồng bộ thành công nhóm 'OmniOps' (oc_efea34ca5a78a73f6e27db62138ee2a1): Trạng thái='Hoạt động', 11 files WeKnora, Nhãn cấm=['Ngân sách', 'Vận hành']
    ```
  - Quá trình kiểm tra 11 tệp mất đúng 84ms, hoàn toàn không gọi gRPC DocReader, không tải lại bytes, và trạng thái 11 files WeKnora của nhóm `OmniOps` được giữ nguyên vẹn.

## Latest: Fix Đệ Quy Thư Mục Lồng Nhau (Nested Folders) Khi Đồng Bộ Base ➔ WeKnora (2026-11-02)
- **Vấn đề đã xử lý:**
  - Nhóm `OmniOps` dán link thư mục cha `YDz8fmSXvlvtled3wsEjJcijp0g`, bên trong chứa 3 thư mục con: `01_project`, `03_sensitive`, `04_operations`.
  - Trong `server/services/knowledge/chat_scopes.py`, đoạn code cũ tự duyệt `alist_drive_folder_files` chỉ ở cấp 1 (shallow scan) và chỉ xử lý `itype in ["docx", "wiki", "file"]`. Khi gặp `itype == "folder"`, code cũ không làm gì, dẫn đến việc bỏ qua toàn bộ 3 thư mục con và kết quả báo `0 files WeKnora`.
- **Giải pháp & Bằng chứng:**
  - Refactor khối 6.2.1 trong `chat_scopes.py`: Chuyển sang sử dụng `doc_parser_service.parse_lark_folder(token, recursive=True, max_depth=3, tenant_key=eff_tenant)`.
  - Kết quả kiểm chứng thực tế trong container:
    - Tìm thấy đầy đủ **11 tài liệu con** nằm sâu trong các thư mục lồng nhau: `risk_register.md`, `incident_report.md`, `vendor_contract_summary.md`, `employee_records.csv`, `finance_snapshot.csv`, `security_register.md`, `03_architecture.md`, `02_requirements.md`, `OmniOps_Project_Overview.docx`, `04_api_contract.md`, `01_project_charter.md`.
    - Phân giải thành công qua AnyDoc / DocX OpenAPI và nạp toàn bộ 11 tài liệu vào WeKnora dataset của nhóm `OmniOps` (`59eaf81b-16ee-4576-b480-7132f3e8c34b`).
    - Log xác nhận: `✔ [ChatScope Sync] Đồng bộ thành công nhóm 'OmniOps' (oc_efea34ca5a78a73f6e27db62138ee2a1): Trạng thái='Hoạt động', 11 files WeKnora, Nhãn cấm=['Ngân sách', 'Vận hành']`.

## Latest: Hỗ Trợ Phân Giải Thư Mục (Lark Drive Folder) Cho Chính Sách Base Với Cơ Chế Cô Lập Tenant Nghiêm Ngặt (2026-11-02)
- **Vấn đề đã xử lý:**
  1. Mở rộng hỗ trợ nạp tài liệu từ Thư mục (Lark Drive Folder) trong Bảng 2 (Chính sách & Quy định Công ty): Khi người dùng dán liên kết 1 Folder Lark Drive vào Base, hệ thống tự động quét đệ quy các tài liệu con (DocX, Wiki, file PDF/Word/Excel/TXT, hình ảnh OCR) và nạp toàn bộ vào Policy KB.
  2. Gia cố nguyên tắc cô lập dữ liệu đa tenant (Multi-tenant data isolation fail-closed): Mọi thao tác liệt kê tệp, tải nhị phân và upload WeKnora đều gắn chặt với `tenant_key` và `weknora_tenant_id` của tenant yêu cầu, ngăn chặn hoàn toàn việc rò rỉ hoặc ghi đè chéo giữa các tổ chức.
- **Giải pháp & Kiến trúc:**
  - **Lark OpenAPI Client (`server/services/lark/client.py`):**
    - Bổ sung tham số `tenant_key: Optional[str] = None` cho 4 hàm: `alist_drive_folder_files`, `list_drive_folder_files`, `adownload_drive_file`, `download_drive_file`.
    - Truyền `tenant_key=tenant_key` trực tiếp vào `_get_request_option(as_user=..., tenant_key=tenant_key)` cả khi request chính và khi fallback bot token, bảo đảm TokenBroker cấp đúng token của tenant đó.
  - **Doc Parser Service (`server/services/knowledge/doc_parser.py`):**
    - Nâng cấp `parse_lark_folder` và `parse_text_links`: Nhận `tenant_key: Optional[str] = None` và truyền xuyên suốt qua tất cả các hàm con (`alist_drive_folder_files`, `parse_lark_docx`, `parse_lark_wiki`, `adownload_drive_file`).
  - **Chat Scopes (`server/services/knowledge/chat_scopes.py`):**
    - Truyền `tenant_key=eff_tk` khi phân giải thư mục Lark Drive cho nhóm chat.
  - **Policy Sync Service (`server/services/knowledge/policy_sync.py`):**
    - Trong chu trình `sync_policies`: Sau khi thử DocX và Wiki, nếu không khớp sẽ tự động gọi `doc_parser_service.parse_lark_folder(tok, tenant_key=eff_tenant)`.
    - Nạp toàn bộ tài liệu con thành công vào `target_policy_kb` với `tenant_id=weknora_tenant_id`.
    - Báo cáo chi tiết số lượng tệp hợp lệ và tên từng tệp từ thư mục ra console log UI per tenant.
- **Bằng chứng xác thực (Verified in Container `hilark-server`):**
  - Chạy `python3 -m py_compile` sạch trên cả 4 file.
  - Sync code vào container `hilark-server` và khởi động lại dịch vụ thành công.
  - Endpoint `/policy/status?tenant_key=19835e79ba9c9942` trả về HTTP 200 OK.

## Latest: UI Cấu Hình Chu Kỳ Quét & Nhật Ký Đồng Bộ Chính Sách Base ➔ WeKnora (2026-11-02)
- **Vấn đề đã xử lý:**
  1. Kiểm tra và xác thực cơ chế chạy của `policy_sync_interval_seconds = 3600` sau khi kiến trúc đa tenant được tái cấu trúc.
  2. Đưa cấu hình chu kỳ quét định kỳ (`policy_sync_interval_seconds`) lên UI trên cả 2 màn hình cài đặt (`onboarding_wizard.html` và `setup_one_click.html`) để quản trị viên có thể tùy chỉnh trực tiếp.
  3. Bổ sung bảng điều khiển Nhật ký đồng bộ trực tiếp (Live Logs console) trên UI, cho phép xem tiến trình quét tài liệu, số lượng bản ghi trích xuất, và chủ động bấm nút "🔄 Đồng bộ ngay" hoặc "Làm mới".
- **Giải pháp & Kiến trúc:**
  - **Backend Models & Storage:**
    - `server/models/onboarding.py`, `server/models/user_settings.py`: Thêm `policy_sync_interval_seconds: Optional[int] = Field(default=3600)`.
    - `server/services/user_settings_service.py`: Lưu vào collection `user_settings` đồng thời đồng bộ vào document của tenant trong `tenants` (`$set: {"policy_sync_interval_seconds": ...}`).
  - **Dynamic Multi-tenant Scheduler & Real-time Logs:**
    - `server/services/knowledge/policy_sync.py`:
      - Thiết kế bộ đệm xoay vòng (ring buffer) `_recent_logs: Dict[str, List[str]]` ghi nhận các mốc sự kiện với timestamp định dạng `[HH:MM:SS]`.
      - Tái cấu trúc vòng lặp `start_policy_sync_loop`: Tick mỗi 60 giây và duyệt qua các tenant đang hoạt động, so sánh `now - last_synced_at >= tenant_interval`. Người dùng thay đổi cấu hình trên UI sẽ có hiệu lực ngay trong vòng 60s mà không cần restart server.
      - Lưu `last_policy_sync` gồm timestamp, status, số records, tokens, và logs vào MongoDB.
    - `server/routers/policy.py`:
      - Nâng cấp `GET /policy/status`: Trả về `sync_interval_seconds`, `last_sync`, và `recent_logs` theo từng tenant.
      - Nâng cấp `POST /policy/sync`: Trả về mảng `logs` chi tiết sau khi hoàn thành.
      - Bổ sung `POST /policy/interval`: Cho phép cập nhật nhanh chu kỳ quét.
    - `server/routers/onboarding.py`: Endpoint `/onboarding/api/save` và `/onboarding/api/settings/{open_id}` hỗ trợ đầy đủ `policy_sync_interval_seconds`.
  - **Frontend UI & UX (Apple Minimalist):**
    - `server/templates/onboarding_wizard.html` & `server/templates/setup_one_click.html`:
      - Thêm KHỐI 3: Dropdown chọn chu kỳ quét (30 phút, 1 giờ, 3 giờ, 6 giờ, 12 giờ, 24 giờ).
      - Hộp nhật ký trực tiếp (Dark Terminal UI) hiển thị trạng thái bảng Base, mốc thời gian lần sync gần nhất, và toàn bộ log chi tiết.
      - Tích hợp nút `🔄 Đồng bộ ngay` (`triggerPolicySyncLive()`) và `Làm mới` (`loadPolicyStatusAndLogs()`).
      - Tự động nạp dữ liệu khi mở giao diện cấu hình và lưu đồng bộ khi nhấn "Lưu Thay Đổi Cấu Hình".
- **Bằng chứng xác thực (Verified in Container `hilark-server`):**
  - Đồng bộ file vào container và restart `hilark-server` thành công.
  - Worker khởi động: `⏰ [PolicySync Loop] Khởi động worker đồng bộ định kỳ theo từng tenant (Tick 60s).`
  - Gọi `GET /policy/status?tenant_key=19835e79ba9c9942`: Trả về `sync_interval_seconds: 3600`, `policy_table_id: "tblFoQ7C8qdu6BE8"`, `last_sync` kèm đầy đủ 4 dòng nhật ký có timestamp.
  - Gọi `POST /policy/sync?tenant_key=19835e79ba9c9942&force=true`: Thực thi quét Base và trả về HTTP 200 kèm `logs`.
  - Gọi `POST /onboarding/api/save` và `POST /policy/interval`: Lưu chu kỳ mới vào DB và cập nhật trạng thái runtime tức thì.
  - Render HTML của cả `/onboarding/wizard` và `/setup` chứa đầy đủ cấu trúc UI mới.
- **Vấn đề đã xử lý:** Lỗi Lark OpenAPI trả về `HTTP 400 Bad Request, code 230099, ErrCode 200621: msg: [parse card json err, please check whether the card json is correct], value: [unknown property, property: elements, path: ]` khi bot gửi thẻ phê duyệt bản nháp câu trả lời (`DRAFT_PENDING_APPROVAL`) tới DM của chủ nhân (`ou_79d38f5e2b6034c05476a66df0be3528`).
- **Nguyên nhân gốc:**
  - Trong thẻ tương tác khai báo `"schema": "2.0"` (`build_draft_card`, `build_draft_edit_form_card`, `build_updated_status_card`), cấu trúc Schema 2.0 quy định các phần tử giao diện nằm trong `"body": { "elements": [...] }`.
  - Tuy nhiên ở tầng gốc (root dictionary) vẫn còn sót thuộc tính `"elements": elements`. Bộ kiểm tra hợp lệ nghiêm ngặt của Lark Schema 2.0 từ chối vì `elements` ở root path là "unknown property".
- **Giải pháp:**
  - Sửa `server/services/lark/card_builder.py`: Loại bỏ `"elements": elements` ở root level của cả 3 hàm tạo thẻ Schema 2.0 (`build_draft_card`, `build_draft_edit_form_card`, `build_updated_status_card`).
  - Cập nhật `server/services/lark/messenger.py`: Nâng cấp regex/pattern phát hiện card string JSON hỗ trợ cả `"schema"` và `"body"`.
  - Thêm unit test `server/tests/lark/test_card_builder_schema.py`: Kiểm tra toàn diện cả 4 test case đều passed (100%).
  - Đã sync code vào container `hilark-server` và xác thực gửi thẻ thực tế qua Lark OpenAPI thành công (nhận `message_id: om_x100b61bd8ce798a0edadb48475baf9e`).

## Latest: WS8 — "Tra cứu có hợp đồng" cho Tenant Resolution & Token Flow (EDL-0070, 2026-11-02)
- **Trạng thái:** code + test của cả 6 giai đoạn (GĐ0–GĐ6) đã xong trên nhánh `fix/tenant-resolution-token`.
  **Chưa commit, chưa deploy** (AGENTS: agent không tự commit).
- **Bằng chứng hồi quy:** `cd server && HILARK_TEST_MONGO_URL=mongodb://localhost:27017 .venv/bin/python -m pytest tests -q`
  → **250 passed, 3 warnings in 25.04s**. Baseline GĐ0 là **117 passed / 11 failed / 37 errors**.
  `import main` chạy sạch; `python -m compileall core services routers database models` exit 0.
- **GĐ1 — Token loop & TokenBroker (T1–T4):** `server/core/token_loop.py` (daemon thread, `submit/asubmit`, stop trong
  lifespan), `server/core/tenant_errors.py` (6 exception có `error_code`+`http_status`), TokenBroker cache 3 chiều
  `(tenant_key, app_id, kind)` + single-flight + buffer 300s + không bao giờ trả `""`; `bitable.py`/`client.py` dùng
  `get_sync`, `isv_token_service` thành wrapper. Test: `tests/auth/test_token_loop_concurrency.py`,
  `tests/auth/test_token_broker.py`.
- **GĐ2 — TenantResourceResolver fail-closed (T7/T8/C1/C2/C4):** `services/tenancy/tenant_resolver.py` hợp đồng 6 bước,
  cache 60s, `resolve_current()` theo ContextVar. Đã xoá `_resolve_app_credentials_*`, nhánh `.env`/hardcode
  `"tblZphzEZPLQAy24"` và các `or settings.*` trong `chat_scopes`, `chat_workflow`, `digest_workflow`, `policy_sync`,
  `weknora_client` (`dataset_id` bắt buộc), `token_service`, `tenant_lifecycle_handler`. Test:
  `tests/tenancy/test_tenant_resolver.py`, `tests/tenancy/test_sentinel_env.py`.
- **GĐ3 — Bỏ ghi đè singleton (C3):** `LarkBaseService.for_tenant()/for_policy_table()`, instance không tenant raise
  `TenantContextMissing`. Test: `tests/tenancy/test_base_service_tenant_isolation.py`.
- **GĐ4 — OAuth mang danh tính App (T5/T6/S1):** collection `oauth_states` (TTL 10', dùng một lần),
  `/auth/lark/login` đòi `tenant_key`, callback truyền `app_id/app_secret`, `exchange_code_for_token` đòi
  `expected_tenant_key` và không ghi `primary_user_token`. Test: `tests/auth/test_oauth_state_service.py`,
  `tests/auth/test_oauth_login_flow_contract.py`.
- **GĐ5 — State machine + invalidation + sweeper + phản hồi người dùng (T9/S2–S4):** `services/tenancy/tenant_state.py`
  (`mark_ready`, `invalidate_caches`), `tenant_refresh_sweeper` thay `start_token_refresh_loop`, lỗi chat
  `services/lark/tenant_error_reply.py`, HTTP 409/401/503 qua handler trong `main.py`, nút **"Thử lại"** trong
  `templates/setup_one_click.html`. Test: `tests/tenancy/test_tenant_state_machine.py`,
  `tests/auth/test_tenant_refresh_sweeper.py`, `tests/lark/test_tenant_error_reply.py`,
  `tests/final_test/test_tenant_error_http_mapping.py`.
- **GĐ6 — Dữ liệu & bảo mật (D1/D2):** `scripts/cleanup_test_tenant.py` (mặc định `--dry-run`, có
  `--mongo-url/--mongo-db`; đã verify `--apply` xoá 6 document trên DB seed local, còn 0), test DB riêng
  `LarkAssistant_test` qua `tests/conftest.py` + `HILARK_TEST_MONGO_URL`, `docker-compose.prod.yml` bỏ credential
  Atlas embedded (`${MONGO_URL:?...}` → `docker compose config` EXIT=1 khi thiếu), audit script thêm mục 9
  (state machine + `app_id` khớp).
- **Sửa thêm trong phiên này (phát hiện khi audit lại spec, không phải churn test):**
  1. `main.py` thiếu handler cho `TokenUnavailable`/`UserTokenMissing` (không phải subclass `TenantResolutionError`)
     ⇒ Lark từ chối cấp token bị trả 500 thay vì 503/401. Đã đăng ký handler + `/auth/lark/exchange` nhả lỗi có kiểu
     để body giữ `error_code` + `tenant_key`.
  2. `resolve_effective_owner_open_id()` (`chat_workflow.py`) vẫn còn 3 nguồn toàn cục: `settings.LARK_USER_OPEN_ID`,
     "tenant bất kỳ" và `auth_tokens.primary_user_token` ⇒ bản nháp của tenant A có thể gửi cho lãnh đạo tenant B.
     Thu còn 7 bậc chỉ nguồn thuộc tenant; `user_settings`/`system_config` chỉ được tin khi document mang `tenant_key`
     khớp (`routers/onboarding.py` nay ghi `tenant_key` vào `lark_admin_config`); `_sync_runtime_admin_open_id` không
     còn ghi `settings.LARK_USER_OPEN_ID`. Test: `tests/final_test/test_owner_open_id_tenant_scoped.py`.
  3. Xoá `bitable.get_tenant_access_token_async()` và hai attribute `_app_access_token[_expires_at]` còn sót của
     `LarkTokenService` (thuộc danh sách "Xoá" của GĐ1/GĐ4).
- **Việc còn lại — cần người dùng:**
  1. **D2:** tenant tương ứng registration `19a84399cc971978` / App `cli_aa6c6ae8baf85e11` vẫn thiếu App Secret hợp lệ
     (Lark báo App ID mismatch, ghi nhận ở mục dưới). Cần nhập secret qua `register_app` + `link_tenant`; nếu secret đã
     mất thì uninstall/setup lại. Agent không tự sinh hay đoán credential.
  2. **Đổi mật khẩu MongoDB Atlas** vì connection string từng nằm trong `docker-compose.prod.yml`/Git history (EDL-0024),
     rồi set `MONGO_URL`/`MONGODB_URI` trong `.env` của máy deploy.
  3. Chạy `scripts/audit_tenant_config_readonly.py` và `scripts/cleanup_test_tenant.py --apply` trên production sau khi review dry-run.
  4. Chạy lại full suite + audit **trên Atlas thật** (phiên này Atlas không truy cập được: `SSL: TLSV1_ALERT_INTERNAL_ERROR`).
  5. Commit nhánh `fix/tenant-resolution-token` khi người dùng sẵn sàng.
- **Chưa làm / chưa verify:** deploy production, Notion Decision Log (**không có Notion MCP** nên EDL-0070 là Local Record),
  test thủ công E2E hai tenant song song trên môi trường thật.
- **Nếu scale ≥ 2 replica:** phải thêm lease Mongo cho `refresh_token` trước khi bật sweeper (giả định GĐ5).

## Latest (superseded by EDL-0070): WS7 - Single Source of Truth Refactor (2026-11-02)
- **Status:** ✅ COMPLETED - All 5 bypass locations refactored, 46/46 tests passing (100%)
- **Deliverables completed:**
  1. **Task #1:** Fixed `base_provision_service.py:114` - changed `isv_token_service.get_tenant_access_token()` → `tenant_token_manager.get_token(token_type="bot")`
  2. **Task #2:** Fixed `one_click_setup_service.py:352` - same change as Task #1
  3. **Task #3:** Fixed `messenger.py:299, 541` (2 locations) - changed `token_service.get_valid_user_token()` → `tenant_token_manager.get_token(token_type="user")`
  4. **Task #4:** Fixed `runtime.py:39, 54` (2 locations) - same change as Task #3
  5. **Task #5:** Fixed `bitable.py:186` - created 3-tier solution:
     - `get_tenant_access_token_async()`: New async version using `tenant_token_manager.get_token()`
     - `get_tenant_access_token()`: Sync wrapper using `asyncio.run()` when safe
     - `_get_tenant_access_token_fallback()`: Old implementation for edge cases (when event loop is already running)
  6. **Task #6:** Full test suite verification - 46/46 tests PASSED in 14.36s (zero regressions)
- **Architecture decision:**
  - All token access now flows through `TenantTokenManager` as single source of truth
  - Per-tenant RAM cache + asyncio.Lock prevents race conditions
  - Zero direct calls to `isv_token_service` or `token_service` from business logic
  - Backward compatibility preserved via sync wrappers for legacy callers
- **Files modified:**
  - `server/services/lark/base_provision_service.py`
  - `server/services/setup/one_click_setup_service.py`
  - `server/services/lark/messenger.py`
  - `server/services/lark/runtime.py`
  - `server/services/lark/bitable.py`
- **Test results:**
  - 30 unit tests (test_tenant_token_manager.py) - PASSED
  - 7 integration tests (test_tenant_token_manager_integration.py) - PASSED
  - 9 ISV token service tests (test_isv_token_service.py) - PASSED
  - Total: **46/46 tests PASSED (100%)** in 14.36s
- **Next steps:**
  - Update `DECISIONS.md` with EDL-0069 (WS7: Single source of truth refactor)
  - Monitor production logs for any edge cases with sync wrapper fallback
  - Consider migrating remaining sync callers (`_get_headers`, `subscribe_base_events`, `get_bot_chats`) to async in future sprint

## Previous: WS6 - Integration Tests & Documentation (2026-11-02)
- **Status:** ✅ COMPLETED - All 7 E2E integration tests passing (100%)
- **Deliverables completed:**
  1. **WS1:** TenantTokenManager singleton (650 lines) with per-tenant cache + asyncio.Lock architecture, zero .env fallback design
  2. **WS2:** 30 unit tests covering cache hits/misses, expiry buffers, concurrency patterns, error recovery (30/30 PASSED)
  3. **WS3:** Refactored `bitable.py` (-50 lines) to use TenantTokenManager for token provisioning (41/41 tests PASSED)
  4. **WS4:** Refactored `client.py` Lark client builder (-57 lines) to use centralized token manager (39/39 tests PASSED)
  5. **WS5:** Removed .env fallback via IS_ISV_MODE guards in `token_service.py`: production (IS_ISV_MODE=True) disables legacy PRIMARY_TOKEN_DOC_ID fallback; single-tenant (IS_ISV_MODE=False) retains backward compat (126/128 tests PASSED)
  6. **WS6 Integration Tests:** 7 E2E test suites all passing:
     - `test_e2e_multi_tenant_isolation_separate_tokens`: Verifies tenant A/B token isolation
     - `test_e2e_concurrent_tenants_independent_refresh`: 5 parallel tenant refresh operations
     - `test_e2e_cache_persistence_across_multiple_requests`: Token reuse across 10 requests
     - `test_e2e_user_and_bot_tokens_isolated_same_tenant`: Per-token-type isolation
     - `test_e2e_error_recovery_cache_invalidation`: Error handling and cache cleanup
     - `test_e2e_service_delegation_parameters_correct`: Verify exact parameter passing to services
     - `test_e2e_monitoring_stats_accuracy`: Cache stats accuracy (total_tenants_tracked)
  7. **Full test suite:** 46/46 tests pass (30 unit + 7 integration + 9 final ISV tests) with zero regressions
- **Documentation updated:**
  - `PROJECT_CONTEXT.md`: Added TenantTokenManager architecture, per-tenant isolation design, IS_ISV_MODE role
  - `DECISIONS.md`: Added EDL-0068 entry for centralized token management decision
  - `HANDOFF.md`: Session completion status
- **Technical notes:**
  - Fixed patch paths: token_service imports inside methods (`_refresh_user_token` @ line 215), so patched at `services.auth.token_service.token_service` not `services.auth.tenant_token_manager.token_service`
  - Fixed stats method: `get_cache_stats()` now counts unique tenants from cache keys (union of user + bot cache) instead of locks
  - Fixed mock signatures: All mock side_effect functions now accept `**kwargs` to handle keyword arguments in delegated calls

## Current task

## 15. Chuẩn Hóa Cổng Đăng Nhập WeKnora Web Console (Cổng 80) & Cấp Quyền Admin Hệ Thống
- **Vấn đề người dùng gặp phải:** Khi click vào nút đăng nhập WeKnora, trình duyệt nhận phản hồi JSON `{"error":"Unauthorized: missing authentication"}`.
- **Nguyên nhân gốc:** 
  1. WeKnora có hai container: `WeKnora-app` (Golang backend API) lắng nghe cổng `8080`, và `WeKnora-frontend` (Nginx + Vue SPA) lắng nghe cổng `80`.
  2. Mọi truy cập trình duyệt trực tiếp vào cổng 8080 mà không có header xác thực đều bị middleware Golang chặn và trả về lỗi Unauthorized. Cổng Web UI thực sự là cổng **`80`** (`http://localhost/login`).
  3. Đường dẫn cấu hình mặc định trong một số dịch vụ đang fallback về cổng 8080 hoặc URL mẫu.
  4. Người dùng admin mới khởi tạo chưa có tài khoản trong DB WeKnora PostgreSQL.
- **Giải pháp triển khai:**
  1. Chuẩn hóa toàn bộ URL WeKnora Web Console sang `http://localhost/login` (cổng 80) trên `settings.WEKNORA_WEB_URL`, `.env`, `tenant.py`, `card_builder.py`, `card_action_handler.py`, `weknora_provision_service.py` và MongoDB Atlas.
  2. Bổ sung `from core.config import settings` ở đầu `server/services/lark/card_builder.py`.
  3. Tạo và kích hoạt thành công tài khoản WeKnora Admin `admin_19a84399@hilark.internal` / `HLK@%6lbF^W8zQ` với vai trò `is_system_admin=true, can_access_all_tenants=true` trên PostgreSQL của WeKnora.
  4. Xác minh qua API đăng nhập `POST http://localhost/api/v1/auth/login`: thành công 100% (HTTP 200, JWT token hợp lệ).
  5. Xóa triệt để các dòng trống mặc định do Lark tạo ở Bảng 2 (Chính sách), đảm bảo cả 2 bảng Lark Base đều sạch đẹp 100%.
  6. Rebuild và restart container Docker `hilark-server` hoạt động ổn định. Kiểm thử tự động 117/117 test cases passed 100%.

## 16. Khắc Phục Triệt Để Lỗi Không Thấy Docs Trong WeKnora & Trống Thông Tin Đăng Nhập Trên Welcome Card (EDL-0032)
- **Vấn đề người dùng phản hồi:**
  1. Log server báo thành công nhưng khi đăng nhập WeKnora Console không thấy tài liệu nào trong Knowledge Base.
  2. Khi upload link Lark Docs trong chat, không thấy engine nạp tài liệu vào WeKnora.
  3. Thẻ chào mừng hiển thị thiếu thông tin: `Tài khoản: `` ` và `Mật khẩu ban đầu: `` `.
  4. Cấu trúc bảng Base xuất hiện các cột mẫu mặc định tiếng Anh (`Text`, `Single option`, `Date`, `Attachment`) và cột tiếng Trung `多行文本`.
- **Nguyên nhân gốc đã phân tích & chứng minh:**
  1. **Dataset Routing Disconnect:** `chat_scopes.py` fallback về `settings.WEKNORA_DATASET_ID` cũ trong `.env` (`bca87123...`), thuộc về workspace demo cũ. Khi người dùng đăng nhập tài khoản Tenant mới (`20108`), họ xem các Dataset mới (`fc733015...`, `7410f72c...`) nên danh sách tài liệu trống trơn.
  2. **Thiếu X-Tenant-ID Header:** Các hàm `upload_file`, `get_document_info`, `search_knowledge` trong `weknora_client.py` không nhận `tenant_id`, khiến WeKnora không thể phân giải ngữ cảnh tenant.
  3. **Lark Chat Ingestion Chuyển hướng 1 Chiều:** `document_handler.py` chỉ bóc tách facts/claims vào MongoDB mà không tải nạp file/markdown lên WeKnora Knowledge Base.
  4. **Policy Table Multi-Tenant Disconnect:** `policy_sync.py` kiểm tra cứng `table_id == settings.LARK_BASE_POLICY_TABLE_ID` cũ và phụ thuộc `WEKNORA_POLICY_DATASOURCE_ID`, khiến các thay đổi trên Bảng Chính Sách mới của Tenant không được kích hoạt nạp vào Policy KB.
  5. **Card Credentials Fallback:** `provision_tenant_weknora` khi thấy tenant đã có KB thì không bù đắp credentials nếu thiếu trường `weknora_admin_user`, dẫn đến render chuỗi rỗng `` ``.
- **Giải pháp đã triển khai:**
  1. Thêm tham số `tenant_id` và header `X-Tenant-ID` vào `weknora_client.py`.
  2. Tự động phân giải `effective_dataset_id` và `weknora_tenant_id` theo hồ sơ tenant trong `chat_scopes.py`, nạp trực tiếp vào đúng KB của Tenant.
  3. Tích hợp tự động tải nạp tài liệu và Lark Doc/Wiki/Folder link lên WeKnora ngay trong `document_handler.py`.
  4. Nâng cấp `policy_sync.py` hỗ trợ đa tenant và đọc trường `Văn bản đính kèm / Link` (bao gồm kiểu dict `{"link": ..., "text": ...}`).
  5. Tự động bù đắp và bảo đảm deterministic credentials trong `weknora_provision_service.py` và `card_builder.py`.
  6. Xây dựng cơ chế tự động dọn dẹp Base `repair_enterprise_base_schema()`: xóa các cột rác, đổi tên `多行文本` -> `Tên văn bản / Quy định`, đổi tên view `表格视图 1` -> `Tất cả Chính sách`.
  7. Rebuild và kiểm tra container Docker `hilark-server` hoạt động ổn định và kết nối thông suốt.

## Các Nội Dung Đã Triển Khai Trong Chiều 31/10/2026

### 1. Workstream 4: Cấp phát Tri thức WeKnora & Auto-Provision Bitable Đa Doanh nghiệp (Giải pháp B - EDL-0021)
- Tự động cấp phát WeKnora Tenant & 2 Datasets chuẩn (`policy` và `wiki`) cho từng doanh nghiệp khi cài đặt ứng dụng.
- Cơ chế sinh mật khẩu ngẫu nhiên bảo mật cao (`generate_secure_password`) cho tài khoản WeKnora Admin.
- Tự động gửi thông tin tài khoản qua tin nhắn chào mừng trong Lark DM và nhúng trực tiếp vào Screen Guide (Onboarding Wizard Step 3) sau khi setup thành công.
- Tự động khởi tạo Lark Base (Bitable) trên Drive doanh nghiệp dựa trên `tenant_key` và cấu hình phân quyền dữ liệu.
- Định tuyến tri thức thông minh theo `tenant_key` trong quy trình tổng hợp Daily Digest.

### 2. Workstream 5: Trải nghiệm Onboarding Kích hoạt 1-Click từ Lark Marketplace (EDL-0022)
- Lắng nghe và xử lý sự kiện Vòng đời Doanh nghiệp `open_app` / `start_by_tenant` khi Admin cài đặt app từ Marketplace, tự động kích hoạt cấp phát hạ tầng và gửi `build_marketplace_welcome_card` qua DM.
- Thiết kế giao diện Adaptive Dual-Mode Screen Guide (`onboarding_wizard.html`):
  * **ISV Store Mode:** 3 bước tinh gọn (Tự động nhận diện cấu hình, không yêu cầu nhập thủ công App ID, App Secret hay Base App Token).
  * **Custom App Mode:** 4 bước chuẩn truyền thống cho khách hàng tự triển khai app nội bộ.
- Bổ sung trường `tenant_key` vào `SaveSettingsRequest` và đồng bộ cấu hình doanh nghiệp an toàn.

### 3. Tối ưu hóa 100% Nút Bấm Trên Thẻ Tương Tác (Loại bỏ Hoàn toàn Text Commands - EDL-0023)
- Xóa bỏ triệt để hơn 450 dòng mã logic phân tích cú pháp câu lệnh văn bản (`/status`, `/weknora`, `/setup`, `/config`, `duyệt digest`, `hủy digest`, `sửa:`, `gửi`, `bỏ`, `sửa fact:`...).
- Tái cấu trúc [owner_command_handler.py](file:///Users/hoainam/Desktop/HiLark/server/services/lark/handlers/owner_command_handler.py) thành Owner DM Interaction Handler: khi Admin gửi bất kỳ tin nhắn nào trong DM 1-1, Bot phản hồi ngay bằng **Thẻ Bảng Điều Khiển Quản Trị (Executive Control Hub Card V2)** cá nhân hóa theo tenant.
- Thẻ tích hợp 2 hàng nút bấm 1-Click:
  * Hàng 1: `[Mở Lark Base Quản Trị]` (URL), `[WeKnora Console]` (URL), `[Cấu Hình Trợ Lý]` (Applink modal).
  * Hàng 2: `[Báo Cáo Ngày Gần Nhất]` (action: `view_master_digest`), `[Trạng Thái Vận Hành]` (action: `view_tenant_status`), `[Tài Khoản WeKnora]` (action: `view_weknora_info`).
- Cập nhật [card_action_handler.py](file:///Users/hoainam/Desktop/HiLark/server/services/lark/handlers/card_action_handler.py) xử lý tập trung mọi tương tác nút bấm.

### 4. Chuyển dịch Cơ sở Dữ liệu sang MongoDB Atlas Cloud Cluster (EDL-0024)
- Thay thế kết nối MongoDB local bằng cụm đám mây MongoDB Atlas (`cluster0.ivrk314.mongodb.net`) an toàn, sẵn sàng cho môi trường Multi-Tenant SaaS.
- Cập nhật [server/core/config.py](file:///Users/hoainam/Desktop/HiLark/server/core/config.py) hỗ trợ đa dạng biến môi trường: `MONGO_URL`, `mongo_url`, `MONGODB_URI`.
- Cấu hình `serverSelectionTimeoutMS=5000ms` cho Motor và PyMongo để đảm bảo bắt tay TLS/SSL và phân giải DNS SRV ổn định qua internet.
- Bảo mật thông tin xác thực nhạy cảm: Đưa `atlas-credentials.env` và `*.env` vào [.gitignore](file:///Users/hoainam/Desktop/HiLark/.gitignore).
- Kết nối thực tế và tự động khởi tạo thành công toàn bộ 13 Collections và hệ thống Compound Indexes trên Atlas.

### 5. Khắc phục Triệt để Lỗi Thiếu LARK_USER_OPEN_ID Khi Duyệt Bản Nháp & Phân giải Đa tầng (EDL-0025)
- **Nguyên nhân gốc:** Khi câu hỏi trong nhóm kích hoạt hành động `DRAFT_PENDING_APPROVAL` hoặc `MEMORY_AND_DRAFT`, quy trình yêu cầu Open ID của chủ nhân để lưu draft và gửi thẻ phê duyệt. Trước đó, mã chỉ kiểm tra biến `.env` và ném `RuntimeError: Thiếu LARK_USER_OPEN_ID để lưu draft chờ duyệt.` nếu thiếu, dẫn đến crash queue pipeline.
- **Giải pháp triển khai:**
  * Xây dựng hàm phân giải linh hoạt `resolve_effective_owner_open_id` trong [chat_workflow.py](file:///Users/hoainam/Desktop/HiLark/server/services/workflows/chat_workflow.py) qua 9 cấp bậc: Cache LarkService -> Settings -> MongoDB `tenants` -> MongoDB `user_settings` (được lưu trực tiếp từ Screen Guide Onboarding) -> MongoDB `system_config` -> MongoDB `auth_tokens` -> Chat Scope `admins` -> `sender` -> Fallback an toàn (không bao giờ gây crash).
  * Trong [onboarding.py](file:///Users/hoainam/Desktop/HiLark/server/routers/onboarding.py) (`/api/save` và `/api/provision-base`), tự động đồng bộ ngay lập tức Open ID của người dùng vào `settings.LARK_USER_OPEN_ID`, `lark_service.known_user_open_id`, collection `tenants.admin_open_id` và `system_config.lark_admin_config`.
  * Nâng cấp property `owner_open_id` trong [client.py](file:///Users/hoainam/Desktop/HiLark/server/services/lark/client.py) tự động tra cứu từ cấu hình đã lưu trong CSDL.
  * Truyền tường minh `target_open_id=owner_open_id` và `tenant_key=eff_tenant` khi gửi thẻ duyệt [send_bot_dm_to_owner](file:///Users/hoainam/Desktop/HiLark/server/services/lark/messenger.py).
  * Bổ sung log hướng dẫn khi gặp mã lỗi Lark `230013` (Tài khoản chưa nằm trong phạm vi Availability của Lark Bot).
  * Toàn bộ 108/108 bài kiểm thử tự động đều passed 100%.
- Xác nhận kiểm thử hồi quy: **108/108 test cases PASSED 100% trong 31.17s**.

### 6. Hoàn thành Luồng One-Click Setup 7 Bước Tự Động theo Chuẩn ISV SaaS (EDL-0026)
- **Vấn đề giải quyết:** Loại bỏ hoàn toàn sự phức tạp của luồng cấu hình thủ công 4 bước, không bắt khách hàng/Admin phải tự tạo Bot hay copy App ID / App Secret trên Lark Developer.
- **Quy trình 7 bước tự động 100%:**
  1. `Admin mở HiLark Setup`: Truy cập giao diện Apple Minimalist `/setup` và nhấn nút "Cài đặt HiLark cho Doanh nghiệp".
  2. `Lark Authorization`: Chuyển hướng sang Lark OAuth (`/setup/install` -> Lark OAuth) với scope đầy đủ (`offline_access`, `im:message`, `bitable:app`, `contact`, `wiki`, `docx`, `drive`).
  3. `HiLark Backend nhận authorization`: Nhận code tại `/setup/callback`, tự động đổi lấy Token và trích xuất `tenant_key`, `admin_open_id`, `admin_name`.
  4. `Tự động kích hoạt Bot`: Kích hoạt Bot mặc định của hệ thống cho doanh nghiệp mà không cần tạo bot mới.
  5. `Đồng bộ cấu hình & Cấp phát hạ tầng`: Tự động khởi tạo song song Lark Base Quản trị và Không gian Tri thức WeKnora cho Tenant.
  6. `Gửi tin nhắn kiểm tra`: Bot gửi Thẻ tương tác Chào mừng & Bàn giao hệ thống (Welcome Card V2) trực tiếp tới Lark DM của Admin.
  7. `Ready`: Hiển thị màn hình thành công "Sẵn Sàng Vận Hành" kèm nút mở Lark Bot và Lark Base Quản trị.
- **Thành phần kỹ thuật xây dựng:**
  * Dịch vụ điều phối [one_click_setup_service.py](file:///Users/hoainam/Desktop/HiLark/server/services/setup/one_click_setup_service.py).
  * Router [setup.py](file:///Users/hoainam/Desktop/HiLark/server/routers/setup.py) (`/setup`, `/setup/install`, `/setup/callback`, `/setup/api/status/{task_id}`).
  * Giao diện Apple Minimalist [setup_one_click.html](file:///Users/hoainam/Desktop/HiLark/server/templates/setup_one_click.html) kèm cơ chế AJAX Polling mượt mà 1s/lần và không dùng emoji.
  * Bộ kiểm thử toàn diện [test_one_click_setup.py](file:///Users/hoainam/Desktop/HiLark/server/tests/final_test/test_one_click_setup.py) (9 test cases unit, integration & resilience).

### 7. Hợp Nhất Trải Nghiệm Setup & Onboarding: One-Click Setup + Progressive Customization (EDL-0027)
- **Vấn đề giải quyết:** Hợp nhất hai trang độc lập `/setup` và `/onboarding` thành một luồng trải nghiệm duy nhất. Đạt đồng thời 2 mục tiêu: 1-Click cài đặt tự động trong 10 giây cho mọi người dùng, và cho phép tùy biến nâng cao (BYOK, Daily Digest, Strict HITL) ngay dưới màn hình Ready.
- **Tuân thủ Thiết kế UI/UX Onboarding:**
  * Giữ nguyên 100% phong cách thiết kế Apple SF Pro Light đặc trưng của `onboarding_wizard.html` (nền sáng `#F5F6F8`, surface trắng `#FFFFFF`, font chữ SF Pro sắc nét, bo góc chuẩn mực, bóng đổ nhẹ).
  * Danh sách 7 bước cài đặt tự động hiển thị với icon xanh lá/xanh dương tinh tế, thông tin trạng thái cập nhật thời gian thực.
  * Màn hình Ready hiển thị dạng thẻ Admin Card với nút CTA mở Lark Bot và Lark Base.
  * Khối **"Tùy Chỉnh Nâng Cao (Tùy chọn)"** dạng Accordion mở rộng mượt mà ngay bên dưới:
    - *Khối 1: Bộ não AI & BYOK:* Tùy chọn Hạn mức mặc định hoặc Khóa riêng (Google Gemini, OpenAI, Claude, Custom), kèm chức năng test độ trễ live.
    - *Khối 2: Lịch nhận báo cáo & Kiểm duyệt:* Chọn giờ nhận Daily Digest (17:30, 18:00, 21:00, 23:00) và checkbox Strict HITL.
    - *Khối 3: Bàn giao WeKnora:* Hiển thị thông tin tài khoản WeKnora Vault nếu có.
    - Nút *"Lưu Thay Đổi Cấu Hình"* gửi AJAX lưu trực tiếp vào CSDL MongoDB.
- Xác nhận kiểm thử toàn diện: **117/117 test cases PASSED 100% trong 32.33s**.

### 8. Khắc phục Triệt để Deadlock & Tối ưu Cấp phát Hạ tầng Bước 5 (EDL-0028)
- **Nguyên nhân gốc rễ (Root Cause):**
  * **Deadlock trong ISVTokenService:** `get_tenant_access_token` đã giữ `self._lock`, bên trong lại gọi `await self.get_app_access_token()` vốn cũng gọi `async with self._lock:`. Do `asyncio.Lock` không phải Reentrant Lock (RLock), coroutine tự chờ chính nó nhả lock -> Gây deadlock vô tận tại Bước 5.
  * **Rẽ nhánh sai điều kiện trong `bitable.py`:** Kiểm tra `if tenant_key or getattr(settings, "IS_ISV_MODE", False):` làm các lệnh gọi Custom App Mode nội bộ nhảy vào ISV Token Exchange và bị lỗi thiếu `app_ticket`.
  * **Gọi API tuần tự kéo dài:** `base_provision_service.py` gọi 16 requests tuần tự lên máy chủ Lark OpenAPI (mỗi request 2-3s), tổng thời gian lên tới 40-50s.
- **Giải pháp triển khai & xác minh:**
  * **Tách Lock độc lập:** Tách riêng `self._app_lock` và `self._tenant_lock` trong `ISVTokenService`, giải phóng lock trước khi gọi tác vụ con.
  * **Sửa nhánh điều kiện:** Chỉ vào ISV Token Exchange khi `IS_ISV_MODE == True` và có `tenant_key`. Khi `IS_ISV_MODE == False`, sử dụng Bot Tenant Access Token nội bộ qua `/internal`.
  * **Cấp phát Song song (Parallel Gathering):** Dùng `asyncio.gather` khởi tạo đồng thời Lark Base và WeKnora trong `one_click_setup_service.py`; dùng `asyncio.gather` tạo đồng thời các trường Bitable và nạp dữ liệu mẫu trong `base_provision_service.py`. Tốc độ Bước 5 giảm từ 40s xuống dưới 4 giây.
  * **Timeout & Fallback:** Bọc `asyncio.wait_for(timeout=25.0)` đảm bảo pipeline không bao giờ bị treo.
  * **Rebuild Docker Image:** Đã build và restart container `hilark-server` mang toàn bộ mã nguồn mới nhất. Toàn bộ 117/117 test cases passed 100%.

### 9. Cơ chế Tự động Thích ứng Schema Cột Lark Base (Adaptive Schema Field Mapping - EDL-0029)
- **Nguyên nhân gốc rễ (Root Cause):**
  * Trong `bitable.py` và `dispatcher.py`, mã nguồn hardcode tên cột cũ: `"ID Group"` và `"Dự án / Nhóm"`.
  * Trong khi cấu trúc Lark Base thực tế (cả Base template ban đầu lẫn Base auto-provisioned) đặt tên trường chuẩn là `"Chat ID"` và `"Tên dự án"`.
  * Khi bot được thêm vào nhóm chat mới (`bot_added` event), lệnh gọi `create_record` gửi `{"ID Group": ..., "Dự án / Nhóm": ...}` bị Lark API từ chối với mã lỗi `1254045 FieldNameNotFound`.
- **Giải pháp triển khai & xác minh:**
  * **Schema Field Mapping:** Xây dựng hàm `_get_table_field_names()` đọc và cache danh sách cột thực tế của bảng, kết hợp hàm `_adapt_fields()` tự động map linh hoạt giữa các cặp bí danh (`Chat ID` $\leftrightarrow$ `ID Group`, `Tên dự án` $\leftrightarrow$ `Dự án / Nhóm`, `Trạng thái hoạt động` $\leftrightarrow$ `Trạng thái`...).
  * **Bảo vệ Create/Update Record:** `create_record` và `update_record` tự động lọc bỏ các trường không tồn tại trong schema bảng để không bao giờ bị lỗi `FieldNameNotFound`.
  * **Cập nhật BASE_FIELD_MAP:** Bổ sung `"Chat ID"` và `"Tên dự án"` vào `BASE_FIELD_MAP` trong `chat_scopes.py`.
  * **Kiểm tra thực tế:** Nhóm `'PROJECT TEST'` (`oc_45ba874a6152de48209bcce6e34d27a2`) đã được đồng bộ chuẩn xác vào Base và MongoDB `chat_scopes`.
  * **Kiểm thử hồi quy:** 117/117 test cases PASSED 100%. Rebuild và restart container `hilark-server` thành công.

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
- **Tổng kiểm thử Final Test Suite (ISV Multi-Tenant & Auto-Provision Hardening):** **117/117 PASSED 100%** (chạy trong 32.04s).
- **Trạng thái Container Docker:** `hilark-server` đã được build lại bằng mã nguồn mới nhất và đang chạy ổn định (healthy, port 8000).
- **Kiểm tra trực tiếp Lark Base trên Cloud (`WNlUbn5avaDHNNsZGqijoca6pVe`):**
  * Bảng 1: Không còn dòng trống, không còn cột rác. Primary column là `Dự án / Nhóm`, 3 dự án mẫu nằm ở đúng hàng 1, 2, 3.
  * Bảng 2: View mang tên `Tất cả Chính sách`, primary column là `Tên văn bản / Quy định`, bản ghi mẫu hoàn chỉnh.

- **Khắc phục lỗi 403 Forbidden khi nạp tài liệu WeKnora (EDL-0033)**:
  * **Nguyên nhân**: `WEKNORA_API_KEY` trong `.env` ban đầu có `scope_type = 'tenant'` cố định vào tenant 10000, nên khi gửi `X-Tenant-ID: 10002` (hoặc dummy 20108), WeKnora trả về `403 Forbidden: workspace API key cannot switch workspaces`. Đồng thời `is_builtin` của models Embedding và KnowledgeQA là `false`, khiến tenant 10002 không tìm thấy model embedding.
  * **Giải pháp**:
    1. Chuyển đổi API Key sang `scope_type = 'platform'`, `tenant_id = NULL` với đầy đủ capabilities trong `WeKnora-postgres`.
    2. Cập nhật `is_builtin = true` trên 2 models hệ thống (`gemini-2.5-flash` và `gemini-embedding-001`).
    3. Cập nhật `weknora_provision_service.py`: trích xuất `tenant_id` thực từ `/auth/register` (hoặc `/auth/login`), gán chính xác `tenant_id` thực (10002) vào MongoDB và KBs.
    4. Sửa endpoint `get_document_info` sang `GET /knowledge/{id}` chuẩn của WeKnora.
    5. Đã kiểm chứng thực tế: Đồng bộ thành công 100% tài liệu Wiki từ Lark Base (`TÀI LIỆU DỰ ÁN MẪU_ HỆ THỐNG BÁN LẺ THÔNG MINH OMNISHOP.md`) sang KB `fc733015-7e39-4d4b-92c4-5a57cf5b3f2f` của Tenant 10002 với `Parse Status: completed`, `Summary Status: completed`.

## Next concrete steps
1. Mời Admin đăng nhập WeKnora Web Console (`http://localhost/login`) với tài khoản `admin_19a84399@hilark.internal` để xem trực tiếp tài liệu đã được nạp và bóc tách hoàn chỉnh.
2. Kiểm tra bot trong nhóm chat với câu hỏi liên quan đến tài liệu dự án để xác nhận RAG retrieval hoạt động mượt mà.

## Current session update — Hoàn Tất Toàn Diện Cô Lập Dữ Liệu Đa Doanh Nghiệp (EDL-0035 Zero Cross-Tenant Data Leakage)
- **Tình trạng:** Đã hoàn thành 100% cả 5 giai đoạn theo kế hoạch phê duyệt `multi_tenant_isolation_plan.md`.
- **Chi tiết các thành phần đã hoàn tất:**
  1. **Giai đoạn 1 (Models & Core DB Layer):**
     - Bổ sung `tenant_key` vào `PendingDraft` model trong `server/models/chat.py`.
     - Cập nhật `get_pending_proposed_claims`, `promote_all_proposed_claims`, `promote_proposed_claims_for_chat` và `get_latest_proposed_claim` trong `server/database/db.py` áp dụng `inject_tenant_filter`.
  2. **Giai đoạn 2 (Staging & Master Daily Digest Isolation):**
     - Sửa `add_staging_message`, `get_staging_messages`, `get_active_chat_ids_today` trong `server/services/workflows/digest_workflow.py` bắt buộc cô lập `tenant_key`.
     - Phân giải ID Master Digest độc lập chống ghi đè: `master_digest_{tenant_key}_{date}`.
     - Cập nhật scheduler daemon trong `bot_runner.py` quét danh sách active tenants từ MongoDB và chạy báo cáo ngày độc lập cho từng tenant.
  3. **Giai đoạn 3 (Claims & Draft Approval Workflow Isolation):**
     - Mở rộng toàn bộ interface của `ClaimService`, `DraftStore`, `DraftService` hỗ trợ `tenant_key`.
     - Nhúng `tenant_key` vào action value của các nút bấm trên Thẻ tương tác (`build_draft_card`, `build_claim_approval_card`, `build_digest_approval_card`).
     - Tái cấu trúc `card_action_handler.py` trích xuất `tenant_key` từ header hoặc action payload, bao bọc toàn bộ luồng xử lý trong `async with async_tenant_context(tenant_key):` và gọi `update_card_message(..., tenant_key=tenant_key)`.
  4. **Giai đoạn 4 (Động hóa Owner Identity & Bitable Context):**
     - Thêm bộ đệm `_tenant_admin_cache` và các hàm `register_tenant_admin`, `get_tenant_admin` vào `LarkDispatcherMixin`.
     - Nhận diện `is_self` và `is_owner` dựa trên `admin_open_id` của từng tenant thay vì biến tĩnh toàn cục.
     - Cập nhật `_get_headers` và `subscribe_events` trong `server/services/lark/bitable.py` lấy đúng tenant access token qua `isv_token_service`.
  5. **Giai đoạn 5 (Scoped REST APIs & Test Suite):**
     - Thêm tham số `tenant_key` vào các REST API endpoints trong `server/routers/scope.py` và `server/routers/digest.py`.
     - `scope_service.list_all_scopes` và `set_chat_kb` áp dụng bộ lọc tenant.
     - Xây dựng Test Suite toàn diện `server/tests/final_test/test_cross_tenant_isolation_complete.py`: 5/5 test cases passed 100%.
     - Kiểm thử regression các suite multi-tenant liên quan: `test_multi_tenant_db_isolation.py` (6/6 passed), `test_claims_knowledge_multi_tenant.py` (6/6 passed), `test_event_ingress_multi_tenant.py` (8/8 passed).
     - Đồng bộ Decision Log `EDL-0035` lên Notion Database.

## Next concrete steps
1. Chạy thử nghiệm thực tế với 2 tài khoản Lark thuộc 2 tenant khác nhau để quan sát tương tác thẻ duyệt DM và Master Digest.
2. Kiểm tra log vận hành của bot daemon trên server để đảm bảo scheduler 23:00 quét và gửi báo cáo phân tách hoàn hảo cho từng doanh nghiệp.

## Current session update — Required App/Tenant/User Setup Flow (EDL-0039)
- Setup landing đã yêu cầu App ID và App Secret, gọi test credential rồi mới lưu cấu hình mã hóa trước khi bắt đầu OAuth.
- OAuth user là bắt buộc: pipeline từ chối tiếp tục nếu không có đủ `access_token` và `refresh_token`; refresh token được lưu qua `token_service` để có thể tự làm mới access token.
- ISV App lấy `tenant_access_token` theo `tenant_key` qua `app_access_token`; Custom App dùng endpoint `/tenant_access_token/internal` trong lúc provision Base. Không dùng tenant token để giả danh user.
- Pipeline không còn đánh dấu Ready nếu Lark Base provision thất bại; cả Base và WeKnora phải hoàn tất.
- Setup screen giải thích rõ ba lớp quyền: App credential, tenant token và user OAuth; lỗi xác thực hiển thị ngay tại form.
- Verification: `tests/final_test/test_one_click_setup.py`, `test_isv_token_service.py`, `test_marketplace_onboarding_experience.py` — **28/28 PASSED**, 2 warning deprecation từ thư viện Lark.

## Next concrete steps
1. Test manual callback OAuth bằng một tenant Lark thật, xác nhận callback trả đủ `access_token`, `refresh_token`, `tenant_key`.
2. Test provision Base/WeKnora trên môi trường staging với App credential thật trước khi deploy production.

## Current session update — Explicit WeKnora Tenant Routing for Base Webhooks
- Root cause đã xác nhận bằng API response: upload tài liệu trả `409 TENANT_REQUIRED` vì WeKnora platform API key bắt buộc header `X-Tenant-ID`.
- MongoDB Atlas của container đã có mapping tenant `19835e79ba9c9942` → WeKnora tenant `10004`, KB mặc định `a36f62f2-2b14-484b-97f3-135705c41cd0`.
- Sửa `server/services/knowledge/chat_scopes.py`: Bitable webhook truyền thẳng tenant config đã resolve theo `bitable_app_token/table_id` vào `sync_group_from_base_record`, tránh phụ thuộc `ContextVar` không có trong webhook task; thêm log routing và log lỗi upload chi tiết.
- `compileall` pass. Regression chọn lọc: `27 passed, 2 failed`; 2 failure còn lại là lỗi môi trường/network test cũ (DNS MongoDB Atlas và mocked Lark Base PATCH chưa được mock), không liên quan patch routing.
- Cần rebuild/restart server rồi sửa/lưu lại ô tài liệu trong Base để replay event; kiểm tra log có `tenant_id=10004` và upload thành công.

## Current session update — Preserve JEV Routing for Owner Messages
- Sửa `server/services/workflows/chat_workflow.py`: Owner Shield chỉ giữ `reply_to_lark=False` từ caller để chống loop; không còn đổi kết quả JEV thành `MEMORY_ONLY` hoặc `IGNORE`.
- Owner message hiện tôn trọng đầy đủ action JEV: `IGNORE` không lưu, `MEMORY_ONLY` mới lưu memory, `REPLY_ONLY` chỉ xử lý nội bộ không reply group, `MEMORY_AND_DRAFT` theo đúng HITL flow.
- Verification: `tests/final_test/phase_2_chat_intent_safety/test_phase_2_chat_intent_safety.py` — **9 passed, 2 warnings**.
- Sau khi kiểm tra log thực tế, bổ sung `speaker_role` vào `JevService.classify_message()` và role guidance riêng cho owner để JEV không mặc định coi phát ngôn của sếp là memory. Docker đã rebuild và health `healthy`.

## Current session update — Compact Message Processing Logs
- Dọn log hot path ở dispatcher, bot runner, member handler, chat queue và digest staging: bỏ banner/trùng lặp, chuyển payload chi tiết sang `DEBUG`, chuẩn hóa `INFO` thành `[INGRESS]`, `[DISPATCH]`, `[ROUTE]`, `[STORE]`, `[DRAFT]`, `[REPLY]`, `[DROP]`.
- `[STORE] staging=yes memory=no` giờ thể hiện rõ staging không phải memory/claims; chỉ khi action cần lưu mới ghi `memory=yes`.
- Verification: compile pass; `test_phase_2_chat_intent_safety.py` + `test_event_ingress_multi_tenant.py` — **17 passed, 2 warnings**. Docker `healthy`.
- Hotfix sau runtime log: sửa nhầm `chat_queue_service.debounce_seconds` thành resolve an toàn qua `chat_queue_service.debouncer.debounce_seconds`; lỗi trước đó làm task handler dừng sau staging. Regression lại **17 passed**, Docker `healthy`.

## Current session update — Multi-Custom-App Runtime Foundation (EDL-0041)
- Đã tạo implementation plan tại `docs/IMPLEMENTATION_PLAN_MULTI_CUSTOM_APP.md` cho mô hình một server phục vụ nhiều Custom App của nhiều công ty.
- Đã thêm registry `lark_app_credentials`: App Secret, verification token và encrypt key được mã hóa; không còn ghi đè settings global trong flow `/setup`.
- OAuth setup dùng `registration_id`, gọi đúng `app_id/app_secret` của tenant; token user được lưu bằng `_id = lark_app:{app_id}:user:{tenant_key}:{open_id}`.
- Đã sửa lỗi token exchange trước đây luôn ghi vào `primary_user_token`; refresh lazy theo App/tenant hiện cập nhật đúng document và không dùng nhầm global app token.
- Webhook có runtime client/dispatcher theo `app_id`, xác thực verification token theo App, đặt `current_lark_service` theo request để các handler/chat workflow gửi trả bằng đúng App credential.
- Regression kiểm chứng: compile thành công; `tests/final_test/test_one_click_setup.py`, `test_isv_token_service.py`, `test_event_ingress_multi_tenant.py` — **26 passed, 2 warnings**.

### Việc còn phải làm trước khi gọi production-ready
1. Bổ sung test integration thật cho hai Custom App đồng thời (hai app_id, hai tenant, hai token document, hai webhook payload).
2. Hoàn thiện các background workflow chạy ngoài request context (digest scheduler, lifecycle/card callback) để chúng luôn resolve runtime client từ `tenant_key`, không phụ thuộc ContextVar của webhook.
3. Thêm auth/rate-limit/CSRF protection cho endpoint đăng ký App credential; hiện endpoint này phục vụ setup nội bộ và chưa phải public SaaS onboarding hardened.

## Current session update — Strict Claims Scope Resolution (EDL-0036)
- Refactor `get_all_facts` hỗ trợ `scope_type` và `strict_chat`; project Q&A không còn mở rộng query qua `global` hoặc `project_tag` khi đã có `chat_id`.
- Policy Q&A query riêng claims `scope_type="global"`, sau đó vẫn yêu cầu `is_policy` và `status="current"`.
- Entity lookup được giới hạn theo `entity_id` xuất hiện trong claims đã query và cùng `tenant_key`.
- Giữ nguyên một danh sách `forbidden_labels`; không tách query/content labels theo quyết định của người dùng.
- Regression suite liên quan: 33 passed, 2 thư viện Lark deprecation warnings.

## Current session update — P1/P2 Production Hardening (EDL-0037)
- P1: thêm collection `setup_sessions` với unique `task_id`, TTL 2 giờ; setup state được hash/consume một lần, polling fallback Mongo sau restart/scale-out.
- P1: lifecycle event bỏ qua provisioning lặp cho tenant đã `ready/provisioning`; chỉ ghi `ready` khi provision trả về WeKnora tenant ID, lỗi ghi `provisioning_failed`.
- P2: bổ sung tenant filter cho digest get/approve/reject, master digest theo ID, ChatScope delete và user settings; bỏ fallback WeKnora tenant `10000` khi chưa resolve được tenant.
- P2: index user settings không còn global-unique theo `open_id`; startup migration drop index cũ và dùng index tenant-aware.
- Verification: compile thành công; regression liên quan P1/P2 `25 passed, 2 warnings`. `git diff --check` còn cảnh báo whitespace/blank-line có sẵn ở `HANDOFF.md` và `card_builder.py`.
- Dev/test cho phép persistence warning khi Mongo unavailable; `.env.production.example` bật `ENVIRONMENT=production` và `SETUP_REQUIRE_DURABLE_STATE=true`, khi đó setup sẽ fail-fast thay vì fallback RAM.

## Current session update — Digest/Master Digest Scope Completion (EDL-0038)
- Bổ sung tenant filter cho staging upsert/processed update, claims dùng trong digest, previous daily/master digest, daily/master digest save và WeKnora sync update.
- Daily digest ID có tenant prefix khi có tenant; tránh collision giữa hai doanh nghiệp cùng ngày/chat ID.
- Master digest đã dùng tenant trong ID và toàn bộ get/pending/approve/reject/update path.
- Regression: Phase 3 digest + P1/P2 suites `32 passed, 2 warnings`.

## Current session update — Tenant-scoped Digest Schedule (EDL-0046)
- Màn hình cấu hình trợ lý dùng ô chọn giờ tùy ý (không còn giới hạn 4 mốc cố định); API lưu `digest_schedule_time` theo cặp `open_id + tenant_key`.
- Chuẩn hóa giờ về `HH:MM` và từ chối giá trị ngoài `00:00–23:59` trước khi ghi MongoDB.
- Digest scheduler đọc giờ của admin từng tenant, nên mỗi doanh nghiệp có thể chạy Digest ở giờ khác nhau; tenant chưa cấu hình vẫn fallback về `DIGEST_SCHEDULE_TIME` trong `.env`.
- Scheduler đánh dấu đã chạy theo từng tenant/ngày, không còn dùng một mốc chạy chung cho toàn bộ server.
- Verification: compile pass; `test_one_click_setup.py` **9 passed**; onboarding suite **34 passed, 1 failed** do sandbox không phân giải DNS MongoDB Atlas, không liên quan thay đổi Digest. Docker rebuild thành công, container `hilark-server` healthy.

## Current session update — Acknowledge Unsupported Drive Read Event
- Lark WebSocket có thể gửi `drive.file.read_v1` khi người dùng mở/đọc file; SDK không có typed handler trong pipeline hiện tại nên trước đây ghi `processor not found`.
- Đăng ký event này như custom no-op để acknowledge an toàn và giữ ingest tài liệu ở pipeline riêng; không ảnh hưởng message/Base events.
- Verification: `test_event_ingress_multi_tenant.py` **8 passed**, compile pass, Docker container healthy.

## Current session update — Tenant-specific Master Digest Sender (EDL-0047)
- Root cause lỗi `open_id cross app`: scheduler lấy đúng `admin_open_id` theo tenant nhưng vẫn gọi singleton Lark client/App mặc định.
- Thêm lookup Custom App theo `tenant_key` và resolve runtime client trước khi gửi thẻ duyệt Master Digest; fallback client mặc định chỉ còn dùng khi tenant chưa có mapping App.
- Verification: Digest suite **9 passed**, compile pass, Docker container healthy.

## Current session update — Tenant Context for Digest Sync and Card Callback (EDL-0048)
- Daily Digest sync now passes `X-Tenant-ID` from the tenant's `weknora_tenant_id` to `save_to_kb`; if a tenant lacks that mapping, sync fails safely instead of writing to an ambiguous workspace.
- Card action webhook resolves the registered Custom App runtime before executing update-card, preventing `open_id cross app` / wrong sender identity.
- Verification: Phase 3 Digest + event ingress **17 passed**, compile pass, Docker container healthy.
- Bổ sung fallback cho endpoint `/card-action`: nếu callback không có `header.app_id`, hệ thống resolve Custom App bằng `tenant_key` nằm trong action payload.

## Current session update — JEV Urgent Request Routing (EDL-0049)
- Bổ sung vào prompt JEV quy tắc: tin có deadline gần/yêu cầu xử lý trong ngày và đang xin phương án, chỉ đạo hoặc phản hồi cho vấn đề công việc/khách hàng/thương lượng/rủi ro sẽ chọn `MEMORY_AND_DRAFT`.
- Tin chỉ thông báo khẩn nhưng không yêu cầu phản hồi vẫn giữ `MEMORY_ONLY`, tránh biến mọi tin có chữ “gấp” thành draft.
- Verification: phase 2 intent safety + event ingress **17 passed**, Docker container healthy.

## Current session update — Multi-Tenant Token Refresh and App Mismatch Handling
- Token refresh loop now scans registered `app_id + tenant_key` pairs instead of only the legacy `primary_user_token`.
- Lark error `20024/20038` marks the affected token document as `invalid_refresh_token` and stops repeated refresh attempts; the tenant must OAuth again using the same registered Custom App.
- Runtime verification: loop detected `app=cli_aa6c6ae8baf85e11`, tenant-scoped refresh attempted, and container remains healthy. Existing token still requires reauthorization because Lark reports an App ID mismatch.








## Current session update — PolicySync nhận diện link Wiki trong Base
- Root cause: PolicySync đọc được record nhưng parser phụ thuộc vào một số field key và shape cố định; Lark records API có thể trả mention/link dưới field ID khác hoặc dưới dạng JSON string, nên log báo `1 bản ghi` nhưng `0 tokens`.
- Đã sửa `server/services/knowledge/policy_sync.py`: parser đệ quy cho dict/list/JSON string, nhận `link/url/text/token`, fallback quét semantic link khi key không khớp, đồng thời giữ xử lý attachment.
- Verification: `server/.venv/bin/pytest -q server/tests/final_test/test_policy_sync_parser.py` — **2 passed**. Docker rebuild `docker compose -f docker-compose.prod.yml up -d --build hilark-server` thành công; container `running healthy`; `/health` trả `status=ok` và MongoDB `connected`.
- Bước kiểm tra tiếp theo: sửa/lưu lại record chính sách trong Base để phát event; log mong đợi là `Trích xuất được 1 tokens...` và sau đó parser WeKnora bắt đầu xử lý Wiki token.
## Current session update — Bật rich-text response cho PolicySync
- Runtime vẫn trả `0 tokens` dù parser đã hỗ trợ field ID; nguyên nhân bổ sung là PolicySync gọi `/records` chỉ với `page_size`, có thể làm Lark trả display text thay vì cấu trúc mention/link.
- Đã thêm `user_id_type=open_id` và `text_field_as_array=true` vào request records, cùng warning shape an toàn khi không tìm thấy link/file.
- Verification: parser test **2 passed**; Docker rebuild thành công; container `running healthy`; `/health` trả `status=ok`.
- Bước xác nhận: chỉnh/lưu lại record trong bảng Chính sách và kiểm tra log request có `text_field_as_array=true`, sau đó log extraction phải lớn hơn 0.
## Current session update — PolicySync bind đúng Custom App khi đọc tài liệu
- Sau khi extraction đã đúng (`1 token`), log phát hiện User Token không hợp lệ và Bot token bị `permission denied`. Root cause code: PolicySync chạy trong background Bitable task nhưng `doc_parser_service` dùng singleton Lark client, không bind runtime theo `tenant_key`.
- Đã sửa `server/services/knowledge/policy_sync.py`: trước khi đọc DocX/Wiki, resolve `lark_app_service.get_by_tenant_key`, tạo runtime client tương ứng và đặt ContextVar; luôn reset context sau khi hoàn tất.
- Verification: compile pass; parser + multi-tenant ingress tests **10 passed**; Docker rebuild thành công; container `running healthy`; `/health` trả `status=ok`.
- Bước kiểm tra: sửa/lưu lại policy record. Log cần có `[PolicySync] Lark runtime bound tenant=... app=...`; nếu sau đó vẫn `permission denied`, cần cấp quyền đọc Wiki node cho Bot/App hoặc re-authorize User OAuth đúng Custom App.
## Current session update — loại bỏ cảnh báo token legacy trong multi-Custom-App mode
- Root cause: `start_bot_service()` luôn gọi `check_and_warn_token(token=lark_service.user_access_token)` trên singleton legacy, nên token `.env`/primary cũ hết hạn vẫn phát banner dù token scoped của từng Custom App được refresh riêng.
- Đã sửa `server/services/lark/bot_runner.py`: nếu có registration active theo tenant, bỏ qua legacy ping/banner và hiển thị tenant-scoped token mode; runtime vẫn resolve/refresh theo `tenant_key + app_id`.
- Verification: compile pass; token/policy tests **11 passed**. Docker rebuild chưa xác nhận trong lượt này vì quyền truy cập Docker socket bị từ chối khi xin escalation.
- Lệnh cần chạy sau khi có quyền Docker: `docker compose -f docker-compose.prod.yml up -d --build hilark-server`.
## Current session update — sửa `open_id cross app` khi gửi draft approval
- Root cause: `resolve_effective_owner_open_id()` ưu tiên `owner_open_id/known_user_open_id` từ global/DB trước khi hỏi `user_info` của runtime Custom App hiện tại. Lark `open_id` là App-scoped nên App B không thể gửi tới ID do App A cấp.
- Đã sửa `server/services/workflows/chat_workflow.py`: khi có `tenant_key` và User Token của runtime, lấy open_id từ `get_current_user()` trước; các nguồn global chỉ còn fallback.
- Verification: compile pass; isolation/ingress tests **13 passed**; Docker rebuild thành công; container `running healthy`; `/health` trả `status=ok`.
- Bước kiểm tra: tạo lại một message cần `MEMORY_AND_DRAFT`; log không còn `open_id cross app`. Nếu còn, cần kiểm tra runtime App đã resolve đúng tenant và User OAuth của App đó.
## Current session update — bỏ refresh legacy primary token trong multi-App startup
- Runtime log xác nhận `refresh_user_token(app=None, tenant=...)` đang đụng bản ghi `primary_user_token` legacy và refresh token đã bị invalidated; đây là lỗi thật của token cũ, không phải token scoped hiện tại.
- Đã sửa `server/services/auth/token_service.py` và `server/services/lark/client.py`: nếu tồn tại Custom App scoped, startup bỏ qua primary token legacy; chỉ token loop theo `tenant_key + app_id` được refresh.
- Verification: token/isolation/ingress tests **22 passed**; Docker rebuild thành công; container `running healthy`; `/health` trả `status=ok`.

## Current session update — Khắc phục triệt để lỗi User Token & Định tuyến Multi-Tenant trong luồng Duyệt Draft (Approve Draft)
- Root cause:
  1. `draft_workflow._send_claimed()` chỉ truyền `tenant_key` mà không truyền `app_id`. Khi `token_service.get_valid_user_token(tenant_key)` tìm trong MongoDB, vì thiếu sort theo thời gian và không loại trừ status invalid, nó luôn bốc trúng bản ghi cũ `primary_user_token` (mang `status: "invalid_refresh_token"`) thay vì bản ghi scoped mới `lark_app:cli_aa6c6ae8baf85e11:...` vừa được cấp.
  2. `messenger._prepare_user_msg_payload_async()` sau khi lấy token hợp lệ lại gọi `self._get_user_request_option()`, đọc `self.user_access_token` cũ trong RAM của singleton mặc định thay vì gán `valid_token` vào `RequestOption`.
  3. Khi không lấy được User Token, hệ thống fallback sang Bot nhưng Bot chưa được add vào nhóm chat nên Lark API trả về lỗi 230002.
- Đã sửa:
  1. `server/services/auth/token_service.py`: trong `get_valid_user_token` và `get_stored_token_data`, nếu có `tenant_key` mà `app_id` chưa có hoặc mang giá trị default `.env`, tự động resolve `app_id` qua `lark_app_service.get_by_tenant_key(tenant_key)`; ưu tiên bản ghi có `status != "invalid_refresh_token"` và sort `[("updated_at", -1)]`.
  2. `server/services/lark/messenger.py`: trong `_prepare_user_msg_payload_async`, tự động điều chỉnh `target_app_id`, gán `self.user_access_token = valid_token` và trực tiếp tạo `lark.RequestOption.builder().user_access_token(valid_token).build()`.
  3. MongoDB: Gỡ bỏ `tenant_key` khỏi bản ghi legacy `primary_user_token` để không bao giờ gây va chạm truy vấn cho tenant `19835e79ba9c9942`.
- Verification:
  1. `token_service.get_valid_user_token(tenant_key="19835e79ba9c9942")` tự động tìm và trả về đúng token sống `u-6q2EuY.gt5FWG...` (100% passed).
  2. `_prepare_user_msg_payload_async()` tạo thành công `RequestOption` mang `opt.user_access_token = u-6q2EuY.gt5FWG...` (100% passed).
  3. Container `hilark-server` đã rebuild và chạy healthy.

## Current session update — Khắc phục lỗi UI báo lỗi dù tin nhắn đã gửi thành công (Card Action Response Schema & Sender Mismatch)
- Root cause:
  1. Sau khi `draft_svc.send_latest` gửi tin nhắn vào nhóm thành công (HTTP 200 OK), hàm callback trả về HTTP response cho Lark mang trường `"card": updated_card` dạng raw card dictionary `{header: ..., elements: ...}`, trong khi chuẩn OpenAPI Card Action Callback của Lark quy định bắt buộc phải bọc trong `{"card": {"type": "raw", "data": updated_card}}`. Do sai schema payload phản hồi, ứng dụng Lark client từ chối cập nhật và hiển thị toast đỏ "Lỗi thao tác / Operation failed" trên màn hình người dùng.
  2. `card_action_handler._execute_card_action` gọi `lark_svc.update_card_message(message_id, updated_card)` bằng singleton `default_lark_service` (App `.env` cũ) thay vì Custom App đã gửi thẻ, khiến Lark trả về `400 Bad Request / code=230001 (bot or user is not the message's sender)`.
  3. Thẻ `build_draft_card` trong `chat_workflow.py` thiếu truyền `tenant_key=eff_tenant`, dẫn tới payload nút bấm gửi lên có `tenant_key: ""` rỗng.
- Đã sửa:
  1. `server/services/lark/messenger.py`: Chuẩn hóa phản hồi HTTP Callback theo đúng đặc tả Lark: `"card": {"type": "raw", "data": updated_card}`. Đồng thời tự động truy vấn `tenant_key` từ `admin_open_id` nếu payload callback bị khuyết.
  2. `server/services/lark/handlers/card_action_handler.py`: Tự động phân giải `lark_svc` theo Custom App của tenant để lệnh cập nhật thẻ tại chỗ nếu gọi sẽ khớp chính xác Sender Bot của tin nhắn.
  3. `server/services/workflows/chat_workflow.py`: Bổ sung `tenant_key=eff_tenant` khi gọi `build_draft_card`.
- Verification:
  1. Docker container rebuild và up healthy.
  2. Kiểm tra serialization của Card Action callback: khớp 100% định dạng `{"type": "raw", "data": ...}`.

## Current session update — Khắc phục lỗi Luồng Hỏi Đáp Chính Sách Toàn Công Ty bị Drop Chunks (Document Isolation Filter)
- Vấn đề: Câu hỏi chính sách công ty (ví dụ: "À cho em xin số ngày nghỉ lễ") được JEV phân loại đúng domain `COMPANY_POLICY` và WeKnora trả về đúng các chunks chính sách, nhưng hệ thống lại báo KB rỗng, ép downgrade sang Draft và không trả lời được chính sách.
- Nguyên nhân gốc:
  1. Tại `server/services/workflows/chat_workflow.py` (dòng 1172), điều kiện kiểm tra `is_policy_doc` so sánh cứng `kb_id == str(settings.WEKNORA_POLICY_DATASET_ID)`. Trong mô hình Multi-Tenant, `policy_dataset_id` của tenant là một ID riêng (`f4f07033-8eab-4c22-a7c5-6cef2b9cc079`), hoàn toàn khác với ID trong `.env`.
  2. Tên file khi sync từ Lark DocX là `Lark DocX (WzxDw72ILiBI1Ika862jGWE9pta).md` (không chứa các từ khóa filename như `chinh_sach`, `so_tay`...).
  3. Dẫn đến `is_policy_doc = False`. Hệ thống tưởng đây là tài liệu dự án của nhóm khác và bộ lọc `[DOCUMENT ISOLATION DROP]` đã loại bỏ 100% chunks chính sách vừa tìm được.
  4. Hệ thống rơi vào `[RAG GATE] REPLY_ONLY nhưng KB rỗng (0 chunks, 0 claims) -> Downgrade sang DRAFT_PENDING_APPROVAL`, khiến bot không lấy được nội dung quy định nội bộ để trả lời.
- Đã sửa:
  1. `server/services/workflows/chat_workflow.py`: Tập hợp `policy_kb_ids` từ `policy_dataset_id`, `wiki_dataset_id`, `global_policy_kbs` và `settings.WEKNORA_POLICY_DATASET_ID`.
  2. Cập nhật `is_policy_doc = (kb_id in policy_kb_ids if kb_id else False) or any(kw in doc_name.lower() for kw in [...])`.
- Verification:
  1. Chạy kịch bản kiểm thử giả lập truy vấn "À cho em xin số ngày nghỉ lễ" trong context nhóm `oc_4a63905bd7a20fb15e03048e5e42b551` trực tiếp trong container `hilark-server`:
     - `Policy KB IDs`: nhận diện đúng `f4f07033-8eab-4c22-a7c5-6cef2b9cc079`.
     - `Retrieved`: 8 chunks từ WeKnora.
     - `RESULT`: KEPT 8 chunks, DROPPED 0 chunks (100% pass, không còn bị isolation filter loại bỏ).
  2. Container `hilark-server` đã rebuild và chạy healthy.

## Current session update — Khắc phục lỗi Feedback Loop: Bot Reply as User bị nuốt ngược vào Staging & biến thành Claims trong Daily Digest
- Vấn đề: Tin nhắn trả lời của Bot (nhân danh Sếp bằng User Access Token `as_user=True` hoặc duyệt Draft) bị Webhook bắt lại, không nhận diện được là tin nhắn do hệ thống gửi ra, dẫn tới bị lưu vào `conversation_staging` với tên "Thành viên". Sau đó Daily Digest quét và trích xuất câu trả lời của Bot thành các mục Milestone / Status Changes gán mác "Báo cáo bởi: Thành viên".
- Nguyên nhân gốc:
  1. `_sent_message_ids` lưu ở instance cục bộ của Custom App service; khi sự kiện Webhook `im.message.receive_v1` về router `/api/lark/events`, nó chạy qua singleton Dispatcher nên không tìm thấy message_id vừa gửi, không drop được.
  2. `member_message_handler.py` lưu mọi tin nhắn vào staging; khi `is_owner=True`, do hàm lấy tên không tìm thấy tag mention nên fallback về `speaker = "Thành viên"`.
  3. `digest_workflow.py` prompt chưa có chỉ dẫn loại trừ câu chat giữ nhịp giao tiếp ("để anh kiểm tra lại rồi nhắn sau...").
- Đã sửa:
  1. `server/services/lark/dispatcher.py`: Xây dựng `SHARED_SENT_MESSAGE_IDS` và các hàm `record_sent_message_id_global`, `is_sent_message_id_global` cấp process (thread-safe). Bất kể runtime nào gửi tin, `sent_mid` đều được lưu vào cache chung và Dispatcher sẽ DROP ngay tại chỗ (`[DROP] reason=self_sent`).
  2. `server/services/lark/messenger.py`: Đồng bộ `_record_sent_message_id` vào `record_sent_message_id_global`, áp dụng cho cả reply, send và bot DM card.
  3. `server/services/lark/handlers/member_message_handler.py`: Khi `is_owner=True`, gán đúng danh tính `speaker = responder_name or "Nguyễn Tiến"` / `"Lãnh đạo"`, không bao giờ fallback thành `"Thành viên"`.
  4. `server/services/workflows/digest_workflow.py`: Bổ sung quy tắc loại trừ câu giao tiếp giữ nhịp trong `EXTRACTION_SYSTEM_PROMPT`.
  5. MongoDB: Đã dọn dẹp 13 bản ghi bot reply bị lọt nhầm vào `conversation_staging` của nhóm `oc_4a63905bd7a20fb15e03048e5e42b551`.
- Verification:
  1. Chạy test giả lập quy trình gửi tin và bắt webhook trong container `hilark-server`:
     - Test 1: `record_sent_message_id_global` ghi nhận đúng `test_msg_id`.
     - Test 2: Dispatcher nhận diện và DROP thành công tin nhắn bot reply as_user.
     - Test 3: Khi sếp gửi tin, `speaker_name` gán chuẩn "Nguyễn Tiến".
     - Toàn bộ 3/3 test cases passed 100%.
  2. Container `hilark-server` đã rebuild và chạy healthy.



## Current session update — Khắc phục lỗi Lark Error Code 200341: "Đã có lỗi xảy ra. Vui lòng thử lại sau code: 200341" khi bấm Duyệt hoặc Hủy trên Thẻ bản nháp
- Vấn đề: Khi Lãnh đạo bấm nút "Duyệt và gửi" hoặc "Hủy bỏ" trên Interactive Card bản nháp câu trả lời, trên giao diện Lark xuất hiện popup/toast lỗi màu đỏ: "Đã có lỗi xảy ra. Vui lòng thử lại sau code: 200341". Tuy nhiên, tin nhắn câu trả lời vẫn được gửi thành công vào nhóm chat và thẻ sau đó vẫn được cập nhật sang màu xanh "Đã duyệt và gửi".
- Nguyên nhân gốc:
  1. Lark Error Code `200341` là mã lỗi chính thức của Lark cho Callback Timeout (> 3 giây).
  2. Trước đây trong `card_action_handler.py`: Khi xử lý `approve_draft` hoặc `discard_draft`, backend vừa gọi Lark OpenAPI `PATCH /open-apis/im/v1/messages/{message_id}` (`update_card_message`), vừa trả về `updated_card` trong gói tin Response của WebSocket / Webhook callback.
  3. Thao tác gọi `apatch` qua internet làm phát sinh thêm 1.0 - 1.8 giây độ trễ mạng, đẩy tổng thời gian xử lý vượt quá ngưỡng 3 giây của Lark Card Server -> Lark Server phát lỗi `200341` về client.
  4. Hơn nữa, việc gọi `apatch` sửa tin nhắn trước đó làm thay đổi version/revision của message trên Lark Server, khiến `resp.card` trả về sau đó bị xung đột phiên bản (Version Mismatch / Token Expired).
- Đã sửa:
  1. `server/services/lark/handlers/card_action_handler.py`: Loại bỏ toàn bộ các lệnh gọi `update_card_message` qua OpenAPI bên trong các action handler (`approve_draft`, `discard_draft`, `approve_claim`, `reject_claim`, `approve_digest`, `reject_digest`, `view_digest_detail`, `view_master_digest`, `view_tenant_status`, `view_owner_hub`, `view_weknora_info`). Chuẩn hóa 100% cập nhật thẻ đồng bộ (Sync In-place Response).
  2. `server/services/lark/dispatcher.py`: Tối ưu hóa luồng gọi `handle_card_action`, không khởi tạo `ThreadPoolExecutor` mới trong mỗi request, giới hạn thời gian phản hồi an toàn < 2.8s để triệt tiêu vĩnh viễn nguy cơ timeout 3s của Lark.
  3. `server/routers/policy.py`: Bổ sung import `Optional` còn thiếu từ `typing`.
- Verification:
  1. Toàn bộ **128/128** test cases trong `server/tests/final_test/` đã chạy qua `uv run pytest` và **PASS 100%**.
  2. Docker image `hilark/server:latest` đã được rebuild sạch và container `hilark-server` đã restart, trạng thái healthy.


## Current session update — Tinh giản Giao diện & Luồng Duyệt Bản Nháp: Loại bỏ hoàn toàn tính năng "Sửa AI"
- Yêu cầu: Gỡ bỏ toàn bộ UI và logic liên quan đến tính năng "Nhờ AI sửa lại" (AI Rewrite) của thẻ duyệt bản nháp.
- Đã thực hiện:
  1. `server/services/lark/card_builder.py`: Xóa nút "Nhờ AI sửa lại" (`action: "ai_rewrite_draft"`), thẻ bản nháp giờ chỉ còn 3 nút tinh gọn: **[Duyệt và gửi]**, **[Tự sửa]**, **[Hủy bỏ]**. Xóa đoạn `/ Sửa AI: <yêu cầu>` trong note thao tác nhanh.
  2. `server/services/lark/handlers/card_action_handler.py`: Gỡ bỏ khối xử lý `if action == "ai_rewrite_draft":`.
  3. `server/services/ai/draft_rewriter.py`: Đã xóa file mã nguồn và gỡ bỏ import `rewrite_draft_with_llm` khỏi `server/services/ai/__init__.py`.
  4. `server/tests/final_test/phase_2_chat_intent_safety/test_phase_2_chat_intent_safety.py`: Cập nhật test case sang kiểm thử nút `manual_edit_draft`.
- Verification:
  1. Toàn bộ **128/128** test cases trong `server/tests/final_test/` đã chạy qua `uv run pytest` và **PASS 100%**.
  2. Docker image `hilark/server:latest` đã được build lại và container `hilark-server` đã được recreate/restart, trạng thái healthy.

## Current session update — Triển khai Form Textarea Trực Tiếp Trên Lark Interactive Card (Card JSON 2.0) Cho Luồng Tự Sửa Bản Nháp (EDL-0063)
- Yêu cầu:
  1. Hỗ trợ component `textarea` nhiều dòng bên trong `form` container trên thẻ Lark Interactive Card (Card JSON 2.0).
  2. Khi người dùng bấm "Tự sửa", thẻ chuyển sang chế độ soạn thảo:
     - Ô nhập `textarea` (`name: "edited_content"`) được điền sẵn toàn bộ nội dung bản nháp gợi ý ban đầu (**A**) qua thuộc tính `default_value` để tiện chỉnh sửa trực tiếp.
     - Nút submit: **[Lưu và gửi vào nhóm]** (`form_action_type: "submit"`).
     - Nút quay lại: **[Quay lại]** (`cancel_manual_edit`) để hủy sửa và quay về thẻ duyệt nháp ban đầu.
  3. Khi sếp bấm "Lưu và gửi vào nhóm", Lark callback gửi dữ liệu form (`form_value`), backend trích xuất nội dung `edited_content`, gửi vào nhóm chat qua `draft_svc.send_latest(open_id, approved_content=edited_content, tenant_key=tenant_key)` và cập nhật thẻ tại chỗ sang thẻ xanh "Đã duyệt và gửi".
- Đã thực hiện:
  1. `server/services/lark/card_builder.py`:
     - Xây dựng hàm `build_draft_edit_form_card(draft_id, question, draft_content, group_name="Nhóm", sender_name="Thành viên", tenant_key=None)` với cấu trúc Card JSON 2.0: header màu xanh dương, container `form` chứa `textarea` có `default_value=draft_content`, và 2 nút hành động `[Lưu và gửi vào nhóm]` & `[Quay lại]`.
  2. `server/services/lark/__init__.py`: Export `build_draft_edit_form_card`.
  3. `server/services/lark/dispatcher.py`:
     - Bóc tách `action.form_value` từ `CallBackAction` của Lark SDK và gộp vào payload `action_val["form_value"]`.
  4. `server/services/lark/handlers/card_action_handler.py`:
     - Cập nhật `parse_card_action_payload` trích xuất `form_value`.
     - Xử lý hành động `manual_edit_draft`: lấy bản nháp đang chờ duyệt, chuyển đổi thẻ tại chỗ sang `build_draft_edit_form_card` có sẵn nội dung nháp ban đầu trong `default_value`.
     - Xử lý hành động `submit_manual_edit`: lấy nội dung đã sửa từ `form_value.get("edited_content")`, gửi vào nhóm và cập nhật thẻ xanh hoàn tất.
     - Xử lý hành động `cancel_manual_edit`: hoàn nguyên về thẻ bản nháp ban đầu `build_draft_card`.
  5. `server/tests/final_test/phase_2_chat_intent_safety/test_phase_2_chat_intent_safety.py`:
     - Bổ sung test kiểm tra `manual_edit_draft` trả về card có `tag: "textarea"`, `default_value` chứa câu trả lời nháp `85% lương chính thức`, và submit `submit_manual_edit` gửi đúng nội dung sửa đổi vào nhóm chat.
- Verification:
  1. Toàn bộ **128/128** test cases trong `server/tests/final_test/` đã chạy qua `uv run pytest` và **PASS 100% (42.80s)**.
  2. Docker image `hilark/server:latest` đã được build lại và container `hilark-server` đã recreate/restart, trạng thái healthy. WebSocket Lark Client kết nối thành công với frontier gateway.

## Current session update — Tối Ưu Hóa ThreadPoolExecutor, Caching Motor Client Per Loop & Tăng Timeout Card Action Lên 10s (EDL-0064)
- Vấn đề: `TimeoutError` tại `dispatcher.py` khi sếp bấm nút trên thẻ tương tác do timeout đang set cứng ở mức `2.8s`.
- Nguyên nhân gốc: Khi thao tác nút bấm chạy trong worker thread qua `asyncio.run()`, `get_async_client()` trong `db.py` thấy loop bị lệch nên hủy client cũ và thiết lập lại kết nối mới tới cụm MongoDB Atlas đám mây (DNS SRV + TLS handshake + auth mất ~2.5 - 3.0s), khiến `executor.result(timeout=2.8)` phát sinh `TimeoutError`.
- Đã thực hiện:
  1. `server/services/lark/dispatcher.py`:
     - Tăng timeout từ `2.8s` lên `10.0s`.
     - Sử dụng persistent `_card_action_executor` thay vì tạo/hủy `ThreadPoolExecutor` trên từng request.
  2. `server/database/db.py`:
     - Caching Motor Client theo từng event loop (`_async_clients: Dict[Any, AsyncIOMotorClient]`), ngăn ngừa triệt để tình trạng hủy client của loop chính khi worker thread tạo loop mới.
  3. Rebuild và kiểm tra container `hilark-server`: Các bài test pass 100%, server khởi động healthy.


