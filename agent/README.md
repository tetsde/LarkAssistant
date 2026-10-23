# Project Memory Starter

Bộ khung để coding agent giữ ngữ cảnh dự án, bàn giao giữa các phiên và ghi lại quyết định kỹ thuật.

## Có gì trong bộ này?

- `AGENTS.md`: quy tắc làm việc ở cấp repo.
- `.agents/skills/project-memory/SKILL.md`: workflow cho skill-aware coding agent.
- `docs/project-memory/PROJECT_CONTEXT.md`: kiến trúc và thông tin nền của dự án.
- `docs/project-memory/HANDOFF.md`: trạng thái phiên làm việc và bước tiếp theo.
- `docs/project-memory/DECISIONS.md`: chỉ mục quyết định, liên kết tới Notion.
- `.agents/skills/project-memory/references/`: mẫu quyết định và bộ câu hỏi phản biện.

## Cách dùng

1. Giải nén vào **root repo dự án**.
2. Nếu repo đã có `AGENTS.md`, hãy gộp các quy tắc cần thiết vào file hiện có, đừng ghi đè mù quáng.
3. Mở `docs/project-memory/PROJECT_CONTEXT.md`, điền thông tin dự án thật. Không để agent coi nội dung mẫu là sự thật.
4. Mở `docs/project-memory/HANDOFF.md` và ghi trạng thái ban đầu; có thể để trống nếu chưa có việc đang làm.
5. Mở coding agent và yêu cầu:  
   `Đọc AGENTS.md và skill project-memory. Khảo sát repo, điền PROJECT_CONTEXT.md bằng bằng chứng từ code/docs. Không tự bịa dữ liệu. Chỉ ghi HANDOFF.md nếu xác định được task hiện tại.`
6. Khi dùng Notion MCP, yêu cầu agent tìm database decision log đang có, đọc schema thật rồi mới tạo/cập nhật bản ghi. Không tạo database mới nếu đã có database tương đương.

## Lưu ý

- Đây là bộ khung trung lập, chưa được cài đặt hoặc kiểm thử trong một coding agent cụ thể.
- Thư mục `.agents/skills/` được một số công cụ hỗ trợ; quy ước phát hiện skill khác nhau theo agent. Nếu agent không tự nhận diện skill, đặt `SKILL.md` vào vị trí skill mà công cụ đó quy định hoặc yêu cầu agent đọc trực tiếp.
- Các file context là mẫu ban đầu. Không commit thông tin bí mật, token, khóa API hoặc dữ liệu nhạy cảm vào Git.
