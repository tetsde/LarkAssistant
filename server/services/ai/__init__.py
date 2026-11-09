"""
HiLark AI Domain Package
========================
Vị trí: server/services/ai/

Chứa toàn bộ các mô hình và động cơ trí tuệ nhân tạo:
  - jev_classifier: System 1 Intent Classifier (phân loại ý định, lọc tin rác, kiểm tra câu hỏi cấm).
  - llm_client: Unified Multi-Provider LLM Client (gọi LLM dạng text, JSON hoặc multimodal).
  - llm_extractor: Bóc tách thực thể (Entities) và mệnh đề sự thật (Facts / Claims) từ ngữ cảnh.
"""

from services.ai.jev_classifier import JEVError, JevService, jev_service
from services.ai.llm_client import LLMClient, llm_client
from services.ai.ai_config_manager import AIConfigManager, ai_config_manager
from services.ai.llm_extractor import (
    extract,
    extract_async,
    extract_claims,
    extract_entities,
    extract_facts,
    apply_and_save_extraction,
)
from services.ai.text_filter import TextFilter, text_filter

__all__ = [
    "JEVError",
    "JevService",
    "jev_service",
    "LLMClient",
    "llm_client",
    "AIConfigManager",
    "ai_config_manager",
    "extract",
    "extract_async",
    "extract_claims",
    "extract_entities",
    "extract_facts",
    "apply_and_save_extraction",
    "TextFilter",
    "text_filter",
]
