"""
HiLark Lark Service - Backward Compatibility Shim
==================================================
Vị trí: server/services/lark.py

File này CHỈ re-export từ services.larkServices để đảm bảo
toàn bộ codebase hiện tại không cần sửa dòng import nào.

Logic thực sự nằm trong:
  server/services/larkServices/
    ├── __init__.py       → LarkService class + lark_service singleton
    ├── lark_client.py    → Kết nối SDK, User Identity, Token
    ├── lark_dispatcher.py→ Parser sự kiện, Dedup, Event Handlers
    ├── lark_messenger.py → Gửi/Reply/Đọc tin nhắn, Webhook
    └── lark_runner.py    → WebSocket, DM Polling, Hybrid Runner
"""

from services.larkServices import (
    LarkConfig,
    LarkService,
    lark_service,
    LarkMessage,
    LarkMention,
    LarkUserProfile,
)

__all__ = [
    "LarkConfig",
    "LarkService",
    "lark_service",
    "LarkMessage",
    "LarkMention",
    "LarkUserProfile",
]
