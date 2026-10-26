"""
Transitional Facade Shim for WeKnoraService
===========================================
Vị trí: server/services/weknora.py (Deprecated - Vui lòng import từ services.knowledge)

Module này re-export toàn bộ interface từ `services.knowledge.weknora_client` để bảo đảm 100%
khả năng tương thích ngược cho các file routers, tests và utils hiện hành.
"""

from __future__ import annotations

import httpx
from core.config import settings

from services.knowledge.weknora_client import (
    WeKnoraService,
    weknora_service,
)

__all__ = [
    "WeKnoraService",
    "weknora_service",
    "httpx",
    "settings",
]
