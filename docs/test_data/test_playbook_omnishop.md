# KỊCH BẢN KIỂM THỬ THỰC HÀNH: DỰ ÁN OMNISHOP
**Tài liệu tham chiếu:** [du_an_omnishop_sample.md](file:///Users/hoainam/Desktop/HiLark/docs/test_data/du_an_omnishop_sample.md)  
**Nhóm chat áp dụng:** `[Dự Án] OmniShop Core`  
**Nhãn cấm cấu hình (Forbidden Labels):** `Ngân sách`, `Lương`, `Hợp đồng`, `Mật mã`

---

## PHẦN 1: BẢNG TIN NHẮN MẪU & MONG ĐỢI XỬ LÝ CỦA AI

Dưới đây là 8 tin nhắn thực tế để bạn copy/paste vào Lark để kiểm tra phản ứng của từng tầng xử lý trong hệ thống:

### Tin nhắn 1: Hỏi đáp Tri thức Dự án Công khai (Q&A Bình thường)
- **Kênh gửi:** Nhóm chat `[Dự Án] OmniShop Core` (Gửi từ tài khoản Nhân viên).
- **Nội dung gõ:**
  `Cho mình hỏi dự án OmniShop này ai làm Quản lý dự án (PM) và giờ họp Daily hàng ngày là mấy giờ thế?`
- **Mong đợi hệ thống xử lý:**
  1. JEV System 1 phân loại: `NEEDS_ANSWER` (Thời gian: ~35-50ms).
  2. WeKnora truy xuất tri thức từ tài liệu dự án: Nhận diện Hoàng Minh Tuấn là PM, giờ họp 09:15 - 09:30 sáng qua Lark Meeting.
  3. Gemini LLM sinh bản nháp câu trả lời lịch sự, đầy đủ thông tin.
  4. Bot tạo bản ghi nháp `drafts` ở trạng thái `pending`.
  5. Bot gửi **Thẻ phê duyệt bản nháp câu trả lời** vào tin nhắn riêng (DM) của Chủ nhân.
  6. Trong nhóm chat: Bot tạm thời CHƯA phát ngôn gì cho đến khi Chủ nhân bấm duyệt.
- **Mong đợi đo lường (Cost Telemetry):**
  - JEV: 1 lượt gọi (~45ms, chi phí phẳng).
  - Gemini: 1 lượt gọi sinh văn bản (~800-1200ms, ~350-500 tokens).

---

### Tin nhắn 2: Sếp Điều khiển Bản nháp Bằng Tin Nhắn Lệnh Nhanh
- **Kênh gửi:** Tin nhắn riêng (DM) với Bot (Gửi từ tài khoản Chủ nhân).
- **Nội dung gõ:**
  `Sửa AI: Nhắc thêm anh em nhớ chuẩn bị trước nội dung trước khi vào họp 5 phút nhé.`
- **Mong đợi hệ thống xử lý:**
  1. [owner_command_handler.py](file:///Users/hoainam/Desktop/HiLark/server/services/lark/handlers/owner_command_handler.py) bắt trigger `Sửa AI:`.
  2. Gọi [rewrite_draft_with_llm](file:///Users/hoainam/Desktop/HiLark/server/services/ai/draft_rewriter.py) viết lại câu trả lời theo chỉ đạo.
  3. Gửi thẻ cập nhật mới cho Chủ nhân.
- **Thao tác tiếp theo:** Chủ nhân nhắn: `Gửi` (hoặc `ok`).
- **Mong đợi kết quả:** Bot gửi câu trả lời đã chỉnh sửa vào nhóm chat `[Dự Án] OmniShop Core` và xác nhận trong DM của Chủ nhân.

---

### Tin nhắn 3: Cập nhật Tiến độ & Điểm nghẽn (Blocker Detection cho Daily Digest)
- **Kênh gửi:** Nhóm chat `[Dự Án] OmniShop Core` (Gửi từ tài khoản Nhân viên hoặc Tech Lead).
- **Nội dung gõ:**
  `Báo cáo tiến độ: Hôm nay đã xong giao diện giỏ hàng. Tuy nhiên đang bị blocker nặng: Cổng thanh toán OnePay chưa cấp tài khoản Sandbox nên nhóm Backend đang bị nghẽn chưa test được luồng Visa/Mastercard.`
- **Mong đợi hệ thống xử lý:**
  1. JEV System 1 phân loại: Nhận diện từ khóa/ngữ nghĩa `blocker` và báo cáo tiến độ.
  2. Lưu tin nhắn vào collection `conversation_staging` với tag phân loại `blocker`.
  3. Ghi nhận `blocker_reason`: Chưa có tài khoản Sandbox OnePay.
  4. Bot im lặng (không sinh nháp trả lời vì đây là câu thông báo cập nhật, không phải câu hỏi cần bot giải đáp).
  5. Chuẩn bị đưa mục này vào khối **Điểm nghẽn cần lưu ý** trên Thẻ Master Daily Digest cuối ngày.

---

### Tin nhắn 4: Đề xuất Fact/Claim Mới Từ Hội Thoại
- **Kênh gửi:** Nhóm chat `[Dự Án] OmniShop Core`.
- **Nội dung gõ:**
  `Anh Tuấn PM vừa thống nhất chốt ngày Go-live toàn hệ thống là 20/01/2027 thay vì 15/01/2027 nhé mọi người.`
- **Mong đợi hệ thống xử lý:**
  1. LLM Extractor phân tích câu thoại và bóc tách được:
     - Thực thể (`entity_id`): `Hệ thống OmniShop` (hoặc `Dự án OmniShop`).
     - Thuộc tính (`property`): `go_live_date` (hoặc `ngày golive`).
     - Giá trị (`value`): `20/01/2027`.
     - Người phát ngôn (`speaker_name`): Thành viên gửi tin.
  2. Lưu vào collection `facts` với trạng thái `pending`.
  3. Đưa thông tin này vào bảng chờ duyệt cuối ngày của Sếp.

---

### Tin nhắn 5: Vi phạm Nhãn Cấm Trực Tiếp (Hỏi Ngân Sách)
- **Kênh gửi:** Nhóm chat `[Dự Án] OmniShop Core` (Gửi từ tài khoản Nhân viên).
- **Nội dung gõ:**
  `Dự án OmniShop này tổng ngân sách được duyệt là bao nhiêu tiền vậy bot?`
- **Mong đợi hệ thống xử lý:**
  1. Vọng gác Fast Keyword Gate bắt trúng từ khóa trong nhãn cấm: `ngân sách`.
  2. Vọng gác [check_forbidden_query](file:///Users/hoainam/Desktop/HiLark/server/services/ai/jev_classifier.py) xác nhận vi phạm: `is_forbidden = True` (nhãn vi phạm: `Ngân sách`).
  3. **Zero-Response (Im lặng tuyệt đối):** Bot KHÔNG trả lời vào nhóm chat, KHÔNG gọi WeKnora RAG, KHÔNG gọi Gemini LLM để sinh câu trả lời.
  4. Ghi log terminal: `🚫 [FORBIDDEN DROP] Câu hỏi vi phạm nhãn cấm 'Ngân sách'. Kích hoạt Zero-response.`

---

### Tin nhắn 6: Vi phạm Nhãn Cấm Bằng Tiếng Lóng / Ẩn Ý (Lương / Thu Nhập)
- **Kênh gửi:** Nhóm chat `[Dự Án] OmniShop Core` (Gửi từ tài khoản Nhân viên).
- **Nội dung gõ:**
  `Tháng này anh em làm dự án xong thì sếp ting ting mấy chục củ vào tài khoản thế?`
- **Mong đợi hệ thống xử lý:**
  1. Câu hỏi hoàn toàn KHÔNG có chữ "lương" hay "thu nhập" (tránh được bộ lọc regex thông thường).
  2. Vọng gác JEV Semantic NLU đọc hiểu ngữ nghĩa: Nhận diện "ting ting" + "mấy chục củ" chính là tiền lương/thưởng cá nhân.
  3. Đánh giá xác suất vi phạm `prob_forbidden >= 0.70` đối với nhãn cấm `Lương, Thu nhập`.
  4. Kích hoạt **Zero-Response (Im lặng tuyệt đối)**, bot im lặng hoàn toàn.

---

### Tin nhắn 7: Vi phạm Nhãn Cấm Bằng Cách Nói Giảm Nói Tránh (Hợp Đồng / NDA)
- **Kênh gửi:** Nhóm chat `[Dự Án] OmniShop Core` (Gửi từ tài khoản Nhân viên).
- **Nội dung gõ:**
  `Cho mình xin bản chụp văn bản thỏa thuận có chữ ký hai bên với tập đoàn Asia Retail xem có điều khoản phạt nào không.`
- **Mong đợi hệ thống xử lý:**
  1. Câu hỏi không dùng trực tiếp từ "hợp đồng".
  2. JEV Semantic NLU phân tích: "văn bản thỏa thuận có chữ ký hai bên", "điều khoản phạt" thuộc chủ đề `Hợp đồng & Điều khoản phạt (NDA)`.
  3. Kích hoạt **Zero-Response (Im lặng tuyệt đối)**.

---

### Tin nhắn 8: Tin Rác / Chào Hỏi Xã Giao (Kiểm tra JEV Fast-Lane tiết kiệm Token)
- **Kênh gửi:** Nhóm chat `[Dự Án] OmniShop Core`.
- **Nội dung gõ:**
  `Chào buổi chiều cả nhà, hôm nay ai đi uống trà sữa không?`
- **Mong đợi hệ thống xử lý:**
  1. JEV System 1 phân loại hành động: `IGNORE` trong vòng 30-40ms.
  2. Bot im lặng, không ghi staging, không gọi Gemini LLM.
  3. Ghi log terminal: `🔇 [IGNORE] Tin rác/chào hỏi không quan trọng. Không lưu, không trả lời.`
  4. Tiết kiệm 100% token LLM.

---

## PHẦN 2: MONG ĐỢI BÁO CÁO CUỐI NGÀY (MASTER DAILY DIGEST)

Sau khi gửi các tin nhắn trên, trong cửa sổ chat riêng với Bot (DM), Chủ nhân gõ lệnh:
`xem digest` (hoặc `xem báo cáo`)

### Giao diện Thẻ Master Daily Digest sẽ hiển thị như sau:

1. **Header Thẻ:**
   - Màu sắc: Xanh chàm (`indigo`).
   - Tiêu đề: **Báo cáo tổng hợp hoạt động trong ngày**.

2. **Khối Thống kê Cơ bản:**
   - **Ngày:** Hôm nay (Ví dụ: `27/10/2026`).
   - **Số nhóm:** 1 nhóm (`[Dự Án] OmniShop Core`).
   - **Tin nhắn:** 6 tin nhắn được ghi nhận.

3. **Khối Tổng quan Điều hành (Executive Summary):**
   - AI tóm lược: *"Nhóm OmniShop hoàn tất giao diện giỏ hàng trong Sprint 2. Đội ngũ ghi nhận điểm nghẽn kỹ thuật tại cổng thanh toán OnePay và đề xuất điều chỉnh ngày Go-live sang 20/01/2027."*

4. **Khối Điểm nghẽn Cần Lưu ý (Blockers):**
   - `[[Dự Án] OmniShop Core] Cổng thanh toán OnePay chưa bàn giao Sandbox -> Tạm hoãn kiểm thử luồng thẻ quốc tế.`

5. **Danh Sách Thông Tin Đề Xuất Mới Trong Ngày (Pending Claims - Định Dạng Danh Sách Phân Cấp):**
   • **[Hệ thống OmniShop]** Thời hạn hoàn thành: `20/01/2027` *(Người gửi: Tuấn)*
   • **[Cổng thanh toán OnePay]** Trạng thái tiến độ: `chưa được phê duyệt` *(Người gửi: Nam)*
   • **[Quy mô siêu thị]** Phạm vi công việc: `mở rộng từ 120 lên 130 cửa hàng`
   *(... và còn các thông tin đề xuất khác)*

6. **Khối Thống kê Chi Phí & Hiệu Năng AI Hôm Nay:**
   - **Tổng ngân sách:** `$0.0028 USD (~71 VND) | Tokens: 3,240`
   - **Gemini LLM:** 2 lượt (3,240 tokens) - $0.0024 - Phản hồi TB: 1150ms
   - **JEV System 1:** 6 lượt phân loại nhanh - Phản hồi TB: 42ms
   - **Tiết kiệm Fast-lane:** 66% tác vụ được lọc sơ bộ qua JEV giúp tối ưu token gọi LLM.

7. **Hàng Nút Thao Tác:**
   - Nút `Duyệt toàn bộ thông tin hôm nay`: Khi bấm, toàn bộ các giá trị trên chính thức có hiệu lực cho toàn hệ thống.
   - Nút `Xem chi tiết`: Mở thẻ chi tiết từng nhóm.
   - Nút `Nhờ AI tóm tắt ngắn`: Gửi tin nhắn DM tóm tắt 3 dòng.
   - Nút `Hủy báo cáo`: Từ chối báo cáo.

---

## PHẦN 3: KIỂM THỬ TRÍCH XUẤT CLAIMS TỪ TỆP ĐÍNH KÈM (ẢNH, DOCX, PDF)

Các tệp kiểm thử đã được chuẩn bị sẵn trong thư mục `docs/test_data/`:

### 1. Kiểm thử Tệp Hình Ảnh: `OmniShop_Sprint3_Infographic.jpg`
- **Đường dẫn tệp:** [OmniShop_Sprint3_Infographic.jpg](file:///Users/hoainam/Desktop/HiLark/docs/test_data/OmniShop_Sprint3_Infographic.jpg)
- **Thao tác:** Kéo thả tệp ảnh này gửi vào nhóm chat `[Dự Án] OmniShop Core`.
- **Mong đợi AI xử lý (Gemini Multimodal Vision - Silent Ingestion):**
  - Bot nhận diện ảnh đính kèm, kích hoạt OCR / Visual Extraction trong nền.
  - Bóc tách 3 claims:
    * `[Dự án OmniShop]` Thời hạn hoàn thành: `05/11/2026` (Tích hợp cổng OnePay).
    * `[Dự án OmniShop]` Thời hạn hoàn thành: `12/11/2026` (Bàn giao bản Beta 20 siêu thị).
    * `[Dự án OmniShop]` Người phụ trách chính: `Nguyễn Văn Nam`.
  - Bot âm thầm tiếp thu (Silent Ingestion): KHÔNG phát ngôn tin nhắn thông báo vào nhóm để giữ sự chuyên nghiệp, tự động đưa các claims vào danh mục chờ duyệt cuối ngày.

### 2. Kiểm thử Tệp Word: `OmniShop_Ke_Hoach_Sprint_3.docx`
- **Đường dẫn tệp:** [OmniShop_Ke_Hoach_Sprint_3.docx](file:///Users/hoainam/Desktop/HiLark/docs/test_data/OmniShop_Ke_Hoach_Sprint_3.docx)
- **Thao tác:** Đính kèm tệp `.docx` này gửi vào nhóm chat.
- **Mong đợi AI xử lý (gRPC AnyDoc DocReader - Silent Ingestion):**
  - Chuyển đổi `.docx` sang Markdown trong vòng dưới 1 giây.
  - Bóc tách 4 claims phân công và deadline từ bảng công việc.
  - Âm thầm nạp tri thức và đẩy các claims vào hàng chờ duyệt, không spam thông báo.

### 3. Kiểm thử Tệp PDF: `OmniShop_Bien_Ban_Nghiem_Thu.pdf`
- **Đường dẫn tệp:** [OmniShop_Bien_Ban_Nghiem_Thu.pdf](file:///Users/hoainam/Desktop/HiLark/docs/test_data/OmniShop_Bien_Ban_Nghiem_Thu.pdf)
- **Thao tác:** Đính kèm tệp `.pdf` này gửi vào nhóm chat.
- **Mong đợi AI xử lý (Silent Ingestion):**
  - Bóc tách: Giá trị thanh toán đợt 2 (`450.000.000 VNĐ`), Thời hạn thanh toán (`05/11/2026`), Thời gian bảo hành (`12 tháng`).
  - Âm thầm lưu tri thức vào hệ thống.

---

## PHẦN 4: BỘ TIN NHẮN MẪU MỞ RỘNG ĐỂ KIỂM THỬ CÁC LOẠI CLAIMS

Bạn có thể copy/paste các tin nhắn này vào nhóm chat để kiểm tra khả năng bắt trọn vẹn từng loại thuộc tính:

1. **Claim Thời hạn (Deadline):**
   `Team Backend vừa thống nhất đẩy sớm lịch hoàn thành API cổng OnePay lên 15h chiều ngày 04/11/2026 nhé.`
   *Mong đợi:* Thuộc tính `deadline` = `15:00 04/11/2026`.

2. **Claim Ngân sách (Budget):**
   `Sếp vừa duyệt chi thêm 85 triệu đồng cho hạng mục mở rộng cụm máy chủ chịu tải cao.`
   *Mong đợi:* Thuộc tính `budget` = `85.000.000 VNĐ`.

3. **Claim Phân công Nhân sự (Lead / Assignee):**
   `Từ tuần này anh Nguyễn Văn Nam sẽ phụ trách chính module tích hợp thanh toán thẻ thay cho Tuấn nhé.`
   *Mong đợi:* Thuộc tính `lead` = `Nguyễn Văn Nam`.

4. **Claim Trạng thái Tiến độ (Status):**
   `Hạng mục thiết kế giao diện mobile app OmniShop đã hoàn thành và sẵn sàng cho đội Dev tích hợp.`
   *Mong đợi:* Thuộc tính `status` = `hoàn thành`.

5. **Claim Phạm vi Công việc (Scope):**
   `Ban giám đốc quyết định mở rộng phạm vi thử nghiệm từ 20 siêu thị lên 35 siêu thị trên toàn quốc.`
   *Mong đợi:* Thuộc tính `scope` = `mở rộng từ 20 lên 35 siêu thị`.

6. **Claim Cập nhật Thay thế (Replaces Fact Cũ):**
   `Lịch bàn giao bản Beta dời lại từ ngày 12/11 sang ngày 18/11/2026 nhé mọi người.`
   *Mong đợi:* Bóc tách ngày mới `18/11/2026` và đánh dấu thay thế (`replaces`) cho mốc cũ.

---

## PHẦN 5: KIỂM THỬ THU HỒI TIN NHẮN (MESSAGE RECALL & 4-TIER CASCADE SYNC - EDL-0015)

Phần này dùng để kiểm tra phản ứng của hệ thống khi người gửi hoặc lãnh đạo bấm **Recall (Thu hồi)** tin nhắn trên ứng dụng Lark.

### Kịch bản Thu hồi 1: Thu hồi câu hỏi sau khi Bot đã trả lời (Bot Reply Cascade Recall)
- **Mục đích:** Khi người dùng xóa/thu hồi câu hỏi đã được bot trả lời, bot phải tự động thu hồi tin nhắn trả lời của chính bot để nhóm chat sạch sẽ.
- **Kênh gửi:** Nhóm chat `[Dự Án] OmniShop Core`.
- **Thao tác thực hiện:**
  1. Gửi tin nhắn câu hỏi:
     `Dạ cho em hỏi PM dự án này là ai ạ?`
  2. Đợi Bot trả lời tự động vào nhóm:
     `PM dự án HỆ THỐNG BÁN LẺ THÔNG MINH OMNISHOP là Hoàng Minh Tuấn nhé em...`
  3. Trên Lark Desktop/Mobile: Click chuột phải (hoặc nhấn giữ) vào tin nhắn hỏi ban đầu -> Chọn **Recall (Thu hồi)**.
- **Mong đợi hệ thống xử lý:**
  1. Lark gửi sự kiện WebSocket `im.message.recalled_v1` về server.
  2. Terminal server hiển thị:
     `🗑️ [LARK RECALL PHÁT HIỆN] Tin nhắn đã bị thu hồi trên Lark!`
     `🛡️ [TẦNG 1 - STAGING] Đã đánh dấu is_recalled: True cho <message_id> -> Loại khỏi Daily Digest.`
     `🤖 [TẦNG 4 - BOT REPLY CASCADE] Tin nhắn gốc từng được Bot reply qua <bot_msg_id>. Tiến hành thu hồi...`
     `✔ [TẦNG 4 - BOT REPLY CASCADE] Đã thu hồi thành công tin nhắn reply của Bot!`
  3. **Quan sát giao diện Lark:** Câu trả lời của bot trong nhóm chat tự động biến mất (thu hồi) trong vòng 1-2 giây.
- **Lệnh kiểm tra MongoDB nhanh:**
  `uv run python -c "from database.db import get_sync_db; db=get_sync_db(); doc=db['conversation_staging'].find_one({'is_recalled': True}); print('Staging recalled:', doc.get('is_recalled'), 'Bot reply id:', doc.get('bot_reply_message_id'))"`

---

### Kịch bản Thu hồi 2: Thu hồi tin nhắn Báo cáo / Blocker (Daily Digest Guard)
- **Mục đích:** Đảm bảo các tin nhắn báo cáo nhầm hoặc sự cố đã giải quyết không lọt vào Báo cáo tổng hợp cuối ngày của Sếp.
- **Kênh gửi:** Nhóm chat `[Dự Án] OmniShop Core`.
- **Thao tác thực hiện:**
  1. Gửi tin nhắn cập nhật blocker:
     `Cảnh báo blocker: Cổng thanh toán OnePay đang bảo trì đột xuất, toàn bộ giao dịch thẻ đang bị lỗi 500.`
  2. Kiểm tra terminal: Hệ thống ghi nhận vào `conversation_staging`.
  3. Giả định sau 1 phút đối tác khắc phục xong, người gửi bấm **Recall (Thu hồi)** tin nhắn cảnh báo trên Lark.
  4. Vào cửa sổ chat riêng với Bot (DM), Chủ nhân gõ lệnh:
     `xem digest`
- **Mong đợi hệ thống xử lý:**
  1. Tầng 1 đánh dấu `is_recalled: True` cho tin nhắn.
  2. Khi `DigestService.get_staging_messages` truy vấn MongoDB, điều kiện `{"is_recalled": {"$ne": True}}` tự động loại bỏ tin nhắn này.
  3. Thẻ Master Daily Digest gửi về cho Sếp **hoàn toàn không có dòng blocker lỗi 500 của OnePay**.

---

### Kịch bản Thu hồi 3: Thu hồi tin nhắn Đề xuất Tri thức (Claims Revocation)
- **Mục đích:** Ngăn chặn việc Sếp phê duyệt nhầm một thông tin/quyết định mà nhân sự đã chủ động rút lại.
- **Kênh gửi:** Nhóm chat `[Dự Án] OmniShop Core`.
- **Thao tác thực hiện:**
  1. Gửi tin nhắn đề xuất:
     `Đề xuất dời hạn chót nghiệm thu Sprint 2 sang ngày 30/11/2026 nhé cả nhóm.`
  2. Hệ thống bóc tách claim với trạng thái `status: "proposed"`.
  3. Người gửi nhận ra nhầm lịch và bấm **Recall (Thu hồi)** tin nhắn này.
- **Mong đợi hệ thống xử lý:**
  1. Tầng 2 kích hoạt hàm `revoke_claims_by_message_id`.
  2. Claim được chuyển từ trạng thái `proposed` sang `revoked` với lý do: *"Tin nhắn gốc đã bị người dùng thu hồi"*.
  3. Terminal hiển thị:
     `🚫 [TẦNG 2 - CLAIMS] Đã hủy bỏ 1 đề xuất tri thức (PROPOSED -> REVOKED).`
  4. Khi Sếp xem danh sách đề xuất (`xem claims`), mục đề xuất dời ngày 30/11/2026 không còn xuất hiện trong hàng đợi duyệt.
- **Lệnh kiểm tra MongoDB nhanh:**
  `uv run python -c "from database.db import get_sync_db; db=get_sync_db(); docs=list(db['claims'].find({'status': 'revoked'})); print('Số lượng claims đã thu hồi:', len(docs))"`

---

### Kịch bản Thu hồi 4: Thu hồi câu hỏi đang ở trạng thái Bản nháp chờ duyệt (Draft Cancellation)
- **Mục đích:** Khi người dùng thu hồi câu hỏi đang chờ Sếp duyệt bản nháp trong DM, bản nháp đó tự động bị hủy để tránh gửi câu trả lời thừa.
- **Kênh gửi:** Nhóm chat `[Dự Án] OmniShop Core`.
- **Thao tác thực hiện:**
  1. Nhân viên gửi câu hỏi yêu cầu duyệt bản nháp (ví dụ câu hỏi về chính sách hoặc câu hỏi mới):
     `Cho mình hỏi quy trình xin cấp thêm thiết bị test POS của dự án này thế nào?`
  2. Bot tạo bản nháp câu trả lời và gửi Thẻ tương tác vào DM của Sếp (trạng thái `pending`).
  3. Trước khi Sếp bấm nút `Gửi vào nhóm`, người hỏi bấm **Recall (Thu hồi)** câu hỏi trong nhóm chat.
- **Mong đợi hệ thống xử lý:**
  1. Tầng 3 kích hoạt `cancel_pending_drafts_by_message_id`.
  2. Bản ghi nháp trong MongoDB `draft_logs` được cập nhật trạng thái `status: "recalled"`.
  3. Terminal hiển thị:
     `❌ [TẦNG 3 - DRAFTS] Đã tự động hủy 1 bản nháp đang chờ duyệt.`
  4. Nếu Sếp bấm nút `Gửi vào nhóm` trên thẻ cũ, hệ thống báo lỗi an toàn: tin nhắn gốc đã bị thu hồi nên bản nháp không được phát ngôn.

---

## PHẦN 6: KIỂM THỬ PHÊ DUYỆT ĐỀ XUẤT QUA REACTION & THREAD REPLY (3-TIER DECISION GOVERNANCE - EDL-0011)

Phần này dùng để kiểm tra tính năng phê duyệt tri thức tức thì không cần mở thẻ hay gõ lệnh phức tạp, trực tiếp ngay trong luồng thảo luận nhóm.

### Kịch bản Phê duyệt 1: Lãnh đạo chấp nhận đề xuất thông qua Reaction (Fast Reaction Hook - Tầng 1)
- **Mục đích:** Khi nhân viên đề xuất một mốc thời gian / phương án mới, Lãnh đạo chỉ cần thả biểu tượng cảm xúc đồng thuận (như Thumbs up, Check mark, OK) vào tin nhắn đó, hệ thống tự động thăng hạng đề xuất thành tri thức chính thức (CURRENT) với chi phí 0 token LLM và độ trễ 0ms.
- **Kênh thực hiện:** Nhóm chat `[Dự Án] OmniShop Core`.
- **Thao tác thực hiện:**
  1. Tài khoản Nhân sự gửi tin nhắn đề xuất:
     `Em đề xuất dời hạn chót kiểm thử tải cổng thanh toán sang ngày 15/11/2026 nhé anh Tuấn PM.`
  2. Hệ thống bóc tách Fact với trạng thái `status: "proposed"`.
  3. Tài khoản Lãnh đạo (Chủ nhân token / Hoài Nam) di chuột vào tin nhắn trên Lark và bấm thả biểu tượng cảm xúc:
     - Chọn biểu tượng ngón tay cái (Thumbs up / +1) HOẶC dấu tích xanh (Check mark / OK).
- **Mong đợi hệ thống xử lý:**
  1. Lark gửi sự kiện WebSocket `im.message.reaction.created_v1` về server.
  2. Bộ lọc bảo mật [dispatcher.py](file:///Users/hoainam/Desktop/HiLark/server/services/lark/dispatcher.py#L304) kiểm tra và xác nhận: người thả biểu tượng chính là Lãnh đạo (`is_owner = True`).
  3. Kích hoạt hàm [promote_claims_by_message_id](file:///Users/hoainam/Desktop/HiLark/server/database/db.py#L349): thăng hạng Fact gắn với tin nhắn đó từ `proposed` thành `current`.
  4. Terminal hiển thị:
     `[LARK REACTION] Bắt được reaction 'THUMBSUP' vào tin nhắn om_xxx từ ou_xxx`
     `[FAST REACTION APPROVAL] Sếp đã thả THUMBSUP vào tin om_xxx! Đã thăng hạng 1 fact(s) thành CURRENT.`
- **Lệnh kiểm tra MongoDB nhanh:**
  `uv run python -c "from database.db import get_sync_db; db=get_sync_db(); doc=db['claims'].find_one({'status': 'current', 'promoted_by_message_id': {'$exists': True}}); print('Fact đã duyệt:', doc.get('property'), '->', doc.get('value'), '| Người duyệt:', doc.get('asserted_by'))"`

---

### Kịch bản Phê duyệt 2: Lãnh đạo phê duyệt nguyên trạng bằng Reply luồng (Smart Thread Reply - Tầng 2)
- **Mục đích:** Khi Lãnh đạo bấm Reply trực tiếp vào tin nhắn đề xuất và gõ ngắn gọn ("Ok em", "Duyệt nhé", "Đồng ý"), AI Semantic NLU phân loại hành động `APPROVE_AS_IS` và tự động thăng hạng tri thức ngay lập tức.
- **Kênh thực hiện:** Nhóm chat `[Dự Án] OmniShop Core`.
- **Thao tác thực hiện:**
  1. Tài khoản Nhân sự gửi tin nhắn đề xuất:
     `Nhóm đề xuất chọn thư viện ChartJS để vẽ biểu đồ doanh thu cho dashboard OmniShop nhé.`
  2. Tài khoản Lãnh đạo click chuột phải vào tin nhắn trên -> chọn **Reply (Trả lời theo luồng / Thread Reply)**.
  3. Lãnh đạo gõ nội dung reply:
     `Ok em` (hoặc `Duyệt phương án này nhé`, `Đồng ý`)
- **Mong đợi hệ thống xử lý:**
  1. Hệ thống phát hiện tin nhắn có `parent_id` trỏ đến tin nhắn gốc của nhân sự.
  2. Bộ phân loại JEV Semantic phân tích cặp câu (Đề xuất + Phản hồi của sếp):
     - Phân loại: `APPROVE_AS_IS` (Độ tin cậy > 0.90).
  3. Kích hoạt Fast-lane: Thăng hạng claim của tin nhắn gốc thành `current` mà không tốn token sinh văn bản.
  4. Terminal hiển thị:
     `[THREAD REPLY PHÁT HIỆN] Sếp reply tin nhắn 'om_xxx': \"Nhóm đề xuất chọn thư viện ChartJS...\"`
     `[THREAD JEV DECISION] Quyết định của Sếp: APPROVE_AS_IS (Độ tin cậy: 0.96)`
     `[THREAD APPROVAL FAST-LANE] Sếp reply 'Ok em' -> APPROVE_AS_IS! Đã thăng hạng 1 fact(s) thành CURRENT (0 LLM tokens).`

---

### Kịch bản Phê duyệt 3: Lãnh đạo phê duyệt kèm điều chỉnh thông số (Approve with Changes)
- **Mục đích:** Khi Lãnh đạo đồng ý nhưng điều chỉnh lại giá trị (ví dụ nhân viên xin 4 ngày nhưng sếp chỉ cho 2 ngày), hệ thống thông minh kết hợp cả hai ngữ cảnh để cập nhật giá trị đã điều chỉnh thành tri thức chính thức.
- **Kênh thực hiện:** Nhóm chat `[Dự Án] OmniShop Core`.
- **Thao tác thực hiện:**
  1. Tài khoản Nhân sự gửi tin nhắn đề xuất:
     `Anh Tuấn ơi cho đội mobile xin dời hạn chót tích hợp SDK thêm 4 ngày nữa được không ạ?`
  2. Tài khoản Lãnh đạo bấm **Reply theo luồng** vào tin nhắn trên và gõ:
     `Dời 2 ngày thôi nhé, cuối tuần này phải xong không được dời thêm.`
- **Mong đợi hệ thống xử lý:**
  1. JEV phân loại quyết định: `APPROVE_WITH_CHANGES`.
  2. Hệ thống tổng hợp ngữ cảnh đề xuất ban đầu (xin 4 ngày) và chỉ đạo của Sếp (chỉ duyệt 2 ngày).
  3. LLM cập nhật giá trị Fact chính xác: Gia hạn thêm 2 ngày, trạng thái `current`.
  4. Terminal hiển thị:
     `[THREAD JEV DECISION] Quyết định của Sếp: APPROVE_WITH_CHANGES`
     `[THREAD MODIFICATION] Sếp reply -> Kích hoạt cập nhật giá trị điều chỉnh mới...`

---

### Kịch bản Phê duyệt 4: Lãnh đạo từ chối đề xuất bằng Reply luồng (Reject)
- **Mục đích:** Khi Lãnh đạo không đồng ý, đề xuất lập tức bị hủy bỏ để không còn nằm trong danh sách chờ duyệt.
- **Kênh thực hiện:** Nhóm chat `[Dự Án] OmniShop Core`.
- **Thao tác thực hiện:**
  1. Tài khoản Nhân sự gửi tin nhắn:
     `Em đề xuất hủy bỏ tính năng quét mã QR thanh toán tại quầy trong đợt ra mắt này nhé.`
  2. Tài khoản Lãnh đạo bấm **Reply theo luồng** vào tin nhắn trên và gõ:
     `Không được em ơi, tính năng này bắt buộc phải có trong đợt 1.`
- **Mong đợi hệ thống xử lý:**
  1. JEV phân loại quyết định: `REJECT` (Độ tin cậy > 0.90).
  2. Kích hoạt [reject_claims_by_message_id](file:///Users/hoainam/Desktop/HiLark/server/database/db.py#L492), chuyển claim sang `superseded` / `rejected`.
  3. Terminal hiển thị:
     `[THREAD JEV DECISION] Quyết định của Sếp: REJECT`
     `[THREAD REJECT] Sếp reply -> REJECT! Đã từ chối 1 fact(s).`

