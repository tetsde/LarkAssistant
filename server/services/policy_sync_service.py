"""
Transitional Facade Shim for PolicySyncService
==============================================
Vị trí: server/services/policy_sync_service.py (Deprecated - Vui lòng import từ services.knowledge)

Module này re-export toàn bộ interface từ `services.knowledge.policy_sync` để bảo đảm 100%
khả năng tương thích ngược cho các file routers, tests và utils hiện hành.
"""

from __future__ import annotations

import services.knowledge.policy_sync as _policy_mod
from services.knowledge.policy_sync import *  # noqa: F401, F403

__all__ = [name for name in dir(_policy_mod) if not name.startswith("_")]
