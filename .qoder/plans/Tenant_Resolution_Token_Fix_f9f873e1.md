# Kế hoạch sửa Tenant Resolution & Token Flow

## Tóm tắt

**Vấn đề gốc:** không có một nơi duy nhất xác định "cấu hình và token này thuộc tenant nào"; mỗi chỗ tự đoán theo thứ tự tenant → App bất kỳ → `.env`, và lặng lẽ dùng dữ liệu của người khác khi đoán hỏng.

**Hướng sửa:** "đoán" → "tra cứu có hợp đồng". Thiếu là raise exception có kiểu, không có giá trị thay thế.

**Bối cảnh đã xác minh:**
- Production: 1 container `hilark-server`, `uvicorn main:app` 1 worker → cache RAM là đủ, **không** làm lease Mongo.
- Mọi file mục tiêu đang có thay đổi chưa commit → bắt buộc làm Giai đoạn 0 trước.
- `get_async_client()` đã tạo Motor client riêng theo từng loop → token loop dùng được Motor an toàn.

## Giai đoạn 0 — Baseline (bắt buộc, không sửa code)

- Người dùng commit hoặc tạo nhánh từ trạng thái hiện tại (`git status` có ~30 file `M`, 1 file `D`). Agent **không** tự commit/stash.
- Tạo nhánh làm việc `fix/tenant-resolution-token`.
- Chạy baseline: `cd server && .venv/bin/python -m pytest tests -q` → ghi lại số pass/fail làm mốc so sánh.
- Chạy `scripts/audit_tenant_config_readonly.py` → lưu output làm mốc dữ liệu.

## Giai đoạn 1 — Token loop & TokenBroker (sửa T1, T2, T3, T4)

**File mới `server/core/token_loop.py`**
- Một daemon thread chạy một event loop suốt vòng đời process; khởi động lazy, an toàn thread (`threading.Lock`).
- `submit(coro, timeout=15.0)` cho caller sync: `run_coroutine_threadsafe(...).result(timeout)`; timeout → raise `TokenUnavailable`.
- `async asubmit(coro)` cho caller async ở bất kỳ loop nào: `await asyncio.wrap_future(run_coroutine_threadsafe(...))`.
- Nếu đang chạy **chính trên** token loop thì `asubmit` await trực tiếp (tránh tự deadlock).
- Đăng ký stop trong lifespan shutdown của `main.py`.

**File mới `server/core/tenant_errors.py`** — exception có kiểu, dùng chung toàn dự án:
`TenantContextMissing`, `TenantNotFound`, `TenantNotReady(status)`, `TenantConfigIncomplete(missing_fields)`, `TokenUnavailable(reason)`, `UserTokenMissing` (cần uỷ quyền lại).

**Sửa `server/services/auth/tenant_token_manager.py` thành TokenBroker**
- API công khai duy nhất: `async get(tenant_key, kind: "app"|"tenant"|"user") -> str` và `get_sync(...)` (qua `submit`).
- Mọi lời gọi `get` đều nhảy sang token loop qua `asubmit` → lock và cache chỉ tồn tại trên một loop.
- Cache key = `(tenant_key, app_id, kind)`; `app_id` lấy từ resolver (Giai đoạn 2; tạm thời đọc `lark_app_credentials` theo tenant_key, thiếu → raise).
- Single-flight: `asyncio.Lock` theo key, double-check sau khi lấy lock. Buffer hết hạn 300s.
- Provider tách riêng, **không cache, không fallback**:
  - `CustomAppProvider`: `app` → `/auth/v3/app_access_token/internal`; `tenant` → `/auth/v3/tenant_access_token/internal` với `(app_id, app_secret)`.
  - `ISVProvider`: giữ logic `app_ticket` hiện có của `isv_token_service`.
  - `UserTokenProvider`: đọc `lark_auth` theo `(app_id, tenant_key)`, refresh khi còn <10 phút; không có → `UserTokenMissing`.
- Chọn provider theo `settings.IS_ISV_MODE`; bỏ `raise ValueError` ở `_refresh_bot_token` khi Custom App.
- Lỗi provider → raise `TokenUnavailable` kèm mã lỗi Lark; **không** trả `""`.
- `invalidate(tenant_key, kind=None)` giữ nguyên chữ ký, xoá mọi key có `tenant_key` đó.

**Sửa `server/services/lark/bitable.py`**
- Xoá: `self._tenant_token`, `self._tenant_token_expires_at`, `get_tenant_access_token_async`, `_get_tenant_access_token_fallback`, `_resolve_app_credentials_sync`, mọi `asyncio.run(...)` ở L283-288 và L390-403.
- `_get_headers` gọi `token_broker.get_sync(tenant_key, kind)`; `tenant_key` lấy từ field instance (Giai đoạn 3) hoặc ContextVar; thiếu → `TenantContextMissing`.

**Sửa `server/services/lark/client.py`** L307-332: thay `asyncio.run(tenant_token_manager.get_token(...))` bằng `get_sync`. L82-83 bỏ `or settings.LARK_APP_ID/SECRET`.

**Sửa `server/services/auth/isv_token_service.py`** L465, L471-508: `get_tenant_access_token_sync` và `_get_custom_app_tenant_token*` chuyển thành wrapper gọi broker.

**Ngoài phạm vi giai đoạn này:** `asyncio.run` trong `dispatcher.py`, `messenger.py:617`, `draft_workflow.py:56`, `docreader_client.py:312`. Chúng vẫn an toàn sau thay đổi vì mọi truy cập token đều nhảy sang token loop.

## Giai đoạn 2 — TenantResourceResolver (sửa T7, T8, C1, C2, C4)

**File mới `server/services/tenancy/tenant_resolver.py`**
- `TenantResources` (frozen dataclass): `tenant_key, app_id, app_secret, verification_token, encrypt_key, base_app_token, chat_scope_table_id, company_policy_table_id, weknora_tenant_id, weknora_policy_dataset_id, weknora_wiki_dataset_id, weknora_default_dataset_id`.
- `async resolve(tenant_key) -> TenantResources` và `resolve_sync` (qua token loop):
  1. `tenant_key` rỗng → `TenantContextMissing`.
  2. Không có doc `tenants` → `TenantNotFound`.
  3. `status != "ready"` → `TenantNotReady(status)`.
  4. Không có `lark_app_credentials {tenant_key, status != revoked}` → `TenantConfigIncomplete(["app_credentials"])`.
  5. `tenants.app_id` khác `credentials.app_id` → `TenantConfigIncomplete(["app_id_mismatch"])`.
  6. Thiếu field bắt buộc → `TenantConfigIncomplete(missing)`.
- `app_id` + `app_secret` luôn lấy **từ cùng một document** credential.
- Cache RAM theo `tenant_key`, TTL 60s; `invalidate(tenant_key)`.
- `resolve_current()` đọc tenant từ ContextVar của `database/scoped_query.py`.

**Xoá**
- `_resolve_app_credentials_sync_safe`, `_resolve_app_credentials_async` (`isv_token_service.py:42-132`) và `_resolve_app_credentials_sync` (`bitable.py:82`). Đổi các chỗ gọi: `token_service.py:125`, `base_provision_service.py:86`, `isv_token_service.py:474,494`, `bitable.py:316,1012`.
- Nhánh `.env` / hardcode `"tblZphzEZPLQAy24"` trong `base_provision_service.get_active_base_config`.

**Thay `or settings.*` bằng `resolver.resolve(...)`** (danh sách đã grep):
- `chat_scopes.py:307, 786, 792, 797, 802`
- `chat_workflow.py:994, 1001, 1009`
- `digest_workflow.py:596`
- `policy_sync.py:316`
- `weknora_client.py:172, 215` → `dataset_id` thành tham số bắt buộc; rỗng → `ValueError`.
- `token_service.py:130-131, 198`
- `tenant_lifecycle_handler.py:61` → `app_id` chỉ lấy từ event/header; thiếu → log error và bỏ qua event.

**Giữ nguyên:** override theo từng group (`raw_kb_field`, `digest.weknora_kb_id`) vẫn được ưu tiên trước giá trị của tenant — chỉ bỏ tầng `.env` cuối cùng.

## Giai đoạn 3 — Bỏ ghi đè singleton (sửa C3)

- `LarkBaseService.__init__` nhận `tenant_key` bắt buộc; thêm factory `LarkBaseService.for_tenant(resources, app_token=None, table_id=None)`.
- Thay mọi phép gán field của singleton bằng instance tạo theo request:
  - `chat_scopes.py:1113-1115, 1186-1188`
  - `dispatcher.py:513-515`
  - `bot_runner.py:262, 362-363`
  - `base_provision_service.py:511-512`
  - `token_service.py:644, 662`
- Giữ `lark_base_service` module-level chỉ để tương thích import, nhưng mọi method cần tenant sẽ raise `TenantContextMissing` nếu instance không có `tenant_key`.
- Sửa `messenger.py`: thay `getattr(self, "tenant_key", None)` bằng tenant từ ContextVar.

## Giai đoạn 4 — OAuth mang danh tính App (sửa T5, T6, S1)

**Collection mới `oauth_states`**: `{_id: state, tenant_key, app_id, purpose, created_at, consumed_at}`; TTL index 10 phút trên `created_at`.

- `oauth_state_service.create(tenant_key, app_id, purpose)` và `consume(state)` dùng `find_one_and_update({_id, consumed_at: null}, {$set: {consumed_at}})` → dùng đúng 1 lần.
- `/auth/lark/login`: yêu cầu `tenant_key` hợp lệ (từ setup task hoặc phiên admin); resolve App của tenant; `client_id = resources.app_id`; `state` do service sinh. Không có tenant → trang lỗi "Mở từ màn hình setup".
- `/auth/lark/callback` nhánh thường: `consume(state)` → không hợp lệ → 400; truyền `app_id`, `app_secret` vào `exchange_code_for_token`.
- `exchange_code_for_token`: `app_id`, `app_secret`, `expected_tenant_key` bắt buộc; `tenant_key` từ profile Lark phải bằng `expected_tenant_key`, khác → raise. Xoá nhánh `PRIMARY_TOKEN_DOC_ID`, fallback `settings.LARK_USER_OPEN_ID/LARK_USER_NAME/LARK_TENANT_KEY`.
- `get_app_access_token`: bỏ nhánh tự resolve; `app_id` + `app_secret` bắt buộc; bỏ biến global `_app_access_token`.
- `get_authorize_url`: `app_id` bắt buộc.
- `one_click_setup_service.py:289`: xoá `f"tenant_{admin_open_id[:8]}"` / `"tenant_default"`; thiếu `tenant_key` từ Lark → fail step với thông báo rõ.
- Nhánh setup giữ `claim_oauth_state` hiện có (đã đúng).

## Giai đoạn 5 — State machine tenant, invalidation, refresh (sửa T9, S2, S3, S4)

**State machine trên field `status` hiện có** (không thêm field mới):

| Từ | Sự kiện | Sang |
|---|---|---|
| — / `provisioning_failed` | bắt đầu setup | `provisioning` |
| `provisioning` | pipeline xong + kiểm tra đủ dữ liệu | `ready` |
| `provisioning` | pipeline lỗi | `provisioning_failed` (+ `last_error`, `failed_step`) |
| `ready` | `stop_by_tenant` | `inactive` |
| `inactive` | `start_by_tenant` | `ready` nếu resolver kiểm tra đủ dữ liệu, ngược lại `provisioning_failed` — **không** provision lại |
| bất kỳ | `app_uninstalled` | `uninstalled` |

- Hàm chung `tenant_state.mark_ready(tenant_key)`: chạy kiểm tra của resolver (bỏ qua bước 3) trước khi set `ready`; thiếu → `provisioning_failed`. Dùng ở cả `one_click_setup_service` (step 7) và `tenant_lifecycle_handler` (thay logic `ready_status` L134).
- `one_click_setup_service.py:580-603`: except block đặt tenant `provisioning_failed`. UI setup đã hiển thị `task.status=failed` → thêm nút "Thử lại" gọi lại pipeline cho tenant ở `provisioning_failed`.
- `one_click_setup_service.py:439-443`: bỏ fallback `settings.LARK_BASE_APP_TOKEN` cho `bitable_url`; không có → fail step.
- `weknora_provision_service.py:213-221`: dry-run **không ghi** vào `tenants`; nếu `ENVIRONMENT=production` mà `WEKNORA_PROVISION_DRY_RUN=True` → raise khi khởi động.
- **Invalidation**: mọi chuyển trạng thái + `register_app` + `link_tenant` gọi `tenant_resolver.invalidate` và `token_broker.invalidate`.
- **Refresh sweeper** (thay `start_token_refresh_loop`): chạy trên token loop mỗi 10 phút, duyệt `tenants` có `status="ready"`, gọi `token_broker.get(tk, "user")`. `UserTokenMissing` / `TokenUnavailable` → log `warning` có `tenant_key` và lý do; không dừng vòng lặp.
- `init_token_on_startup`: bỏ nhánh legacy `primary_user_token`.

**Phản hồi người dùng khi bị từ chối** (dispatcher/router bắt exception có kiểu):
- Event Lark → trả lời trong chat: "Doanh nghiệp chưa hoàn tất cài đặt HiLark. Quản trị viên vui lòng mở trang Setup để thử lại." (`TenantNotReady`, `TenantConfigIncomplete`) hoặc "Cần uỷ quyền lại tài khoản Lark." (`UserTokenMissing`). Gửi bằng bot token; nếu cả bot token cũng không lấy được → chỉ log.
- HTTP → `409` cho `TenantNotReady`/`TenantConfigIncomplete`, `401` cho `UserTokenMissing`, `503` cho `TokenUnavailable`; body có `error_code` và `tenant_key`.

## Giai đoạn 6 — Dữ liệu & bảo mật (sửa D1, D2)

- **D1**: script `scripts/cleanup_test_tenant.py`, mặc định `--dry-run`, xoá `tenant_save_corp` khỏi `tenants` và mọi collection có `tenant_key` đó. Chỉ chạy thật khi người dùng xác nhận. Test suite chuyển sang `MONGO_DB` riêng (`LarkAssistant_test`) qua `pytest.ini`/conftest.
- **D2** (`19a84399cc971978`, app `cli_aa4770…`): cần người dùng cung cấp App Secret qua UI `register_app` hiện có rồi `link_tenant`. Nếu không còn secret → chuyển tenant sang `provisioning_failed` để buộc setup lại. Agent không tự sinh hay đoán credential.
- **Bảo mật** (ngoài 19 lỗi, phát hiện khi lập plan): `docker-compose.prod.yml` chứa connection string Mongo Atlas kèm mật khẩu trong giá trị mặc định của `MONGO_URL`/`MONGODB_URI`. Bỏ giá trị mặc định (thiếu → container fail khi khởi động). Người dùng cần **đổi mật khẩu Atlas** vì mật khẩu đã nằm trong lịch sử Git.
- Mở rộng `audit_tenant_config_readonly.py`: thêm kiểm tra state machine (không còn tenant `ready` vi phạm hợp đồng resolver) và `app_id` khớp giữa `tenants` và `lark_app_credentials`.

## Test plan

Chạy bằng `cd server && .venv/bin/python -m pytest tests -q`, DB test riêng, mock HTTP Lark.

- **T1** `tests/auth/test_token_loop_concurrency.py`: 20 coroutine trên 4 thread, mỗi thread tự `asyncio.run`, cùng gọi `get(tenant, "tenant")` với provider giữ 50ms → tất cả trả về trong <3s; provider được gọi đúng 1 lần (single-flight). Đây là tái hiện thực nghiệm treo đã chạy.
- **T3/T4** `test_token_broker.py`: Custom App mode trả bot token; 2 tenant đồng thời nhận token khác nhau; tenant đổi `app_id` → cache cũ không dùng lại; provider lỗi → `TokenUnavailable`, không phải `""`.
- **T7/T8/C1** `tests/tenancy/test_tenant_resolver.py`: thiếu tenant_key, không tìm thấy, `provisioning`, thiếu credential, `app_id` lệch, thiếu field → đúng exception; DB có App của tenant khác → **không** được trả về.
- **Sentinel**: đặt `LARK_APP_ID/LARK_APP_SECRET/WEKNORA_*_DATASET_ID = "ENV_SENTINEL"`; chạy luồng chat, digest, policy sync, bitable → không request nào chứa `ENV_SENTINEL`.
- **C3**: 2 coroutine đồng thời 2 tenant thao tác Base → mỗi request dùng đúng `app_token` của tenant mình.
- **T5/T6**: login sinh state gắn App của tenant; callback với state đã dùng → 400; callback hợp lệ → token lưu `_id = lark_app:{app}:user:{tenant}:{open_id}` và `get(tenant, "user")` đọc được ngay; profile trả tenant khác → raise.
- **Giai đoạn 5**: pipeline lỗi → tenant `provisioning_failed`; `stop` rồi `start` → về `ready`, không provision lại; uninstall → resolver và broker không còn cache.
- **Sweeper**: rút TTL token còn 60s, chạy 1 vòng sweeper → token được refresh; tenant thiếu token → log warning, vòng lặp tiếp tục.
- Hồi quy: các test hiện có trong `tests/final_test/` và `tests/auth/` so với baseline Giai đoạn 0; test nào dựa vào fallback `.env` sẽ được cập nhật và ghi rõ trong báo cáo.

## Thứ tự & phụ thuộc

0 → 1 → 2 → (3 ∥ 4) → 5 → 6. Mỗi giai đoạn chạy đủ test của nó + hồi quy trước khi sang giai đoạn tiếp theo; dừng và báo cáo nếu hồi quy fail.

## Ghi nhận tài liệu

- Thêm EDL mới trong `docs/project-memory/DECISIONS.md` (supersede phần chưa thực hiện của EDL-0068): resolver fail-closed, token loop, state machine, không lease vì 1 replica. Đồng bộ Notion nếu có MCP; không có thì báo chưa đồng bộ.
- Cập nhật `HANDOFF.md` sau mỗi giai đoạn; `PROJECT_CONTEXT.md` sau Giai đoạn 5.

## Giả định

- Production tiếp tục 1 container, 1 worker. Nếu scale ≥2 phải bổ sung lease Mongo cho refresh `refresh_token` trước khi bật sweeper.
- Không còn chế độ chạy bằng `.env` cho tenant, kể cả dev; dev tạo tenant qua luồng setup như production.
- Các thay đổi chưa commit hiện có là công việc dở của người dùng và sẽ được commit ở Giai đoạn 0 trước khi bắt đầu.
- Chưa đổi API công khai ngoài: `/auth/lark/login` yêu cầu ngữ cảnh tenant, và mã HTTP mới 409/401/503 cho lỗi tenant/token.
