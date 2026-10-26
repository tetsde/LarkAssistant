"""
Transitional Facade Shim for LarkBaseService
============================================
Vị trí: server/services/larkbase.py (Deprecated - Vui lòng import từ services.lark.bitable)
"""

from __future__ import annotations

from services.lark.bitable import (  # noqa: F401
    LarkBaseField,
    LarkBaseQueryResult,
    LarkBaseRecord,
    LarkBaseService,
    lark_base_service,
    read_lark_base_records,
)
import services.lark.bitable as _bitable_mod
from services.lark.bitable import *  # noqa: F401, F403

__all__ = [name for name in dir(_bitable_mod) if not name.startswith("_")]
