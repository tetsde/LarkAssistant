# Đặc tả Kỹ thuật Lớp 3: Kho tri thức đa nguồn & Hợp nhất bối cảnh

Tài liệu này ghi lại chi tiết luồng xử lý kỹ thuật, cấu trúc bóc tách dữ liệu, cơ chế truy xuất WeKnora Hybrid RAG và nguyên lý hợp nhất bối cảnh của Lớp 3 trong HiLark Server.

Mã nguồn liên quan:
- Trích xuất tài liệu & OCR: [`server/services/knowledge/doc_parser.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/doc_parser.py)
- AnyDoc gRPC Reader: [`server/services/knowledge/docreader_client.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/docreader_client.py)
- Truy xuất WeKnora: [`server/services/knowledge/weknora_client.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/weknora_client.py)
- Bóc tách thực thể & sự thật: [`server/services/ai/llm_extractor.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/llm_extractor.py)
- Hợp nhất bối cảnh: [`server/services/knowledge/context_composer.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/context_composer.py)
- Kiểm duyệt an toàn: [`server/services/knowledge/rule_engine.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/rule_engine.py)

---

## 1. Luồng xử lý tổng thể Lớp 3

```
[Tin nhắn hợp lệ từ Lớp 2]
                │
                ├── (Nếu jev_action in [MEMORY_ONLY, MEMORY_AND_DRAFT])
                │       └── llm_extractor -> Trích xuất Entities & Claims -> Lưu MongoDB
                │
                └── (Nếu jev_action in [REPLY_ONLY, MEMORY_AND_DRAFT, DRAFT_PENDING_APPROVAL])
                        │
                        ├── A. Đọc MongoDB Claims của nhóm chat theo tenant_key
                        │
                        ├── B. WeKnora Hybrid RAG (Phân vùng theo dataset_id của nhóm)
                        │       └── JEV Semantic Filter & Rerank
                        │
                        ├── C. Rule Engine (Line-level Redaction che nhãn cấm)
                        │
                        ├── D. Kiểm tra kho rỗng -> Hạ cấp sang Thẻ nháp nếu cần
                        │
                        └── E. ContextComposer -> Hợp nhất bối cảnh 3 phần (Hạn mức 16.000 ký tự)
                                        │
                                        ▼
                        [Bàn giao sang Lớp 4: Multi-Provider LLM & HITL Gateway]
```

---

## 2. Bảng phân rã các module chức năng

| Thành phần | Đường dẫn file | Vai trò kỹ thuật | Lớp / Hàm phụ trách |
| :--- | :--- | :--- | :--- |
| **Bóc tách ký ức động** | [`server/services/ai/llm_extractor.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/llm_extractor.py) | Bóc tách Thực thể và Mệnh đề sự thật, quản lý lịch sử thay thế (`superseded`), băm compound key theo tenant. | `extract_async()`<br/>`generate_stable_entity_id()` |
| **Truy xuất WeKnora** | [`server/services/knowledge/weknora_client.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/weknora_client.py) | Kết nối WeKnora API, tìm kiếm vector + BM25 trong các dataset được cấp phép cho nhóm. | `WeKnoraClient.retrieve()` |
| **Đọc tệp AnyDoc gRPC** | [`server/services/knowledge/docreader_client.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/docreader_client.py) | Kết nối kênh gRPC buffer 50MB tới `WeKnora-docreader:50051`, phân giải 17 định dạng văn bản sang Markdown. | `DocReaderClient.parse_file()` |
| **Kiểm duyệt an toàn** | [`server/services/knowledge/rule_engine.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/rule_engine.py) | Line-level Redaction che các dòng dữ liệu nhạy cảm trước khi đưa vào prompt của LLM. | `RuleEngine.sanitize()` |
| **Lọc ngữ nghĩa & Rerank** | [`server/services/ai/jev_classifier.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/jev_classifier.py) | Đánh giá độ tương quan ngữ nghĩa của các đoạn trích từ WeKnora, loại bỏ đoạn lạc đề. | `filter_chunks_relevance()` |
| **Hợp nhất bối cảnh** | [`server/services/knowledge/context_composer.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/context_composer.py) | Hợp nhất tri thức thành văn bản 3 phần, áp dụng Fact Override (`CURRENT Claims > WeKnora Documents`). | `ContextComposer.compose()` |

---

## 3. Chi tiết kỹ thuật từng bước thực thi

### Bước 1: Bóc tách thực thể và mệnh đề sự thật (Entity-Claim Lineage)
- **Vị trí mã nguồn:** [`server/services/ai/llm_extractor.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/llm_extractor.py)
- **Đầu vào:** `query_text: str`, `tenant_key: str`, `chat_id: str`, `project_tag: str`.
- **Cơ chế bóc tách 2 tầng:**
  1. **Thực thể (Entities):** Đóng vai trò là mỏ neo định danh (`project`, `person`, `feature`, `team`, `customer`, `document`).
     - Entity ID được băm bằng thuật toán SHA256/UUID5 kết hợp `f"{clean_tenant}:{clean_ws}:{clean_name}"`.
     - Lưu trữ trong collection `memories` với compound unique index `[("tenant_key", ASCENDING), ("id", ASCENDING)]`, ngăn chặn hoàn toàn va chạm ID giữa hai khách thuê có cùng tên dự án.
  2. **Mệnh đề sự thật (Claims):** Bắt buộc phải gắn với một `entity_id` cha: `property`, `value`, `status` (`current`, `proposed`, `superseded`), `replaces`.
     - Khi có dữ kiện mới chốt, dữ kiện cũ cùng thuộc tính tự động chuyển sang `superseded`.

### Bước 2: Truy xuất tài liệu WeKnora với cách ly cứng
- **Vị trí mã nguồn:** [`server/services/knowledge/weknora_client.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/weknora_client.py)
- **Nguyên tắc cô lập:**
  - Mỗi nhóm chat chỉ được phép tìm kiếm trong đúng các `dataset_id` được liên kết trong collection `chat_scopes`.
  - Mở rộng ngữ cảnh tự động: Bổ sung tên dự án liên kết vào câu truy vấn tìm kiếm nếu người dùng hỏi ngắn, giúp thuật toán hybrid search của WeKnora tìm chính xác tài liệu liên quan.

### Bước 3: Kiểm duyệt an toàn tri thức (Rule Engine Line-level Redaction)
- **Vị trí mã nguồn:** [`server/services/knowledge/rule_engine.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/rule_engine.py)
- **Cơ chế xử lý:**
  - Đối chiếu nội dung với danh sách `forbidden_labels` của nhóm chat.
  - Line-level Redaction: Thay thế các dòng chứa số liệu bảo mật bằng nhãn `[REDACTED: Thông tin bảo mật]` mà vẫn giữ nguyên các dòng mô tả quy trình kỹ thuật xung quanh, bảo đảm LLM vẫn hiểu được ngữ cảnh tổng thể.

### Bước 4: Lọc ngữ nghĩa và tái sắp xếp (JEV Rerank)
- **Vị trí mã nguồn:** [`server/services/ai/jev_classifier.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/jev_classifier.py)
- **Cách thức hoạt động:**
  - Đánh giá độ tương quan giữa câu hỏi và từng đoạn trích tài liệu.
  - Sắp xếp các đoạn trích có điểm tương quan cao nhất lên đầu; loại bỏ các đoạn không liên quan.
  - Hạ cấp an toàn khi kho rỗng: Nếu cả WeKnora và MongoDB đều không có dữ liệu chứng thực, chuyển câu hỏi sang luồng soạn Thẻ nháp gửi Quản trị viên phê duyệt.

### Bước 5: Hợp nhất bối cảnh có thứ tự ưu tiên (Context Composer)
- **Vị trí mã nguồn:** [`server/services/knowledge/context_composer.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/context_composer.py)
- **Hạn mức 16.000 ký tự:** Giữ trọn vẹn các tài liệu quy trình dài không bị cắt cụt.
- **Cấu trúc bối cảnh 3 phần:**
  1. `=== PHẦN 0: BỐI CẢNH DỰ ÁN & HỒ SƠ TÀI LIỆU CỦA NHÓM ===`
  2. `=== PHẦN 1: TÀI LIỆU DỰ ÁN & VĂN BẢN GỐC (WEKNORA) ===`
  3. `=== PHẦN 2: THỰC TẾ CẬP NHẬT & MỆNH ĐỀ ĐỘNG (MONGODB CLAIMS) ===` (Ưu tiên số 1 ghi đè lên Phần 1).

---

## 4. Bảng tham số cấu hình Lớp 3

| Biến cấu hình | Vị trí | Mô tả kỹ thuật |
| :--- | :--- | :--- |
| `DOCREADER_GRPC_HOST` | Biến môi trường `.env` | Địa chỉ máy chủ gRPC trích xuất văn bản AnyDoc (mặc định: `127.0.0.1`). |
| `DOCREADER_GRPC_PORT` | Biến môi trường `.env` | Cổng dịch vụ gRPC AnyDoc DocReader (mặc định: `50051`). |
| `WEKNORA_API_KEY` | Biến môi trường `.env` | Khóa API kết nối WeKnora RAG Engine. |
| `BASE_URL` | Biến môi trường `.env` | Endpoint WeKnora API (mặc định: `http://localhost:8080/api/v1`). |
| `max_chunk_chars` | `ContextComposer` | Hạn mức ký tự tối đa của bối cảnh tài liệu (16.000 ký tự). |
| `retrieve_count` | `WeKnoraClient` | Số đoạn trích tối đa truy xuất từ WeKnora (mặc định: 5 chunks). |
