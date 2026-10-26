"""
Transitional Facade Shim for LarkTokenService
=============================================
Vị trí: server/services/token_service.py (Deprecated - Vui lòng import từ services.auth)

Module này re-export toàn bộ interface từ `services.auth.token_service` để bảo đảm 100%
khả năng tương thích ngược cho các file routers, tests và utils hiện hành.
"""

from __future__ import annotations

import httpx
from database.db import get_auth_collection

from services.auth.token_service import (
    PRIMARY_TOKEN_DOC_ID,
    VIETNAM_TZ,
    format_remaining_seconds,
    LarkTokenService,
    token_service,
    start_token_refresh_loop,
)

__all__ = [
    "PRIMARY_TOKEN_DOC_ID",
    "VIETNAM_TZ",
    "format_remaining_seconds",
    "LarkTokenService",
    "token_service",
    "start_token_refresh_loop",
    "httpx",
    "get_auth_collection",
]
