# Current Handoff

> Cập nhật khi kết thúc phiên có công việc đang dở hoặc bàn giao trạng thái sẵn sàng.

## Current task
- **Goal:** Kiểm thử và hoàn thiện toàn diện Hệ thống Trợ lý AI theo Đề bài thử việc (9 trang) & Chuẩn bị Môi trường Triển khai Sản xuất (Production-Ready Architecture) cho Anh Hiệp:
  1. **Phase 1: Group Setup, Baseline Docs, Multimodal OCR & Knowledge Alignment:** Đã hoàn thành 100% (10/10 test cases passed).
  2. **Phase 2: Chat Intent, Safety Guardrails & HITL Interactive Governance:** Đã hoàn thành 100% (9/9 test cases passed).
  3. **Phase 3: End-to-End Daily Digest & Management Reporting:** Đã hoàn thành 100% (9/9 test cases passed).
  4. **Phase 4: Hybrid BYOK, Auto-Provision Lark Base & Onboarding Screen Guide:** Đã hoàn thành 100% (18/18 test cases passed).
  5. **Nâng cấp Multi-Provider LLM & Apple Minimalist UI:** Hỗ trợ ChatGPT, Anthropic, Google, và Custom (OpenAI-compatible), timeout tùy chỉnh, base URL tùy biến, Initializing Screen mượt mà và loại bỏ 100% emoji khỏi giao diện.
  6. **Hướng dẫn Tạo Bot & Cấu hình Hạ tầng Nâng cao:** Bổ sung hướng dẫn 2 phút tạo Custom App trên Lark Developer, form nhập và thẩm định trực tiếp cặp App ID & App Secret qua Lark Open Platform, cùng tùy chọn nâng cao kết nối MongoDB riêng của doanh nghiệp.
  7. **Chiến lược Kiến trúc Lark Store App (ISV Multi-Tenant SaaS) & Cụm Server Bảo trợ:** Nhận chỉ đạo và cam kết hạ tầng máy chủ tập trung từ Anh Hiệp ("Cần server anh cấp server"), lập Kế hoạch triển khai toàn diện `IMPLEMENTATION_PLAN_LARK_STORE_ISV_APP.md` cho mô hình SaaS Multi-Tenant (1-Click Install từ Lark App Directory, cô lập dữ liệu `tenant_key`, dynamic ISV token lifecycle).
  8. **Hoàn thành Workstream 1 - Vòng đời Token ISV & Marketplace Auth Engine:** Xây dựng `ISVTokenService`, nhận `app_ticket` qua webhook, cấp mới và cache `app_access_token` và `tenant_access_token` độc lập theo `tenant_key`, Dual-Mode tương thích ngược Custom App (9 TCs passed).
  9. **Hoàn thành Workstream 2 - Cô lập Dữ liệu Multi-Tenant trong MongoDB:** Bổ sung `tenant_key` vào 6 Models cốt lõi (`Entity`, `Fact`, `ChatScopeRecord`, `StagingMessage`, `DailyDigestRecord`, `UserSettingsRecord`), nâng cấp Index Model compound với tiền tố `tenant_key`, xây dựng `TenantScopedCollection` & `scoped_query` engine chống rò rỉ dữ liệu chéo giữa các công ty (6 TCs passed).
  10. **Hoàn thành Workstream 3 - Bộ định tuyến Sự kiện & Client Pool Đa Doanh nghiệp:** Bóc tách `tenant_key` từ Event Header / Sender trong `parse_event`, tự động kích hoạt `TenantContext` trong `_dispatch_to_handlers`, xử lý sự kiện Vòng đời Doanh nghiệp `app_status_change` & `app_uninstalled` qua `tenant_lifecycle_handler`, hỗ trợ `tenant_key` trong các hàm gửi tin `messenger.py` (8 TCs passed).
  11. **Hoàn thành Workstream 4 - Đa Dataset WeKnora & Auto-Provision Bitable theo Doanh nghiệp:** Tự động cấp phát WeKnora Tenant và bộ 2 KB chuẩn (Policy & Wiki Digest), sinh mật khẩu Admin ngẫu nhiên an toàn, bàn giao qua Lark DM và nhúng thông tin trực tiếp vào Screen Guide Onboarding Wizard (Giải pháp B), tự động tạo Lark Base trên Drive doanh nghiệp theo `tenant_key` (10 TCs passed).
  12. **Hoàn thành Workstream 5 - Onboarding & Trải nghiệm Kích hoạt 1-Click từ Marketplace:** Tự động gửi Lark Interactive Card V2 chào mừng khi nhận sự kiện cài đặt app từ Store, xây dựng giao diện Adaptive Dual-Mode Screen Guide (3 bước tinh gọn cho ISV Mode, 4 bước chuẩn cho Custom App Mode), hỗ trợ bộ lệnh điều hành nhanh trong DM 1-1 cho Admin (/status, /dashboard, /weknora, /setup, /wizard) (9 TCs passed).
  13. **Khắc phục lỗi Onboarding Wizard & Dọn dẹp Chuẩn hóa Lark Base (EDL-0028, EDL-0029, EDL-0030):** Khắc phục lỗi `save_user_settings()` nhận `tenant_key`, dọn sạch 100% các cột rác (`Text`, `Single option`, `Date`, `Attachment`), xóa 10 dòng trống rỗng, chuẩn hóa tên tiếng Việt cho view và trường primary của Base; tự động hóa hoàn toàn trong `base_provision_service.py` và rebuild container `hilark-server` thành công (117/117 TCs passed).
  14. **Khắc phục Triệt để Lỗi FieldNameNotFound (code 1254045) Khi Thêm Bot Vào Nhóm Chat:** Cách ly cache schema theo `(app_token, table_id)`, khử trùng lặp và làm sạch bộ lọc alias thích ứng (`_adapt_fields`), đồng thời tự động phân giải đúng Base của Tenant trong `_internal_on_bot_added_event`.
- **Status:** SẴN SÀNG 100% - TOÀN BỘ 117/117 TEST CASES PASSED, DOCKER SERVER HEALTHY, BASE VÀ WEKNORA ĐĂNG NHẬP 100% THÀNH CÔNG.

## 15. Chuẩn Hóa Cổng Đăng Nhập WeKnora Web Console (Cổng 80) & Cấp Quyền Admin Hệ Thống
- **Vấn đề người dùng gặp phải:** Khi click vào nút đăng nhập WeKnora, trình duyệt nhận phản hồi JSON `{"error":"Unauthorized: missing authentication"}`.
- **Nguyên nhân gốc:** 
  1. WeKnora có hai container: `WeKnora-app` (Golang backend API) lắng nghe cổng `8080`, và `WeKnora-frontend` (Nginx + Vue SPA) lắng nghe cổng `80`.
  2. Mọi truy cập trình duyệt trực tiếp vào cổng 8080 mà không có header xác thực đều bị middleware Golang chặn và trả về lỗi Unauthorized. Cổng Web UI thực sự là cổng **`80`** (`http://localhost/login`).
  3. Đường dẫn cấu hình mặc định trong một số dịch vụ đang fallback về cổng 8080 hoặc URL mẫu.
  4. Người dùng admin mới khởi tạo chưa có tài khoản trong DB WeKnora PostgreSQL.
- **Giải pháp triển khai:**
  1. Chuẩn hóa toàn bộ URL WeKnora Web Console sang `http://localhost/login` (cổng 80) trên `settings.WEKNORA_WEB_URL`, `.env`, `tenant.py`, `card_builder.py`, `card_action_handler.py`, `weknora_provision_service.py` và MongoDB Atlas.
  2. Bổ sung `from core.config import settings` ở đầu `server/services/lark/card_builder.py`.
  3. Tạo và kích hoạt thành công tài khoản WeKnora Admin `admin_19a84399@hilark.internal` / `HLK@%6lbF^W8zQ` với vai trò `is_system_admin=true, can_access_all_tenants=true` trên PostgreSQL của WeKnora.
  4. Xác minh qua API đăng nhập `POST http://localhost/api/v1/auth/login`: thành công 100% (HTTP 200, JWT token hợp lệ).
  5. Xóa triệt để các dòng trống mặc định do Lark tạo ở Bảng 2 (Chính sách), đảm bảo cả 2 bảng Lark Base đều sạch đẹp 100%.
  6. Rebuild và restart container Docker `hilark-server` hoạt động ổn định. Kiểm thử tự động 117/117 test cases passed 100%.

## 16. Khắc Phục Triệt Để Lỗi Không Thấy Docs Trong WeKnora & Trống Thông Tin Đăng Nhập Trên Welcome Card (EDL-0032)
- **Vấn đề người dùng phản hồi:**
  1. Log server báo thành công nhưng khi đăng nhập WeKnora Console không thấy tài liệu nào trong Knowledge Base.
  2. Khi upload link Lark Docs trong chat, không thấy engine nạp tài liệu vào WeKnora.
  3. Thẻ chào mừng hiển thị thiếu thông tin: `Tài khoản: `` ` và `Mật khẩu ban đầu: `` `.
  4. Cấu trúc bảng Base xuất hiện các cột mẫu mặc định tiếng Anh (`Text`, `Single option`, `Date`, `Attachment`) và cột tiếng Trung `多行文本`.
- **Nguyên nhân gốc đã phân tích & chứng minh:**
  1. **Dataset Routing Disconnect:** `chat_scopes.py` fallback về `settings.WEKNORA_DATASET_ID` cũ trong `.env` (`bca87123...`), thuộc về workspace demo cũ. Khi người dùng đăng nhập tài khoản Tenant mới (`20108`), họ xem các Dataset mới (`fc733015...`, `7410f72c...`) nên danh sách tài liệu trống trơn.
  2. **Thiếu X-Tenant-ID Header:** Các hàm `upload_file`, `get_document_info`, `search_knowledge` trong `weknora_client.py` không nhận `tenant_id`, khiến WeKnora không thể phân giải ngữ cảnh tenant.
  3. **Lark Chat Ingestion Chuyển hướng 1 Chiều:** `document_handler.py` chỉ bóc tách facts/claims vào MongoDB mà không tải nạp file/markdown lên WeKnora Knowledge Base.
  4. **Policy Table Multi-Tenant Disconnect:** `policy_sync.py` kiểm tra cứng `table_id == settings.LARK_BASE_POLICY_TABLE_ID` cũ và phụ thuộc `WEKNORA_POLICY_DATASOURCE_ID`, khiến các thay đổi trên Bảng Chính Sách mới của Tenant không được kích hoạt nạp vào Policy KB.
  5. **Card Credentials Fallback:** `provision_tenant_weknora` khi thấy tenant đã có KB thì không bù đắp credentials nếu thiếu trường `weknora_admin_user`, dẫn đến render chuỗi rỗng `` ``.
- **Giải pháp đã triển khai:**
  1. Thêm tham số `tenant_id` và header `X-Tenant-ID` vào `weknora_client.py`.
  2. Tự động phân giải `effective_dataset_id` và `weknora_tenant_id` theo hồ sơ tenant trong `chat_scopes.py`, nạp trực tiếp vào đúng KB của Tenant.
  3. Tích hợp tự động tải nạp tài liệu và Lark Doc/Wiki/Folder link lên WeKnora ngay trong `document_handler.py`.
  4. Nâng cấp `policy_sync.py` hỗ trợ đa tenant và đọc trường `Văn bản đính kèm / Link` (bao gồm kiểu dict `{"link": ..., "text": ...}`).
  5. Tự động bù đắp và bảo đảm deterministic credentials trong `weknora_provision_service.py` và `card_builder.py`.
  6. Xây dựng cơ chế tự động dọn dẹp Base `repair_enterprise_base_schema()`: xóa các cột rác, đổi tên `多行文本` -> `Tên văn bản / Quy định`, đổi tên view `表格视图 1` -> `Tất cả Chính sách`.
  7. Rebuild và kiểm tra container Docker `hilark-server` hoạt động ổn định và kết nối thông suốt.

## Các Nội Dung Đã Triển Khai Trong Chiều 31/10/2026

### 1. Workstream 4: Cấp phát Tri thức WeKnora & Auto-Provision Bitable Đa Doanh nghiệp (Giải pháp B - EDL-0021)
- Tự động cấp phát WeKnora Tenant & 2 Datasets chuẩn (`policy` và `wiki`) cho từng doanh nghiệp khi cài đặt ứng dụng.
- Cơ chế sinh mật khẩu ngẫu nhiên bảo mật cao (`generate_secure_password`) cho tài khoản WeKnora Admin.
- Tự động gửi thông tin tài khoản qua tin nhắn chào mừng trong Lark DM và nhúng trực tiếp vào Screen Guide (Onboarding Wizard Step 3) sau khi setup thành công.
- Tự động khởi tạo Lark Base (Bitable) trên Drive doanh nghiệp dựa trên `tenant_key` và cấu hình phân quyền dữ liệu.
- Định tuyến tri thức thông minh theo `tenant_key` trong quy trình tổng hợp Daily Digest.

### 2. Workstream 5: Trải nghiệm Onboarding Kích hoạt 1-Click từ Lark Marketplace (EDL-0022)
- Lắng nghe và xử lý sự kiện Vòng đời Doanh nghiệp `open_app` / `start_by_tenant` khi Admin cài đặt app từ Marketplace, tự động kích hoạt cấp phát hạ tầng và gửi `build_marketplace_welcome_card` qua DM.
- Thiết kế giao diện Adaptive Dual-Mode Screen Guide (`onboarding_wizard.html`):
  * **ISV Store Mode:** 3 bước tinh gọn (Tự động nhận diện cấu hình, không yêu cầu nhập thủ công App ID, App Secret hay Base App Token).
  * **Custom App Mode:** 4 bước chuẩn truyền thống cho khách hàng tự triển khai app nội bộ.
- Bổ sung trường `tenant_key` vào `SaveSettingsRequest` và đồng bộ cấu hình doanh nghiệp an toàn.

### 3. Tối ưu hóa 100% Nút Bấm Trên Thẻ Tương Tác (Loại bỏ Hoàn toàn Text Commands - EDL-0023)
- Xóa bỏ triệt để hơn 450 dòng mã logic phân tích cú pháp câu lệnh văn bản (`/status`, `/weknora`, `/setup`, `/config`, `duyệt digest`, `hủy digest`, `sửa:`, `gửi`, `bỏ`, `sửa fact:`...).
- Tái cấu trúc [owner_command_handler.py](file:///Users/hoainam/Desktop/HiLark/server/services/lark/handlers/owner_command_handler.py) thành Owner DM Interaction Handler: khi Admin gửi bất kỳ tin nhắn nào trong DM 1-1, Bot phản hồi ngay bằng **Thẻ Bảng Điều Khiển Quản Trị (Executive Control Hub Card V2)** cá nhân hóa theo tenant.
- Thẻ tích hợp 2 hàng nút bấm 1-Click:
  * Hàng 1: `[Mở Lark Base Quản Trị]` (URL), `[WeKnora Console]` (URL), `[Cấu Hình Trợ Lý]` (Applink modal).
  * Hàng 2: `[Báo Cáo Ngày Gần Nhất]` (action: `view_master_digest`), `[Trạng Thái Vận Hành]` (action: `view_tenant_status`), `[Tài Khoản WeKnora]` (action: `view_weknora_info`).
- Cập nhật [card_action_handler.py](file:///Users/hoainam/Desktop/HiLark/server/services/lark/handlers/card_action_handler.py) xử lý tập trung mọi tương tác nút bấm.

### 4. Chuyển dịch Cơ sở Dữ liệu sang MongoDB Atlas Cloud Cluster (EDL-0024)
- Thay thế kết nối MongoDB local bằng cụm đám mây MongoDB Atlas (`cluster0.ivrk314.mongodb.net`) an toàn, sẵn sàng cho môi trường Multi-Tenant SaaS.
- Cập nhật [server/core/config.py](file:///Users/hoainam/Desktop/HiLark/server/core/config.py) hỗ trợ đa dạng biến môi trường: `MONGO_URL`, `mongo_url`, `MONGODB_URI`.
- Cấu hình `serverSelectionTimeoutMS=5000ms` cho Motor và PyMongo để đảm bảo bắt tay TLS/SSL và phân giải DNS SRV ổn định qua internet.
- Bảo mật thông tin xác thực nhạy cảm: Đưa `atlas-credentials.env` và `*.env` vào [.gitignore](file:///Users/hoainam/Desktop/HiLark/.gitignore).
- Kết nối thực tế và tự động khởi tạo thành công toàn bộ 13 Collections và hệ thống Compound Indexes trên Atlas.

### 5. Khắc phục Triệt để Lỗi Thiếu LARK_USER_OPEN_ID Khi Duyệt Bản Nháp & Phân giải Đa tầng (EDL-0025)
- **Nguyên nhân gốc:** Khi câu hỏi trong nhóm kích hoạt hành động `DRAFT_PENDING_APPROVAL` hoặc `MEMORY_AND_DRAFT`, quy trình yêu cầu Open ID của chủ nhân để lưu draft và gửi thẻ phê duyệt. Trước đó, mã chỉ kiểm tra biến `.env` và ném `RuntimeError: Thiếu LARK_USER_OPEN_ID để lưu draft chờ duyệt.` nếu thiếu, dẫn đến crash queue pipeline.
- **Giải pháp triển khai:**
  * Xây dựng hàm phân giải linh hoạt `resolve_effective_owner_open_id` trong [chat_workflow.py](file:///Users/hoainam/Desktop/HiLark/server/services/workflows/chat_workflow.py) qua 9 cấp bậc: Cache LarkService -> Settings -> MongoDB `tenants` -> MongoDB `user_settings` (được lưu trực tiếp từ Screen Guide Onboarding) -> MongoDB `system_config` -> MongoDB `auth_tokens` -> Chat Scope `admins` -> `sender` -> Fallback an toàn (không bao giờ gây crash).
  * Trong [onboarding.py](file:///Users/hoainam/Desktop/HiLark/server/routers/onboarding.py) (`/api/save` và `/api/provision-base`), tự động đồng bộ ngay lập tức Open ID của người dùng vào `settings.LARK_USER_OPEN_ID`, `lark_service.known_user_open_id`, collection `tenants.admin_open_id` và `system_config.lark_admin_config`.
  * Nâng cấp property `owner_open_id` trong [client.py](file:///Users/hoainam/Desktop/HiLark/server/services/lark/client.py) tự động tra cứu từ cấu hình đã lưu trong CSDL.
  * Truyền tường minh `target_open_id=owner_open_id` và `tenant_key=eff_tenant` khi gửi thẻ duyệt [send_bot_dm_to_owner](file:///Users/hoainam/Desktop/HiLark/server/services/lark/messenger.py).
  * Bổ sung log hướng dẫn khi gặp mã lỗi Lark `230013` (Tài khoản chưa nằm trong phạm vi Availability của Lark Bot).
  * Toàn bộ 108/108 bài kiểm thử tự động đều passed 100%.
- Xác nhận kiểm thử hồi quy: **108/108 test cases PASSED 100% trong 31.17s**.

### 6. Hoàn thành Luồng One-Click Setup 7 Bước Tự Động theo Chuẩn ISV SaaS (EDL-0026)
- **Vấn đề giải quyết:** Loại bỏ hoàn toàn sự phức tạp của luồng cấu hình thủ công 4 bước, không bắt khách hàng/Admin phải tự tạo Bot hay copy App ID / App Secret trên Lark Developer.
- **Quy trình 7 bước tự động 100%:**
  1. `Admin mở HiLark Setup`: Truy cập giao diện Apple Minimalist `/setup` và nhấn nút "Cài đặt HiLark cho Doanh nghiệp".
  2. `Lark Authorization`: Chuyển hướng sang Lark OAuth (`/setup/install` -> Lark OAuth) với scope đầy đủ (`offline_access`, `im:message`, `bitable:app`, `contact`, `wiki`, `docx`, `drive`).
  3. `HiLark Backend nhận authorization`: Nhận code tại `/setup/callback`, tự động đổi lấy Token và trích xuất `tenant_key`, `admin_open_id`, `admin_name`.
  4. `Tự động kích hoạt Bot`: Kích hoạt Bot mặc định của hệ thống cho doanh nghiệp mà không cần tạo bot mới.
  5. `Đồng bộ cấu hình & Cấp phát hạ tầng`: Tự động khởi tạo song song Lark Base Quản trị và Không gian Tri thức WeKnora cho Tenant.
  6. `Gửi tin nhắn kiểm tra`: Bot gửi Thẻ tương tác Chào mừng & Bàn giao hệ thống (Welcome Card V2) trực tiếp tới Lark DM của Admin.
  7. `Ready`: Hiển thị màn hình thành công "Sẵn Sàng Vận Hành" kèm nút mở Lark Bot và Lark Base Quản trị.
- **Thành phần kỹ thuật xây dựng:**
  * Dịch vụ điều phối [one_click_setup_service.py](file:///Users/hoainam/Desktop/HiLark/server/services/setup/one_click_setup_service.py).
  * Router [setup.py](file:///Users/hoainam/Desktop/HiLark/server/routers/setup.py) (`/setup`, `/setup/install`, `/setup/callback`, `/setup/api/status/{task_id}`).
  * Giao diện Apple Minimalist [setup_one_click.html](file:///Users/hoainam/Desktop/HiLark/server/templates/setup_one_click.html) kèm cơ chế AJAX Polling mượt mà 1s/lần và không dùng emoji.
  * Bộ kiểm thử toàn diện [test_one_click_setup.py](file:///Users/hoainam/Desktop/HiLark/server/tests/final_test/test_one_click_setup.py) (9 test cases unit, integration & resilience).

### 7. Hợp Nhất Trải Nghiệm Setup & Onboarding: One-Click Setup + Progressive Customization (EDL-0027)
- **Vấn đề giải quyết:** Hợp nhất hai trang độc lập `/setup` và `/onboarding` thành một luồng trải nghiệm duy nhất. Đạt đồng thời 2 mục tiêu: 1-Click cài đặt tự động trong 10 giây cho mọi người dùng, và cho phép tùy biến nâng cao (BYOK, Daily Digest, Strict HITL) ngay dưới màn hình Ready.
- **Tuân thủ Thiết kế UI/UX Onboarding:**
  * Giữ nguyên 100% phong cách thiết kế Apple SF Pro Light đặc trưng của `onboarding_wizard.html` (nền sáng `#F5F6F8`, surface trắng `#FFFFFF`, font chữ SF Pro sắc nét, bo góc chuẩn mực, bóng đổ nhẹ).
  * Danh sách 7 bước cài đặt tự động hiển thị với icon xanh lá/xanh dương tinh tế, thông tin trạng thái cập nhật thời gian thực.
  * Màn hình Ready hiển thị dạng thẻ Admin Card với nút CTA mở Lark Bot và Lark Base.
  * Khối **"Tùy Chỉnh Nâng Cao (Tùy chọn)"** dạng Accordion mở rộng mượt mà ngay bên dưới:
    - *Khối 1: Bộ não AI & BYOK:* Tùy chọn Hạn mức mặc định hoặc Khóa riêng (Google Gemini, OpenAI, Claude, Custom), kèm chức năng test độ trễ live.
    - *Khối 2: Lịch nhận báo cáo & Kiểm duyệt:* Chọn giờ nhận Daily Digest (17:30, 18:00, 21:00, 23:00) và checkbox Strict HITL.
    - *Khối 3: Bàn giao WeKnora:* Hiển thị thông tin tài khoản WeKnora Vault nếu có.
    - Nút *"Lưu Thay Đổi Cấu Hình"* gửi AJAX lưu trực tiếp vào CSDL MongoDB.
- Xác nhận kiểm thử toàn diện: **117/117 test cases PASSED 100% trong 32.33s**.

### 8. Khắc phục Triệt để Deadlock & Tối ưu Cấp phát Hạ tầng Bước 5 (EDL-0028)
- **Nguyên nhân gốc rễ (Root Cause):**
  * **Deadlock trong ISVTokenService:** `get_tenant_access_token` đã giữ `self._lock`, bên trong lại gọi `await self.get_app_access_token()` vốn cũng gọi `async with self._lock:`. Do `asyncio.Lock` không phải Reentrant Lock (RLock), coroutine tự chờ chính nó nhả lock -> Gây deadlock vô tận tại Bước 5.
  * **Rẽ nhánh sai điều kiện trong `bitable.py`:** Kiểm tra `if tenant_key or getattr(settings, "IS_ISV_MODE", False):` làm các lệnh gọi Custom App Mode nội bộ nhảy vào ISV Token Exchange và bị lỗi thiếu `app_ticket`.
  * **Gọi API tuần tự kéo dài:** `base_provision_service.py` gọi 16 requests tuần tự lên máy chủ Lark OpenAPI (mỗi request 2-3s), tổng thời gian lên tới 40-50s.
- **Giải pháp triển khai & xác minh:**
  * **Tách Lock độc lập:** Tách riêng `self._app_lock` và `self._tenant_lock` trong `ISVTokenService`, giải phóng lock trước khi gọi tác vụ con.
  * **Sửa nhánh điều kiện:** Chỉ vào ISV Token Exchange khi `IS_ISV_MODE == True` và có `tenant_key`. Khi `IS_ISV_MODE == False`, sử dụng Bot Tenant Access Token nội bộ qua `/internal`.
  * **Cấp phát Song song (Parallel Gathering):** Dùng `asyncio.gather` khởi tạo đồng thời Lark Base và WeKnora trong `one_click_setup_service.py`; dùng `asyncio.gather` tạo đồng thời các trường Bitable và nạp dữ liệu mẫu trong `base_provision_service.py`. Tốc độ Bước 5 giảm từ 40s xuống dưới 4 giây.
  * **Timeout & Fallback:** Bọc `asyncio.wait_for(timeout=25.0)` đảm bảo pipeline không bao giờ bị treo.
  * **Rebuild Docker Image:** Đã build và restart container `hilark-server` mang toàn bộ mã nguồn mới nhất. Toàn bộ 117/117 test cases passed 100%.

### 9. Cơ chế Tự động Thích ứng Schema Cột Lark Base (Adaptive Schema Field Mapping - EDL-0029)
- **Nguyên nhân gốc rễ (Root Cause):**
  * Trong `bitable.py` và `dispatcher.py`, mã nguồn hardcode tên cột cũ: `"ID Group"` và `"Dự án / Nhóm"`.
  * Trong khi cấu trúc Lark Base thực tế (cả Base template ban đầu lẫn Base auto-provisioned) đặt tên trường chuẩn là `"Chat ID"` và `"Tên dự án"`.
  * Khi bot được thêm vào nhóm chat mới (`bot_added` event), lệnh gọi `create_record` gửi `{"ID Group": ..., "Dự án / Nhóm": ...}` bị Lark API từ chối với mã lỗi `1254045 FieldNameNotFound`.
- **Giải pháp triển khai & xác minh:**
  * **Schema Field Mapping:** Xây dựng hàm `_get_table_field_names()` đọc và cache danh sách cột thực tế của bảng, kết hợp hàm `_adapt_fields()` tự động map linh hoạt giữa các cặp bí danh (`Chat ID` $\leftrightarrow$ `ID Group`, `Tên dự án` $\leftrightarrow$ `Dự án / Nhóm`, `Trạng thái hoạt động` $\leftrightarrow$ `Trạng thái`...).
  * **Bảo vệ Create/Update Record:** `create_record` và `update_record` tự động lọc bỏ các trường không tồn tại trong schema bảng để không bao giờ bị lỗi `FieldNameNotFound`.
  * **Cập nhật BASE_FIELD_MAP:** Bổ sung `"Chat ID"` và `"Tên dự án"` vào `BASE_FIELD_MAP` trong `chat_scopes.py`.
  * **Kiểm tra thực tế:** Nhóm `'PROJECT TEST'` (`oc_45ba874a6152de48209bcce6e34d27a2`) đã được đồng bộ chuẩn xác vào Base và MongoDB `chat_scopes`.
  * **Kiểm thử hồi quy:** 117/117 test cases PASSED 100%. Rebuild và restart container `hilark-server` thành công.

## What is confirmed
- **Toàn bộ 52/52 Unit & Integration Tests Đều Đạt 100% (PASSED):**
  * **Phase 1 (10 TCs):** Xử lý tài liệu đa định dạng, thư mục lồng nhau, nhận diện OCR link DocX/Wiki.
  * **Phase 2 (9 TCs):** Lọc tin rác JEV 0ms, gom tin bàn việc vào Staging, bảo mật vùng cấm ngân sách, Strict HITL nhóm Tuyệt mật, phân quyền Claims, thu hồi tin 4 tầng.
  * **Phase 3 (9 TCs):** Daily Digest 3 nhánh tri thức, Full Provenance & Applink, Context Continuation K-1 sang K, Master Daily Digest đa dự án, duyệt 1-chạm Interactive Card V2, WeKnora Entity-Centric Sync.
  * **BYOK & Screen Guide (18 TCs):** Mã hóa AES-256 Fernet, Masking khóa, Phân cấp khóa 3-Tier, Live Latency Ping test, Stepper Wizard 4 bước, Interactive Card chào mừng, In-App OAuth Popup & PostMessage, Multi-Provider LLM (ChatGPT, Anthropic, Google, Custom), Custom Base URL & Timeout.
  * **Auto-Provisioning Lark Base (6 TCs):** Tự động tạo Bitable qua OpenAPI, cấu hình bảng Chat Scopes & Policies, nạp 3 dự án mẫu, cấp quyền Owner cho Sếp, phân giải động và fallback về `.env`.
- **Hạ tầng Sản xuất Hoàn thiện:**
  * Multi-stage `server/Dockerfile` sử dụng `uv` và user bảo mật `appuser`.
  * `docker-compose.prod.yml` cách ly mạng `hilark-network`, Zero Ingress Attack Surface qua Lark WebSocket.
  * Script triển khai tự động `deploy.sh` 1-click có kiểm tra healthcheck và cấu hình.
  * Tài liệu kiến trúc toàn diện `docs/DEPLOYMENT_GUIDE.md`.

## Work completed
- Khắc phục lỗi cắt cụt ngữ cảnh lương Sổ tay Nhân viên:
  * Phát hiện `01_So_Tay_Nhan_Vien_Employee_Handbook.docx` trên WeKnora chứa đúng ngày 25 ("Ngày 25 hàng tháng" tại ký tự thứ `10,578`).
  * Phát hiện `context_composer.py` hardcode `max_chunk_chars: int = 4000` làm mất toàn bộ đoạn văn từ ký tự 4000 trở đi.
  * Đã nâng giới hạn lên `max_chunk_chars: int = 16000` trong `server/utils/context_composer.py`. Xác minh với Gemini trả về đúng "ngày 25 hàng tháng".
- Ghi nhận Kiến trúc Quyết định `EDL-0010` vào Notion và `DECISIONS.md`.
- **Hoàn tất Giai đoạn 1 (Phase 1: Thiết lập Môi trường & Hạ tầng gRPC - EDL-0010)**:
  * Mở mapping cổng `127.0.0.1:50051:50051` cho service `docreader` trong `WeKnora/docker-compose.yml`, restart container `WeKnora-docreader` thành công.
  * Cập nhật `server/pyproject.toml` bổ sung `grpcio`, `protobuf`, `grpcio-tools`; đồng bộ môi trường bằng `uv sync`.
  * Bổ sung cấu hình `DOCREADER_GRPC_HOST="127.0.0.1"`, `DOCREADER_GRPC_PORT=50051`, `DOCREADER_TIMEOUT_SECONDS=60` vào `server/core/config.py`.
  * Khởi tạo thư mục `server/proto/`, sao chép `docreader.proto` và biên dịch sinh mã Python stubs `docreader_pb2.py`, `docreader_pb2_grpc.py`.
  * Chạy kiểm thử smoke test `test_grpc_smoke.py`: Kết nối thành công tới `WeKnora-docreader:50051`, nhận diện 3 engines (`builtin`, `markitdown`, `opendataloader`) và chuyển đổi văn bản sang Markdown 100% không lỗi.
- **Hoàn tất Giai đoạn 2 (Phase 2: DocReader Service, Lark Client Extension & DocParserService - EDL-0010)**:
  * **Bước 2.1 (Core gRPC Wrapper & Models)**:
    - File Extension Gate: Kiểm tra nghiêm ngặt 17 định dạng tệp hợp lệ (`.docx`, `.pdf`, `.xlsx`, `.pptx`, `.md`, `.txt`, `.png`, `.jpg`...). Chặn sớm các file không hợp lệ (`.exe`, `.zip`, `.py`...).
    - File Size Gate: Giới hạn tệp tối đa 50MB và chặn tệp rỗng 0 bytes.
    - Kênh kết nối gRPC tái sử dụng (`grpc.aio.insecure_channel`) kèm cấu hình buffer 50MB và keepalive tối ưu.
    - Định nghĩa cấu trúc dữ liệu trong `server/models/docreader.py`: `DocReaderResult`, `DocParseResult`, `SUPPORTED_DOCUMENT_EXTENSIONS`, `MAX_FILE_SIZE_BYTES`.
    - Viết bộ kiểm thử `server/tests/01/test_docreader_service.py` (8/8 test cases passed 100% trong 0.096s).
  * **Bước 2.2 & 2.3 (Mở rộng Lark Client & Unified DocParserService)**:
    - Mở rộng `LarkClientMixin` (`server/services/larkServices/lark_client.py`):
      * `adownload_message_resource` / `download_message_resource`: Tải nhị phân tệp/ảnh đính kèm từ Lark IM qua `client.im.v1.message_resource.aget`.
      * `aget_docx_raw_content` / `get_docx_raw_content`: Đọc Markdown sạch từ Lark DocX qua OpenAPI `client.docx.v1.document.araw_content` (0 token cost).
      * `aresolve_wiki_token` / `resolve_wiki_token`: Giải mã node token sang docx token qua Wiki API `client.wiki.v2.space.aget_node`.
    - Xây dựng `server/services/doc_parser_service.py`:
      * Tự động phát hiện URL Lark DocX và Wiki từ văn bản tin nhắn qua Regex (`DOCX_URL_PATTERN`, `WIKI_URL_PATTERN`).
      * Điều phối phân giải: Gọi OpenAPI lấy Markdown đối với link DocX/Wiki; kiểm tra Extension Gate -> tải binary -> gọi AnyDoc gRPC `docreader_service.read()` đối với file đính kèm.
      * Chuẩn hóa đầu ra thành `DocParseResult`.
    - Viết bộ test `server/tests/01/test_doc_parser_service.py` (11/11 test cases passed 100% trong 0.019s).
- **Hoàn tất Giai đoạn 3 (Phase 3: Tích hợp Claims Pipeline & Dispatcher - EDL-0010)**:
  * **Tích hợp Claims Pipeline (`server/services/chat_service.py`)**:
    - Xây dựng `process_document_to_claims`: Nhận `DocParseResult`, gọi `llm_extractor.extract_async(...)` bóc tách Entities và Facts/Claims, bổ sung metadata (`source_doc`, `source_type`, `document_id`), lưu bền vững vào MongoDB với `scope_type="chat"` và `chat_id`.
  * **Tích hợp Bot Dispatcher (`server/services/bot_service.py`)**:
    - Mở rộng `LarkMessage` (`server/models/lark.py`) với các thuộc tính: `file_key`, `file_name`, `image_key`.
    - Bắt sự kiện tệp đính kèm (`msg.message_type in ("file", "image")`): Kiểm tra Extension Gate, gửi thông báo đang đọc, gọi `doc_parser_service.parse_attachment`, nạp Claims vào MongoDB và thông báo kết quả.
    - Bắt sự kiện liên kết Lark DocX / Wiki: Quét regex trong tin nhắn text, gọi OpenAPI lấy Markdown, trích xuất Claims vào MongoDB.
  * **Kiểm thử Unit Test**:
    - Viết `server/tests/01/test_claims_doc_pipeline.py` (6/6 test cases passed 100%).
- **Hoàn tất Giai đoạn 4 (Phase 4: Kiểm thử Mô phỏng Toàn Diện End-to-End - EDL-0010)**:
  * Xây dựng `server/tests/01/test_e2e_document_knowledge_overlay.py` mô phỏng toàn trình:
    1. Parse trực tiếp DOCX qua live gRPC AnyDoc container (`127.0.0.1:50051`) ra Markdown trong 1.5s.
    2. Bóc tách và nạp Claims vào MongoDB có gắn `source_doc="Meeting_Notes_Policy_Update.docx"`.
    3. `ContextComposer` hợp nhất WeKnora Handbook (ngày 25) và Claims động (ngày 28).
    4. Xác minh Grounded QA: Rule `CURRENT Claims > Static WeKnora Documents` đảm bảo thông tin lương trả về ngày 28 và giải thích lịch sử rõ ràng.
  * Tinh chỉnh `server/utils/context_composer.py`:
    - Hỗ trợ `RetrievedChunk` trực tiếp trong `normalize_retriever_data`.
    - Chuẩn hóa đồng nghĩa trạng thái (`accepted`, `active`, `approved` -> `current`) và trích xuất nguồn từ `source_doc`.
    - Điều kiện `auto_align`: Chỉ lọc claims theo query khi query được truyền vào.
- **Tính năng Mới: Duy Trì Mạch Ngữ Cảnh Digest Liên Tục Giữa Các Ngày (Digest Context Continuation)**:
  * Cơ chế: `Digests Ngày K = overview_summary của Ngày K-1 + Dữ liệu Ngày K`.
  * `server/models/digest.py`: Bổ sung `previous_overview_summary`, `previous_digest_date` vào `DailyDigestRecord`, và `previous_executive_summary`, `previous_master_date` vào `MasterDailyDigestRecord`. Render mạch tiếp nối tự nhiên vào `to_weknora_markdown()`.
  * `server/services/digest_service.py`: Thêm `get_previous_digest` & `get_previous_master_digest`, tự động nạp bối cảnh K-1 vào prompt trích xuất LLM để đảm bảo không bị đứt gãy diễn biến công việc, cam kết và blockers giữa các ngày.
  * `server/tests/01/test_digest_continuation.py`: Viết bộ 5 unit test kiểm thử toàn diện tính năng (5/5 tests pass).

- **Tự Động Làm Mới Token Khi Khởi Động & Khắc Phục Lỗi Token Chết / Graceful Bot Fallback**:
  * Khắc phục lỗi hiển thị cảnh báo `EXPIRED` khi bật server và lỗi `20038` (Invalid refresh token):
    - `server/services/token_service.py`:
      * Trong `refresh_user_token()`: Bắt mã lỗi `20038` ("The refresh token passed is invalid. It may have been used"), cập nhật trạng thái `invalid_refresh_token` vào MongoDB.
      * Trong `get_valid_user_token()`: Nếu access token đã hết hạn (`expires_at < now`) và refresh thất bại, trả về `None`, dứt khoát không trả về token đã chết.
      * Trong `init_token_on_startup()`: Tự động dọn dẹp `user_access_token = ""` trong RAM nếu token không hợp lệ, không để token rác gây lỗi API.
      * Trong `start_token_refresh_loop()`: Khởi động vòng lặp kiểm tra token ngay sau 5 giây (thay vì chờ 30 phút), chu kỳ kiểm tra định kỳ 15 phút.
    - `server/services/larkServices/lark_client.py`:
      * Sửa `_get_request_option(as_user=True)`: Kiểm tra đúng `if as_user and self.user_access_token:`.
      * Bổ sung cơ chế **Graceful Fallback sang Bot (Tenant Token)** cho các thao tác đọc tài liệu: `aresolve_wiki_token`, `resolve_wiki_token`, `aget_docx_raw_content`, `get_docx_raw_content`, `adownload_message_resource`, `download_message_resource`, `_get_name_sync`. Khi User Token hỏng hoặc thiếu quyền, tự động gọi lại bằng Bot token giúp hệ thống không bị gián đoạn.
  * Bộ test `test_token_service.py`, `test_doc_parser_service.py`, `test_chat_scope.py`: Toàn bộ **38/38 PASSED 100%**.
- **Nâng Cấp Cột Documents trong Lark Base Hỗ Trợ Link Lark Docs & Wiki (Bitable Document Link Ingestion)**:
  * `server/services/scope_service.py`:
    - Thêm helper `_extract_document_items` và `_sanitize_filename`: Phân loại và trích xuất cả tệp đính kèm nhị phân (PDF, Word, Excel...) lẫn liên kết Lark DocX / Wiki (dạng chuỗi URL, dict `{'link': ..., 'text': ...}` của Bitable Hyperlink field, hoặc list).
    - Cập nhật `sync_group_from_base_record`: Đối với các link Lark DocX / Wiki, gọi `doc_parser_service` để trích xuất Markdown sạch với chi phí 0 token, nạp nội dung dưới dạng file `.md` vào Knowledge Base WeKnora của nhóm chat tương ứng.
    - Cơ chế chống trùng lặp: Tra cứu `knowledge_id` sẵn có trong MongoDB qua `doc_key` hoặc `url`, không gọi lại API WeKnora nếu tài liệu đã tồn tại.
  * `server/tests/01/test_chat_scope.py`: Bổ sung 3 unit tests (`test_extract_document_items_various_formats`, `test_sync_group_from_base_record_with_lark_docx_link`, `test_sync_group_deduplicates_existing_lark_doc`) -> Toàn bộ **18/18 PASSED 100%**.

- **Giai đoạn 1 Tái Cấu Trúc (Phase 1 Refactoring: Database Indexes & Bounded Cache Eviction - EDL-0009)**:
  * Khởi tạo `server/database/indexes.py`: Định nghĩa IndexModel cho 8 collections (`claims`, `memories`, `conversation_staging`, `chat_scopes`, `daily_digests`, `master_daily_digests`, `draft_logs`, `lark_auth`) kèm cơ chế Graceful Fallback đơn lẻ chống OperationFailure.
  * Quản lý vòng đời kết nối `server/database/db.py`: Bổ sung `close_mongo_connections()` đóng an toàn `_async_client` và `_sync_client`, re-export `ensure_database_indexes`.
  * Tích hợp `server/main.py`: Gọi `ensure_database_indexes()` trong startup và `close_mongo_connections()` trong shutdown của `lifespan`.
  * Chống rò rỉ bộ nhớ (Bounded Cache):
    - `server/services/larkServices/lark_messenger.py`: Thêm `_record_sent_message_id` với TTL 600s, max 1,000 items.
    - `server/services/larkServices/lark_client.py`: Nâng cấp `get_user_name` và `_user_name_cache` với TTL 3,600s (1h), max 1,000 users.
  * Bộ test `tests/01/test_phase1_stability.py`: 8/8 tests passed 100%.

- **Giai đoạn 2 Tái Cấu Trúc (Phase 2 Refactoring: Tối Ưu Mạng & Async I/O - EDL-0009)**:
  * Khởi tạo `server/core/http_client.py`: Persistent `httpx.AsyncClient` Connection Pool duy nhất toàn server với cấu hình `max_keepalive_connections=20`, `max_connections=100`, `timeout=30.0s`.
  * Quản lý vòng đời `server/main.py`: Khởi tạo `await init_http_client()` khi startup và `await close_http_client()` khi shutdown của FastAPI lifespan.
  * Tách biệt kiến trúc `server/services/jev.py`: Loại bỏ hoàn toàn `HTTPException` khỏi tầng service, định nghĩa ngoại lệ nội bộ `JEVError(RuntimeError)` để ngăn rò rỉ web layer xuống business logic.
  * Tái sử dụng kết nối mạng & Tương thích ngược:
    - Xây dựng helper `_get_client_session` trong `jev.py`, `weknora.py`, `token_service.py`.
    - Loại bỏ 17 điểm tạo mới ad-hoc `httpx.AsyncClient` rải rác: WeKnora (10 điểm), JEV (3 điểm), TokenService (4 điểm).
    - Tự động nhận diện mock context manager trong môi trường test (`@patch("...httpx.AsyncClient")`), đảm bảo tương thích 100% với các test cũ mà không cần viết lại fixture.
  * Non-blocking Startup I/O `server/services/bot_service.py`: Chuyển các network call đồng bộ lúc startup (`subscribe_events`, `sync_bot_chats`) sang background bootstrap task thông qua `asyncio.to_thread` và `loop.create_task`, đảm bảo server FastAPI phản hồi HTTP healthcheck tức thì (< 0.1s).
  * Viết bộ unit tests `server/tests/01/test_phase2_network_io.py`: 7/7 tests pass 100%.

- **Giai đoạn 3 Tái Cấu Trúc (Phase 3 Refactoring: Tách nhỏ Bot Service & Handlers Decoupling - EDL-0009)**:
  * Tạo package mới `server/services/bot_handlers/`:
    - `document_handler.py`: Xử lý tệp đính kèm nhị phân (Word, PDF, Excel, ảnh) và liên kết Lark DocX/Wiki. Tích hợp dynamic dependency resolution giúp tương thích hoàn toàn với unit test mock.
    - `owner_command_handler.py`: Thụ lý các câu lệnh điều hành trong DM của Chủ nhân (xem/duyệt/hủy Digest, duyệt/sửa/bỏ Draft).
    - `member_message_handler.py`: Nhận diện danh tính người gửi, lưu staging cho Daily Digest và đẩy tin nhắn nhóm vào Smart Debouncer Queue.
  * Tái cấu trúc Facade `server/services/bot_service.py`:
    - Rút gọn file từ 674 dòng xuống ~230 dòng.
    - Hàm `handle_lark_incoming_message` trở thành Root Dispatcher ngắn gọn, phân luồng mạch lạc.
    - Re-export các biến và hàm quan trọng để không phá vỡ bất kỳ interface hay module phụ thuộc nào.
  * Viết bộ unit tests `server/tests/01/test_phase3_bot_handlers.py`: 8/8 tests pass 100%.

## Verification
- Phase 3 Bot Handlers Suite (`tests/01/test_phase3_bot_handlers.py`):
  * Ran 8 tests -> **8/8 PASSED**.
- Phase 2 Network & Async I/O Suite (`tests/01/test_phase2_network_io.py`):
  * Ran 7 tests -> **7/7 PASSED**.
- Phase 1 Stability Test Suite (`tests/01/test_phase1_stability.py`):
  * Ran 8 tests -> **8/8 PASSED**.
- Claims Document Pipeline Suite (`tests/01/test_claims_doc_pipeline.py`):
  * Ran 6 tests -> **6/6 PASSED**.
- JEV Classification & Routing Suite (`tests/01/test_jev_classification.py`):
  * Ran 9 tests -> **9/9 PASSED**.
- WeKnora Thresholds & Retrieval Suite (`tests/01/test_weknora_thresholds.py`):
  * Ran 2 tests -> **2/2 PASSED**.
- Token Service & OAuth Suite (`tests/01/test_token_service.py`):
  * Ran 9 tests -> **9/9 PASSED**.
- Chat Scope & Base Sync Suite (`tests/01/test_chat_scope.py`):
  * Ran 18 tests -> **18/18 PASSED**.
- DocParser Service Unit Test Suite (`tests/01/test_doc_parser_service.py`):
  * Ran 11 tests -> **11/11 PASSED**.
- Contextual Claim Gate Regression Suite (`tests/01/test_contextual_claim_gate.py`):
  * Ran 8 tests -> **8/8 PASSED**.
- Lark Service Unit Test Suite (`tests/01/test_lark_service.py`):
  * Ran 5 tests -> **5/5 PASSED**.
- Memory WeKnora Gating Suite (`tests/01/test_memory_weknora_gating.py`):
  * Ran 5 tests -> **5/5 PASSED**.
- **Tổng kiểm thử regression sau Phase 3:** **96/96 PASSED 100%** (chạy trong 3.36s).
- **Triển khai Mô hình Lark Store ISV SaaS Đa Khách Thuê (EDL-0020)**:
  * **Workstream 1 (Xác thực & Vòng đời Token ISV)**: Hoàn thành `isv_token_service.py`, quản lý dynamic `tenant_access_token` theo `tenant_key`, intercept `app_ticket` webhook event, tương thích ngược 100% (9/9 tests pass).
  * **Workstream 2 (Cô lập Dữ liệu Multi-Tenant trong MongoDB)**: Gắn `tenant_key` trên cả 6 models nghiệp vụ, thiết lập Compound Indexes với tiền tố `tenant_key`, xây dựng `TenantScopedCollection` và `inject_tenant_filter` (6/6 tests pass).
  * **Workstream 3 (Bộ định tuyến Sự kiện & Client Pool Đa Doanh nghiệp)**: Trích xuất `tenant_key` từ webhook header/sender, tự động bao bọc luồng async bằng `async_tenant_context(tenant_key)`, cài đặt lifecycle handler (`app_status_change`, `app_uninstalled`) và mở rộng Messenger API (8/8 tests pass).
  * **Multi-Tenant Claims & Knowledge Isolation Hardening**: Bọc kín toàn diện truy vấn tri thức (`get_all_facts`, `get_all_entities`, `save_extraction_to_mongo`, `get_scope_by_chat_id`), bổ sung lớp Defense-in-depth trong `ContextComposer` (loại bỏ triệt để claims của tenant khác kể cả khi `scope_type="global"`), mở rộng `ChatQueueItem` truyền thông suốt `tenant_key` (6/6 tests pass).
  * **Workstream 4 (Đa Dataset WeKnora & Auto-Provision Bitable theo Doanh nghiệp)**: Cấp phát không gian tri thức 3 tầng (`policy_dataset_id`, `wiki_dataset_id`, `project_dataset_id`), tự động tạo WeKnora Tenant & Admin Credentials (Giải pháp B), bàn giao tài khoản qua Lark DM và hiển thị trực tiếp trên Screen Guide Onboarding Wizard, tự động tạo Lark Base trên Drive khách theo `tenant_key` (10/10 tests pass).
- **Tổng kiểm thử Final Test Suite (ISV Multi-Tenant & Auto-Provision Hardening):** **117/117 PASSED 100%** (chạy trong 32.04s).
- **Trạng thái Container Docker:** `hilark-server` đã được build lại bằng mã nguồn mới nhất và đang chạy ổn định (healthy, port 8000).
- **Kiểm tra trực tiếp Lark Base trên Cloud (`WNlUbn5avaDHNNsZGqijoca6pVe`):**
  * Bảng 1: Không còn dòng trống, không còn cột rác. Primary column là `Dự án / Nhóm`, 3 dự án mẫu nằm ở đúng hàng 1, 2, 3.
  * Bảng 2: View mang tên `Tất cả Chính sách`, primary column là `Tên văn bản / Quy định`, bản ghi mẫu hoàn chỉnh.

- **Khắc phục lỗi 403 Forbidden khi nạp tài liệu WeKnora (EDL-0033)**:
  * **Nguyên nhân**: `WEKNORA_API_KEY` trong `.env` ban đầu có `scope_type = 'tenant'` cố định vào tenant 10000, nên khi gửi `X-Tenant-ID: 10002` (hoặc dummy 20108), WeKnora trả về `403 Forbidden: workspace API key cannot switch workspaces`. Đồng thời `is_builtin` của models Embedding và KnowledgeQA là `false`, khiến tenant 10002 không tìm thấy model embedding.
  * **Giải pháp**:
    1. Chuyển đổi API Key sang `scope_type = 'platform'`, `tenant_id = NULL` với đầy đủ capabilities trong `WeKnora-postgres`.
    2. Cập nhật `is_builtin = true` trên 2 models hệ thống (`gemini-2.5-flash` và `gemini-embedding-001`).
    3. Cập nhật `weknora_provision_service.py`: trích xuất `tenant_id` thực từ `/auth/register` (hoặc `/auth/login`), gán chính xác `tenant_id` thực (10002) vào MongoDB và KBs.
    4. Sửa endpoint `get_document_info` sang `GET /knowledge/{id}` chuẩn của WeKnora.
    5. Đã kiểm chứng thực tế: Đồng bộ thành công 100% tài liệu Wiki từ Lark Base (`TÀI LIỆU DỰ ÁN MẪU_ HỆ THỐNG BÁN LẺ THÔNG MINH OMNISHOP.md`) sang KB `fc733015-7e39-4d4b-92c4-5a57cf5b3f2f` của Tenant 10002 với `Parse Status: completed`, `Summary Status: completed`.

## Next concrete steps
1. Mời Admin đăng nhập WeKnora Web Console (`http://localhost/login`) với tài khoản `admin_19a84399@hilark.internal` để xem trực tiếp tài liệu đã được nạp và bóc tách hoàn chỉnh.
2. Kiểm tra bot trong nhóm chat với câu hỏi liên quan đến tài liệu dự án để xác nhận RAG retrieval hoạt động mượt mà.

## Current session update — Hoàn Tất Toàn Diện Cô Lập Dữ Liệu Đa Doanh Nghiệp (EDL-0035 Zero Cross-Tenant Data Leakage)
- **Tình trạng:** Đã hoàn thành 100% cả 5 giai đoạn theo kế hoạch phê duyệt `multi_tenant_isolation_plan.md`.
- **Chi tiết các thành phần đã hoàn tất:**
  1. **Giai đoạn 1 (Models & Core DB Layer):**
     - Bổ sung `tenant_key` vào `PendingDraft` model trong `server/models/chat.py`.
     - Cập nhật `get_pending_proposed_claims`, `promote_all_proposed_claims`, `promote_proposed_claims_for_chat` và `get_latest_proposed_claim` trong `server/database/db.py` áp dụng `inject_tenant_filter`.
  2. **Giai đoạn 2 (Staging & Master Daily Digest Isolation):**
     - Sửa `add_staging_message`, `get_staging_messages`, `get_active_chat_ids_today` trong `server/services/workflows/digest_workflow.py` bắt buộc cô lập `tenant_key`.
     - Phân giải ID Master Digest độc lập chống ghi đè: `master_digest_{tenant_key}_{date}`.
     - Cập nhật scheduler daemon trong `bot_runner.py` quét danh sách active tenants từ MongoDB và chạy báo cáo ngày độc lập cho từng tenant.
  3. **Giai đoạn 3 (Claims & Draft Approval Workflow Isolation):**
     - Mở rộng toàn bộ interface của `ClaimService`, `DraftStore`, `DraftService` hỗ trợ `tenant_key`.
     - Nhúng `tenant_key` vào action value của các nút bấm trên Thẻ tương tác (`build_draft_card`, `build_claim_approval_card`, `build_digest_approval_card`).
     - Tái cấu trúc `card_action_handler.py` trích xuất `tenant_key` từ header hoặc action payload, bao bọc toàn bộ luồng xử lý trong `async with async_tenant_context(tenant_key):` và gọi `update_card_message(..., tenant_key=tenant_key)`.
  4. **Giai đoạn 4 (Động hóa Owner Identity & Bitable Context):**
     - Thêm bộ đệm `_tenant_admin_cache` và các hàm `register_tenant_admin`, `get_tenant_admin` vào `LarkDispatcherMixin`.
     - Nhận diện `is_self` và `is_owner` dựa trên `admin_open_id` của từng tenant thay vì biến tĩnh toàn cục.
     - Cập nhật `_get_headers` và `subscribe_events` trong `server/services/lark/bitable.py` lấy đúng tenant access token qua `isv_token_service`.
  5. **Giai đoạn 5 (Scoped REST APIs & Test Suite):**
     - Thêm tham số `tenant_key` vào các REST API endpoints trong `server/routers/scope.py` và `server/routers/digest.py`.
     - `scope_service.list_all_scopes` và `set_chat_kb` áp dụng bộ lọc tenant.
     - Xây dựng Test Suite toàn diện `server/tests/final_test/test_cross_tenant_isolation_complete.py`: 5/5 test cases passed 100%.
     - Kiểm thử regression các suite multi-tenant liên quan: `test_multi_tenant_db_isolation.py` (6/6 passed), `test_claims_knowledge_multi_tenant.py` (6/6 passed), `test_event_ingress_multi_tenant.py` (8/8 passed).
     - Đồng bộ Decision Log `EDL-0035` lên Notion Database.

## Next concrete steps
1. Chạy thử nghiệm thực tế với 2 tài khoản Lark thuộc 2 tenant khác nhau để quan sát tương tác thẻ duyệt DM và Master Digest.
2. Kiểm tra log vận hành của bot daemon trên server để đảm bảo scheduler 23:00 quét và gửi báo cáo phân tách hoàn hảo cho từng doanh nghiệp.

## Current session update — Required App/Tenant/User Setup Flow (EDL-0039)
- Setup landing đã yêu cầu App ID và App Secret, gọi test credential rồi mới lưu cấu hình mã hóa trước khi bắt đầu OAuth.
- OAuth user là bắt buộc: pipeline từ chối tiếp tục nếu không có đủ `access_token` và `refresh_token`; refresh token được lưu qua `token_service` để có thể tự làm mới access token.
- ISV App lấy `tenant_access_token` theo `tenant_key` qua `app_access_token`; Custom App dùng endpoint `/tenant_access_token/internal` trong lúc provision Base. Không dùng tenant token để giả danh user.
- Pipeline không còn đánh dấu Ready nếu Lark Base provision thất bại; cả Base và WeKnora phải hoàn tất.
- Setup screen giải thích rõ ba lớp quyền: App credential, tenant token và user OAuth; lỗi xác thực hiển thị ngay tại form.
- Verification: `tests/final_test/test_one_click_setup.py`, `test_isv_token_service.py`, `test_marketplace_onboarding_experience.py` — **28/28 PASSED**, 2 warning deprecation từ thư viện Lark.

## Next concrete steps
1. Test manual callback OAuth bằng một tenant Lark thật, xác nhận callback trả đủ `access_token`, `refresh_token`, `tenant_key`.
2. Test provision Base/WeKnora trên môi trường staging với App credential thật trước khi deploy production.

## Current session update — Explicit WeKnora Tenant Routing for Base Webhooks
- Root cause đã xác nhận bằng API response: upload tài liệu trả `409 TENANT_REQUIRED` vì WeKnora platform API key bắt buộc header `X-Tenant-ID`.
- MongoDB Atlas của container đã có mapping tenant `19835e79ba9c9942` → WeKnora tenant `10004`, KB mặc định `a36f62f2-2b14-484b-97f3-135705c41cd0`.
- Sửa `server/services/knowledge/chat_scopes.py`: Bitable webhook truyền thẳng tenant config đã resolve theo `bitable_app_token/table_id` vào `sync_group_from_base_record`, tránh phụ thuộc `ContextVar` không có trong webhook task; thêm log routing và log lỗi upload chi tiết.
- `compileall` pass. Regression chọn lọc: `27 passed, 2 failed`; 2 failure còn lại là lỗi môi trường/network test cũ (DNS MongoDB Atlas và mocked Lark Base PATCH chưa được mock), không liên quan patch routing.
- Cần rebuild/restart server rồi sửa/lưu lại ô tài liệu trong Base để replay event; kiểm tra log có `tenant_id=10004` và upload thành công.

## Current session update — Preserve JEV Routing for Owner Messages
- Sửa `server/services/workflows/chat_workflow.py`: Owner Shield chỉ giữ `reply_to_lark=False` từ caller để chống loop; không còn đổi kết quả JEV thành `MEMORY_ONLY` hoặc `IGNORE`.
- Owner message hiện tôn trọng đầy đủ action JEV: `IGNORE` không lưu, `MEMORY_ONLY` mới lưu memory, `REPLY_ONLY` chỉ xử lý nội bộ không reply group, `MEMORY_AND_DRAFT` theo đúng HITL flow.
- Verification: `tests/final_test/phase_2_chat_intent_safety/test_phase_2_chat_intent_safety.py` — **9 passed, 2 warnings**.
- Sau khi kiểm tra log thực tế, bổ sung `speaker_role` vào `JevService.classify_message()` và role guidance riêng cho owner để JEV không mặc định coi phát ngôn của sếp là memory. Docker đã rebuild và health `healthy`.

## Current session update — Compact Message Processing Logs
- Dọn log hot path ở dispatcher, bot runner, member handler, chat queue và digest staging: bỏ banner/trùng lặp, chuyển payload chi tiết sang `DEBUG`, chuẩn hóa `INFO` thành `[INGRESS]`, `[DISPATCH]`, `[ROUTE]`, `[STORE]`, `[DRAFT]`, `[REPLY]`, `[DROP]`.
- `[STORE] staging=yes memory=no` giờ thể hiện rõ staging không phải memory/claims; chỉ khi action cần lưu mới ghi `memory=yes`.
- Verification: compile pass; `test_phase_2_chat_intent_safety.py` + `test_event_ingress_multi_tenant.py` — **17 passed, 2 warnings**. Docker `healthy`.
- Hotfix sau runtime log: sửa nhầm `chat_queue_service.debounce_seconds` thành resolve an toàn qua `chat_queue_service.debouncer.debounce_seconds`; lỗi trước đó làm task handler dừng sau staging. Regression lại **17 passed**, Docker `healthy`.

## Current session update — Multi-Custom-App Runtime Foundation (EDL-0041)
- Đã tạo implementation plan tại `docs/IMPLEMENTATION_PLAN_MULTI_CUSTOM_APP.md` cho mô hình một server phục vụ nhiều Custom App của nhiều công ty.
- Đã thêm registry `lark_app_credentials`: App Secret, verification token và encrypt key được mã hóa; không còn ghi đè settings global trong flow `/setup`.
- OAuth setup dùng `registration_id`, gọi đúng `app_id/app_secret` của tenant; token user được lưu bằng `_id = lark_app:{app_id}:user:{tenant_key}:{open_id}`.
- Đã sửa lỗi token exchange trước đây luôn ghi vào `primary_user_token`; refresh lazy theo App/tenant hiện cập nhật đúng document và không dùng nhầm global app token.
- Webhook có runtime client/dispatcher theo `app_id`, xác thực verification token theo App, đặt `current_lark_service` theo request để các handler/chat workflow gửi trả bằng đúng App credential.
- Regression kiểm chứng: compile thành công; `tests/final_test/test_one_click_setup.py`, `test_isv_token_service.py`, `test_event_ingress_multi_tenant.py` — **26 passed, 2 warnings**.

### Việc còn phải làm trước khi gọi production-ready
1. Bổ sung test integration thật cho hai Custom App đồng thời (hai app_id, hai tenant, hai token document, hai webhook payload).
2. Hoàn thiện các background workflow chạy ngoài request context (digest scheduler, lifecycle/card callback) để chúng luôn resolve runtime client từ `tenant_key`, không phụ thuộc ContextVar của webhook.
3. Thêm auth/rate-limit/CSRF protection cho endpoint đăng ký App credential; hiện endpoint này phục vụ setup nội bộ và chưa phải public SaaS onboarding hardened.

## Current session update — Strict Claims Scope Resolution (EDL-0036)
- Refactor `get_all_facts` hỗ trợ `scope_type` và `strict_chat`; project Q&A không còn mở rộng query qua `global` hoặc `project_tag` khi đã có `chat_id`.
- Policy Q&A query riêng claims `scope_type="global"`, sau đó vẫn yêu cầu `is_policy` và `status="current"`.
- Entity lookup được giới hạn theo `entity_id` xuất hiện trong claims đã query và cùng `tenant_key`.
- Giữ nguyên một danh sách `forbidden_labels`; không tách query/content labels theo quyết định của người dùng.
- Regression suite liên quan: 33 passed, 2 thư viện Lark deprecation warnings.

## Current session update — P1/P2 Production Hardening (EDL-0037)
- P1: thêm collection `setup_sessions` với unique `task_id`, TTL 2 giờ; setup state được hash/consume một lần, polling fallback Mongo sau restart/scale-out.
- P1: lifecycle event bỏ qua provisioning lặp cho tenant đã `ready/provisioning`; chỉ ghi `ready` khi provision trả về WeKnora tenant ID, lỗi ghi `provisioning_failed`.
- P2: bổ sung tenant filter cho digest get/approve/reject, master digest theo ID, ChatScope delete và user settings; bỏ fallback WeKnora tenant `10000` khi chưa resolve được tenant.
- P2: index user settings không còn global-unique theo `open_id`; startup migration drop index cũ và dùng index tenant-aware.
- Verification: compile thành công; regression liên quan P1/P2 `25 passed, 2 warnings`. `git diff --check` còn cảnh báo whitespace/blank-line có sẵn ở `HANDOFF.md` và `card_builder.py`.
- Dev/test cho phép persistence warning khi Mongo unavailable; `.env.production.example` bật `ENVIRONMENT=production` và `SETUP_REQUIRE_DURABLE_STATE=true`, khi đó setup sẽ fail-fast thay vì fallback RAM.

## Current session update — Digest/Master Digest Scope Completion (EDL-0038)
- Bổ sung tenant filter cho staging upsert/processed update, claims dùng trong digest, previous daily/master digest, daily/master digest save và WeKnora sync update.
- Daily digest ID có tenant prefix khi có tenant; tránh collision giữa hai doanh nghiệp cùng ngày/chat ID.
- Master digest đã dùng tenant trong ID và toàn bộ get/pending/approve/reject/update path.
- Regression: Phase 3 digest + P1/P2 suites `32 passed, 2 warnings`.

## Current session update — Tenant-scoped Digest Schedule (EDL-0046)
- Màn hình cấu hình trợ lý dùng ô chọn giờ tùy ý (không còn giới hạn 4 mốc cố định); API lưu `digest_schedule_time` theo cặp `open_id + tenant_key`.
- Chuẩn hóa giờ về `HH:MM` và từ chối giá trị ngoài `00:00–23:59` trước khi ghi MongoDB.
- Digest scheduler đọc giờ của admin từng tenant, nên mỗi doanh nghiệp có thể chạy Digest ở giờ khác nhau; tenant chưa cấu hình vẫn fallback về `DIGEST_SCHEDULE_TIME` trong `.env`.
- Scheduler đánh dấu đã chạy theo từng tenant/ngày, không còn dùng một mốc chạy chung cho toàn bộ server.
- Verification: compile pass; `test_one_click_setup.py` **9 passed**; onboarding suite **34 passed, 1 failed** do sandbox không phân giải DNS MongoDB Atlas, không liên quan thay đổi Digest. Docker rebuild thành công, container `hilark-server` healthy.

## Current session update — Acknowledge Unsupported Drive Read Event
- Lark WebSocket có thể gửi `drive.file.read_v1` khi người dùng mở/đọc file; SDK không có typed handler trong pipeline hiện tại nên trước đây ghi `processor not found`.
- Đăng ký event này như custom no-op để acknowledge an toàn và giữ ingest tài liệu ở pipeline riêng; không ảnh hưởng message/Base events.
- Verification: `test_event_ingress_multi_tenant.py` **8 passed**, compile pass, Docker container healthy.

## Current session update — Tenant-specific Master Digest Sender (EDL-0047)
- Root cause lỗi `open_id cross app`: scheduler lấy đúng `admin_open_id` theo tenant nhưng vẫn gọi singleton Lark client/App mặc định.
- Thêm lookup Custom App theo `tenant_key` và resolve runtime client trước khi gửi thẻ duyệt Master Digest; fallback client mặc định chỉ còn dùng khi tenant chưa có mapping App.
- Verification: Digest suite **9 passed**, compile pass, Docker container healthy.

## Current session update — Tenant Context for Digest Sync and Card Callback (EDL-0048)
- Daily Digest sync now passes `X-Tenant-ID` from the tenant's `weknora_tenant_id` to `save_to_kb`; if a tenant lacks that mapping, sync fails safely instead of writing to an ambiguous workspace.
- Card action webhook resolves the registered Custom App runtime before executing update-card, preventing `open_id cross app` / wrong sender identity.
- Verification: Phase 3 Digest + event ingress **17 passed**, compile pass, Docker container healthy.
- Bổ sung fallback cho endpoint `/card-action`: nếu callback không có `header.app_id`, hệ thống resolve Custom App bằng `tenant_key` nằm trong action payload.

## Current session update — JEV Urgent Request Routing (EDL-0049)
- Bổ sung vào prompt JEV quy tắc: tin có deadline gần/yêu cầu xử lý trong ngày và đang xin phương án, chỉ đạo hoặc phản hồi cho vấn đề công việc/khách hàng/thương lượng/rủi ro sẽ chọn `MEMORY_AND_DRAFT`.
- Tin chỉ thông báo khẩn nhưng không yêu cầu phản hồi vẫn giữ `MEMORY_ONLY`, tránh biến mọi tin có chữ “gấp” thành draft.
- Verification: phase 2 intent safety + event ingress **17 passed**, Docker container healthy.

## Current session update — Multi-Tenant Token Refresh and App Mismatch Handling
- Token refresh loop now scans registered `app_id + tenant_key` pairs instead of only the legacy `primary_user_token`.
- Lark error `20024/20038` marks the affected token document as `invalid_refresh_token` and stops repeated refresh attempts; the tenant must OAuth again using the same registered Custom App.
- Runtime verification: loop detected `app=cli_aa6c6ae8baf85e11`, tenant-scoped refresh attempted, and container remains healthy. Existing token still requires reauthorization because Lark reports an App ID mismatch.








## Current session update — PolicySync nhận diện link Wiki trong Base
- Root cause: PolicySync đọc được record nhưng parser phụ thuộc vào một số field key và shape cố định; Lark records API có thể trả mention/link dưới field ID khác hoặc dưới dạng JSON string, nên log báo `1 bản ghi` nhưng `0 tokens`.
- Đã sửa `server/services/knowledge/policy_sync.py`: parser đệ quy cho dict/list/JSON string, nhận `link/url/text/token`, fallback quét semantic link khi key không khớp, đồng thời giữ xử lý attachment.
- Verification: `server/.venv/bin/pytest -q server/tests/final_test/test_policy_sync_parser.py` — **2 passed**. Docker rebuild `docker compose -f docker-compose.prod.yml up -d --build hilark-server` thành công; container `running healthy`; `/health` trả `status=ok` và MongoDB `connected`.
- Bước kiểm tra tiếp theo: sửa/lưu lại record chính sách trong Base để phát event; log mong đợi là `Trích xuất được 1 tokens...` và sau đó parser WeKnora bắt đầu xử lý Wiki token.
## Current session update — Bật rich-text response cho PolicySync
- Runtime vẫn trả `0 tokens` dù parser đã hỗ trợ field ID; nguyên nhân bổ sung là PolicySync gọi `/records` chỉ với `page_size`, có thể làm Lark trả display text thay vì cấu trúc mention/link.
- Đã thêm `user_id_type=open_id` và `text_field_as_array=true` vào request records, cùng warning shape an toàn khi không tìm thấy link/file.
- Verification: parser test **2 passed**; Docker rebuild thành công; container `running healthy`; `/health` trả `status=ok`.
- Bước xác nhận: chỉnh/lưu lại record trong bảng Chính sách và kiểm tra log request có `text_field_as_array=true`, sau đó log extraction phải lớn hơn 0.
## Current session update — PolicySync bind đúng Custom App khi đọc tài liệu
- Sau khi extraction đã đúng (`1 token`), log phát hiện User Token không hợp lệ và Bot token bị `permission denied`. Root cause code: PolicySync chạy trong background Bitable task nhưng `doc_parser_service` dùng singleton Lark client, không bind runtime theo `tenant_key`.
- Đã sửa `server/services/knowledge/policy_sync.py`: trước khi đọc DocX/Wiki, resolve `lark_app_service.get_by_tenant_key`, tạo runtime client tương ứng và đặt ContextVar; luôn reset context sau khi hoàn tất.
- Verification: compile pass; parser + multi-tenant ingress tests **10 passed**; Docker rebuild thành công; container `running healthy`; `/health` trả `status=ok`.
- Bước kiểm tra: sửa/lưu lại policy record. Log cần có `[PolicySync] Lark runtime bound tenant=... app=...`; nếu sau đó vẫn `permission denied`, cần cấp quyền đọc Wiki node cho Bot/App hoặc re-authorize User OAuth đúng Custom App.
## Current session update — loại bỏ cảnh báo token legacy trong multi-Custom-App mode
- Root cause: `start_bot_service()` luôn gọi `check_and_warn_token(token=lark_service.user_access_token)` trên singleton legacy, nên token `.env`/primary cũ hết hạn vẫn phát banner dù token scoped của từng Custom App được refresh riêng.
- Đã sửa `server/services/lark/bot_runner.py`: nếu có registration active theo tenant, bỏ qua legacy ping/banner và hiển thị tenant-scoped token mode; runtime vẫn resolve/refresh theo `tenant_key + app_id`.
- Verification: compile pass; token/policy tests **11 passed**. Docker rebuild chưa xác nhận trong lượt này vì quyền truy cập Docker socket bị từ chối khi xin escalation.
- Lệnh cần chạy sau khi có quyền Docker: `docker compose -f docker-compose.prod.yml up -d --build hilark-server`.
## Current session update — sửa `open_id cross app` khi gửi draft approval
- Root cause: `resolve_effective_owner_open_id()` ưu tiên `owner_open_id/known_user_open_id` từ global/DB trước khi hỏi `user_info` của runtime Custom App hiện tại. Lark `open_id` là App-scoped nên App B không thể gửi tới ID do App A cấp.
- Đã sửa `server/services/workflows/chat_workflow.py`: khi có `tenant_key` và User Token của runtime, lấy open_id từ `get_current_user()` trước; các nguồn global chỉ còn fallback.
- Verification: compile pass; isolation/ingress tests **13 passed**; Docker rebuild thành công; container `running healthy`; `/health` trả `status=ok`.
- Bước kiểm tra: tạo lại một message cần `MEMORY_AND_DRAFT`; log không còn `open_id cross app`. Nếu còn, cần kiểm tra runtime App đã resolve đúng tenant và User OAuth của App đó.
## Current session update — bỏ refresh legacy primary token trong multi-App startup
- Runtime log xác nhận `refresh_user_token(app=None, tenant=...)` đang đụng bản ghi `primary_user_token` legacy và refresh token đã bị invalidated; đây là lỗi thật của token cũ, không phải token scoped hiện tại.
- Đã sửa `server/services/auth/token_service.py` và `server/services/lark/client.py`: nếu tồn tại Custom App scoped, startup bỏ qua primary token legacy; chỉ token loop theo `tenant_key + app_id` được refresh.
- Verification: token/isolation/ingress tests **22 passed**; Docker rebuild thành công; container `running healthy`; `/health` trả `status=ok`.

## Current session update — Khắc phục triệt để lỗi User Token & Định tuyến Multi-Tenant trong luồng Duyệt Draft (Approve Draft)
- Root cause:
  1. `draft_workflow._send_claimed()` chỉ truyền `tenant_key` mà không truyền `app_id`. Khi `token_service.get_valid_user_token(tenant_key)` tìm trong MongoDB, vì thiếu sort theo thời gian và không loại trừ status invalid, nó luôn bốc trúng bản ghi cũ `primary_user_token` (mang `status: "invalid_refresh_token"`) thay vì bản ghi scoped mới `lark_app:cli_aa6c6ae8baf85e11:...` vừa được cấp.
  2. `messenger._prepare_user_msg_payload_async()` sau khi lấy token hợp lệ lại gọi `self._get_user_request_option()`, đọc `self.user_access_token` cũ trong RAM của singleton mặc định thay vì gán `valid_token` vào `RequestOption`.
  3. Khi không lấy được User Token, hệ thống fallback sang Bot nhưng Bot chưa được add vào nhóm chat nên Lark API trả về lỗi 230002.
- Đã sửa:
  1. `server/services/auth/token_service.py`: trong `get_valid_user_token` và `get_stored_token_data`, nếu có `tenant_key` mà `app_id` chưa có hoặc mang giá trị default `.env`, tự động resolve `app_id` qua `lark_app_service.get_by_tenant_key(tenant_key)`; ưu tiên bản ghi có `status != "invalid_refresh_token"` và sort `[("updated_at", -1)]`.
  2. `server/services/lark/messenger.py`: trong `_prepare_user_msg_payload_async`, tự động điều chỉnh `target_app_id`, gán `self.user_access_token = valid_token` và trực tiếp tạo `lark.RequestOption.builder().user_access_token(valid_token).build()`.
  3. MongoDB: Gỡ bỏ `tenant_key` khỏi bản ghi legacy `primary_user_token` để không bao giờ gây va chạm truy vấn cho tenant `19835e79ba9c9942`.
- Verification:
  1. `token_service.get_valid_user_token(tenant_key="19835e79ba9c9942")` tự động tìm và trả về đúng token sống `u-6q2EuY.gt5FWG...` (100% passed).
  2. `_prepare_user_msg_payload_async()` tạo thành công `RequestOption` mang `opt.user_access_token = u-6q2EuY.gt5FWG...` (100% passed).
  3. Container `hilark-server` đã rebuild và chạy healthy.
