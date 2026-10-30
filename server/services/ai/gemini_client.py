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
  - Xử lý trích xuất an toàn (Safety block handling & Finish reason detection)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Union

import httpx

from core.config import settings
from decorators.cost_telemetry import track_llm_cost

logger = logging.getLogger(__name__)


class LLMClient:
    """Client giao tiếp với LLM API (Google Gemini, OpenAI ChatGPT, Anthropic Claude, Custom) sử dụng httpx."""

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
        provider: str = "google",
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.api_key = api_key
        self.provider = (provider or "google").strip().lower()
        self.base_url = base_url
        self.model_name = model_name
        self.timeout = timeout
        if default_models:
            self.default_models = default_models
        elif self.model_name:
            self.default_models = [self.model_name]
        elif self.provider in ("openai", "chatgpt"):
            self.default_models = ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"]
        elif self.provider == "anthropic":
            self.default_models = ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]
        elif self.provider == "custom":
            self.default_models = [self.model_name or "gpt-3.5-turbo"]
        else:
            self.default_models = self.DEFAULT_MODELS

    def _ensure_api_key(self) -> str:
        """Lazy validation: lấy API key từ tham số hoặc cấu hình hệ thống."""
        if self.api_key:
            return self.api_key

        if self.provider in ("openai", "chatgpt"):
            key = os.getenv("OPENAI_API_KEY") or getattr(settings, "OPENAI_API_KEY", None)
            if key:
                return key
        elif self.provider == "anthropic":
            key = os.getenv("ANTHROPIC_API_KEY") or getattr(settings, "ANTHROPIC_API_KEY", None)
            if key:
                return key

        key = (
            getattr(settings, "GEMINI_API_KEY", None)
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
        b_url = (self.base_url or "https://generativelanguage.googleapis.com").rstrip("/")
        return f"{b_url}/v1beta/models/{model_name}:generateContent?key={key}"

    def _build_payload(
        self,
        prompt: str,
        temperature: float,
        max_output_tokens: int,
        thinking_budget: int = 0,
        is_json: bool = False,
    ) -> Dict[str, Any]:
        """Tạo payload cấu hình chuẩn hóa cho Gemini API và Multi-provider."""
        gen_config: Dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
            "thinkingConfig": {"thinkingBudget": thinking_budget},
        }
        if is_json:
            gen_config["responseMimeType"] = "application/json"

        return {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
            "_raw_prompt": prompt,
            "_is_json": is_json,
            "_temperature": temperature,
            "_max_output_tokens": max_output_tokens,
        }

    def _extract_text_from_response(self, resp: httpx.Response, model: str) -> Optional[str]:
        """
        Bóc tách text phản hồi từ JSON của Gemini API.
        Trả về chuỗi text nếu thành công, hoặc None nếu response code không phải 200.
        Phát hiện sớm các trường hợp bị chặn bởi Safety Filters.
        """
        if resp.status_code == 200:
            data = resp.json()
            usage_meta = data.get("usageMetadata")
            if usage_meta and isinstance(usage_meta, dict):
                try:
                    from decorators.cost_telemetry import last_llm_usage
                    last_llm_usage.set(usage_meta)
                except Exception:
                    pass

            candidates = data.get("candidates", [])
            if candidates:
                candidate = candidates[0]
                parts = candidate.get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
                
                finish_reason = candidate.get("finishReason", "")
                if finish_reason and finish_reason != "STOP":
                    logger.warning(f"Model {model} trả về không có text. finishReason={finish_reason}")
            
            # Kiểm tra Safety block cấp độ prompt
            prompt_feedback = data.get("promptFeedback", {})
            block_reason = prompt_feedback.get("blockReason")
            if block_reason:
                logger.warning(f"Model {model} chặn prompt vì lý do an toàn: blockReason={block_reason}")
            
            # Trả về text rỗng nếu 200 nhưng không có parts
            return ""

        return None

    # --------------------------------------------------------------------------
    # CORE EXECUTORS (NATIVE ASYNC & SYNC)
    # --------------------------------------------------------------------------

    async def _aexecute(self, payload: Dict[str, Any], model_name: Optional[str] = None) -> str:
        """Thực thi gọi LLM API bất đồng bộ (Native Async) kèm cơ chế tự động fallback model."""
        models_to_try = [model_name] if model_name else self.default_models
        last_error = None

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for model in models_to_try:
                try:
                    if self.provider in ("openai", "chatgpt", "custom"):
                        b_url = (self.base_url or "https://api.openai.com/v1").rstrip("/")
                        url = f"{b_url}/chat/completions" if not b_url.endswith("/chat/completions") else b_url
                        headers = {
                            "Authorization": f"Bearer {self._ensure_api_key()}",
                            "Content-Type": "application/json",
                        }
                        oai_payload: Dict[str, Any] = {
                            "model": model,
                            "messages": [{"role": "user", "content": payload.get("_raw_prompt", "")}],
                            "temperature": payload.get("_temperature", 0.2),
                            "max_tokens": payload.get("_max_output_tokens", 4096),
                        }
                        if payload.get("_is_json"):
                            oai_payload["response_format"] = {"type": "json_object"}
                        resp = await client.post(url, headers=headers, json=oai_payload)
                        if resp.status_code == 200:
                            data = resp.json()
                            choices = data.get("choices", [])
                            if choices:
                                return choices[0].get("message", {}).get("content", "")
                            return ""
                    elif self.provider == "anthropic":
                        b_url = (self.base_url or "https://api.anthropic.com/v1").rstrip("/")
                        url = f"{b_url}/messages" if b_url.endswith("/v1") else f"{b_url}/v1/messages"
                        headers = {
                            "x-api-key": self._ensure_api_key(),
                            "anthropic-version": "2023-06-01",
                            "Content-Type": "application/json",
                        }
                        ant_payload: Dict[str, Any] = {
                            "model": model,
                            "messages": [{"role": "user", "content": payload.get("_raw_prompt", "")}],
                            "max_tokens": payload.get("_max_output_tokens", 4096),
                            "temperature": payload.get("_temperature", 0.2),
                        }
                        if payload.get("_is_json"):
                            ant_payload["system"] = "You must output strictly valid JSON only. Do not include markdown code block syntax or explanations."
                        resp = await client.post(url, headers=headers, json=ant_payload)
                        if resp.status_code == 200:
                            data = resp.json()
                            content = data.get("content", [])
                            if content:
                                return content[0].get("text", "")
                            return ""
                    else:  # Google Gemini
                        url = self._get_url(model)
                        resp = await client.post(url, json=payload)
                        text = self._extract_text_from_response(resp, model)
                        if text is not None:
                            return text

                    if resp.status_code in (404, 400):
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
                    logger.warning(f"Lỗi khi gọi model {model} ({self.provider}): {e}")
                    continue

        raise RuntimeError(f"Không thể gọi LLM API ({self.provider}) qua các model {models_to_try}. Lỗi cuối: {last_error}")

    def _execute(self, payload: Dict[str, Any], model_name: Optional[str] = None) -> str:
        """Thực thi gọi LLM API đồng bộ (Sync) kèm cơ chế tự động fallback model."""
        models_to_try = [model_name] if model_name else self.default_models
        last_error = None

        with httpx.Client(timeout=self.timeout) as client:
            for model in models_to_try:
                try:
                    if self.provider in ("openai", "chatgpt", "custom"):
                        b_url = (self.base_url or "https://api.openai.com/v1").rstrip("/")
                        url = f"{b_url}/chat/completions" if not b_url.endswith("/chat/completions") else b_url
                        headers = {
                            "Authorization": f"Bearer {self._ensure_api_key()}",
                            "Content-Type": "application/json",
                        }
                        oai_payload: Dict[str, Any] = {
                            "model": model,
                            "messages": [{"role": "user", "content": payload.get("_raw_prompt", "")}],
                            "temperature": payload.get("_temperature", 0.2),
                            "max_tokens": payload.get("_max_output_tokens", 4096),
                        }
                        if payload.get("_is_json"):
                            oai_payload["response_format"] = {"type": "json_object"}
                        resp = client.post(url, headers=headers, json=oai_payload)
                        if resp.status_code == 200:
                            data = resp.json()
                            choices = data.get("choices", [])
                            if choices:
                                return choices[0].get("message", {}).get("content", "")
                            return ""
                    elif self.provider == "anthropic":
                        b_url = (self.base_url or "https://api.anthropic.com/v1").rstrip("/")
                        url = f"{b_url}/messages" if b_url.endswith("/v1") else f"{b_url}/v1/messages"
                        headers = {
                            "x-api-key": self._ensure_api_key(),
                            "anthropic-version": "2023-06-01",
                            "Content-Type": "application/json",
                        }
                        ant_payload: Dict[str, Any] = {
                            "model": model,
                            "messages": [{"role": "user", "content": payload.get("_raw_prompt", "")}],
                            "max_tokens": payload.get("_max_output_tokens", 4096),
                            "temperature": payload.get("_temperature", 0.2),
                        }
                        if payload.get("_is_json"):
                            ant_payload["system"] = "You must output strictly valid JSON only. Do not include markdown code block syntax or explanations."
                        resp = client.post(url, headers=headers, json=ant_payload)
                        if resp.status_code == 200:
                            data = resp.json()
                            content = data.get("content", [])
                            if content:
                                return content[0].get("text", "")
                            return ""
                    else:  # Google Gemini
                        url = self._get_url(model)
                        resp = client.post(url, json=payload)
                        text = self._extract_text_from_response(resp, model)
                        if text is not None:
                            return text

                    if resp.status_code in (404, 400):
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
                    logger.warning(f"Lỗi khi gọi model {model} ({self.provider}): {e}")
                    continue

        raise RuntimeError(f"Không thể gọi LLM API ({self.provider}) qua các model {models_to_try}. Lỗi cuối: {last_error}")

    # --------------------------------------------------------------------------
    # 1. GENERATE JSON (DÀNH CHO ENTITY / FACT EXTRACTION VÀ DỮ LIỆU CÓ CẤU TRÚC)
    # --------------------------------------------------------------------------

    @track_llm_cost(operation="generate_json_async")
    async def generate_json_async(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
        thinking_budget: int = 0,
    ) -> str:
        """Gọi Gemini API bất đồng bộ (async) với responseMimeType='application/json'."""
        payload = self._build_payload(
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_budget=thinking_budget,
            is_json=True,
        )
        return await self._aexecute(payload, model_name=model_name)

    @track_llm_cost(operation="generate_json")
    def generate_json(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
        thinking_budget: int = 0,
    ) -> str:
        """Gọi Gemini API đồng bộ (sync) với responseMimeType='application/json'."""
        payload = self._build_payload(
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_budget=thinking_budget,
            is_json=True,
        )
        return self._execute(payload, model_name=model_name)

    # Aliases cho trích xuất thực thể
    generate_async = generate_json_async
    generate = generate_json

    # --------------------------------------------------------------------------
    # 2. GENERATE TEXT (DÀNH CHO GROUNDED QA & DAILY DIGEST)
    # --------------------------------------------------------------------------

    @track_llm_cost(operation="generate_text_async")
    async def generate_text_async(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 4096,
        thinking_budget: int = 0,
    ) -> str:
        """Gọi Gemini API bất đồng bộ (async) để sinh văn bản tự nhiên (không ép JSON)."""
        payload = self._build_payload(
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_budget=thinking_budget,
            is_json=False,
        )
        return await self._aexecute(payload, model_name=model_name)

    @track_llm_cost(operation="generate_text")
    def generate_text(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 4096,
        thinking_budget: int = 0,
    ) -> str:
        """Gọi Gemini API đồng bộ (sync) để sinh văn bản tự nhiên (không ép JSON)."""
        payload = self._build_payload(
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_budget=thinking_budget,
            is_json=False,
        )
        return self._execute(payload, model_name=model_name)

    # --------------------------------------------------------------------------
    # 3. GENERATE MULTIMODAL (DÀNH CHO OCR HÌNH ẢNH & THỊ GIÁC MÁY TÍNH)
    # --------------------------------------------------------------------------

    def _build_multimodal_payload(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
        thinking_budget: int = 0,
        is_json: bool = False,
    ) -> Dict[str, Any]:
        """Tạo payload cho yêu cầu đa phương thức (Ảnh + Prompt)."""
        import base64
        b64_data = base64.b64encode(image_bytes).decode("utf-8")
        gen_config: Dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
            "thinkingConfig": {"thinkingBudget": thinking_budget},
        }
        if is_json:
            gen_config["responseMimeType"] = "application/json"

        return {
            "contents": [
                {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": b64_data,
                            }
                        },
                        {
                            "text": prompt,
                        },
                    ]
                }
            ],
            "generationConfig": gen_config,
        }

    @track_llm_cost(operation="generate_multimodal_async")
    async def generate_multimodal_async(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        model_name: Optional[str] = None,
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
        thinking_budget: int = 0,
        is_json: bool = False,
    ) -> str:
        """Gọi Gemini API Multimodal (ảnh + text) bất đồng bộ (async)."""
        payload = self._build_multimodal_payload(
            prompt=prompt,
            image_bytes=image_bytes,
            mime_type=mime_type,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_budget=thinking_budget,
            is_json=is_json,
        )
        return await self._aexecute(payload, model_name=model_name)

    @track_llm_cost(operation="generate_multimodal")
    def generate_multimodal(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        model_name: Optional[str] = None,
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
        thinking_budget: int = 0,
        is_json: bool = False,
    ) -> str:
        """Gọi Gemini API Multimodal (ảnh + text) đồng bộ (sync)."""
        payload = self._build_multimodal_payload(
            prompt=prompt,
            image_bytes=image_bytes,
            mime_type=mime_type,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_budget=thinking_budget,
            is_json=is_json,
        )
        return self._execute(payload, model_name=model_name)


# Alias tương thích ngược cho GeminiClient
GeminiClient = LLMClient

# Singleton instance dùng chung toàn server
llm_client = LLMClient()
