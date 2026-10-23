# Repository Agent Instructions

## Mục tiêu

Thay đổi code có căn cứ, giữ ngữ cảnh giữa các phiên, và lưu lại lý do của các quyết định kỹ thuật có ảnh hưởng đáng kể. Ưu tiên tính đúng đắn, đơn giản, khả năng kiểm chứng và phạm vi thay đổi nhỏ.

## Trước khi làm việc

1. Đọc hướng dẫn gần nhất áp dụng cho thư mục đang sửa; nếu có `AGENTS.md` lồng bên dưới, tuân thủ cả file đó.
2. Kiểm tra `git status` trước khi sửa. Không ghi đè hoặc xóa thay đổi chưa commit của người dùng.
3. Đọc `docs/project-memory/PROJECT_CONTEXT.md`, `HANDOFF.md` và `DECISIONS.md` nếu tồn tại; chỉ đọc thêm tài liệu liên quan trực tiếp đến task.
4. Kiểm tra code hiện tại, test và lịch sử Git trước khi kết luận về kiến trúc hoặc nguyên nhân lỗi.
5. Nếu skill `project-memory` có sẵn, hãy dùng workflow trong `.agents/skills/project-memory/SKILL.md`.

## Quy tắc khi sửa code

- Xác định vấn đề, phạm vi, tiêu chí chấp nhận và các ràng buộc trước khi triển khai.
- Ưu tiên thay đổi nhỏ nhất giải quyết đúng vấn đề; tránh abstraction, dependency hoặc refactor ngoài phạm vi khi chưa có lý do.
- Không đoán API, schema, hành vi thư viện hoặc cấu hình. Kiểm tra nguồn có sẵn hoặc đánh dấu điều chưa chắc chắn.
- Không tự ý đổi hợp đồng API, schema dữ liệu, quyền truy cập, cơ chế xác thực, dependency hoặc kiến trúc có ảnh hưởng lớn. Nêu tác động và hỏi người dùng khi lựa chọn chưa rõ.
- Không sửa/xóa thay đổi có sẵn của người dùng nếu chưa hiểu mục đích.
- Không đưa secrets, token, private key hoặc dữ liệu cá nhân vào code, log, docs hay Git.
- Với lỗi, tìm nguyên nhân gốc; không chỉ che triệu chứng.
- Nếu ba lần thử có mục tiêu và phạm vi rõ ràng vẫn thất bại, dừng vòng lặp, tóm tắt bằng chứng và xem lại giả thuyết thay vì lặp lại cùng một cách làm.

## Kiểm thử và bằng chứng

- Chạy các kiểm tra phù hợp với thay đổi và ghi lại lệnh cùng kết quả thực tế.
- Phân biệt rõ: test đã viết, test đã chạy, test pass, test fail và test chưa chạy.
- Không nói “đã pass”, “đã xác minh” hoặc “đã deploy” nếu không có bằng chứng thực tế.
- Nếu không thể chạy test, nêu lý do và kiểm tra thay thế đã thực hiện.
- Với thay đổi liên quan bảo mật, phân quyền, dữ liệu hoặc đồng thời, xem xét cả trường hợp bị từ chối, lỗi, ranh giới và race condition.

## Quản lý ngữ cảnh

- `PROJECT_CONTEXT.md`: thông tin nền tương đối ổn định và kiến trúc hiện tại đã được xác minh.
- `HANDOFF.md`: trạng thái công việc hiện tại, thay đổi đang dở, blocker và bước tiếp theo cụ thể.
- `DECISIONS.md`: chỉ mục ngắn gọn các quyết định quan trọng; hồ sơ đầy đủ có thể nằm trong Notion.
- Git: bằng chứng thay đổi code và lịch sử commit.
- Notion Decision Log: lý do, phương án đã cân nhắc, trade-off, rủi ro, xác minh và lịch sử thay thế quyết định.

Không chép toàn bộ nội dung vào nhiều nơi. Ghi nguồn liên kết rõ ràng; không bịa ID Notion, URL, commit hash, test result hoặc lịch sử.

## Khi nào cần ghi quyết định?

Ghi nhận quyết định khi nó ảnh hưởng đáng kể tới kiến trúc, bảo mật/phân quyền, dữ liệu, API/contract, hiệu năng, độ tin cậy, dependency, triển khai hoặc chi phí vận hành. Với thay đổi nhỏ, dễ đảo ngược và không ảnh hưởng dài hạn, ghi chú ngắn hoặc không cần tạo hồ sơ riêng.

Khi có Notion MCP:
1. Tìm database Decision Log hiện có.
2. Đọc schema và các lựa chọn property thực tế trước khi ghi.
3. Tìm quyết định trùng lặp trước khi tạo mới.
4. Dùng đúng tên property và option trong database; xác minh lại sau khi ghi.
5. Không tạo database thay thế nếu database hiện có đã đáp ứng mục tiêu.
6. Không ghi nội dung suy đoán như sự thật; đánh dấu rõ `Assumption` hoặc `Unknown`.

Không có MCP hoặc không đủ quyền thì chuẩn bị bản ghi ở local, báo rõ việc đồng bộ Notion chưa thực hiện.

## Khi kết thúc task

- Cập nhật `PROJECT_CONTEXT.md` chỉ khi kiến trúc/thông tin nền thực sự thay đổi.
- Cập nhật `HANDOFF.md` nếu còn việc dở hoặc có phiên tiếp theo cần tiếp tục.
- Thêm/cập nhật mục trong `DECISIONS.md` và Notion nếu có quyết định đáng ghi nhận.
- Nêu tóm tắt thay đổi, file chính, test đã chạy và kết quả, rủi ro còn lại, cùng bước tiếp theo.
