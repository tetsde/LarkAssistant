# Decision Index

> Chỉ mục ngắn trong repo. Hồ sơ đầy đủ có thể nằm trong Notion. Không tạo ID hoặc URL giả.

| ID | Decision | Status | Impact | Date | Notion record | Code / commit |
|---|---|---|---|---|---|---|
| EDL-0002 | [Chiến lược Phân tầng Tri thức & Đồng bộ Đa tài liệu](https://app.notion.com/p/EDL-0002-Chi-n-l-c-Ph-n-t-ng-Tri-th-c-ng-b-a-t-i-li-u-402590f7e19e81ef82bbeb091ece965f) | Approved | High | 2026-10-23 | [Notion Page](https://app.notion.com/p/EDL-0002-Chi-n-l-c-Ph-n-t-ng-Tri-th-c-ng-b-a-t-i-li-u-402590f7e19e81ef82bbeb091ece965f) | `server/models/chat_scope.py`, `server/utils/context_composer.py` |
| EDL-0003 | [JEV Piggyback Routing cho Phân tầng Tri thức](https://app.notion.com/p/EDL-0003-JEV-Piggyback-Routing-cho-Ph-n-t-ng-Tri-th-c-Project-KB-vs-Global-Wiki-402590f7e19e8179bc26ed7248bb725b) | Approved | High | 2026-10-23 | [Notion Page](https://app.notion.com/p/EDL-0003-JEV-Piggyback-Routing-cho-Ph-n-t-ng-Tri-th-c-Project-KB-vs-Global-Wiki-402590f7e19e8179bc26ed7248bb725b) | `server/services/jev.py`, `server/services/chat_service.py` |
| EDL-0004 | [Tận dụng WeKnora Document Summary làm Macro-Context](https://app.notion.com/p/EDL-0004-T-n-d-ng-WeKnora-Document-Summary-l-m-Macro-Context-cho-Auto-Manifest-ContextComposer-402590f7e19e810093e5c38fe1e74da5) | Approved | High | 2026-10-23 | [Notion Page](https://app.notion.com/p/EDL-0004-T-n-d-ng-WeKnora-Document-Summary-l-m-Macro-Context-cho-Auto-Manifest-ContextComposer-402590f7e19e810093e5c38fe1e74da5) | `server/services/scope_service.py`, `server/utils/context_composer.py` |

## Rules
- Add entries only for consequential technical decisions.
- Use the real Notion URL/ID returned by the connected MCP.
- Keep old decisions for history; mark replaced decisions as `Superseded` and link the replacement.
- If Notion sync is unavailable, say so and keep a local draft rather than pretending it synced.
