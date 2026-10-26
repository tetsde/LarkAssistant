"""
Transitional Facade Shim for LarkDispatcherMixin
================================================
Vị trí: server/services/larkServices/lark_dispatcher.py (Deprecated - Vui lòng import từ services.lark.dispatcher)
"""

from __future__ import annotations

import services.lark.dispatcher as _disp_mod
from services.lark.dispatcher import *  # noqa: F401, F403

__all__ = [name for name in dir(_disp_mod) if not name.startswith("_")]
