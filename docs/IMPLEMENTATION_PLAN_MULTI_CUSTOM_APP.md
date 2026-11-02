# Implementation Plan — One Server, Many Custom Lark Apps

## Objective

Cho phép một HiLark server phục vụ nhiều công ty; mỗi công ty kết nối bằng một Custom App/Bot riêng mà không ghi đè credential, user token, webhook validation hoặc runtime Lark client của tenant khác.

## Current constraint

Code hiện tại còn các singleton/global state: `settings.LARK_*`, `primary_user_token`, `lark_service`, một `EventDispatcherHandler` và `token_service` dùng App credential global. Mô hình hiện tại an toàn nhất là một server cho một Custom App.

## Target contract

```text
tenant_key -> LarkAppCredential -> UserToken -> LarkClient/RequestOption
```

Mọi inbound event phải resolve `app_id`/`tenant_key` trước khi validate và xử lý. Mọi outbound API phải nhận `tenant_key` và lấy đúng credential/token của tenant.

## Phases

### Phase 1 — Credential registry and durable schema

- Tạo collection `lark_app_credentials` với unique `app_id` và unique `(tenant_key, app_id)`.
- Mã hóa `app_secret`, `verification_token`, `encrypt_key` bằng Fernet hiện có.
- Lưu trạng thái setup, owner/admin và timestamps.
- Không ghi secret plaintext vào log hoặc response.

### Phase 2 — Tenant-aware OAuth/setup

- Setup session giữ `app_registration_id`.
- OAuth URL dùng App ID của session, không dùng `settings.LARK_APP_ID`.
- Callback exchange code bằng đúng App credential của session.
- Lưu user token theo `tenant_key + app_id + open_id`; refresh token rotation cũng theo khóa này.
- Giữ fallback global chỉ cho backward compatibility/single-tenant deployment.

### Phase 3 — Inbound event routing

- Resolve app từ `payload.header.app_id`/registration state.
- Validate verification/encryption key của đúng App.
- Chạy handler trong `async_tenant_context(tenant_key)`.
- Không bypass invalid verification token trong production.
- Card callback, lifecycle và message event dùng cùng resolver.

### Phase 4 — Runtime client and outbound routing

- Tạo `LarkClientPool` cache client theo `(tenant_key, app_id)`.
- Messenger, Bitable, Base provisioning và token service lấy client/token theo tenant.
- Loại bỏ mutate trực tiếp `settings.LARK_*` trong onboarding.
- Không dùng `known_user_open_id`/`user_access_token` global cho request tenant-scoped.

### Phase 5 — Provisioning and data isolation

- Gắn `app_id`/credential reference vào tenant record.
- Base, WeKnora, claims, digest và chat scope giữ `tenant_key` như hiện tại.
- Không cho app A đọc/gửi vào resource của tenant B.

### Phase 6 — Verification and rollout

- Test hai Custom App thật hoặc mock App A/B trên cùng server.
- Test callback sai token bị từ chối, callback đúng token được xử lý.
- Test OAuth/refresh đồng thời hai tenant.
- Migration backward-compatible cho `primary_user_token` và `.env` single-tenant.
- Chỉ chuyển production sau khi pass cross-app isolation suite.

## Acceptance criteria

- Hai App ID khác nhau có thể setup trên cùng server.
- App B không ghi đè credential/token/client của App A.
- Event của App A chỉ tạo dữ liệu dưới `tenant_key_A`.
- Refresh token của A không dùng cho B.
- Gửi message/Base API dùng đúng App và tenant.
- Invalid verification token trả 401/403, không chạy handler fallback.
- Existing single-tenant tests vẫn pass.

## Implementation order for this change

1. Registry + encryption + indexes.
2. Setup registration endpoint and session binding.
3. Token service app-credential injection.
4. Callback/pipeline wiring.
5. Event resolver and runtime pool.
6. Cross-app tests.

## Status after implementation pass (2026-11-01)

- Phases 1–3: implemented for the Custom App setup path (registry, encrypted credentials, setup binding, App-scoped OAuth token storage/refresh, webhook App validation and tenant context).
- Phase 4: runtime client pool foundation implemented in `server/services/lark/runtime.py`; message/document/chat workflow resolution uses the request-scoped client.
- Phase 5: existing Mongo/WeKnora/claims/digest tenant isolation remains in place; background paths still need explicit runtime resolution by `tenant_key`.
- Phase 6: focused regression passes; two-real-App integration testing and setup endpoint hardening remain before production sign-off.
