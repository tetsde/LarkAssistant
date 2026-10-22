# 🛠️ TỔNG QUAN BỘ CÔNG CỤ (UTILS) CỦA LAYER 4
> **HiLark Server Architecture** — Bóc tách chi tiết các module tiện ích thuộc Lớp 4 (Sinh câu trả lời & Đóng vai người điều hành).

---

## 🧭 1. KIẾN TRÚC PHÂN CẤP: UTILS (CHILD) ➔ STEPS (PARENT) ➔ LAYER 4 (ROOT)

Trong Layer 4, câu trả lời từ AI được biến hóa để khoác lên phong cách của một nhà điều hành thực tế, làm sạch định dạng văn bản và phân phối an toàn vào phòng chat hoặc luồng duyệt riêng tư. Mỗi **Bước xử lý (Parent Step)** được vận hành bởi các **Tiện ích con (Child Utils / Helpers)** chuyên trách:

```
                      ┌─────────────────────────────────────────────────────────────┐
                      │              LAYER 4: EXECUTIVE PERSONA PIPELINE            │
                      │               (Đóng vai điều hành & Phân phối)              │
                      └──────────────────────────────┬──────────────────────────────┘
                                                     │
         ┌───────────────────┬───────────────────────┼───────────────────────┬───────────────────┐
         ▼                   ▼                       ▼                       ▼                   ▼
┌─────────────────┐ ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐ ┌─────────────────┐
│     BƯỚC 1      │ │     BƯỚC 2      │     │     BƯỚC 3      │     │     BƯỚC 4      │ │     BƯỚC 5      │
│  Thiết lập vai  │ │  Sinh câu trả   │     │  Dọn sạch định  │     │  Phân nhánh gửi │ │  Lưu nháp &     │
│  diễn của Sếp   │ │  lời Grounded   │     │  dạng văn bản   │     │  hoặc soạn nháp │ │  Sếp phê duyệt  │
│  (Parent Step)  │ │  (Parent Step)  │     │  (Parent Step)  │     │  (Parent Step)  │ │  (Parent Step)  │
└────────┬────────┘ └────────┬────────┘     └────────┬────────┘     └────────┬────────┘ └────────┬────────┘
         │                   │                       │                       │                   │
         │ (Child Utils)     │ (Child Utils)         │ (Child Utils)         │ (Child Utils)     │ (Child Utils)
         ▼                   ▼                       ▼                       ▼                   ▼
┌─────────────────┐ ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐ ┌─────────────────┐
│ • Persona       │ │ • LLMClient     │     │ • XML/HTML Tag  │     │ • Policy Check  │ │ • PendingDraft  │
│   Prompt Builder│ │   (Gemini API)  │     │   Stripper      │     │   (Tuyệt mật)   │   Mongo Store   │
│ • Identity &    │ │ • GLOBAL_LLM_   │     │ • Citation Tag  │     │ • areply_text   │ │ • Draft Card    │
│   Tone Injector │ │   SEMAPHORE     │     │   Cleaner       │     │   (as_user=True)│   Formatter     │
│ • Scope         │ │ • Fallback      │     │ • Punctuation & │     │ • Direct Reply  │ │ • send_bot_dm   │
│   Defaulting    │ │   WeKnora Chat  │     │   Whitespace Fix│     │   Dispatcher    │   _to_owner()   │
└─────────────────┘ └─────────────────┘     └─────────────────┘     └─────────────────┘ └─────────────────┘
```

---

## 🧩 2. BẢNG MỐI QUAN HỆ PARENT - CHILD CHI TIẾT

| Bước xử lý (Parent Step) | Vai trò của Bước trong Layer 4 | Tiện ích thực thi con (Child Utils / Functions) | Vị trí mã nguồn |
| :--- | :--- | :--- | :--- |
| **BƯỚC 1: Thiết lập vai diễn của Sếp** *(Persona Injection)* | Nạp phong cách điều hành 10/10: xưng "anh - em", không nói dông dài, nói như kiến thức của mình. | • `Persona Prompt Builder`: Nạp template `GROUNDED_QA_USER_PERSONA_PROMPT`.<br/>• `Identity Injector`: Điền `{responder_name}`, `{role}`, `{user_name}`.<br/>• `Scope Defaulting`: Tự động ngầm hiểu dự án của nhóm, cấm hỏi ngược. | [`services/chat_service.py:L78-126`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L78-L126)<br/>[`services/chat_service.py:L209-221`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L209-L221) |
| **BƯỚC 2: Sinh câu trả lời Grounded** *(Gemini QA & Fallback)* | Gọi mô hình ngôn ngữ lớn để trả lời dựa trên bối cảnh tri thức, có giới hạn tải trọng. | • `LLMClient.generate_text_async()`: Gọi Gemini API với `max_output_tokens=4096`.<br/>• `GLOBAL_LLM_SEMAPHORE`: Khóa an toàn giới hạn số tác vụ AI chạy song song.<br/>• `WeKnora Fallback Engine`: Tự động gọi WeKnora Chat nếu LLM rỗng. | [`services/chat_service.py:L190-235`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L190-L235)<br/>[`services/chat_service.py:L576-584`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L576-L584) |
| **BƯỚC 3: Dọn sạch định dạng văn bản** *(Output Sanitization)* | Quét sạch toàn bộ các thẻ trích dẫn nội bộ của RAG/WeKnora, sửa lỗi dấu câu và markdown. | • `XML/HTML Tag Stripper`: Xóa `<kb .../>`, `<doc ...>`, `<chunk ...>`.<br/>• `Citation Tag Cleaner`: Xóa `[Tài liệu: ...]`, `[Cập nhật hội thoại: ...]`.<br/>• `Punctuation & Whitespace Fix`: Chữa lỗi hở dấu câu, rút gọn `\n\n`. | [`utils/text_filter.py:L39-91`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py#L39-L91)<br/>[`services/chat_service.py:L586`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L586) |
| **BƯỚC 4: Phân nhánh gửi hoặc soạn nháp** *(Delivery Branching)* | Quyết định phát ngôn trực tiếp hay chuyển sang luồng soạn nháp dựa trên chính sách bảo mật. | • `Policy Check`: Kiểm tra cờ `is_confidential_group` hoặc `jev_action`.<br/>• `areply_text(as_user=True)`: Phát ngôn nhân danh tài khoản User của Sếp.<br/>• `Direct Reply Dispatcher`: Gửi tin phản hồi kèm trích dẫn tin nhắn gốc. | [`services/chat_service.py:L588-615`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L588-L615)<br/>[`services/chat_service.py:L653-665`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L653-L665) |
| **BƯỚC 5: Lưu nháp & Sếp phê duyệt** *(Draft Approval Workflow)* | Lưu bản nháp vào MongoDB và gửi thẻ thông báo riêng vào DM của Sếp kèm 3 nút lệnh. | • `PendingDraft Store`: Lưu bản ghi vào MongoDB bảng `pending_drafts`.<br/>• `Draft Card Formatter`: Đóng gói thẻ tin nhắn kèm lý do bảo mật và ID gốc.<br/>• `send_bot_dm_to_owner()`: Gửi tin nhắn riêng (DM) tới Sếp để duyệt. | [`services/chat_service.py:L596-636`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py#L596-L636)<br/>[`services/larkServices/lark_messenger.py`](file:///Users/hoainam/Desktop/HiLark/server/services/larkServices/lark_messenger.py) |

---

## 🗂️ DANH MỤC TÀI LIỆU BÓC TÁCH KỸ THUẬT

1. **[`output_sanitizer.md`](file:///Users/hoainam/Desktop/HiLark/server/docs/layer4/ultis_docs/output_sanitizer.md)**:
   * **Mã nguồn:** [`server/utils/text_filter.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/text_filter.py) *(các hàm hậu xử lý: `clean_output()`, `extract_kb_citations()`)* và logic format bản nháp tại [`server/services/chat_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/chat_service.py).
   * **Nội dung:** Bóc tách sâu thuật toán Regex 5 tầng làm sạch thẻ trích dẫn RAG, định dạng thẻ tin nhắn duyệt nháp (Interactive Card), và cơ chế gửi tin nhắn Lark dưới danh nghĩa cá nhân Sếp (`as_user=True`).

---

## 🔄 3. SƠ ĐỒ KẾT NỐI LUỒNG DỮ LIỆU: UTILS ➔ STEPS ➔ LAYER 4

![Sơ đồ kết nối Utils Layer 4](/Users/hoainam/.gemini/antigravity-ide/brain/7757b940-33a0-4b24-b567-26c89fe134f7/ket_noi_utils_layer4_1792462094048.jpg)

### Quy trình dòng chảy chi tiết (Mermaid Flowchart):

```mermaid
flowchart TD
    classDef stepBox fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#f8fafc;
    classDef utilBox fill:#0f172a,stroke:#10b981,stroke-width:1px,color:#e2e8f0;
    classDef alertBox fill:#450a0a,stroke:#ef4444,stroke-width:1px,color:#fecaca;
    classDef successBox fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#a7f3d0;

    InContext["📦 Bối cảnh tri thức đã hợp nhất từ Layer 3"]

    subgraph L4["🏛️ LAYER 4: EXECUTIVE PERSONA & DELIVERY PIPELINE (ROOT)"]
        
        subgraph S1["🔹 BƯỚC 1: Thiết lập vai diễn của Sếp (Parent Step 1)"]
            U1_1["Persona Prompt Builder<br/>(Nạp template chuẩn 10/10)"]:::utilBox
            U1_2["Identity Injector<br/>(Gán responder_name, role, user_name)"]:::utilBox
            U1_3["Scope Defaulting<br/>(Ngầm hiểu dự án, cấm hỏi ngược)"]:::utilBox
            U1_1 --> U1_2 --> U1_3
        end
        
        subgraph S2["🔹 BƯỚC 2: Sinh câu trả lời Grounded QA (Parent Step 2)"]
            U2_1["LLMClient (Gemini API)<br/>(max_output_tokens=4096)"]:::utilBox
            U2_2["GLOBAL_LLM_SEMAPHORE<br/>(Khóa giới hạn tải song song)"]:::utilBox
            U2_3["WeKnora Fallback Engine<br/>(Dự phòng khi LLM rỗng)"]:::utilBox
            U2_1 --> U2_2
            U2_2 -->|Nếu rỗng| U2_3
        end

        subgraph S3["🔹 BƯỚC 3: Dọn sạch định dạng văn bản (Parent Step 3)"]
            U3_1["XML/HTML Tag Stripper<br/>(Xóa thẻ kb, doc, chunk)"]:::utilBox
            U3_2["Citation Cleaner<br/>(Xóa ngoặc vuông trích dẫn)"]:::utilBox
            U3_3["Punctuation & Space Fix<br/>(Sửa lỗi hở dấu, rút gọn \\n\\n)"]:::utilBox
            U3_1 --> U3_2 --> U3_3
        end

        subgraph S4["🔹 BƯỚC 4: Phân nhánh gửi hoặc soạn nháp (Parent Step 4)"]
            U4_1{"Kiểm tra điều kiện?"}:::utilBox
            U4_2["Nhóm TUYỆT MẬT hoặc<br/>DRAFT_PENDING_APPROVAL"]:::alertBox
            U4_3["Nhóm Bình thường &<br/>REPLY_ONLY"]:::successBox
            U4_1 -->|Có rủi ro / Tuyệt mật| U4_2
            U4_1 -->|An toàn| U4_3
        end

        subgraph S5["🔹 BƯỚC 5: Thực thi gửi tin hoặc lưu nháp (Parent Step 5)"]
            U5_1["areply_text(as_user=True)<br/>(Phát ngôn nhân danh cá nhân Sếp)"]:::successBox
            U5_2["PendingDraft Mongo Store<br/>(Lưu bản nháp status='pending')"]:::utilBox
            U5_3["Draft Card Formatter & DM<br/>(Gửi thẻ duyệt vào tin nhắn riêng Sếp)"]:::utilBox
            U4_3 --> U5_1
            U4_2 --> U5_2 --> U5_3
        end

    end

    InContext --> S1
    S1 --> S2
    S2 --> S3
    S3 --> S4
    
    U5_1 --> DoneGroup["💬 Hoàn tất gửi tin vào nhóm Lark"]:::successBox
    U5_3 --> DoneDM["📱 Chờ Sếp duyệt qua tin nhắn riêng (Gửi / Sửa / Bỏ)"]:::alertBox
```
