"""
HiLark AI Draft Rewriter
========================
Vị trí: server/services/ai/draft_rewriter.py

Mục đích:
    Sử dụng mô hình ngôn ngữ lớn (Gemini) để viết lại bản nháp câu trả lời
    dựa trên chỉ đạo trực tiếp của Lãnh đạo (Executive Rewrite Directive).

Nguyên tắc biên soạn:
    - Thuần tiếng Việt, thân thiện, rõ ràng, lịch sự.
    - Tuyệt đối không sử dụng biểu tượng cảm xúc (icon/emoji).
    - Không sử dụng từ sáo rỗng hoặc thuật ngữ không cần thiết.
    - Xuất văn bản thuần, không dùng định dạng in đậm hay trích dẫn rườm rà.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from services.ai.gemini_client import llm_client

logger = logging.getLogger("hilark.ai.draft_rewriter")

# Bộ lọc loại bỏ ký tự emoji nếu mô hình vô tình sinh ra
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Misc Symbols and Pictographs
    "\U0001F680-\U0001F6FF"  # Transport and Map
    "\U0001F700-\U0001F77F"  # Alchemical
    "\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
    "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
    "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
    "\U0001FA00-\U0001FA6F"  # Chess Symbols
    "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
    "\U00002702-\U000027B0"  # Dingbats
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)


def _clean_rewritten_text(text: str) -> str:
    """Làm sạch câu trả lời sau khi AI sinh ra."""
    if not text:
        return ""

    cleaned = text.strip()

    # Bỏ dấu ngoặc kép bọc quanh toàn văn bản nếu có
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (
        cleaned.startswith("'") and cleaned.endswith("'")
    ):
        cleaned = cleaned[1:-1].strip()

    # Bỏ các tiền tố thừa thường thấy
    prefixes_to_strip = [
        "bản nháp mới:",
        "câu trả lời:",
        "nội dung chỉnh sửa:",
        "gợi ý trả lời:",
        "trả lời:",
    ]
    lower_c = cleaned.lower()
    for p in prefixes_to_strip:
        if lower_c.startswith(p):
            cleaned = cleaned[len(p) :].strip()
            break

    # Loại bỏ biểu tượng cảm xúc (emoji/icon)
    cleaned = _EMOJI_PATTERN.sub("", cleaned).strip()

    # Loại bỏ định dạng in đậm không cần thiết
    cleaned = cleaned.replace("**", "")

    # Chuẩn hóa khoảng trắng dư thừa
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned


REWRITE_SYSTEM_PROMPT = """Bạn là trợ lý điều hành của Lãnh đạo ({responder_name}), hỗ trợ viết câu trả lời để gửi vào nhóm làm việc trên Lark.

BỐI CẢNH HIỆN TẠI:
- Thành viên hỏi: {user_name}
- Câu hỏi ban đầu của thành viên: "{query}"
- Bản nháp đề xuất trước đó: "{original_draft}"
- Chỉ đạo trực tiếp của Lãnh đạo: "{boss_instruction}"
{project_context_section}

NHIỆM VỤ:
Viết lại câu trả lời phản hồi cho thành viên ({user_name}) hoàn toàn dựa trên chỉ đạo của Lãnh đạo.

QUY TẮC BẮT BUỘC:
1. Tuân thủ tuyệt đối chỉ đạo của Lãnh đạo:
   - Nếu Lãnh đạo muốn rút ngắn: Viết súc tích, ngắn gọn trong 1 đến 2 câu.
   - Nếu Lãnh đạo muốn từ chối khéo: Sử dụng lời lẽ lịch sự, nhã nhặn, giải thích hợp lý theo chỉ đạo.
   - Nếu Lãnh đạo điều chỉnh số liệu, mốc thời gian hoặc phân công: Cập nhật chính xác thông tin mới đó.
   - Nếu Lãnh đạo yêu cầu liên hệ người khác: Hướng dẫn thành viên liên hệ đúng người được chỉ đạo.
2. Ngôn ngữ và phong cách:
   - Thuần tiếng Việt, xưng hô thân thiện, lịch sự, đúng chuẩn mực văn hóa doanh nghiệp.
   - TUYỆT ĐỐI KHÔNG sử dụng biểu tượng cảm xúc (icon hoặc emoji).
   - TUYỆT ĐỐI KHÔNG dùng từ sáo rỗng hoặc từ ngữ khoa trương.
   - Định dạng văn bản thuần, không dùng in đậm (**), không dùng dấu trích dẫn (>).
3. Định dạng đầu ra:
   - CHỈ trả về duy nhất nội dung câu trả lời hoàn chỉnh.
   - KHÔNG thêm bất kỳ lời chào đầu, lời giải thích hay tiền tố nào như "Bản nháp:", "Đây là câu trả lời:".
"""


async def rewrite_draft_with_llm(
    original_draft: str,
    query: str,
    boss_instruction: str,
    project_context: Optional[str] = None,
    user_name: Optional[str] = None,
    responder_name: Optional[str] = None,
) -> str:
    """
    Gọi mô hình ngôn ngữ để viết lại bản nháp câu trả lời theo chỉ đạo của Lãnh đạo.

    Args:
        original_draft: Bản nháp hiện tại đang chờ duyệt.
        query: Câu hỏi ban đầu của thành viên.
        boss_instruction: Chỉ đạo bằng lời của Lãnh đạo (ví dụ: "từ chối khéo", "rút ngắn 1 câu").
        project_context: Bối cảnh dự án hoặc thông tin tài liệu bổ trợ (nếu có).
        user_name: Tên của thành viên hỏi.
        responder_name: Danh tính của Lãnh đạo trả lời.

    Returns:
        Nội dung câu trả lời mới đã được viết lại sạch sẽ.
    """
    clean_user = user_name.strip() if user_name else "em"
    clean_responder = responder_name.strip() if responder_name else "anh"

    ctx_sec = ""
    if project_context and project_context.strip():
        ctx_sec = f"\nTHÔNG TIN BỔ TRỢ TỪ TÀI LIỆU DỰ ÁN:\n{project_context.strip()[:1500]}\n"

    prompt = REWRITE_SYSTEM_PROMPT.format(
        responder_name=clean_responder,
        user_name=clean_user,
        query=query.strip(),
        original_draft=original_draft.strip(),
        boss_instruction=boss_instruction.strip(),
        project_context_section=ctx_sec,
    )

    try:
        raw_output = await llm_client.generate_text_async(
            prompt=prompt,
            temperature=0.3,
            max_output_tokens=1024,
        )
        cleaned_output = _clean_rewritten_text(raw_output)
        if not cleaned_output:
            logger.warning("[DRAFT REWRITER] Kết quả viết lại rỗng, giữ lại bản nháp ban đầu.")
            return original_draft

        logger.info(f"[DRAFT REWRITER] Đã viết lại bản nháp theo chỉ đạo: \"{boss_instruction[:50]}\"")
        return cleaned_output
    except Exception as e:
        logger.error(f"[DRAFT REWRITER] Lỗi khi gọi mô hình viết lại nháp: {e}", exc_info=True)
        # Nếu gặp lỗi gọi mô hình, không làm sập tiến trình, trả về bản nháp cũ
        return original_draft
