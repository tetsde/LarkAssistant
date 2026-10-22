# 📘 TỔNG QUAN HỆ THỐNG ĐỒNG BỘ DỮ LIỆU LARK BASE (BITABLE SYNC)
> **Dự án HiLark Server** — Trung tâm điều khiển quản trị (Admin Control Plane) và luồng đồng bộ đa nguồn tự động.  
> **Vị trí thư mục:** [`server/docs/LarkBase/`](file:///Users/hoainam/Desktop/HiLark/server/docs/LarkBase)

---

## 🧭 1. LARK BASE LÀ GÌ TRONG HỆ THỐNG HILARk?

Trong kiến trúc HiLark Server, **Lark Base (Bitable)** đóng vai trò là **"Trung tâm điều khiển quản trị không chạm code" (No-code Admin Control Plane)**:

* **Không cần sửa file `.env` hay viết mã:** Sếp hoặc Quản trị viên chỉ cần mở ứng dụng Lark, truy cập vào bảng tính Lark Base để:
  1. Bật / Tắt hoạt động của bot trong từng nhóm (`status = active / paused / inactive`).
  2. Thiết lập chính sách bảo mật cho từng dự án (`security_level = standard / confidential`).
  3. Đặt danh sách các chủ đề cấm hỏi (`forbidden_labels = ["Ngân sách", "Lương", "Hợp đồng"]`).
  4. Nạp tài liệu tri thức cho bot bằng cách **kéo thả trực tiếp file PDF/Word vào ô đính kèm** của bảng Base!
* **Dữ liệu được đồng bộ tự động 2 chiều:** Bất kỳ thao tác nào của Sếp trên Lark Base đều được hệ thống tự động đồng bộ sang **MongoDB** (lưu cấu hình nhóm) và **WeKnora RAG** (nạp và vector hóa tài liệu).

---

## 🏗️ 2. KIẾN TRÚC 3 TẦNG ĐỒNG BỘ (BITABLE SYNC ARCHITECTURE)

![Sơ đồ luồng đồng bộ dữ liệu Lark Base](/Users/hoainam/.gemini/antigravity-ide/brain/7757b940-33a0-4b24-b567-26c89fe134f7/sync_larkbase_1792462484721.jpg)

### Quy trình dòng chảy chi tiết (Mermaid Flowchart):

```mermaid
flowchart TD
    classDef stepBox fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#f8fafc;
    classDef utilBox fill:#0f172a,stroke:#10b981,stroke-width:1px,color:#e2e8f0;
    classDef alertBox fill:#450a0a,stroke:#ef4444,stroke-width:1px,color:#fecaca;
    classDef successBox fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#a7f3d0;

    subgraph UI["🖥️ GIAO DIỆN SẾP: BẢNG TÍNH LARK BASE (ADMIN NO-CODE)"]
        R1["ID Group (chat_id)"]
        R2["Dự án / Nhóm (chat_name)"]
        R3["Trạng thái (active / paused / inactive)"]
        R4["Mức độ bảo mật (standard / confidential)"]
        R5["Nhãn cấm (forbidden_labels)"]
        R6["Tài liệu đính kèm (File PDF / Word)"]
    end

    UI -->|Kênh 1: Webhook Event (Realtime)| EV["drive.file.bitable_record_changed_v1<br/>(Sếp sửa Base ➔ Tức thời ~0.5s)"]
    IM["Lark IM Group Event<br/>(im.chat.member.bot.added_v1)"] -->|Kênh 2: Webhook Event (Realtime)| BOT["_internal_on_bot_added_event()<br/>(Tự tạo dòng mới tức thì trên Base ~0.5s)"]
    BOT -.-> UI
    BOOT["Khởi động Server<br/>(One-off Bootstrap Sync)"] -.->|Nạp dữ liệu ban đầu| S1

    subgraph SYNC["⚙️ ĐỘNG CƠ ĐỒNG BỘ: scope_service.py & larkbase.py"]
        direction TB
        S1["1. Bóc tách & Làm sạch Cell Values<br/>clean_field_value(raw_val)"]:::utilBox
        S2["2. Phân giải Nhãn cấm & Bảo mật<br/>parse_labels() & Nhóm Tuyệt mật"]:::utilBox
        S3["3. Tải file & Đẩy WeKnora<br/>adownload_attachment() ➔ upload_file()"]:::utilBox
        S4["4. Lưu trữ MongoDB 'chat_scopes'<br/>Upsert ChatScopeRecord"]:::utilBox
        
        S1 --> S2 --> S3 --> S4
    end

    EV --> S1
    BOT -->|sync_group_from_base_record| S1

    S3 -->|File bytes| WK[("📚 KHO TRI THỨC WEKNORA<br/>Phân đoạn văn bản & Vector hóa<br/>Trả về 'knowledge_id'")]:::successBox
    WK -->|Gán knowledge_ids| S4

    S4 --> MG[("💾 CƠ SỞ DỮ LIỆU MONGODB<br/>Collection: 'chat_scopes'<br/>Cung cấp dữ liệu < 1ms cho Layer 2 & 3")]:::successBox
```

---

## 🔄 3. CƠ CHẾ ĐỒNG BỘ 100% EVENT-DRIVEN (REALTIME SYNC)

Hệ thống hoạt động theo kiến trúc **100% Hướng sự kiện (Event-Driven)**, triệt tiêu hoàn toàn cơ chế Polling ngầm để không lãng phí API Quota và đảm bảo dữ liệu phản ứng tức thì trong **~0.5 giây**:

| Kênh đồng bộ | Tác nhân kích hoạt | Cơ chế kỹ thuật | Tốc độ phản ứng |
| :--- | :--- | :--- | :---: |
| **1. Kênh Sự kiện Bảng Base** *(Base Record Changed)* | Sếp sửa một ô, đổi trạng thái hoặc kéo thả file mới vào bảng Base. | Webhook `drive.file.bitable_record_changed_v1` gửi về FastAPI $\rightarrow$ `scope_service.handle_bitable_record_changed_event()`. | **Tức thì (~0.5 - 1s)** |
| **2. Kênh Sự kiện Nhóm Chat** *(Bot Added to Group)* | Thành viên mời Bot vào nhóm chat mới trên ứng dụng Lark. | Webhook `im.chat.member.bot.added_v1` $\rightarrow$ `_internal_on_bot_added_event()` tự tạo record Base và sync sang Mongo. | **Tức thì (~0.5s)** |
| **3. Khởi tạo khi Start Server** *(One-off Bootstrap Sync)* | Khi khởi động FastAPI server (`bot_service.py`). | Quét `sync_bot_chats()` và `sync_all_groups_from_base()` **1 lần duy nhất** lúc bật server để nạp toàn bộ cấu hình ban đầu. | **1 lần duy nhất lúc khởi động** |

> [!NOTE]
> **Khai tử Background Polling:** Trước đây hệ thống chạy 1 luồng ngầm polling mỗi 30s. Hiện tại đã được gỡ bỏ hoàn toàn sau khi đăng ký sự kiện `im.chat.member.bot.added_v1` trên Lark Developer Console, giúp loại bỏ 2.880 lượt gọi API lãng phí mỗi ngày!

---

## 🗂️ DANH MỤC TÀI LIỆU BÓC TÁCH KỸ THUẬT

1. **[`sync_pipeline_deep_dive.md`](file:///Users/hoainam/Desktop/HiLark/server/docs/LarkBase/sync_pipeline_deep_dive.md)**:
   * **Nội dung:** Bản đặc tả kỹ thuật chi tiết toàn bộ luồng đồng bộ dữ liệu.
   * **Bóc tách mã nguồn:**
     * [`server/services/larkbase.py`](file:///Users/hoainam/Desktop/HiLark/server/services/larkbase.py) *(1097 dòng)*: Driver kết nối Lark Bitable API.
     * [`server/services/scope_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/scope_service.py) *(470 dòng)*: Điều phối luồng nạp file sang WeKnora và lưu trữ vào MongoDB.
     * [`server/utils/larkbase/cleaner.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/larkbase/cleaner.py) & [`token.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/larkbase/token.py): Bộ dọn dẹp cell values và giải mã token JWT.
