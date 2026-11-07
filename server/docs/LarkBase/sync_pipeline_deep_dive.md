# Đặc tả Kỹ thuật: Luồng đồng bộ dữ liệu Lark Base (Bitable)

Tài liệu này ghi lại chi tiết luồng xử lý kỹ thuật, cấu trúc phân giải ô tính, cơ chế kiểm soát MD5 Hash Guard và quy trình nạp tài liệu sang WeKnora từ bảng tính Lark Base.

Mã nguồn liên quan:
- Dịch vụ Lark Base: [`server/services/lark/bitable.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/bitable.py)
- Khởi tạo Base tự động: [`server/services/lark/base_provision_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/base_provision_service.py)
- Đồng bộ Chat Scopes: [`server/services/knowledge/chat_scopes.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/chat_scopes.py)
- Đồng bộ chính sách Policy: [`server/services/knowledge/policy_sync.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/policy_sync.py)
- Dọn dẹp dữ liệu ô: [`server/services/lark/bitable.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/bitable.py)

---

## 1. Tổng quan luồng đồng bộ dữ liệu

Luồng đồng bộ dữ liệu Lark Base là cầu nối giữa bảng tính quản trị Lark Base với cơ sở dữ liệu MongoDB (`chat_scopes`) và kho tri thức WeKnora:

```
[Quản trị viên thao tác trên Lark Base]      [Thành viên thêm Bot vào nhóm]
(Sửa trạng thái / Nạp file PDF)             (im.chat.member.bot.added_v1)
                 │                                        │
  (Kênh 1: Webhook Base Realtime)          (Kênh 2: Webhook Group Realtime)
                 │                                        │
                 ▼                                        ▼
[handle_bitable_record_changed_event]       [handle_bot_added_to_chat]
                 │                                        │
                 └──────────────────┬─────────────────────┘
                                    │
                                    ▼
                [LarkBaseService: aget_all_records()]
                                    │
                                    ▼
                [sync_group_from_base_record()]
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
       [Bước 1 & 2: Dọn dẹp & Phân tích]    [Bước 3: Tải file & Đẩy WeKnora]
       • cleaner.clean_field_value()        • Tải tệp nhị phân attachment
       • parse_labels(forbidden_labels)     • Kiểm tra MD5 Hash Guard
       • Phân định nhóm confidential        • WeKnora upload & vectorization
                 │                               │
                 └───────────────┬───────────────┘
                                 │
                                 ▼
       [Bước 4: Lưu trữ MongoDB collection 'chat_scopes']
       • Upsert ChatScopeRecord theo {"chat_id": chat_id, "tenant_key": tenant_key}
       • Cung cấp dữ liệu < 1ms cho Lớp 2 & Lớp 3
```

---

## 2. Bảng phân rã các module thực thi

| Thành phần | Đường dẫn file | Vai trò trong luồng Sync | Hàm / Lớp phụ trách |
| :--- | :--- | :--- | :--- |
| **Lark Base Service** | [`server/services/lark/bitable.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/bitable.py) | Giao tiếp với Lark Bitable OpenAPI: đọc bản ghi, tải tệp đính kèm, tạo dòng mới. | `LarkBaseService.aget_all_records()`<br/>`LarkBaseService.adownload_attachment()` |
| **Cấp phát Base tự động** | [`server/services/lark/base_provision_service.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/base_provision_service.py) | Tự động tạo Base, cấu hình bảng Chat Scopes và Policies, nạp dữ liệu mẫu và gán quyền. | `BaseProvisionService.provision_base_for_tenant()` |
| **Đồng bộ Chat Scopes** | [`server/services/knowledge/chat_scopes.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/chat_scopes.py) | Nhận bản ghi thô, phân giải nhãn cấm, nạp tài liệu sang WeKnora và lưu trữ MongoDB. | `sync_group_from_base_record()`<br/>`handle_bitable_record_changed_event()` |
| **Đồng bộ chính sách Policy** | [`server/services/knowledge/policy_sync.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/policy_sync.py) | Quét bảng Policies, tải tài liệu quy định, đối soát MD5 hash và rebuild tri thức chính sách. | `sync_policies()`<br/>`_upload_or_rebuild()` |

---

## 3. Chi tiết kỹ thuật 4 bước thực thi

### Bước 1: Trích xuất và dọn dẹp dữ liệu ô (Cell Value Sanitization)
- **Vị trí mã nguồn:** [`server/services/lark/bitable.py`](file:///Users/hoainam/Desktop/HiLark/server/services/lark/bitable.py)
- **Xử lý dữ liệu phức tạp của Bitable:**
  - Ô rich-text: Bóc tách mảng `[{"text": "Dự án Atlas", "type": "text"}]` thành chuỗi `"Dự án Atlas"`.
  - Ô user mention: Trích xuất tên hiển thị người dùng từ đối tượng mention.
  - Ô đính kèm (Attachment): Trích xuất danh sách tệp đính kèm gồm `file_token`, tên tệp, kích thước và định dạng MIME.

### Bước 2: Phân giải nhãn cấm và trạng thái bảo mật
- **Vị trí mã nguồn:** [`server/services/knowledge/chat_scopes.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/chat_scopes.py)
- **Quy trình:**
  1. Phân giải nhãn cấm: Bóc tách chuỗi ngăn cách tự do (phẩy, chấm phẩy) thành mảng chuỗi chuẩn hóa: `["Ngân sách", "Lương", "Chi phí", "Hợp đồng"]`.
  2. Nhận diện nhóm bảo mật cao: Nếu cột "Mức độ bảo mật" chứa các từ khóa (`tuyệt mật`, `confidential`, `bí mật`), gán `security_level = "confidential"`, tự động tước quyền tự động phát ngôn của bot trong nhóm.

### Bước 3: Tải file đính kèm & MD5 Hash Guard sang WeKnora
- **Vị trí mã nguồn:** [`server/services/knowledge/chat_scopes.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/chat_scopes.py), [`server/services/knowledge/policy_sync.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/policy_sync.py)
- **Kiểm soát MD5 Hash Guard:**
  - Trước khi upload, hệ thống tính toán mã băm MD5 của tài liệu.
  - Đối chiếu với bản ghi hiện hữu trong WeKnora. Nếu MD5 trùng khớp hoàn toàn và không có cờ ép buộc (`force = False`), hệ thống bỏ qua việc nạp lại.
  - Nếu tệp mới hoặc có thay đổi nội dung, hệ thống xóa bản ghi cũ (`delete_knowledge`) và nạp bản mới để WeKnora xây dựng lại chỉ mục từ đầu (tránh trùng lặp vector).

### Bước 4: Lưu trữ MongoDB collection `chat_scopes`
- **Vị trí mã nguồn:** [`server/services/knowledge/chat_scopes.py`](file:///Users/hoainam/Desktop/HiLark/server/services/knowledge/chat_scopes.py)
- **Hoạt động:** Cập nhật bản ghi `ChatScopeRecord` vào MongoDB kèm danh sách `knowledge_ids` vừa nhận từ WeKnora. Dữ liệu này được cung cấp cho Lớp 2 và Lớp 3 với tốc độ truy vấn < 1ms nhờ Compound Index `(tenant_key, chat_id)`.
