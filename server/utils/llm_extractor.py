"""
Transitional Facade Shim for LLMExtractor
=========================================
Vị trí: server/utils/llm_extractor.py (Deprecated - Vui lòng import từ services.ai)

Module này re-export toàn bộ interface từ `services.ai.llm_extractor` để bảo đảm 100%
khả năng tương thích ngược cho các file routers, tests và utils hiện hành.
"""

from __future__ import annotations

import services.ai.llm_extractor as _ai_extractor
from services.ai.llm_extractor import *  # noqa: F401, F403

__all__ = [name for name in dir(_ai_extractor) if not name.startswith("_")]
