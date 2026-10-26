"""
HiLark Platform Integration Domain Package (Lark Integration Domain)
===================================================================
Vị trí: server/services/lark/

Hợp nhất toàn bộ các dịch vụ tương tác với nền tảng Lark:
  - client: LarkClientMixin (OpenAPI SDK, xác thực, download binary resources, docx raw content)
  - dispatcher: LarkDispatcherMixin (Parser sự kiện JSON, Dedup cache, Event handlers)
  - messenger: LarkMessengerMixin (Gửi tin nhắn, reply thread, DM owner, card format)
  - runner: LarkRunnerMixin (WebSocket long connection, background reconnect loop)
  - bitable: LarkBaseService (Bitable OpenAPI SDK, download attachments, base records)
  - bot_runner: BotService (Root Dispatcher, lifecycle startup listeners)
  - handlers: DocumentHandler, OwnerCommandHandler, MemberMessageHandler
"""

from typing import Optional

from models.lark import LarkConfig, LarkMention, LarkMessage, LarkUserProfile
from services.lark.client import LarkClientMixin
from services.lark.dispatcher import LarkDispatcherMixin
from services.lark.messenger import LarkMessengerMixin
from services.lark.runner import LarkRunnerMixin


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


# Singleton instance dùng chung toàn hệ thống (phải khởi tạo trước khi import downstream services)
lark_service = LarkService()

# Downstream services & Handlers (import sau lark_service để tránh circular import)
from services.lark.bitable import (
    LarkBaseService,
    lark_base_service,
    LarkBaseRecord,
    read_lark_base_records,
)
from services.lark.bot_runner import (
    handle_lark_incoming_message,
    start_bot_service,
    stop_bot_service,
    start_digest_scheduler_daemon,
    run_standalone_bot,
)
from services.lark.handlers import (
    handle_document_or_links,
    handle_owner_dm_command,
    handle_member_message,
)

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
    "LarkBaseService",
    "lark_base_service",
    "LarkBaseRecord",
    "read_lark_base_records",
    "handle_lark_incoming_message",
    "start_bot_service",
    "stop_bot_service",
    "start_digest_scheduler_daemon",
    "run_standalone_bot",
    "handle_document_or_links",
    "handle_owner_dm_command",
    "handle_member_message",
]
