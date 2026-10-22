# 📘 SPEC KỸ THUẬT LAYER 2: VỌNG GÁC AN NINH & PHÂN LOẠI Ý ĐỊNH
> **Dự án HiLark Server** — Bản đặc tả kỹ thuật chi tiết (Spec), đối chiếu mã nguồn thực tế, ưu tiên tiếng Việt, không dùng từ ngữ bóng bẩy.

---

## 🧭 1. TỔNG QUAN LAYER 2 TRONG TOÀN BỘ PIPELINE

Trong quy trình xử lý hội thoại (`process_chat_pipeline`), **Layer 2** đảm nhận toàn bộ giai đoạn từ lúc tiếp nhận câu hỏi thô từ Layer 1 cho đến khi đưa ra quyết định hành động (`jev_action`):

```
Layer 1 (Chat Queue / Handoff)
           │
           ▼
[1. text_filter.validate_and_clean()] ──(Lỗi độ dài / rác)──> Trả về 'invalid_input' (Dừng)
           │
           ▼
[2. scope_service.get_scope_by_chat_id()]
           │
           ├──(is_active == False)──────────────────────────> Trả về 'group_inactive' (Dừng)
           │
           ▼
[3. jev_service.check_forbidden_query()]
           │
           ├──(is_forbidden == True)────────────────────────> ZERO-RESPONSE + DM Alert cho Sếp (Dừng)
           │
           ▼
[4. jev_service.classify_message()]
           │
           ├──(is_owner == True trong Group)────────────────> OWNER ANTI-LOOP SHIELD
           │
           ▼
[5. Quyết định định tuyến hành động]:
    ├── IGNORE                 ──> Kết thúc ngay (Bỏ qua)
    ├── MEMORY_ONLY            ──> process_memory_extraction() -> Lưu MongoDB -> Kết thúc
    ├── REPLY_ONLY             ──> Chuyển tiếp sang Layer 3 (RAG) & Layer 4 (LLM QA)
    ├── MEMORY_AND_DRAFT       ──> Lưu MongoDB + Soạn draft chờ duyệt qua DM
    └── DRAFT_PENDING_APPROVAL ──> Chuyển sang Layer 3 & 4 để soạn draft chờ Sếp duyệt
```

---

## 🖼️ SƠ ĐỒ PHÂN RÃ THÀNH PHẦN LAYER 2

![Sơ đồ phân rã thành phần Lớp 2 thuần Việt](/Users/hoainam/.gemini/antigravity-ide/brain/7757b940-33a0-4b24-b567-26c89fe134f7/phan_ra_thanh_phan_lop_2_1792418349814.jpg)

---

## 🧩 2. BẢNG PHÂN RÃ CÁC MODULE THUỘC LAYER 2

> 💡 **Tài liệu bóc tách chi tiết:** Xem tại thư mục [`ultis_docs/`](file:///Users/hoainam/Desktop/HiLark/server/docs/layer2/ultis_docs/README.md) gồm: [`text_filter.md`](file:///Users/hoainam/Desktop/HiLark/server/docs/layer2/ultis_docs/text_filter.md) và sơ đồ quan hệ phân cấp Parent-Child.

| Module | Đường dẫn file | Vai trò chính | Lớp / Hàm phụ trách |
| :--- | :--- | :--- | :--- |
| **Module 1: Dọn rác văn bản** | [`server/utils/text_filter.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py) | Làm sạch ký tự lạ, chuẩn hóa khoảng trắng, kiểm tra giới hạn từ (2–1000 từ). | `TextFilter.validate_and_clean()` |
| **Module 2: Quản lý phạm vi & Nhãn cấm** | [`server/services/scope_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/scope_service.py) | Đọc trạng thái hoạt động, mức độ bảo mật và danh sách nhãn cấm từ MongoDB `chat_scopes`. | `ScopeService.get_scope_by_chat_id()` |
| **Module 3: Mô hình phân quyền JEV** | [`server/services/jev.py`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py) | Gọi JEV System One API để kiểm tra chủ đề cấm và phân loại 5 hành động của tin nhắn. | `JevService.check_forbidden_query()`<br/>`JevService.classify_message()` |
| **Module 4: Bộ điều phối & Ra quyết định** | [`server/services/chat_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py) | Chốt chặn an ninh, điều phối luồng, kích hoạt cảnh báo mật và khiên chống lặp của Sếp. | `process_chat_pipeline()` (L264–L437) |

---

## 🔬 3. CHI TIẾT KỸ THUẬT TỪNG CHỐT CHẶN (CODE-LEVEL)

### Chốt chặn 1: Dọn dẹp ký tự & Kiểm tra kích thước (Syntactic Sanitizer)
- **Vị trí mã nguồn:** [`server/utils/text_filter.py:L19-37`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py#L19-L37)
- **Đầu vào:** `query: str`
- **Xử lý:**
  1. Kiểm tra chuỗi rỗng: Nếu `not text or not text.strip()` $\rightarrow$ Ném `ValueError("Tin nhắn không được để trống.")`.
  2. Lọc chuỗi ký tự lặp bằng biểu thức chính quy (Regex):
     ```python
     cleaned = re.sub(r'([!@#$%^&*?])\1+', r'\1', text)
     cleaned = re.sub(r'\s+', ' ', cleaned).strip()
     ```
  3. Kiểm tra số lượng từ:
     * `MIN_WORDS = 2`: Chặn các tin nhắn cộc lốc ("alo", "?", "hey").
     * `MAX_WORDS = 1000` (~1300 tokens): Chặn tấn công quá tải văn bản.
- **Kết quả trả về nếu lỗi:**
  ```python
  return {
      "status": "invalid_input",
      "jev_action": "IGNORE",
      "jev_confidence": 0.0,
      "message": str(e)
  }
  ```

---

### Chốt chặn 2: Tra cứu phạm vi nhóm & Kiểm tra trạng thái hoạt động
- **Vị trí mã nguồn:** [`server/services/chat_service.py:L293-321`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L293-L321)
- **Truy vấn:** `scope_record = await scope_service.get_scope_by_chat_id(chat_id)`
- **Logic kiểm tra:**
  ```python
  if scope_record and not scope_record.is_active:
      logger.info(f"🛑 [GROUP INACTIVE] Nhóm '{scope_record.chat_name}' đang ở trạng thái '{scope_record.status}'. Bỏ qua hoàn toàn tin nhắn.")
      return {
          "status": "group_inactive",
          "jev_action": "IGNORE",
          "jev_confidence": 1.0,
          "answer": None,
          "message": f"Nhóm chat đang ở trạng thái '{scope_record.status}'. Bot tạm dừng phản hồi."
      }
  ```
- **Ý nghĩa:** Cho phép quản trị viên tắt bot tạm thời trong nhóm mà không cần gỡ bot ra khỏi nhóm Lark.

---

### Chốt chặn 3: Kiểm soát nhãn cấm (Forbidden Intent Gating & Zero-Response)
- **Vị trí mã nguồn:** [`server/services/jev.py:L198-388`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py#L198-L388) và [`server/services/chat_service.py:L324-370`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L324-L370)
- **Danh sách nhãn cấm:** Lấy từ `scope_record.forbidden_labels` (ví dụ: `["Ngân sách", "Bảng lương", "Chi phí", "Hợp đồng"]`).
- **Cơ chế kiểm tra 2 lớp:**
  1. **Lớp 1 (Fast Keyword Match):** So khớp trực tiếp `lbl.lower() in query.lower()`. Nếu trùng từ khóa $\rightarrow$ Đánh dấu vi phạm ngay với `confidence = 1.0`.
  2. **Lớp 2 (Deep Semantic Check qua JEV System One):** Gửi payload sang JEV API phân tích ngữ nghĩa câu hỏi.
- **Cấu trúc Payload gửi tới JEV System One:**
  ```json
  {
    "state": "Nội dung câu hỏi của người dùng trong nhóm làm việc: \"...\"",
    "model": "jev-latest",
    "questions": {
      "forbidden_intent": {
        "type": "choice",
        "instructions": "Kiểm tra xem câu hỏi có cố tình tra cứu hoặc yêu cầu tiết lộ thông tin liên quan đến các chủ đề cấm sau hay không: [Ngân sách, Bảng lương...]",
        "criteria": {
          "FORBIDDEN": "Câu hỏi liên quan trực tiếp hoặc gián tiếp đến chủ đề cấm",
          "ALLOWED": "Câu hỏi thông thường, an toàn"
        }
      }
    }
  }
  ```
- **Quy tắc xác định vi phạm (`is_forbidden`):**
  * `(choice == "FORBIDDEN" and prob_forbidden >= 0.65)` HOẶC `prob_forbidden >= 0.70` HOẶC có từ khóa khớp trực tiếp.
- **Cơ chế phản hồi khi vi phạm:**
  * **Im lặng tuyệt đối (Zero-response):** Trả về `status="forbidden_query"`, `jev_action="IGNORE"`.
  * **Mật báo ngầm:** Nếu câu hỏi đến từ nhóm (`channel == "lark_group"`), gửi tin nhắn riêng cho Sếp qua `lark_service.send_bot_dm_to_owner(alert_text)`.

---

### Chốt chặn 4: Người gác cổng phân loại ý định (JEV Gatekeeper)
- **Vị trí mã nguồn:** [`server/services/jev.py:L18-103`](file:///Users/hoainam/Desktop/HiLark/server/services/jev.py#L18-L103)
- **API Endpoint:** `POST https://api.typesafe.ai/v1/systemone`
- **5 Nhãn phân loại chính:**
  1. `IGNORE`: Tin nhắn rác, chào hỏi, tán gẫu không quan trọng.
  2. `MEMORY_ONLY`: Báo cáo tiến độ, cập nhật thông tin cần lưu trữ nhưng không ai đặt câu hỏi.
  3. `REPLY_ONLY`: Câu hỏi nghiệp vụ thông thường cần tra cứu tài liệu và trả lời ngay.
  4. `MEMORY_AND_DRAFT`: Vừa có thông tin quan trọng cần nhớ, vừa có câu hỏi cần phản hồi.
  5. `DRAFT_PENDING_APPROVAL`: Câu hỏi đặc biệt nhạy cảm hoặc nhóm có chính sách bảo mật cao.

#### Bảng ma trận điều chỉnh độ tự tin (Confidence Calibrator):
Để tránh tình trạng bot bị "ảo giác" hoặc quá thận trọng, JEV áp dụng bộ lọc xác suất thực nghiệm:

| Nhãn JEV đề xuất | Điều kiện xác suất áp dụng | Hành động thực tế cuối cùng | Lý do kỹ thuật |
| :--- | :--- | :---: | :--- |
| `MEMORY_AND_DRAFT` | `prob >= 0.70` | `MEMORY_AND_DRAFT` | Đủ độ tin cậy để vừa lưu vừa tạo nháp. |
| `MEMORY_AND_DRAFT` | `prob < 0.70` | `MEMORY_ONLY` | Hạ cấp xuống chỉ ghi nhớ, tránh tạo nháp rác cho Sếp. |
| `MEMORY_ONLY` | `prob >= 0.50` | `MEMORY_ONLY` | Ghi nhận sự kiện cập nhật tiến độ. |
| `MEMORY_ONLY` | `prob < 0.50` | `IGNORE` | Xác suất quá thấp, coi như tán gẫu. |
| `REPLY_ONLY` | `prob_draft_risk >= 0.85` | `DRAFT_PENDING_APPROVAL` | Rủi ro nhạy cảm quá cao, chuyển sang chờ duyệt. |
| `REPLY_ONLY` | `prob >= 0.75` | `REPLY_ONLY` | Đủ tin cậy để trả lời tự động vào nhóm. |
| `REPLY_ONLY` | `prob < 0.75` | `DRAFT_PENDING_APPROVAL` | Chưa chắc chắn, chuyển sang chờ duyệt cho an toàn. |
| `DRAFT_PENDING_APPROVAL` | `prob < 0.60` và `prob_reply >= 0.30` | `REPLY_ONLY` | Bỏ qua cảnh báo ảo, ưu tiên trải nghiệm trả lời mượt mà. |

---

### Chốt chặn 5: Khiên chống lặp của Chủ nhân (Owner Anti-Loop Shield)
- **Vị trí mã nguồn:** [`server/services/chat_service.py:L382-394`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L382-L394)
- **Điều kiện kích hoạt:** `is_owner == True` và `channel == "lark_group"`
- **Hành vi ép nhãn:**
  ```python
  if is_owner and channel == "lark_group":
      if jev_action in ("MEMORY_ONLY", "MEMORY_AND_DRAFT"):
          # Chủ nhân nói câu có dữ liệu/quyết định: Âm thầm học, tuyệt đối KHÔNG trả lời lại Sếp
          jev_action = "MEMORY_ONLY"
      else:
          # Chủ nhân hỏi thăm/tán gẫu: Bỏ qua hoàn toàn, không chen ngang lời Sếp
          jev_action = "IGNORE"
  ```
- **Tác dụng:**
  1. Ngăn chặn 100% việc bot nhảy vào nhóm tranh lời hoặc cãi lại Chủ nhân.
  2. Triệt tiêu vòng lặp phản hồi vô tận giữa Bot và tài khoản đại diện của Sếp.

---

### Chốt chặn 6: Cơ chế an toàn khi mất mạng hoặc API lỗi (Graceful Fallback)
- **Vị trí mã nguồn:** [`server/services/chat_service.py:L376-380`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L376-L380)
- **Xử lý ngoại lệ khi gọi JEV gặp lỗi/timeout:**
  ```python
  except Exception as e:
      logger.error(f"Lỗi phân loại JEV: {e}")
      # [SAFETY] Tuyệt đối không tự ý phát ngôn vào nhóm khi lỗi mạng
      jev_action = "DRAFT_PENDING_APPROVAL" if ("?" in clean_query or len(clean_query.split()) >= 4) else "IGNORE"
      jev_confidence = 0.0
  ```
- **Triết lý:** Trong trường hợp sự cố hạ tầng, thà chuyển câu hỏi vào hòm thư nháp để Sếp duyệt tay, còn hơn để bot tự ý phát ngôn sai lệch trong nhóm khách hàng hay dự án.

---

## ⚙️ 4. BẢNG CẤU HÌNH & THAM SỐ TOÀN DIỆN CỦA LAYER 2

| Biến cấu hình / Trường dữ liệu | Thuộc tính | Giá trị mặc định | Giải thích chi tiết |
| :--- | :--- | :---: | :--- |
| `MIN_WORDS` | [`utils/text_filter.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py#L13) | `2` | Số lượng từ tối thiểu để được coi là tin nhắn hợp lệ. |
| `MAX_WORDS` | [`utils/text_filter.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py#L14) | `1000` | Số lượng từ tối đa (~1300 tokens) để chống tràn bộ nhớ. |
| `JEV_API_KEY` | `.env` (`jev_api`) | Khóa API bí mật | Dùng để xác thực với cổng JEV System One. |
| `status` | MongoDB `chat_scopes` | `"Hoạt động"` | Điều khiển tắt/bật quyền phản hồi của bot theo từng nhóm. |
| `security_level` | MongoDB `chat_scopes` | `"Nội bộ"` | Nếu đặt `"Tuyệt mật"`, bot khóa 100% tự động reply, ép sang gửi nháp. |
| `forbidden_labels` | MongoDB `chat_scopes` | `[]` | Mảng danh sách các chủ đề cấm xem của nhóm (ngân sách, bảng lương...). |
| `LARK_USER_OPEN_ID` | `.env` | `ou_xxx` | Open ID của Chủ nhân máy chủ để nhận cảnh báo mật và bản nháp duyệt. |

---

## 🎯 5. KẾT LUẬN & ĐIỂM CHUYỂN GIAO SANG LAYER 3

Sau khi đi qua Layer 2:
* Nếu là **`IGNORE`** $\rightarrow$ Dừng quy trình, không tiêu tốn thêm tài nguyên.
* Nếu là **`MEMORY_ONLY`** $\rightarrow$ Kích hoạt `process_memory_extraction()` để trích xuất thực thể & mệnh đề vào MongoDB và kết thúc.
* Nếu là **`REPLY_ONLY`**, **`DRAFT_PENDING_APPROVAL`** hoặc **`MEMORY_AND_DRAFT`** $\rightarrow$ Dữ liệu đã được chứng nhận an toàn, chính thức bàn giao sang **Layer 3: Truy xuất tri thức & Hợp nhất bối cảnh (WeKnora RAG + MongoDB Claims + ContextComposer)**.
