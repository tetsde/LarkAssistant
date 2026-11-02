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
| Database layer | `server/database/` (`db.py`, `indexes.py`) | Kết nối Motor AsyncIOMotorClient, PyMongo, đánh index, truy vấn và thăng hạng proposed claims theo ngày (EDL-0009, EDL-0013) | Đã xác minh |
| Test suite | `server/tests/01/` & `server/tests/` | Bộ kiểm thử chức năng, OCR, modular services, interactive cards, telemetry & hồi quy toàn diện (244 test cases) | 244 passed (100%) |

## 5. Contracts and constraints
- **Lark API:** Dùng `lark-oapi` kết nối WebSocket mode (không cần public IP/webhook proxy khi dev).
- **Quy tắc giải quyết xung đột:** Sự thật (Claim) có hiệu lực mới nhất trong nhóm chat luôn được ưu tiên cao hơn tài liệu tĩnh từ WeKnora.
- **RAG Hard Isolation:** Dataset truy xuất phải được giới hạn chặt chẽ theo `chat_id` và quyền của người dùng; cấm truy xuất chéo nhóm trái phép.
- **Human-in-the-Loop:** Khi độ tin cậy thấp hoặc thông tin nhạy cảm, bot không trả lời công khai mà gửi nháp kèm nút bấm duyệt qua DM cá nhân.

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
- **Date:** 2026-10-27
- **What was checked:** Hoàn thành Bộ Decorator Đo Lường Chi Phí LLM & JEV (EDL-0014) & Trích xuất Tài liệu Ảnh Gemini Vision OCR, Gom Nhóm Thông Tin Đề Xuất (EDL-0013):
  1. `server/decorators/cost_telemetry.py`: Xây dựng package decorators riêng biệt, cung cấp `@track_llm_cost` và `@track_jev_cost` đo lường chính xác token (từ usageMetadata của Gemini), thời gian phản hồi (latency_ms), chi phí ước tính USD/VND, ghi log có cấu trúc và lưu ngầm vào MongoDB collection `cost_telemetry`.
  2. Bọc decorator vào toàn bộ các phương thức gọi LLM trong `gemini_client.py` và JEV trong `jev_classifier.py`.
  3. Cập nhật `indexes.py`, `config.py`, `db.py` quản lý chỉ mục và kết nối cho collection `cost_telemetry`.
  4. Đã bổ sung bộ kiểm thử `server/tests/test_cost_telemetry.py` (9/9 passed).
  5. Toàn bộ 244 bài test (207 tests trong `server/tests/01` và 37 tests trong `server/tests/`) PASSED 100%.
- **By / source:** Antigravity Agent.

### Multi-Custom-App deployment note (2026-11-01)
HiLark is being migrated from the legacy single `.env` Lark App to a shared-server model where each customer registers its own Custom App. The current implementation has a tenant-aware credential registry and per-App runtime client foundation; the legacy singleton remains only as a backward-compatible fallback. See `docs/IMPLEMENTATION_PLAN_MULTI_CUSTOM_APP.md` and decision `EDL-0041` for the rollout boundary and remaining hardening work.
