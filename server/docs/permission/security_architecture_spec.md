# Đặc tả Kỹ thuật An ninh & Phân quyền Dữ liệu

Tài liệu này ghi lại chi tiết các giải pháp kỹ thuật, cơ chế phòng thủ 5 tầng và ma trận đối ứng an ninh trong HiLark Server.

Mã nguồn liên quan:
- Cổng phân quyền REST: [`server/routers/scope.py`](file:///Users/hoainam/Desktop/HiLark/server/routers/scope.py)
- Quản lý phạm vi nhóm chat: [`server/services/knowledge/chat_scopes.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/chat_scopes.py)
- Chốt chặn an toàn JEV: [`server/services/ai/jev_classifier.py`](file:///Users/hoainam/Desktop/HiLark/server/services/ai/jev_classifier.py)
- Kiểm duyệt quy tắc: [`server/services/knowledge/rule_engine.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/rule_engine.py)
- Quy trình bản nháp: [`server/services/workflows/draft_workflow.py`](file:///Users/hoainam/Desktop/HiLark/server/services/workflows/draft_workflow.py)
- Thẻ tương tác nút bấm: [`server/services/lark/card_builder.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/card_builder.py)

---

## 1. Nguyên lý thiết kế & Mô hình 5 tầng phòng thủ

Kiến trúc an ninh của HiLark giải quyết bài toán: bảo đảm Trợ lý AI hoạt động an toàn trên nhiều nhóm chat doanh nghiệp mà không bị rò rỉ dữ liệu chéo, không bị prompt injection và không vô tình tiết lộ thông tin bảo mật nội bộ.

Hệ thống triển khai mô hình Phòng thủ Chiều sâu 5 Tầng:

```
[Người dùng nhắn tin từ Lark]
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. TẦNG 1: RBAC & IDENTITY GOVERNANCE                       │
│    • Phân định Quản trị viên (Owner/Admin) vs Thành viên   │
│    • Whitelist Open IDs: settings.LARK_USER_OPEN_ID         │
│    • Thin Controller: routers/scope.py (403 Forbidden)      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. TẦNG 2: GROUP SCOPE & HARD DATA ISOLATION                │
│    • ChatScopeRecord (MongoDB collection 'chat_scopes')     │
│    • WeKnora: Chỉ tìm kiếm trong 'dataset_id' của nhóm      │
│    • Claims: MongoDB Query lọc theo chat_id và tenant_key   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. TẦNG 3: KIỂM SOÁT Ý ĐỊNH ĐẦU VÀO (LAYER 2 GATING)        │
│    • TextFilter: Lọc ký tự lạ, chặn flood lặp, 2-1000 từ   │
│    • Group Status: is_active == False -> Ngắt pipeline ngay │
│    • JEV Forbidden Intent: NLU bắt tiếng lóng/hỏi vòng vo   │
│    • Phản xạ kép: Zero-Response (im lặng) + Thẻ nháp gửi DM │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. TẦNG 4: CHỐT CHẶN AN NINH TRI THỨC (LAYER 3 RULE ENGINE) │
│    • Unified Rule Engine: Lọc tất định In-Memory (0ms, 0$)  │
│    • Tầng 1: Canonical Property Mapping (budget, salary...) │
│    • Tầng 2: Vietnamese Word-Boundary Regex Matcher         │
│    • Line-level Redaction che thông tin bảo mật             │
│    • Safety RAG Gate: KB rỗng -> Downgrade DRAFT            │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. TẦNG 5: KIỂM SOÁT ĐẦU RA & HUMAN-IN-THE-LOOP (LAYER 4)   │
│    • Strict Confidential: Nhóm bảo mật cao -> Zero Auto-reply│
│    • Owner Anti-Loop Shield: Cấm bot tự reply Quản trị viên │
│    • Interactive Card Approval: Duyệt qua nút 1-chạm        │
│    • TextFilter Output Scrubbing: Xóa sạch technical tokens │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Tầng 1: Quản trị danh tính & Phân quyền vai trò (RBAC)

### 2.1. Phân định vai trò hệ thống
Hệ thống phân định người dùng thành 2 vai trò cơ bản:
- **Quản trị viên (Owner / Admin):**
  - Quyền điều chỉnh liên kết Knowledge Base (`set-kb`, `reset-kb`).
  - Quyền duyệt Thẻ Master Daily Digest và thăng hạng sự thật lên WeKnora.
  - Quyền nhận và phê duyệt các Thẻ nháp trả lời (HITL Draft Cards).
  - Được miễn áp dụng thời gian chờ giãn cách (cooldown = 0s).
- **Thành viên (Team Member):**
  - Quyền tra cứu tài liệu được phân quyền trong nhóm chat.
  - Mọi thông tin cung cấp trong chat chỉ được lưu ở trạng thái `proposed` (chờ Quản trị viên duyệt).
  - Không có quyền thay đổi cấu hình Knowledge Base hoặc nhận thẻ phê duyệt.

### 2.2. Kiểm soát tại cổng REST Controller
Các API quản trị liên kết tri thức tại `server/routers/scope.py` được bảo vệ bởi hàm kiểm tra thẩm quyền:
```python
if not scope_service.is_admin_user(operator_open_id):
    raise HTTPException(status_code=403, detail="Chỉ Quản trị viên mới có quyền thao tác.")
```

---

## 3. Tầng 2: Cách ly dữ liệu cấp nhóm (Hard Data Isolation)

### 3.1. Phân vùng kho tài liệu WeKnora
Mỗi nhóm chat được ánh xạ cố định tới một hoặc nhiều `dataset_id` trong WeKnora. Khi thực hiện tìm kiếm, tham số truy vấn bắt buộc phải chỉ định danh sách này:
```python
chunks = await weknora_service.retrieve(
    query=retrieval_query,
    knowledge_base_ids=target_kbs,
    knowledge_ids=target_knowledge_ids,
    match_count=retrieve_count,
)
```
Không có cơ chế tìm kiếm toàn cục xuyên qua các nhóm chat khác nhau.

### 3.2. Phân vùng ký ức động MongoDB Claims
Mọi truy vấn lấy mệnh đề sự thật từ collection `claims` đều áp dụng bộ lọc bắt buộc theo `tenant_key` và `chat_id`:
```python
query = {
    "tenant_key": eff_tenant,
    "$or": [
        {"chat_id": chat_id},
        {"scope_type": "global"}
    ],
    "status": "current"
}
```
Ngăn chặn hoàn toàn tình trạng hiển thị sự thật của dự án này sang dự án khác.

---

## 4. Tầng 3: Kiểm soát ý định đầu vào (Input Security Gating)

### 4.1. Bộ lọc cú pháp (Syntactic Sanitizer)
- Chặn các câu hỏi rác hoặc spam ký tự trước khi tốn tài nguyên mạng.
- Giới hạn độ dài từ 2 đến 1.000 từ.

### 4.2. Quét vùng cấm JEV (Forbidden Intent Gating)
- Kết hợp Regex nhanh (< 0.1ms) và phân tích ngữ nghĩa qua JEV API.
- Phát hiện các câu hỏi liên quan đến bảng lương, ngân sách, chi phí hoặc hợp đồng mật kể cả khi sử dụng tiếng lóng hoặc diễn đạt gián tiếp.
- Hành vi khi vi phạm: Zero-Response (im lặng trong nhóm chat) + Soạn Thẻ nháp gửi riêng Quản trị viên.

---

## 5. Tầng 4: Chốt chặn an ninh tri thức (Rule Engine In-Memory)

### 5.1. Thực thi In-Memory trước khi gọi AI
Rule Engine được thực thi trực tiếp trên RAM (độ trễ 0ms) ngay sau khi WeKnora và MongoDB trả về dữ liệu thô:
- **Canonical Property Mapping:** Ánh xạ nhãn tiếng Việt trên Lark Base sang tập thuộc tính chuẩn tiếng Anh (`budget`, `salary`, `contract`).
- **Word-Boundary Regex Matcher:** Quét biên từ Unicode có dấu và không dấu, loại trừ bắt nhầm từ nghiệp vụ thông thường.
- **Line-level Redaction:** Che các dòng chứa số liệu bảo mật mà vẫn giữ nguyên các dòng mô tả quy trình nghiệp vụ xung quanh.

### 5.2. Safety RAG Gate (Hạ cấp an toàn khi rỗng bối cảnh)
Nếu sau quá trình thanh lọc, toàn bộ chunks và claims đều bị loại bỏ do vi phạm nhãn cấm:
```python
if jev_action == "REPLY_ONLY" and not clean_chunks and not clean_claims:
    jev_action = "DRAFT_PENDING_APPROVAL"
```
Hệ thống cấm bot tự trả lời vào nhóm, ép chuyển thành Thẻ nháp gửi Quản trị viên xem xét.

---

## 6. Tầng 5: Kiểm soát phát ngôn & Human-in-the-Loop (HITL)

### 6.1. Chế độ bảo mật cao (Strict Confidential)
Nếu nhóm chat được đánh dấu `security_level == "confidential"`, bot bị khóa 100% quyền tự động phát ngôn. Mọi câu hỏi đều được chuyển thành bản nháp gửi Quản trị viên phê duyệt.

### 6.2. Chống vòng lặp phản hồi từ Quản trị viên (Owner Anti-Loop Shield)
Khi Quản trị viên phát ngôn trong nhóm chat, tin nhắn được phân luồng tự động về `MEMORY_ONLY` (nếu là cập nhật công việc) hoặc `IGNORE` (nếu là chào hỏi), triệt tiêu hoàn toàn nguy cơ bot xen ngang lời nói của Quản trị viên.

### 6.3. Quy trình duyệt nháp qua Thẻ tương tác (HITL Draft Card)
Bản nháp `PendingDraft` được lưu trữ gắn với `tenant_key` và `owner_id`. Quản trị viên điều khiển trực tiếp qua các nút bấm 1-chạm trên Thẻ tương tác trong tin nhắn riêng:
1. `[Duyệt và gửi]`: Bắn câu trả lời ngay vào nhóm chat dưới danh nghĩa Quản trị viên và cập nhật trạng thái thẻ.
2. `[Nhờ AI sửa lại]`: Mở modal nhập yêu cầu chỉ đạo, LLM viết lại nội dung và cập nhật thẻ tại chỗ.
3. `[Tự sửa]`: Mở form chỉnh sửa văn bản trực tiếp trên giao diện Lark.
4. `[Hủy bỏ]`: Hủy bản nháp an toàn, bot tiếp tục giữ im lặng.

---

## 7. Ma trận đối ứng nguy cơ an ninh (Threat Matrix)

| Nguy cơ bảo mật | Tình huống tấn công | Chốt chặn đối ứng | Kết quả an ninh |
| :--- | :--- | :--- | :--- |
| **Dò hỏi trực tiếp chủ đề cấm** | Hỏi: *"Bảng lương của anh em dev tháng này?"* | Tầng 3 (JEV Forbidden Intent) | Im lặng trong nhóm + Chuyển Thẻ nháp gửi Quản trị viên. |
| **Dùng tiếng lóng / Hỏi né từ** | Hỏi: *"Kế toán đã ting ting mấy chục củ chưa?"* | Tầng 3 (JEV Semantic Scan) | Bắt nhãn FORBIDDEN, bot giữ im lặng tuyệt đối. |
| **Đọc tài liệu dự án khác** | Hỏi tài liệu Dự án B trong nhóm Dự án A | Tầng 2 (RAG Hard Isolation) | WeKnora chỉ tìm trong dataset_id của nhóm A. |
| **Đọc dữ kiện thực tế khác** | Hỏi deadline/tiến độ mật của dự án khác | Tầng 2 (Claims Hard Scoping) | Query MongoDB chỉ trả về Claims của chat_id này. |
| **Rò rỉ dữ liệu mật trong file** | Tài liệu hợp lệ có chứa phụ lục chi phí | Tầng 4 (Rule Engine) | Line-level Redaction che số liệu mật trước khi gửi LLM. |
| **AI phỏng đoán khi thiếu dữ liệu** | Kho tri thức rỗng sau khi lọc sạch | Tầng 4 (Safety RAG Gate) | Cấm bot tự trả lời, ép chuyển sang Thẻ nháp. |
| **Nhóm dự án chiến lược** | Nhóm làm việc diện NDA công ty | Tầng 5 (Strict Confidential) | Khóa 100% tự động phát ngôn, ép toàn bộ sang Thẻ nháp. |
| **Vòng lặp bot vô tận** | Bot đọc tin nhắn của Quản trị viên rồi reply lại | Tầng 5 (Owner Anti-Loop Shield) | Ép REPLY sang IGNORE, triệt tiêu vòng lặp tự phản hồi. |
| **Gỡ liên kết KB trái phép** | Gửi REST request `DELETE /api/v1/scopes/{chat_id}` | Tầng 1 (REST RBAC Guard) | Trả về 403 Forbidden, ghi log cảnh báo an ninh. |
