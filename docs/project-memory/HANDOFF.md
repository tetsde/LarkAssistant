# Current Handoff

> Cập nhật khi kết thúc phiên có công việc đang dở hoặc bàn giao trạng thái sẵn sàng.

## Current task
- **Goal:** Khắc phục lỗi cắt cụt ngữ cảnh Sổ tay Nhân viên (Salary Date Truncation Bug), Thiết kế Kiến trúc Tầng Phân Giải Tài Liệu Đa Phương Tiện (Document Parsing Layer via AnyDoc gRPC & Lark OpenAPI), và Chuẩn hóa Cơ chế Xử lý Xung đột Tri thức (EDL-0010).
- **Status:** Architecture Approved & Documented (Đã phê duyệt và đồng bộ lên Notion EDL-0010; đã sửa xong lỗi cắt cụt ngữ cảnh lương trong `context_composer.py`).
- **Scope:**
  1. Điều tra & Fix Bug Lương: Sửa `max_chunk_chars: int = 16000` trong `server/utils/context_composer.py` đảm bảo không bị cắt cụt tài liệu Sổ tay Nhân viên (`01_So_Tay_Nhan_Vien_Employee_Handbook.docx`).
  2. Brainstorm & Thống nhất Cơ chế Xử lý Xung đột: Giữ nguyên tài liệu gốc (Project Charter) trên WeKnora làm Baseline bất biến; trích xuất các quyết định họp/chốt việc thành Dynamic Claims (MongoDB) làm Overlay; `ContextComposer` hợp nhất với rule `CURRENT Claims > Static WeKnora Documents`.
  3. Thiết kế Tầng Phân Giải Đa Phương Tiện: Tách biệt `doc_parser_service.py` (chuyển đổi PDF, Word, Excel, PPTX, ảnh sang Markdown bằng WeKnora AnyDoc gRPC `WeKnora-docreader:50051`, và Lark Doc URL qua Lark OpenAPI) đứng trước `llm_extractor.py` (chỉ nhận Markdown sạch để bóc tách Claims).
  4. Ghi nhận quyết định kỹ thuật `EDL-0010` lên Notion Engineering Decision Log và cập nhật bộ nhớ dự án (`DECISIONS.md`, `HANDOFF.md`, `PROJECT_CONTEXT.md`).

## What is confirmed
- Quyết định kỹ thuật `EDL-0006`, `EDL-0007`, `EDL-0008`, `EDL-0009` và `EDL-0010` đã được ghi nhận và đồng bộ thành công lên Notion Database `Engineering Decision Log`:
  - `EDL-0006`: [Page ID `403590f7-e19e-81ec-908f-c1f4527802fe`](https://app.notion.com/p/EDL-0006-T-ng-L-m-m-i-Lark-User-Token-OAuth2-Single-Use-Refresh-Token-Rotation-MongoDB-Stora-403590f7e19e81ec908fc1f4527802fe) (Approved)
  - `EDL-0007`: [Page ID `403590f7-e19e-8175-9524-ffcc0fc15288`](https://app.notion.com/p/EDL-0007-nh-tuy-n-RAG-a-kho-Mi-n-tr-Nh-n-c-m-D-n-cho-V-n-b-n-Ch-nh-s-ch-C-ng-ty-403590f7e19e81759524ffcc0fc15288) (Approved)
  - `EDL-0008`: [Page ID `403590f7-e19e-81d7-9957-cd187c3df8fa`](https://app.notion.com/p/EDL-0008-Ki-n-tr-c-Contextual-Claim-Gate-Ki-m-so-t-N-p-Claims-ng-v-Ch-ng-nhi-m-Ng-c-nh-RAG-403590f7e19e81d79957cd187c3df8fa) (Approved)
  - `EDL-0009`: [Page ID `403590f7-e19e-81a3-b443-e08deef4e925`](https://app.notion.com/p/EDL-0009-nh-Gi-Ch-t-L-ng-Codebase-Ph-n-Lo-i-Code-Dirty-v-Chi-n-L-c-Gi-i-Quy-t-N-K-Thu-t-403590f7e19e81a3b443e08deef4e925) (Approved)
  - `EDL-0010`: [Page ID `403590f7-e19e-811a-9a02-cd8ddff7c38b`](https://app.notion.com/p/EDL-0010-Ki-n-tr-c-T-ng-Ph-n-Gi-i-T-i-Li-u-a-Ph-ng-Ti-n-AnyDoc-gRPC-Lark-OpenAPI-Tr-ch-Xu--403590f7e19e811a9a02cd8ddff7c38b) (Approved)

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

## Verification
- Context Truncation Fix:
  * Chạy kịch bản mô phỏng kiểm thử sinh câu trả lời với chunk đầy đủ: Gemini trích dẫn chính xác "ngày 25 hàng tháng" từ Sổ tay Nhân viên.
- AnyDoc gRPC Phase 1 Smoke Test:
  * Chạy script `test_grpc_smoke.py` từ virtualenv Python server:
    - `Connecting to gRPC DocReader at 127.0.0.1:50051...`
    - `ListEngines: 3 engines (builtin, markitdown, opendataloader) available`
    - `Read: markdown returned, error='' -> Status 100% Success`.

## Next concrete steps
1. **Giai đoạn 2 (Xây dựng Core Parser Services - EDL-0010):**
   - Xây dựng `server/services/docreader_service.py` (gRPC client AnyDoc có timeout, connection reuse, 50MB message limits).
   - Mở rộng `server/services/larkServices/lark_client.py` với `download_message_resource` (Lark IM binary) và `get_docx_raw_content` (Lark DocX OpenAPI).
   - Xây dựng `server/services/doc_parser_service.py` (điều phối nhận diện URL Lark Doc vs Binary Attachment).
2. **Giai đoạn 3 (Tích hợp Claims Pipeline & Dispatcher):**
   - Xây dựng `process_document_to_claims` trong `chat_service.py` và hook sự kiện vào `bot_service.py`.
3. **Giai đoạn 4 (Kiểm thử Toàn Diện & Đóng Gói):**
   - Viết unit test cho doc parser và test end-to-end với meeting notes.




