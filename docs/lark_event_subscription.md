# Lark Event Subscription Checklist

`docs/lark_scope_import.json` chỉ import permission scopes. Events phải cấu hình riêng tại **Events & Callbacks**.

## Cách nhanh nhất cho local: Long Connection/WebSocket

Code HiLark đã khởi động `lark_oapi.ws.Client` trong `bot_runner.py`, nên khi test local hãy chọn **Receive events through persistent connection / Long connection** trong Lark Console. Cách này không cần ngrok và không cần Request URL public cho message events. Lark hỗ trợ cả persistent connection và webhook; tài liệu hướng dẫn event subscription mô tả hai chế độ này. [Lark event subscription](https://open.larksuite.com/document/home/develop-a-bot-in-5-minutes/step-5-configure-event-subscription)

Sau đó chỉ cần bật tối thiểu `im.message.receive_v1`, restart container để WebSocket reconnect, rồi nhắn vào Bot.

## Callback URLs (chỉ dùng khi chọn Webhook)

- Event subscription: `POST https://<hilark-domain>/api/lark/events`
- Interactive card action callback: `POST https://<hilark-domain>/api/lark/card-action`

Nếu chọn Webhook, dùng `/api/lark/events`; endpoint này đã xử lý URL verification, message events, lifecycle events và card action payload.

## Events HiLark đang xử lý

### Bắt buộc cho bot chat

- `im.message.receive_v1` — nhận tin nhắn trong nhóm/DM.
- `im.chat.member.bot.added_v1` — biết Bot được thêm vào nhóm.
- `im.chat.member.bot.deleted_v1` — biết Bot bị gỡ khỏi nhóm.

### Bắt buộc cho workflow và dữ liệu

- `im.message.recalled_v1` — đồng bộ tin nhắn bị thu hồi.
- `im.message.reaction.created_v1` — xử lý reaction nếu workflow sử dụng.
- `drive.file.bitable_record_changed_v1` — đồng bộ bản ghi Lark Base.
- `drive.file.bitable_field_changed_v1` — đồng bộ thay đổi field Lark Base.
- `drive.file.edit_v1` — nhận thay đổi file/drive liên quan Base.
- `card.action.trigger` — callback khi Admin bấm nút trên interactive card.

### Lifecycle tenant

- `app_status_change`
- `app_uninstalled`
- `open_app`

### Chỉ dành cho Store/ISV App

- `app_ticket` — chỉ cấu hình khi App đã chạy ISV/Marketplace mode; Custom App không cần event này.

Sau khi cấu hình, dùng **Send test event**/URL verification trong Lark Console và kiểm tra HTTP `200` từ HiLark trước khi test OAuth hoặc nhắn tin.
