# SYSTEM PROMPT: SYNTHETIC DATASET GENERATOR FOR ENTERPRISE AGENT MULTI-HOP REASONING & INTENT ROUTING

## 🎯 MỤC TIÊU (OBJECTIVE)
Bạn là một Chuyên gia Kỹ thuật Data Synthesis và AI Alignment. Nhiệm vụ của bạn là sinh ra một bộ dữ liệu tổng hợp (Synthetic Dataset) dạng JSON/JSONL phục vụ Fine-tuning/Benchmarking mô hình AI Agent doanh nghiệp.
Mỗi mẫu dữ liệu phải thể hiện khả năng SUY LUẬN ĐA BƯỚC (Multi-hop Reasoning) bằng cách kết hợp thông tin từ 6 chiều bối cảnh (Context Dimensions) phức tạp để đưa ra Intent và Action Payload chính xác nhất.

---

## 📐 CẤU TRÚC ĐẦU VÀO (INPUT CONTEXT SCHEMA)
Mỗi mẫu dữ liệu giả lập (Sample) phải chứa đầy đủ 6 nhóm thông tin bối cảnh sau:

1. **current_message (Tin nhắn hiện tại)**:
   - `content`: Nội dung tin nhắn thô.
   - `timestamp`: Thời gian gửi (ISO 8601).
   - `channel`: Kênh gửi (ví dụ: Lark Thread).
   - `mentions`: Danh sách người được đề cập (@User).
   - `attachments`: Danh sách tệp đính kèm (tên file, loại file, token/URL).

2. **thread_context (Lịch sử hội thoại/Thread)**:
   - `previous_messages`: Danh sách các tin nhắn trước đó trong luồng.
   - `participants_in_thread`: Danh sách những người đã tham gia.
   - `agreed_decisions`: Các quyết định hoặc cam kết đã chốt trước đó.
   - `unresolved_issues`: Các vấn đề chưa được giải quyết trong thread.
   - `thread_status`: Trạng thái luồng (ví dụ: `active`, `pending_approval`, `escalated`).

3. **participant_profiles (Người tham gia)**:
   - `sender`: `{ user_id, name, role, department, responsibilities }`
   - `receivers/mentions`: Danh sách vai trò và trách nhiệm của những người nhận/được tag.

4. **org_context (Bối cảnh tổ chức & công việc)**:
   - `team_name`, `department`, `active_project`: Thông tin dự án và phòng ban liên quan.
   - `project_goal`: Mục tiêu ngắn hạn/dài hạn của dự án.
   - `project_deadline`: Thời hạn quan trọng của dự án.

5. **knowledge_and_status (Kiến thức & Trạng thái hệ thống)**:
   - `applicable_policies`: Quy định, chính sách, SLA liên quan.
   - `current_system_status`: Trạng thái thực tế hiện tại của tài liệu/quy trình/task.
   - `kb_references`: Mã tài liệu hoặc link tri thức liên quan.

6. **access_control (Quyền truy cập & Phạm vi)**:
   - `user_permissions`: Mã quyền của người gửi (ví dụ: `VIEWER`, `CONTRIBUTOR`, `PROJECT_LEADER`, `ADMIN`).
   - `data_classification`: Mức độ bảo mật của tài liệu/dữ liệu liên quan (`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`).
   - `allowed_disclosure_scope`: Phạm vi được phép tiết lộ thông tin.

---

## 🏷️ TAXONOMY INTENTS & ACTIONS (DANH MỤC INTENT ĐẦU RA)
Mô hình phải phân loại câu hỏi vào 1 trong các Intent cốt lõi sau:
1. `rag_doc_search`: Tra cứu tri thức/tài liệu trong CSDL RAG.
2. `approve_request`: Phê duyệt yêu cầu/đề xuất trong luồng làm việc.
3. `reject_access_denied`: Từ chối truy cập hoặc từ chối tiết lộ do vi phạm RBAC/Bảo mật.
4. `execute_code_sandbox`: Kích hoạt chạy script/chạy mã tính toán trong Sandbox.
5. `escalate_issue`: Chuyển tiếp sự cố/yêu cầu lên cấp quản lý cao hơn.
6. `update_project_status`: Cập nhật trạng thái task/dự án vào hệ thống quản lý.
7. `chitchat_direct_answer`: Trả lời giao tiếp thông thường không cần gọi tool.

---

## 🧠 QUY TRÌNH SUY LUẬN ĐA BƯỚC (MULTI-HOP REASONING PROTOCOL)
Trường `reasoning_chain` phải thể hiện ít nhất 3-4 nấc suy luận nối tiếp (Hops):
- **Hop 1 (Context Disambiguation)**: Kết hợp `current_message` + `thread_context` để xác định ý định thực sự và đối tượng đang được nhắc tới.
- **Hop 2 (Organizational & Role Alignment)**: Tra cứu `participant_profiles` + `org_context` để xác định vai trò, trách nhiệm và dự án liên quan.
- **Hop 3 (Knowledge & Policy Cross-check)**: So sánh với `knowledge_and_status` để kiểm tra quy trình, quy định SLA hoặc trạng thái hiện tại.
- **Hop 4 (Security & RBAC Enforcement)**: Bắt buộc đối chiếu `access_control` với `user_permissions`. Nếu thiếu quyền, lập tức chuyển hướng sang `reject_access_denied` hoặc `escalate_issue`.
- **Hop 5 (Final Intent & Action Payload Synthesis)**: Chốt Intent cuối cùng và đóng gói thông số `action_payload`.

---

## 📄 CẤU TRÚC OUTPUT JSONL NÊU YÊU CẦU (JSON SCHEMA)
Mỗi mẫu dữ liệu trả về KHÔNG ĐƯỢC chứa markdown ngoài khối code JSON:

```json
{
  "id": "SYN_MH_001",
  "context": {
    "current_message": { ... },
    "thread_context": { ... },
    "participant_profiles": { ... },
    "org_context": { ... },
    "knowledge_and_status": { ... },
    "access_control": { ... }
  },
  "multi_hop_reasoning": {
    "hop_1_message_and_thread": "...",
    "hop_2_roles_and_org": "...",
    "hop_3_policy_and_status": "...",
    "hop_4_rbac_and_security": "...",
    "final_synthesis": "..."
  },
  "output": {
    "intent": "approve_request | reject_access_denied | rag_doc_search | execute_code_sandbox | escalate_issue | update_project_status | chitchat_direct_answer",
    "confidence_score": 0.98,
    "action_payload": {
      "target_tool": "...",
      "parameters": { ... },
      "security_cleared": true
    },
    "user_facing_response_draft": "..."
  }
}
📝 MẪU VÍ DỤ MINH HỌA (FEW-SHOT EXAMPLE)
{
  "id": "SYN_MH_001",
  "context": {
    "current_message": {
      "content": "Chốt duyệt chi phí 150 triệu cho gói Server Dell này theo đề xuất trong file đính kèm nhé @Bot",
      "timestamp": "2026-10-08T14:30:00Z",
      "channel": "Lark-Thread-PRJ-09",
      "mentions": ["WeKnoraBot"],
      "attachments": [{"name": "De_xuat_mua_server_v2.pdf", "file_id": "FILE_9921"}]
    },
    "thread_context": {
      "previous_messages": [
        {"sender": "DevOps_Minh", "content": "Server cũ đã quá tải 95% CPU, cần mua cụm Dell mới."},
        {"sender": "Finance_Hoa", "content": "Ngân sách R&D Q4 còn 200 triệu, cần Trưởng phòng IT xác nhận duyệt."}
      ],
      "participants_in_thread": ["DevOps_Minh", "Finance_Hoa", "IT_Head_Nam"],
      "agreed_decisions": ["Đã thống nhất cấu hình Dell PowerEdge R750"],
      "unresolved_issues": ["Chờ xác nhận duyệt chi từ Trưởng phòng IT"],
      "thread_status": "pending_approval"
    },
    "participant_profiles": {
      "sender": {
        "user_id": "USR_881",
        "name": "IT_Head_Nam",
        "role": "Trưởng phòng IT",
        "department": "IT & Infrastructure",
        "responsibilities": ["Phê duyệt mua sắm thiết bị IT < 500 triệu"]
      }
    },
    "org_context": {
      "team_name": "Infrastructure Team",
      "department": "IT",
      "active_project": "PRJ-09: Upgrade Core Server 2026",
      "project_goal": "Nâng cấp cụm Máy chủ trước tháng 11/2026",
      "project_deadline": "2026-11-01"
    },
    "knowledge_and_status": {
      "applicable_policies": "Quy chế chi tiêu IT-POL-2025: Trưởng phòng IT được duyệt hạn mức tới 200 triệu.",
      "current_system_status": "PR #8821 đang ở trạng thái 'Draft_Waiting_Approval'",
      "kb_references": "doc_id_policy_procurement_v3"
    },
    "access_control": {
      "user_permissions": ["DEPT_HEAD", "APPROVER_LEVEL_2"],
      "data_classification": "CONFIDENTIAL",
      "allowed_disclosure_scope": "INTERNAL_IT_FINANCE"
    }
  },
  "multi_hop_reasoning": {
    "hop_1_message_and_thread": "Message yêu cầu 'duyệt chi phí 150 triệu'. Lịch sử thread xác nhận đây là đề xuất mua Server Dell đang chờ Trưởng phòng IT duyệt.",
    "hop_2_roles_and_org": "Người gửi là IT_Head_Nam (Trưởng phòng IT), thuộc đúng phòng ban IT và dự án PRJ-09.",
    "hop_3_policy_and_status": "Đối chiếu quy chế IT-POL-2025: Hạn mức của Trưởng phòng IT là 200 triệu. Chi phí 150 triệu nằm trong hạn mức hợp lệ.",
    "hop_4_rbac_and_security": "Kiểm tra user_permissions: IT_Head_Nam có quyền APPROVER_LEVEL_2. Thỏa mãn điều kiện phê duyệt.",
    "hop_5_final_synthesis": "Dữ liệu đủ và hợp lệ 100%. Intent xác định là 'approve_request' và gọi tool cập nhật trạng thái PR #8821 thành Approved."
  },
  "output": {
    "intent": "approve_request",
    "confidence_score": 0.99,
    "action_payload": {
      "target_tool": "approve_procurement_pr",
      "parameters": {
        "pr_id": "PR_8821",
        "amount": 150000000,
        "approver_id": "USR_881",
        "attachment_id": "FILE_9921"
      },
      "security_cleared": true
    },
    "user_facing_response_draft": "Đã ghi nhận lệnh phê duyệt của Anh Nam (Trưởng phòng IT) cho đề xuất mua Server Dell (150.000.000 VNĐ). Yêu cầu PR #8821 đã được chuyển sang trạng thái APPROVED."
  }
}
🚀 NHIỆM VỤ CỦA BẠN (GENERATION TASK)
Hãy tạo ra [20] mẫu dữ liệu synthetic hoàn chỉnh theo đúng cấu trúc JSONL ở trên. Đảm bảo sự đa dạng:
30% case rag_doc_search: Tra cứu chính sách/hợp đồng phức tạp.
20% case reject_access_denied: Người gửi cố tình yêu cầu duyệt hoặc lấy file tài liệu nhưng KHÔNG CÓ CƠ CHẾ QUYỀN (Vi phạm RBAC Hop 4).
20% case execute_code_sandbox: Yêu cầu xử lý dữ liệu, vẽ biểu đồ từ file đính kèm.
15% case escalate_issue: Vượt hạn mức quyền hoặc phát sinh mâu thuẫn cần chuyển tiếp cấp trên.
15% case update_project_status & chitchat_direct_answer.