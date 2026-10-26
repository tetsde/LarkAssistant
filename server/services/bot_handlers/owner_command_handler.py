"""
Transitional Facade Shim for OwnerCommandHandler
================================================
Vị trí: server/services/bot_handlers/owner_command_handler.py (Deprecated - Vui lòng import từ services.lark.handlers.owner_command_handler)
"""

from __future__ import annotations

import services.lark.handlers.owner_command_handler as _och_mod
from services.lark.handlers.owner_command_handler import *  # noqa: F401, F403

__all__ = [name for name in dir(_och_mod) if not name.startswith("_")]
