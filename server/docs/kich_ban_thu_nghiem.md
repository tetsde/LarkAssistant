# Kịch Bản Thử Nghiệm Thực Tế Hệ Thống HiLark

Kịch bản được thiết kế để bạn copy/paste trực tiếp vào nhóm chat Lark để kiểm tra 2 luồng cốt lõi:
1. **Luồng 1: Xây dựng Daily Digest (Tổng hợp tin nhắn trao đổi trong ngày)**.
2. **Luồng 2: Bóc tách & Thay đổi Facts (Cập nhật dữ liệu động, lưu vết lịch sử, chống loop chủ nhân)**.

---

## 📋 PHẦN 1: CÁC TIN NHẮN ĐỂ XÂY DỰNG DAILY DIGEST

> **Mục đích**: Giả lập cuộc trao đổi công việc thường nhật trong nhóm. Toàn bộ các tin nhắn này sẽ tự động lưu vào bảng `conversation_staging`. Đến giờ hẹn (hoặc khi chạy tổng hợp), AI sẽ gom lại thành một báo cáo ngày chi tiết (Tiến độ, Vấn đề, Việc cần làm) gửi cho Chủ nhân duyệt vào WeKnora.

### Chuỗi tin nhắn gửi vào Nhóm (Chat lần lượt theo thứ tự):

* **Tin nhắn 1 (Thành viên báo cáo tiến độ):**
  > *"Sáng nay team dev đã hoàn thành xong phần kết nối API thanh toán QR code cho dự án HiLark rồi nhé mọi người. Đã test thông luồng sandbox."*

* **Tin nhắn 2 (Thành viên nêu khó khăn / blocker):**
  > *"Tuy nhiên bên cổng thanh toán đối tác đang bảo trì môi trường staging đến 15h chiều nay, nên phần test webhook thanh toán tự động tạm thời chưa kiểm tra được."*

* **Tin nhắn 3 (Chủ nhân chỉ đạo - Test cơ chế chỉ ghi nhớ/staging, không bot reply):**
  > *"OK bạn. Trong lúc chờ đối tác mở lại staging thì team tranh thủ viết trước tài liệu hướng dẫn tích hợp và chuẩn bị sẵn bộ test case cho phần webhook nhé."*

* **Tin nhắn 4 (Thành viên xác nhận kế hoạch tiếp theo):**
  > *"Dạ rõ anh, em với Nguyên sẽ hoàn thành tài liệu API spec trước 16h chiều nay để kịp nghiệm thu nội bộ."*

---

### 🎯 Cách kiểm tra kết quả Luồng 1:
1. Sau khi chat xong 4 câu trên, mở tin nhắn riêng (DM 1-1) với Bot Lark.
2. Gõ lệnh: **`xem digest`** hoặc **`chi tiết digest`**.
3. **Kết quả mong đợi**: Bot gửi bản báo cáo tổng hợp Markdown:
   * **Chủ đề thảo luận**: Tích hợp API thanh toán QR code dự án HiLark.
   * **Tiến độ đạt được**: Hoàn thành kết nối API sandbox.
   * **Khó khăn / Rủi ro**: Đối tác bảo trì staging đến 15h làm chậm test webhook.
   * **Kế hoạch tiếp theo**: Viết tài liệu tích hợp và test case trước 16h.
4. Gõ: **`Duyệt digest`** ➔ Bot xác nhận nạp thành công vào WeKnora Knowledge Base.

---

## ⚡ PHẦN 2: CÁC TIN NHẮN THAY ĐỔI FACTS & KIỂM TRA PHẢN HỒI

> **Mục đích**: 
> - Thử nghiệm bóc tách Thực thể (Nhánh 1) & Sự thật (Nhánh 2).
> - Thử nghiệm tính năng **Chủ nhân phát ngôn**: Tự động lưu tri thức mới vào MongoDB nhưng **tuyệt đối không trả lời vào nhóm (chống loop)**.
> - Thử nghiệm cơ chế **Phế truất thông tin cũ (`superseded`)**: Ghi đè thông tin mới lên thông tin cũ.
> - Thử nghiệm **Hỏi đáp Grounded QA**: Thành viên khác hỏi, bot ưu tiên dữ liệu mới và giải thích quá trình biến động.

---

### Mốc 1: Khởi tạo thông tin ban đầu (Fact ban đầu)
* **Người gửi**: Thành viên (hoặc Chủ nhân)
* **Nội dung chat vào nhóm:**
  > *"Dự án Atlas chốt khởi động với ngân sách ban đầu là 150 triệu, hạn chót ngày 15/10/2026 nhé mọi người."*
* **Kết quả hệ thống**:
  - Nhánh 1 tạo Entity: `Atlas` (`id: "ent_atlas_..."`).
  - Nhánh 2 tạo 2 Facts:
    + `budget = "150 triệu"` (trạng thái: `current`).
    + `deadline = "15/10/2026"` (trạng thái: `current`).

---

### Mốc 2: Chủ nhân thay đổi thông tin (Test Tấm khiên chống Loop)
* **Người gửi**: **CHÍNH CHỦ NHÂN** (Tài khoản Hoài Nam)
* **Nội dung chat vào nhóm:**
  > *"Dự án bữa anh nói 150tr bây giờ khách hàng chốt tăng ngân sách lên 300 triệu nhé, deadline cũng dời sang 30/10/2026."*
* **Kết quả hệ thống**:
  - **Chống Loop hoạt động**: JEV phân loại `MEMORY_ONLY`, bot **IM LẶNG 100% trong nhóm, không tự trả lời chủ nhân**.
  - **Coreference Resolution**: Nhìn thấy "150tr" ➔ Khớp đúng vào dự án `Atlas` đã có.
  - **Thay đổi Fact cũ**:
    + Fact ngân sách 150tr và deadline 15/10 ➔ chuyển sang trạng thái **`superseded`**.
    + Tạo 2 Fact mới: `budget = "300 triệu"` và `deadline = "30/10/2026"` ở trạng thái **`current`**.

---

### Mốc 3: Chủ nhân điều chỉnh nhân sự phụ trách
* **Người gửi**: **CHÍNH CHỦ NHÂN** (Tài khoản Hoài Nam)
* **Nội dung chat vào nhóm:**
  > *"Giao bạn Nguyên lead dự án HiLark thay cho Tuấn PM nhé."*
* **Kết quả hệ thống**:
  - Bot tiếp tục im lặng, không reply.
  - Fact `assignee` / `owner` của `HiLark` cập nhật thành: `Nguyên`. Người cũ (Tuấn PM) chuyển thành lịch sử.

---

### Mốc 4: Thành viên khác hỏi để Bot giải đáp (Test Context Composer & Grounded QA)
* **Người gửi**: **TÀI KHOẢN KHÁC** (Thành viên trong nhóm hỏi)
* **Nội dung chat vào nhóm:**
  > *"Mọi người cho em hỏi dự án Atlas ngân sách hiện tại là bao nhiêu, và ai đang phụ trách dự án HiLark vậy ạ?"*
* **Kết quả mong đợi từ Bot**:
  - Bot nhận diện câu hỏi ➔ Phân loại `REPLY_ONLY` ➔ Chạy `ContextComposer` ➔ Sinh câu trả lời nhân danh Hoài Nam:
  > *"Chào bạn,*  
  > *Về câu hỏi của bạn:*  
  > *1. **Dự án Atlas**: Ngân sách ban đầu là 150 triệu, tuy nhiên theo cập nhật mới nhất đã được tăng lên **300 triệu** (hạn chót dời đến 30/10/2026).*  
  > *2. **Dự án HiLark**: Hiện tại đã được giao cho **bạn Nguyên** làm Project Lead thay cho Tuấn PM.*  
  > *Chúc bạn làm việc hiệu quả nhé!"*

---

## 📊 Bảng Theo Dõi Trạng Thái Dữ Liệu Sau Khi Chạy Kịch Bản (Luồng 2)

| Mốc | Hành động | Trạng thái trong MongoDB | Trạng thái Bot trong Nhóm |
| :--- | :--- | :--- | :--- |
| **Mốc 1** | Khởi tạo Atlas | `budget = 150tr` [CURRENT] | Im lặng / Không reply |
| **Mốc 2** | Chủ nhân tăng lên 300tr | `budget = 150tr` [SUPERSEDED]<br>`budget = 300tr` [CURRENT] | **Im lặng 100% (Chống Loop)** |
| **Mốc 3** | Chủ nhân đổi Lead HiLark | `owner = Tuấn PM` [SUPERSEDED]<br>`owner = Nguyên` [CURRENT] | **Im lặng 100% (Chống Loop)** |
| **Mốc 4** | Thành viên hỏi ngân sách & lead | Đọc facts [CURRENT] kết hợp lịch sử | **Phản hồi chính xác: 300tr & Nguyên lead** |

---

## 🛡️ PHẦN 3: CÁC TIN NHẮN THỬ NGHIỆM SOẠN NHÁP CHỜ DUYỆT (DRAFT PENDING APPROVAL)

> **Mục đích**: 
> Thử nghiệm cơ chế an toàn kiểm duyệt (Human-in-the-Loop). Khi thành viên hỏi câu hỏi **nhạy cảm / rủi ro** (lương bổng cá nhân, thỏa thuận bảo mật, tranh chấp...) hoặc thông tin chưa có trong Knowledge Base:
> 1. Bot **TUYỆT ĐỐI KHÔNG tự tiện phát ngôn vào nhóm** (tránh rủi ro phát ngôn bậy).
> 2. Bot tự soạn một bản nháp gợi ý rồi **gửi riêng 1-1 vào DM của Chủ nhân (Hoài Nam)**.
> 3. Chủ nhân toàn quyền quyết định qua chat DM: **`[Gửi]`**, **`[Sửa: <nội dung>]`**, hoặc **`[Bỏ]`**.

---

### Kịch bản 3.1: Thử nghiệm lệnh DUYỆT & GỬI NHÁP (`Gửi` / `OK`)

* **Bước 1 (Thành viên hỏi câu hỏi nhạy cảm vào nhóm):**
  > *"Anh Nam ơi cho em hỏi mức lương và thưởng KPI quý này của team dev HiLark được tính thế nào vậy ạ?"*
* **Bước 2 (Hệ thống xử lý an toàn):**
  - JEV phân loại: `DRAFT_PENDING_APPROVAL`.
  - Bot **im lặng hoàn toàn trong nhóm**, không gửi tin nhắn nào vào nhóm chat.
  - Bot gửi tin nhắn riêng vào DM 1-1 của Hoài Nam:
    ```text
    📝 [SOẠN NHÁP CHỜ DUYỆT - CÂU HỎI CÓ RỦI RO]
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    👤 Người hỏi : Thành viên
    💬 Câu hỏi   : "Anh Nam ơi cho em hỏi mức lương và thưởng KPI quý này..."

    💡 Bản nháp AI soạn sẵn:
    "Chào bạn, về chính sách lương thưởng KPI của dự án, các số liệu chi tiết thuộc quy chế bảo mật nhân sự nội bộ. Bạn vui lòng liên hệ trực tiếp Lead hoặc HR để được giải đáp cụ thể nhé."

    👉 Hành động chờ duyệt: Nhắn lại [Gửi] / [Sửa: <nội dung>] / [Bỏ]
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ```
* **Bước 3 (Chủ nhân duyệt trong DM 1-1):**
  - Trong tin nhắn riêng với Bot, bạn gõ: **`Gửi`** (hoặc `OK`, `Duyệt`).
* **Bước 4 (Kết quả):**
  - Bot xác nhận trong DM: *"✔ ĐÃ DUYỆT VÀ GỬI THÀNH CÔNG VÀO NHÓM!"*
  - Câu trả lời nháp trên lập tức được phát ngôn vào nhóm chat nhân danh Hoài Nam!

---

### Kịch bản 3.2: Thử nghiệm lệnh CHỈNH SỬA NỘI DUNG TRƯỚC KHI PHÁT NGÔN (`Sửa: ...`)

* **Bước 1 (Thành viên hỏi câu hỏi nhạy cảm khác vào nhóm):**
  > *"Dự án HiLark có tỷ lệ chia sẻ doanh thu cụ thể với bên đối tác là bao nhiêu phần trăm thế anh?"*
* **Bước 2 (Bot gửi bản nháp vào DM của Hoài Nam):**
  - Bot gửi thông báo soạn nháp vào tin nhắn riêng DM 1-1 của bạn.
* **Bước 3 (Chủ nhân sửa lại theo ý mình trong DM 1-1):**
  - Bạn gõ vào DM:
    > **`Sửa: Chào em, điều khoản chia sẻ doanh thu thuộc thỏa thuận bảo mật NDA với đối tác, anh sẽ trao đổi riêng với em trong buổi họp review tuần tới nhé.`**
* **Bước 4 (Kết quả):**
  - Bot gửi đúng câu chữ mà bạn vừa chỉnh sửa vào nhóm chat. Không dùng câu nháp của AI nữa!

---

### Kịch bản 3.3: Thử nghiệm lệnh HỦY BỎ BẢN NHÁP (`Bỏ` / `Hủy`)

* **Bước 1 (Thành viên hỏi câu hỏi rủi ro hoặc spam vào nhóm):**
  > *"Nghe nói dự án mình đang bị đối tác phạt hợp đồng vì trễ tiến độ đúng không anh Nam?"*
* **Bước 2 (Bot gửi thông báo nháp vào DM của Hoài Nam).**
* **Bước 3 (Chủ nhân quyết định không trả lời):**
  - Bạn gõ vào DM: **`Bỏ`** (hoặc `Hủy`).
* **Bước 4 (Kết quả):**
  - Bot xác nhận trong DM: *"🗑 ĐÃ HỦY BỎ BẢN NHÁP THÀNH CÔNG! Không có tin nhắn nào được gửi vào nhóm."*
  - Trong nhóm chat, hoàn toàn không có bất kỳ tin nhắn phản hồi nào. An toàn tuyệt đối!

