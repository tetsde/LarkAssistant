*Nhánh 1: Bóc tách thực thể, entity extraction*
1. Mục đích:
Xác định đoạn chat/câu chat đang nói về cái gì. Và để xếp vào đúng claims đang có trong claims store

2 Dữ liệu đầu vào
query: nội dung chat
workspace_id: mã nhóm
existing_entites: các thực thể đã lưu trong mongoDB trước đó
existing_facts: các thông tin đang có hiệu lực của thực thể đó

3. Trước khi gửi cho LLM
Python trích xuất thuộc tính trước khi đưa cho LLM xử lí:
Ví dụ LLM trước đó đã phân tích câu chat: Dự án atlas có budget 150tr
=> Trong mongoDB lưu các property như 150tr | atlas | budget
=> hệ thống quét xem có property nào đã có trong mongoDB không rồi mới đưa vào LLM xử lí

Ví dụ với prompt:
Bạn bóc tách thực thể ra giúp tôi với câu chat :"dự án này tăng budget từ 150tr => 300tr nhé"
Hiện tại tại trong  các thực thể đã biết bao gồm:[
  {
    "id": "ent_a1b2c3d4e5f6",
    "name": "Atlas",
    "type": "project",
    "aliases": [
      "Dự án Atlas"
    ],
    "known_attributes": {
      "budget": "150 triệu"
    }
  }
=> LLM có thể suy luận ra 150tr là của dự án atlas chứ không phải một dự án khác

output của entity sẽ đính kèm 1 cái id để liên kết với nhánh 2
Ví dụ :
{
  "entities": [
    {
      "entity_id": "ent_atlas_123",  <-- ID để nhánh 2 biết đây làAtlas
      "name": "Atlas",
      "type": "project",
      "confidence": 0.95,
      "aliases": [
        "Dự án Atlas",
        "Atlas Project"
      ]
    }
  ],
  "new_attributes": [
    {
      "attribute_name": "budget",
      "values": [
        "300 triệu"
      ],
      "confidence": 0.92,
      "source_entity_id": "ent_atlas_123"  <-- Liên kết ngược lại Entity
    }
  ]
}
Tránh việc nó tạo ra một thực thể mới => dẫn đến rác thông tin


Nhánh 2: Đã xác định được thông tin đó thuộc đối tượng gì
Nhánh 2 sẽ xếp thông tin đó vào đúng fact/claims của nó, tránh việc xếp nhần lẫm claims
 Dữ liệu đầu vào (Input của hàm 

extract_facts
)
query: Nội dung tin nhắn người dùng.

entities: Toàn bộ các Entity (kết quả vừa nhận diện từ Nhánh 1 + các Entity cũ có sẵn trong MongoDB).

existing_facts: Danh sách các Fact đang có hiệu lực (status == "current") của các Entity đó(nếu có)

source_message_id: Mã tin nhắn từ Lark (để truy vết tin nhắn gốc).

sender: Tên/ID người gửi tin nhắn.

reference_time_vn: Giờ hệ thống tại Việt Nam (GMT+7) tại thời điểm nhận tin.

4. Sau khi nhánh 2 xử lý xong
Thì sinh ra một claims mới về thông tin (nếu có) và cập nhật lại entity cũ

Ví dụ với prompt:
Đầu vào:
{
  "query": "Dự án Atlas tăng budget lên 300 triệu nhé",
  "entities": [
    {
      "entity_id": "ent_atlas_123",
      "name": "Atlas",
      "type": "project",
      "confidence": 0.95
    }
  ],
  "existing_facts": [
    {
      "fact_id": "fact_atlas_budget_v1",
      "statement": "Dự án Atlas có ngân sách 150 triệu",
      "current_value": "150 triệu",
      "entity_id": "ent_atlas_123"
    }
  ],
  "source_message_id": "msg_lark_456",
  "sender": "John Doe"
}
output:
{
  "entities": [
    {
      "entity_id": "ent_atlas_123",
      "name": "Atlas",
      "type": "project",
      "status": "current",
      "known_attributes": {
        "budget": "300 triệu"
      }
    }
  ],
  "facts": [
    {
      "fact_id": "fact_atlas_budget_v2",
      "statement": "Dự án Atlas có ngân sách 300 triệu",
      "entity_id": "ent_atlas_123",
      "source_message_id": "msg_lark_456",
      "status": "current",
      "confidence": 0.93
    }
  ],
  "expired_facts": [
    {
      "fact_id": "fact_atlas_budget_v1",
      "statement": "Dự án Atlas có ngân sách 150 triệu",
      "entity_id": "ent_atlas_123",
      "source_message_id": "msg_lark_abc",
      "status": "expired"
    }
  ]
}
