"""
HiLark AI Domain Package
========================
Vị trí: server/services/ai/

Chứa toàn bộ các mô hình và động cơ trí tuệ nhân tạo:
  - jev_classifier: System 1 Intent Classifier (phân loại ý định, lọc tin rác, kiểm tra câu hỏi cấm).
  - gemini_client: Unified Google Gemini API Client (gọi LLM dạng text hoặc JSON).
  - llm_extractor: Bóc tách thực thể (Entities) và mệnh đề sự thật (Facts / Claims) từ ngữ cảnh.
"""

from services.ai.jev_classifier import JEVError, JevService, jev_service
from services.ai.gemini_client import GeminiClient, LLMClient, llm_client
from services.ai.llm_extractor import (
    extract,
    extract_async,
    extract_claims,
    extract_entities,
    extract_facts,
    apply_and_save_extraction,
)
from services.ai.text_filter import TextFilter, text_filter
from services.ai.draft_rewriter import rewrite_draft_with_llm

__all__ = [
    "JEVError",
    "JevService",
    "jev_service",
    "GeminiClient",
    "LLMClient",
    "llm_client",
    "extract",
    "extract_async",
    "extract_claims",
    "extract_entities",
    "extract_facts",
    "apply_and_save_extraction",
    "TextFilter",
    "text_filter",
    "rewrite_draft_with_llm",
]
