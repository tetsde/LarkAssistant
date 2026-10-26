"""
Transitional Facade Shim for Bot Handlers
=========================================
Vị trí: server/services/bot_handlers/__init__.py (Deprecated - Vui lòng import từ services.lark.handlers)
"""

from __future__ import annotations

import services.lark.handlers as _h_mod
from services.lark.handlers import *  # noqa: F401, F403

__all__ = [name for name in dir(_h_mod) if not name.startswith("_")]
