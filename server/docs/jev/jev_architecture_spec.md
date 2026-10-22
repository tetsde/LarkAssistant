# 📘 SPEC KỸ THUẬT: KIẾN TRÚC JEV SYSTEM ONE TRONG HỆ THỐNG HILARk
> **HiLark Server** — Bản đặc tả kỹ thuật chi tiết (Spec), đối chiếu mã nguồn thực tế, ưu tiên tiếng Việt, không dùng từ ngữ bóng bẩy.  
> **Vị trí file:** [`server/docs/jev/jev_architecture_spec.md`](file:///Users/hoainam/Desktop/HiLark/server/docs/jev/jev_architecture_spec.md)

---

## 🧭 1. TỔNG QUAN HẠ TẦNG & GIAO THỨC KẾT NỐI JEV

JEV (System One) là dịch vụ phân loại xác suất định lượng thời gian thực, được cung cấp qua endpoint của Typesafe AI:

| Thuộc tính | Cấu hình trong mã nguồn | Ý nghĩa kỹ thuật |
| :--- | :--- | :--- |
| **API Endpoint** | `https://api.typesafe.ai/v1/systemone` | Cổng tiếp nhận truy vấn phân loại nhị phân / đa nhãn. |
| **Mô hình (Model)** | `jev-latest` | Phiên bản mô hình phân loại xác suất mới nhất của JEV. |
| **Giao thức xác thực** | `Authorization: Bearer {settings.JEV_API_KEY}` | Đọc từ biến môi trường `jev_api` trong `.env`. |
| **Thư viện HTTP Client** | `httpx.AsyncClient` | Thực thi I/O bất đồng bộ hoàn toàn (Non-blocking Async). |
| **Timeout mặc định** | `10.0s` (Gating & Rerank) / `30.0s` (Classifier) | Giới hạn thời gian tối đa để kích hoạt cơ chế Fail-safe nếu mạng nghẽn. |

---

## 🛡️ 2. PARENT STEP 1: CHỐT CHẶN BẢO MẬT & NHÃN CẤM (FORBIDDEN INTENT GATING)

### 2.1. Vị trí và Vai trò
* **Vị trí trong Pipeline:** [`server/services/chat_service.py:L323-370`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L323-L370)
* **Hàm thực thi:** `JevService.check_forbidden_query()` tại [`server/services/jev.py:L198-388`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py#L198-L388)
* **Nhiệm vụ:** Ngăn chặn ngay lập tức bất kỳ câu hỏi nào của thành viên nhóm cố tình tra cứu các chủ đề cấm đã cấu hình trong Lark Base (ví dụ: `Chi phí`, `Ngân sách`, `Bảng lương`, `Hợp đồng`...).

### 2.2. Chi tiết thực thi Child Logic
```
[Câu hỏi người dùng + Danh sách forbidden_labels từ Lark Base]
               │
               ▼
     [Child 1.1: Fast Keyword Matcher]
       ├─ Quét thô từ khóa đen có dấu / không dấu (< 0.1ms)
       └─ Nếu dính từ khóa đen ➔ is_forbidden = True (Ngắt sớm tức thì)
               │ (Nếu câu hỏi dùng từ lắt léo, ẩn ý, tiếng lóng)
               ▼
     [Child 1.2: JEV Semantic Choice Evaluator]
       ├─ Gọi JEV System One API (Model: 'jev-latest')
       ├─ Phân tích ngữ nghĩa NLU: 'FORBIDDEN' vs 'ALLOWED'
       └─ Nhận diện: Tiếng lóng, hỏi vòng vo, ngụ ý tài chính/lương bổng
               │ (Xác định vi phạm qua ngưỡng xác suất)
               ▼
     [Child 1.3: Zero-Response Guard] ➔ Bot im lặng 100%, ngắt chu trình
               │
               ▼
     [Child 1.4: Silent DM Alert Dispatcher] ➔ Bắn tin DM báo động riêng cho Sếp
```

### 2.3. Năng lực Phân tích Ngữ nghĩa Sâu (Deep Semantic NLU & Slang Detection)
Điểm vượt trội của JEV nằm ở chỗ **nó không chỉ là bộ lọc chuỗi Regex thông thường**, mà thực sự "đọc hiểu" ý định ẩn giấu đằng sau câu hỏi:

| Kiểu lẩn tránh của người dùng | Ví dụ câu hỏi thực tế | Nhãn cấm trên Base | Phản xạ của Child 1.1 (Keyword) | Phản xạ của Child 1.2 (JEV Semantic AI) |
| :--- | :--- | :--- | :--- | :--- |
| **Dùng tiếng lóng (Slang)** | *"Tháng này kế toán đã ting ting mấy chục củ vào tài khoản chưa?"* | `Lương, Thu nhập` | ⚪ Bỏ sót (Không có chữ "lương") | 🔴 **Bắt `FORBIDDEN` (Hiểu ting ting + củ = tiền lương)** |
| **Hỏi vòng vo / Ẩn ý** | *"Dự án này bên mình đút túi được bao nhiêu phần trăm từ đối tác?"* | `Ngân sách, Chi phí` | ⚪ Bỏ sót (Không có chữ "ngân sách") | 🔴 **Bắt `FORBIDDEN` (Hiểu đút túi = hoa hồng/lợi nhuận mật)** |
| **Nói giảm nói tránh (Euphemism)** | *"Cho tui xin cái file có chữ ký hai bên với công ty B"* | `Hợp đồng, NDA` | ⚪ Bỏ sót (Không có chữ "hợp đồng") | 🔴 **Bắt `FORBIDDEN` (Hiểu file có chữ ký 2 bên = thỏa thuận pháp lý)** |
| **Hỏi quy mô vốn** | *"Đợt này Sếp duyệt rót bao nhiêu tỷ để anh em chạy marketing?"* | `Ngân sách` | ⚪ Bỏ sót (Không có chữ "ngân sách") | 🔴 **Bắt `FORBIDDEN` (Hiểu duyệt rót tiền = phân bổ ngân sách)** |
| **Câu hỏi chuyên môn hợp lệ** | *"Số lượng màn hình UI cần thiết kế trong Sprint 5 là bao nhiêu?"* | `Lương` | ⚪ An toàn (Không bắt nhầm "lương" trong "số lượng") | 🟢 **`ALLOWED` (Xác định đúng là hỏi số lượng công việc)** |

### 2.4. Cấu trúc Payload gửi sang JEV System One:
```json
{
  "state": "Nội dung câu hỏi của người dùng trong nhóm làm việc: \"Tháng này kế toán đã ting ting mấy chục củ vào tài khoản chưa?\"",
  "model": "jev-latest",
  "questions": {
    "forbidden_intent": {
      "type": "choice",
      "instructions": "Bạn là chuyên gia an ninh thông tin và bảo mật nội bộ. Nhiệm vụ của bạn là kiểm tra xem câu hỏi của người dùng có cố tình tra cứu, hỏi đáp hoặc yêu cầu tiết lộ thông tin liên quan TRỰC TIẾP hoặc GIÁN TIẾP đến bất kỳ chủ đề cấm nào sau đây hay không: [Lương, Bảng lương, Thu nhập]. Chú ý nhận diện cả tiếng lóng, cách nói ẩn ý hoặc vòng vo. Nếu vi phạm, hãy chọn FORBIDDEN. Nếu an toàn, chọn ALLOWED.",
      "criteria": {
        "FORBIDDEN": "Câu hỏi liên quan trực tiếp hoặc gián tiếp đến một trong các chủ đề cấm: Lương, Bảng lương, Thu nhập",
        "ALLOWED": "Câu hỏi thông thường, an toàn, không chứa hoặc không đòi hỏi thông tin thuộc các chủ đề cấm."
      }
    }
  }
}
```

### 2.5. Ngưỡng phân định xác suất (Decision Logic):
Hệ thống xác định vi phạm (`is_forbidden = True`) nếu thỏa mãn một trong các điều kiện sau:
```python
is_forbidden = (
    (choice == "FORBIDDEN" and prob_forbidden >= 0.65)
    or (prob_forbidden >= 0.70)
    or bool(keyword_matched)
)
```

### 2.6. Cơ chế Xử lý Vi phạm (Zero-Response & Mật báo):
1. **Zero-Response (Im lặng tuyệt đối):** Trả về ngay lập tức tại [`server/services/chat_service.py:L359-367`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L359-L367) với `status="forbidden_query"`, `jev_action="IGNORE"`. Bot không phát ngôn vào nhóm, không gọi WeKnora và không gọi Gemini.
2. **Mật báo ngầm tới Sếp:** Nếu câu hỏi phát sinh từ nhóm chat (`channel == "lark_group"`), hệ thống gửi tin DM riêng qua [`server/services/larkServices/lark_messenger.py`](file:///Users/hoainam/Desktop/HiLark/server/services/larkServices/lark_messenger.py):
   ```text
   ⚠️ [CẢNH BÁO BẢO MẬT: TRUY CẬP TRÁI PHÉP]
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   👥 Nhóm chat : [Project 1] Fintech (oc_6c6ee0dc...)
   👤 Thành viên: Cao Phụng (ou_c073866...)
   💬 Câu hỏi   : "Tháng này kế toán đã ting ting mấy chục củ vào tài khoản chưa?"
   🚫 Nhãn cấm  : Lương, Thu nhập
   🛡️ Phản hồi  : Bot đã IM LẶNG HOÀN TOÀN, không phát ngôn vào nhóm.
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```

---

## 🚪 3. PARENT STEP 2: NGƯỜI GÁC CỔNG PHÂN LOẠI Ý ĐỊNH (GATEKEEPER ROUTING)

### 3.1. Vị trí và Vai trò
* **Vị trí trong Pipeline:** [`server/services/chat_service.py:L371-404`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L371-L404)
* **Hàm thực thi:** `JevService.classify_message()` tại [`server/services/jev.py:L18-103`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py#L18-L103)
* **Nhiệm vụ:** Phân tích cấu trúc ngữ nghĩa câu hỏi để định tuyến luồng xử lý thành 1 trong 5 hành động chiến lược.

### 3.2. Tiêu chí 5 Hành động (5-Choice Criteria):
Nằm tại [`server/services/jev.py:L34-40`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py#L34-L40):

| Hành động (`choice`) | Định nghĩa nghiệp vụ | Luồng xử lý tiếp theo |
| :--- | :--- | :--- |
| **`IGNORE`** | Tin rác, chào hỏi xã giao, cảm ơn, tán gẫu không chứa thông tin quan trọng. | Ngắt pipeline ngay, không làm gì cả (tiết kiệm 100% token). |
| **`MEMORY_ONLY`** | Tin nhắn báo cáo tiến độ, cập nhật tài liệu hoặc thông báo sự thật mới, không ai đặt câu hỏi. | Chuyển sang Layer 3 bóc tách Fact/Claim nạp vào MongoDB, **cấm bot trả lời vào nhóm**. |
| **`REPLY_ONLY`** | Câu hỏi nghiệp vụ, tiến độ, phân công, kiến trúc thông thường đã có trong tài liệu. | Tiếp tục truy vấn WeKnora và cho phép Bot tự động trả lời thẳng vào nhóm. |
| **`MEMORY_AND_DRAFT`** | Tin nhắn phức tạp: vừa cập nhật dữ liệu quan trọng vừa có câu hỏi cần phản hồi. | Bóc tách lưu Fact vào Memory + Soạn bản nháp gửi Sếp duyệt (không tự reply). |
| **`DRAFT_PENDING_APPROVAL`** | Câu hỏi đặc biệt nhạy cảm, rủi ro cao, tranh chấp hoặc bí mật kinh doanh. | Soạn nháp và gửi thẻ phê duyệt vào DM của Sếp (Layer 4). |

### 3.3. Ma trận Lọc Độ Tự Tin (Confidence Tuning Engine)
Nằm tại [`server/services/jev.py:L67-98`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py#L67-L98):

```python
prob_draft_risk = probabilities.get("DRAFT_PENDING_APPROVAL", 0.0)
prob_reply = probabilities.get("REPLY_ONLY", 0.0)

# 1. Nếu là MEMORY_AND_DRAFT:
if choice == "MEMORY_AND_DRAFT":
    return {"action": "MEMORY_AND_DRAFT"} if prob_choice >= 0.70 else {"action": "MEMORY_ONLY"}

# 2. Nếu là MEMORY_ONLY:
elif choice == "MEMORY_ONLY":
    return {"action": "MEMORY_ONLY"} if prob_choice >= 0.50 else {"action": "IGNORE"}

# 3. Nếu là REPLY_ONLY (Ưu tiên an toàn):
elif choice == "REPLY_ONLY":
    if prob_draft_risk >= 0.85 and prob_draft_risk > prob_choice:
        return {"action": "DRAFT_PENDING_APPROVAL"} # Ép về Draft nếu rủi ro quá cao
    elif prob_choice >= 0.75:
        return {"action": "REPLY_ONLY"}            # Tự tin trả lời
    else:
        return {"action": "DRAFT_PENDING_APPROVAL"} # Chưa chắc chắn -> Trình Sếp duyệt

# 4. Nếu là DRAFT_PENDING_APPROVAL (Tránh nhát tay quá mức):
elif choice == "DRAFT_PENDING_APPROVAL":
    if prob_choice < 0.60 and prob_reply >= 0.30:
        return {"action": "REPLY_ONLY"}            # Tự tin trả lời thay vì làm phiền Sếp
    return {"action": "DRAFT_PENDING_APPROVAL"}
```

### 3.4. Lá chắn chống lặp vô tận của Chủ nhân (Owner Anti-Loop Shield)
Nằm tại [`server/services/chat_service.py:L382-394`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L382-L394):
* Nếu người phát ngôn trong nhóm chat là **chính Chủ nhân (Sếp)**:
  * Nếu tin có tri thức: Ép sang `MEMORY_ONLY` (chỉ ghi nhận sự thật của Sếp, cấm bot nhảy vào cướp lời Sếp).
  * Nếu tin hỏi đáp / tán gẫu: Ép sang `IGNORE` (ngắt ngay, triệt tiêu 100% nguy cơ bot tự nói chuyện với Sếp gây vòng lặp vô tận).

---

## 🎯 4. PARENT STEP 3: LỌC NGỮ NGHĨA & RERANK RAG (SEMANTIC CHUNK RERANKER)

### 4.1. Vị trí và Vai trò
* **Vị trí trong Pipeline:** [`server/services/chat_service.py:L486-497`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L486-L497)
* **Hàm thực thi:** `JevService.filter_chunks_relevance()` tại [`server/services/jev.py:L104-197`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py#L104-L197)
* **Vấn đề giải quyết:** Tìm kiếm vector (Cosine Similarity) thường trả về các đoạn văn bản có từ vựng tương đồng nhưng thực chất **hoàn toàn lạc đề** hoặc thuộc dự án khác. JEV đóng vai trò là mô hình Cross-Encoder đánh giá lại ngữ nghĩa thực tế.

### 4.2. Chi tiết thực thi Child Logic
```
[Top-K Chunks từ WeKnora]
           │
           ▼
[Child 3.1: Candidate Chunk Pruner] ➔ Lấy tối đa 5 chunks, cắt ngắn 300 ký tự/chunk
           │
           ▼
[Child 3.2: Batch Payload Builder] ➔ Gộp 5 câu hỏi đánh giá vào 1 lượt gọi API JEV duy nhất
           │
           ▼
[Child 3.3: jev_score Assigner] ➔ Bóc tách xác suất RELEVANT, loại bỏ IRRELEVANT
           │
           ▼
[Child 3.4: Cross-Encoder Reranker] ➔ chunks.sort(key=jev_score, reverse=True)
           │
           ▼
[Child 3.5: Graceful Empty Fallback] ➔ Nếu rỗng danh sách thì giữ lại chunks gốc
```

### 4.3. Cấu trúc Payload Batch đa câu hỏi (Multi-Question Batch):
```json
{
  "state": "Bối cảnh: Trợ lý AI đang hỗ trợ giải đáp cho [Project 1] Fintech.\nCâu hỏi của người dùng: \"Cổng thanh toán hỗ trợ phương thức nào?\"",
  "model": "jev-latest",
  "questions": {
    "chunk_1": {
      "type": "choice",
      "instructions": "Đoạn trích 1 từ tài liệu 'fintech_payment_gateway.md': \"Hệ thống hỗ trợ thẻ Visa, Master, Ví MoMo, VNPay và chuyển khoản ngân hàng qua QR Code...\". Đoạn trích này có chứa thông tin phù hợp để tham khảo cho câu hỏi của người dùng không?",
      "criteria": {
        "RELEVANT": "Tài liệu hoặc thông tin hữu ích, liên quan đến bối cảnh dự án để trả lời câu hỏi",
        "IRRELEVANT": "Tài liệu thuộc dự án khác, nội dung lạc đề hoặc tài liệu mẫu không liên quan"
      }
    },
    "chunk_2": {
      "type": "choice",
      "instructions": "Đoạn trích 2 từ tài liệu 'logistics_tracking.md': \"Quy trình vận đơn bao gồm giao nhận kho bãi...\". Đoạn trích này có chứa thông tin phù hợp không?",
      "criteria": {
        "RELEVANT": "Tài liệu hữu ích...",
        "IRRELEVANT": "Tài liệu thuộc dự án khác..."
      }
    }
  }
}
```

### 4.4. Tái sắp xếp (Reranking):
* Đoạn trích được giữ lại nếu `choice == "RELEVANT"` hoặc `jev_score >= 0.5`.
* Các đoạn đạt chuẩn được sắp xếp theo thứ tự giảm dần:
  ```python
  relevant_chunks.sort(key=lambda x: x.get("jev_score", 0.0), reverse=True)
  ```
* Đoạn trích có điểm sát nghĩa nhất sẽ nằm ở vị trí số 1 (`chunk[0]`) để khi nạp vào Gemini ở Layer 4, câu trả lời đạt độ chính xác cao nhất.

---

## 🛡️ 5. KHẢ NĂNG CHỐNG CHỊU LỖI & PHỤC HỒI MẠNG (RESILIENCE & FAILOVER)

Tại cả 3 trạm kiểm soát, JEV đều được bọc các khối `try...except` và cơ chế phòng vệ suy thoái (Graceful Degradation):

| Trạm kiểm soát | Tình huống sự cố | Cơ chế phục hồi tự động (Fail-safe) |
| :--- | :--- | :--- |
| **Trạm 1: Nhãn cấm** | Mất kết nối JEV API hoặc thiếu API Key | Tự động kích hoạt `keyword_matched` fallback: nếu câu hỏi chứa từ khóa cấm $\rightarrow$ vẫn chặn thành công 100%. |
| **Trạm 2: Phân loại ý định** | JEV timeout (quá 30s) hoặc HTTP 500 | Tự động kiểm tra cú pháp: Nếu câu hỏi có dấu `?` hoặc độ dài $\ge 4$ từ $\rightarrow$ Ép sang `DRAFT_PENDING_APPROVAL` (Gửi Sếp duyệt, tuyệt đối không tự ý phát ngôn bậy). |
| **Trạm 3: Lọc Chunks RAG** | JEV lọc quá tay (loại hết sạch) hoặc lỗi mạng | Tự động giữ nguyên toàn bộ danh sách chunks ban đầu từ WeKnora để chu trình RAG không bị gián đoạn. |

---

## 📊 6. BẢNG TỔNG HỢP THAM SỐ CẤU HÌNH & NGƯỠNG SỐ HỌC

| Tham số / Ngưỡng | Vị trí định nghĩa | Giá trị mặc định | Giải thích nghiệp vụ |
| :--- | :--- | :---: | :--- |
| `max_snippet_chars` | [`server/services/jev.py:L108`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py#L108) | `300` | Số ký tự tối đa của mỗi đoạn trích gửi sang JEV để tiết kiệm token và tăng tốc độ xử lý. |
| `candidate_chunks_limit` | [`server/services/jev.py:L126`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py#L126) | `5` | Số lượng chunks tối đa gửi trong 1 batch đánh giá. |
| `prob_forbidden_threshold` | [`server/services/jev.py:L355`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py#L355) | `0.70` | Ngưỡng xác suất vi phạm nhãn cấm để kích hoạt Zero-response. |
| `prob_draft_escalation` | [`server/services/jev.py:L86`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py#L86) | `0.85` | Ngưỡng rủi ro để tự động cưỡng chế chuyển `REPLY_ONLY` thành `DRAFT`. |
| `prob_reply_confidence` | [`server/services/jev.py:L88`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py#L88) | `0.75` | Độ tự tin tối thiểu để cho phép bot tự động trả lời thẳng vào nhóm. |
