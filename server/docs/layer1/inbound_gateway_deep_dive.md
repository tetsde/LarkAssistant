# 📘 SPEC KỸ THUẬT LAYER 1: CỬA NGÕ TIẾP NHẬN & ĐIỀU TIẾT TIN NHẮN

> **Dự án HiLark Server** — Tài liệu phân rã kỹ thuật chi tiết, ưu tiên tiếng Việt, không dùng từ ngữ bóng bẩy.
> Cập nhật: phản ánh đúng kiến trúc sau khi tách `lark.py` → `larkServices/` và tích hợp `ChatQueueService` vào `bot_service.py`.

---

## 🧭 Layer 1 làm gì?

Hãy hình dung Layer 1 như **"Bàn tiếp tân và phòng chờ có trật tự"** của toàn hệ thống:

1. **Nhận** tin nhắn từ Lark qua nhiều cổng (WebSocket, Webhook, DM Polling, REST).
2. **Lọc** tin rác, tin trùng, tin do chính bot gửi ra (chống vòng lặp).
3. **Lưu tạm** vào MongoDB để phục vụ báo cáo ngày (23:00).
4. **Phân luồng** theo vai trò người gửi (Chủ nhân đi thẳng, Thành viên qua hàng đợi).
5. **Gom** các dòng gõ ngắt quãng của cùng một người lại thành một câu hoàn chỉnh.
6. **Điều tiết** tốc độ và giới hạn số tác vụ chạy cùng lúc.
7. **Bàn giao** sang Layer 2 (JEV phân loại → LLM trả lời).

---

## 🖼️ SƠ ĐỒ PHÂN RÃ THÀNH PHẦN & LUỒNG HOẠT ĐỘNG

### 1. Phân rã thành phần Lớp 1 (Thuần Việt)
![Sơ đồ phân rã thành phần Lớp 1 thuần Việt](/Users/hoainam/.gemini/antigravity-ide/brain/7757b940-33a0-4b24-b567-26c89fe134f7/phan_ra_thanh_phan_lop_1_1792402814061.jpg)

### 2. Luồng thực thi mã nguồn
![Sơ đồ luồng Layer 1](/Users/hoainam/.gemini/antigravity-ide/brain/7757b940-33a0-4b24-b567-26c89fe134f7/layer1_flow_diagram_1792400839886.jpg)

```
Lark Platform
(WebSocket / Webhook / DM Polling / REST)
        │
        ▼
┌──────────────────────────────────────────────┐  MODULE 1
│  larkServices/lark_dispatcher.py             │  ─────────
│  LarkDispatcherMixin                         │
│  • parse_event()  →  LarkMessage             │
│  • Lọc: is_bot / is_self / is_duplicate      │
│  • Dedup Cache: 1.000 msg_id × 10 phút       │
└───────────────────┬──────────────────────────┘
                    │ _dispatch_to_handlers(lark_msg)
                    ▼
        ┌───────────────────────┐  MODULE 2
        │  bot_service.py       │  ─────────
        │  handle_lark_incoming │
        │  _message()           │
        │                       │
        │  • Lưu staging 23:00  │──► digest_service → MongoDB
        │  • Phân luồng vai trò │
        └──────┬────────┬───────┘
               │        │
         is_owner        is member
               │        │
               ▼        ▼
   process_chat_pipeline()    chat_queue_service.push_incoming_message()
   (reply_to_lark=False)              │
   [TRỰC TIẾP, không Queue]   ┌──────▼──────────────────────┐  MODULE 3
                               │  utils/chat_queue.py        │  ─────────
                               │  A. MessageDebouncer        │
                               │     Gom 1.75s / user-group  │
                               │  B. ThrottledChatQueue      │
                               │     Giãn cách 4s / user     │
                               │  C. Semaphore(max=3)        │
                               │     Giới hạn tác vụ đồng thời│
                               └──────────────┬──────────────┘
                                              │
                                              ▼
                                    process_chat_pipeline()
                                    [→ LAYER 2: JEV → LLM → Reply]
```

---

## 📦 BẢNG PHÂN RÃ MODULE (SPEC CHI TIẾT)

### MODULE 1 — `services/larkServices/` (Cửa ngõ nhận & lọc sự kiện)

| Sub-file | Class/Hàm chính | Vai trò cụ thể |
| :--- | :--- | :--- |
| `lark_client.py` | `LarkClientMixin` | Khởi tạo Lark SDK Client, quản lý User Access Token, lấy user profile |
| `lark_dispatcher.py` | `LarkDispatcherMixin` | **Parse** raw event → `LarkMessage`; **Dedup cache** 1.000 msg_id × 10 phút; **Lọc** `is_bot`, `is_self`, `is_duplicate`; **Phân phối** tới `_message_handlers`; Xử lý sự kiện bot thêm/xóa nhóm, Lark Base thay đổi |
| `lark_messenger.py` | `LarkMessengerMixin` | Gửi/reply tin nhắn nhân danh User (async & sync); Webhook handler cho FastAPI `/api/lark/events` |
| `lark_runner.py` | `LarkRunnerMixin` | WebSocket Client (background thread, event loop riêng); DM Polling; Hybrid Runner |
| `__init__.py` | `LarkService` | Ghép 4 Mixin → một đối tượng duy nhất `lark_service` (singleton) |

> 📍 Entry point: `lark_service.register_handler(handle_lark_incoming_message)` trong `bot_service.py`

---

### MODULE 2 — `services/bot_service.py` (Phân luồng & Lưu tạm)

**Hàm chính:** `handle_lark_incoming_message(msg: LarkMessage)` — [`L200~364`](file:///Users/hoainam/Desktop/HiLark/server/services/bot_service.py#L200)

| Bước | Logic | Vị trí |
| :--- | :--- | :--- |
| **Lọc DM chủ nhân** | Tin nhắn 1-1 tới chủ nhân → xử lý lệnh điều khiển (Duyệt/Sửa/Hủy digest) riêng | `L200-260` |
| **Tra cứu tên người gửi** | Gọi `lark_service.get_user_name()` để log đẹp hơn | `L270-292` |
| **Lưu staging** | Mỗi tin nhắn group → `digest_service.add_staging_message()` → MongoDB `conversation_staging`. (Điểm ghi duy nhất: `chat_service.py` bỏ qua `channel == "lark_group"` để triệt tiêu I/O trùng lặp) | `L295-308` |
| **Phân luồng Chủ nhân** | `is_owner=True` → gọi `process_chat_pipeline()` **trực tiếp**, `reply_to_lark=False` (không được phát ngôn vào nhóm) | `L311-354` |
| **Phân luồng Thành viên** | `is_owner=False` → `chat_queue_service.push_incoming_message()` → vào Debouncer + Queue | `L355-363` |

**Tại sao Chủ nhân đi thẳng, không qua Queue?**
> Chủ nhân cần kết quả JEV ngay lập tức (để xem tin nhắn của mình được phân loại thế nào) và không bao giờ cần bot reply vào nhóm thay mình nói chuyện (`reply_to_lark=False`). Vì vậy không cần Debouncer hay Cooldown.

---

### MODULE 3 — `utils/chat_queue.py` (Gom & Điều tiết)
> 💡 **Tài liệu bóc tách chi tiết:** Xem tại [`ultis_docs/chat_queue.md`](file:///Users/hoainam/Desktop/HiLark/server/docs/layer1/ultis_docs/chat_queue.md) và tổng quan quan hệ Parent-Child tại [`ultis_docs/README.md`](file:///Users/hoainam/Desktop/HiLark/server/docs/layer1/ultis_docs/README.md).

#### A. `MessageDebouncer` — Bộ gom tin gõ ngắt dòng

| Thuộc tính | Giá trị | Ý nghĩa |
| :--- | :---: | :--- |
| `debounce_seconds` | `1.75s` | Thời gian chờ sau dòng gõ cuối |
| Key gom | `(chat_id, sender_id)` | Gom theo từng người trong từng nhóm riêng biệt |
| Cơ chế | `asyncio.TimerHandle` | Timer reset mỗi lần user gõ thêm |
| Output | `ChatQueueItem` | Gói tin đã gom, text nối `\n` |

**Ví dụ thực tế:**
```
"Alo anh Nam"    [Enter]  → timer 1.75s bắt đầu
"Dự án HiLark"   [Enter]  → timer reset
"Bao giờ xong?"  [Enter]  → timer reset
... 1.75s im lặng ...
→ flush() → gom thành: "Alo anh Nam\nDự án HiLark\nBao giờ xong?"
```

---

#### B. `ThrottledChatQueue` — Hàng đợi điều tiết tốc độ

| Thuộc tính | Giá trị | Ý nghĩa |
| :--- | :---: | :--- |
| `cooldown_seconds` | `4.0s` | Giãn cách tối thiểu giữa 2 lần xử lý của cùng 1 user |
| `max_concurrent` | `3` | Semaphore: tối đa 3 pipeline chạy cùng lúc toàn server |
| `max_size` | `100` | Sức chứa tối đa của hàng đợi tin nhắn chờ |
| `enqueue_timeout` | `2.0s` | Thời gian chờ tối đa khi hàng đợi đầy trước khi hủy tin |
| Silent Throttling | ✅ | Không gửi tin nhắn cảnh báo vào nhóm, tự động chờ ngầm |
| Xử lý tràn queue (Giai đoạn 1) | Chờ 2s & Báo lỗi | Đợi tối đa 2 giây, quá 2s ghi log lỗi rõ ràng, hủy tin mới, **giữ nguyên tin cũ** |
| Owner bypass | ✅ | `is_owner=True` → bỏ qua cooldown (đi thẳng qua, không qua đây) |

**Cơ chế worker:**
```
asyncio.Queue(maxsize=100)
    └── enqueue(item)
          ├── Chờ tối đa 2.0s nếu hàng đợi đang đầy (QueueFull)
          ├── Quá 2.0s → Ghi log ERROR chi tiết, bỏ qua tin mới, KHÔNG xóa tin cũ
          └── Thành công → Đưa vào hàng đợi
    └── _worker_loop() [asyncio Task]
          ├── Lấy item từ queue
          ├── Tính elapsed = now - last_processed[sender_id]
          ├── Nếu elapsed < 4s → await asyncio.sleep(4s - elapsed)  [Silent wait]
          ├── Cập nhật last_processed[sender_id] = now
          └── asyncio.create_task(_process_with_semaphore(item))
                    └── async with semaphore(3):
                              └── pipeline_executor(item)  → process_chat_pipeline()
```

---

#### C. `ChatQueueService` — Điểm giao nhau

Là lớp kết nối Debouncer ↔ Queue:

```python
chat_queue_service.push_incoming_message(msg)
    └── debouncer.push(msg)
          └── [sau 1.75s im lặng] _on_debounced_ready(item)
                └── queue.enqueue(item) [chờ tối đa 2.0s nếu đầy]
                      └── [sau cooldown] _execute_pipeline(item)
                                └── process_chat_pipeline()
```

---

## ⚙️ BẢNG THAM SỐ CẤU HÌNH (file `.env` / `config.py`)

| Biến cấu hình | Mặc định | Điều khiển |
| :--- | :---: | :--- |
| `DEBOUNCE_DELAY_SECONDS` | `1.75` | Thời gian gom tin ngắt dòng (giây) |
| `USER_COOLDOWN_SECONDS` | `4.0` | Giãn cách tối thiểu giữa 2 request của cùng 1 user |
| `MAX_CONCURRENT_CHAT_PIPELINES` | `3` | Số pipeline LLM chạy đồng thời tối đa |
| `CHAT_QUEUE_MAX_SIZE` | `100` | Sức chứa tối đa của hàng đợi tin nhắn chờ |
| `CHAT_QUEUE_ENQUEUE_TIMEOUT` | `2.0` | Thời gian chờ tối đa khi đầy queue (giây) |
| `DIGEST_SCHEDULE_TIME` | `23:00` | Giờ chạy tổng hợp báo cáo ngày |
| `ENABLE_DM_POLLING` | `false` | Có bật chế độ quét hộp thư 1-1 định kỳ không |
| `DM_POLL_INTERVAL` | `60.0` | Chu kỳ quét DM (giây) |

---

## 🔖 ĐÁNH DẤU MODULE THEO LAYER

```
LAYER 1 — INBOUND GATEWAY
├── [RECV]   services/larkServices/lark_runner.py      → Kết nối WebSocket + DM Polling
├── [RECV]   services/larkServices/lark_dispatcher.py  → Parse sự kiện, lọc, dedup, phân phối
├── [ROUTE]  services/bot_service.py                   → Phân luồng Chủ nhân / Thành viên, lưu staging
├── [BUFFER] utils/chat_queue.py                       → Gom tin (Debouncer) + điều tiết (ThrottledQueue)
│
├── [SUPPORT] services/larkServices/lark_client.py     → Kết nối SDK, Token (hỗ trợ cho RECV)
├── [SUPPORT] services/larkServices/lark_messenger.py  → Gửi tin nhắn (hỗ trợ cho ROUTE)
├── [SUPPORT] services/larkServices/__init__.py        → Ghép LarkService singleton
│
└── [STAGING] services/digest_service.add_staging_message()
              → MongoDB: conversation_staging (phục vụ Layer báo cáo 23:00)

LAYER 2 — JEV FILTER & INTENT ROUTING (ra ngoài phạm vi Layer 1)
└── services/chat_service.process_chat_pipeline()
```

---

## ❓ GIẢI ĐÁP CÂU HỎI KỸ THUẬT THƯỜNG GẶP

### Tại sao Layer 1 chưa gọi JEV?
> Layer 1 lo làm mượt hạ tầng mạng. Nếu gọi JEV ngay từ Debouncer, mỗi dòng gõ ngắt quãng sẽ tốn 1 lần JEV, trong khi 3 dòng chỉ là 1 câu hỏi. Phải gom xong mới phân loại.

### Tại sao Chủ nhân đi thẳng, không qua Queue?
> Chủ nhân không bao giờ được bot reply vào nhóm (`reply_to_lark=False`). Mục đích duy nhất là ghi nhớ ngầm và debug log JEV. Không có lý do gì phải chờ cooldown hay gom tin.

### Lưu tất cả tin nhắn nhóm vào staging có bị rác hoặc ghi đúp không?
> Không. 
> 1. **Về rác:** Lúc 23:00 AI chỉ nhặt ra Quyết định, Cam kết, Người phụ trách. Câu chào hỏi, đùa cợt bị AI bỏ qua. Bản báo cáo còn phải Chủ nhân duyệt trước khi vào kho tri thức WeKnora. Ngoài ra, dữ liệu tạm nên đặt TTL 7 ngày trong MongoDB để tự xóa sau khi báo cáo đã xử lý xong.
> 2. **Về chống ghi đúp:** Gateway `bot_service.py` là điểm ghi staging duy nhất cho nhóm Lark. Tại `chat_service.py`, lệnh ghi staging được bảo vệ bởi điều kiện `channel != "lark_group"`, triệt tiêu 100% nguy cơ ghi đúp I/O vào cơ sở dữ liệu.

### Nếu user gửi cùng lúc ở 2 nhóm khác nhau thì sao?
> Debouncer gom theo `(chat_id, sender_id)` — hai nhóm khác nhau là hai key riêng biệt, xử lý hoàn toàn độc lập. Semaphore `max=3` kiểm soát tổng tải trên toàn server.
