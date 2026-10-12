"""
HiLark - Lark Models
====================
Vị trí: server/models/lark.py

Chứa các cấu trúc dữ liệu cho Lark IM: tin nhắn (LarkMessage), profile, mention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LarkMention:
    """Đại diện cho thông tin người/bot được mention trong tin nhắn."""
    key: str
    name: str
    id: str = ""


@dataclass
class LarkUserProfile:
    """Hồ sơ thông tin người dùng từ Lark."""
    name: str = ""
    open_id: str = ""
    union_id: str = ""
    avatar_url: str = ""
    email: str = ""
    mobile: str = ""
    tenant_key: str = ""


@dataclass
class LarkMessage:
    """Đại diện cho 1 tin nhắn nhận được từ Lark IM."""
    message_id: str
    chat_id: str
    chat_type: str  # "p2p" (1-1) hoặc "group" (nhóm)
    sender_id: str  # open_id / user_id
    sender_type: str  # "user" hoặc "app"
    message_type: str  # "text", "post", "image", "file", ...
    text: str  # Nội dung văn bản thuần đã làm sạch
    raw_content: str  # JSON content gốc từ Lark
    create_time: int
    is_bot: bool = False
    is_self: bool = False  # True nếu tin nhắn được gửi từ chính user hiện tại
    root_id: Optional[str] = None
    parent_id: Optional[str] = None
    mentions: List[Dict[str, Any]] = field(default_factory=list)
    raw_event: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "chat_id": self.chat_id,
            "chat_type": self.chat_type,
            "sender_id": self.sender_id,
            "sender_type": self.sender_type,
            "message_type": self.message_type,
            "text": self.text,
            "create_time": self.create_time,
            "is_bot": self.is_bot,
            "is_self": self.is_self,
            "root_id": self.root_id,
            "parent_id": self.parent_id,
        }
