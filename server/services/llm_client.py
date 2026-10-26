"""
Transitional Facade Shim for LLMClient
======================================
Vị trí: server/services/llm_client.py (Deprecated - Vui lòng import từ services.ai)

Module này re-export toàn bộ interface từ `services.ai.gemini_client` để bảo đảm 100%
khả năng tương thích ngược cho các file routers, tests và utils hiện hành.
"""

from __future__ import annotations

from services.ai.gemini_client import (
    GeminiClient,
    LLMClient,
    llm_client,
)

__all__ = [
    "GeminiClient",
    "LLMClient",
    "llm_client",
]
