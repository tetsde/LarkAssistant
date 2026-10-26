"""
Transitional Facade Shim for LarkMessengerMixin
===============================================
Vị trí: server/services/larkServices/lark_messenger.py (Deprecated - Vui lòng import từ services.lark.messenger)
"""

from __future__ import annotations

import services.lark.messenger as _msg_mod
from services.lark.messenger import *  # noqa: F401, F403

__all__ = [name for name in dir(_msg_mod) if not name.startswith("_")]
