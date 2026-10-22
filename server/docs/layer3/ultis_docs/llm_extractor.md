# 📘 BÓC TÁCH KỸ THUẬT: `utils/llm_extractor.py`
> **HiLark Server** — Module trích xuất tri thức động & quản lý phả hệ sự thật từ tin nhắn hội thoại.  
> **Vị trí file:** [`server/utils/llm_extractor.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/llm_extractor.py) (1332 dòng, 53.9 KB).

---

## 🧭 1. VAI TRÒ VÀ BÀI TOÁN CỐT LÕI GIẢI QUYẾT

Trong quá trình các thành viên và người quản lý trao đổi trên Lark, các quyết định công việc diễn ra liên tục: chốt deadline mới, đổi người phụ trách, báo cáo trạng thái tính năng...

### ❓ Vấn đề cốt lõi: Tại sao KHÔNG THỂ trích xuất Claims một cách đơn lẻ?
Hãy hình dung một tin nhắn thực tế trong nhóm:
> *"Dự án Sàn chuyển deadline sang ngày 30/10, giao Nguyên lead; còn tính năng Quét mã QR thì Trí làm, xong trước ngày 20 nhé."*

Nếu hệ thống chỉ bóc tách sự thật ngây thơ theo dạng thuộc tính đơn lẻ:
* `deadline = 30/10/2026`
* `assignee = Nguyên`
* `assignee = Trí`
* `deadline = 20/10/2026`

$\rightarrow$ **Hậu quả nghiêm trọng:** Toàn bộ các sự thật trên sẽ trở thành **"mồ côi" (Orphaned Claims)**! Hệ thống sẽ **hoàn toàn mù tịt**, không biết deadline 30/10 là của Dự án Sàn hay của tính năng Quét QR, ai là người lead của phần nào. Khi người dùng hỏi: *"Ai đang lead tính năng Quét QR?"*, AI sẽ dễ dàng lấy nhầm Nguyên sang cho Quét QR (hiện tượng "râu ông nọ cắm cằm bà kia").

### 💡 Giải pháp đột phá của LLM Extractor: Bóc tách Thực thể làm mỏ neo (Entity Anchoring)
Để sắp xếp dữ liệu chính xác 100%, `llm_extractor.py` giải quyết bài toán qua **quy trình 2 bước bắt buộc**:
1. **Bước 1 — Tìm Thực thể (Entity Anchor):** Đọc câu chat để nhận diện ra 2 chủ thể độc lập:
   * Thực thể A: `Atlas / Dự án Sàn` (`id = ent_project_san`)
   * Thực thể B: `Tính năng Quét QR` (`id = ent_feature_qr`)
2. **Bước 2 — Sắp xếp Claims vào đúng Thực thể cha (`entity_id`):** 
   * Gắn `assignee = Nguyên` và `deadline = 30/10` $\rightarrow$ Thuộc về `ent_project_san`.
   * Gắn `assignee = Trí` và `deadline = 20/10` $\rightarrow$ Thuộc về `ent_feature_qr`.

> [!IMPORTANT]
> **Giá trị cốt lõi của Entity trong hệ thống:**  
> Thực thể (`Entity`) đóng vai trò như **"ngăn tủ / chiếc móc treo / mỏ neo"**. Nhờ có Thực thể, hệ thống mới biết chính xác sắp xếp từng mệnh đề (Claims) vào đúng ngăn tủ nào, giúp `ContextComposer` gom nhóm dữ liệu mạch lạc và ngăn chặn triệt để việc nhầm lẫn thông tin giữa các dự án/tính năng!

```
❌ NẾU CHỈ BÓC TÁCH CLAIMS (KHÔNG CÓ ENTITY ANCHOR):
   "Dự án Sàn dời deadline 30/10 giao Nguyên lead, còn Quét QR thì Trí làm xong trước 20/10"
   ┌────────────────────────────────────────────────────────┐
   │ Claims trôi nổi / Mồ côi trong kho dữ liệu:           │
   │  • deadline = 30/10  (❓ Của Sàn hay của Quét QR?)     │
   │  • assignee = Nguyên (❓ Lead dự án hay làm QR?)       │
   │  • assignee = Trí    (❓ Làm phần nào?)                │
   │  • deadline = 20/10  (❓ Deadline này gắn vào đâu?)    │
   └────────────────────────────────────────────────────────┘
   => HẬU QUẢ: Hệ thống mù tịt, dễ ghép nhầm "Trí lead Dự án Sàn", "Deadline QR là 30/10".

✅ CƠ CHẾ ĐỘT PHÁ CỦA LLM EXTRACTOR (BÓC TÁCH ENTITY ĐỂ SẮP XẾP CLAIMS):
   Bước 1: Bóc tách Thực thể (Mỏ neo)    Bước 2: Sắp xếp Claims vào đúng Thực thể cha
   ┌───────────────────────────────┐     ┌───────────────────────────────────────────────┐
   │  [Entity A] Dự án Sàn         │ ──> │  • assignee = Nguyên                          │
   │   (ID: ent_project_san)       │     │  • deadline = 30/10/2026                      │
   └───────────────────────────────┘     └───────────────────────────────────────────────┘
   ┌───────────────────────────────┐     ┌───────────────────────────────────────────────┐
   │  [Entity B] Tính năng Quét QR │ ──> │  • assignee = Trí                             │
   │   (ID: ent_feature_qr)        │     │  • deadline = 20/10/2026                      │
   └───────────────────────────────┘     └───────────────────────────────────────────────┘
   => KẾT QUẢ: 100% chuẩn xác! Mọi Claim đều có "hộ khẩu" cha, không bao giờ nhầm lẫn!
```

---

## 🏗️ 2. MÔ HÌNH DỮ LIỆU CÂY 2 TẦNG (PARENT - CHILD)

Dữ liệu được tổ chức theo cấu trúc cây thực thể, phản ánh đúng thực tế kinh doanh:

```
Thực thể Cha (Entity: ID, Tên chuẩn, Loại, Bí danh, Mô tả)
    ├── Sự thật Con 1 (Fact: deadline = 30/10/2026, status = CURRENT)
    ├── Sự thật Con 2 (Fact: assignee = Nguyên, status = CURRENT, replaces = fact_001)
    └── Sự thật Lịch sử (Fact: assignee = Nam, status = SUPERSEDED)
```

### Chi tiết cấu trúc 2 tầng:

| Tầng | Tên mô hình | Các trường dữ liệu cốt lõi | Ý nghĩa kinh doanh |
| :--- | :--- | :--- | :--- |
| **Tầng 1 (Cha)** | `Entity` | `id`, `name`, `type`, `aliases`, `description`, `attributes` | Đối tượng trung tâm: Dự án (`project`), Tính năng (`feature`), Nhân sự (`person`), Phòng ban (`team`), Khách hàng (`customer`), Tài liệu (`document`). |
| **Tầng 2 (Con)** | `Fact` | `id`, `entity_id`, `property`, `value`, `status`, `source_snippet`, `replaces`, `asserted_by` | Mệnh đề sự thật gắn với thực thể: hạn chót (`deadline`), người phụ trách (`assignee`), trạng thái (`status`), ngân sách (`budget`), phạm vi (`scope`). |

### 5 Trạng thái vòng đời của một Fact (`FactStatus`):
* `current`: Mệnh đề đang có hiệu lực thi hành cao nhất.
* `proposed`: Đề xuất, ý kiến cá nhân hoặc câu hỏi của nhân viên (chưa được duyệt chính thức).
* `superseded`: Mệnh đề cũ đã bị thay thế bởi một mệnh đề mới hơn.
* `conflicted`: Hai thông tin mâu thuẫn trực tiếp giữa các nguồn.
* `uncertain`: Thông tin phỏng đoán, chưa chắc chắn (*"chắc là", "hình như"*).

---

## 🧠 3. CHI TIẾT 2 BƯỚC BÓC TÁCH (PROMPT & PARSING)

Quá trình bóc tách diễn ra tuần tự qua 2 lời gọi mô hình AI độc lập:

### Nhánh 1: Bóc tách Thực thể (Entity Extraction)
- **Hàm thực thi:** `extract_entities_async()` ([`L583-611`](file:///Users/hoainam/Desktop/HiLark/server/utils/llm_extractor.py#L583-L611))
- **Prompt:** `ENTITY_EXTRACTION_PROMPT` ([`L204-265`](file:///Users/hoainam/Desktop/HiLark/server/utils/llm_extractor.py#L204-L265))
- **Quy tắc đặc thù tiếng Việt:**
  * **Chống nhận diện nhầm từ chỉ thời gian:** Chữ *"Mai"* đứng đầu câu trong tiếng Việt mặc định là ngày mai (*Tomorrow*), không được nhận diện thành nhân sự tên Mai trừ khi có tiền tố như *"chị Mai"*, *"bạn Mai"*.
  * **Chống đưa đại từ vào bí danh (Aliases):** Tuyệt đối cấm đưa các đại từ xưng hô (*"mình", "bên mình", "em", "anh", "tôi", "chúng tôi"*) vào trường bí danh của bất kỳ thực thể nào.
  * **Nhận diện giao việc:** Cụm từ *"giao nguyên lead"* $\rightarrow$ tự động nhận diện nhân sự tên là *"Nguyên"* dù người chat gõ chữ thường.

---

### Nhánh 2: Bóc tách Sự thật (Fact Extraction)
- **Hàm thực thi:** `extract_facts_async()` ([`L889-950`](file:///Users/hoainam/Desktop/HiLark/server/utils/llm_extractor.py#L889-L950))
- **Prompt:** `FACT_EXTRACTION_PROMPT` ([`L271-342`](file:///Users/hoainam/Desktop/HiLark/server/utils/llm_extractor.py#L271-L342))
- **Đầu vào:** Câu chat của người dùng + Danh sách Entities vừa nhận diện + Danh sách Facts đang có hiệu lực (`CURRENT`) của nhóm đó.
- **Quy tắc trích xuất:**
  * **Không trích xuất tin tán gẫu:** Cấm trích xuất các thuộc tính vô nghĩa như *"chat"*, *"message"*, *"urging"*. Chỉ lưu các sự kiện kinh doanh cốt lõi.
  * **Giá trị cô đọng (Max 15 từ):** Giá trị `value` phải ngắn gọn dứt khoát (ví dụ: *"30/10/2026"*, *"Nguyên"*, *"đã nghiệm thu"*); câu văn đầy đủ được đưa vào `source_snippet` làm bằng chứng.
  * **Xác định thông tin thay thế (`replaces`):** Tự động phát hiện xem sự thật mới có ghi đè sự thật cũ nào không (cùng `entity_id` và cùng `property`).

---

## ⚡ 4. CÁC THUẬT TOÁN KỸ THUẬT ĐẶC THÙ

### A. Sinh mã định danh ổn định (Deterministic Stable ID)
* **Hàm:** `generate_stable_entity_id(workspace_id, name)` ([`L64-73`](file:///Users/hoainam/Desktop/HiLark/server/utils/llm_extractor.py#L64-L73))
* **Cơ chế:** Sử dụng thuật toán băm `uuid5` với không gian tên DNS kết hợp `workspace:clean_name`.
* **Ý nghĩa:** Cùng một thực thể (ví dụ: "Dự án Sàn") ở bất kỳ lần chạy nào cũng luôn sinh ra một mã duy nhất `ent_xxxxxxxxxxxx`, tránh sinh ID ngẫu nhiên làm phân mảnh dữ liệu.

---

### B. Chuẩn hóa lịch và giờ Việt Nam (UTC+7)
* **Hàm:** `normalize_time_value(prop, val, reference_dt)` ([`L155-198`](file:///Users/hoainam/Desktop/HiLark/server/utils/llm_extractor.py#L155-L198))
* **Vấn đề thực tế:** Người Việt chat rất đa dạng: *"chiều mai"*, *"ngày 10"*, *"30/10"*, *"tháng 12"*, *"cuối tuần"*.
* **Xử lý thuật toán:**
  1. `30/10` hoặc `ngày 10/10` $\rightarrow$ Tự động ghép năm hiện tại thành `30/10/2026`.
  2. `ngày 10` $\rightarrow$ Ghép tháng và năm hiện tại thành `10/10/2026`.
  3. `tháng 12` $\rightarrow$ Ghép năm hiện tại thành `12/2026`.
  4. Giờ cụ thể (*"15h chiều mai"*) $\rightarrow$ Chuẩn hóa thành `15:00 DD/MM/YYYY`.

---

### C. Cơ chế liên kết thuộc tính (Attribute Coreference Resolution)
* **Tình huống:** Người dùng không gọi tên dự án mà nói: *"Cái dự án bữa anh bảo ngân sách 150 triệu ấy, giờ khách nâng lên 500 triệu rồi nhé"*.
* **Giải pháp:** Hệ thống truyền toàn bộ thuộc tính đã biết (`known_attributes`) của các thực thể hiện có trong workspace vào Prompt. AI đối chiếu thấy dự án "Atlas" đang có thuộc tính `budget = 150 triệu` $\rightarrow$ Tự động gán sự thật 500 triệu này vào đúng thực thể "Atlas" mà không tạo ra dự án rác mang tên "Dự án bữa anh bảo".

---

### D. Khiên bảo vệ thẩm quyền của Sếp (Supersede Shield)
* **Vị trí mã nguồn:** [`server/utils/llm_extractor.py:L726-750`](file:///Users/hoainam/Desktop/HiLark/server/utils/llm_extractor.py#L726-L750)
* **Tình huống thực tế:** Sếp vừa chốt: *"Deadline dự án là ngày 30/10"*. Hôm sau một nhân viên chat vào nhóm: *"Em nghĩ dời sang ngày 15/11 đi anh"*.
* **Nguyên tắc kỹ thuật sống còn:**
  ```python
  if speaker_role == "member" and old_role == "owner":
      # Đề xuất của nhân sự đi ngược quyết định của Sếp:
      # Giữ nguyên trạng thái là PROPOSED (Đề xuất), CẤM ghi đè quyết định của Sếp!
      fact_status = FactStatus.PROPOSED
      replaces_id = None
  ```
* **Kết quả:** Sự thật của Sếp vẫn giữ nguyên trạng thái `[CURRENT]`. Ý kiến của nhân viên chỉ được lưu dưới dạng `[PROPOSED]` (Đề xuất chờ xem xét), đảm bảo tính toàn vẹn và kỷ luật quản trị của hệ thống.

---

## 💾 5. LƯU TRỮ VÀO MONGODB (SINGLE SOURCE OF TRUTH)

Toàn bộ kết quả bóc tách được lưu vào 2 collection chính trong MongoDB qua hàm `save_extraction_to_mongo()`:

```
MongoDB Database (HiLark)
├── Collection: 'entities'
│   └── {_id, id: 'ent_...', name: 'Atlas', type: 'project', aliases: [...], chat_id, project_tag}
└── Collection: 'facts' (hoặc 'claims')
    └── {_id, id: 'fact_...', entity_id: 'ent_...', property: 'deadline', value: '30/10/2026', status: 'current', replaces: 'fact_001', asserted_by: {role: 'owner'}}
```

* **Phân vùng Scope:** Mỗi bản ghi đều được gắn chặt với `chat_id` và `project_tag` để đảm bảo dữ liệu của nhóm này không bị đọc lén bởi nhóm khác.
* **Cập nhật trạng thái tự động:** Khi lưu fact mới có `replaces = fact_001`, hệ thống tự động tìm bản ghi `fact_001` trong MongoDB và cập nhật trường `status = superseded`.

---

## 📋 6. BẢNG TRA CỨU HÀM VÀ PHƯƠNG THỨC CỐT LÕI

| Tên hàm / Phương thức | Kiểu gọi | Đầu vào | Đầu ra | Chức năng chính |
| :--- | :---: | :--- | :--- | :--- |
| `extract_async()` | `async` | `query`, `existing_entities`, `existing_facts` | `dict(entities, facts, superseded_facts)` | Quy trình bóc tách toàn diện 2 nhánh (Entities + Facts). |
| `extract_entities_async()`| `async` | `query`, `existing_entities` | `list[Entity]` | Gọi Gemini bóc tách riêng Nhánh 1 (Thực thể). |
| `extract_facts_async()` | `async` | `query`, `entities`, `existing_facts`, `asserted_by` | `dict(facts, superseded_facts)` | Gọi Gemini bóc tách riêng Nhánh 2 (Sự thật). |
| `find_matching_entity()` | `sync` | `name`, `aliases`, `existing_entities` | `Optional[dict]` | Nhận diện thực thể trùng tên hoặc bí danh. |
| `normalize_time_value()` | `sync` | `property`, `value`, `reference_dt` | `str` | Chuẩn hóa mốc thời gian sang định dạng lịch Việt Nam. |
| `save_extraction_to_mongo()`| `async`| `extraction_result`, `chat_id`, `project_tag` | `dict(total_stored_...)` | Lưu trữ phân vùng dữ liệu an toàn vào MongoDB. |
