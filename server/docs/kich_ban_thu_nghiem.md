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

---

## 🔒 PHẦN 4: CÔ LẬP TRI THỨC VÀ CLAIMS GIỮA CÁC DỰ ÁN (CLAIMS SCOPE ISOLATION)

> **Mục đích**: 
> Kiểm chứng tri thức (ngân sách, hạn chót, quyết định nội bộ) trích xuất từ Nhóm Dự án Alpha **tuyệt đối không bị rò rỉ** sang Nhóm Dự án Beta khi thành viên ở nhóm khác đặt câu hỏi.

### Kịch bản 4.1: Kiểm tra cô lập dữ liệu facts giữa 2 nhóm

* **Bước 1 (Chủ nhân công bố ngân sách trong Nhóm Dự án Alpha - `oc_alpha`):**
  > *"Ngân sách chạy quảng cáo tháng này cho dự án Alpha chốt là 80 triệu nhé cả team."*
  - **Hệ thống xử lý:** Bot bóc tách Fact: `budget = 80 triệu`, gán metadata: `chat_id = "oc_alpha"`, `project_tag = "Alpha"`, `scope_type = "chat"`.
  - Bot **im lặng 100% trong nhóm** (Owner Shield).

* **Bước 2 (Chủ nhân công bố ngân sách trong Nhóm Dự án Beta - `oc_beta`):**
  > *"Ngân sách chạy quảng cáo tháng này cho dự án Beta chốt là 200 triệu."*
  - **Hệ thống xử lý:** Bot bóc tách Fact: `budget = 200 triệu`, gán metadata: `chat_id = "oc_beta"`, `project_tag = "Beta"`, `scope_type = "chat"`.
  - Bot **im lặng 100% trong nhóm** (Owner Shield).

* **Bước 3 (Thành viên hỏi ngân sách trong Nhóm Alpha):**
  > *"Anh Nam ơi ngân sách quảng cáo tháng này của nhóm mình là bao nhiêu ạ?"*
  - **Kết quả mong đợi:** Bot chỉ đọc facts có `chat_id = "oc_alpha"` hoặc `project_tag = "Alpha"`.
  - Bot trả lời: *"Ngân sách chạy quảng cáo tháng này của dự án Alpha đã được chốt là 80 triệu."* (TUYỆT ĐỐI không nhắc tới con số 200 triệu của nhóm Beta).

* **Bước 4 (Thành viên hỏi ngân sách trong Nhóm Beta):**
  > *"Anh Nam ơi cho em hỏi ngân sách quảng cáo của nhóm mình chốt bao nhiêu vậy ạ?"*
  - **Kết quả mong đợi:** Bot trả lời: *"Ngân sách chạy quảng cáo của dự án Beta là 200 triệu."* (TUYỆT ĐỐI không nhắc tới 80 triệu của nhóm Alpha).

---

## 📊 PHẦN 5: MASTER DAILY DIGEST (BÁO CÁO ĐIỀU HÀNH TỔNG HỢP TOÀN CÔNG TY)

> **Mục đích**: 
> Gom toàn bộ hoạt động trao đổi, quyết định, cam kết và điểm nghẽn từ **tất cả các nhóm chat trong ngày** thành **1 báo cáo điều hành duy nhất** gửi vào DM riêng của Chủ nhân.
> Chủ nhân duyệt 1 lệnh (`Duyệt digest`), hệ thống tự động bóc tách và nạp tri thức của từng nhóm vào đúng Knowledge Base WeKnora tương ứng.

### Kịch bản 5.1: Nhận và xem Báo cáo Master Daily Digest cuối ngày

* **Bước 1 (Hoạt động trong ngày):**
  - Nhóm Alpha trao đổi về chốt backend FastAPI và gặp điểm nghẽn (Blocker) thiếu API key ngân hàng.
  - Nhóm Beta trao đổi về nghiệm thu Sprint 2 mobile app.
* **Bước 2 (Đến 23:00 hoặc kích hoạt thủ công qua API):**
  - Hệ thống tự động tổng hợp tất cả nhóm và gửi **DUY NHẤT 1 tin nhắn DM** tới Chủ nhân:
    ```text
    📊 BÁO CÁO TỔNG HỢP TOÀN BỘ CÁC NHÓM (DAILY MASTER DIGEST)
    📅 Ngày: 2026-10-16 | 👥 Số nhóm hoạt động: 2 | 💬 Tổng tin nhắn: 40
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    🏢 I. TỔNG QUAN ĐIỀU HÀNH (EXECUTIVE OVERVIEW)
    Dự án Alpha đã thống nhất kiến trúc backend nhưng đang bị nghẽn do chờ cấp API sandbox từ đối tác ngân hàng. Dự án Beta đã hoàn thành nghiệm thu Sprint 2 đúng hạn.

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    📂 II. CHI TIẾT TỪNG NHÓM DỰ ÁN

    ### 📌 Nhóm 1: Nhóm Dự Án Alpha
    💬 Số tin nhắn: 15 | 🎯 Dự án: Alpha
    📝 Tóm tắt: Nhóm Alpha đã chốt kiến trúc API và kế hoạch release.

      🔹 Quyết định đã thống nhất:
        • Chuyển sang FastAPI: Đồng ý chuyển toàn bộ backend sang FastAPI (Chốt bởi Nguyễn Văn A)
      ⏰ Cam kết & Hạn chót:
        • Nguyễn Văn A: Hoàn thiện router Payment [Hạn: 17:00 ngày 20/10/2026]
      🔄 Trạng thái & Tiến độ:
        • 🔴 [BLOCKER] Cổng thanh toán: Đang tắc nghẽn (Thiếu API key sandbox) - Lý do: Cần PM liên hệ đối tác cấp key

    ### 📌 Nhóm 2: Nhóm Dự Án Beta
    💬 Số tin nhắn: 25 | 🎯 Dự án: Beta
    📝 Tóm tắt: Nhóm Beta hoàn thành kiểm thử giao diện người dùng.

      🔹 Quyết định: (Không có)
      ⏰ Cam kết & Hạn chót:
        • Trần Thị B: Fix lỗi hiển thị dark mode trên iOS [Hạn: Thứ 6 tuần này]
      🔄 Trạng thái & Tiến độ:
        • 🟢 [MILESTONE] UI/UX Sprint 2: Hoàn thành (Đã nghiệm thu thiết kế mobile app)

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    💡 HƯỚNG DẪN THAO TÁC:
    👉 Nhắn tin "duyệt digest" để phê duyệt và đồng bộ tri thức của từng nhóm vào đúng Knowledge Base WeKnora tương ứng.
    👉 Nhắn tin "hủy digest" nếu không muốn lưu trữ bản tổng hợp này.
    ```

### Kịch bản 5.2: Thao tác Duyệt hoặc Hủy Master Daily Digest trong DM

* **Lệnh DUYỆT (`duyệt digest` / `ok digest`):**
  - Trong DM 1-1 với Bot, Chủ nhân gõ: **`duyệt digest`**
  - **Kết quả:**
    - Bot tự động đẩy phần Digest của Nhóm Alpha vào KB của Nhóm Alpha trên WeKnora.
    - Bot tự động đẩy phần Digest của Nhóm Beta vào KB của Nhóm Beta trên WeKnora.
    - Bot phản hồi DM cho Chủ nhân:
      ```text
      ✔ ĐÃ DUYỆT VÀ ĐỒNG BỘ TOÀN BỘ MASTER DAILY DIGEST THÀNH CÔNG!
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      📅 Ngày ghi nhận : 2026-10-16
      🆔 Mã Master     : master_digest_20261016
      👥 Số nhóm duyệt : 2 nhóm (40 tin nhắn)
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      Tri thức của từng nhóm đã được phân phối nạp chính xác vào đúng Knowledge Base WeKnora tương ứng!
      ```

* **Lệnh XEM LẠI (`xem digest`):**
  - Gõ **`xem digest`** để đọc lại toàn bộ nội dung bản Master Daily Digest đang chờ duyệt.

* **Lệnh HỦY BỎ (`hủy digest` / `bỏ digest`):**
  - Gõ **`hủy digest`** -> Bản tổng hợp được đánh dấu `rejected`, không đẩy bất kỳ dữ liệu nào vào WeKnora.

---

## 🔒 PHẦN 6: PHÂN CẤP BẢO MẬT TỪ LARK BASE (MỨC ĐỘ BẢO MẬT)

> **Mục đích**: 
> Kiểm soát mức độ phát ngôn và rủi ro rò rỉ thông tin dựa trên cột **"Mức độ bảo mật"** cấu hình trên Lark Base (`Nội bộ`, `Tuyệt mật`).

### Kịch bản 6.1: Nhóm Tuyệt Mật (Khóa Auto-Reply -> 100% Qua Sếp Duyệt)

* **Thiết lập trên Lark Base**:
  - Nhóm `[Project 3] LogiChain`: Cột `Mức độ bảo mật` chọn **`Tuyệt mật`**.
* **Thành viên hỏi trong nhóm**:
  > *"Kế hoạch thử nghiệm dự án LogiChain tiến hành thế nào anh?"*
* **Hành vi của hệ thống**:
  1. JEV phân loại câu hỏi là `REPLY_ONLY` (do có tài liệu và là câu hỏi dự án).
  2. Hệ thống phát hiện nhóm ở mức **`Tuyệt mật` (Confidential)** $\rightarrow$ **Kích hoạt Zero Auto-reply**:
     - Bot **TUYỆT ĐỐI IM LẶNG trong nhóm chat**, không tự trả lời.
     - Tự động ép chuyển sang **`DRAFT_PENDING_APPROVAL`**.
  3. Bot gửi thông báo soạn nháp riêng vào **DM của Sếp**:
     ```text
     📝 [SOẠN NHÁP CHỜ DUYỆT - DỰ ÁN TUYỆT MẬT]
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
     👥 Nhóm chat : [Project 3] LogiChain
     🛡️ Bảo mật   : TUYỆT MẬT (Khóa auto-reply)
     👤 Người hỏi : Thành viên
     💬 Câu hỏi   : "Kế hoạch thử nghiệm dự án LogiChain tiến hành thế nào anh?"

     💡 Bản nháp AI soạn sẵn:
     "Dự án LogiChain hiện đang hoàn thiện giai đoạn MVP..."

     ⚠️ Lý do: Nhóm thuộc mức độ TUYỆT MẬT (Chính sách: 100% câu trả lời phải được Sếp duyệt trước khi gửi vào nhóm).
     👉 Hành động chờ duyệt: Nhắn lại [Gửi] / [Sửa: <nội dung>] / [Bỏ]
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
     ```
  4. Sếp xem xét trong DM:
     - Nhắn `Gửi` $\rightarrow$ Câu trả lời mới xuất hiện trong nhóm dưới danh nghĩa Sếp.
     - Nhắn `Sửa: ...` $\rightarrow$ Chỉnh sửa nội dung trước khi gửi.
     - Nhắn `Bỏ` $\rightarrow$ Hủy bỏ, không gửi gì vào nhóm.

---

## 📚 PHẦN 7: TỔNG HỢP TRI THỨC ĐA LUỒNG (CLAIMS + DAILY DIGEST CHO WEKNORA WIKI)

> **Mục đích**:
> Tích hợp MongoDB Claims (Mệnh đề / Sự thật / Đề xuất) vào quá trình tổng hợp ngày, phân tách 2 bản dữ liệu:
> 1. **Bản 1 (Lark DM)**: Gửi Sếp duyệt nhanh, **đính kèm các Đề xuất mới (Proposed Claims)** để Sếp không bị mù thông tin.
> 2. **Bản 2 (WeKnora Wiki)**: Cấu trúc Entity-Centric, chứa quan hệ Nhóm chat thuộc Dự án nào, đẩy sang `wiki_dataset_id`.

### Kịch bản 7.1: Duyệt Daily Digest Có Kèm Đề Xuất Của Nhân Sự
* **Hoạt động trong ngày**:
  - Thành viên Duy nhắn: *"Em đề xuất mình đổi cổng thanh toán sang VNPay Sandbox trước nhé."*
  - Hệ thống trích xuất và lưu Claim: `entity='Fintech'`, `property='payment_gateway'`, `value='VNPay Sandbox'`, `status='proposed'`.
* **Cuối ngày (Bản 1 gửi DM Sếp)**:
  - Bot gửi tin nhắn xin duyệt có mục riêng:
    ```text
    📋 [YÊU CẦU DUYỆT DAILY DIGEST]
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    🏢 Nhóm chat     : Fintech Core Team
    🎯 Dự án         : PayStream
    📅 Ngày ghi nhận : 2026-10-17
    ✉ Số tin nhắn   : 20 | 🧠 Số Claims: 1

    🔍 TỔNG QUAN HÔM NAY:
    Thảo luận tích hợp cổng thanh toán mới.

    💡 ĐỀ XUẤT MỚI TỪ THÀNH VIÊN (PROPOSED CLAIMS):
      - Duy đề xuất: payment_gateway = VNPay Sandbox

    👉 Quyết định nổi bật: ...
    👉 Cam kết deadline: ...
    ```
* **Khi Sếp duyệt (Bản 2 đẩy sang WeKnora Wiki)**:
  - Bot đẩy văn bản Markdown chuẩn Entity-Centric sang `wiki_dataset_id`:
    ```markdown
    # WIKI KNOWLEDGE BASE: [[DỰ ÁN PAYSTREAM]]
    **Nhóm trao đổi (Chat Group):** [[Fintech Core Team]] (ID: `oc_xxx`)
    **Dự án trực thuộc (Parent Project):** [[PayStream]]
    
    ## 2. THỰC THỂ & MỆNH ĐỀ CẬP NHẬT (ENTITIES & CLAIMS)
    ### 📌 Thực thể: [[Fintech]]
    - **Thuộc nhóm chat:** [[Fintech Core Team]] | **Dự án:** [[PayStream]]
      • `[PROPOSED]` **payment_gateway**: VNPay Sandbox
        - *Khẳng định bởi:* Duy (member)
    ```
