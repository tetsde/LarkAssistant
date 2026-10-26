"""
Transitional Facade Shim for LarkClientMixin
============================================
Vị trí: server/services/larkServices/lark_client.py (Deprecated - Vui lòng import từ services.lark.client)
"""

from __future__ import annotations

import services.lark.client as _client_mod
from services.lark.client import *  # noqa: F401, F403

__all__ = [name for name in dir(_client_mod) if not name.startswith("_")]
