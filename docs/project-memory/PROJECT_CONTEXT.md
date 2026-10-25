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
- **Database/storage:** MongoDB (Motor >= 3.7.1 cho async, PyMongo >= 4.18.3 cho sync)
- **External services/APIs:**
  - Lark Open Platform (`lark-oapi` >= 1.7.3)
  - WeKnora Hybrid RAG API
  - JEV Intent Classifier API (System 1)
  - Google Gemini API (LLM generation)
- **Build/package manager:** `uv`
- **Libraries hỗ trợ:** `flashtext` (lọc từ khóa cấm), `httpx` (HTTP client), `python-docx`, `reportlab` (xử lý tài liệu), `python-dotenv`

## 3. Architecture
Kiến trúc vận hành 4 lớp tuần tự:
1. **Lớp 1: Cổng sự kiện Lark (Gateway & Dispatcher):** Nhận tin nhắn/sự kiện qua WebSocket (`services/bot_service.py`) hoặc Webhook HTTP, lọc trùng tin nhắn (deduplication).
2. **Lớp 2: Bộ kiểm soát ý định JEV (System 1 Gatekeeper):** Phản xạ nhanh phân loại ý định người dùng (chào hỏi xã giao, tra cứu Q&A, giao việc, out-of-scope) để ngắt sớm hoặc điều hướng xử lý, tránh lãng phí token LLM.
3. **Lớp 3: Động cơ nhận thức & Giải quyết xung đột tri thức:**
   - **Tầng Phân Giải Đa Phương Tiện (Document Parsing Layer):** Chuẩn hóa file đính kèm (PDF, DOCX, XLSX, PPTX, ảnh) qua WeKnora AnyDoc gRPC (`WeKnora-docreader:50051`) và Lark DocX/Wiki URL qua Lark OpenAPI thành Markdown thuần với 0 token cost, cung cấp đầu vào cho `llm_extractor`.
   - **WeKnora RAG (Baseline Layer):** Tìm kiếm hybrid (vector + BM25 keyword) trên kho tài liệu tĩnh bất biến có phân vùng theo nhóm chat (`chat_scopes`).
   - **MongoDB Claims (Claims Overlay):** Lưu trữ các sự thật mới chốt trong đoạn chat hoặc bóc tách từ tài liệu họp. Cơ chế `ContextComposer` giải quyết xung đột theo nguyên tắc: `CURRENT Claims > Static WeKnora Baseline`.
   - **Rule Engine & Contextual Claim Gate:** Lọc bỏ dữ liệu nhạy cảm và ngăn chặn ô nhiễm ngữ cảnh chéo domain trước khi đưa vào prompt LLM.
4. **Lớp 4: Cổng thực thi & Phê duyệt (Execution & HITL Gateway):**
   - Trả lời trực tiếp nếu thông tin đầy đủ và an toàn.
   - Cơ chế duyệt nháp (HITL): Gửi bản nháp dạng interactive card vào DM của người duyệt khi thiếu dữ liệu hoặc cần xác nhận.
   - Daily Digest & LarkBase Sync: Tổng hợp tự động và đồng bộ tri thức vào WeKnora / Lark Base.

## 4. Important code paths
| Area | Path | Responsibility | Evidence / notes |
|---|---|---|---|
| Entry point | `server/main.py` | Khởi tạo FastAPI app, lifespan quản lý bot service, đăng ký routers | Đã xác minh |
| Configuration | `server/core/config.py` | Load `.env` từ repo root, cấu hình MongoDB, Lark, WeKnora, JEV, Gemini | Đã xác minh |
| Lark Bot Service | `server/services/bot_service.py` | Kết nối Lark WebSocket, lắng nghe event tin nhắn & card action | Đã xác minh |
| Core Chat Orchestration | `server/services/chat_service.py` | Pipeline xử lý tin nhắn, gọi JEV, RAG, Claims, LLM, duyệt nháp, bóc tách tài liệu (EDL-0010) | Đã xác minh |
| Intent Classifier (JEV) | `server/services/jev.py` | Giao tiếp API JEV để phân loại mục tiêu tin nhắn | Đã xác minh |
| Hybrid RAG | `server/services/weknora.py` | Tìm kiếm ngữ nghĩa/từ khóa trên WeKnora dataset | Đã xác minh |
| Context Composer | `server/utils/context_composer.py` | Hợp nhất RAG chunks + Claims, ưu tiên Claims mới hơn tài liệu | Đã xác minh qua unit test |
| Document Parsing Layer | `server/services/doc_parser_service.py` | Chuyển đổi file đính kèm & Lark Doc URL sang Markdown (EDL-0010) | Đã xác minh qua unit test (11/11 pass) |
| AnyDoc gRPC Client | `server/services/docreader_service.py` | Kết nối `WeKnora-docreader:50051` parse nhị phân sang Markdown | Đã xác minh qua unit test (8/8 pass) |
| Rule Engine | `server/utils/rule_engine.py` | Kiểm duyệt từ khóa nhạy cảm trên Chunks và Claims | Đã xác minh qua unit test |
| Daily Digest & Staging | `server/services/digest_service.py` | Lưu staging tin nhắn, tổng hợp digest ngày, xuất báo cáo | Đã xác minh |
| Chat Scope Isolation | `server/services/scope_service.py` | Quản lý quyền truy cập dataset và dữ liệu theo chat_id | Đã xác minh qua unit test |
| Draft Approval (HITL) | `server/services/draft_service.py` | Quản lý vòng đời bản nháp (Pending, Approved, Rejected) | Đã xác minh |
| Database layer | `server/database/` (`db.py`, `mongo.py`) | Kết nối Motor AsyncIOMotorClient và PyMongo | Đã xác minh |
| Test suite | `server/tests/01/` | Bộ kiểm thử chức năng (73 test cases) | 72 passed, 1 failed |

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
- **Verified issues:**
  1. `tests/01/test_master_digest.py::test_master_digest_dm_text_format`: Bị fail do chuỗi tiêu đề `BÁO CÁO TỔNG HỢP TOÀN BỘ CÁC NHÓM` mong đợi khác với định dạng thực tế sinh ra `📊 BÁO CÁO NGÀY CẤP ĐIỀU HÀNH (DAILY MASTER DIGEST)`.
- **Open questions:**
  - Kế hoạch triển khai Docker/Container hóa cho môi trường Production.
- **Assumptions requiring confirmation:**
  - Giả định MongoDB cục bộ hoặc cloud URI đã sẵn sàng khi chạy bot service thực tế.

## 9. Last verified
- **Date:** 2026-10-25
- **What was checked:** Cấu hình `server/core/config.py`, `.env`, hạ tầng AnyDoc gRPC `WeKnora-docreader:50051`, và toàn bộ 4 Giai đoạn của Quyết định Kỹ thuật `EDL-0010` (DocReader Service 8/8 pass, DocParser Service 11/11 pass, Claims Doc Pipeline 6/6 pass, E2E Document Knowledge Overlay 4/4 pass, Contextual Claim Gate 8/8 pass -> Tổng cộng 37/37 test cases passed 100%).
- **By / source:** Antigravity Agent (phiên nghiệm thu hoàn thành EDL-0010).
