# HiLark

**Trợ lý AI hỗ trợ quản lý hội thoại và tri thức doanh nghiệp trên Lark.**

HiLark là dự án xây dựng trợ lý AI tích hợp với hệ sinh thái [Lark / Feishu](https://www.larksuite.com/), nhằm hỗ trợ doanh nghiệp quản lý thông tin từ các cuộc hội thoại, khai thác tài liệu nội bộ và theo dõi những thay đổi trong quá trình vận hành.

Thay vì xử lý từng tin nhắn như một yêu cầu độc lập, HiLark kết nối dữ liệu hội thoại với kho tri thức doanh nghiệp và một lớp bộ nhớ có cấu trúc. Nhờ đó, hệ thống có thể ghi nhận thông tin quan trọng, theo dõi các thay đổi và sử dụng ngữ cảnh phù hợp khi trả lời.

Dự án tập trung vào việc xây dựng một trợ lý AI có khả năng hoạt động trong môi trường nhiều doanh nghiệp, hỗ trợ nhiều nhà cung cấp LLM và kết hợp quy trình phê duyệt của con người khi cần thiết.

**Trạng thái triển khai:** AWS EC2 · Docker

---

## 1. Tổng quan

HiLark tập trung vào ba nhóm chức năng chính:

- **Xử lý hội thoại:** Tiếp nhận và phân tích tin nhắn, tài liệu được chia sẻ trong các nhóm chat và tin nhắn trực tiếp trên Lark.
- **Quản lý tri thức:** Kết hợp truy xuất tài liệu với bộ nhớ có cấu trúc để lưu trữ và cập nhật thông tin doanh nghiệp.
- **Hỗ trợ quy trình làm việc:** Tạo câu trả lời, bản nháp và báo cáo tổng hợp hằng ngày, kết hợp cơ chế phê duyệt khi cần thiết.

### Các chức năng chính

| Nhóm chức năng | Mô tả |
|---|---|
| Lark Integration | Kết nối và xử lý sự kiện thông qua Lark Open API |
| Multi-Tenant | Phân tách dữ liệu và ngữ cảnh xử lý giữa các doanh nghiệp |
| Hybrid RAG | Truy xuất tri thức bằng Vector Search và BM25 thông qua WeKnora |
| Dynamic Claims | Trích xuất và theo dõi thông tin có cấu trúc từ hội thoại |
| Human-in-the-Loop | Hỗ trợ con người kiểm tra và phê duyệt thông tin |
| Daily Digest | Tổng hợp hoạt động theo ngày ở cấp nhóm và doanh nghiệp |
| Multi-Provider LLM | Hỗ trợ Gemini, OpenAI, Claude và các API tương thích OpenAI |
| BYOK | Cho phép người dùng cấu hình API Key cá nhân |
| Document Processing | Xử lý tài liệu văn phòng, hình ảnh và tài liệu Lark |
| Interactive Cards | Tương tác với hệ thống thông qua các thẻ chức năng trên Lark |

---

## 2. Kiến trúc hệ thống

HiLark được tổ chức thành bốn lớp xử lý chính, kết hợp với cơ chế hàng đợi bất đồng bộ.

```text
                   Lark Client
                        |
                        v
          +----------------------------+
          | 1. Gateway & Dispatcher    |
          |                            |
          | - Tiếp nhận Webhook        |
          | - Khử trùng lặp tin nhắn   |
          | - Xác định Tenant          |
          | - Hàng đợi xử lý           |
          +--------------+-------------+
                         |
                         v
          +----------------------------+
          | 2. JEV Gatekeeper          |
          |                            |
          | - Phân loại ý định         |
          | - Kiểm tra nội dung        |
          | - Điều hướng xử lý         |
          +--------------+-------------+
                         |
                         v
          +----------------------------+
          | 3. Cognitive Engine        |
          |                            |
          | - Phân tích tài liệu       |
          | - Hybrid RAG                |
          | - Dynamic Claims           |
          | - Tổng hợp ngữ cảnh        |
          | - Che thông tin nhạy cảm   |
          +--------------+-------------+
                         |
                         v
          +----------------------------+
          | 4. Execution & HITL        |
          |                            |
          | - Sinh phản hồi bằng LLM   |
          | - Interactive Cards        |
          | - Phê duyệt bản nháp       |
          | - Daily Digest             |
          +--------------+-------------+
                         |
                         v
                    Lark Client
```

### 2.1. Gateway & Dispatcher

Đây là lớp tiếp nhận sự kiện từ Lark và điều phối chúng đến các thành phần xử lý tương ứng.

Các nhiệm vụ chính:

- Tiếp nhận sự kiện thông qua Webhook.
- Khử trùng lặp tin nhắn.
- Xác định doanh nghiệp tương ứng với yêu cầu.
- Điều phối xử lý tin nhắn bất đồng bộ.
- Quản lý Debounce, Cooldown và giới hạn xử lý đồng thời.
- Phân luồng tin nhắn, tài liệu và thao tác trên Interactive Cards.

Hệ thống sử dụng ChatQueue để kiểm soát luồng xử lý, hạn chế các yêu cầu trùng lặp và tránh tạo quá nhiều tác vụ đồng thời.

### 2.2. JEV Gatekeeper

Trước khi đi vào pipeline xử lý AI chính, tin nhắn được đưa qua một lớp phân loại ban đầu.

Hệ thống sử dụng bốn nhóm kết quả:

| Nhãn | Ý nghĩa |
|---|---|
| `IGNORE` | Bỏ qua nội dung không cần xử lý |
| `MEMORY_ONLY` | Ghi nhận thông tin có giá trị đối với bộ nhớ |
| `REPLY_ONLY` | Xử lý yêu cầu cần phản hồi |
| `DRAFT` | Tạo bản nháp để kiểm tra trước khi gửi |

Lớp này giúp loại bỏ sớm những tin nhắn không cần thiết, đồng thời giảm số lần gọi LLM cho các trường hợp không cần đi qua pipeline đầy đủ.

### 2.3. Cognitive Engine

Đây là lớp kết hợp giữa truy xuất tài liệu và bộ nhớ có cấu trúc.

**Truy xuất tri thức**

HiLark tích hợp với WeKnora để tìm kiếm thông tin trong kho tài liệu thông qua:

- Vector Search.
- BM25.
- Lựa chọn Dataset theo Chat Scope.

**Dynamic Claims**

Hệ thống trích xuất các thực thể và mệnh đề thông tin từ hội thoại, sau đó lưu trữ trong MongoDB.

Ví dụ:

```text
Dự án: Alpha

Thông tin 1:
Deadline: 20/11
Trạng thái: Current

Thông tin 2:
Deadline: 15/11
Trạng thái: Superseded
```

Cách tổ chức này giúp hệ thống phân biệt thông tin hiện hành với thông tin đã thay đổi.

**Tổng hợp ngữ cảnh**

Khi tạo câu trả lời, HiLark kết hợp thông tin từ tài liệu được truy xuất với các Claims đã được xác nhận.

Nguyên tắc ưu tiên:

`CURRENT Claims > Static WeKnora Documents`

Điều này giúp trợ lý sử dụng thông tin mới nhất mà không cần lập chỉ mục lại toàn bộ kho tài liệu mỗi khi có thay đổi.

**Xử lý thông tin nhạy cảm**

Rule Engine thực hiện Line-level Redaction nhằm che các thông tin được xác định là nhạy cảm trước khi chuyển đến các bước xử lý tiếp theo.

### 2.4. Execution & Human-in-the-Loop

Lớp cuối cùng chịu trách nhiệm tạo phản hồi và điều phối các quy trình nghiệp vụ.

Tùy thuộc vào loại yêu cầu và quy tắc xử lý, hệ thống có thể:

- Phản hồi trực tiếp trong nhóm chat.
- Tạo bản nháp để quản trị viên kiểm tra.
- Trích xuất thông tin phục vụ bộ nhớ doanh nghiệp.
- Tổng hợp thông tin đề xuất vào Daily Digest.
- Tạo báo cáo tổng hợp ở cấp doanh nghiệp.

Human-in-the-Loop được sử dụng để đảm bảo những thông tin cần xác nhận được kiểm tra trước khi trở thành dữ liệu hiện hành trong hệ thống.

---

## 3. Các chức năng nổi bật

### 3.1. Kiến trúc Multi-Tenant

HiLark được thiết kế để hỗ trợ nhiều doanh nghiệp trên cùng một hệ thống triển khai.

Ngữ cảnh Tenant được xác định và truyền xuyên suốt các luồng xử lý:

- Chat Processing.
- Document Ingestion.
- Claims và Memories.
- Digest Generation.
- User Settings.
- LLM Configuration và Token Management.

MongoDB sử dụng các Compound Index có chứa `tenant_key` để hỗ trợ truy vấn theo phạm vi doanh nghiệp.

Tầng xác thực sử dụng TokenBroker tập trung với các cơ chế:

- Cache token theo `(tenant_key, app_id, kind)`.
- Single-Flight Lock để hạn chế các yêu cầu làm mới token đồng thời.
- Chủ động làm mới token trước thời điểm hết hạn.
- Background Sweeper để kiểm tra và dọn dẹp dữ liệu định kỳ.

OAuth State Registry sử dụng state dùng một lần và TTL Index để hỗ trợ bảo vệ quy trình xác thực trước các yêu cầu CSRF.

### 3.2. Dynamic Claims & Organizational Memory

Tài liệu tĩnh không phải lúc nào cũng phản ánh chính xác tình trạng hiện tại của doanh nghiệp, đặc biệt khi thông tin dự án, nhân sự hoặc thời hạn công việc liên tục thay đổi.

HiLark giải quyết vấn đề này bằng một lớp Claims có cấu trúc.

Quy trình hoạt động:

1. Trích xuất thông tin từ hội thoại.
2. Chuyển đổi thành các thực thể và Claims có cấu trúc.
3. Lưu thông tin do nhân viên đề xuất với trạng thái `proposed`.
4. Tổng hợp các đề xuất vào Daily Digest.
5. Quản trị viên kiểm tra và phê duyệt.
6. Chuyển thông tin được duyệt sang trạng thái `current`.

Việc phân biệt giữa `proposed` và `current` giúp hệ thống không mặc định xem mọi thông tin xuất hiện trong hội thoại đều là thông tin đã được xác nhận.

### 3.3. Interactive Card Hub

HiLark sử dụng Lark Interactive Cards làm giao diện tương tác chính.

Executive Control Hub cung cấp các chức năng:

- Quản trị Lark Base.
- Truy cập WeKnora Console.
- Hướng dẫn thiết lập hệ thống.
- Xem Daily Digest.
- Kiểm tra trạng thái vận hành.
- Truy cập thông tin tài khoản WeKnora.

Master Daily Digest hỗ trợ xem thông tin tổng hợp, kiểm tra các đề xuất và phê duyệt hoặc từ chối thông tin trực tiếp thông qua các nút tương tác.

### 3.4. Multi-Provider LLM & BYOK

HiLark hỗ trợ nhiều nhà cung cấp mô hình ngôn ngữ:

| Nhà cung cấp | Hỗ trợ |
|---|---|
| Google Gemini | Có |
| OpenAI | Có |
| Anthropic Claude | Có |
| OpenAI-compatible APIs | Có |

Các dịch vụ tương thích có thể bao gồm DeepSeek, Ollama, vLLM và Azure.

Thứ tự ưu tiên khi lựa chọn API Key:

```text
Request Override
       |
       v
User BYOK
       |
       v
Project Chat Scope
       |
       v
System Default
```

API Key do người dùng cung cấp được mã hóa trước khi lưu vào MongoDB bằng Fernet.

Ngoài ra, người dùng có thể cấu hình Base URL, Timeout và kiểm tra kết nối đến nhà cung cấp.

### 3.5. Document Processing

HiLark hỗ trợ xử lý nhiều nguồn tài liệu:

| Nguồn dữ liệu | Phương thức xử lý |
|---|---|
| PDF | WeKnora AnyDoc |
| DOCX | WeKnora AnyDoc |
| XLSX | WeKnora AnyDoc |
| PPTX | WeKnora AnyDoc |
| PNG / JPG / JPEG / WEBP | Gemini Vision |
| Lark Docs | Lark Open API |
| Lark Wiki | Lark Open API |
| Lark Drive | Lark Open API |

Quy trình nạp tài liệu sử dụng MD5 Hash để kiểm tra thay đổi nội dung, hạn chế việc lập chỉ mục lại các tài liệu không thay đổi.

### 3.6. Automated Onboarding

Hệ thống hỗ trợ thiết lập môi trường cho doanh nghiệp mới thông qua quy trình Onboarding.

Các bước chính:

- Tạo Lark Base.
- Khởi tạo hai bảng Chat Scopes và Policies.
- Cấp phát cấu trúc kho tri thức trên WeKnora.
- Tạo tài khoản quản trị.
- Thiết lập cấu hình cho từng Tenant.
- Hướng dẫn thiết lập thông qua giao diện tương tác.

Hệ thống vận hành theo mô hình **Custom App Multi-Tenant** trên Lark Open Platform (mỗi doanh nghiệp đăng ký cặp App ID / App Secret riêng).

---

## 4. Công nghệ sử dụng

| Thành phần | Công nghệ |
|---|---|
| Backend | Python, FastAPI |
| Database | MongoDB 7.0 |
| Knowledge Engine | WeKnora |
| Retrieval | Vector Search, BM25 |
| LLM | Gemini, OpenAI, Claude |
| Document Parsing | WeKnora AnyDoc, gRPC |
| Image Understanding | Gemini Vision |
| Integration | Lark Open API |
| Authentication | OAuth 2.0 |
| Encryption | Fernet |
| Containerization | Docker, Docker Compose |
| Deployment | AWS EC2 |
| Testing | Pytest |

---

## 5. Cấu trúc dự án

```text
HiLark/
├── docker-compose.all-in-one.yml
├── docker-compose.prod.yml
├── deploy.sh
│
├── docs/
│   └── project-memory/
│       ├── PROJECT_CONTEXT.md
│       ├── HANDOFF.md
│       ├── DECISIONS.md
│       └── TECHNICAL_DEBT.md
│
├── server/
│   ├── main.py
│   ├── Dockerfile
│   ├── pyproject.toml
│   │
│   ├── core/
│   ├── database/
│   ├── models/
│   ├── routers/
│   ├── services/
│   │   ├── ai/
│   │   ├── auth/
│   │   ├── knowledge/
│   │   ├── lark/
│   │   ├── tenancy/
│   │   └── workflows/
│   │
│   ├── templates/
│   └── tests/
│
└── WeKnora/
```

### Các module chính

| Module | Chức năng |
|---|---|
| `core/` | Cấu hình ứng dụng, HTTP Client và xử lý ngoại lệ |
| `database/` | Kết nối MongoDB và quản lý Index |
| `models/` | Pydantic Schema và Data Model |
| `routers/` | REST API và Webhook |
| `services/ai/` | Tích hợp LLM và phân loại tin nhắn |
| `services/auth/` | OAuth, TokenBroker và xác thực |
| `services/knowledge/` | Tích hợp WeKnora, truy xuất và tổng hợp ngữ cảnh |
| `services/lark/` | Xử lý sự kiện Lark và Interactive Cards |
| `services/tenancy/` | Phân giải Tenant và quản lý vòng đời |
| `services/workflows/` | Các quy trình Chat, Claims, Digest và Draft Approval |

---

## 6. Thiết kế cơ sở dữ liệu

HiLark sử dụng MongoDB để quản lý dữ liệu ứng dụng.

Các Collections chính:

| Collection | Chức năng |
|---|---|
| `tenants` | Thông tin doanh nghiệp và trạng thái hoạt động |
| `claims` | Thông tin, quyết định và các mệnh đề có cấu trúc |
| `memories` | Thực thể, dự án và thông tin nhân sự |
| `conversation_staging` | Vùng lưu trữ tạm thời dữ liệu hội thoại |
| `chat_scopes` | Ánh xạ giữa nhóm chat và Dataset |
| `daily_digests` | Báo cáo hằng ngày của từng nhóm chat |
| `master_daily_digests` | Báo cáo tổng hợp cấp doanh nghiệp |
| `draft_logs` | Nhật ký bản nháp chờ phê duyệt |
| `lark_auth` | Thông tin xác thực Lark |
| `oauth_states` | State phục vụ xác thực OAuth |
| `user_settings` | Cấu hình người dùng và API Key đã mã hóa |
| `system_config` | Cấu hình động của hệ thống |
| `cost_telemetry` | Theo dõi chi phí và độ trễ của LLM/JEV |

Các Compound Index được thiết kế để hỗ trợ truy vấn theo `tenant_key`, giúp giới hạn phạm vi dữ liệu giữa các doanh nghiệp.

---

## 7. Cài đặt và khởi chạy

HiLark hỗ trợ hai phương thức triển khai.

### Cách 1: Docker All-in-One

Đây là phương thức khởi chạy toàn bộ các dịch vụ bằng Docker Compose.

**Yêu cầu**

- Docker.
- Docker Compose.
- Lark Application Credentials.
- API Key của các dịch vụ AI cần sử dụng.

**Bước 1. Clone repository**

```bash
git clone https://github.com/tetsde/LarkAssistant.git

cd LarkAssistant
```

**Bước 2. Cấu hình môi trường**

```bash
cp .env.production.example .env
```

Chỉnh sửa các biến môi trường:

```bash
nano .env
```

Cấu hình thông tin MongoDB, khóa mã hóa, AI Provider, WeKnora và Lark Credentials.

Có thể tạo Fernet Key bằng lệnh:

```bash
uv run python -c \
"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Sử dụng giá trị được tạo cho `ENCRYPTION_SECRET_KEY`.

**Bước 3. Khởi chạy hệ thống**

```bash
docker compose \
  -f docker-compose.all-in-one.yml \
  up -d
```

**Bước 4. Kiểm tra trạng thái**

```bash
docker compose \
  -f docker-compose.all-in-one.yml \
  ps
```

Cấu hình All-in-One bao gồm bảy dịch vụ:

| Dịch vụ | Chức năng |
|---|---|
| `hilark-server` | Backend FastAPI |
| `mongodb` | Cơ sở dữ liệu ứng dụng |
| `weknora-app` | Động cơ truy xuất tri thức |
| `weknora-docreader` | Dịch vụ phân tích tài liệu |
| `weknora-postgres` | Cơ sở dữ liệu ParadeDB / pgvector |
| `weknora-redis` | Cache và Queue |
| `weknora-frontend` | Giao diện quản trị WeKnora |

### Cách 2: Local Development

**Yêu cầu**

- Python 3.13 trở lên.
- [uv](https://docs.astral.sh/uv/).
- MongoDB 7.0 hoặc MongoDB Atlas.
- Một instance WeKnora đang hoạt động.

**Bước 1. Cài đặt dependencies**

```bash
cd server

uv venv

source .venv/bin/activate

uv sync
```

**Bước 2. Cấu hình biến môi trường**

Tạo file `.env` tại thư mục gốc:

```env
ENVIRONMENT=development

# MongoDB
MONGO_URL=mongodb://localhost:27017
MONGO_DB=LarkAssistant

# Encryption
ENCRYPTION_SECRET_KEY=your_fernet_key

# AI Providers
JEV_API_KEY=your_jev_api_key
GEMINI_API_KEY=your_gemini_api_key

# WeKnora
WEKNORA_API_KEY=your_weknora_api_key
BASE_URL=http://localhost:8080/api/v1

DOCREADER_GRPC_HOST=127.0.0.1
DOCREADER_GRPC_PORT=50051

# Lark
APP_BASE_URL=http://localhost:8000

# Processing
DEBOUNCE_DELAY_SECONDS=1.75
USER_COOLDOWN_SECONDS=4.0
MAX_CONCURRENT_CHAT_PIPELINES=3
```

Bổ sung các biến môi trường khác theo cấu hình triển khai thực tế.

**Bước 3. Khởi chạy Backend**

```bash
cd server

uv run uvicorn main:app \
  --reload \
  --host 0.0.0.0 \
  --port 8000
```

Các địa chỉ truy cập:

| Dịch vụ | Địa chỉ |
|---|---|
| Swagger UI | `http://localhost:8000/docs` |
| Health Check | `http://localhost:8000/health` |
| Setup | `http://localhost:8000/setup` |

---

## 8. Tích hợp Lark

Để kết nối HiLark với Lark, cần thực hiện các bước sau:

**Bước 1. Đăng ký ứng dụng**

Tạo Custom App thông qua [Lark Open Platform](https://open.larksuite.com).

**Bước 2. Cấu hình quyền truy cập**

Các nhóm quyền cần thiết bao gồm:

- `im:message`
- `im:message:send_as_bot`
- `im:chat`
- `bitable:app`
- `drive:drive`
- `docx:document`

Quyền cụ thể phụ thuộc vào các chức năng được kích hoạt.

**Bước 3. Cấu hình Event Subscription**

Request URL:

```text
https://your-domain.com/api/lark/events
```

Các sự kiện cần đăng ký:

```text
im.message.receive_v1
card.action.trigger
```

**Bước 4. Cấu hình Interactive Card Callback**

```text
https://your-domain.com/api/lark/card-action
```

**Bước 5. Cấu hình OAuth Redirect URLs**

```text
https://your-domain.com/setup/callback

https://your-domain.com/auth/lark/callback
```

**Bước 6. Hoàn tất Onboarding**

Truy cập:

```text
https://your-domain.com/setup
```

Thực hiện các bước hướng dẫn để kết nối ứng dụng và thiết lập doanh nghiệp.

---

## 9. Triển khai

HiLark đã được triển khai trên **AWS EC2**, sử dụng Docker để đóng gói và quản lý các dịch vụ.

Môi trường triển khai bao gồm Backend và các dịch vụ quản lý tri thức, được tổ chức thành những container riêng biệt.

Repository cung cấp các cấu hình:

- `docker-compose.prod.yml`: Cấu hình triển khai Backend.
- `docker-compose.all-in-one.yml`: Cấu hình triển khai toàn bộ hệ thống.
- `deploy.sh`: Script hỗ trợ quá trình triển khai.

Các thông tin xác thực và biến môi trường được quản lý riêng, không đưa trực tiếp vào mã nguồn.

---

## 10. API Reference

Backend cung cấp REST API phục vụ các chức năng chính:

| Method | Endpoint | Mô tả |
|---|---|---|
| GET | `/health` | Kiểm tra trạng thái hệ thống |
| POST | `/api/lark/events` | Tiếp nhận sự kiện từ Lark |
| POST | `/api/lark/card-action` | Xử lý thao tác trên Interactive Card |
| POST | `/api/chat` | Kiểm thử Chat Pipeline |
| GET | `/api/digests/master/pending/latest` | Lấy báo cáo tổng hợp đang chờ duyệt |
| POST | `/api/digests/master/generate` | Tạo báo cáo tổng hợp |
| POST | `/api/digests/master/{master_id}/approve` | Phê duyệt báo cáo |
| POST | `/api/digests/master/{master_id}/reject` | Từ chối báo cáo |
| GET | `/api/v1/scopes` | Lấy danh sách Chat Scope |
| POST | `/api/v1/scopes` | Thiết lập Chat Scope |
| POST | `/api/v1/scopes/{chat_id}/documents` | Nạp tài liệu vào Chat Scope |
| GET | `/policy/status` | Kiểm tra trạng thái đồng bộ chính sách |
| POST | `/policy/sync` | Đồng bộ chính sách doanh nghiệp |
| GET | `/setup` | Truy cập giao diện thiết lập |
| POST | `/setup/api/register-app` | Đăng ký ứng dụng Lark |
| GET | `/onboarding/wizard` | Truy cập giao diện Onboarding |

Có thể xem đầy đủ API Schema tại `/docs` khi Backend đang hoạt động.

---

## 11. Kiểm thử

HiLark có bộ kiểm thử tự động bao gồm Unit Tests, Integration Tests, kiểm thử phân tách dữ liệu giữa các Tenant và Concurrency Tests.

Chạy các lệnh từ thư mục `server`:

**Chạy toàn bộ bộ kiểm thử**

```bash
uv run pytest tests -q
```

**Kiểm thử phân tách dữ liệu giữa các Tenant**

```bash
uv run pytest \
  tests/final_test/test_cross_tenant_isolation_complete.py -v
```

**Kiểm thử các trường hợp rò rỉ dữ liệu**

```bash
uv run pytest \
  tests/final_test/test_data_leakage_fixes.py -v
```

**Kiểm thử TokenBroker**

```bash
uv run pytest \
  tests/auth/test_token_broker.py -v
```

**Kiểm thử BYOK và Onboarding**

```bash
uv run pytest \
  tests/final_test/test_byok_onboarding.py -v
```

Kết quả kiểm thử gần nhất được ghi nhận trong tài liệu dự án:

**280/280 tests PASSED (100%).**

---

## 12. Tài liệu kỹ thuật

Các tài liệu về kiến trúc và quá trình phát triển được lưu trong `docs/project-memory/`.

| Tài liệu | Nội dung |
|---|---|
| `PROJECT_CONTEXT.md` | Bối cảnh và kiến trúc hiện tại của dự án |
| `HANDOFF.md` | Trạng thái bàn giao và nhật ký phát triển |
| `DECISIONS.md` | Các quyết định kỹ thuật và lý do lựa chọn |
| `TECHNICAL_DEBT.md` | Những vấn đề kỹ thuật còn tồn tại và kế hoạch xử lý |

Ngoài ra, dự án duy trì Engineering Decision Log (EDL) để ghi lại các quyết định thiết kế, những lựa chọn đã cân nhắc và quá trình kiểm chứng.

---

## 13. Thông tin dự án

HiLark được phát triển bởi Tống Phước Hoài Nam và đội ngũ phát triển dự án HiLark.

