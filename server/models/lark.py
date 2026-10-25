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
class LarkConfig:
    """
    Cấu hình kết nối và xác thực với Lark Open Platform:
      - app_id, app_secret: Thông tin ứng dụng Bot
      - verification_token, encrypt_key: Xác thực Webhook / Event Subscription
      - domain: Domain endpoint của Lark (mặc định Open Platform)
      - user_access_token: Token danh nghĩa người dùng (User Access Token)
    """
    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""
    encrypt_key: str = ""
    domain: str = ""
    user_access_token: str = ""
    user_open_id: str = ""

    @classmethod
    def from_settings(cls) -> LarkConfig:
        """Khởi tạo LarkConfig tự động đọc từ core.config.settings."""
        try:
            from core.config import settings
            return cls(
                app_id=settings.LARK_APP_ID or "",
                app_secret=settings.LARK_APP_SECRET or "",
                verification_token=settings.LARK_VERIFICATION_TOKEN or "",
                encrypt_key=settings.LARK_ENCRYPT_KEY or "",
                domain=settings.LARK_DOMAIN or "",
                user_access_token=settings.LARK_USER_ACCESS_TOKEN or "",
                user_open_id=settings.LARK_USER_OPEN_ID or "",
            )
        except Exception:
            return cls()



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

    @property
    def file_key(self) -> Optional[str]:
        """Trích xuất file_key từ raw_content nếu tin nhắn là file."""
        if self.message_type == "file" and self.raw_content:
            try:
                import json
                data = json.loads(self.raw_content)
                if isinstance(data, dict):
                    return data.get("file_key")
            except Exception:
                pass
        return None

    @property
    def file_name(self) -> Optional[str]:
        """Trích xuất tên file từ raw_content nếu tin nhắn là file."""
        if self.message_type == "file" and self.raw_content:
            try:
                import json
                data = json.loads(self.raw_content)
                if isinstance(data, dict):
                    return data.get("file_name")
            except Exception:
                pass
        return None

    @property
    def image_key(self) -> Optional[str]:
        """Trích xuất image_key từ raw_content nếu tin nhắn là image."""
        if self.message_type == "image" and self.raw_content:
            try:
                import json
                data = json.loads(self.raw_content)
                if isinstance(data, dict):
                    return data.get("image_key")
            except Exception:
                pass
        return None

