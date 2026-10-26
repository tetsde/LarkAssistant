"""
Transitional Facade Shim for DocReaderService
=============================================
Vị trí: server/services/docreader_service.py (Deprecated - Vui lòng import từ services.knowledge)

Module này re-export toàn bộ interface từ `services.knowledge.docreader_client` để bảo đảm 100%
khả năng tương thích ngược cho các file routers, tests và utils hiện hành.
"""

from __future__ import annotations

import services.knowledge.docreader_client as _docreader_mod
from services.knowledge.docreader_client import *  # noqa: F401, F403

__all__ = [name for name in dir(_docreader_mod) if not name.startswith("_")]
