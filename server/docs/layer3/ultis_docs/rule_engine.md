# 📘 BÓC TÁCH KỸ THUẬT: `utils/rule_engine.py`
> **HiLark Server** — Bộ lọc an ninh và chuẩn hóa tri thức tập trung (Unified Rule Engine).  
> **Vị trí file:** [`server/utils/rule_engine.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/rule_engine.py) (489 dòng, 21.2 KB).

---

## 🧭 1. VAI TRÒ VÀ NHIỆM VỤ

Trong quá trình tổng hợp dữ liệu để chuẩn bị trả lời, hệ thống thu thập tri thức từ 2 nguồn khác nhau:
1. **Các đoạn văn bản từ WeKnora (Tài liệu tĩnh).**
2. **Các mệnh đề sự thật từ MongoDB (Tri thức động từ cuộc trò chuyện).**

Dù đã qua cổng kiểm duyệt ý định ở Layer 2, nội dung bên trong các tài liệu hoặc tin nhắn cũ có thể vẫn vô tình chứa thông tin mật (*ví dụ: một tài liệu kế hoạch có chèn bảng lương nhân sự, hoặc một tin nhắn có nhắc đến số tiền hợp đồng bí mật*).

`rule_engine.py` đóng vai trò là **"Máy dò kim loại an ninh cuối cùng"**:
* Nhận danh sách các nhãn cấm (`forbidden_labels`) được cấu hình động trên Lark Base theo từng nhóm chat (*ví dụ: Ngân sách, Bảng lương, Hợp đồng, Thầu phụ...*).
* Quét sạch mọi đoạn trích (Chunks) và mệnh đề (Claims).
* Nếu phát hiện bất kỳ phần tử nào vi phạm $\rightarrow$ **Loại bỏ ngay lập tức** trước khi dữ liệu được chuyển sang bộ đóng gói bối cảnh (`ContextComposer`).

---

## 🛡️ 2. CƠ CHẾ LỌC ĐA TẦNG (MULTI-TIER DYNAMIC RESOLUTION)

Hệ thống áp dụng kiến trúc lọc 3 tầng thông minh, đảm bảo vừa an toàn tuyệt đối vừa không bắt nhầm các từ ngữ nghiệp vụ thông thường:

```
Nhãn cấm từ Lark Base (forbidden_labels)
                    │
    ┌───────────────┴───────────────┐
    ▼                               ▼
[TẦNG 1: MÃ HÓA THUỘC TÍNH]     [TẦNG 2: QUÉT REGEX BIÊN TỪ]
Ánh xạ sang tên trường chuẩn:    Quét chuỗi con có dấu & không dấu
- Lương -> salary, payroll...    với biên từ tiếng Việt (?<!\w)...(?!\w)
- Ngân sách -> budget, cost...   (Chống bắt nhầm 'lương' trong 'số lượng')
    │                               │
    └───────────────┬───────────────┘
                    ▼
        [TẦNG 3: KIỂM SOÁT CHẤT LƯỢNG]
        Loại bỏ văn bản rỗng, claims thiếu giá trị
                    │
                    ▼
     DỮ LIỆU ĐÃ LỌC SẠCH (SanitizeResult)
```

---

### Tầng 1: Ánh xạ thuộc tính chuẩn (Canonical Property Mapping)
* **Vị trí mã nguồn:** [`server/utils/rule_engine.py:L96-130`](file:///Users/hoainam/Desktop/HiLark/server/utils/rule_engine.py#L96-L130)
* **Nguyên lý:** Quản trị viên trên Lark Base thường nhập nhãn cấm bằng tiếng Việt có dấu hoặc không dấu (*"Ngân sách", "Lương", "Hợp đồng"*). Hệ thống tự động ánh xạ sang tập hợp các thuộc tính tiếng Anh chuẩn (`slug properties`) thường được lưu trong cơ sở dữ liệu:

| Nhãn cấm tiếng Việt | Tập hợp thuộc tính chuẩn bị khóa (`blocked_properties`) |
| :--- | :--- |
| **Ngân sách, Chi phí, Giá, Tài chính** | `budget`, `cost`, `price`, `fee`, `expense`, `financial`, `fund`, `revenue`, `profit`, `cashflow` |
| **Lương, Thu nhập, Thù lao** | `salary`, `compensation`, `income`, `payroll`, `wage`, `fee` |
| **Hợp đồng, Thỏa thuận, Đấu thầu** | `contract`, `agreement`, `deal`, `nda`, `sign`, `bid`, `bidding`, `tender` |
| **Doanh thu, Doanh số, Lợi nhuận** | `revenue`, `sales`, `profit`, `margin` |

---

### Tầng 2: Quét Regex chuỗi con động (Dynamic Literal Substring Scan)
* **Vị trí mã nguồn:** [`server/utils/rule_engine.py:L210-227`](file:///Users/hoainam/Desktop/HiLark/server/utils/rule_engine.py#L210-L227)
* **Khả năng mở rộng không cần sửa code:** Khi Sếp thêm bất kỳ nhãn cấm mới nào trên Lark Base (*ví dụ: "Thầu phụ", "Đối tác VIP", "Kế hoạch Q4"*), Rule Engine tự động biên dịch thành 2 mẫu Regex an toàn:
  1. **Accented Pattern (Có dấu):** Tìm kiếm chính xác từ có dấu trong văn bản gốc:
     ```python
     pattern_acc = re.compile(rf"(?<!\w){re.escape(lbl_lower)}(?!\w)", re.IGNORECASE)
     ```
  2. **Unaccented Pattern (Không dấu):** Tìm kiếm dạng không dấu qua hàm `remove_vietnamese_accents()` để bắt trường hợp người dùng hoặc tài liệu gõ không dấu.
* **Kỹ thuật chống bắt nhầm (False-Positive Protection):**
  * Đối với các từ đơn 1 âm tiết (như *"lương"*), hệ thống **tuyệt đối không quét không dấu (`luong`)**! Vì nếu quét `luong`, hệ thống sẽ bắt nhầm từ *"số lượng"* (*so luong*), gây lọc oan các tài liệu về số lượng tính năng hay sản phẩm!

---

### Tầng 3: Kiểm soát tính hợp lệ của dữ liệu (Data Quality & Validity)
* Lọc bỏ hoàn toàn các đoạn trích rỗng hoặc quá ngắn (dưới 10 ký tự).
* Lọc bỏ các mệnh đề thiếu thuộc tính (`property`) hoặc có giá trị rỗng (`value is None`).

---

## 🔍 3. LOGIC KIỂM TRA CHI TIẾT

### A. Kiểm tra mệnh đề sự thật (`is_claim_violating`)
- **Vị trí mã nguồn:** [`server/utils/rule_engine.py:L259-299`](file:///Users/hoainam/Desktop/HiLark/server/utils/rule_engine.py#L259-L299)
- **Kiểm tra qua 3 thành phần của Claim:**
  1. **Kiểm tra Thuộc tính (`property`):** Sử dụng thuật toán giao tách token (`token intersection`) thay vì kiểm tra chuỗi con đơn thuần.
     * *Ví dụ:* Nếu cấm `fee`, từ `feedback` sẽ **không bị chặn**! Nếu cấm `gia`, từ `giai_doan` sẽ **không bị chặn**!
  2. **Kiểm tra Giá trị (`value`):** Quét xem chuỗi giá trị có chứa từ khóa cấm hay không.
  3. **Kiểm tra Trích dẫn bằng chứng (`source_snippet`):** Quét câu trích dẫn gốc từ tin nhắn.

---

### B. Kiểm tra đoạn trích văn bản (`is_chunk_violating`)
- **Vị trí mã nguồn:** [`server/utils/rule_engine.py:L300-329`](file:///Users/hoainam/Desktop/HiLark/server/utils/rule_engine.py#L300-L329)
- **Kiểm tra qua 2 thành phần:**
  1. **Nội dung đoạn trích (`content`):** Quét toàn bộ nội dung của chunk.
  2. **Tên file tài liệu (`document_name`):** Nếu tên file chứa nhãn cấm (*ví dụ: "Bang_luong_thang_10.xlsx"*), toàn bộ các đoạn trích từ file này bị gạch bỏ ngay lập tức.

---

## 📦 4. CẤU TRÚC KẾT QUẢ & CÚ PHÁP TUPLE UNPACKING

Kết quả trả về được đóng gói trong đối tượng dữ liệu `SanitizeResult`:

```python
@dataclass
class SanitizeResult:
    clean_chunks: List[Dict[str, Any]]    # Danh sách chunks an toàn
    clean_claims: List[Dict[str, Any]]    # Danh sách claims an toàn
    dropped_chunks: List[Dict[str, Any]]  # Chunks bị loại kèm lý do
    dropped_claims: List[Dict[str, Any]]  # Claims bị loại kèm lý do
    forbidden_labels: List[str]          # Danh sách nhãn cấm đã dùng
    stats: Dict[str, Any]                 # Thống kê số lượng
```

### Hỗ trợ cú pháp mở gói trực tiếp (Tuple Unpacking):
Nhờ phương thức `__iter__` được cài đặt sẵn ([`L146-148`](file:///Users/hoainam/Desktop/HiLark/server/utils/rule_engine.py#L146-L148)), các service khác có thể gọi Rule Engine với cú pháp cực kỳ ngắn gọn và tự nhiên:

```python
clean_chunks, clean_claims = rule_engine.sanitize(
    chunks=normalized_chunks,
    claims=active_claims,
    forbidden_labels=scope_record.forbidden_labels,
    query=clean_query,
)
```

---

## 📋 5. BẢNG TRA CỨU HÀM VÀ THUỘC TÍNH

| Tên hàm / Thuộc tính | Kiểu dữ liệu | Chức năng chính |
| :--- | :---: | :--- |
| `sanitize()` | Phương thức chính | Thực hiện lọc toàn diện cả Chunks và Claims dựa trên nhãn cấm. |
| `is_claim_violating()` | Phương thức kiểm tra | Đánh giá một Claim/Fact cụ thể có phạm nhãn cấm hay không. |
| `is_chunk_violating()` | Phương thức kiểm tra | Đánh giá một Chunk tài liệu cụ thể có phạm nhãn cấm hay không. |
| `is_text_violating()` | Phương thức kiểm tra | Quét Regex trên chuỗi văn bản thuần túy. |
| `parse_labels()` | Hàm tiện ích | Chuẩn hóa chuỗi hoặc mảng nhãn đa dạng từ Lark Base về danh sách chuẩn. |
| `remove_vietnamese_accents()` | Hàm tiện ích | Chuyển đổi văn bản tiếng Việt có dấu thành không dấu an toàn (hỗ trợ cả đ/Đ). |
| `rule_engine` | Biến Singleton | Thực thể dùng chung toàn hệ thống được khởi tạo sẵn ở cuối file. |
