"""
Transitional Facade Shim for JevService
=======================================
Vị trí: server/services/jev.py (Deprecated - Vui lòng import từ services.ai)

Module này re-export toàn bộ interface từ `services.ai.jev_classifier` để bảo đảm 100%
khả năng tương thích ngược cho các file routers, tests và utils hiện hành.
"""

from __future__ import annotations

import httpx

from services.ai.jev_classifier import (
    JEVError,
    JevService,
    jev_service,
)

__all__ = [
    "JEVError",
    "JevService",
    "jev_service",
    "httpx",
]
