# Bóc Tách Hoạt Động Của Context Composer (Bộ Ghép Bối Cảnh)

Tài liệu giải thích luồng xử lý thực tế của module [`ContextComposer`](file:///Users/hoainam/Desktop/HiLark/server/utils/context_composer.py#L91) trong việc kết hợp dữ liệu từ cơ sở dữ liệu và tài liệu để phục vụ trả lời câu hỏi.

---

## 1. Ảnh Trực Quan Luồng Hoạt Động

![Sơ đồ luồng hoạt động Context Composer](/Users/hoainam/.gemini/antigravity-ide/brain/72e9f6c9-730f-41c5-9cc5-0feac227bdeb/context_composer_flow_1791871702080.jpg)

---

## 2. Context Composer Lôi Dữ Liệu Từ DB Lên Rồi Làm Gì Nữa?

Toàn bộ quá trình từ lúc lấy dữ liệu đến khi trả lời được chia thành 3 giai đoạn rõ ràng:

### Giai đoạn 1: Lấy Dữ Liệu Từ 2 Nguồn & Lọc Sơ Bộ

1. **Nguồn 1 - MongoDB (Tri thức động / Sự thật cập nhật)**:
   - Kéo các thông tin đang có hiệu lực (`status == "current"`), ví dụ: dự án Atlas ngân sách hiện tại là `300 triệu`.
2. **Nguồn 2 - WeKnora (Tri thức tĩnh / Tài liệu văn bản)**:
   - Kéo các đoạn văn bản liên quan từ tài liệu nội bộ (PDF, Word, quy trình).
3. **[ĐIỂM CÓ LLM / JEV] Lọc tài liệu liên quan**:
   - JEV dùng mô hình ngôn ngữ để đọc lướt qua các đoạn tài liệu tìm được và câu hỏi của người dùng.
   - Loại bỏ các đoạn văn bản rác, chỉ giữ lại các đoạn tài liệu thực sự liên quan đến câu hỏi.

---

### Giai đoạn 2: Bên Trong Context Composer (XỬ LÝ CODE PYTHON THUẦN - Không tốn token LLM)

Sau khi kéo dữ liệu từ DB lên, `ContextComposer` thực hiện 4 bước xử lý logic thuần túy bằng code Python:

#### Bước 1: Chuẩn hoá dữ liệu (Normalize)
- Đưa dữ liệu từ WeKnora về cấu trúc chuẩn (`RetrievedChunk`), tự động xóa các đoạn bị trùng lặp nội dung.
- Đưa dữ liệu từ MongoDB về cấu trúc chuẩn (`NormalizedClaim`), sắp xếp các thông tin đang có hiệu lực (`current`) lên đầu, thông tin cũ đã bị thay thế (`superseded`) xuống dưới.

#### Bước 2: So khớp chéo thực thể (Cross Alignment)
- Dò xem trong câu hỏi và trong các đoạn tài liệu đang nhắc đến dự án hay người nào.
- **Tác dụng**: Nếu câu hỏi chỉ hỏi về dự án "Atlas", hệ thống sẽ **tự động loại bỏ toàn bộ thông tin của các dự án khác** (như HiLark, Alpha) ra ngoài. Tránh việc đưa thông tin của dự án khác vào gây nhầm lẫn.

#### Bước 3: Nhóm dữ liệu theo từng đối tượng (Grouping)
- Gom tất cả thông tin lại theo từng chủ thể cụ thể, ví dụ:
  ```text
  📦 THỰC THỂ: ATLAS
    • [CURRENT] budget = "300 triệu"
    • [CURRENT] deadline = "30/10/2026"
    • [LỊCH SỬ] budget = "150 triệu" (Đã bị thay thế)
  ```

#### Bước 4: Cài cắm Nguyên tắc ưu tiên dữ liệu (Conflict Rules)
Context Composer gắn kèm một bộ luật xử lý mâu thuẫn để chỉ dẫn cho AI:
1. **Sự thật luôn thắng tài liệu**: Thông tin cập nhật trong MongoDB luôn có độ ưu tiên cao hơn tài liệu văn bản tĩnh (bởi vì tài liệu PDF có thể viết từ nhiều tháng trước, còn tin nhắn chat trên Lark là thỏa thuận mới nhất hôm nay).
2. **Nêu rõ biến động nếu có**: Nếu tài liệu cũ ghi giá trị A nhưng tin nhắn mới cập nhật giá trị B, bắt buộc phải trả lời: *"Theo tài liệu cũ là A, tuy nhiên theo cập nhật thảo luận mới nhất đã được điều chỉnh thành B"*.

---

### Giai đoạn 3: Sinh Câu Trả Lời Cuối Cùng

1. **Đầu ra của Context Composer**: Tạo thành một khối văn bản ngữ cảnh hoàn chỉnh gồm 3 phần:
   - **Phần 1**: Tài liệu văn bản (WeKnora).
   - **Phần 2**: Thông tin thực tế cập nhật (MongoDB).
   - **Phần 3**: Nguyên tắc ưu tiên dữ liệu.
2. **[ĐIỂM CÓ LLM / GEMINI] Grounded QA**:
   - Khối văn bản này được gửi vào mô hình Gemini cùng với câu hỏi của người dùng.
   - Mô hình đọc hiểu và tạo ra câu trả lời chính xác, trung thực, không bịa đặt, sau đó gửi trả lời về cho người dùng qua tin nhắn Lark.
