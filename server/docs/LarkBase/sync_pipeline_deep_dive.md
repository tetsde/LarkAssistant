# 📘 SPEC KỸ THUẬT: LUỒNG ĐỒNG BỘ DỮ LIỆU LARK BASE (BITABLE SYNC)
> **HiLark Server** — Bản đặc tả kỹ thuật chi tiết (Spec), đối chiếu mã nguồn thực tế, ưu tiên tiếng Việt, không dùng từ ngữ bóng bẩy.

---

## 🧭 1. TỔNG QUAN LUỒNG ĐỒNG BỘ DỮ LIỆU

Luồng đồng bộ dữ liệu Lark Base là cầu nối giữa **Bảng tính quản trị Lark Base** với **Cơ sở dữ liệu MongoDB `chat_scopes`** và **Kho tri thức WeKnora RAG**:

```
[Sếp thao tác trên Lark Base]              [Thành viên Add Bot vào nhóm]
(Sửa trạng thái / Nạp file PDF)           (im.chat.member.bot.added_v1)
                 │                                      │
  (Kênh 1: Webhook Base Realtime)        (Kênh 2: Webhook Group Realtime)
                 │                                      │
                 ▼                                      ▼
[scope_service.py: bitable_changed]     [lark_dispatcher.py: bot_added]
                 │                                      │
                 └──────────────────┬───────────────────┘
                                    │
                                    ▼
                 [larkbase.py: create_record() / aget_all_records()]
                                    │
                                    ▼
                 [scope_service.py: sync_group_from_base_record()]
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
       [Bước 1 & 2: Dọn dẹp & Phân tích]    [Bước 3: Tải file & Đẩy WeKnora]
       • cleaner.clean_field_value()        • adownload_attachment(file_token)
       • parse_labels(forbidden_labels)     • weknora_service.upload_file()
       • Nhận diện nhóm Tuyệt mật           • Nhận về 'knowledge_id'
                 │                               │
                 └───────────────┬───────────────┘
                                 │
                                 ▼
       [Bước 4: Lưu trữ MongoDB collection 'chat_scopes']
       • Upsert ChatScopeRecord theo {"chat_id": chat_id}
       • Cung cấp dữ liệu siêu tốc (< 1ms) cho Layer 2 & Layer 3
```

---

## 🧩 2. BẢNG PHÂN RÃ CÁC MODULE THỰC THI

| Module | Đường dẫn file | Vai trò trong luồng Sync | Lớp / Hàm phụ trách |
| :--- | :--- | :--- | :--- |
| **Driver kết nối Lark Bitable** | [`server/services/larkbase.py`](file:///Users/hoainam/Desktop/HiLark/server/services/larkbase.py) | Giao tiếp với Open API của Lark: đọc records, tải file đính kèm, tạo dòng mới, đăng ký webhook. | `LarkBaseService.aget_all_records()`<br/>`LarkBaseService.adownload_attachment()`<br/>`LarkBaseService.sync_bot_chats()` |
| **Động cơ điều phối đồng bộ** | [`server/services/scope_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/scope_service.py) | Nhận bản ghi thô, phân giải nhãn cấm, tải nạp tài liệu sang WeKnora và lưu trữ vào MongoDB. | `ScopeService.sync_group_from_base_record()`<br/>`ScopeService.handle_bitable_record_changed_event()` |
| **Bộ dọn dẹp cell values** | [`server/utils/larkbase/cleaner.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/larkbase/cleaner.py) | Bóc tách cấu trúc JSON phức tạp của Bitable (mảng text, user mentions, options, attachments) thành kiểu Python sạch. | `clean_field_value()`<br/>`clean_record_fields()` |
| **Quản trị Token JWT** | [`server/utils/larkbase/token.py`](file:///Users/hoainam/Desktop/HiLark/server/utils/larkbase/token.py) | Giải mã payload JWT của App Token và Bitable Token, kiểm tra thời gian hết hạn. | `decode_jwt_token_payload()`<br/>`inspect_bitable_token()` |
| **Mô hình dữ liệu** | [`server/models/larkbase.py`](file:///Users/hoainam/Desktop/HiLark/server/models/larkbase.py)<br/>[`server/models/scope.py`](file:///Users/hoainam/Desktop/HiLark/server/models/scope.py) | Định nghĩa ánh xạ kiểu dữ liệu trường Bitable (`BITABLE_FIELD_TYPE_MAP`) và cấu trúc lưu trữ `ChatScopeRecord`. | `LarkBaseRecord`<br/>`ChatScopeRecord` |

---

## 🔬 3. CHI TIẾT KỸ THUẬT 4 BƯỚC THỰC THI (CODE-LEVEL)

Hàm cốt lõi điều hành luồng đồng bộ là `sync_group_from_base_record(record: LarkBaseRecord)` tại [`server/services/scope_service.py:L226-396`](file:///Users/hoainam/Desktop/HiLark/server/services/scope_service.py#L226-L396):

### Bước 1: Trích xuất & Dọn dẹp dữ liệu ô (Cell Value Sanitization)
- **Vị trí mã nguồn:** [`server/utils/larkbase/cleaner.py:L15-85`](file:///Users/hoainam/Desktop/HiLark/server/utils/larkbase/cleaner.py#L15-L85)
- **Vấn đề thực tế:** Dữ liệu trả về từ Lark Bitable API không phải là chuỗi văn bản đơn thuần, mà là các đối tượng lồng nhau phức tạp:
  * Ô văn bản rich-text: `[{"text": "Dự án Sàn", "type": "text"}]` $\rightarrow$ Cần gộp thành `"Dự án Sàn"`.
  * Ô User mention: `[{"id": "ou_xxx", "name": "Nguyên", "en_name": "Nguyen"}]` $\rightarrow$ Cần lấy `"Nguyên"`.
  * Ô Đính kèm (Attachment): `[{"file_token": "boxcn...", "name": "spec.pdf", "size": 1024, "type": "application/pdf"}]`.
- **Cơ chế bóc tách:**
  ```python
  clean_fields = clean_record_fields(record.fields)
  chat_id = _extract_text_field(clean_fields.get("ID Group") or clean_fields.get("chat_id"))
  chat_name = _extract_text_field(clean_fields.get("Dự án / Nhóm") or clean_fields.get("project_name"))
  ```

---

### Bước 2: Phân giải Nhãn cấm & Trạng thái Bảo mật (Policy Resolution)
- **Vị trí mã nguồn:** [`server/services/scope_service.py:L285-305`](file:///Users/hoainam/Desktop/HiLark/server/services/scope_service.py#L285-L305)
- **1. Phân giải danh sách nhãn cấm:**
  * Sếp có thể gõ nhãn cấm tự do: *"Ngân sách, Bảng lương; Chi phí; Hợp đồng"*.
  * Hàm `parse_labels(raw_labels)` tự động bóc tách thành danh sách chuẩn: `["Ngân sách", "Bảng lương", "Chi phí", "Hợp đồng"]`.
- **2. Nhận diện nhóm Tuyệt mật (Confidential Group):**
  * Quét chuỗi trong cột "Mức độ bảo mật":
  * Nếu phát hiện các từ khóa: *"tuyệt mật"*, *"bí mật"*, *"confidential"*, *"nghiêm ngặt"*:
    ```python
    if any(k in sec_raw for k in ["tuyệt mật", "tuyet mat", "confidential", "bí mật", "nghiêm ngặt"]):
        security_level = "confidential"
    ```
  * **Hậu quả an ninh:** Toàn bộ câu hỏi trong nhóm này sẽ bị khóa tính năng tự động trả lời (Auto-reply), bắt buộc 100% phải chuyển sang luồng soạn nháp để Sếp duyệt trước khi gửi.

---

### Bước 3: Tải file đính kèm & Tự động nạp sang WeKnora RAG
- **Vị trí mã nguồn:** [`server/services/scope_service.py:L310-360`](file:///Users/hoainam/Desktop/HiLark/server/services/scope_service.py#L310-L360)
- **Cơ chế chống tải lại file cũ (Cache Deduplication):**
  * Trước khi tải, hệ thống đọc danh sách file hiện có của nhóm trong MongoDB:
  * Tạo bảng tra cứu `existing_doc_map = {file_token: knowledge_id}`.
  * Nếu `file_token` đã có trong map $\rightarrow$ Giữ nguyên `knowledge_id`, **không tốn băng thông tải lại**!
- **Quy trình nạp file mới sang WeKnora:**
  1. **Tải file nhị phân:**
     ```python
     file_bytes = await lark_base_service.adownload_attachment(file_token, use_tenant_token=True)
     ```
     Gọi API Lark Drive `/open-apis/drive/v1/medias/{file_token}/download` tải file PDF/Word về máy chủ.
  2. **Đẩy sang WeKnora Knowledge Base:**
     ```python
     upload_res = await weknora_service.upload_file(
         file_name=file_name,
         file_bytes=file_bytes,
         dataset_id=effective_dataset_id,
         mime_type=mime_type,
     )
     knowledge_id = upload_res.get("knowledge_id", "")
     ```
  3. WeKnora tự động bóc tách văn bản, cắt đoạn (chunking), tạo vector embeddings và đưa vào cơ sở dữ liệu vector.
  4. Hệ thống ghi nhận `knowledge_id` này vào danh sách tri thức được phép truy xuất của nhóm.

---

### Bước 4: Lưu trữ và Cập nhật trạng thái vào MongoDB (Atomic Upsert)
- **Vị trí mã nguồn:** [`server/services/scope_service.py:L361-396`](file:///Users/hoainam/Desktop/HiLark/server/services/scope_service.py#L361-L396)
- **Đóng gói đối tượng `ChatScopeRecord`:**
  * `chat_id`: Khóa chính định danh nhóm chat.
  * `project_tag`: Nhãn dự án phân vùng Claims (bảo toàn bằng `effective_project_tag = raw_project_tag or (existing_scope.project_tag if existing_scope else None)` để không bị ghi đè thành `None` khi cập nhật).
  * `status`: Trạng thái hoạt động (`active`, `paused`, `inactive`).
  * `security_level`: `standard` hoặc `confidential`.
  * `forbidden_labels`: Danh sách nhãn cấm đã chuẩn hóa.
  * `knowledge_ids`: Danh sách các mã tài liệu WeKnora được phép truy xuất.
  * `documents`: Chi tiết các file đính kèm (tên, kích thước, token, knowledge_id).
  * `updated_by`: Đóng dấu nguồn `"larkbase_sync"`.
- **Thực thi Upsert an toàn vào MongoDB:**
  ```python
  await coll.update_one(
      {"chat_id": chat_id},
      {"$set": scope_rec.to_dict()},
      upsert=True,
  )
  ```
- **Ý nghĩa kiến trúc:** Khi người dùng nhắn tin, Layer 2 chỉ cần đọc thẳng từ MongoDB `chat_scopes` với tốc độ siêu nhanh (**< 1ms**), hoàn toàn không bị nghẽn mạng hay phụ thuộc vào thời gian phản hồi của Lark API.

---

## ⚡ 4. CƠ CHẾ TỰ ĐỘNG PHÁT HIỆN & ĐỒNG BỘ 2 CHIỀU (BIDIRECTIONAL DISCOVERY)

Không chỉ đồng bộ từ Base về Server, HiLark còn có cơ chế **tự động phát hiện và đồng bộ ngược lên Lark Base**:

### Khi Bot được thêm vào nhóm chat mới trên Lark:
1. Lark gửi sự kiện webhook `im.chat.member.bot.added_v1` về hệ thống.
2. `lark_dispatcher.py` bắt sự kiện và kiểm tra:
   ```python
   base_record = lark_base_service.find_record_by_chat_id(chat_id)
   if not base_record:
       # Nhóm chat chưa tồn tại trên bảng Lark Base:
       # BOT TỰ ĐỘNG TẠO DÒNG MỚI TRÊN LARK BASE!
       lark_base_service.create_record({
           "ID Group": chat_id,
           "Dự án / Nhóm": chat_name or "Nhóm mới",
           "Trạng thái": "Hoạt động",
           "Mức độ bảo mật": "Tiêu chuẩn",
       })
   ```
3. **Kết quả:** Sếp chỉ cần add bot vào nhóm chat Lark, dòng thông tin của nhóm đó **tự động xuất hiện trên bảng tính Lark Base** để Sếp bắt đầu kéo thả tài liệu và đặt nhãn cấm mà không cần copy paste ID thủ công!

---

## 🛡️ 5. CƠ CHẾ CHỊU LỖI & PHỤC HỒI (FAULT TOLERANCE)

1. **Xử lý Token hết hạn (Dual Token Failover):**
   * Nếu `user_access_token` của Sếp bị hết hạn: Hệ thống tự động chuyển sang dùng `tenant_access_token` của Bot (`use_tenant_token=True`) để duy trì việc đọc bảng Base và tải file mà không bị gián đoạn.
2. **Xử lý File lỗi hoặc rớt mạng:**
   * Nếu một file PDF bị hỏng hoặc WeKnora từ chối tải: Lỗi được bắt cục bộ (`try...except`), ghi log chi tiết và tiếp tục xử lý các file còn lại trong danh sách, không làm sập toàn bộ luồng đồng bộ của nhóm.
3. **Khắc phục rớt gói tin bằng Webhook Retry & Bootstrap Sync:**
   * **Webhook Retry:** Lark Open Platform tự động gửi lại sự kiện theo hàm mũ nếu server chưa phản hồi mã HTTP 200 trong vòng 3 giây.
   * **One-off Bootstrap Sync:** Mỗi khi khởi động server (`bot_service.py:L500-517`), hệ thống tự động chạy `sync_bot_chats()` và `sync_all_groups_from_base()` để bù đắp bất kỳ dữ liệu nào bị thiếu trong thời gian server offline, đảm bảo tính toàn vẹn 100% mà không cần duy trì polling 30s liên tục.
