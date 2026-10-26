"""
Unified AI Service Module
=========================
Vị trí: server/services/ai_service.py

Gom nhóm toàn bộ các dịch vụ và client trí tuệ nhân tạo (AI Domain):
  - JEV Intent Classifier & Safety Gate (jev_service, JevService, JEVError)
  - Gemini LLM Client (llm_client, LLMClient, GeminiClient)
  - LLM Information Extractor (extract_async)
  - Text Filter & Content Sanitizer (text_filter, TextFilter)
"""

from __future__ import annotations

import httpx

from services.ai.jev_classifier import (
    JEVError,
    JevService,
    jev_service,
)
from services.ai.gemini_client import (
    GeminiClient,
    LLMClient,
    llm_client,
)
from services.ai.llm_extractor import extract_async
from services.ai.text_filter import TextFilter, text_filter

__all__ = [
    "JEVError",
    "JevService",
    "jev_service",
    "GeminiClient",
    "LLMClient",
    "llm_client",
    "extract_async",
    "TextFilter",
    "text_filter",
    "httpx",
]
