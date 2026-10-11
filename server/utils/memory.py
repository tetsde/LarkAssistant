import os
import uuid
from datetime import datetime, timezone

# Lưu files vào thư mục memory_db ở cùng cấp với utils
MEMORY_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory_db")

def save_memory(query: str, action: str, confidence: float, sender: str = "Client (User)") -> str:
    """
    Tạo một file markdown lưu trữ thông tin cần ghi nhớ, trả về claim_id
    """
    if not os.path.exists(MEMORY_DB_DIR):
        os.makedirs(MEMORY_DB_DIR)
        
    claim_id = f"mem-{uuid.uuid4().hex[:8]}"
    asserted_at = datetime.now(timezone.utc).isoformat()
    
    file_content = f"""---
claim_id: "{claim_id}"
asserted_by: "{sender}"
asserted_at: "{asserted_at}"
confidence: {confidence}
superseded_by: null
---

# Claim (Nội dung ghi nhớ)
"{query}"

## JEV Routing Metadata
- **Nhãn JEV gán (Action):** `{action}`
- **JEV Probability:** `{confidence}`
- **Trạng thái:** Đã lưu vào CSDL (Knowledge Base).

---

### Ghi chú dành cho hệ thống
- File markdown này đóng vai trò như một **Memory Node** trong CSDL đồ thị (hoặc Vector DB).
- Khi có thông tin mới phủ định hoặc thay thế thông tin này, hệ thống sẽ tạo một file markdown claim mới, đồng thời update trường `superseded_by` ở file này thành ID của file mới đó.
"""
    
    file_path = os.path.join(MEMORY_DB_DIR, f"{claim_id}.md")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(file_content)
        
    return claim_id
