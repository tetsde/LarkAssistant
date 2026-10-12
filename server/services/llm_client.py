"""
HiLark Unified LLM Client
=========================
Module cung cấp client thống nhất (Unified LLM Client) giao tiếp với Gemini API,
phục vụ cho cả 3 nghiệp vụ cốt lõi:
  1. Trích xuất Thực thể & Mệnh đề (Entity & Fact Extraction) - Ép chuẩn JSON
  2. Hỏi đáp có căn cứ (Grounded QA) - Sinh văn bản tự nhiên, Persona
  3. Tổng hợp Báo cáo hàng ngày (Daily Digest) - Tổng hợp tri thức từ staging messages

Đặc điểm kiến trúc:
  - Tự động fallback qua danh sách model ưu tiên: gemini-2.5-flash -> gemini-flash-latest -> gemini-2.0-flash
  - Mặc định tắt thinkingBudget (thinkingBudget: 0) để tối ưu độ trễ và tiết kiệm quota
  - Hỗ trợ cả cơ chế Bất đồng bộ (Async) cho FastAPI Server và Đồng bộ (Sync) cho Scripts/CLI/Tests
  - Lazy validation API key từ core.config hoặc environment
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Union

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Client giao tiếp với Gemini REST API sử dụng httpx."""

    DEFAULT_MODELS: List[str] = [
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-2.0-flash",
    ]

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_models: Optional[List[str]] = None,
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.default_models = default_models or self.DEFAULT_MODELS
        self.timeout = timeout

    def _ensure_api_key(self) -> str:
        """Lazy validation: lấy API key từ tham số hoặc cấu hình hệ thống."""
        key = (
            self.api_key
            or getattr(settings, "GEMINI_API_KEY", None)
            or getattr(settings, "gemini_api", None)
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("gemini_api")
        )
        if not key:
            raise ValueError(
                "Chưa tìm thấy GEMINI_API_KEY trong cấu hình hoặc file .env (key: GEMINI_API_KEY hoặc gemini_api)."
            )
        return key

    def _get_url(self, model_name: str) -> str:
        key = self._ensure_api_key()
        return f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"

    # --------------------------------------------------------------------------
    # 1. GENERATE JSON (DÀNH CHO ENTITY / FACT EXTRACTION VÀ DỮ LIỆU CÓ CẤU TRÚC)
    # --------------------------------------------------------------------------

    async def generate_json_async(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
        thinking_budget: int = 0,
    ) -> str:
        """Gọi Gemini API bất đồng bộ (async) với responseMimeType='application/json'."""
        models_to_try = [model_name] if model_name else self.default_models
        last_error = None

        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "maxOutputTokens": max_output_tokens,
                "thinkingConfig": {"thinkingBudget": thinking_budget},
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for model in models_to_try:
                url = self._get_url(model)
                try:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                return parts[0].get("text", "")
                    elif resp.status_code in (404, 400):
                        last_error = f"Model {model} không khả dụng (status {resp.status_code}): {resp.text}"
                        logger.warning(last_error)
                        continue
                    elif resp.status_code in (429, 503):
                        last_error = f"Model {model} bị nghẽn/hết quota (status {resp.status_code}): {resp.text}"
                        logger.warning(last_error)
                        continue
                    else:
                        resp.raise_for_status()
                except Exception as e:
                    last_error = e
                    logger.warning(f"Lỗi khi gọi model {model}: {e}")
                    continue

        raise RuntimeError(f"Không thể gọi Gemini API qua các model {models_to_try}. Lỗi cuối: {last_error}")

    def generate_json(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
        thinking_budget: int = 0,
    ) -> str:
        """Gọi Gemini API đồng bộ (sync) với responseMimeType='application/json'."""
        models_to_try = [model_name] if model_name else self.default_models
        last_error = None

        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "maxOutputTokens": max_output_tokens,
                "thinkingConfig": {"thinkingBudget": thinking_budget},
            },
        }

        with httpx.Client(timeout=self.timeout) as client:
            for model in models_to_try:
                url = self._get_url(model)
                try:
                    resp = client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                return parts[0].get("text", "")
                    elif resp.status_code in (404, 400):
                        last_error = f"Model {model} không khả dụng (status {resp.status_code}): {resp.text}"
                        logger.warning(last_error)
                        continue
                    elif resp.status_code in (429, 503):
                        last_error = f"Model {model} bị nghẽn/hết quota (status {resp.status_code}): {resp.text}"
                        logger.warning(last_error)
                        continue
                    else:
                        resp.raise_for_status()
                except Exception as e:
                    last_error = e
                    logger.warning(f"Lỗi khi gọi model {model}: {e}")
                    continue

        raise RuntimeError(f"Không thể gọi Gemini API qua các model {models_to_try}. Lỗi cuối: {last_error}")

    # Aliases cho trích xuất thực thể
    generate_async = generate_json_async
    generate = generate_json

    # --------------------------------------------------------------------------
    # 2. GENERATE TEXT (DÀNH CHO GROUNDED QA & DAILY DIGEST)
    # --------------------------------------------------------------------------

    async def generate_text_async(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 4096,
        thinking_budget: int = 0,
    ) -> str:
        """Gọi Gemini API bất đồng bộ (async) để sinh văn bản tự nhiên (không ép JSON)."""
        models_to_try = [model_name] if model_name else self.default_models
        last_error = None

        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
                "thinkingConfig": {"thinkingBudget": thinking_budget},
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for model in models_to_try:
                url = self._get_url(model)
                try:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                return parts[0].get("text", "")
                    elif resp.status_code in (404, 400):
                        last_error = f"Model {model} không khả dụng (status {resp.status_code}): {resp.text}"
                        logger.warning(last_error)
                        continue
                    elif resp.status_code in (429, 503):
                        last_error = f"Model {model} bị nghẽn/hết quota (status {resp.status_code}): {resp.text}"
                        logger.warning(last_error)
                        continue
                    else:
                        resp.raise_for_status()
                except Exception as e:
                    last_error = e
                    logger.warning(f"Lỗi khi gọi model {model}: {e}")
                    continue

        raise RuntimeError(f"Không thể gọi Gemini API qua các model {models_to_try}. Lỗi cuối: {last_error}")

    def generate_text(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 4096,
        thinking_budget: int = 0,
    ) -> str:
        """Gọi Gemini API đồng bộ (sync) để sinh văn bản tự nhiên (không ép JSON)."""
        models_to_try = [model_name] if model_name else self.default_models
        last_error = None

        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
                "thinkingConfig": {"thinkingBudget": thinking_budget},
            },
        }

        with httpx.Client(timeout=self.timeout) as client:
            for model in models_to_try:
                url = self._get_url(model)
                try:
                    resp = client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                return parts[0].get("text", "")
                    elif resp.status_code in (404, 400):
                        last_error = f"Model {model} không khả dụng (status {resp.status_code}): {resp.text}"
                        logger.warning(last_error)
                        continue
                    elif resp.status_code in (429, 503):
                        last_error = f"Model {model} bị nghẽn/hết quota (status {resp.status_code}): {resp.text}"
                        logger.warning(last_error)
                        continue
                    else:
                        resp.raise_for_status()
                except Exception as e:
                    last_error = e
                    logger.warning(f"Lỗi khi gọi model {model}: {e}")
                    continue

        raise RuntimeError(f"Không thể gọi Gemini API qua các model {models_to_try}. Lỗi cuối: {last_error}")


# Alias tương thích ngược cho GeminiClient
GeminiClient = LLMClient

# Singleton instance dùng chung toàn server
llm_client = LLMClient()
