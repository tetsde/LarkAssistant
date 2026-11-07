# Đặc tả Kỹ thuật: Kiến trúc JEV System 1 trong HiLark Server

Tài liệu này ghi lại chi tiết các tham số kỹ thuật, cấu trúc payload HTTP, cơ chế tính toán xác suất và quy tắc định tuyến của mô hình phân loại JEV System 1 trong HiLark Server.

Mã nguồn liên quan:
- Bộ phân loại JEV: [`server/services/ai/jev_classifier.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/jev_classifier.py)
- Điều phối quy trình: [`server/services/workflows/chat_workflow.py`](file:///Users/hoainam/Desktop/HiLark/server/services/workflows/chat_workflow.py)
- Kết nối HTTP bền vững: [`server/core/http_client.py`](file:///Users/hoainam/Desktop/HiLark/server/core/http_client.py)

---

## 1. Tổng quan hạ tầng & Giao thức kết nối

JEV System 1 là dịch vụ phân loại xác suất định lượng thời gian thực:

| Thuộc tính | Cấu hình | Ý nghĩa kỹ thuật |
| :--- | :--- | :--- |
| **API Endpoint** | `https://api.typesafe.ai/v1/systemone` | Cổng tiếp nhận truy vấn phân loại nhị phân / đa nhãn. |
| **Mô hình (Model)** | `jev-latest` | Phiên bản mô hình phân loại xác suất của JEV. |
| **Giao thức xác thực** | `Authorization: Bearer {settings.JEV_API_KEY}` | Đọc từ biến môi trường `JEV_API_KEY` (hoặc `jev_api`). |
| **HTTP Client** | `httpx.AsyncClient` | Sử dụng persistent connection pool của `HttpClientPool`. |
| **Timeout mặc định** | `10.0s` (Gating & Rerank) / `30.0s` (Classifier) | Giới hạn thời gian tối đa để kích hoạt cơ chế Fail-safe nếu mạng nghẽn. |

---

## 2. Trạm 1: Chốt chặn bảo mật và nhãn cấm (Forbidden Intent Gating)

### 2.1. Vị trí và vai trò
- **Vị trí mã nguồn:** [`server/services/ai/jev_classifier.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/jev_classifier.py)
- **Hàm thực thi:** `JevClassifier.check_forbidden_query()`
- **Mục tiêu:** Ngăn chặn ngay lập tức bất kỳ câu hỏi nào cố tình tra cứu các chủ đề cấm đã cấu hình trong Lark Base (ví dụ: Chi phí, Ngân sách, Bảng lương, Hợp đồng đối tác).

### 2.2. Chi tiết thực thi
```
[Câu hỏi người dùng + Danh sách forbidden_labels từ Lark Base]
               │
               ▼
     [Fast Keyword Matcher]
       • Quét từ khóa cấm có dấu và không dấu (< 0.1ms)
       • Nếu trùng khớp -> is_forbidden = True (Ngắt sớm)
               │ (Nếu câu hỏi dùng từ lắt léo, ẩn ý, tiếng lóng)
               ▼
     [JEV Semantic Evaluator]
       • Gọi JEV System 1 API (Model: 'jev-latest')
       • Phân tích ngữ nghĩa: 'FORBIDDEN' vs 'ALLOWED'
       • Nhận diện: Tiếng lóng, hỏi vòng vo, ngụ ý tài chính/lương bổng
               │ (Xác định vi phạm qua ngưỡng xác suất)
               ▼
     [Zero-Response Guard] -> Bot im lặng 100%, ngắt chu trình trong nhóm
               │
               ▼
     [Silent Alert Dispatcher] -> Chuyển Thẻ nháp bảo mật về DM Quản trị viên
```

### 2.3. Bảng đối chiếu nhận diện ngữ nghĩa sâu

| Kiểu diễn đạt | Ví dụ câu hỏi | Nhãn cấm | Phản xạ Keyword | Phản xạ JEV Semantic |
| :--- | :--- | :--- | :--- | :--- |
| **Dùng tiếng lóng** | *"Tháng này kế toán đã ting ting mấy chục củ vào tài khoản chưa?"* | `Lương, Thu nhập` | Bỏ sót (không có chữ "lương") | Bắt `FORBIDDEN` (hiểu ting ting + củ = tiền lương) |
| **Hỏi vòng vo** | *"Dự án này bên mình nhận được bao nhiêu phần trăm từ đối tác?"* | `Ngân sách, Chi phí` | Bỏ sót (không có chữ "ngân sách") | Bắt `FORBIDDEN` (hiểu phần trăm = lợi nhuận mật) |
| **Nói giảm nói tránh** | *"Cho tui xin cái file có chữ ký hai bên với công ty B"* | `Hợp đồng, NDA` | Bỏ sót (không có chữ "hợp đồng") | Bắt `FORBIDDEN` (hiểu file ký 2 bên = hợp đồng pháp lý) |
| **Hỏi quy mô vốn** | *"Đợt này duyệt rót bao nhiêu tỷ để chạy marketing?"* | `Ngân sách` | Bỏ sót (không có chữ "ngân sách") | Bắt `FORBIDDEN` (hiểu duyệt rót tiền = phân bổ ngân sách) |
| **Chuyên môn hợp lệ** | *"Số lượng màn hình UI cần thiết kế trong Sprint 5 là bao nhiêu?"* | `Lương` | An toàn (không bắt nhầm "lương" trong "số lượng") | Bắt `ALLOWED` (xác định đúng là hỏi khối lượng việc) |

### 2.4. Ngưỡng phân định xác suất
Hệ thống xác định vi phạm (`is_forbidden = True`) nếu thỏa mãn một trong các điều kiện:
```python
is_forbidden = (
    (choice == "FORBIDDEN" and prob_forbidden >= 0.65)
    or (prob_forbidden >= 0.70)
    or bool(keyword_matched)
)
```

---

## 3. Trạm 2: Phân loại ý định tin nhắn (Gatekeeper Router)

### 3.1. Vị trí và vai trò
- **Vị trí mã nguồn:** [`server/services/ai/jev_classifier.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/jev_classifier.py)
- **Hàm thực thi:** `JevClassifier.classify_message()`
- **Mục tiêu:** Phân loại tin nhắn thành 1 trong 5 hành động: `IGNORE`, `MEMORY_ONLY`, `REPLY_ONLY`, `MEMORY_AND_DRAFT`, hoặc `DRAFT_PENDING_APPROVAL`.

### 3.2. Cấu trúc câu hỏi phân loại gửi tới JEV
```json
{
  "state": "Tin nhắn từ thành viên: 'Dự án Fintech deadline chuyển sang ngày 15/11 nhé'",
  "model": "jev-latest",
  "questions": {
    "intent_classification": {
      "type": "choice",
      "instructions": "Phân loại mục đích của tin nhắn trong môi trường làm việc doanh nghiệp.",
      "criteria": {
        "IGNORE": "Lời chào hỏi xã giao, cảm ơn, tán gẫu ngoài lề, không chứa thông tin công việc.",
        "MEMORY_ONLY": "Cập nhật tiến độ, quyết định, thay đổi deadline hoặc phân công nhân sự; không yêu cầu phản hồi.",
        "REPLY_ONLY": "Câu hỏi nghiệp vụ thông thường cần tra cứu tài liệu để trả lời vào nhóm.",
        "MEMORY_AND_DRAFT": "Vừa cung cấp thông tin mới vừa có câu hỏi nhạy cảm cần phê duyệt.",
        "DRAFT_PENDING_APPROVAL": "Câu hỏi nhạy cảm, thiếu dữ liệu chứng thực hoặc cần Quản trị viên duyệt trước khi phát ngôn."
      }
    }
  }
}
```

---

## 4. Trạm 3: Lọc ngữ nghĩa và tái sắp xếp RAG (Semantic Reranker)

### 4.1. Vị trí và vai trò
- **Vị trí mã nguồn:** [`server/services/ai/jev_classifier.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/jev_classifier.py)
- **Hàm thực thi:** `JevClassifier.filter_chunks_relevance()`
- **Mục tiêu:** Đánh giá độ tương quan của từng đoạn trích từ WeKnora và sắp xếp đoạn phù hợp nhất lên đầu.

### 4.2. Quy trình Reranking
1. **Thu gọn đoạn trích (Pruning):** Giới hạn tối đa 5 chunks, cắt ngắn mỗi đoạn $\le 300$ ký tự để tiết kiệm băng thông mạng.
2. **Batch Request:** Đóng gói toàn bộ 5 đoạn trích vào 1 request HTTP duy nhất gửi tới JEV System 1.
3. **Chấm điểm & Sắp xếp:** Trích xuất xác suất `RELEVANT`, loại bỏ các đoạn `IRRELEVANT`, sắp xếp các đoạn trích theo điểm xác suất giảm dần.
4. **Bảo toàn dự phòng:** Nếu việc lọc loại bỏ toàn bộ các đoạn nhưng câu hỏi cần trả lời, giữ lại các đoạn trích ban đầu để Context Composer kiểm tra trước khi quyết định hạ cấp sang bản nháp.
