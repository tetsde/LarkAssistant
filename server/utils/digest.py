"""
HiLark - Daily Digest Utilities
================================
Vị trí: server/utils/digest.py

Các hàm tiện ích phục vụ xử lý Daily Digest:
  - Sinh deep link tin nhắn Lark (Applink)
  - Chuẩn hóa định dạng thời gian và ngày tháng
  - Hỗ trợ format và bóc tách dữ liệu
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from models.memory import get_vietnam_now, VIETNAM_TZ


def build_lark_message_link(message_id: str) -> str:
    """
    Sinh deep link mở trực tiếp tin nhắn trên ứng dụng Lark (Desktop & Mobile).
    Format: https://applink.larksuite.com/client/message/open?open_message_id=<message_id>
    """
    clean_id = (message_id or "").strip()
    if not clean_id:
        return ""
    return f"https://applink.larksuite.com/client/message/open?open_message_id={clean_id}"


def get_current_digest_date() -> str:
    """Trả về ngày hiện tại theo chuẩn YYYY-MM-DD theo giờ Việt Nam (UTC+7)."""
    return get_vietnam_now().strftime("%Y-%m-%d")


def format_human_timestamp(iso_str: Optional[str] = None) -> str:
    """
    Định dạng timestamp thành chuỗi dễ đọc dạng: 'HH:MM DD/MM/YYYY'.
    Nếu không truyền, lấy thời gian hiện tại.
    """
    if not iso_str:
        return get_vietnam_now().strftime("%H:%M %d/%m/%Y")
    try:
        dt = datetime.fromisoformat(iso_str)
        # Chuyển về múi giờ VN nếu có timezone
        if dt.tzinfo:
            dt = dt.astimezone(VIETNAM_TZ)
        return dt.strftime("%H:%M %d/%m/%Y")
    except Exception:
        return iso_str


def clean_markdown_text(text: str) -> str:
    """Loại bỏ ký tự điều khiển hoặc khoảng trắng thừa trong văn bản Markdown."""
    if not text:
        return ""
    # Chuẩn hóa xuống dòng Windows CRLF và CR về \n
    text = re.sub(r"\r\n|\r", "\n", text)
    # Loại bỏ tab và khoảng trắng liên tiếp trên cùng 1 dòng
    text = re.sub(r"[ \t]+", " ", text)
    # Loại bỏ khoảng trắng thừa quanh dấu xuống dòng
    text = re.sub(r" *\n *", "\n", text)
    # Thu gọn nhiều dòng trống liên tiếp thành tối đa 2 dòng trống
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

