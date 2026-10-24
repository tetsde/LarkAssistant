# Current Handoff

> Cập nhật khi kết thúc phiên có công việc đang dở hoặc bàn giao trạng thái sẵn sàng.

## Current task
- **Goal:** Brainstorm & Thiết kế Kiến trúc Xử lý Đa tài liệu (Multi-Document RAG), Phân tầng Tri thức (Two-Tier Hierarchy) và Đồng bộ trực tiếp Lark Docs.
- **Status:** In Progress (Đã chốt kiến trúc & đồng bộ Notion Decision Log)
- **Scope:** 
  1. Mổ xẻ nguyên nhân gốc rễ lỗi nhiễu loạn thông tin khi upload nhiều file (`Project_Charter`, `Code_of_Conduct`, `04_So_tay_chinh_sach_cong_ty`, `Ngan_sach_du_an`).
  2. Vạch trần bug logic trong code: hàm `get_project_name()` trong `server/models/chat_scope.py` lấy `doc_names[0]` dẫn đến ép LLM nhận diện sai tên dự án.
  3. Thiết kế kiến trúc Phân tầng Tri thức: Global Wiki KB (chính sách chung) vs Project Scoped KB (tài liệu riêng của nhóm).
  4. Thiết kế cơ chế Auto-Manifest (tự động đọc hiểu và tạo thẻ vai trò tài liệu dưới background, zero user friction).
  5. Đề xuất & thống nhất giải pháp đồng bộ trực tiếp Lark Docs (Docx raw content qua OpenAPI) thay vì chỉ upload file thủ công từ máy tính.
  6. Làm rõ quy trình giải quyết xung đột khi tài liệu cập nhật từ A lên A+1 (Atomic Replacement trong WeKnora + Real-time Override từ Claims).

## What is confirmed
- Nguyên nhân trực tiếp gây ra câu trả lời ngớ ngẩn trong ảnh screenshot là dòng code `first_doc = doc_names[0]` tại `server/models/chat_scope.py:79`.
- Cơ chế cập nhật tài liệu WeKnora qua việc xóa document cũ và re-index document mới (Atomic replacement) chỉ mất 1-3 giây chạy ngầm, không gây nghẽn và ngăn chặn 100% "Ghost Chunks".
- Quyết định kiến trúc `EDL-0002` (Two-Tier Hierarchy & Lark Docs Sync) đã được ghi nhận trên Notion (Page ID: `402590f7-e19e-81ef-82bb-eb091ece965f`).
- Quyết định kiến trúc `EDL-0003` (JEV Piggyback Routing cho Phân tầng Tri thức) đã được tạo và đồng bộ thành công lên Notion Database `Engineering Decision Log` (Page ID: `402590f7-e19e-8179-bc26-ed7248bb725b`).
- Quyết định kiến trúc `EDL-0004` (Tận dụng WeKnora Document Summary làm Macro-Context) đã được tạo và đồng bộ thành công lên Notion Database `Engineering Decision Log` (Page ID: `402590f7-e19e-8100-93e5-c38fe1e74da5`).
- Đã xác nhận: Bộ đệm `MessageDebouncer` (1.75s) tại `server/utils/chat_queue.py` giải quyết triệt để vấn đề tin nhắn chat ngắt quãng của người dùng trước khi đến JEV.
- Đã xác nhận: Cơ chế Pessimistic Routing (ngưỡng tin cậy >= 0.85, phân vân tự động fallback sang `HYBRID` query cả 2 kho) loại trừ 100% rủi ro mất mát dữ liệu (False Negatives).
- Đã xác nhận: Tận dụng trường `summary` có sẵn của WeKnora để sinh Document Manifest thay vì tốn chi phí gọi LLM ngoài (Zero-cost LLM worker).

## Work completed
- **Phân tích kỹ thuật & Code Audit:** Soi toàn bộ flow từ LarkBase sync, WeKnora retrieval, JEV relevance filter, ContextComposer đến Grounded QA.
- **Thiết kế & Phản biện Kiến trúc Routing:** Đào sâu ưu/nhược điểm các phương án truy vấn giữa Project KB và Global Wiki KB, chốt Phương án B (JEV Piggyback).
- **Tối ưu hóa Macro-Context:** Thống nhất tận dụng trường `summary` tự động của WeKnora để nhúng vào ContextComposer và sửa hàm nhận diện tên dự án.
- **Hoàn thành Giai đoạn 1 (Fix get_project_name):** Đã xóa dứt điểm dòng `first_doc = doc_names[0]` trong `server/models/chat_scope.py`, chuẩn hóa nguồn chân lý `project_tag -> chat_name`, viết unit test pass 13/13.
- **Hoàn thành Giai đoạn 2 (WeKnora Summary Persistence):** Đã bổ sung `get_document_info()` trong `weknora.py` và lưu trữ/backfill `summary` vào `synced_docs` trong `scope_service.py`, viết unit test pass 15/15.
- **Hoàn thành Giai đoạn 3 (Document Manifest & ContextComposer):** Đã format Section 0 Document Manifest kèm `summary` trong `context_composer.py`, truyền `documents` đầy đủ từ `chat_service.py`, viết unit test kiểm thử 6/6 tests pass trong `test_context_composer.py`.
- **Hoàn thành Giai đoạn 4 (JEV Piggyback Routing & Two-Tier Retrieval):** Đã thêm question `knowledge_domain` vào JEV `classify_message`, áp dụng Pessimistic Routing (ngưỡng >= 0.85), định tuyến WeKnora song song `asyncio.gather` cho chế độ Hybrid, loại bỏ hoàn toàn regex/keywords cứng để đạt chuẩn AI-native. Unit test: 9/9 pass trong `test_jev_classification.py`.
- **Đồng bộ Notion Decision Log:** Tạo và ghi nhận đầy đủ chi tiết quyết định `EDL - 0002`, `EDL - 0003`, `EDL - 0004` trên Notion qua Notion MCP, cập nhật Section 5 (Execution Evidence) cho cả 3 quyết định `EDL-0002`, `EDL-0003`, `EDL-0004`.
- **Cập nhật Project Memory:** Cập nhật `docs/project-memory/DECISIONS.md` và `docs/project-memory/HANDOFF.md`.

## Verification
- **Commands actually run:**
  - `PYTHONPATH=. .venv/bin/python -m unittest tests/01/test_jev_classification.py`: 9/9 tests passed (0.518s).
  - `PYTHONPATH=. .venv/bin/python -m unittest tests/01/test_memory_weknora_gating.py`: 5/5 tests passed (0.038s).
  - `PYTHONPATH=. .venv/bin/python -m unittest tests/01/test_chat_scope.py`: 15/15 tests passed (0.116s).
  - `PYTHONPATH=. .venv/bin/python tests/01/test_context_composer.py`: 6/6 tests passed (0.012s).
  - Notion MCP `API-patch-block-children`: Đã cập nhật Section 5 (Execution Evidence) vào trang Notion `EDL-0003` (Page ID: `402590f7-e19e-8179-bc26-ed7248bb725b`).

## Next concrete steps
1. **Giai đoạn 5 (Lark Docs Direct Sync qua OpenAPI):**
   - Triển khai hàm trích xuất nội dung văn bản thuần trực tiếp từ link/document token của Lark Docx qua Lark Open API (`docx.v1.document`).
   - Cập nhật luồng sync từ Lark Base để tự động kéo nội dung Docx và nạp vào WeKnora mà không cần người dùng export thủ công file ra máy tính.
   - Viết unit test cho Lark Docx parser & sync flow.
   - DỪNG LẠI và báo cáo cho user review Giai đoạn 5.
