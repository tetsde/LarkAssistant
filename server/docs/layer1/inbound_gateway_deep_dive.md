# Đặc tả Kỹ thuật Lớp 1: Cổng tiếp nhận & Điều tiết tin nhắn

Tài liệu này phân tích chi tiết cấu trúc kỹ thuật, thành phần mã nguồn và quy trình xử lý của Lớp 1 (Inbound Gateway & Dispatcher) trong HiLark Server.

Mã nguồn liên quan:
- Cổng tiếp nhận Webhook: [`server/routers/lark.py`](file:///Users/hoainam/Desktop/HiLark/server/routers/lark.py)
- Bộ điều phối sự kiện: [`server/services/lark/dispatcher.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/dispatcher.py)
- Bộ handlers chuyên biệt: [`server/services/lark/handlers/`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/handlers/)
- Điều phối hàng đợi: [`server/services/workflows/chat_workflow.py`](file:///Users/hoainam/Desktop/HiLark/server/services/workflows/chat_workflow.py)

---

## 1. Trách nhiệm của Lớp 1

1. **Tiếp nhận sự kiện:** Nhận webhook từ Lark Open Platform tại `/api/lark/events`, thiết lập Scoped Execution Context theo `tenant_key`.
2. **Khử trùng lặp & Chống vòng lặp:** Khử các tin nhắn trùng, tin nhắn từ Bot khác và tin nhắn do chính hệ thống phát ra.
3. **Lưu trữ vùng đệm (Staging):** Lưu bản ghi vào MongoDB `conversation_staging` phục vụ tổng hợp báo cáo ngày.
4. **Phân luồng sự kiện:** Chuyển tiếp tới các handler chuyên biệt:
   - Tin nhắn thành viên nhóm chat (`member_message_handler.py`)
   - Tệp đính kèm và tài liệu (`document_handler.py`)
   - Bấm nút trên thẻ tương tác (`card_action_handler.py`)
   - Vòng đời cài đặt tenant (`tenant_lifecycle_handler.py`)
5. **Gom ngắt dòng (Debounce):** Ghép các dòng gõ ngắt quãng của cùng một người thành một câu hoàn chỉnh (1.75 giây).
6. **Điều tiết tốc độ (Cooldown):** Áp dụng giãn cách 4.0 giây giữa 2 câu hỏi liên tiếp của cùng một người (Quản trị viên 0 giây).
7. **Khống chế tải đồng thời (Semaphore):** Giới hạn tối đa 3-5 pipeline chạy đồng thời, bảo vệ bộ nhớ và tránh lỗi HTTP 429 từ các nhà cung cấp LLM.

---

## 2. Sơ đồ luồng hoạt động Lớp 1

```
Lark Open Platform
(Webhook /api/lark/events)
         │
         ▼
┌──────────────────────────────────────────────┐
│  server/services/lark/dispatcher.py          │
│  LarkDispatcher                              │
│  • Trích xuất tenant_key & Scoped Context    │
│  • parse_event() -> LarkMessage              │
│  • Lọc: is_bot / is_self / is_duplicate      │
│  • Dedup Cache: 1.000 msg_id x 10 phút       │
└──────────────────────┬───────────────────────┘
                       │
       ┌───────────────┴───────────────┐
       ▼                               ▼
[Sự kiện Thẻ Card Action]       [Sự kiện Tin nhắn]
       │                               │
card_action_handler.py                 ├─► Lưu staging MongoDB (conversation_staging)
                                       ▼
                       ┌───────────────────────────────┐
                       │  chat_workflow.py             │
                       │  • MessageDebouncer (1.75s)   │
                       │  • CooldownQueue (4.0s)       │
                       │  • ConcurrencySemaphore(3)    │
                       └───────────────┬───────────────┘
                                       │
                                       ▼
                         Bàn giao sang Lớp 2 (JEV)
```

---

## 3. Phân rã các thành phần mã nguồn

### Thành phần 1: Bộ điều phối trung tâm (`server/services/lark/dispatcher.py`)

- **Nhiệm vụ:** Nhận raw event JSON từ endpoint `/api/lark/events`, chuẩn hóa thành đối tượng `LarkMessage` và phân loại luồng.
- **Khử trùng lặp (Deduplication):** Sử dụng `OrderedDict` làm bộ đệm RAM lưu tối đa 1.000 `message_id` gần nhất kèm thời điểm nhận. Tin nhắn lặp lại trong vòng 10 phút sẽ bị loại bỏ với log cảnh báo.
- **Chống tự phản hồi:** Khi hệ thống gửi tin nhắn vào nhóm nhân danh tài khoản cá nhân của Quản trị viên (`as_user=True`), Lark sẽ bắn ngược sự kiện về webhook. Hệ thống kiểm tra `message_id` có trong danh sách vừa phát (`_sent_message_ids`) để ngắt xử lý ngay lập tức.

### Thành phần 2: Xử lý tài liệu (`server/services/lark/handlers/document_handler.py`)

- **Nhiệm vụ:** Xử lý các tin nhắn chứa file đính kèm hoặc liên kết tài liệu.
- **Xử lý tệp nhị phân:** Tải tệp `.docx`, `.pdf`, `.xlsx`, `.pptx` và chuyển tới `WeKnora-docreader:50051` qua gRPC để bóc tách thành Markdown cấu trúc.
- **Xử lý Lark DocX / Wiki URL:** Gọi Lark OpenAPI đọc trực tiếp Markdown, hoàn toàn không tốn token LLM.
- **Quét đệ quy thư mục Drive:** Hỗ trợ quét toàn bộ cây thư mục tài liệu dự án để nạp vào kho tri thức của nhóm chat.
- **MD5 Hash Guard:** So sánh mã băm MD5 của tài liệu trước khi cập nhật sang WeKnora, ngăn ngừa việc nạp lại dữ liệu không đổi.

### Thành phần 3: Điều tiết hàng đợi (`server/services/workflows/chat_workflow.py`)

- **MessageDebouncer:**
  - Khóa gom tin: `f"{tenant_key}:{chat_id}:{sender_id}"`.
  - Độ trễ chờ: `1.75` giây (`DEBOUNCE_DELAY_SECONDS = 1.75`).
  - Khi người dùng gõ ngắt quãng bấm Enter nhiều dòng liên tiếp, đồng hồ đếm ngược được đặt lại mỗi khi có dòng mới. Khi người dùng dừng gõ quá 1.75 giây, toàn bộ nội dung được ghép lại và chuyển tiếp.
- **CooldownQueue:**
  - Khoảng cách an toàn: `4.0` giây (`USER_COOLDOWN_SECONDS = 4.0`).
  - Ngăn ngừa việc gửi dồn dập nhiều câu hỏi. Quản trị viên (Admin) được miễn giãn cách (thời gian chờ = 0s).
- **ConcurrencySemaphore:**
  - Sử dụng `asyncio.Semaphore(MAX_CONCURRENT_CHAT_PIPELINES)` (mặc định 3).
  - Giới hạn số lượng tác vụ hội thoại chạy đồng thời, bảo vệ tài nguyên hệ thống và không vượt ngưỡng rate limit của các nhà cung cấp AI.

---

## 4. Bảng tham số cấu hình

| Tên biến | Kiểu dữ liệu | Mặc định | Ý nghĩa kỹ thuật |
| :--- | :---: | :---: | :--- |
| `DEBOUNCE_DELAY_SECONDS` | float | `1.75` | Thời gian chờ để gom các dòng gõ ngắt quãng của một người dùng. |
| `USER_COOLDOWN_SECONDS` | float | `4.0` | Khoảng thời gian giãn cách tối thiểu giữa 2 lần hỏi liên tiếp. |
| `MAX_CONCURRENT_CHAT_PIPELINES` | int | `3` | Số lượng tác vụ hội thoại được phép chạy đồng thời trên toàn server. |
| `CHAT_QUEUE_MAX_SIZE` | int | `100` | Sức chứa tối đa của hàng đợi tin nhắn chờ xử lý. |
| `DOCREADER_GRPC_HOST` | string | `127.0.0.1` | Địa chỉ máy chủ gRPC AnyDoc DocReader. |
| `DOCREADER_GRPC_PORT` | int | `50051` | Cổng dịch vụ gRPC AnyDoc DocReader. |
