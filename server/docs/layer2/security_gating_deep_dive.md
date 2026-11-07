# Đặc tả Kỹ thuật Lớp 2: Kiểm soát an toàn & Phân loại ý định

Tài liệu này ghi lại chi tiết luồng xử lý kỹ thuật, các chốt chặn an toàn và cơ chế phân loại ý định của Lớp 2 trong quy trình xử lý hội thoại (`process_chat_pipeline`).

Mã nguồn liên quan:
- Bộ phân loại JEV: [`server/services/ai/jev_classifier.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/jev_classifier.py)
- Quy trình hội thoại: [`server/services/workflows/chat_workflow.py`](file:///Users/hoainam/Desktop/HiLark/server/services/workflows/chat_workflow.py)
- Kiểm duyệt quy tắc: [`server/services/knowledge/rule_engine.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/rule_engine.py)
- Quản lý phạm vi nhóm: [`server/services/knowledge/chat_scopes.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/chat_scopes.py)

---

## 1. Luồng xử lý tổng thể Lớp 2

```
Lớp 1 (Chat Queue / Dispatcher)
           │
           ▼
[1. text_filter: Kiểm tra độ dài & Làm sạch rác] ──(Lỗi / Vi phạm)──> Trả về 'invalid_input' (Dừng)
           │
           ▼
[2. chat_scopes: Kiểm tra trạng thái nhóm chat]
           │
           ├──(is_active == False)─────────────────────────────> Trả về 'group_inactive' (Dừng)
           │
           ▼
[3. jev_classifier: Kiểm tra chủ đề cấm / Vùng cấm]
           │
           ├──(is_forbidden == True)───────────────────────────> ZERO-RESPONSE + Thẻ nháp gửi Quản trị viên
           │
           ▼
[4. jev_classifier: Phân loại ý định 5 nhánh]
           │
           ├──(Người gửi là Quản trị viên trong nhóm)──────────> Chuyển MEMORY_ONLY hoặc IGNORE
           │
           ▼
[5. Quyết định định tuyến hành động]:
    ├── IGNORE                 ──> Kết thúc ngay (Bỏ qua, 0 token)
    ├── MEMORY_ONLY            ──> Bóc tách sự thật (LLM Extractor) -> Lưu MongoDB -> Kết thúc
    ├── REPLY_ONLY             ──> Chuyển tiếp sang Lớp 3 (WeKnora) & Lớp 4 (LLM QA)
    ├── MEMORY_AND_DRAFT       ──> Lưu MongoDB Claims + Soạn Thẻ nháp gửi Quản trị viên
    └── DRAFT_PENDING_APPROVAL ──> Chuyển sang Lớp 3 & 4 để soạn Thẻ nháp gửi Quản trị viên
```

---

## 2. Bảng phân rã các module chức năng

| Thành phần | Đường dẫn file | Vai trò kỹ thuật | Hàm / Lớp phụ trách |
| :--- | :--- | :--- | :--- |
| **Dọn rác văn bản** | [`server/services/knowledge/rule_engine.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/rule_engine.py) | Làm sạch ký tự lặp, chuẩn hóa khoảng trắng, kiểm tra giới hạn từ (2–1000 từ). | `validate_and_clean_query()` |
| **Quản lý phạm vi & Nhãn cấm** | [`server/services/knowledge/chat_scopes.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/chat_scopes.py) | Tra cứu trạng thái hoạt động, mức độ bảo mật và nhãn cấm từ collection `chat_scopes`. | `get_scope_by_chat_id()` |
| **Mô hình phân loại JEV** | [`server/services/ai/jev_classifier.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/jev_classifier.py) | Gọi JEV System 1 API kiểm tra chủ đề cấm và phân loại 5 nhánh hành động. | `check_forbidden_query()`<br/>`classify_message()` |
| **Điều phối quy trình** | [`server/services/workflows/chat_workflow.py`](file:///Users/hoainam/Desktop/HiLark/server/services/workflows/chat_workflow.py) | Chốt chặn an toàn, điều phối luồng xử lý, kích hoạt Strict HITL và chống vòng lặp. | `process_chat_pipeline()` |

---

## 3. Chi tiết kỹ thuật từng chốt chặn

### Chốt chặn 1: Dọn dẹp ký tự & Kiểm tra kích thước
- **Vị trí mã nguồn:** [`server/services/knowledge/rule_engine.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/rule_engine.py)
- **Đầu vào:** `query: str`
- **Quy trình xử lý:**
  1. Kiểm tra chuỗi rỗng: Nếu chuỗi rỗng hoặc chỉ chứa khoảng trắng, trả về lỗi đầu vào không hợp lệ.
  2. Lọc chuỗi ký tự lặp bằng Regex:
     ```python
     cleaned = re.sub(r'([!@#$%^&*?])\1+', r'\1', text)
     cleaned = re.sub(r'\s+', ' ', cleaned).strip()
     ```
  3. Kiểm tra số lượng từ:
     - `MIN_WORDS = 2`: Loại bỏ các tin nhắn cụt ("alo", "?").
     - `MAX_WORDS = 1000`: Ngăn chặn các câu hỏi quá dài làm tràn bộ nhớ hoặc vượt hạn ngạch token.

### Chốt chặn 2: Tra cứu phạm vi nhóm & Kiểm tra trạng thái
- **Vị trí mã nguồn:** [`server/services/knowledge/chat_scopes.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/chat_scopes.py)
- **Truy vấn:** Tra cứu theo cặp `(tenant_key, chat_id)`.
- **Xử lý:** Nếu `is_active == False` (trạng thái `paused`), hệ thống lập tức trả về `status = "group_inactive"`, không gọi WeKnora và không gọi LLM.

### Chốt chặn 3: Quét vùng cấm ngân sách và bảo mật (Strict HITL)
- **Vị trí mã nguồn:** [`server/services/ai/jev_classifier.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/jev_classifier.py)
- **Phạm vi bảo vệ:** Các nhãn cấm cấu hình trong `forbidden_labels` của nhóm chat (ví dụ: Ngân sách, Chi phí, Bảng lương, Hợp đồng đối tác).
- **Quy trình:**
  - Vòng 1: So khớp từ khóa Regex trong RAM (< 0.1ms).
  - Vòng 2: Phân tích ngữ nghĩa qua JEV API để nhận diện các câu hỏi ẩn ý, tiếng lóng né từ khóa.
- **Hành vi xử lý:**
  - Không phản hồi công khai vào nhóm chat (zero-response).
  - Soạn sẵn Thẻ nháp gửi DM cho Quản trị viên kèm lý do phân loại để Quản trị viên tự quyết định phát ngôn.

### Chốt chặn 4: Phân loại 5 nhánh ý định
- **Vị trí mã nguồn:** [`server/services/ai/jev_classifier.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/jev_classifier.py)
- **Các nhánh phân loại:**
  1. `IGNORE`: Lời chào hỏi, cảm ơn, tán gẫu $\rightarrow$ Kết thúc ngay lập tức.
  2. `MEMORY_ONLY`: Cập nhật tiến độ, quyết định, nhân sự $\rightarrow$ Kích hoạt `llm_extractor` lưu Claims vào MongoDB.
  3. `REPLY_ONLY`: Câu hỏi nghiệp vụ được chứng thực $\rightarrow$ Chuyển sang Lớp 3 (RAG) và Lớp 4 (LLM QA).
  4. `MEMORY_AND_DRAFT`: Vừa có thông tin vừa có câu hỏi $\rightarrow$ Lưu Claims và chuẩn bị Thẻ nháp gửi Quản trị viên.
  5. `DRAFT_PENDING_APPROVAL`: Câu hỏi nhạy cảm hoặc độ tin cậy thấp $\rightarrow$ Soạn Thẻ nháp gửi Quản trị viên.

### Chốt chặn 5: Chống vòng lặp phản hồi từ Quản trị viên
- **Vị trí mã nguồn:** [`server/services/workflows/chat_workflow.py`](file:///Users/hoainam/Desktop/HiLark/server/services/workflows/chat_workflow.py)
- Khi người gửi là Quản trị viên (`is_owner = True`):
  - Thông tin nghiệp vụ được ép về `MEMORY_ONLY` để ghi nhận dữ kiện mới.
  - Các trao đổi xã giao được ép về `IGNORE` để tránh bot xen ngang.

---

## 4. Tham số cấu hình Lớp 2

| Tham số | Vị trí lưu | Mô tả kỹ thuật |
| :--- | :--- | :--- |
| `status` | Collection `chat_scopes` | Trạng thái nhóm: `"active"` hoặc `"paused"`. |
| `security_level` | Collection `chat_scopes` | Cấp bảo mật: `"standard"` hoặc `"confidential"`. |
| `forbidden_labels` | Collection `chat_scopes` | Danh sách các chủ đề cấm của nhóm chat. |
| `JEV_API_KEY` | Biến môi trường `.env` | Khóa API truy cập dịch vụ JEV System 1. |
| `LARK_USER_OPEN_ID` | Biến môi trường `.env` / Tenant config | Open ID của Quản trị viên để nhận các thông báo cảnh báo và Thẻ nháp. |
