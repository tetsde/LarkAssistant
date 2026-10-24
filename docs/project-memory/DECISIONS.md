# Decision Index

> Chỉ mục ngắn trong repo. Hồ sơ đầy đủ có thể nằm trong Notion. Không tạo ID hoặc URL giả.

| ID | Decision | Status | Impact | Date | Notion record | Code / commit |
|---|---|---|---|---|---|---|
| EDL-0002 | [Chiến lược Phân tầng Tri thức & Đồng bộ Đa tài liệu](https://app.notion.com/p/EDL-0002-Chi-n-l-c-Ph-n-t-ng-Tri-th-c-ng-b-a-t-i-li-u-402590f7e19e81ef82bbeb091ece965f) | Approved | High | 2026-10-23 | [Notion Page](https://app.notion.com/p/EDL-0002-Chi-n-l-c-Ph-n-t-ng-Tri-th-c-ng-b-a-t-i-li-u-402590f7e19e81ef82bbeb091ece965f) | `server/models/chat_scope.py`, `server/utils/context_composer.py` |
| EDL-0003 | [JEV Piggyback Routing cho Phân tầng Tri thức](https://app.notion.com/p/EDL-0003-JEV-Piggyback-Routing-cho-Ph-n-t-ng-Tri-th-c-Project-KB-vs-Global-Wiki-402590f7e19e8179bc26ed7248bb725b) | Approved | High | 2026-10-23 | [Notion Page](https://app.notion.com/p/EDL-0003-JEV-Piggyback-Routing-cho-Ph-n-t-ng-Tri-th-c-Project-KB-vs-Global-Wiki-402590f7e19e8179bc26ed7248bb725b) | `server/services/jev.py`, `server/services/chat_service.py` |
| EDL-0004 | [Tận dụng WeKnora Document Summary làm Macro-Context](https://app.notion.com/p/EDL-0004-T-n-d-ng-WeKnora-Document-Summary-l-m-Macro-Context-cho-Auto-Manifest-ContextComposer-402590f7e19e810093e5c38fe1e74da5) | Approved | High | 2026-10-23 | [Notion Page](https://app.notion.com/p/EDL-0004-T-n-d-ng-WeKnora-Document-Summary-l-m-Macro-Context-cho-Auto-Manifest-ContextComposer-402590f7e19e810093e5c38fe1e74da5) | `server/services/scope_service.py`, `server/utils/context_composer.py` |
| EDL-0005 | [Pipeline Đồng bộ Policy Tự động (Lark Base Thin Bridge & WeKnora Data Source)](https://app.notion.com/p/EDL-0005-Pipeline-ng-b-Policy-T-ng-Lark-Base-Thin-Bridge-WeKnora-Data-Source-403590f7e19e81258ed3e2b2eb444f9c) | Approved | High | 2026-10-24 | [Notion Page](https://app.notion.com/p/EDL-0005-Pipeline-ng-b-Policy-T-ng-Lark-Base-Thin-Bridge-WeKnora-Data-Source-403590f7e19e81258ed3e2b2eb444f9c) | `server/services/policy_sync_service.py`, `server/routers/policy.py`, `server/services/weknora.py` |
| EDL-0006 | [Tự động Làm mới Lark User Token (OAuth2 Single-Use Refresh Token Rotation & MongoDB Storage)](https://app.notion.com/p/EDL-0006-T-ng-L-m-m-i-Lark-User-Token-OAuth2-Single-Use-Refresh-Token-Rotation-MongoDB-Stora-403590f7e19e81ec908fc1f4527802fe) | In Progress | High | 2026-10-24 | [Notion Page](https://app.notion.com/p/EDL-0006-T-ng-L-m-m-i-Lark-User-Token-OAuth2-Single-Use-Refresh-Token-Rotation-MongoDB-Stora-403590f7e19e81ec908fc1f4527802fe) | `server/services/token_service.py`, `server/routers/auth.py`, `server/services/larkServices/lark_client.py` |

## Rules
- Add entries only for consequential technical decisions.
- Use the real Notion URL/ID returned by the connected MCP.
- Keep old decisions for history; mark replaced decisions as `Superseded` and link the replacement.
- If Notion sync is unavailable, say so and keep a local draft rather than pretending it synced.
