"""
Transitional Facade Shim for LarkTokenVerifier
==============================================
Vị trí: server/utils/lark_token.py (Deprecated - Vui lòng import từ services.auth)

Module này re-export toàn bộ interface từ `services.auth.token_verifier` để bảo đảm 100%
khả năng tương thích ngược cho các file routers, tests và utils hiện hành.
"""

from __future__ import annotations

import services.auth.token_verifier as _auth_verifier
from services.auth.token_verifier import *  # noqa: F401, F403

__all__ = [name for name in dir(_auth_verifier) if not name.startswith("_")]
