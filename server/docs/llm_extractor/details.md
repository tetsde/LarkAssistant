# Chi Tiết Sử dụng LLM: Với 2 Luồng Bóc Tách Dữ Liệu 2 Nhánh

Hệ thống chia việc đọc hiểu tin nhắn thành **2 nhánh chạy nối tiếp nhau**:
1. **Nhánh 1 (Tìm Chủ thể / Thực thể)**: Xác định câu chat đang nói về ai hoặc cái gì (dự án, con người, khách hàng...).
2. **Nhánh 2 (Tìm Thông tin chi tiết)**: Xác định chủ thể đó có thêm thông tin gì mới (ngân sách, hạn chót, người làm...) và gắn chặt vào chủ thể đó.

---

## NHÁNH 1: BÓC TÁCH THỰC THỂ (CHỦ THỂ)

### 1. Mục đích
Xác định chính xác **chủ thể** trong câu chat để làm "điểm tựa". Mọi thông tin sau này đều phải gắn vào một chủ thể cụ thể, không được để thông tin trôi nổi.

### 2. Dữ liệu đầu vào
- `query`: Nội dung câu chat của người dùng.
- `workspace_id`: Mã nhóm hoặc mã công ty.
- `existing_entities`: Danh sách các chủ thể đã lưu trong cơ sở dữ liệu trước đó.
- `existing_facts`: Các thông tin đang có hiệu lực của những chủ thể này.

### 3. Tiền xử lý (Kỹ thuật chống tạo trùng lặp)
Trước khi gửi câu chat cho AI, hệ thống tự động gom các thông tin đã biết (`known_attributes`) của các chủ thể cũ vào ngữ cảnh.

**Ví dụ thực tế:**
- Trong cơ sở dữ liệu đã có dự án **Atlas**, kèm thông tin ngân sách là `150 triệu`.
- Người dùng chat: *"Dự án bữa anh nói 150tr bây giờ khách hàng tăng lên 300tr nhé"*.
- **Cách AI xử lý**: Nhờ nhìn thấy mốc `150 triệu` trong danh sách đã biết, AI nhận ra ngay *"Dự án bữa anh nói 150tr"* chính là dự án **Atlas**.
- **Kết quả**: Hệ thống dùng lại đúng dự án Atlas, **không tạo thêm dự án mới gây rác dữ liệu**.

### 4. Kết quả đầu ra của Nhánh 1
Trả về danh sách chủ thể kèm theo một **mã định danh (`id`)** để làm chìa khóa nối sang Nhánh 2:

```json
[
  {
    "id": "ent_atlas_123",
    "name": "Atlas",
    "type": "project",
    "aliases": [
      "Dự án Atlas",
      "Dự án bữa anh nói 150tr"
    ]
  }
]
```

---

## NHÁNH 2: BÓC TÁCH THÔNG TIN CHI TIẾT (SỰ THẬT)

### 1. Mục đích
- Gắn các thông tin cụ thể (ngân sách, hạn chót, người phụ trách, trạng thái...) vào đúng mã `id` của chủ thể tìm được ở Nhánh 1.
- **Quy tắc bắt buộc**: Mọi thông tin sinh ra phải có mã chủ thể (`entity_id`). Tuyệt đối không lưu thông tin mồ côi (không rõ của ai).
- Tự động phát hiện thông tin mới đè lên thông tin cũ để cập nhật và lưu vết lịch sử.

### 2. Dữ liệu đầu vào
- `query`: Nội dung câu chat.
- `entities`: Danh sách chủ thể nhận từ Nhánh 1 (chứa `id: "ent_atlas_123"`).
- `existing_facts`: Thông tin cũ đang có hiệu lực của chủ thể đó (ngân sách cũ: 150 triệu).
- `source_message_id`: Mã tin nhắn chat (để biết thông tin này xuất phát từ tin nhắn nào).
- `sender`: Tên người nhắn tin.
- `reference_time_vn`: Giờ hiện tại tại Việt Nam (để quy đổi các từ như "ngày mai", "cuối tuần" thành ngày tháng cụ thể).

### 3. Quá trình xử lý
1. AI đọc câu chat kết hợp với danh sách chủ thể và thông tin cũ.
2. AI nhận biết: Có số tiền mới là `300 triệu`, thuộc về chủ thể `ent_atlas_123`, và số tiền này thay thế cho số tiền cũ `150 triệu`.
3. Hệ thống tạo mã cho thông tin mới, đồng thời đổi trạng thái của thông tin cũ thành **hết hiệu lực / bị thay thế** (`superseded`).

---

## VÍ DỤ TỔNG HỢP TOÀN BỘ LUỒNG

### Đầu vào:
- **Câu chat**: *"Dự án Atlas tăng ngân sách lên 300 triệu nhé"*
- **Người gửi**: Hoài Nam
- **Dữ liệu cũ trong hệ thống**: Dự án `Atlas` (`ent_atlas_123`) đang có ngân sách là `150 triệu` (`fact_001`).

### Kết quả sau khi chạy xong cả 2 nhánh:

```json
{
  "entities": [
    {
      "id": "ent_atlas_123",
      "name": "Atlas",
      "type": "project"
    }
  ],
  "facts": [
    {
      "id": "fact_002",
      "entity_id": "ent_atlas_123",
      "property": "budget",
      "value": "300 triệu",
      "status": "current",
      "replaces": "fact_001"
    }
  ],
  "superseded_facts": [
    {
      "id": "fact_001",
      "entity_id": "ent_atlas_123",
      "property": "budget",
      "value": "150 triệu",
      "status": "superseded"
    }
  ]
}
```

---

## Ý NGHĨA THỰC TẾ
1. **Trả lời chính xác**: Khi hỏi *"Dự án Atlas ngân sách bao nhiêu?"*, trợ lý ảo chỉ đọc dòng có trạng thái `current` và trả lời ngay: **300 triệu**.
2. **Không mất lịch sử**: Thông tin cũ `150 triệu` không bị xóa mất mà được gắn nhãn `superseded`. Khi cần tra lại lịch sử thay đổi ngân sách, hệ thống vẫn có đầy đủ bằng chứng.
3. **Dữ liệu gọn gàng**: Không bao giờ xảy ra tình trạng tạo trùng lặp dự án hay lưu thông tin không rõ của ai.


S