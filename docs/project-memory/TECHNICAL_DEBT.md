# Báo Cáo & Danh Mục Nợ Kỹ Thuật (Technical Debt & Code Smells)

> **Dự án:** HiLark Server  
> **Thời điểm rà soát:** 24/10/2026  
> **Người thực hiện:** Antigravity AI Pair Programmer  
> **Điểm đánh giá chất lượng toàn diện:** **6.8 / 10** (Vận hành tốt chức năng nhưng nợ kỹ thuật bắt đầu tích tụ)

---

## 1. Bảng Điểm Đánh Giá Định Lượng

| Tiêu chí | Điểm | Hiện trạng tóm tắt |
| :--- | :---: | :--- |
| **Tính mô-đun & Kiến trúc** | **6.5 / 10** | Tồn tại "God Object" (`chat_service.py`, `larkbase.py`), workaround import vòng trong hàm. |
| **Tính tinh gọn (DRY - Không trùng lặp)** | **6.0 / 10** | 4 luồng quản lý Token độc lập, giẫm chân nhau; trùng lặp hàm format thời gian. |
| **Mức độ sạch sẽ & Tính chắp vá** | **6.5 / 10** | Hardcode từ khóa chính sách, cấp phát lại 5 bộ từ điển tĩnh mỗi khi xử lý request. |
| **Quản lý Tài nguyên & Async I/O** | **6.5 / 10** | Anti-pattern tạo mới `httpx.AsyncClient` 11+ lần; lệnh đồng bộ chạy trong luồng khởi động. |
| **Cơ sở dữ liệu & Bộ nhớ** | **5.5 / 10** | **0 Database Indexes** trên 7 collections; memory leak cache tin nhắn không giới hạn. |
| **Độ tin cậy của Test Suite** | **8.5 / 10** | 109/110 tests pass, bao phủ rất tốt các ca biên bảo mật & gating. |

---

## 2. Danh Mục Vấn Đề Code Dirty (Mã Nguồn Chưa Sạch)

### 2.1. Phân mảnh quản trị Token (4 cơ chế độc lập, giẫm chân nhau)
* `server/services/larkbase.py` (L166-L197): Tự cài đặt `get_tenant_access_token()` đồng bộ gọi trực tiếp endpoint `/open-apis/auth/v3/tenant_access_token/internal`.
* `server/services/larkServices/lark_client.py` (L87-L95): Dùng `lark.Client.builder()` của `lark_oapi`, bản thân SDK đã có bộ quản lý và refresh tenant token riêng trong RAM.
* `server/services/token_service.py` (L74-L120): Có hàm riêng `get_app_access_token()` bất đồng bộ cũng gọi Lark API để phục vụ OIDC.
* `server/utils/lark_token.py` (L131-L180): Bộ parser JWT và network ping kiểm tra token độc lập.
* **Tác hại:** Khi thay đổi thông tin xác thực, phải cập nhật 4 nơi; lãng phí bộ nhớ lưu nhiều phiên bản token cùng lúc.

### 2.2. Trùng lặp mã (Code Duplication - DRY)
* **Hàm định dạng thời gian:** 
  * `server/services/token_service.py` (L36-L62): `format_remaining_seconds(seconds: Optional[float]) -> str`.
  * `server/utils/lark_token.py` (L70-L95): `format_remaining_time(self) -> str`.
  * Cả hai đều bóc tách ngày/giờ/phút/giây và sinh chuỗi tiếng Việt y hệt nhau.
* **Hàm trích xuất Lark Token:**
  * `extract_lark_token` nằm cục bộ tại `server/services/policy_sync_service.py` (L32-L75), khiến các module khác không thể tái sử dụng.

### 2.3. "God Object" quá tải trách nhiệm
* `server/services/chat_service.py` (834 dòng): Ôm trọn 10 nghiệp vụ từ tiền xử lý, staging, tra cứu scope, gọi JEV, WeKnora RAG, compose context, rule engine, quản lý draft, LLM generate, đến reply Lark.
* `server/services/larkbase.py` (1047 dòng): Nhồi nhét cả argparse CLI, threading, httpx custom, đồng bộ bitable, CRUD record, event handling.

### 2.4. Workaround giải quyết Nhập khẩu vòng (Circular Imports)
Code phải dùng local import bên trong hàm để né lỗi import vòng:
* `server/services/chat_service.py` (L171): `from utils.llm_extractor import extract_async`
* `server/services/chat_service.py` (L300): `from services.digest_service import digest_service`
* `server/utils/chat_queue.py` (L282): `from services.chat_service import process_chat_pipeline`
* **Tác hại:** Vi phạm tính độc lập module, gây khó khăn cho việc viết unit test độc lập.

### 2.5. Hardcoding từ khóa & Cấp phát lại từ điển tĩnh
* `server/services/chat_service.py` (L614-L617): Hardcode danh sách nhận diện văn bản chính sách `["so_tay", "chinh_sach", "quy_che", "quy_tac", ...]`.
* `server/utils/context_composer.py` (L473-L512): Khởi tạo lại `PROPERTY_SYNONYMS`, `PROPOSAL_INTENT_KEYWORDS`, `GENERAL_PROJECT_QUERY_KEYWORDS`, `QUERY_STOPWORDS`, `GENERIC_ENTITY_WORDS` bên trong thân hàm `align_claims_with_retriever` mỗi khi có request từ người dùng.

### 2.6. Vi phạm ranh giới tầng kiến trúc (Layer Leakage)
* `server/services/jev.py` (L19-L20): Tầng service ném `HTTPException(status_code=500)` của FastAPI. Khi chạy trong background worker hoặc WebSocket runner, exception này gây crash worker vì không có HTTP cycle.

---

## 3. Danh Mục Nợ Kỹ Thuật (Technical Debt - Tài Nguyên & Vận Hành)

### 3.1. [MỨC ĐỘ: KHẨN CẤP] Thiếu 100% Database Index trên MongoDB
* **Hiện trạng:** 0 lệnh `create_index` trên toàn bộ 7 collections (`memories`, `claims`, `conversation_staging`, `chat_scopes`, `draft_logs`, `daily_digests`, `master_daily_digests`).
* **Hậu quả:** 100% câu lệnh truy vấn đều thực hiện **Full Collection Scan (COLLSCAN)**. Sẽ làm tê liệt hệ thống khi dữ liệu tăng trưởng.
* **Khắc phục:** Cần bổ sung hàm `ensure_database_indexes()` tự động thực thi khi server startup:
  * `memories`: index `{entity_id: 1}`, `{chat_id: 1}`.
  * `claims`: index `{source_message_id: 1}`, `{chat_id: 1}`, `{status: 1}`.
  * `conversation_staging`: index `{chat_id: 1, created_at: -1}`, compound index `{status: 1}`.
  * `chat_scopes`: index `{chat_id: 1}`.

### 3.2. [MỨC ĐỘ: KHẨN CẤP] Rò rỉ bộ nhớ (Memory Leaks do Unbounded Cache)
* `server/services/larkServices/lark_messenger.py` (L143) & `lark_client.py` (L106): 
  `self._sent_message_ids` là `OrderedDict` lưu message_id bot gửi đi để chống loop, nhưng **không hề có max size, không TTL, không bao giờ popitem()**.
* `server/services/larkServices/lark_client.py` (L198-L211):
  `self._user_name_cache` là dict thường lưu họ tên người dùng, **không có kích thước tối đa**.
* **Khắc phục:** Thêm giới hạn `max_size=1000` và dọn dẹp theo thời gian (TTL 600s) tương tự như `_processed_msg_ids`.

### 3.3. [MỨC ĐỘ: CAO] Anti-pattern tạo mới `httpx.AsyncClient` liên tục
* `server/services/weknora.py`: **11 lần** gọi `async with httpx.AsyncClient(...) as client:`.
* `server/services/jev.py` (L57): Tạo mới client mỗi lần phân loại tin nhắn.
* `server/services/token_service.py` (L98): Tạo mới client mỗi lần refresh token.
* **Hậu quả:** Không tái sử dụng được TCP Connection Pool, tốn 100-300ms bắt tay TLS mỗi request, nguy cơ socket exhaustion dưới tải cao.
* **Khắc phục:** Khởi tạo một singleton `httpx.AsyncClient(limits=httpx.Limits(max_keepalive_connections=20, max_connections=50))` trong `lifespan` FastAPI và truyền vào các service.

### 3.4. [MỨC ĐỘ: TRUNG BÌNH] Lệnh I/O đồng bộ trong luồng bất đồng bộ
* `server/services/bot_service.py` (L520): `sync_bot_chats()` là hàm đồng bộ gọi nhiều API sang Lark Base, chạy trực tiếp trong `lifespan` gây block server lúc khởi động.
* `server/services/larkServices/lark_client.py` (L60-L65): Gọi `get_sync_db()` (PyMongo) để đọc token trong async context.
* `server/services/larkServices/lark_runner.py` (L274): `time.sleep(dm_poll_interval)` chặn luồng thay vì dùng async sleep hoặc interruptible event.

### 3.5. [MỨC ĐỘ: TRUNG BÌNH] Nuốt lỗi im lặng (24 vị trí `except Exception: pass`)
* Nuốt lỗi kết nối DB khi khởi tạo token (`lark_client.py: L66`).
* Nuốt lỗi bóc tách claim (`context_composer.py: L469, L630, L755`).
* Nuốt lỗi gọi WeKnora (`weknora.py: L112, L237`).
* **Khắc phục:** Thay toàn bộ `pass` bằng `logger.warning(...)` kèm chi tiết lỗi hoặc raise custom domain exception.

### 3.6. [MỨC ĐỘ: TRUNG BÌNH] Cấu hình thủ công & Hardcoded IDs
* `server/core/config.py`: Hardcode các UUID và Table ID cụ thể của môi trường dev/staging (`WEKNORA_POLICY_DATASET_ID = "d715d7ee-..."`, `LARK_BASE_POLICY_TABLE_ID = "tblZphzEZPLQAy24"`).
* Thiếu validation runtime bằng `pydantic-settings`.

### 3.7. [MỨC ĐỘ: THẤP] Lỗi cấu hình Test Suite
* Chạy `uv run pytest tests/01` bị 21 lỗi `ModuleNotFoundError` do thiếu file `pytest.ini` quy định `pythonpath = ["."]`.
* Test case `test_master_digest.py` (L127) fail do chuỗi assertion cũ (`"BÁO CÁO TỔNG HỢP TOÀN BỘ CÁC NHÓM"` vs text mới `"📊 BÁO CÁO NGÀY CẤP ĐIỀU HÀNH..."`).
* Cảnh báo `ResourceWarning: Unclosed MongoClient` do thiếu `client.close()`.

---

## 4. Lộ Trình Tái Cấu Trúc Khuyến Nghị (Action Plan)

```
[Phase 1: Ổn định Dữ liệu & Bộ nhớ] (Ưu tiên số 1 - Khẩn cấp)
  ├── 1. Tạo hàm ensure_database_indexes() cho MongoDB (7 collections)
  ├── 2. Giới hạn dung lượng (Bounded Size & TTL) cho _sent_message_ids và _user_name_cache
  └── 3. Đóng kết nối Motor/PyMongo đúng cách khi shutdown để xóa ResourceWarning

[Phase 2: Hiệu năng Mạng & Async I/O] (Ưu tiên số 2)
  ├── 1. Thiết lập Shared Persistent httpx.AsyncClient trong FastAPI lifespan
  ├── 2. Bỏ toàn bộ 11+ điểm khởi tạo httpx.AsyncClient cục bộ trong weknora.py & jev.py
  └── 3. Chuyển sync_bot_chats() sang asyncio.to_thread() lúc startup

[Phase 3: Clean Code & Kiến trúc] (Ưu tiên số 3)
  ├── 1. Thống nhất Token Management thành LarkTokenManager duy nhất
  ├── 2. Gom format_remaining_seconds và extract_lark_token vào server/utils/lark_utils.py
  ├── 3. Chuyển toàn bộ từ điển tĩnh sang server/core/lexicons.py
  └── 4. Tách nhỏ chat_service.py theo mô hình Middleware / Interceptor

[Phase 4: Cấu hình & Hoàn thiện Test] (Ưu tiên số 4)
  ├── 1. Thêm pytest.ini (pythonpath = .)
  ├── 2. Sửa assertion trong test_master_digest.py để đạt 110/110 tests pass
  └── 3. Chuyển config.py sang Pydantic BaseSettings
```
