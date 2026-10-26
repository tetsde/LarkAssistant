"""
Transitional Facade Shim for DocumentHandler
============================================
Vị trí: server/services/bot_handlers/document_handler.py (Deprecated - Vui lòng import từ services.lark.handlers.document_handler)
"""

from __future__ import annotations

import services.lark.handlers.document_handler as _dh_mod
from services.lark.handlers.document_handler import *  # noqa: F401, F403

__all__ = [name for name in dir(_dh_mod) if not name.startswith("_")]
