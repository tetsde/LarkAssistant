# 📘 BÓC TÁCH KỸ THUẬT: `utils/context_composer.py`
> **HiLark Server** — Bộ hợp nhất ngữ cảnh phân cấp đa nguồn (Hierarchical Context Composer).  
> **Vị trí file:** [`server/utils/context_composer.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/context_composer.py) (687 dòng, 30.5 KB).

---

## 🧭 1. VAI TRÒ VÀ NHIỆM VỤ

Sau khi tài liệu tĩnh (Chunks từ WeKnora) và sự thật động (Claims từ MongoDB) đã được làm sạch an ninh bởi `rule_engine.py`, chúng vẫn là các mảng dữ liệu JSON rời rạc. Nếu đưa trực tiếp các mảnh vụn này cho Trí tuệ nhân tạo (Gemini AI), mô hình sẽ dễ bị:
* Hoang mang vì thông tin giữa tài liệu cũ và tin nhắn mới bị mâu thuẫn nhau.
* Không phân biệt được đâu là quyết định chính thức của Sếp, đâu chỉ là đề xuất cá nhân của nhân viên.
* Không nắm được bối cảnh tổng quan của nhóm chat đang hỏi về dự án nào.

Module `context_composer.py` đóng vai trò là **"Tổng biên tập dữ liệu"**:
1. Chuẩn hóa mọi định dạng dữ liệu đầu vào đa dạng.
2. Sắp xếp và nhóm các sự thật con (Facts) theo từng thực thể cha (Entities).
3. Đóng gói thành một khối ngữ cảnh phân cấp 3 phần chặt chẽ.
4. Áp dụng **Bộ quy tắc giải quyết xung đột (Conflict Resolution Rules)** giúp AI luôn ưu tiên sự thật mới nhất.

---

## 🏛️ 2. CẤU TRÚC BỐI CẢNH PHÂN CẤP 3 PHẦN

Toàn bộ ngữ cảnh chuyển giao sang mô hình AI được tổ chức thành 3 phần rõ ràng, mạch lạc:

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ === PHẦN 0: BỐI CẢNH DỰ ÁN & HỒ SƠ TÀI LIỆU CỦA NHÓM ===                 │
│ • Nhóm chat: Dự án Cổng Thanh Toán HiLark                                │
│ • Dự án    : Fintech Payment Gateway                                     │
│ • Tài liệu : Ke_hoach_trien_khai.pdf, Kien_truc_he_thong.docx             │
├──────────────────────────────────────────────────────────────────────────┤
│ === PHẦN 1: TÀI LIỆU DỰ ÁN & VĂN BẢN HỆ THỐNG (WEKNORA) ===              │
│ [Tài liệu: Ke_hoach_trien_khai.pdf]                                      │
│ Mục tiêu dự án là xây dựng hệ thống thanh toán. Trưởng nhóm ban đầu: Nam │
├──────────────────────────────────────────────────────────────────────────┤
│ === PHẦN 2: THỰC TẾ CẬP NHẬT & MỆNH ĐỀ ĐỘNG (MONGODB CLAIMS) ===         │
│ ⭐ [QUYẾT ĐỊNH CHÍNH THỨC TỪ CEO / BAN ĐIỀU HÀNH] [CURRENT]:             │
│ • Dự án Fintech Payment Gateway:                                         │
│   - Người phụ trách: Nguyên (Ghi chú: Thay thế cho Nam)                  │
│   - Hạn chót mới   : 30/10/2026                                          │
│                                                                          │
│ 💡 [ĐỀ XUẤT NHÂN SỰ / CHỜ DUYỆT (PROPOSED)]:                             │
│ • Tính năng Quét QR: Minh xin làm người kiểm thử (Chờ duyệt)             │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## ⚖️ 3. BỘ QUY TẮC GIẢI QUYẾT XUNG ĐỘT (CONFLICT RESOLUTION RULES)

Được cài đặt mặc định trong `DEFAULT_CONFLICT_RULES` ([`L99-103`](file:///Users/hoainam/Desktop/HiLark/server/utils/context_composer.py#L99-L103)) và nhúng thẳng vào chỉ dẫn của AI:

### 1. Thẩm quyền tối cao từ CEO / Ban điều hành (Fact Override)
* Các mệnh đề có tiền tố ⭐ `[QUYẾT ĐỊNH CHÍNH THỨC TỪ CEO / BAN ĐIỀU HÀNH]` hoặc `[CURRENT]` do Sếp chốt là chân lý thực tế cao nhất.
* **Quy tắc ghi đè:** Có hiệu lực tuyệt đối và cao hơn mọi tài liệu văn bản tĩnh ở Phần 1!

### 2. Phân biệt rạch ròi giữa Đề xuất và Quyết định
* Các mệnh đề có tiền tố 💡 `[ĐỀ XUẤT NHÂN SỰ / CHỜ DUYỆT (PROPOSED)]` chỉ là ý kiến, nguyện vọng của nhân viên, **tuyệt đối chưa phải quyết định của công ty**.
* Khi trả lời, AI bắt buộc phải nói rõ: *"Đây mới là đề xuất của bạn [X], hiện đang chờ Sếp xem xét duyệt"*.

### 3. Không gán ghép nhầm lẫn nhân sự
* Mỗi nhân sự có lộ trình và nhiệm vụ riêng biệt.
* Người hỏi hỏi về ai thì chỉ trả lời đúng người đó; cấm lấy nhiệm vụ hay kỹ năng của nhân sự khác gán ghép cho người hỏi.

### 4. Nêu rõ biến động lịch sử (Lineage Transparency)
* Nếu phát hiện mâu thuẫn giữa Tài liệu và Mệnh đề (tài liệu ghi giá trị A nhưng mệnh đề thực tế đã cập nhật sang giá trị B), AI phải nêu rõ quá trình biến động:
  > *"Theo tài liệu thiết kế ban đầu là Nam phụ trách, tuy nhiên theo cập nhật trao đổi mới nhất đã được chuyển giao cho Nguyên đảm nhiệm."*

---

## 🔧 4. CÁC THUẬT TOÁN XỬ LÝ DỮ LIỆU CỐT LÕI

### A. Chuẩn hóa & Khử trùng lặp Chunks (`normalize_retriever_data`)
* **Vị trí mã nguồn:** [`server/utils/context_composer.py:L121-212`](file:///Users/hoainam/Desktop/HiLark/server/utils/context_composer.py#L121-L212)
* **Khả năng tương thích:** Hỗ trợ mọi cấu trúc trả về từ WeKnora (mảng chunks, dict `records`, `citations`, hoặc chuỗi thô).
* **Khử trùng lặp:** Tự động lọc bỏ các đoạn trích có nội dung văn bản giống hệt nhau (`seen_texts`), chỉ giữ lại các đoạn độc bản.
* **Giới hạn số lượng:** Cắt tối đa theo `max_chunks` (mặc định 8 đoạn) để tránh làm tràn ngữ cảnh của AI.

---

### B. Chuẩn hóa & Nhóm Sự thật theo Thực thể (`normalize_claims_data`)
* **Vị trí mã nguồn:** [`server/utils/context_composer.py:L214-320`](file:///Users/hoainam/Desktop/HiLark/server/utils/context_composer.py#L214-L320)
* **Gom nhóm theo thực thể cha:** Thay vì liệt kê các sự thật một cách lộn xộn, ContextComposer tự động nhóm các facts con theo từng thực thể cha tương ứng:
  ```text
  • Dự án Sàn Thanh Toán:
    - Hạn chót: 30/10/2026
    - Trạng thái: Đang triển khai
  • Tính năng Quét mã QR:
    - Người phụ trách: Trí
  ```
* **Lần vết thay thế (`replaces`):** Tự động phát hiện và đính kèm ghi chú *(Ghi chú: Thay thế cho thông tin cũ ID...)* để AI nắm được lịch sử thay đổi.

---

## 📊 5. CẤU TRÚC KẾT QUẢ ĐẦU RA

Phương thức chính `compose()` trả về một dictionary toàn diện:

```python
result = composer.compose(
    retriever_data=clean_chunks,
    claims_data=clean_claims,
    query=clean_query,
    scope_context=scope_ctx_data,
)
```

### Các trường dữ liệu trả về:
1. `context_text`: Toàn bộ chuỗi văn bản hoàn chỉnh đã được định dạng chuẩn mực Markdown, sẵn sàng gắn vào system prompt của Gemini AI.
2. `chunks_used`: Số lượng đoạn trích văn bản thực tế được đưa vào bối cảnh.
3. `claims_used`: Số lượng sự thật thực tế được đưa vào bối cảnh.
4. `citations`: Danh sách metadata trích dẫn nguồn gồm: `chunk_id`, `document_name`, `score`.
5. `has_context`: Cờ boolean (`True/False`) báo hiệu bối cảnh có dữ liệu hay rỗng.

---

## 📋 6. BẢNG TRA CỨU HÀM VÀ THUỘC TÍNH

| Tên phương thức / Thuộc tính | Kiểu dữ liệu | Chức năng chính |
| :--- | :---: | :--- |
| `compose()` | Phương thức chính | Hợp nhất toàn diện Chunks và Claims thành prompt context hoàn chỉnh. |
| `normalize_retriever_data()` | Phương thức chuẩn hóa | Dọn dẹp và khử trùng lặp các đoạn trích từ WeKnora. |
| `normalize_claims_data()` | Phương thức chuẩn hóa | Chuẩn hóa danh sách sự thật và liên kết với thực thể cha. |
| `format_claims_hierarchical()`| Phương thức định dạng | Định dạng danh sách facts thành dạng cây thực thể dễ đọc. |
| `max_chunks` | Tham số (`int = 8`) | Số lượng đoạn trích văn bản tối đa đưa vào prompt. |
| `max_claims` | Tham số (`int = 25`)| Số lượng mệnh đề sự thật tối đa đưa vào prompt. |
| `include_superseded` | Tham số (`bool = True`)| Có đưa thông tin lịch sử đã bị thay thế vào bối cảnh hay không. |
