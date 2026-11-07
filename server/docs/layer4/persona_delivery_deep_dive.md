# Đặc tả Kỹ thuật Lớp 4: Sinh câu trả lời & Phê duyệt điều hành

Tài liệu này ghi lại chi tiết luồng xử lý kỹ thuật, động cơ Đa Nhà Cung Cấp LLM, thuật toán làm sạch đầu ra và cơ chế phê duyệt Human-in-the-Loop (HITL) qua Thẻ tương tác của Lớp 4 trong HiLark Server.

Mã nguồn liên quan:
- Điều phối LLM: [`server/services/ai/gemini_client.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/gemini_client.py)
- Quy trình hội thoại: [`server/services/workflows/chat_workflow.py`](file:///Users/hoainam/Desktop/HiLark/server/services/workflows/chat_workflow.py)
- Quản lý bản nháp: [`server/services/workflows/draft_workflow.py`](file:///Users/hoainam/Desktop/HiLark/server/services/workflows/draft_workflow.py)
- Dựng thẻ tương tác: [`server/services/lark/card_builder.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/card_builder.py)
- Xử lý tương tác thẻ: [`server/services/lark/handlers/card_action_handler.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/handlers/card_action_handler.py)
- Điều hành quản trị DM: [`server/services/lark/handlers/owner_command_handler.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/handlers/owner_command_handler.py)

---

## 1. Luồng xử lý tổng thể Lớp 4

```
[Bối cảnh tri thức từ Lớp 3: composed_context]
                 │
                 ▼
[Bước 1: Chọn Prompt & Thiết lập phong cách điều hành]
     └── Xưng hô tự nhiên, tôn trọng người hỏi, Fact Override
                 │
                 ▼
[Bước 2: Động cơ Đa Nhà Cung Cấp LLM (Gemini, ChatGPT, Claude, Custom)]
     ├── Phân giải BYOK 4 tầng (Request > User BYOK > Project Scope > Default)
     ├── GLOBAL_LLM_SEMAPHORE (Bảo vệ tải trọng song song)
     └── max_output_tokens = 4096 (Chống cụt câu)
                 │
                 ▼
[Bước 3: Làm sạch định dạng văn bản qua RuleEngine / Sanitizer]
     ├── Loại bỏ thẻ XML/HTML RAG (<kb .../>, <doc ...>)
     ├── Xóa ngoặc trích dẫn ([Tài liệu: ...], [Cập nhật hội thoại: ...])
     └── Sửa khoảng cách trước dấu câu và dòng trống thừa
                 │
                 ▼
[Bước 4 & 5: Phân nhánh gửi tin & Phê duyệt bản nháp]:
     │
     ├── Nếu (is_confidential_group == True) HOẶC (jev_action in [DRAFT_PENDING_APPROVAL, MEMORY_AND_DRAFT]):
     │       ├── Lưu MongoDB: collection draft_logs (status: 'pending')
     │       └── Gửi Thẻ tương tác HITL Card vào DM Quản trị viên
     │           [Nút 1-chạm: Duyệt và gửi / Nhờ AI sửa / Tự sửa / Hủy bỏ]
     │
     └── Nếu (jev_action == REPLY_ONLY) VÀ (reply_to_lark == True):
             └── Phản hồi trực tiếp vào nhóm chat qua Lark OpenAPI
                 [Trích dẫn tin nhắn gốc của người hỏi]
```

---

## 2. Bảng phân rã các module chức năng

| Thành phần | Đường dẫn file | Vai trò kỹ thuật | Lớp / Hàm phụ trách |
| :--- | :--- | :--- | :--- |
| **Động cơ Multi-LLM** | [`server/services/ai/gemini_client.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/gemini_client.py) | Điều phối các dòng mô hình (Gemini, Claude, GPT, Custom) và giải quyết khóa BYOK. | `LLMClient.generate_text_async()` |
| **Bộ làm sạch đầu ra** | [`server/services/knowledge/rule_engine.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/rule_engine.py) | Quét sạch các thẻ trích dẫn RAG XML/HTML, sửa lỗi dấu câu và chuẩn hóa markdown. | `clean_output()` |
| **Quản lý bản nháp chờ duyệt** | [`server/services/workflows/draft_workflow.py`](file:///Users/hoainam/Desktop/HiLark/server/services/workflows/draft_workflow.py) | Quản lý vòng đời bản nháp (`draft_logs`) trong MongoDB, cập nhật trạng thái `pending`, `approved`, `rejected`. | `draft_store.create()` |
| **Dựng thẻ tương tác** | [`server/services/lark/card_builder.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/card_builder.py) | Dựng cấu trúc JSON thẻ tương tác Lark: Thẻ duyệt nháp, Thẻ Master Digest, Thẻ Executive Control Hub. | `build_draft_approval_card()` |
| **Xử lý tương tác thẻ** | [`server/services/lark/handlers/card_action_handler.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/handlers/card_action_handler.py) | Xử lý sự kiện bấm nút trên thẻ tương tác, gọi cập nhật thẻ tại chỗ và bắn tin nhắn vào nhóm. | `handle_card_action()` |
| **Điều hành trung tâm DM** | [`server/services/lark/handlers/owner_command_handler.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/handlers/owner_command_handler.py) | Phản hồi Thẻ Executive Control Hub Card V2 khi Quản trị viên nhắn tin riêng với bot. | `handle_owner_command()` |

---

## 3. Chi tiết kỹ thuật từng bước thực thi

### Bước 1: Thiết lập phong cách người điều hành (Persona Prompting)
- **Vị trí mã nguồn:** [`server/services/workflows/chat_workflow.py`](file:///Users/hoainam/Desktop/HiLark/server/services/workflows/chat_workflow.py)
- **Cấu trúc:** Nạp chỉ dẫn xưng hô tự nhiên, tôn trọng người hỏi; trả lời như kiến thức của chính mình, không để lộ các thuật ngữ máy móc ("theo tài liệu WeKnora").
- **Fact Override:** Nếu thông tin cũ trong tài liệu đã bị thay thế bởi quyết định mới chốt trong nhóm chat, câu trả lời tự động nêu rõ dữ kiện mới nhất.
- **Scope Defaulting:** Khi thành viên hỏi ngắn gọn về dự án, hệ thống tự động sử dụng tài liệu của dự án gắn với nhóm đó để phản hồi ngay, không hỏi lại.

---

### Bước 2: Động cơ Đa Nhà Cung Cấp LLM & Phân giải BYOK
- **Vị trí mã nguồn:** [`server/services/ai/gemini_client.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/gemini_client.py)
- **Các dòng mô hình hỗ trợ:**
  - Google Gemini: `gemini-2.0-flash`, `gemini-1.5-pro`
  - OpenAI ChatGPT: `gpt-4o`, `gpt-4o-mini`
  - Anthropic Claude: `claude-3-5-sonnet`
  - Custom OpenAI-Compatible: DeepSeek, vLLM, Ollama (hỗ trợ tùy biến `base_url` và `timeout`)
- **Phân giải khóa BYOK 4 tầng:**
  $$\text{Request Override} \longrightarrow \text{User BYOK (AES-256)} \longrightarrow \text{Project Chat Scope} \longrightarrow \text{System Default (.env)}$$

---

### Bước 3: Thuật toán làm sạch đầu ra (Sanitizer)
- **Vị trí mã nguồn:** [`server/services/knowledge/rule_engine.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/rule_engine.py)
- **Các bước làm sạch bằng Regex:**
  1. Xóa thẻ tự đóng: `re.sub(r'<(?:kb|doc|chunk|source|citation)\b[^>]*\/>', '', cleaned)`
  2. Xóa thẻ cặp: `re.sub(r'<(?:kb|doc|chunk|source|citation)\b[^>]*>.*?<\/(?:kb|doc|chunk|source|citation)>', '', cleaned)`
  3. Xóa ngoặc trích dẫn: `re.sub(r'\[(?:Cập nhật hội thoại|Tài liệu|Nguồn|Source|Chunk ID|Document)[^\]]*\]', '', cleaned)`
  4. Sửa khoảng trắng trước dấu câu: `re.sub(r'[ \t]+([,.:;?!])', r'\1', cleaned)`
  5. Rút gọn dòng trống liên tiếp (giữ tối đa 2 dấu xuống dòng `\n\n`).

---

### Bước 4: Luồng phê duyệt bản nháp qua Thẻ tương tác (HITL Draft Card)
- **Vị trí mã nguồn:** [`server/services/workflows/draft_workflow.py`](file:///Users/hoainam/Desktop/HiLark/server/services/workflows/draft_workflow.py), [`server/services/lark/card_builder.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/card_builder.py)
- **Điều kiện kích hoạt:** Nhóm thuộc diện bảo mật cao (`confidential`), câu hỏi vi phạm vùng cấm ngân sách/lương (Strict HITL) hoặc JEV đánh giá rủi ro.
- **Thao tác trên thẻ:**
  - `[Duyệt và gửi]`: Gửi câu trả lời vào nhóm chat và cập nhật trạng thái thẻ thành đã duyệt.
  - `[Nhờ AI sửa lại]`: Mở hộp thoại nhập yêu cầu chỉ đạo, LLM viết lại nội dung và cập nhật thẻ.
  - `[Tự sửa]`: Mở form chỉnh sửa văn bản trực tiếp trên giao diện Lark.
  - `[Hủy bỏ]`: Hủy bản nháp an toàn, không phát ngôn vào nhóm.

---

### Bước 5: Bảng điều khiển Quản trị (Executive Control Hub Card V2)
- **Vị trí mã nguồn:** [`server/services/lark/handlers/owner_command_handler.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/handlers/owner_command_handler.py)
- Trong tin nhắn riêng với Quản trị viên, hệ thống luôn phản hồi bằng Thẻ bảng điều khiển 2 hàng nút 1-chạm:
  - Hàng 1: Lark Base Quản trị, WeKnora Console, Screen Guide Onboarding.
  - Hàng 2: Báo cáo ngày (Daily Digest), Trạng thái vận hành hệ thống, Tài khoản WeKnora.
- Loại bỏ hoàn toàn cú pháp lệnh văn bản trong DM 1-1.

---

## 4. Tham số cấu hình Lớp 4

| Tham số | Giá trị mặc định | Mô tả kỹ thuật |
| :--- | :---: | :--- |
| `DEFAULT_LLM_PROVIDER` | `google` | Nhà cung cấp LLM mặc định (`google`, `openai`, `anthropic`, `custom`). |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Tên mô hình Gemini mặc định. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Tên mô hình OpenAI mặc định. |
| `ANTHROPIC_MODEL` | `claude-3-5-sonnet-20241022` | Tên mô hình Anthropic mặc định. |
| `LLM_DEFAULT_TIMEOUT` | `60.0` | Thời gian chờ tối đa khi gọi LLM (giây). |
| `MAX_OUTPUT_TOKENS` | `4096` | Hạn mức độ dài sinh phản hồi của LLM. |
