# 📘 SPEC KỸ THUẬT LAYER 3: KHO TRI THỨC ĐA NGUỒN & HỢP NHẤT BỐI CẢNH
> **Dự án HiLark Server** — Bản đặc tả kỹ thuật chi tiết (Spec), đối chiếu mã nguồn thực tế, ưu tiên tiếng Việt, không dùng từ ngữ bóng bẩy.

---

## 🧭 1. TỔNG QUAN LAYER 3 TRONG TOÀN BỘ PIPELINE

Trong quy trình xử lý hội thoại (`process_chat_pipeline`), **Layer 3** đóng vai trò là động cơ tri thức cốt lõi. Sau khi tin nhắn được Layer 2 chứng nhận an toàn, Layer 3 sẽ kích hoạt để bóc tách thông tin mới hoặc truy xuất và hợp nhất toàn bộ tài liệu tĩnh lẫn sự thật động:

```
[Tin nhắn an toàn từ Layer 2]
                │
                ├── (Nếu jev_action in MEMORY_ONLY, MEMORY_AND_DRAFT)
                │       └── Module 1: llm_extractor -> Trích xuất Entities & Facts -> Lưu MongoDB
                │
                └── (Nếu jev_action in REPLY_ONLY, MEMORY_AND_DRAFT, DRAFT_PENDING_APPROVAL)
                        │
                        ├── A. Đọc MongoDB Facts/Claims của nhóm [Tri thức động]
                        │
                        ├── B. Module 2: WeKnora Retrieve (RAG Hard Isolation) [Tài liệu tĩnh]
                        │       └── Module 3: JEV Semantic Filter & Rerank
                        │
                        ├── C. Module 4: Unified Rule Engine Sanitization (Quét nhãn cấm)
                        │
                        ├── D. Kiểm tra kho rỗng / Nhóm Tuyệt mật -> Downgrade sang Draft nếu cần
                        │
                        └── E. Module 5: ContextComposer -> Đóng gói bối cảnh phân cấp 3 phần
                                        │
                                        ▼
                        [Bàn giao sang Layer 4: Gemini Grounded QA & Persona Response]
```

---

## 🖼️ SƠ ĐỒ PHÂN RÃ THÀNH PHẦN LAYER 3

![Sơ đồ phân rã thành phần Lớp 3 thuần Việt](/Users/hoainam/.gemini/antigravity-ide/brain/7757b940-33a0-4b24-b567-26c89fe134f7/phan_ra_thanh_phan_lop_3_1792419378380.jpg)

---

## 🧩 2. BẢNG PHÂN RÃ CÁC MODULE THUỘC LAYER 3

> 💡 **Tài liệu bóc tách chi tiết từng Utils:** Xem tại thư mục [`ultis_docs/`](file:///Users/hoainam/Desktop/HiLark/server/docs/layer3/ultis_docs/README.md) gồm: [`llm_extractor.md`](file:///Users/hoainam/Desktop/HiLark/server/docs/layer3/ultis_docs/llm_extractor.md), [`rule_engine.md`](file:///Users/hoainam/Desktop/HiLark/server/docs/layer3/ultis_docs/rule_engine.md), [`context_composer.md`](file:///Users/hoainam/Desktop/HiLark/server/docs/layer3/ultis_docs/context_composer.md).

| Module | Đường dẫn file | Tài liệu bóc tách | Vai trò chính | Lớp / Hàm phụ trách |
| :--- | :--- | :---: | :--- | :--- |
| **Module 1: Bóc tách bộ nhớ động** | [`server/utils/llm_extractor.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/llm_extractor.py)<br/>[`server/models/memory.py`](file:///Users/hoainam/Desktop/HiLark/server/models/memory.py) | [Chi tiết](file:///Users/hoainam/Desktop/HiLark/server/docs/layer3/ultis_docs/llm_extractor.md) | Phân tích câu chat, bóc tách Thực thể (Entities) và Sự thật (Facts), quản lý chuỗi thay thế dữ liệu cũ (`superseded`). | `extract_async()`<br/>`save_extraction_to_mongo()` |
| **Module 2: Truy xuất tài liệu WeKnora** | [`server/services/weknora.py`](file:///Users/hoainam/Desktop/HiLark/server/services/weknora.py) | — | Kết nối WeKnora API, tìm kiếm vector/từ khóa trong các tài liệu tĩnh được chỉ định (`knowledge_ids`). | `WeKnoraService.retrieve()` |
| **Module 3: Bộ lọc an ninh tri thức** | [`server/utils/rule_engine.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/rule_engine.py) | [Chi tiết](file:///Users/hoainam/Desktop/HiLark/server/docs/layer3/ultis_docs/rule_engine.md) | Quét sạch các đoạn văn bản hoặc mệnh đề chứa chủ đề cấm (`forbidden_labels`) ngay trong RAM (0ms) trước khi gửi qua AI. | `RuleEngine.sanitize()` |
| **Module 4: Lọc ngữ nghĩa & Rerank** | [`server/services/jev.py`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py) | — | Gửi các đoạn trích ĐÃ KHỬ TRÙNG sang JEV System One để đánh giá mức độ liên quan (`RELEVANT`), loại bỏ tài liệu rác và tái sắp xếp. | `JevService.filter_chunks_relevance()` |
| **Module 5: Bộ hợp nhất bối cảnh** | [`server/utils/context_composer.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/context_composer.py) | [Chi tiết](file:///Users/hoainam/Desktop/HiLark/server/docs/layer3/ultis_docs/context_composer.md) | Đóng gói tri thức thành văn bản phân cấp 3 phần, áp dụng quy tắc Fact Override (sự thật hội thoại ghi đè tài liệu tĩnh). | `ContextComposer.compose()` |
| **Module 6: Điều phối luồng dữ liệu** | [`server/services/chat_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py) | — | Điều phối quy trình truy xuất, mở rộng câu truy vấn, hạ cấp an toàn khi kho tri thức rỗng. | `process_chat_pipeline()` (L406–L566) |

---

## 🔬 3. CHI TIẾT KỸ THUẬT TỪNG BƯỚC THỰC THI (CODE-LEVEL)

### Bước 1: Bóc tách thực thể & Mệnh đề sự thật (Memory Extraction & Lineage)
- **Vị trí mã nguồn:** [`server/utils/llm_extractor.py:L154-188`](file:///Users/hoainam/Desktop/HiLark/server/utils/llm_extractor.py#L154-L188) và [`server/services/chat_service.py:L133-188`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L133-L188)
- **Đầu vào:** `query_text: str`, `asserted_by: dict` (thẩm quyền người nói: `owner` hoặc `member`), `chat_id`, `project_tag`.
- **Bài toán kiến trúc cốt lõi:**
  * **Tại sao không thể trích xuất Claims đơn lẻ?** Nếu chỉ trích xuất các mệnh đề rời rạc (ví dụ: `deadline = 30/10`, `assignee = Nguyên`), các claims này sẽ bị "mồ côi" vì hệ thống không biết 30/10 là deadline của dự án nào hay của tính năng nào.
  * **Giải pháp của LLM Extractor:** Trích xuất **Thực thể (Entities)** trước để làm mỏ neo (`entity_id`). Nhờ đó, hệ thống mới có đối tượng cha cụ thể để **phân loại và sắp xếp từng Claims/Facts con vào đúng thực thể sở hữu**, triệt tiêu tình trạng "râu ông nọ cắm cằm bà kia".
- **Cơ chế bóc tách 2 tầng (Parent - Child):**
  1. Đọc danh sách thực thể và sự thật hiện có của nhóm từ MongoDB:
     ```python
     existing_entities = await get_mongo_entities()
     existing_facts = await get_mongo_facts(chat_id=chat_id, project_tag=project_tag)
     ```
  2. Gọi `extract_async()`: Sử dụng mô hình ngôn ngữ bóc tách tin nhắn theo cấu trúc cây:
     * **Tầng 1 - Entities (Thực thể cha / Khung mỏ neo):** `name`, `type` (`project`, `person`, `feature`, `team`, `customer`, `document`), `aliases`, sinh `stable_id` (uuid5).
     * **Tầng 2 - Facts/Claims (Sự thật con):** Bắt buộc phải gắn với một `entity_id` cha: `property`, `value`, `status` (`current`, `proposed`, `superseded`), `replaces` (ID của fact cũ thuộc cùng thực thể bị thay thế).
  3. **Lưu trữ phân cấp vào MongoDB (`save_extraction_to_mongo`):**
     * Collection `entities`: Lưu trữ các thực thể, tự động hợp nhất nếu trùng tên/bí danh.
     * Collection `facts`: Cập nhật trạng thái của fact cũ thành `superseded`, chèn fact mới với trạng thái `current`.

---

### Bước 2: Truy xuất tài liệu WeKnora với cách ly cứng & Mở rộng ngữ cảnh
- **Vị trí mã nguồn:** [`server/services/chat_service.py:L450-485`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L450-L485)
- **2 Giải pháp bảo vệ & tối ưu:**
  1. **RAG Hard Isolation (Cách ly cứng):**
     ```python
     target_knowledge_ids = scope_record.knowledge_ids if (scope_record and scope_record.knowledge_ids) else None
     chunks = await weknora_service.retrieve(
         query=retrieval_query,
         knowledge_base_ids=target_kbs,
         knowledge_ids=target_knowledge_ids,
         match_count=retrieve_count,
     )
     ```
     * Chỉ cho phép tìm kiếm trong đúng các ID tài liệu (`knowledge_ids`) được gắn quyền cho nhóm chat này.
  2. **Context-Driven Query Expansion (Mở rộng câu truy vấn theo bối cảnh):**
     ```python
     retrieval_query = clean_query
     if proj_context_name and proj_context_name.lower() not in clean_query.lower():
         retrieval_query = f"{clean_query} {proj_context_name}"
     ```
     * Tự động bổ sung tên dự án (`proj_context_name`) vào câu hỏi nếu người dùng hỏi tắt, nâng tỷ lệ tìm kiếm trúng tài liệu liên quan lên mức tối đa.

---

### Bước 3: Chốt chặn an ninh tri thức tập trung (Unified Rule Engine)
- **Vị trí mã nguồn:** [`server/utils/rule_engine.py:L1-489`](file:///Users/hoainam/Desktop/HiLark/server/utils/rule_engine.py) và [`server/services/chat_service.py:L513-522`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L513-L522)
- **Ưu tiên thực thi sớm (Early Execution):** Chạy **trước** JEV Rerank để loại bỏ ngay lập tức dữ liệu cấm (In-Memory 0ms, 0$), ngăn chặn triệt để nguy cơ gửi văn bản nhạy cảm sang API AI bên ngoài và tiết kiệm token mạng.
- **Cơ chế lọc 3 tầng:**
  1. **Tầng 1 (Canonical Property Mapping):** Tự động ánh xạ nhãn cấm (ví dụ: *"Ngân sách"*, *"Lương"*) sang các thuộc tính chuẩn: `budget`, `cost`, `price`, `salary`, `compensation`.
  2. **Tầng 2 (Dynamic Literal Substring Scan):** Quét so khớp chuỗi không dấu / có dấu chuẩn tiếng Việt (`remove_vietnamese_accents`) trên cả `content`, `document_name` của Chunks và `property`, `value`, `source_snippet` của Claims.
  3. **Tầng 3 (Data Quality Filter):** Loại bỏ các chunk rỗng hoặc claims thiếu thông tin.
- **2 Chốt chặn hạ cấp bảo vệ:**
  * **Hạ cấp khi kho rỗng (RAG Gate Empty Downgrade):**
    ```python
    if jev_action == "REPLY_ONLY" and not clean_chunks and not clean_claims:
        jev_action = "DRAFT_PENDING_APPROVAL"
    ```
  * **Khóa tự động trả lời cho nhóm Tuyệt mật (Strict Confidential Gating):**
    ```python
    if is_confidential_group and jev_action == "REPLY_ONLY":
        jev_action = "DRAFT_PENDING_APPROVAL"
    ```

---

### Bước 4: Lọc ngữ nghĩa thông minh & Rerank qua JEV System One
- **Vị trí mã nguồn:** [`server/services/jev.py:L104-197`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py#L104-L197) và [`server/services/chat_service.py:L524-535`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L524-L535)
- **Mục đích:** Chỉ nhận danh sách `clean_chunks` đã sạch từ Rule Engine, tiến hành loại bỏ các đoạn trích bị lạc đề và xếp đoạn hữu ích nhất lên đầu.
- **Kỹ thuật tối ưu 1 Call API Batch:**
  * Lấy tối đa 5 chunks hàng đầu (`candidate_chunks = clean_chunks[:5]`).
  * Chỉ cắt lấy 300 ký tự đầu của mỗi chunk (`max_snippet_chars = 300`) để tiết kiệm token và giảm độ trễ mạng.
  * Đóng gói toàn bộ 5 chunks vào 1 payload JSON duy nhất gửi sang endpoint `https://api.typesafe.ai/v1/systemone`:
    ```json
    {
      "state": "Bối cảnh: Trợ lý AI đang hỗ trợ giải đáp cho Dự án X.\nCâu hỏi của người dùng: \"...\"",
      "model": "jev-latest",
      "questions": {
        "chunk_1": { "type": "choice", "instructions": "Đoạn trích 1: \"...\". Có phù hợp để trả lời câu hỏi không?", "criteria": {"RELEVANT": "Phù hợp", "IRRELEVANT": "Lạc đề"} },
        "chunk_2": { "type": "choice", "instructions": "Đoạn trích 2: \"...\". Có phù hợp để trả lời câu hỏi không?", "criteria": {"RELEVANT": "Phù hợp", "IRRELEVANT": "Lạc đề"} }
      }
    }
    ```
- **Tái sắp xếp (Rerank):** Các chunk được gán điểm xác suất `jev_score` và sắp xếp giảm dần theo điểm:
  ```python
  relevant_chunks.sort(key=lambda x: x.get("jev_score", 0.0), reverse=True)
  ```
- **Phục hồi an toàn (Fallback):** Nếu JEV lọc hết sạch chunks hoặc API timeout, hệ thống tự động giữ lại danh sách `clean_chunks` ban đầu để không làm hỏng chu trình.

---

### Bước 5: Hợp nhất ngữ cảnh có cấu trúc (Context Composer & Fact Override)
- **Vị trí mã nguồn:** [`server/utils/context_composer.py:L93-250`](file:///Users/hoainam/Desktop/HiLark/server/utils/context_composer.py#L93-L250)
- **Cấu trúc ngữ cảnh hoàn chỉnh gồm 3 phần:**

```text
=== PHẦN 0: BỐI CẢNH DỰ ÁN & HỒ SƠ TÀI LIỆU CỦA NHÓM ===
• Nhóm chat : {chat_name}
• Dự án     : {project_name}
• Hồ sơ file: {documents_list}

=== PHẦN 1: TÀI LIỆU DỰ ÁN & VĂN BẢN HỆ THỐNG (WEKNORA) ===
[Tài liệu: {doc_name}]
{chunk_content}

=== PHẦN 2: THỰC TẾ CẬP NHẬT & MỆNH ĐỀ ĐỘNG (MONGODB CLAIMS) ===
⭐ [QUYẾT ĐỊNH CHÍNH THỨC TỪ CEO / BAN ĐIỀU HÀNH] [CURRENT]:
• {entity_name} -> {property}: {value} (Ghi chú: Thay thế cho {replaces})
```

- **Nguyên tắc giải quyết xung đột (Conflict Resolution Protocol):**
  1. **Fact Override:** Thông tin có cờ `[CURRENT]` trong Phần 2 LUÔN ĐƯỢC ƯU TIÊN TUYỆT ĐỐI so với văn bản tĩnh ở Phần 1.
  2. **Quyền hạn tối cao từ Sếp:** Các quyết định do tài khoản Owner chốt có hiệu lực cao nhất.
  3. **Lần vết thay đổi:** Khi có sự thay đổi (đổi lead, đổi deadline), AI bắt buộc phải chỉ ra quá trình chuyển giao cho người hỏi nắm rõ.

---

## ⚙️ 4. BẢNG THAM SỐ CẤU HÌNH & BỘ NHỚ LAYER 3

| Biến cấu hình / Thuộc tính | Vị trí định nghĩa | Giá trị mặc định | Giải thích chi tiết |
| :--- | :--- | :---: | :--- |
| `retrieve_count` | `chat_service.py` | `5` | Số lượng đoạn trích văn bản tối đa lấy về từ WeKnora. |
| `max_snippet_chars` | `services/jev.py` | `300` | Số ký tự tối đa mỗi chunk gửi sang JEV để tiết kiệm token. |
| `entities` | MongoDB Collection | Bảng dữ liệu | Lưu danh mục thực thể (`id`, `name`, `type`, `aliases`, `scope`). |
| `facts` | MongoDB Collection | Bảng dữ liệu | Lưu mệnh đề sự thật (`id`, `entity_id`, `property`, `value`, `status`, `replaces`). |
| `knowledge_ids` | MongoDB `chat_scopes` | Mảng chuỗi | Danh sách ID tài liệu được phép truy cập của nhóm trên WeKnora. |
| `forbidden_labels` | MongoDB `chat_scopes` | Mảng chuỗi | Danh sách nhãn cấm được Rule Engine dùng để thanh lọc dữ liệu. |

---

## 🎯 5. KẾT LUẬN & ĐIỂM CHUYỂN GIAO SANG LAYER 4

Sau khi kết thúc Layer 3, hệ thống đã sở hữu một khối dữ liệu ngữ cảnh (`composed_context`) hoàn chỉnh, chuẩn xác, đã được lọc sạch thông tin nhạy cảm và sắp xếp theo trật tự ưu tiên sự thật mới nhất.

Dữ liệu này được chuyển giao trọn vẹn sang **Layer 4: Sinh câu trả lời & Đóng vai người điều hành (Gemini Grounded Generation, Executive Persona & Draft Approval Workflow)** để sinh ra câu trả lời tự nhiên nhất nhân danh người quản lý.
