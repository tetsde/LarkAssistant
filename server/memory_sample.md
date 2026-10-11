---
claim_id: "mem-987654321"
asserted_by: "Nguyễn Văn A (Nhân sự)"
asserted_at: "2026-10-09T18:40:00+07:00"
confidence: 0.88
superseded_by: null
---

# Claim (Nội dung ghi nhớ)
"Bản hợp đồng với đối tác ABC đã được chỉnh sửa xong điều khoản thanh toán (chia làm 3 đợt thay vì 2) và đã đẩy lên Google Drive. Chờ sếp rảnh đọc sau."

## JEV Routing Metadata
- **Nhãn JEV gán (Action):** `MEMORY_ONLY`
- **JEV Probability:** `0.88`
- **Trạng thái:** Đã lưu vào CSDL (Knowledge Base). Không làm phiền sếp.

---

### Ghi chú dành cho hệ thống
- File markdown này đóng vai trò như một **Memory Node** trong CSDL đồ thị (hoặc Vector DB).
- Khi có thông tin mới phủ định hoặc thay thế thông tin này (ví dụ nhân sự báo lại là "Thôi đối tác không chịu 3 đợt, quay lại 2 đợt rồi"), hệ thống sẽ tạo một file markdown claim mới, đồng thời update trường `superseded_by` ở file này thành ID của file mới đó.
- WeKnora khi cần lấy thông tin trả lời sẽ đọc phần Frontmatter (phần gạch gạch đầu file) để ưu tiên độ tin cậy và xem thông tin này đã cũ hay chưa (`superseded_by`).
