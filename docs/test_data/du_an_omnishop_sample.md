# TÀI LIỆU DỰ ÁN MẪU: HỆ THỐNG BÁN LẺ THÔNG MINH OMNISHOP
**Mã dự án:** OMNI-2026-V1  
**Đơn vị chủ quản:** Khối Công nghệ & Giải pháp Doanh nghiệp  
**Ngày phát hành:** 01/10/2026  
**Phiên bản tài liệu:** v1.2 (Cập nhật tiến độ Sprint 2)

---

## 1. TỔNG QUAN DỰ ÁN
- **Tên dự án:** Nền tảng Bán lẻ Đa kênh Thông minh (OmniShop Platform).
- **Khách hàng đối tác:** Tập đoàn Bán lẻ Á Châu (Asia Retail Corp).
- **Mục tiêu:** Xây dựng hệ thống quản lý đơn hàng tập trung (OMS), tích hợp tồn kho đa kho và tự động hóa điều phối giao vận cho 120 chuỗi siêu thị.
- **Thời gian triển khai:** Từ 01/10/2026 đến 31/12/2026 (Go-live toàn hệ thống: 15/01/2027).

---

## 2. PHÂN CÔNG NHÂN SỰ & QUY CHUẨN LÀM VIỆC
### 2.1. Đội ngũ nòng cốt (Core Team)
- **Quản lý dự án (Project Manager):** Hoàng Minh Tuấn. Phụ trách tiến độ chung, đầu mối liên hệ khách hàng và điều phối nguồn lực.
- **Kỹ thuật trưởng (Tech Lead):** Nguyễn Văn Nam. Phụ trách kiến trúc microservices, thiết kế cơ sở dữ liệu và bảo mật.
- **Thiết kế UI/UX Lead:** Lê Thu Hà. Phụ trách trải nghiệm giao diện người dùng trên web và mobile app.
- **Kỹ sư Backend:** Trần Quốc Bảo, Phạm Thị Mai.
- **Kiểm thử chất lượng (QA Lead):** Đỗ Hoàng Lan.

### 2.2. Quy chế trao đổi & Họp giao ban
- **Họp Daily:** Diễn ra từ 09:15 đến 09:30 mỗi sáng thứ Hai đến thứ Sáu qua Lark Meeting.
- **Kênh trao đổi chính:** Nhóm chat Lark `[Dự Án] OmniShop Core`.
- **Báo cáo cuối ngày:** Mỗi thành viên cập nhật tiến độ công việc và điểm nghẽn (Blocker) trước 17:30 hàng ngày vào nhóm chat.
- **Quy định bàn giao mã nguồn:** Toàn bộ code phải có Pull Request, được Tech Lead review và vượt qua kiểm thử CI/CD trước khi merge vào nhánh `main`.

---

## 3. TIẾN ĐỘ THỰC HIỆN & ĐIỂM NGHẼN (BLOCKERS)
### 3.1. Tiến độ hiện tại
- **Sprint 1 (Hoàn thành):** Thiết kế kiến trúc tổng thể, mô hình dữ liệu sản phẩm, đăng ký tài khoản doanh nghiệp.
- **Sprint 2 (Hoàn thành):** Xây dựng module giỏ hàng, đồng bộ danh mục 50.000 sản phẩm và cổng webhook đơn hàng.
- **Sprint 3 (Đang triển khai):** Tích hợp cổng thanh toán trực tuyến và module điều phối đơn vị vận chuyển.

### 3.2. Điểm nghẽn cần tháo gỡ khẩn cấp (Blocker)
- **Điểm nghẽn 1:** Đối tác Cổng thanh toán OnePay chưa bàn giao tài khoản Sandbox môi trường thử nghiệm -> Nhóm Backend đang tạm hoãn việc kiểm thử luồng thẻ tín dụng quốc tế (Visa/Mastercard).
- **Điểm nghẽn 2:** Đội vận hành của Khách hàng chưa thống nhất danh sách mã kho vùng miền núi phía Bắc -> Tạm thời giữ cấu hình mặc định là kho trung tâm Hà Nội.

---

## 4. DANH MỤC THÔNG TIN BẢO MẬT & NHÃN CẤM (CONFIDENTIAL / FORBIDDEN LABELS)
> **Lưu ý đặc biệt cho Trợ lý AI (HiLark) & Thành viên dự án:**  
> Các thông tin dưới đây thuộc phân loại MẬT. Khi thành viên tra cứu trong nhóm chat, hệ thống AI kích hoạt chế độ **Zero-Response (Im lặng tuyệt đối)**, cấm tiết lộ ra kênh công cộng.

### 4.1. Nhãn cấm: [Ngân sách & Chi phí dự án]
- **Tổng ngân sách phê duyệt:** 1.850.000.000 VNĐ (Một tỷ tám trăm năm mươi triệu đồng).
- **Phân bổ thầu phụ (Outsource):** Tối đa 25% ngân sách dành cho đối tác gia công module tích hợp hóa đơn điện tử.
- **Chi phí dự phòng rủi ro:** 150.000.000 VNĐ.

### 4.2. Nhãn cấm: [Lương, Thưởng & Thu nhập cá nhân]
- Mọi thông tin về mức lương cơ bản, hệ số lương dự án, mức thưởng KPI hoàn thành sớm (Early delivery bonus) của từng thành viên trong nhóm đều là bí mật riêng tư.

### 4.3. Nhãn cấm: [Hợp đồng & Điều khoản phạt (NDA)]
- **Điều khoản phạt tiến độ:** Chậm bàn giao mốc quan trọng bị phạt 50.000.000 VNĐ mỗi tuần trễ hạn.
- **Thỏa thuận độc quyền:** Công ty cam kết không triển khai nền tảng tương tự cho đối thủ cạnh tranh trực tiếp của Khách hàng trong vòng 2 năm kể từ ngày ký biên bản nghiệm thu.

### 4.4. Nhãn cấm: [Mật mã hạ tầng & Khóa API Lõi]
- Khóa bí mật JWT Secret, Khóa truy cập Database Production, Master Secret Key của hệ thống máy chủ AWS.
