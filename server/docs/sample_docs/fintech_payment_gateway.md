# TÀI LIỆU ĐẶC TẢ KIẾN TRÚC DỰ ÁN: CỔNG THANH TOÁN & VÍ ĐIỆN TỬ PAYSTREAM
**Mã dự án:** PAYSTREAM-CORE-2026  
**Phiên bản:** 2.0.0-PROD  
**Ngày phát hành:** 12/10/2026  
**Đơn vị chủ quản:** Khối Công nghệ Fintech & Khối Vận hành Thanh toán Số  

---

## 1. TỔNG QUAN DỰ ÁN & MỤC TIÊU KINH DOANH

### 1.1. Bối cảnh thị trường
Thị trường thương mại điện tử và thanh toán không tiền mặt tăng trưởng với tốc độ trên 30%/năm. Các hệ thống thanh toán truyền thống theo kiến trúc Monolith thường gặp nghẽn cổ chai nghiêm trọng vào các đợt siêu khuyến mãi (Flash Sale, Black Friday), dẫn đến tình trạng treo giao dịch, trừ tiền nhưng không ghi nhận đơn hàng và độ trễ giao dịch vượt quá mức chấp nhận được.

Dự án **PayStream Payment Gateway** được thiết kế từ đầu theo kiến trúc Microservices phân tán hướng sự kiện (Event-Driven Architecture), nhằm phục vụ quy mô xử lý thanh toán thời gian thực với hiệu năng cực cao và độ tin cậy tuyệt đối.

### 1.2. Mục tiêu kỹ thuật & Kinh doanh
- **Năng lực chịu tải cao (High Throughput):** Đạt ngưỡng xử lý tối thiểu 100,000 TPS (Transactions Per Second) tại thời điểm cao điểm.
- **Độ trễ cực thấp (Ultra-Low Latency):** Thời gian phản hồi xử lý giao dịch nội bộ đạt $P99 < 120\text{ ms}$.
- **Độ tin cậy & Sẵn sàng (High Availability):** Cam kết $99.999\%$ uptime (thời gian gián đoạn tối đa không quá 5 phút/năm).
- **Tuân thủ chuẩn bảo mật toàn cầu:** Đạt chứng chỉ bảo mật dữ liệu thẻ thanh toán quốc tế PCI-DSS Level 1.

---

## 2. KIẾN TRÚC HỆ THỐNG TỔNG THỂ

Hệ thống PayStream bao gồm 5 phân tầng kỹ thuật chuyên biệt:

```
+-------------------------------------------------------------------------------+
|                             CLIENT APPS & MERCHANTS                           |
|       (Mobile SDK, Web Checkout, POS Terminal, Open API Merchant Server)      |
+---------------------------------------+---------------------------------------+
                                        | (HTTPS / mTLS / HMAC-SHA256)
                                        v
+-------------------------------------------------------------------------------+
|                       API GATEWAY & TRAFFIC SHAPING                           |
|     - Envoy Proxy / Kong Gateway (Rate Limiting, DDoS Shield, WAF)            |
|     - Identity & OAuth2 / mTLS Authentication Service                         |
+---------------------------------------+---------------------------------------+
                                        |
                 +----------------------+----------------------+
                 |                                             |
                 v                                             v
+-----------------------------------+         +---------------------------------+
|      CORE PAYMENT ORCHESTRATOR    |         |    AI FRAUD DETECTION ENGINE    |
| - Idempotency Validation (Redis)  |         | - Real-time Risk Scoring (<20ms)|
| - Saga Transaction Coordinator    |         | - Device Fingerprinting         |
| - Dynamic Payment Routing Engine  |         | - Velocity & Geolocation Rules  |
+----------------+------------------+         +----------------+----------------+
                 |                                             |
                 +----------------------+----------------------+
                                        | (Apache Kafka Event Bus)
                                        v
+-------------------------------------------------------------------------------+
|                       SPECIALIZED DOMAIN SERVICES                             |
|  [Wallet Service]   [Card Gateway]   [Napas/QR Gateway]   [Double-Entry Ledger]
|      (Go / gRPC)       (Java 21)         (Rust)              (PostgreSQL Partition)|
+-------------------------------------------------------------------------------+
```

---

## 3. THIẾT KẾ GIAO DỊCH PHÂN TÁN (SAGA PATTERN)

Để đảm bảo tính nhất quán dữ liệu mà không gây khóa chết (Deadlock) cơ sở dữ liệu khi phân tán trên hàng chục microservices, PayStream áp dụng mô hình **Saga Pattern dạng Điều phối tập trung (Orchestration-based Saga)**:

1. **Khởi tạo giao dịch (Initiate Payment):**
   - API Gateway nhận request kèm header `X-Idempotency-Key: <UUID>`.
   - Redis Cluster kiểm tra tính trùng lặp trong 120 giây. Nếu key đã tồn tại, lập tức trả về kết quả đã cache để chống trừ tiền 2 lần.
2. **Thẩm định gian lận thời gian thực (Fraud Scoring):**
   - Fraud Engine chấm điểm rủi ro. Nếu điểm rủi ro $< 15/100$, giao dịch được phê duyệt tự động; nếu từ $15 - 60$, yêu cầu xác thực sinh trắc học/OTP 3D-Secure; nếu $> 60$, từ chối lập tức.
3. **Thực thi bút toán ghi nợ & ghi có (Double-Entry Bookkeeping):**
   - Khởi tạo bút toán treo (Hold/Pending Balance) tại tài khoản người mua.
   - Gửi yêu cầu trừ tiền sang mạng lưới thẻ quốc tế (Visa/Mastercard) hoặc liên ngân hàng Napas.
4. **Xác nhận hoàn tất hoặc Hoàn tác (Compensating Transaction):**
   - Nếu ngân hàng trả về thành công: Bút toán được chuyển thành `POSTED`, cập nhật số dư khả dụng người bán.
   - Nếu ngân hàng từ chối hoặc timeout: Saga Coordinator kích hoạt chuỗi giao dịch bù (Compensating Actions) để giải phóng số dư treo cho khách hàng ngay lập tức.

---

## 4. MA TRẬN PHÂN LOẠI CỔNG VÀ PHÍ DỊCH VỤ

| Kênh thanh toán | Thời gian xử lý trung bình | Tỷ lệ thành công mục tiêu | Cơ chế xác thực | Mức phí Merchant |
| :--- | :--- | :--- | :--- | :--- |
| **VietQR / Napas 247** | $1.2\text{ giây}$ | $\ge 99.2\%$ | Dynamic QR + App OTP | $0.8\% + 1,000\text{ VND}$ |
| **Thẻ ghi nợ nội địa (ATM)**| $2.5\text{ giây}$ | $\ge 97.5\%$ | Smart OTP Ngân hàng | $1.1\% + 1,500\text{ VND}$ |
| **Thẻ quốc tế (Visa/Master)**| $1.8\text{ giây}$ | $\ge 98.8\%$ | 3D-Secure 2.0 (EMVCo) | $2.2\% + 2,000\text{ VND}$ |
| **Ví điện tử PayStream** | $0.4\text{ giây}$ | $\ge 99.8\%$ | Sinh trắc học (Face/Touch ID)| $0.9\%$ trọn gói |

---

## 5. BẢO MẬT & TIÊU CHUẨN TUÂN THỦ PCI-DSS LEVEL 1

- **Cơ chế Tokenization:** Toàn bộ thông tin thẻ nhạy cảm (Số thẻ PAN 16 chữ số, ngày hết hạn, mã CVV) không bao giờ lưu trữ trực tiếp trên cơ sở dữ liệu ứng dụng. Hệ thống băm và thay thế bằng chuỗi Token ngẫu nhiên (Surrogate Token).
- **Mã hóa phần cứng qua HSM (Hardware Security Module):** Khóa giải mã chính (Master Keys) được lưu trữ và thực thi mã hóa trong thiết bị phần cứng chuyên dụng chuẩn FIPS 140-2 Level 3.
- **Mã hóa đường truyền mTLS:** Toàn bộ giao tiếp giữa các microservices nội bộ bắt buộc phải qua mTLS (Mutual TLS 1.3) với chứng chỉ số X.509 được luân phiên tự động mỗi 30 ngày.
- **Zero-Trust Network:** Phân chia mạng lưới cô lập bằng Kubernetes Network Policies; database chỉ chấp nhận kết nối từ IP Whitelist của các dịch vụ chuyên trách.

---

## 6. ĐẶC TẢ API THANH TOÁN (REST / JSON)

### 6.1. Endpoint Tạo Lệnh Thanh Toán (Create Payment Order)
- **Method:** `POST /v2/payments/charges`
- **Headers:**
  - `Authorization: Bearer <Merchant_API_Key>`
  - `X-Idempotency-Key: e8a946b2-6cb1-4384-82f9-7fba11b81920`
  - `Content-Type: application/json`

```json
{
  "order_id": "ORD-20261012-9841",
  "amount": 2500000,
  "currency": "VND",
  "payment_method": "VIETQR",
  "customer_info": {
    "customer_id": "CUST-9921",
    "email": "customer@example.com",
    "phone": "+84901234567"
  },
  "return_url": "https://merchant.vn/checkout/callback",
  "signature": "c88f9104b92b6a213e4b0c..."
}
```

### 6.2. Webhook Callback Thông Báo Kết Quả
Hệ thống PayStream gửi Webhook thông báo kết quả tức thời tới server Merchant với chữ ký số HMAC-SHA512 để xác minh tính toàn vẹn gói tin.

---

## 7. KẾ HOẠCH BÀN GIAO & VẬN HÀNH

```
Quý 1/2026 : Phát triển Core Payment Engine, Mock Napas/Visa Integration
Quý 2/2026 : Kiểm toán bảo mật PCI-DSS Level 1 & Penetration Testing độc lập
Quý 3/2026 : Chạy Pilot với 20 doanh nghiệp TMĐT đối tác chiến lược
Quý 4/2026 : Ra mắt chính thức toàn quốc, hỗ trợ 24/7 với đội ngũ NOC & SOC
```
