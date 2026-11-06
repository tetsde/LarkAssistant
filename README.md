# HiLark

HiLark là trợ lý AI kết nối trực tiếp các cuộc hội thoại trên Lark / Feishu với cơ sở tri thức (knowledge base) của dự án. Hệ thống hỗ trợ tra cứu thông tin nhanh chóng, tự động ghi nhận các quyết định cùng các cập nhật quan trọng trong luồng chat, đồng thời giữ lại các phản hồi chưa chắc chắn hoặc nhạy cảm để quản trị viên duyệt trước khi gửi.

Dự án là sự kết hợp chặt chẽ giữa pipeline xử lý tin nhắn thời gian thực, bộ lọc an toàn và phân loại ý định JEV, công cụ truy xuất dữ liệu ngữ nghĩa WeKnora, cùng MongoDB để lưu trữ dữ liệu tri thức dạng cấu trúc (entities & claims) và nhật ký hội thoại. 

Hiện tại, hệ thống đã được triển khai và vận hành ổn định trên hạ tầng **AWS EC2 (Instance type: `t8i.small`)**.

## Tổng quan

Trong môi trường làm việc nhóm, nội dung trao đổi không chỉ xoay quanh các câu hỏi nghiệp vụ. Nó bao gồm các quyết định kỹ thuật, thay đổi về nhân sự chịu trách nhiệm, cập nhật deadline đột xuất, và cả những cuộc trò chuyện xã giao hàng ngày. Một trợ lý AI hữu ích cần phải phân biệt chính xác từng loại tin nhắn trước khi đưa ra hành động xử lý.

HiLark được thiết kế xoay quanh 4 trọng tâm thực tế:

- **Lọc và phân loại tin nhắn:** Tránh gọi LLM một cách lãng phí đối với các tin nhắn chào hỏi, cảm ơn hoặc trò chuyện ngẫu nhiên.
- **Cập nhật tri thức động (Dynamic Knowledge):** Tự động trích xuất và cập nhật các dữ kiện vừa được xác nhận trong hội thoại; đảm bảo thông tin mới nhất luôn được ưu tiên hơn tài liệu tĩnh trong cơ sở dữ liệu cũ.
- **Phân tách phạm vi truy cập (Chat Scoping):** Giới hạn phạm vi tìm kiếm tài liệu theo đúng cơ sở tri thức (knowledge base) được gán riêng cho từng nhóm chat Lark.
- **Cơ chế duyệt phản hồi (Human-in-the-loop):** Tự động nhận diện câu trả lời nhạy cảm hoặc thiếu dữ liệu chứng thực để gửi bản nháp cho quản trị viên duyệt qua Direct Message (DM) thay vì trả lời bừa vào nhóm.

### Thành phần chính

| Thành phần | Trách nhiệm |
| --- | --- |
| **Lark / Feishu** | Điểm tiếp nhận sự kiện tin nhắn thời gian thực; giao diện tương tác và duyệt bản nháp |
| **FastAPI** | Cổng giao tiếp HTTP API và điều phối toàn bộ vòng đời ứng dụng |
| **JEV** | Động cơ phân loại ý định (intent classification) và kiểm duyệt an toàn nội dung (guardrail) |
| **WeKnora** | Cơ sở tri thức RAG chuyên dụng, truy xuất ngữ nghĩa văn bản |
| **MongoDB** | Quản lý Entities, Claims, hàng đợi hội thoại (staging), Daily Digests, Chat Scopes và Pending Drafts |
| **Gemini** | Trích xuất thông tin cấu trúc và sinh câu trả lời tự nhiên theo ngữ cảnh |

## Kiến trúc hệ thống

HiLark vận hành qua 4 tầng kiến trúc tuần tự:

```text
Lark Events (WebSocket)
    |
    v
+--------------------------------------+
| 1. Inbound Gateway                   |
| Kết nối WebSocket, hàng đợi (queue), |
| khử trùng lặp và gom cụm tin nhắn    |
+--------------------------------------+
    |
    v
+--------------------------------------+
| 2. Security & Intent Routing         |
| Kiểm tra vi phạm JEV, phân loại      |
| ý định, chống vòng lặp bot owner     |
+--------------------------------------+
    |
    v
+--------------------------------------+
| 3. Knowledge & Context               |
| Truy xuất WeKnora, claims MongoDB,   |
| luật ưu tiên, lọc đoạn trích liên quan|
+--------------------------------------+
    |
    v
+--------------------------------------+
| 4. Response & Delivery               |
| Gemini sinh nội dung, lọc mã nội bộ, |
| gửi vào Lark hoặc chuyển duyệt nháp  |
+--------------------------------------+
```

### Tầng 1 — Inbound Gateway

Tiếp nhận sự kiện từ Lark qua kết nối WebSocket bảo mật và chuẩn bị dữ liệu đầu vào.

Nhiệm vụ:
- Lắng nghe sự kiện thời gian thực từ Lark WebSocket.
- Lọc bỏ các tin nhắn bị gửi lặp (deduplication).
- Gom cụm các tin nhắn gửi nối tiếp trong khoảng thời gian ngắn để bảo toàn ngữ cảnh hoàn chỉnh.
- Đẩy các gói tin đã xử lý sơ bộ vào hàng đợi `ChatQueue` chuyển tiếp sang Tầng 2.

Module liên quan:
- `server/services/larkServices/lark_runner.py`
- `server/utils/chat_queue.py`

### Tầng 2 — Security & Intent Routing

JEV đóng vai trò chốt chặn đầu tiên, kiểm tra nội dung trước khi hệ thống thực hiện truy xuất tài liệu hay kích hoạt mô hình sinh ngữ cảnh.

Quy trình định tuyến gồm 3 bước:
1. Kiểm tra chủ đề cấm / nội dung nhạy cảm.
2. Phân loại ý định chính của người dùng.
3. Kích hoạt lớp bảo vệ: chống vòng lặp đối với chủ sở hữu hệ thống (bot owner) và áp dụng ngưỡng tin cậy (confidence score).

Module liên quan:
- `server/services/jev.py`
- `server/services/chat_service.py`

### Tầng 3 — Knowledge & Context

Kết hợp tài liệu tĩnh từ dataset WeKnora của nhóm chat cùng với các dữ kiện cấu trúc (claims) lưu trong MongoDB.

Nhiệm vụ:
- Tự động bóc tách thực thể (entities) và dữ kiện (claims) từ tin nhắn nghiệp vụ.
- Chỉ truy xuất tài liệu từ đúng `dataset_id` được gán cho nhóm chat hiện tại.
- Áp dụng bộ luật trong bộ nhớ và kiểm tra độ liên quan (relevance check) qua JEV đối với các đoạn trích xuất.
- Kết hợp dữ liệu RAG và các claims hiện hành, ưu tiên dữ kiện mới nhất nếu phát hiện ghi đè hoặc mâu thuẫn.

Module liên quan:
- `server/utils/llm_extractor.py`
- `server/services/weknora.py`
- `server/utils/rule_engine.py`
- `server/utils/context_composer.py`

### Tầng 4 — Response & Delivery

Sử dụng Gemini kết hợp với Persona cấu hình sẵn để hoàn thiện câu trả lời, gửi tự động tới nhóm hoặc chuyển hướng thành bản nháp cần duyệt.

Nhiệm vụ:
- Sinh nội dung câu trả lời dựa trên ngữ cảnh chặt chẽ đã qua tinh lọc.
- Loại bỏ các thẻ định dạng RAG hoặc mã XML nội bộ trước khi xuất kết quả.
- Gửi trực tiếp câu trả lời vào nhóm Lark nếu đạt đủ điều kiện tự động.
- Gửi thông báo kèm bản nháp (draft) đến DM của quản trị viên nếu rơi vào trường hợp cần phê duyệt thủ công.

Module liên quan:
- `server/services/llm_client.py`
- `server/utils/text_filter.py`
- `server/services/larkServices/lark_messenger.py`

## Cơ chế định tuyến ý định qua JEV

JEV giữ vai trò ra quyết định trung tâm trong pipeline: xác định tin nhắn nên bỏ qua, trích xuất dữ kiện, phản hồi tự động, hay chuyển duyệt nháp.

### Kiểm tra chủ đề hạn chế (Restricted-topic Check)

Kết hợp so khớp từ khóa và phân loại ngữ nghĩa nhằm phát hiện các chủ đề nhạy cảm, vi phạm chính sách nội bộ (kể cả khi sử dụng tiếng lóng hoặc diễn đạt gián tiếp).

Khi tin nhắn bị gắn cờ (flagged):
- HiLark tuyệt đối không phản hồi vào nhóm chat.
- Hệ thống gửi cảnh báo bảo mật ẩn đến quản trị viên được chỉ định.

### Bảng phân loại ý định (Intent Categories)

| Ý định (Intent) | Ý nghĩa | Hành vi xử lý |
| --- | --- | --- |
| `IGNORE` | Lời chào hỏi, cảm ơn, tán gẫu ngoài lề | Dừng xử lý ngay lập tức |
| `MEMORY_ONLY` | Cập nhật tiến độ, quyết định, phân công việc, thay đổi hạn chót | Bóc tách và lưu trữ dữ kiện; không trả lời vào nhóm |
| `REPLY_ONLY` | Câu hỏi nghiệp vụ được hỗ trợ đầy đủ bởi kho tri thức nhóm | Truy xuất tài liệu, tổng hợp câu trả lời và phản hồi vào nhóm |
| `MEMORY_AND_DRAFT` | Tin nhắn vừa cung cấp thông tin mới vừa yêu cầu quyết định/giải pháp | Lưu trữ dữ kiện mới và chuẩn bị bản nháp gửi admin duyệt |
| `DRAFT_PENDING_APPROVAL` | Câu hỏi nhạy cảm, thiếu dữ liệu chứng thực hoặc độ tin cậy thấp | Chuẩn bị bản nháp gửi admin xem xét và phê duyệt qua DM |

### Các cơ chế bảo vệ bổ sung

- **Chống lặp tin nhắn từ Owner (Owner Anti-loop):** Tin nhắn từ tài khoản owner được phân luồng riêng biệt: tin nhắn công việc chuyển sang `MEMORY_ONLY`, tin nhắn xã giao đưa vào `IGNORE`.
- **Ngưỡng tin cậy (Confidence Threshold):** Chỉ kích hoạt phản hồi tự động khi độ tin cậy của JEV đạt tối thiểu **`0.85`**. Mọi trường hợp dưới ngưỡng đều được chuyển sang luồng duyệt nháp.
- **Cơ chế dự phòng (Fail-safe):** Khi JEV gặp sự cố, các tin nhắn dài sẽ tự động chuyển thành bản nháp gửi admin duyệt; tin nhắn ngắn sẽ được bỏ qua.

### Kiểm tra độ liên quan của tài liệu RAG

Sau khi WeKnora trả về tối đa 5 đoạn tài liệu, JEV đánh giá mức độ tương quan của từng đoạn đối với câu hỏi:
- `IRRELEVANT`: Loại bỏ đoạn trích khỏi ngữ cảnh gửi đến LLM.
- `RELEVANT`: Giữ lại đoạn trích và sắp xếp thứ tự ưu tiên theo điểm tương quan.
- **Không có đoạn trích nào đạt:** Tự động định tuyến sang `DRAFT_PENDING_APPROVAL`.

## Luồng xử lý tin nhắn tổng thể

```text
Tiếp nhận tin nhắn
      |
      v
Kiểm tra chủ đề hạn chế
      |
      +-- Vi phạm --> Không trả lời nhóm + Gửi cảnh báo Admin DM --> Kết thúc
      |
      v
Phân loại ý định (JEV)
      |
      +-- IGNORE
      |      Dừng xử lý
      |
      +-- MEMORY_ONLY
      |      Bóc tách dữ kiện -> Cập nhật MongoDB -> Kết thúc
      |
      +-- REPLY_ONLY
      |      Truy xuất tài liệu được phân quyền
      |      -> Kiểm tra độ liên quan
      |      -> Tổng hợp ngữ cảnh
      |      -> Sinh câu trả lời
      |      -> Gửi trực tiếp vào nhóm
      |
      +-- MEMORY_AND_DRAFT
      |      Lưu dữ kiện mới
      |      -> Chuẩn bị bản nháp phản hồi
      |      -> Gửi Admin DM chờ duyệt
      |
      +-- DRAFT_PENDING_APPROVAL
             Chuẩn bị bản nháp phản hồi
             -> Gửi Admin DM chờ duyệt
```

Sơ đồ chi tiết có thể xem tại:
- Sơ đồ hoạt động chi tiết JEV: `server/docs/jev/so_do_hoat_dong_chi_tiet_jev_memory_reply.png`
- Sơ đồ 4 tầng kiến trúc: `server/docs/so_do_luong_hoat_dong_4_lop_chi_tiet.png`

## Bộ nhớ cấu trúc và quản lý cập nhật dữ kiện (Claims)

HiLark lưu trữ tri thức dạng cấu trúc trong MongoDB thông qua mô hình Entity-Claim:

| Collection | Mục đích sử dụng |
| --- | --- |
| `memories` | Danh mục thực thể: dự án, nhân sự, module, khách hàng... |
| `claims` | Dữ kiện gắn với thực thể, kèm trạng thái và lịch sử thay thế |
| `conversation_staging` | Lưu tạm các tin nhắn hội thoại chờ tổng hợp Daily Digest |
| `daily_digests` | Bản tổng kết ngày chờ duyệt trước khi đẩy vào WeKnora |
| `chat_scopes` | Bảng liên kết giữa `chat_id` (Lark) và `dataset_id` (WeKnora) |
| `pending_drafts` | Các bản nháp phản hồi đang chờ quản trị viên phê duyệt |

Trạng thái vòng đời của một Claim:
- `current`: Dữ kiện hiện hành có hiệu lực cao nhất.
- `superseded`: Đã bị thay thế bởi một dữ kiện mới hơn.
- `conflicted`: Mâu thuẫn với dữ kiện khác, cần quản trị viên đối soát.

### Ví dụ về ghi đè dữ kiện

```text
Thực thể: Dự án Cổng thanh toán (Payment project)

Dữ kiện cũ:
  leader = "Nam"
  status = SUPERSEDED

Dữ kiện mới:
  leader = "Nguyên"
  status = CURRENT
  replaces = Dữ kiện cũ
```

Khi có câu hỏi *"Ai đang phụ trách dự án Cổng thanh toán?"*, bộ phận tổng hợp ngữ cảnh (Context Composer) sẽ tự động ưu tiên dữ kiện mới nhất mà vẫn bảo toàn dấu vết lịch sử thay đổi.

## Cách ly phạm vi tri thức theo nhóm chat

Mỗi nhóm chat Lark được ánh xạ cố định tới một kho dữ liệu WeKnora thông qua `chat_scopes`.

Khi HiLark thực hiện truy xuất, hệ thống chỉ truy vấn đúng `dataset_id` đã được cấp phép cho nhóm chat đó. Tài liệu thuộc các dataset khác hoàn toàn bị loại trừ khỏi phạm vi tìm kiếm.

Ràng buộc truy vấn được áp dụng ngay tại bước khởi tạo:

```python
knowledge_ids = [scope_doc["dataset_id"]]
```

Chỉ những người dùng nằm trong danh sách quản trị viên `ADMIN_USERS` mới có quyền thay đổi liên kết dữ liệu của nhóm thông qua lệnh `set-kb` hoặc `reset-kb`.

## Cơ chế phê duyệt bản nháp (Draft Approval)

Khi gặp câu hỏi nhạy cảm, câu hỏi vượt ngoài phạm vi tài liệu, hoặc độ tin cậy chưa đạt chuẩn, HiLark chủ động tạo bản nháp thay vì trả lời sai lệch vào nhóm.

Bản nháp được gửi qua Lark Direct Message (DM) tới quản trị viên. Quản trị viên có các tùy chọn:
- **Gửi (Send):** Xuất bản ngay nội dung bản nháp vào nhóm chat.
- **Sửa (Edit):** Chỉnh sửa lại câu trả lời theo ý muốn trước khi hệ thống gửi vào nhóm.
- **Hủy (Discard):** Hủy bỏ bản nháp và không gửi phản hồi vào nhóm.

Quy trình này đảm bảo quyền quyết định cuối cùng luôn thuộc về con người trong các tình huống thiếu hụt thông tin hoặc cần bảo mật cao.

## Báo cáo tổng kết ngày (Daily Digest)

HiLark tự động lập báo cáo tổng hợp từ dữ liệu thu thập được trong ngày tại `conversation_staging`.

Thời gian chạy được quy định bởi cấu hình `digest_schedule_time` (mặc định cấu hình lúc `23:00`).

Nội dung tổng hợp được phân tách rõ ràng thành 3 mục:
- **Quyết định (Decisions):** Các chính sách, giải pháp kỹ thuật và lựa chọn kiến trúc đã thống nhất.
- **Cam kết & Phân công (Commitments):** Ai đảm nhận việc gì, cho ai và hạn chót khi nào.
- **Tiến độ & Trở ngại (Status & Milestones):** Các đầu việc hoàn thành, cột mốc đạt được và các vướng mắc (blockers).

Bản tổng hợp được gửi đến người duyệt chỉ định (`digest_approver_id`). Sau khi được duyệt, HiLark sẽ tự động chuyển hóa thành định dạng Markdown và đồng bộ trực tiếp vào cơ sở tri thức WeKnora.

## Tích hợp Lark Base (Bitable)

Pipeline Lark Base đảm nhận việc đọc dữ liệu bảng và bản ghi từ Lark Base để phục vụ tra cứu nội bộ:
1. Thu thập cấu trúc bảng, trường dữ liệu và các bản ghi chi tiết.
2. Làm sạch và chuẩn hóa dữ liệu đầu vào.
3. Lưu trữ dữ liệu chuẩn hóa phục vụ tra cứu nhanh.

Module liên quan:
- `server/utils/larkbase/cleaner.py`

## Cấu trúc thư mục dự án

```text
HiLark/
├── README.md
├── .env
├── server/
│   ├── main.py
│   ├── run_lark_bot.py
│   ├── pyproject.toml
│   ├── core/
│   │   └── config.py
│   ├── database/
│   │   └── db.py
│   ├── models/
│   │   ├── chat.py
│   │   ├── chat_scope.py
│   │   ├── digest.py
│   │   ├── lark.py
│   │   ├── larkbase.py
│   │   └── memory.py
│   ├── routers/
│   │   ├── chat.py
│   │   ├── digest.py
│   │   ├── health.py
│   │   ├── lark.py
│   │   └── scope.py
│   ├── services/
│   │   ├── bot_service.py
│   │   ├── chat_service.py
│   │   ├── digest_service.py
│   │   ├── draft_service.py
│   │   ├── draft_store.py
│   │   ├── jev.py
│   │   ├── larkServices/
│   │   │   ├── lark_client.py
│   │   │   ├── lark_dispatcher.py
│   │   │   ├── lark_messenger.py
│   │   │   └── lark_runner.py
│   │   ├── larkbase.py
│   │   ├── llm_client.py
│   │   ├── scope_service.py
│   │   └── weknora.py
│   ├── utils/
│   │   ├── chat_queue.py
│   │   ├── context_composer.py
│   │   ├── digest.py
│   │   ├── lark_token.py
│   │   ├── larkbase/
│   │   │   └── cleaner.py
│   │   ├── llm_extractor.py
│   │   ├── rule_engine.py
│   │   └── text_filter.py
│   ├── docs/
│   │   ├── so_do_luong_hoat_dong_4_lop.md
│   │   ├── so_do_luong_hoat_dong_4_lop_chi_tiet.png
│   │   ├── jev/
│   │   ├── layer1/
│   │   ├── layer2/
│   │   ├── layer3/
│   │   ├── layer4/
│   │   ├── permission/
│   │   └── LarkBase/
│   └── tests/
│       ├── full_pipeline.py
│       ├── test_chat_scope.py
│       ├── test_context_composer.py
│       ├── test_daily_digest.py
│       ├── test_interactive.py
│       ├── test_lark_service.py
│       ├── test_llm_client.py
│       └── test_token_ping.py
├── labs/
└── WeKnora/
```

## Yêu cầu môi trường & Cài đặt

### Hạ tầng & Yêu cầu phần mềm

- **Hạ tầng Production:** Đã kiểm thử và chạy thực tế trên **AWS EC2 (Instance type: `t8i.small`)**.
- **Hệ điều hành:** Linux (Ubuntu 22.04+ khuyên dùng), macOS, hoặc Windows WSL2.
- **Python:** `>= 3.13`
- **Trình quản lý gói:** [`uv`](https://docs.astral.sh/uv/) (tối ưu hóa tốc độ đóng gói và quản lý virtualenv)
- **Cơ sở dữ liệu:** MongoDB (v6.0+)
- **Dịch vụ phụ thuộc:**
  - Một instance WeKnora API v1 đang chạy.
  - Ứng dụng Lark / Feishu cấu hình đầy đủ quyền bot và webhook/WebSocket.
  - API key cho dịch vụ JEV và Gemini.

### Cài đặt dependencies

Từ thư mục gốc của repository:

```bash
cd server
uv sync
```

### Cấu hình biến môi trường

Tạo file `.env` tại thư mục gốc của repository:

```env
# JEV & Gemini Credentials
jev_api=your_jev_api_key
gemini_api=your_gemini_api_key

# WeKnora Knowledge Base
api_weknora=your_weknora_api_key
base_url=http://localhost/api/v1
dataset_id=your_default_dataset_id

# MongoDB
mongo_url=mongodb://localhost:27017
mongo_db=LarkAssistant
mongo_memory_collection=memories
mongo_claims_collection=claims
mongo_staging_collection=conversation_staging
mongo_digest_collection=daily_digests
mongo_chat_scope_collection=chat_scopes

# Lark / Feishu Application
app_id=your_lark_app_id
app_secret=your_lark_app_secret
verification_token=your_verification_token
encrypt_key=your_encrypt_key
lark_domain=https://open.larksuite.com

# User Access Token & Permissions
access_token_user=your_user_access_token
user_open_id=your_lark_open_id

# Cấu hình Daily Digest
digest_schedule_time=23:00
digest_require_approval=true
digest_approver_id=your_approver_open_id

# Cấu hình kiểm tra DM (Tùy chọn)
ENABLE_DM_POLLING=false
DM_POLL_INTERVAL=60.0
```

> **Lưu ý:** Tuyệt đối không commit file `.env` chứa thông tin nhạy cảm lên Git repository.

## Vận hành hệ thống

### Khởi chạy toàn bộ hệ thống (API, Lark Bot và Scheduler)

Từ thư mục `server`:

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Lệnh này khởi động ứng dụng FastAPI đồng thời kích hoạt kết nối Lark WebSocket và bộ lập lịch Daily Digest theo vòng đời của ứng dụng.

Tài liệu Swagger UI:
`http://localhost:8000/docs`

### Chạy tiến trình Lark Bot độc lập

Nếu chỉ cần chạy tiến trình kết nối Lark bot:

```bash
uv run python run_lark_bot.py
```

## Kiểm thử (Tests)

Thực hiện các lệnh kiểm thử từ thư mục `server`:

```bash
# Kiểm tra tính hợp lệ của Lark User Access Token
uv run python utils/lark_token.py

# Kiểm tra tổng hợp ngữ cảnh và cơ chế ghi đè claim
PYTHONPATH=. uv run python tests/test_context_composer.py

# Kiểm tra phân quyền truy xuất chat scope
PYTHONPATH=. uv run python tests/test_chat_scope.py

# Kiểm tra trích xuất và phê duyệt Daily Digest
PYTHONPATH=. uv run python tests/test_daily_digest.py

# Chạy kiểm thử trích xuất dữ kiện tương tác
PYTHONPATH=. uv run python tests/test_interactive.py --scenario

# Kiểm thử luồng xử lý toàn diện qua một câu hỏi mẫu
PYTHONPATH=. uv run python tests/full_pipeline.py --single "Hiện tại ai đang phụ trách dự án?"
```

## Danh mục lệnh điều khiển trên Lark

### Nhóm chat (Group Chat)

| Lệnh | Quyền hạn | Mô tả |
| --- | --- | --- |
| `get-kb` hoặc `xem kb` | Tất cả thành viên | Xem dataset WeKnora hiện đang gán cho nhóm chat |
| `set-kb <dataset_id>` | Quản trị viên (Admin) | Gán một dataset WeKnora cụ thể cho nhóm chat |
| `reset-kb` | Quản trị viên (Admin) | Hủy gán tùy chỉnh, khôi phục về dataset mặc định |

### Tin nhắn riêng (Direct Message - DM)

| Cú pháp | Mô tả |
| --- | --- |
| `Gửi`, `OK`, hoặc `Duyệt` | Duyệt và cho phép gửi bản nháp vào nhóm chat |
| `Sửa: <nội dung mới>` | Chỉnh sửa nội dung bản nháp trước khi gửi |
| `Bỏ` hoặc `Hủy` | Hủy bỏ bản nháp hiện tại |
| `Xem digest` | Xem bản tổng hợp Daily Digest đang chờ duyệt |
| `Duyệt digest` | Phê duyệt và đẩy nội dung Daily Digest vào WeKnora |
| `Hủy digest` | Hủy bản Daily Digest đang chờ |

## Danh mục API chính

| Phương thức | Endpoint | Chức năng |
| --- | --- | --- |
| `POST` | `/api/chat/pipeline` | Xử lý tin nhắn thủ công qua pipeline chat |
| `POST` | `/api/chat/approve-draft` | Phê duyệt bản nháp phản hồi |
| `GET` | `/api/chat/entities` | Lấy danh sách các thực thể đang lưu trữ |
| `GET` | `/api/chat/facts` | Lấy danh sách claims và trạng thái hiệu lực |
| `GET` | `/api/digests/pending/latest` | Lấy bản Daily Digest gần nhất đang chờ duyệt |
| `POST` | `/api/digests/{digest_id}/approve` | Duyệt và đồng bộ Daily Digest vào WeKnora |
| `GET` | `/api/v1/scopes` | Danh sách cấu hình phân quyền chat-to-knowledge-base |
| `GET` | `/health` | Kiểm tra trạng thái hoạt động của hệ thống |

## Tài liệu kỹ thuật chuyên sâu

Xem tài liệu kiến trúc và hướng dẫn triển khai chi tiết tại thư mục `server/docs/`:

- [Kiến trúc luồng 4 tầng](server/docs/so_do_luong_hoat_dong_4_lop.md)
- [Chi tiết kỹ thuật và cơ chế kiểm soát JEV](server/docs/jev/jev_architecture_spec.md)
- [Tầng 1 — Inbound Gateway & ChatQueue](server/docs/layer1/inbound_gateway_deep_dive.md)
- [Tầng 2 — Security Gating & Phân loại ý định](server/docs/layer2/security_gating_deep_dive.md)
- [Tầng 3 — Quản lý tri thức, Claims & Tổng hợp ngữ cảnh](server/docs/layer3/knowledge_context_deep_dive.md)
- [Tầng 4 — Persona sinh phản hồi & Kênh phân phối](server/docs/layer4/persona_delivery_deep_dive.md)
- [Kiến trúc phân quyền và bảo mật dữ liệu](server/docs/permission/security_architecture_spec.md)
- [Quy trình đồng bộ dữ liệu Lark Base](server/docs/LarkBase/sync_pipeline_deep_dive.md)

---

*Phát triển bởi Tống Phước Hoài Nam và đội ngũ phát triển dự án HiLark.*