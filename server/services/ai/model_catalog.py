"""
HiLark - AI Model Catalog (Single Source of Truth)
==================================================
Vị trí: server/services/ai/model_catalog.py

Nguồn chân lý duy nhất cho model mặc định theo nhà cung cấp và danh mục
Google Gemini (từ 2.5 đến 3.8 + alias gemini-flash-latest) hiển thị trên UI.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from models.llm import LLMModelOption

DEFAULT_GEMINI_MODEL = "gemini-flash-latest"

DEFAULT_MODEL_BY_PROVIDER: Dict[str, str] = {
    "google": DEFAULT_GEMINI_MODEL,
    "openai": "gpt-4o-mini",
    "chatgpt": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-20241022",
    "custom": "gpt-3.5-turbo",
}

GEMINI_MODEL_SPECS: List[LLMModelOption] = [
    LLMModelOption(
        id="gemini-flash-latest",
        label="Gemini Flash Latest (Mặc định)",
        family="latest",
        tier="recommended",
        is_default=True,
    ),
    LLMModelOption(
        id="gemini-3.8-flash",
        label="Gemini 3.8 Flash",
        family="3.8",
        tier="latest",
        is_default=False,
    ),
    LLMModelOption(
        id="gemini-3.6-flash",
        label="Gemini 3.6 Flash",
        family="3.6",
        tier="standard",
        is_default=False,
    ),
    LLMModelOption(
        id="gemini-3.5-flash",
        label="Gemini 3.5 Flash",
        family="3.5",
        tier="standard",
        is_default=False,
    ),
    LLMModelOption(
        id="gemini-3.5-flash-lite",
        label="Gemini 3.5 Flash-Lite",
        family="3.5",
        tier="lite",
        is_default=False,
    ),
    LLMModelOption(
        id="gemini-3.1-pro-preview",
        label="Gemini 3.1 Pro Preview",
        family="3.1",
        tier="pro",
        is_default=False,
    ),
    LLMModelOption(
        id="gemini-3.1-flash-lite",
        label="Gemini 3.1 Flash-Lite",
        family="3.1",
        tier="lite",
        is_default=False,
    ),
    LLMModelOption(
        id="gemini-3-flash",
        label="Gemini 3 Flash",
        family="3.0",
        tier="standard",
        is_default=False,
    ),
    LLMModelOption(
        id="gemini-3-pro-preview",
        label="Gemini 3 Pro Preview",
        family="3.0",
        tier="pro",
        is_default=False,
    ),
    LLMModelOption(
        id="gemini-2.5-pro",
        label="Gemini 2.5 Pro",
        family="2.5",
        tier="pro",
        is_default=False,
    ),
    LLMModelOption(
        id="gemini-2.5-flash",
        label="Gemini 2.5 Flash",
        family="2.5",
        tier="standard",
        is_default=False,
    ),
    LLMModelOption(
        id="gemini-2.5-flash-lite",
        label="Gemini 2.5 Flash-Lite",
        family="2.5",
        tier="lite",
        is_default=False,
    ),
]

GEMINI_MODEL_OPTIONS: List[Dict[str, Any]] = [opt.model_dump() for opt in GEMINI_MODEL_SPECS]


def normalize_provider(provider: Optional[str]) -> str:
    """Chuẩn hóa tên LLM provider (strip + lowercase, fallback về 'google')."""
    normalized = (provider or "").strip().lower()
    return normalized or "google"


def get_default_model(provider: Optional[str] = "google") -> str:
    """Trả về model mặc định ứng với provider đã chuẩn hóa."""
    return DEFAULT_MODEL_BY_PROVIDER.get(normalize_provider(provider), DEFAULT_GEMINI_MODEL)


def get_gemini_model_options() -> List[LLMModelOption]:
    """Trả về danh sách các model Gemini dưới dạng đối tượng LLMModelOption."""
    return list(GEMINI_MODEL_SPECS)


def get_gemini_model_ids() -> List[str]:
    """Trả về danh sách ID các model Gemini theo đúng thứ tự hiển thị trên UI."""
    return [option.id for option in GEMINI_MODEL_SPECS]


__all__ = [
    "DEFAULT_GEMINI_MODEL",
    "DEFAULT_MODEL_BY_PROVIDER",
    "GEMINI_MODEL_SPECS",
    "GEMINI_MODEL_OPTIONS",
    "normalize_provider",
    "get_default_model",
    "get_gemini_model_options",
    "get_gemini_model_ids",
]
