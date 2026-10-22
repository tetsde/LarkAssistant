# 📘 SPEC KỸ THUẬT LAYER 4: SINH CÂU TRẢ LỜI & ĐÓNG VAI NGƯỜI ĐIỀU HÀNH
> **Dự án HiLark Server** — Bản đặc tả kỹ thuật chi tiết (Spec), đối chiếu mã nguồn thực tế, ưu tiên tiếng Việt, không dùng từ ngữ bóng bẩy.

---

## 🧭 1. TỔNG QUAN LAYER 4 TRONG TOÀN BỘ PIPELINE

Trong quy trình xử lý hội thoại (`process_chat_pipeline`), **Layer 4** tiếp nhận bối cảnh tri thức đã hợp nhất từ Layer 3 (`composed_context`) để sinh ra câu trả lời cuối cùng, đóng vai nhà điều hành và thực hiện quy trình phân nhánh: phát ngôn trực tiếp vào nhóm hoặc lưu bản nháp chờ Sếp duyệt:

```
[Bối cảnh tri thức từ Layer 3: composed_context]
                 │
                 ▼
[Bước 1: Chọn Prompt & Nạp Persona Sếp]
     └── GROUNDED_QA_USER_PERSONA_PROMPT (Xưng hô đích danh, văn phong 10/10)
                 │
                 ▼
[Bước 2: Gemini Grounded QA Generation]
     ├── GLOBAL_LLM_SEMAPHORE (Bảo vệ tải trọng song song)
     ├── max_output_tokens = 4096 (Chống cụt câu)
     └── Fallback: weknora_service.get_chat_response() (Nếu LLM rỗng)
                 │
                 ▼
[Bước 3: Làm sạch định dạng qua text_filter.clean_output()]
     ├── Xóa sạch thẻ XML/HTML RAG (<kb .../>, <doc ...>)
     ├── Xóa ngoặc trích dẫn ([Tài liệu: ...], [Cập nhật hội thoại: ...])
     └── Sửa lỗi hở dấu câu & chuẩn hóa khoảng trắng/dòng trống
                 │
                 ▼
[Bước 4 & 5: Phân nhánh gửi tin & Phê duyệt bản nháp]:
     │
     ├── Nếu (is_confidential_group == True) HOẶC (jev_action in DRAFT_PENDING_APPROVAL, MEMORY_AND_DRAFT):
     │       ├── Lưu MongoDB: draft_store.create(PendingDraft(status='pending'))
     │       └── Gửi DM riêng tới Sếp: lark_service.send_bot_dm_to_owner(draft_card_text)
     │           [Cung cấp lệnh duyệt: Gửi / Sửa / Bỏ - KHÔNG phát ngôn vào nhóm]
     │
     └── Nếu (jev_action == REPLY_ONLY) VÀ (reply_to_lark == True):
             └── Phát ngôn vào nhóm: lark_service.areply_text(message_id, answer, as_user=True)
                 [Gửi dưới danh nghĩa tài khoản cá nhân của Sếp]
```

---

## 🧩 2. BẢNG PHÂN RÃ CÁC MODULE THUỘC LAYER 4

> 💡 **Tài liệu bóc tách chi tiết:** Xem tại thư mục [`ultis_docs/`](file:///Users/hoainam/Desktop/HiLark/server/docs/layer4/ultis_docs/README.md) gồm: [`output_sanitizer.md`](file:///Users/hoainam/Desktop/HiLark/server/docs/layer4/ultis_docs/output_sanitizer.md) và sơ đồ quan hệ phân cấp Parent-Child.

| Module | Đường dẫn file | Vai trò chính | Lớp / Hàm phụ trách |
| :--- | :--- | :--- | :--- |
| **Module 1: Động cơ sinh câu trả lời** | [`server/services/chat_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py) | Nạp persona điều hành, gọi Gemini QA có kiểm soát tải trọng, kích hoạt fallback WeKnora nếu lỗi. | `generate_grounded_answer()` (L190–L235) |
| **Module 2: Bộ làm sạch đầu ra** | [`server/utils/text_filter.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py) | Quét sạch toàn bộ các thẻ trích dẫn RAG XML/HTML, sửa lỗi dấu câu và chuẩn hóa markdown. | `TextFilter.clean_output()` (L39–L91)<br/>`TextFilter.extract_kb_citations()` |
| **Module 3: Quản lý bản nháp chờ duyệt** | [`server/models/chat_queue.py`](file:///Users/hoainam/Desktop/HiLark/server/models/chat_queue.py)<br/>[`server/services/chat_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py) | Lưu trữ bản ghi phê duyệt vào MongoDB `pending_drafts`, quản lý trạng thái `pending`, `approved`, `rejected`. | `draft_store.create()`<br/>`PendingDraft` Data Model |
| **Module 4: Cổng phân phối & Phát ngôn** | [`server/services/larkServices/lark_messenger.py`](file:///Users/hoainam/Desktop/HiLark/server/services/larkServices/lark_messenger.py) | Bắn tin phản hồi vào nhóm nhân danh User của Sếp hoặc gửi thẻ duyệt DM riêng tư cho Sếp. | `lark_service.areply_text(as_user=True)`<br/>`lark_service.send_bot_dm_to_owner()` |
| **Module 5: Điều phối định tuyến an toàn** | [`server/services/chat_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py) | Phân luồng giữa gửi thẳng và soạn nháp, kiểm tra chính sách bảo mật nhóm Tuyệt mật. | `process_chat_pipeline()` (L567–L679) |

---

## 🔬 3. CHI TIẾT KỸ THUẬT TỪNG BƯỚC THỰC THI (CODE-LEVEL)

### Bước 1: Nạp phong cách người điều hành (Persona Prompting)
- **Vị trí mã nguồn:** [`server/services/chat_service.py:L78-126`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L78-L126)
- **Đầu vào:** `context_text`, `query`, `user_name`, `responder_name`, `role`.
- **Cấu trúc nhắc lệnh chuẩn mực (Benchmark 10/10):**
  * Tự xưng là `"anh"`, gọi người hỏi là `"em"` hoặc gọi đích danh `{user_name}`.
  * Cấm tuyệt đối: Không xưng là AI/chatbot, không viết hoa chữ `"Anh"` ở giữa câu, không dùng đại từ xa cách như `"chúng tôi"`, `"anh/chị"`.
  * Nói như kiến thức của chính mình, tuyệt đối cấm nói: *"theo tài liệu WeKnora..."* hay *"theo cơ sở tri thức..."*.
  * **Scope Defaulting:** Thành viên hỏi cộc lốc về dự án $\rightarrow$ Tự động lấy tài liệu dự án của nhóm đó trả lời ngay, cấm hỏi ngược lại.

---

### Bước 2: Sinh câu trả lời qua Gemini với Semaphore bảo vệ
- **Vị trí mã nguồn:** [`server/services/chat_service.py:L190-235`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L190-L235)
- **Kiểm soát tải trọng:**
  ```python
  async with GLOBAL_LLM_SEMAPHORE:
      ans = await client.generate_text_async(
          prompt=prompt,
          model_name=model_name,
          max_output_tokens=4096,
      )
  ```
- **Xử lý dự phòng (Fallback):**
  ```python
  if not answer:
      fallback = await weknora_service.get_chat_response(ChatRequest(query=clean_query))
      if isinstance(fallback, dict) and "answer" in fallback:
          answer = fallback["answer"]
  ```

---

### Bước 3: Làm sạch định dạng văn bản qua `text_filter.clean_output()`
- **Vị trí mã nguồn:** [`server/utils/text_filter.py:L39-91`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py#L39-L91)
- **Thuật toán Regex 5 tầng:**
  1. Xóa thẻ XML/HTML: `re.sub(r'<(?:kb|doc|chunk|source|citation)\b[^>]*\/>', '', cleaned)`
  2. Xóa thẻ cặp: `re.sub(r'<(?:kb|doc|chunk|source|citation)\b[^>]*>.*?<\/(?:kb|doc|chunk|source|citation)>', '', cleaned)`
  3. Xóa ngoặc trích dẫn: `re.sub(r'\[(?:Cập nhật hội thoại|Tài liệu|Nguồn|Source|Chunk ID|Document)[^\]]*\]', '', cleaned)`
  4. Chữa lỗi khoảng cách trước dấu câu: `re.sub(r'[ \t]+([,.:;?!])', r'\1', cleaned)`
  5. Rút gọn dòng trống liên tiếp: `re.sub(r'\n{3,}', '\n\n', cleaned)`

---

### Bước 4 & 5: Cơ chế phân nhánh — Phát ngôn trực tiếp vs Duyệt nháp riêng tư

#### Nhánh A: Phát ngôn trực tiếp vào nhóm chat (`REPLY_ONLY`)
- **Điều kiện:** `jev_action == "REPLY_ONLY"` và nhóm KHÔNG thuộc diện Tuyệt mật (`not is_confidential_group`).
- **Thực thi:**
  ```python
  lark_reply_result = await lark_service.areply_text(
      message_id=message_id,
      text=answer,
      as_user=True, # Phát ngôn nhân danh tài khoản cá nhân của Sếp!
  )
  ```

#### Nhánh B: Soạn nháp chờ Sếp duyệt (`DRAFT_PENDING_APPROVAL`)
- **Điều kiện kích hoạt:**
  * Nhóm thuộc mức độ `TUYỆT MẬT` (`is_confidential_group = True`).
  * Hoặc `jev_action in ("DRAFT_PENDING_APPROVAL", "MEMORY_AND_DRAFT")`.
- **Thực thi:**
  1. Lưu vào MongoDB qua `draft_store.create(PendingDraft(...))`.
  2. Bọc thẻ thông báo duyệt nháp gửi thẳng vào tin nhắn riêng (DM) của Sếp:
     ```python
     dm_notice = await lark_service.send_bot_dm_to_owner(draft_card_text)
     ```
  3. Bot **hoàn toàn im lặng trong nhóm chat**, không để lộ bất kỳ dấu vết nào.

---

## ⚙️ 4. BẢNG THAM SỐ CẤU HÌNH LIÊN QUAN

| Biến cấu hình | Mặc định | Ý nghĩa điều khiển |
| :--- | :---: | :--- |
| `GEMINI_API_KEY` | — | Khóa API truy cập mô hình ngôn ngữ Gemini. |
| `LARK_USER_NAME` | `"Sếp"` | Tên thật của Sếp để nạp vào biến `{responder_name}` trong Persona. |
| `LARK_USER_ROLE` | `"CEO / Founder / CTO"` | Chức danh điều hành nạp vào biến `{role}` trong Persona. |
| `LARK_USER_OPEN_ID` | — | Mã định danh người dùng Lark của Sếp để nhận tin nhắn duyệt nháp (DM). |
| `max_output_tokens` | `4096` | Giới hạn độ dài câu trả lời, đảm bảo không bị đứt câu giữa chừng. |
