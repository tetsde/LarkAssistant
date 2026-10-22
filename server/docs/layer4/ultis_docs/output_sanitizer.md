# 📘 BÓC TÁCH KỸ THUẬT: BỘ LÀM SẠCH ĐẦU RA & ĐỊNH DẠNG BẢN NHÁP
> **HiLark Server** — Module làm sạch câu trả lời AI & định dạng thông báo duyệt nháp.  
> **Vị trí file:** [`server/utils/text_filter.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py) và [`server/services/chat_service.py:L586-636`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L586-L636).

---

## 🧭 1. VAI TRÒ VÀ BÀI TOÁN CỐT LÕI GIẢI QUYẾT

Khi mô hình ngôn ngữ lớn (LLM Gemini hoặc WeKnora Chat) sinh ra câu trả lời, đầu ra thường chứa nhiều "dấu vết kỹ thuật" không mong muốn:
1. **Thẻ trích dẫn nội bộ của RAG:** Các thẻ XML như `<kb id="123" />`, `<doc title="..." />`, `[Tài liệu: ...]`. Nếu để nguyên gửi vào nhóm, người dùng sẽ nhận ra ngay đây là câu trả lời do máy sinh ra.
2. **Lỗi hở dấu câu và khoảng cách rác:** Sau khi bóc thẻ hoặc ghép từ, văn bản hay bị lỗi như: *"Dự án Atlas , deadline ngày mai"* hoặc bị cách nhiều dòng trống liên tiếp (`\n\n\n\n`).
3. **Đóng gói thông tin duyệt nháp:** Khi câu hỏi rơi vào diện Tuyệt mật hoặc nhạy cảm, hệ thống cần một bộ định dạng thẻ thông báo chuẩn chỉnh, cung cấp đầy đủ bối cảnh và lệnh duyệt để Sếp thao tác nhanh nhất.

Bộ tiện ích hậu xử lý của Layer 4 giải quyết triệt để các vấn đề trên.

---

## 🔬 2. CHI TIẾT KỸ THUẬT CÁC THUẬT TOÁN HẬU XỬ LÝ

### A. Thuật toán làm sạch văn bản 5 tầng (`clean_output`)
- **Vị trí:** [`server/utils/text_filter.py:L39-91`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py#L39-L91)
- **Đầu vào:** Chuỗi câu trả lời thô từ LLM (`text: str`).

```
Câu trả lời thô từ LLM
         │
         ▼
[Tầng 1: Xóa thẻ XML/HTML RAG] ──> Xóa <kb.../>, <doc>...</doc>, <chunk...>
         │
         ▼
[Tầng 2: Xóa ngoặc trích dẫn nguồn] ──> Xóa [Cập nhật hội thoại: ...], [Tài liệu: ...]
         │
         ▼
[Tầng 3: Chữa lỗi hở dấu câu] ──> Chuyển 'từ ,' thành 'từ,'
         │
         ▼
[Tầng 4: Chuẩn hóa khoảng trắng ngang] ──> Giữ nguyên \\n, gom nhiều dấu cách thành 1
         │
         ▼
[Tầng 5: Rút gọn dòng trống liên tiếp] ──> Giới hạn tối đa 2 dấu xuống dòng (\\n\\n)
         │
         ▼
Văn bản thành phẩm sạch 100%
```

#### Chi tiết mã nguồn từng tầng:
```python
def clean_output(self, text: str) -> str:
    if not text or not isinstance(text, str):
        return ""
    cleaned = text

    # 1. Xóa các thẻ XML/HTML trích dẫn RAG (thẻ đơn, thẻ đóng mở, flag DOTALL)
    cleaned = re.sub(r'<(?:kb|doc|chunk|source|citation)\b[^>]*\/>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<(?:kb|doc|chunk|source|citation)\b[^>]*>.*?<\/(?:kb|doc|chunk|source|citation)>', '', cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r'<\/?(?:kb|doc|chunk|source|citation)\b[^>]*>', '', cleaned, flags=re.IGNORECASE)

    # 1.1 Xóa các thẻ ngoặc trích dẫn nguồn do LLM tự ý sinh ra
    cleaned = re.sub(r'\[(?:Cập nhật hội thoại|Tài liệu|Nguồn|Source|Chunk ID|Document)[^\]]*\]', '', cleaned, flags=re.IGNORECASE)

    # 2. Xóa khoảng trắng đứng trước dấu câu do việc xóa thẻ để lại ("abc , xyz" -> "abc, xyz")
    cleaned = re.sub(r'[ \t]+([,.:;?!])', r'\1', cleaned)

    # 3. Chuẩn hóa khoảng trắng ngang (nhiều dấu cách -> 1 dấu cách, giữ nguyên \n)
    cleaned = re.sub(r'[^\S\r\n]+', ' ', cleaned)

    # 4. Xóa khoảng trắng ở cuối mỗi dòng
    cleaned = re.sub(r'[ \t]+\n', '\n', cleaned)

    # 5. Rút gọn nhiều dòng trống liên tiếp (3 \n trở lên -> tối đa 2 \n)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    return cleaned.strip()
```

---

### B. Bộ định dạng thẻ tin nhắn duyệt nháp (`draft_card_text`)
- **Vị trí:** [`server/services/chat_service.py:L608-629`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L608-L629)
- **Mục đích:** Khi gặp nhóm Tuyệt mật hoặc câu hỏi có rủi ro, hệ thống đóng gói toàn bộ bối cảnh vào một thông điệp trực quan gửi riêng cho Sếp qua tin nhắn trực tiếp (Direct Message):

```python
draft_card_text = (
    f"📝 [SOẠN NHÁP CHỜ DUYỆT - {header_title}]\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    f"👥 Nhóm chat : {chat_title}\n"
    f"🛡️ Bảo mật   : {'TUYỆT MẬT (Khóa auto-reply)' if is_confidential_group else scope_record.security_level}\n"
    f"👤 Người hỏi : {user_name or 'bạn'}\n"
    f"💬 Câu hỏi   : \"{clean_query}\"\n\n"
    f"💡 Bản nháp AI soạn sẵn:\n"
    f"\"{answer}\"\n\n"
    f"⚠️ Lý do: {reason_text}\n"
    f"👉 Hành động chờ duyệt: Nhắn lại [Gửi] / [Sửa: <nội dung>] / [Bỏ]\n"
    f"🆔 Message ID gốc: {message_id or 'N/A'}\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
)
```

* **3 Lệnh duyệt nhanh dành cho Sếp:**
  1. `Gửi`: Đồng ý nội dung bản nháp, bot lập tức bắn câu trả lời vào nhóm chat nhân danh Sếp.
  2. `Sửa: <nội dung>`: Thay thế câu trả lời bằng nội dung do Sếp chỉnh sửa rồi mới gửi vào nhóm.
  3. `Bỏ`: Hủy bỏ câu trả lời, bot im lặng hoàn toàn.

---

### C. Cơ chế phát ngôn nhân danh cá nhân Sếp (`as_user=True`)
- **Vị trí:** [`server/services/larkServices/lark_messenger.py`](file:///Users/hoainam/Desktop/HiLark/server/services/larkServices/lark_messenger.py) và [`chat_service.py:L657-661`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L657-L661)

```python
lark_reply_result = await lark_service.areply_text(
    message_id=message_id,
    text=answer,
    as_user=True, # QUAN TRỌNG NHẤT
)
```

| Tiêu chí | Gửi dạng Bot thông thường (`as_user=False`) | Gửi nhân danh cá nhân Sếp (`as_user=True`) |
| :--- | :--- | :--- |
| **Danh tính hiển thị** | Tên con Bot (ví dụ: *"HiLark Assistant (Bot)"*) | **Tên và Avatar thật của Sếp** trên Lark |
| **Loại Token sử dụng** | `tenant_access_token` của Bot | `user_access_token` được ủy quyền của Sếp |
| **Cảm nhận của nhân sự** | Đang nói chuyện với Chatbot tự động | **Đang nhận chỉ đạo trực tiếp từ Sếp** |
| **Hiệu lực quản trị** | Thấp, mang tính tham khảo | **Cao nhất, là quyết định điều hành chính thức** |
