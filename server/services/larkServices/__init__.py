"""
HiLark LarkServices Package
============================
Vị trí: server/services/larkServices/__init__.py

Package con quản lý toàn bộ giao tiếp với Lark Open Platform.

Cấu trúc nội bộ:
  - lark_client.py     → Kết nối SDK, User Identity, Token Management
  - lark_dispatcher.py → Parser sự kiện, Dedup Cache, Event Handlers, Handler Registry
  - lark_messenger.py  → Gửi/Reply/Đọc tin nhắn, FastAPI Webhook
  - lark_runner.py     → WebSocket Client, DM Polling, Hybrid Runner

Export ra ngoài (backward compat với toàn bộ codebase):
  from services.larkServices import lark_service, LarkService, LarkMessage, LarkConfig
"""

from models.lark import LarkConfig, LarkMention, LarkMessage, LarkUserProfile
from .lark_client import LarkClientMixin
from .lark_dispatcher import LarkDispatcherMixin
from .lark_messenger import LarkMessengerMixin
from .lark_runner import LarkRunnerMixin
from typing import Optional


class LarkService(
    LarkClientMixin,
    LarkDispatcherMixin,
    LarkMessengerMixin,
    LarkRunnerMixin,
):
    """
    Service quản lý toàn diện kết nối và giao tiếp với Lark Open Platform.

    Kế thừa từ 4 mixin chuyên biệt:
      - LarkClientMixin     → kết nối, user identity, token
      - LarkDispatcherMixin → parser sự kiện, dedup, event handlers
      - LarkMessengerMixin  → gửi/reply/đọc tin nhắn
      - LarkRunnerMixin     → WebSocket, DM Polling, Hybrid Runner
    """

    def __init__(
        self,
        config: Optional[LarkConfig] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        verification_token: Optional[str] = None,
        encrypt_key: Optional[str] = None,
        domain: Optional[str] = None,
        user_access_token: Optional[str] = None,
        user_open_id: Optional[str] = None,
    ):
        # Bước 1: Khởi tạo Lark Client (từ LarkClientMixin)
        self._init_client(
            config=config,
            app_id=app_id,
            app_secret=app_secret,
            verification_token=verification_token,
            encrypt_key=encrypt_key,
            domain=domain,
            user_access_token=user_access_token,
            user_open_id=user_open_id,
        )

        # Bước 2: Khởi tạo Dispatcher (từ LarkDispatcherMixin)
        self._init_dispatcher()


# Singleton instance dùng chung toàn hệ thống
lark_service = LarkService()

__all__ = [
    "LarkConfig",
    "LarkService",
    "lark_service",
    "LarkMessage",
    "LarkMention",
    "LarkUserProfile",
    "LarkClientMixin",
    "LarkDispatcherMixin",
    "LarkMessengerMixin",
    "LarkRunnerMixin",
]
