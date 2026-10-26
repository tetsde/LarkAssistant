"""
Transitional Facade Shim for UnifiedRuleEngine
==============================================
Vị trí: server/utils/rule_engine.py (Deprecated - Vui lòng import từ services.knowledge)

Module này re-export toàn bộ interface từ `services.knowledge.rule_engine` để bảo đảm 100%
khả năng tương thích ngược cho các file routers, tests và utils hiện hành.
"""

from __future__ import annotations

import services.knowledge.rule_engine as _rule_mod
from services.knowledge.rule_engine import *  # noqa: F401, F403

__all__ = [name for name in dir(_rule_mod) if not name.startswith("_")]
