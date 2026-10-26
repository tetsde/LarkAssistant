"""
Transitional Facade Shim for ContextComposer
============================================
Vị trí: server/utils/context_composer.py (Deprecated - Vui lòng import từ services.knowledge)

Module này re-export toàn bộ interface từ `services.knowledge.context_composer` để bảo đảm 100%
khả năng tương thích ngược cho các file routers, tests và utils hiện hành.
"""

from __future__ import annotations

import services.knowledge.context_composer as _composer_mod
from services.knowledge.context_composer import *  # noqa: F401, F403

__all__ = [name for name in dir(_composer_mod) if not name.startswith("_")]
