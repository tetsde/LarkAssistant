"""
Transitional Facade Shim for MemberMessageHandler
=================================================
Vị trí: server/services/bot_handlers/member_message_handler.py (Deprecated - Vui lòng import từ services.lark.handlers.member_message_handler)
"""

from __future__ import annotations

import services.lark.handlers.member_message_handler as _mmh_mod
from services.lark.handlers.member_message_handler import *  # noqa: F401, F403

__all__ = [name for name in dir(_mmh_mod) if not name.startswith("_")]
