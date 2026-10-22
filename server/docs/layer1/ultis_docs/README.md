# 🛠️ TỔNG QUAN BỘ CÔNG CỤ (UTILS) CỦA LAYER 1
> **HiLark Server Architecture** — Bóc tách chi tiết các module tiện ích thuộc Lớp 1 (Cửa ngõ tiếp nhận & Điều tiết tin nhắn).

---

## 🧭 1. KIẾN TRÚC PHÂN CẤP: UTILS (CHILD) ➔ STEPS (PARENT) ➔ LAYER 1 (ROOT)

Trong Layer 1, toàn bộ luồng xử lý tin nhắn từ Lark Open Platform được tổ chức theo cấu trúc phân cấp nghiêm ngặt. Mỗi **Bước xử lý (Step)** được vận hành bởi các **Tiện ích con (Child Utils / Components)** chuyên trách:

```
                      ┌─────────────────────────────────────────────────────────────┐
                      │              LAYER 1: INBOUND GATEWAY PIPELINE              │
                      │               (Cửa ngõ tiếp nhận & Điều tiết)               │
                      └──────────────────────────────┬──────────────────────────────┘
                                                     │
         ┌───────────────────┬───────────────────────┼───────────────────────┬───────────────────┐
         ▼                   ▼                       ▼                       ▼                   ▼
┌─────────────────┐ ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐ ┌─────────────────┐
│     BƯỚC 1      │ │     BƯỚC 2      │     │     BƯỚC 3      │     │     BƯỚC 4      │ │     BƯỚC 5      │
│  Tiếp nhận &    │ │ Lọc sơ cấp &    │     │  Phân luồng &   │     │  Gom ngắt dòng  │ │  Hàng đợi &     │
│  Phân giải      │ │ Chống lặp       │     │  Lưu tạm        │     │  (Debouncing)   │ │  Điều tiết tải  │
│  (Parent Step)  │ │ (Parent Step)   │     │  (Parent Step)  │     │  (Parent Step)  │ │  (Parent Step)  │
└────────┬────────┘ └────────┬────────┘     └────────┬────────┘     └────────┬────────┘ └────────┬────────┘
         │                   │                       │                       │                   │
         │ (Child Utils)     │ (Child Utils)         │ (Child Utils)         │ (Child Utils)     │ (Child Utils)
         ▼                   ▼                       ▼                       ▼                   ▼
┌─────────────────┐ ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐ ┌─────────────────┐
│ • parse_event() │ │ • Dedup Cache   │     │ • Role Router   │     │ • TimerHandle   │ │ • asyncio.Queue │
│ • LarkMessage   │ │   (1.000 msg_id)│     │   (Owner vs Mbr)│     │   (1.75s timer) │   (100 slots)   │
│   Builder       │ │ • Loop Shield   │     │ • Staging Logger│     │ • User-Group    │ │ • Timeout Wait  │
│ • JSON Extractor│ │   (is_bot/self) │     │   (Mongo 23:00) │     │   Buffer Lock   │   (2s & Log ERR)│
│                 │ │ • Schema Guard  │     │ • DM Commander  │     │ • String Joiner │ │ • Cooldown 4s   │
│                 │ │   (p2p/group)   │     │   (1-1 Control) │     │   (\\n merger)   │ │ • Semaphore(3)  │
└─────────────────┘ └─────────────────┘     └─────────────────┘     └─────────────────┘ └─────────────────┘
```

---

## 🧩 2. BẢNG MỐI QUAN HỆ PARENT - CHILD CHI TIẾT

| Bước xử lý (Parent Step) | Vai trò của Bước trong Layer 1 | Tiện ích thực thi con (Child Utils / Functions) | Vị trí mã nguồn |
| :--- | :--- | :--- | :--- |
| **BƯỚC 1: Tiếp nhận & Phân giải sự kiện** *(Event Ingestion & Parsing)* | Tiếp nhận raw JSON từ WebSocket hoặc Webhook, giải mã cấu trúc gói tin Lark. | • `parse_event()`: Rút trích `event_type`, `message_id`, `chat_id`, `content`.<br/>• `LarkMessage` Data Class: Chuẩn hóa kiểu dữ liệu tin nhắn toàn server. | [`services/larkServices/lark_dispatcher.py:L70-130`](file:///Users/hoainam/Desktop/HiLark/server/services/larkServices/lark_dispatcher.py#L70-L130) |
| **BƯỚC 2: Lọc sơ cấp & Chống lặp** *(Primary Filtering & Dedup)* | Chặn đứng tin rác, chống vòng lặp vô tận và chống xử lý trùng khi Lark bắn lại webhook. | • `_seen_msg_ids` (Dedup Cache): Bộ nhớ đệm lưu 1.000 `msg_id` trong 10 phút.<br/>• Loop Shield: Kiểm tra `is_bot == True` hoặc `is_self == True` để ngắt ngay.<br/>• Schema Guard: Bỏ qua các sự kiện không phải tin nhắn văn bản (`im.message.receive_v1`). | [`services/larkServices/lark_dispatcher.py:L135-185`](file:///Users/hoainam/Desktop/HiLark/server/services/larkServices/lark_dispatcher.py#L135-L185) |
| **BƯỚC 3: Phân luồng quyền lực & Lưu tạm** *(Role Routing & Staging)* | Phân biệt Chủ nhân với Thành viên; lưu trữ dữ liệu thời gian thực cho báo cáo tổng kết ngày. | • `Role Router`: Chủ nhân (`is_owner=True`) đi thẳng vào pipeline, Thành viên đẩy vào Queue.<br/>• `Staging Logger`: Gọi `digest_service.add_staging_message()` lưu vào MongoDB `conversation_staging`.<br/>• `DM Commander`: Bắt riêng tin nhắn 1-1 của Sếp để nhận lệnh Duyệt/Sửa/Hủy Daily Digest. | [`services/bot_service.py:L200-364`](file:///Users/hoainam/Desktop/HiLark/server/services/bot_service.py#L200-L364) |
| **BƯỚC 4: Gom tin gõ ngắt dòng** *(Message Debouncing)* | Gom nhiều dòng gõ ngắt quãng của cùng một người trong một nhóm thành một câu hoàn chỉnh. | • `MessageDebouncer`: Khởi tạo bộ đệm theo cặp `(chat_id, sender_id)`.<br/>• `asyncio.TimerHandle`: Cửa sổ chờ 1.75s, reset timer nếu người dùng tiếp tục gõ.<br/>• `_flush()`: Nối các dòng chat bằng dấu xuống dòng `\n`, đóng gói thành `ChatQueueItem`. | [`utils/chat_queue.py:L27-119`](file:///Users/hoainam/Desktop/HiLark/server/utils/chat_queue.py#L27-L119) |
| **BƯỚC 5: Hàng đợi điều tiết & Chống nghẽn hạ tầng** *(Throttled Queue & Traffic Control)* | Điều tiết tốc độ xử lý, giới hạn tải đồng thời, chống sập hệ thống và bảo vệ quota LLM. | • `asyncio.Queue(maxsize=100)`: Hàng đợi bất đồng bộ sức chứa 100 gói tin.<br/>• Cơ chế chống tràn: Chờ 2.0s, quá hạn ghi log lỗi rõ ràng, bỏ qua tin mới, bảo toàn tin cũ.<br/>• Silent Throttling: Giãn cách 4.0s/user, tự động chờ ngầm, không spam nhóm.<br/>• `asyncio.Semaphore(3)`: Khóa tối đa 3 tác vụ AI chạy song song toàn server. | [`utils/chat_queue.py:L121-236`](file:///Users/hoainam/Desktop/HiLark/server/utils/chat_queue.py#L121-L236) |

---

## 🗂️ DANH MỤC TÀI LIỆU BÓC TÁCH KỸ THUẬT

1. **[`chat_queue.md`](file:///Users/hoainam/Desktop/HiLark/server/docs/layer1/ultis_docs/chat_queue.md)**:
   * **Mã nguồn:** [`server/utils/chat_queue.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/chat_queue.py) *(335 dòng, 14.5 KB)*.
   * **Nội dung:** Bóc tách sâu từng class: `MessageDebouncer`, `ThrottledChatQueue`, `ChatQueueService`.
   * **Phân tích chi tiết:** Cơ chế gom ngắt dòng 1.75s, cơ chế xử lý tràn queue (Giai đoạn 1: chờ 2s, log ERROR, giữ tin cũ), cơ chế Silent Throttling 4s, Semaphore 3 luồng và quy trình bàn giao an toàn sang Layer 2 (`process_chat_pipeline`).

---

## 🔄 3. SƠ ĐỒ KẾT NỐI LUỒNG DỮ LIỆU: UTILS ➔ STEPS ➔ LAYER 1

![Sơ đồ kết nối Utils Layer 1](/Users/hoainam/.gemini/antigravity-ide/brain/7757b940-33a0-4b24-b567-26c89fe134f7/ket_noi_utils_layer1_1792461292980.jpg)

### Quy trình dòng chảy chi tiết (Mermaid Flowchart):

```mermaid
flowchart TD
    classDef stepBox fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#f8fafc;
    classDef utilBox fill:#0f172a,stroke:#10b981,stroke-width:1px,color:#e2e8f0;
    classDef rootBox fill:#1e1b4b,stroke:#8b5cf6,stroke-width:3px,color:#ffffff;
    classDef alertBox fill:#450a0a,stroke:#ef4444,stroke-width:1px,color:#fecaca;
    classDef successBox fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#a7f3d0;

    LarkMsg["📨 Tin nhắn thô từ Lark (WebSocket / Webhook)"]

    subgraph L1["🏛️ LAYER 1 PIPELINE: CỬA NGÕ TIẾP NHẬN & ĐIỀU TIẾT (ROOT)"]
        
        subgraph S1["🔹 BƯỚC 1: Tiếp nhận & Phân giải (Parent Step 1)"]
            U1_1["parse_event()<br/>(Trích xuất JSON Lark)"]:::utilBox
            U1_2["LarkMessage Model<br/>(Chuẩn hóa dữ liệu tin nhắn)"]:::utilBox
            U1_1 --> U1_2
        end
        
        subgraph S2["🔹 BƯỚC 2: Lọc sơ cấp & Chống lặp (Parent Step 2)"]
            U2_1["_seen_msg_ids<br/>(Dedup Cache 1.000 msg_id / 10p)"]:::utilBox
            U2_2["Loop Shield<br/>(is_bot / is_self check)"]:::utilBox
            U2_3["Schema Guard<br/>(Chỉ nhận im.message.receive_v1)"]:::utilBox
            U2_1 --> U2_2 --> U2_3
        end

        subgraph S3["🔹 BƯỚC 3: Phân luồng quyền lực & Lưu tạm (Parent Step 3)"]
            U3_1["Role Router<br/>(Phân biệt Chủ nhân vs Thành viên)"]:::utilBox
            U3_2["Staging Logger<br/>(Ghi MongoDB staging 23:00)"]:::utilBox
            U3_3["DM Commander<br/>(Xử lý lệnh 1-1 Duyệt/Sửa/Hủy)"]:::utilBox
            U3_1 --> U3_2
            U3_1 --> U3_3
        end

        subgraph S4["🔹 BƯỚC 4: Gom tin gõ ngắt dòng (Parent Step 4)"]
            U4_1["MessageDebouncer._buffers<br/>(Đệm tin theo chat_id & user_id)"]:::utilBox
            U4_2["asyncio.TimerHandle<br/>(Cửa sổ chờ 1.75s, reset khi gõ tiếp)"]:::utilBox
            U4_3["_flush() & String Joiner<br/>(Ghép các dòng gõ bằng \\n)"]:::utilBox
            U4_1 --> U4_2 --> U4_3
        end

        subgraph S5["🔹 BƯỚC 5: Hàng đợi điều tiết & Chống nghẽn (Parent Step 5)"]
            U5_1["asyncio.Queue(maxsize=100)<br/>(Hàng đợi bất đồng bộ)"]:::utilBox
            U5_2{"Đầy hàng đợi?"}:::utilBox
            U5_3["Timeout Wait (2.0s)<br/>❌ Quá 2s: Báo lỗi & Bỏ tin mới<br/>🛡️ Giữ nguyên tin cũ"]:::alertBox
            U5_4["Silent Throttling Worker<br/>(Giãn cách âm thầm 4.0s/user)"]:::utilBox
            U5_5["asyncio.Semaphore(3)<br/>(Khóa tối đa 3 tác vụ AI cùng lúc)"]:::utilBox
            
            U5_1 --> U5_2
            U5_2 -->|Đầy| U5_3
            U5_2 -->|Còn chỗ| U5_4
            U5_4 --> U5_5
        end

    end

    LarkMsg --> S1
    S1 --> S2
    S2 --> S3

    S3 -->|Chủ nhân: is_owner=True| Bypass["🚀 ĐI THẲNG (OWNER BYPASS)<br/>(reply_to_lark=False, không qua Queue)"]:::successBox
    S3 -->|Thành viên: is_owner=False| S4
    
    U4_3 -->|ChatQueueItem đã gom xong| U5_1
    
    U5_5 --> Target["🎯 BÀN GIAO SANG LAYER 2<br/>process_chat_pipeline()<br/>(Kiểm duyệt an ninh JEV ➔ LLM)"]:::successBox
    Bypass --> Target
```
