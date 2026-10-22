# 📘 BÓC TÁCH KỸ THUẬT: `utils/text_filter.py`
> **HiLark Server** — Module làm sạch cú pháp đầu vào (Layer 2) & dọn dẹp định dạng đầu ra (Layer 4).  
> **Vị trí file:** [`server/utils/text_filter.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py) (117 dòng, 4.5 KB).

---

## 🧭 1. VAI TRÒ VÀ BÀI TOÁN CỐT LÕI GIẢI QUYẾT

Module [`server/utils/text_filter.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py) đảm nhiệm vai trò **"Người gác cổng cú pháp" (Syntactic Sanitizer)** của hệ thống HiLark. Nó hoạt động tại hai đầu của đường ống xử lý:
1. **Đầu vào (Tiền xử lý tại Layer 2):** Tiếp nhận câu hỏi từ người dùng, làm sạch các ký tự đặc biệt spam, chuẩn hóa khoảng trắng và kiểm tra giới hạn từ nhằm ngăn chặn tấn công quá tải bộ nhớ hoặc tin nhắn rác cộc lốc.
2. **Đầu ra (Hậu xử lý tại Layer 4):** Quét sạch các thẻ XML/HTML kỹ thuật nội bộ của WeKnora/RAG (`<kb ...>`, `</kb>`, `<doc ...>`) trước khi gửi phản hồi về nhóm chat của người dùng.

---

## 🧠 2. TRIẾT LÝ THIẾT KẾ: TẠI SAO KHÔNG DÙNG TỪ ĐIỂN CẤM?

Một quyết định thiết kế cực kỳ quan trọng trong `TextFilter`:
> **`TextFilter` TUYỆT ĐỐI KHÔNG lọc câu theo từ điển cụm từ cấm (Blacklist/Keyword Filter).**

### Lý do thực tế:
* Nếu sử dụng bộ lọc từ điển thô sơ, hệ thống sẽ liên tục **chặn nhầm các câu hỏi nghiệp vụ chính đáng (False Positive)**:
  * Ví dụ: Nếu cấm từ *"lương"*, hệ thống có thể chặn nhầm câu: *"Khách hàng muốn tăng số **lượng** tài khoản?"* hoặc tên người/địa danh *"anh Lương"*, *"dự án Lương Sơn"*.
  * Nếu cấm từ *"chết"*, hệ thống sẽ chặn nhầm báo cáo kỹ thuật: *"Hệ thống bị **chết** cổng kết nối rồi"*.
* **Giải pháp phân tầng:**
  * `TextFilter` (Layer 2 - Bước 1): Chỉ tập trung dọn rác mặt chữ, ký tự và kiểm tra độ dài.
  * Việc nhận diện ngữ nghĩa nhạy cảm, ý định xấu được bàn giao hoàn toàn cho **Mô hình AI JEV System One** tại Bước 3 của Layer 2!

---

## 🔬 3. CHI TIẾT KỸ THUẬT CÁC HÀM TRONG MÃ NGUỒN

### A. Hàm tiền xử lý đầu vào: `validate_and_clean(text: str) -> str`
- **Vị trí:** [`server/utils/text_filter.py:L19-37`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py#L19-L37)
- **Đầu vào:** Chuỗi tin nhắn thô nhận từ người dùng (`text`).
- **Quy trình 3 bước xử lý:**

#### Bước 1: Kiểm tra chuỗi rỗng
```python
if not text or not text.strip():
    raise ValueError("Tin nhắn không được để trống.")
```

#### Bước 2: Dọn dẹp ký tự spam lặp & khoảng trắng thừa (Regex)
```python
# Rút gọn các ký tự đặc biệt lặp liên tiếp: ????? -> ?, !!!!! -> !
cleaned = re.sub(r'([!@#$%^&*?])\1+', r'\1', text)

# Dọn dẹp khoảng trắng dư thừa liên tiếp thành 1 dấu cách duy nhất
cleaned = re.sub(r'\s+', ' ', cleaned).strip()
```

#### Bước 3: Kiểm duyệt số lượng từ (Word Count Threshold)
```python
word_count = len(cleaned.split())

# 1. Chặn câu quá ngắn (Cộc lốc, vô nghĩa)
if word_count < self.MIN_WORDS: # MIN_WORDS = 2
    raise ValueError("Tin nhắn quá ngắn. Vui lòng cung cấp thêm thông tin.")

# 2. Chặn câu quá dài (Ngăn chặn tấn công làm tràn bộ nhớ LLM)
if word_count > self.MAX_WORDS: # MAX_WORDS = 1000 (~1300 tokens)
    raise ValueError(f"Tin nhắn quá dài ({word_count} từ). Giới hạn tối đa là {self.MAX_WORDS} từ.")
```

#### Xử lý phản hồi tại `chat_service.py` khi vi phạm:
Nếu `validate_and_clean` ném ra ngoại lệ `ValueError`, Layer 2 lập tức ngắt pipeline và trả về trạng thái lỗi an toàn:
```python
return {
    "status": "invalid_input",
    "jev_action": "IGNORE",
    "jev_confidence": 0.0,
    "message": str(e)
}
```

---

### B. Hàm hậu xử lý đầu ra: `clean_output(text: str) -> str`
- **Vị trí:** [`server/utils/text_filter.py:L39-91`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py#L39-L91)
- **Vai trò:** Hoạt động tại **Layer 4** trước khi gửi tin nhắn cho người dùng hoặc tạo bản nháp.
- **5 Bước làm sạch định dạng:**

1. **Xóa toàn bộ các thẻ XML/HTML trích dẫn nội bộ của RAG:**
   * Thẻ đơn: `<kb id="123" />`, `<chunk doc_id="456" />`
   * Thẻ cặp: `<kb>...</kb>`, `<doc>...</doc>`, `<citation>...</citation>`
   * Thẻ đóng/mở sót: `re.sub(r'<\/?(?:kb|doc|chunk|source|citation)\b[^>]*>', '', cleaned)`
2. **Xóa các ngoặc trích dẫn nguồn do LLM tự ý sinh ra:**
   * Xóa các cụm: `[Cập nhật hội thoại: ...]`, `[Tài liệu: ...]`, `[Nguồn: ...]`, `[Chunk ID: ...]`.
3. **Chữa lỗi hở dấu câu:**
   * Sau khi xóa thẻ XML, câu thường bị hở khoảng trắng: `"Dự án Atlas , deadline ngày mai"` $\rightarrow$ Chuyển thành `"Dự án Atlas, deadline ngày mai"`.
   ```python
   cleaned = re.sub(r'[ \t]+([,.:;?!])', r'\1', cleaned)
   ```
4. **Chuẩn hóa khoảng trắng ngang & Xóa khoảng trắng cuối dòng:**
   * Chuyển nhiều khoảng trắng ngang thành 1 dấu cách nhưng **giữ nguyên cấu trúc xuống dòng `\n`**.
   * Xóa khoảng trắng thừa ở cuối mỗi dòng (`[ \t]+\n` $\rightarrow$ `\n`).
5. **Rút gọn dòng trống liên tiếp:**
   * Giới hạn tối đa 2 dấu xuống dòng (`\n\n`), chống hiện tượng văn bản bị giãn dòng quá dài làm xấu giao diện chat.

---

### C. Hàm trích xuất siêu dữ liệu: `extract_kb_citations(text: str) -> list[dict]`
- **Vị trí:** [`server/utils/text_filter.py:L93-108`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py#L93-L108)
- **Công dụng:** Quét toàn bộ nội dung câu trả lời thô của LLM, tìm các thẻ `<kb attr="value" ... />` và bóc tách thành danh sách từ điển (`dict`) chứa metadata tài liệu (như `file_name`, `chunk_id`, `page_number`) phục vụ hiển thị nguồn trích dẫn chuyên nghiệp khi cần.

---

## 📋 4. BẢNG THAM SỐ CẤU HÌNH CỐT LÕI

| Thuộc tính | Giá trị | Giải thích ý nghĩa |
| :--- | :---: | :--- |
| `MIN_WORDS` | `2` từ | Số lượng từ tối thiểu để được coi là tin nhắn hợp lệ. Chặn các câu gõ nhầm 1 từ như `"a"`, `"?"`, `"alo"`. |
| `MAX_WORDS` | `1000` từ | Giới hạn tối đa (~1300 tokens) để chống tấn công làm tràn bộ nhớ đệm và bảo vệ hạn mức context của Gemini AI. |
| Singleton Instance | `text_filter = TextFilter()` | Đối tượng duy nhất được khởi tạo sẵn để import và dùng lại trên toàn dự án. |
