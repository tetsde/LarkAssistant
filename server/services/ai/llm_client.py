"""
HiLark Unified LLM Client
=========================
Vị trí: server/services/ai/llm_client.py

Module cung cấp client thống nhất (Unified LLM Client) giao tiếp với đa nhà cung cấp LLM
(Google Gemini, OpenAI ChatGPT, Anthropic Claude, Custom OpenAI-compatible), phục vụ cho:
  1. Trích xuất Thực thể & Mệnh đề (Entity & Fact Extraction) - Ép chuẩn JSON
  2. Hỏi đáp có căn cứ (Grounded QA) - Sinh văn bản tự nhiên, Persona
  3. Tổng hợp Báo cáo hàng ngày (Daily Digest) - Tổng hợp tri thức từ staging messages
  4. OCR & Thị giác máy tính (Multimodal Image + Prompt)

Đặc điểm kiến trúc:
  - Model mặc định theo `services.ai.model_catalog` (`gemini-flash-latest`)
  - Adapter thuần theo từng provider nhận trực tiếp `(model, LLMRequest)`, không qua trung gian kiểu Google
  - Không đoán/ép `thinkingConfig`; để provider chạy mặc định và đo trực tiếp `LLMUsage` (gồm `thinking_tokens`)
  - Fail-Closed BYOK: không fallback sang `.env` khi đã bật BYOK, dừng ngay khi lỗi xác thực key
  - Hỗ trợ cả cơ chế Bất đồng bộ (Async) cho FastAPI Server và Đồng bộ (Sync) cho Scripts/CLI/Tests
"""

from __future__ import annotations

import base64
import logging
import os
import re
import time
from typing import Any, Dict, List, NoReturn, Optional, Tuple

import httpx

from core.config import settings
from core.tenant_errors import BYOKConfigurationError
from decorators.cost_telemetry import track_llm_cost
from models.llm import LLMRequest, LLMUsage
from services.ai.model_catalog import (
    DEFAULT_GEMINI_MODEL,
    get_default_model,
    normalize_provider,
)

logger = logging.getLogger(__name__)

_BYOK_AUTH_ERROR_MARKERS = (
    "api key",
    "api_key_invalid",
    "invalid_api_key",
    "incorrect api key",
    "unauthorized",
    "authentication",
    "permission",
    "x-api-key",
)


def _to_non_neg_int(val: Any) -> Optional[int]:
    """Chuyển giá trị thành int không âm an toàn (bỏ qua bool/None/lỗi parse)."""
    if val is None or isinstance(val, bool):
        return None
    try:
        return max(0, int(val))
    except (TypeError, ValueError):
        return None


class LLMClient:
    """Client giao tiếp đa nhà cung cấp LLM (Google Gemini, OpenAI ChatGPT, Anthropic Claude, Custom) dùng httpx."""

    DEFAULT_MODELS: List[str] = [DEFAULT_GEMINI_MODEL]

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_models: Optional[List[str]] = None,
        timeout: float = 60.0,
        provider: str = "google",
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        is_byok: bool = False,
        tenant_key: Optional[str] = None,
    ):
        self.api_key = (api_key or "").strip() or None
        self.provider = normalize_provider(provider)
        self.is_byok = bool(is_byok)
        self.tenant_key = tenant_key
        self.base_url = (base_url or "").strip() or None
        self.model_name = (model_name or "").strip() or None
        self.timeout = float(timeout) if timeout and float(timeout) > 0 else 60.0

        cleaned_defaults = (
            [str(m).strip() for m in default_models if m and str(m).strip()]
            if default_models
            else []
        )
        if cleaned_defaults:
            self.default_models = cleaned_defaults
        elif self.model_name:
            self.default_models = [self.model_name]
        elif self.provider in ("openai", "chatgpt"):
            self.default_models = ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"]
        elif self.provider == "anthropic":
            self.default_models = ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]
        elif self.provider == "custom":
            self.default_models = [self.model_name or get_default_model("custom")]
        else:
            self.default_models = list(self.DEFAULT_MODELS)

    # --------------------------------------------------------------------------
    # API KEY RESOLUTION & ERROR REDACTION
    # --------------------------------------------------------------------------

    def _ensure_api_key(self) -> str:
        """
        Kiểm tra và lấy API key theo chế độ Fail-Closed:
          - Ưu tiên `self.api_key` nếu khác rỗng.
          - Nếu `self.is_byok=True` mà thiếu key -> raise `BYOKConfigurationError` (tuyệt đối không đọc `.env`).
          - Nếu `self.is_byok=False` -> chỉ đọc đúng biến môi trường tương ứng của provider.
        """
        if self.api_key and str(self.api_key).strip():
            return str(self.api_key).strip()

        if self.is_byok:
            raise BYOKConfigurationError(
                f"BYOK đã bật cho provider '{self.provider}' nhưng thiếu API key.",
                tenant_key=self.tenant_key,
                provider=self.provider,
                service_type="llm",
            )

        if self.provider in ("openai", "chatgpt"):
            key = (os.getenv("OPENAI_API_KEY") or getattr(settings, "OPENAI_API_KEY", None) or "").strip()
            if not key:
                raise ValueError(
                    "Chưa tìm thấy OPENAI_API_KEY trong cấu hình hoặc biến môi trường."
                )
            return key

        if self.provider == "anthropic":
            key = (os.getenv("ANTHROPIC_API_KEY") or getattr(settings, "ANTHROPIC_API_KEY", None) or "").strip()
            if not key:
                raise ValueError(
                    "Chưa tìm thấy ANTHROPIC_API_KEY trong cấu hình hoặc biến môi trường."
                )
            return key

        if self.provider == "custom":
            raise ValueError(
                "Custom LLM provider bắt buộc truyền API Key trực tiếp."
            )

        key = (
            getattr(settings, "GEMINI_API_KEY", None)
            or getattr(settings, "gemini_api", None)
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("gemini_api")
            or ""
        ).strip()
        if not key:
            raise ValueError(
                "Chưa tìm thấy GEMINI_API_KEY trong cấu hình hoặc file .env (key: GEMINI_API_KEY hoặc gemini_api)."
            )
        return key

    def _redact_api_key(self, text: Any, key: Optional[str] = None) -> str:
        """Che giấu API key nếu xuất hiện trong thông báo lỗi hoặc URL."""
        raw = str(text) if text is not None else ""
        if not raw:
            return ""
        for candidate in (key, self.api_key):
            if candidate and isinstance(candidate, str):
                clean_key = candidate.strip()
                if clean_key:
                    raw = raw.replace(clean_key, "***")
        raw = re.sub(r"([?&]key=)[^&\s'\"]+", r"\1***", raw)
        return raw

    def _extract_error_message(self, resp: httpx.Response, key: Optional[str] = None) -> str:
        """Đọc thông báo lỗi sạch từ JSON response hoặc text thô và che khóa API."""
        raw_attr = getattr(resp, "text", "")
        raw_text = raw_attr if isinstance(raw_attr, str) else ""
        msg = raw_text

        try:
            err_json = resp.json()
            if isinstance(err_json, dict):
                err_obj = err_json.get("error")
                if isinstance(err_obj, dict):
                    parts: List[str] = []
                    if err_obj.get("message"):
                        parts.append(str(err_obj["message"]))

                    extra: List[str] = []
                    for field_name in ("code", "type", "status"):
                        val = err_obj.get(field_name)
                        if val is not None and str(val).strip():
                            extra.append(str(val).strip())

                    details = err_obj.get("details")
                    if isinstance(details, list):
                        for detail in details:
                            if isinstance(detail, dict) and detail.get("reason"):
                                extra.append(str(detail["reason"]).strip())

                    if parts:
                        msg = parts[0]
                        extra_tags = [
                            tag
                            for tag in extra
                            if not tag.isdigit() and tag.lower() not in msg.lower()
                        ]
                        if extra_tags:
                            msg = f"{msg} ({', '.join(extra_tags)})"
                    elif extra:
                        msg = ", ".join(extra)
                    else:
                        msg = str(err_obj)
                elif err_obj:
                    msg = str(err_obj)
                elif err_json.get("detail"):
                    msg = str(err_json["detail"])
                elif err_json.get("message"):
                    msg = str(err_json["message"])
        except Exception:
            msg = raw_text

        cleaned = (msg or f"HTTP {resp.status_code}").strip()
        return self._redact_api_key(cleaned, key=key)

    def _is_byok_auth_error(self, resp: httpx.Response, error_message: str) -> bool:
        """Nhận diện lỗi HTTP 400 do xác thực / phân quyền API key khi bật BYOK."""
        candidates = [error_message.lower()]
        raw_attr = getattr(resp, "text", "")
        if isinstance(raw_attr, str) and raw_attr:
            candidates.append(self._redact_api_key(raw_attr).lower())
        combined = " ".join(candidates)
        return any(marker in combined for marker in _BYOK_AUTH_ERROR_MARKERS)

    # --------------------------------------------------------------------------
    # USAGE NORMALIZATION (LLMUsage -> ContextVar)
    # --------------------------------------------------------------------------

    def _normalize_usage(
        self,
        model: str,
        raw_usage: Optional[Dict[str, Any]],
    ) -> Optional[LLMUsage]:
        """Chuẩn hóa token usage đa provider (bao gồm thinking_tokens) thành `LLMUsage`."""
        if not raw_usage or not isinstance(raw_usage, dict):
            return None

        if self.provider in ("openai", "chatgpt", "custom"):
            input_tokens = _to_non_neg_int(raw_usage.get("prompt_tokens"))
            if input_tokens is None:
                input_tokens = _to_non_neg_int(raw_usage.get("input_tokens")) or 0

            output_tokens = _to_non_neg_int(raw_usage.get("completion_tokens"))
            if output_tokens is None:
                output_tokens = _to_non_neg_int(raw_usage.get("output_tokens")) or 0

            details = raw_usage.get("completion_tokens_details")
            thinking_tokens = _to_non_neg_int(details.get("reasoning_tokens")) if isinstance(details, dict) else None
            if thinking_tokens is None:
                thinking_tokens = _to_non_neg_int(raw_usage.get("thinking_tokens")) or 0

            thinking_included_in_output = True
            raw_total = _to_non_neg_int(raw_usage.get("total_tokens"))
            total_tokens = raw_total if (raw_total is not None and raw_total > 0) else (input_tokens + output_tokens)

        elif self.provider == "anthropic":
            input_tokens = _to_non_neg_int(raw_usage.get("input_tokens")) or 0
            output_tokens = _to_non_neg_int(raw_usage.get("output_tokens")) or 0
            thinking_tokens = _to_non_neg_int(raw_usage.get("thinking_tokens")) or 0
            thinking_included_in_output = True
            raw_total = _to_non_neg_int(raw_usage.get("total_tokens"))
            total_tokens = raw_total if (raw_total is not None and raw_total > 0) else (input_tokens + output_tokens)

        else:  # Google Gemini
            input_tokens = _to_non_neg_int(raw_usage.get("promptTokenCount"))
            if input_tokens is None:
                input_tokens = _to_non_neg_int(raw_usage.get("input_tokens")) or 0

            output_tokens = _to_non_neg_int(raw_usage.get("candidatesTokenCount"))
            if output_tokens is None:
                output_tokens = _to_non_neg_int(raw_usage.get("output_tokens")) or 0

            thinking_tokens = _to_non_neg_int(raw_usage.get("thoughtsTokenCount"))
            if thinking_tokens is None:
                thinking_tokens = _to_non_neg_int(raw_usage.get("thinking_tokens")) or 0

            thinking_included_in_output = False
            raw_total = _to_non_neg_int(raw_usage.get("totalTokenCount"))
            if raw_total is None:
                raw_total = _to_non_neg_int(raw_usage.get("total_tokens"))
            total_tokens = (
                raw_total
                if (raw_total is not None and raw_total > 0)
                else (input_tokens + output_tokens + thinking_tokens)
            )

        return LLMUsage(
            provider=self.provider,
            model=model,
            is_byok=self.is_byok,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
            total_tokens=total_tokens,
            thinking_included_in_output=thinking_included_in_output,
        )

    def _record_usage_context(
        self,
        model: str,
        raw_usage: Optional[Dict[str, Any]],
    ) -> Optional[LLMUsage]:
        """Chuẩn hóa token usage thành `LLMUsage` và ghi vào ContextVar `last_llm_usage`."""
        usage_model = self._normalize_usage(model, raw_usage)
        if usage_model is None:
            return None

        try:
            from decorators.cost_telemetry import last_llm_usage
            last_llm_usage.set(usage_model)
        except Exception:
            pass
        return usage_model

    # --------------------------------------------------------------------------
    # URL & PURE PROVIDER PAYLOAD ADAPTERS (LLMRequest -> Provider JSON)
    # --------------------------------------------------------------------------

    def _get_url(self, model_name: str, api_key: Optional[str] = None) -> str:
        key = api_key if api_key is not None else self._ensure_api_key()
        b_url = (self.base_url or "https://generativelanguage.googleapis.com").rstrip("/")
        clean_model = model_name[len("models/"):] if model_name.startswith("models/") else model_name
        return f"{b_url}/v1beta/models/{clean_model}:generateContent?key={key}"

    def _get_openai_url(self) -> str:
        b_url = (self.base_url or "https://api.openai.com/v1").rstrip("/")
        return b_url if b_url.endswith("/chat/completions") else f"{b_url}/chat/completions"

    def _get_anthropic_url(self) -> str:
        b_url = (self.base_url or "https://api.anthropic.com/v1").rstrip("/")
        if not b_url.endswith("/v1") and not b_url.endswith("/messages"):
            b_url = f"{b_url}/v1"
        return b_url if b_url.endswith("/messages") else f"{b_url}/messages"

    @staticmethod
    def _build_google_payload(model: str, req: LLMRequest) -> Dict[str, Any]:
        """Dựng payload Google Gemini thuần túy từ `LLMRequest` (không chèn thinkingConfig)."""
        _ = model
        if req.is_multimodal:
            eff_mime = (req.mime_type or "image/png").strip() or "image/png"
            parts: List[Dict[str, Any]] = [
                {
                    "inlineData": {
                        "mimeType": eff_mime,
                        "data": req.image_b64,
                    }
                },
                {"text": req.prompt},
            ]
        else:
            parts = [{"text": req.prompt}]

        gen_config: Dict[str, Any] = {
            "temperature": req.temperature,
            "maxOutputTokens": req.max_output_tokens,
        }
        if req.is_json:
            gen_config["responseMimeType"] = "application/json"

        return {
            "contents": [{"parts": parts}],
            "generationConfig": gen_config,
        }

    @staticmethod
    def _build_openai_payload(model: str, req: LLMRequest) -> Dict[str, Any]:
        """Dựng payload OpenAI / ChatGPT / Custom OpenAI-compatible trực tiếp từ `LLMRequest`."""
        if req.is_multimodal:
            eff_mime = (req.mime_type or "image/png").strip() or "image/png"
            content: Any = [
                {"type": "text", "text": req.prompt},
                {"type": "image_url", "image_url": {"url": f"data:{eff_mime};base64,{req.image_b64}"}},
            ]
        else:
            content = req.prompt

        oai_payload: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": req.temperature,
            "max_tokens": req.max_output_tokens,
        }
        if req.is_json:
            oai_payload["response_format"] = {"type": "json_object"}
        return oai_payload

    @staticmethod
    def _build_anthropic_payload(model: str, req: LLMRequest) -> Dict[str, Any]:
        """Dựng payload Anthropic Messages trực tiếp từ `LLMRequest`."""
        if req.is_multimodal:
            eff_mime = (req.mime_type or "image/png").strip() or "image/png"
            content: Any = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": eff_mime,
                        "data": req.image_b64,
                    },
                },
                {"type": "text", "text": req.prompt},
            ]
        else:
            content = req.prompt

        ant_payload: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": req.max_output_tokens,
            "temperature": req.temperature,
        }
        if req.is_json:
            ant_payload["system"] = (
                "You must output strictly valid JSON only. "
                "Do not include markdown code block syntax or explanations."
            )
        return ant_payload

    def _prepare_provider_request(
        self,
        model: str,
        req: LLMRequest,
        api_key: str,
    ) -> Tuple[str, Optional[Dict[str, str]], Dict[str, Any]]:
        """Chuẩn bị thống nhất `(url, headers, json_payload)` theo provider hiện tại."""
        if self.provider in ("openai", "chatgpt", "custom"):
            return (
                self._get_openai_url(),
                {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                self._build_openai_payload(model, req),
            )

        if self.provider == "anthropic":
            return (
                self._get_anthropic_url(),
                {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                self._build_anthropic_payload(model, req),
            )

        return (
            self._get_url(model, api_key=api_key),
            None,
            self._build_google_payload(model, req),
        )

    # --------------------------------------------------------------------------
    # RESPONSE EXTRACTION
    # --------------------------------------------------------------------------

    @staticmethod
    def _extract_openai_text(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        choices = data.get("choices", [])
        if not choices or not isinstance(choices, list):
            return ""
        msg_content = choices[0].get("message", {}).get("content", "")
        if isinstance(msg_content, str):
            return msg_content
        if isinstance(msg_content, list):
            parts = [
                item.get("text", "")
                for item in msg_content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            return "".join(parts)
        return "" if msg_content is None else str(msg_content)

    @staticmethod
    def _extract_anthropic_text(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        content = data.get("content", [])
        if not content or not isinstance(content, list):
            return ""
        text_blocks = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        if text_blocks:
            return "".join(text_blocks)
        if isinstance(content[0], dict):
            return content[0].get("text", "") or ""
        return ""

    def _extract_text_from_response(self, resp: httpx.Response, model: str) -> Optional[str]:
        """
        Bóc tách text phản hồi từ JSON của Gemini API.
        Trả về chuỗi text nếu thành công, hoặc None nếu status khác 200.
        """
        if resp.status_code != 200:
            return None

        data = resp.json()
        if isinstance(data, dict):
            self._record_usage_context(model, data.get("usageMetadata"))
        else:
            return ""

        candidates = data.get("candidates", [])
        if candidates:
            candidate = candidates[0]
            parts = candidate.get("content", {}).get("parts", [])
            if parts:
                non_thought_texts = [
                    p.get("text", "")
                    for p in parts
                    if isinstance(p, dict) and not p.get("thought") and "text" in p
                ]
                if non_thought_texts:
                    return "".join(non_thought_texts)
                return parts[0].get("text", "")

            finish_reason = candidate.get("finishReason", "")
            if finish_reason and finish_reason != "STOP":
                logger.warning(f"Model {model} trả về không có text. finishReason={finish_reason}")

        prompt_feedback = data.get("promptFeedback", {})
        block_reason = prompt_feedback.get("blockReason")
        if block_reason:
            logger.warning(f"Model {model} chặn prompt vì lý do an toàn: blockReason={block_reason}")

        return ""

    def _extract_provider_response(self, resp: httpx.Response, model: str) -> Optional[str]:
        """Bóc tách text phản hồi + ghi nhận `LLMUsage` thống nhất cho mọi provider khi HTTP 200."""
        if resp.status_code != 200:
            return None

        if self.provider in ("openai", "chatgpt", "custom"):
            data = resp.json()
            if isinstance(data, dict):
                self._record_usage_context(model, data.get("usage"))
            return self._extract_openai_text(data)

        if self.provider == "anthropic":
            data = resp.json()
            if isinstance(data, dict):
                self._record_usage_context(model, data.get("usage"))
            return self._extract_anthropic_text(data)

        return self._extract_text_from_response(resp, model)

    # --------------------------------------------------------------------------
    # ERROR HANDLING & CORE EXECUTORS (NATIVE ASYNC & SYNC)
    # --------------------------------------------------------------------------

    def _handle_non_200_response(
        self,
        resp: httpx.Response,
        model: str,
        resolved_key: str,
    ) -> str:
        """
        Xử lý phản hồi lỗi từ provider:
          - Khi `self.is_byok=True`, status 401/403 hoặc 400 do lỗi xác thực key
            -> raise `BYOKConfigurationError` ngay lập tức (Fail-Closed).
          - Trả về thông báo lỗi sạch (đã redact key) để lưu vào `last_error`.
        """
        err_msg = self._extract_error_message(resp, key=resolved_key)
        status_code = resp.status_code

        if self.is_byok:
            if status_code in (401, 403):
                raise BYOKConfigurationError(
                    f"API key BYOK bị từ chối bởi {self.provider} (HTTP {status_code}): {err_msg}",
                    tenant_key=self.tenant_key,
                    provider=self.provider,
                    service_type="llm",
                )
            if status_code == 400 and self._is_byok_auth_error(resp, err_msg):
                raise BYOKConfigurationError(
                    f"API key BYOK không hợp lệ theo phản hồi từ {self.provider} (HTTP 400): {err_msg}",
                    tenant_key=self.tenant_key,
                    provider=self.provider,
                    service_type="llm",
                )

        if status_code in (404, 400):
            detail = f"Model {model} không khả dụng (status {status_code}): {err_msg}"
        elif status_code in (429, 503):
            detail = f"Model {model} bị nghẽn/hết quota (status {status_code}): {err_msg}"
        else:
            detail = f"Model {model} trả về lỗi (status {status_code}): {err_msg}"

        logger.warning(detail)
        return detail

    def _resolve_models_to_try(self, model_name: Optional[str]) -> List[str]:
        clean_model_arg = (model_name or "").strip() if model_name else None
        models_to_try = [clean_model_arg] if clean_model_arg else list(self.default_models)
        if not models_to_try:
            models_to_try = [get_default_model(self.provider)]
        return models_to_try

    def _raise_execution_failure(
        self,
        resolved_key: str,
        models_to_try: List[str],
        attempt_statuses: List[Optional[int]],
        last_error: Any,
    ) -> NoReturn:
        safe_last = self._redact_api_key(last_error, key=resolved_key)
        if self.is_byok and attempt_statuses and all(code in (400, 404) for code in attempt_statuses):
            raise BYOKConfigurationError(
                f"Cấu hình BYOK không hợp lệ cho provider '{self.provider}' "
                f"(models={models_to_try}, base_url={self.base_url or 'default'}): {safe_last}",
                tenant_key=self.tenant_key,
                provider=self.provider,
                service_type="llm",
            )

        raise RuntimeError(
            f"Không thể gọi LLM API ({self.provider}) qua các model {models_to_try}. Lỗi cuối: {safe_last}"
        )

    async def _aexecute(self, req: LLMRequest, model_name: Optional[str] = None) -> str:
        """Thực thi gọi LLM API bất đồng bộ (Native Async) kèm fallback model."""
        resolved_key = self._ensure_api_key()
        models_to_try = self._resolve_models_to_try(model_name)

        last_error: Any = None
        attempt_statuses: List[Optional[int]] = []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for model in models_to_try:
                try:
                    url, headers, json_payload = self._prepare_provider_request(model, req, resolved_key)
                    post_kwargs: Dict[str, Any] = {"json": json_payload}
                    if headers is not None:
                        post_kwargs["headers"] = headers

                    resp = await client.post(url, **post_kwargs)
                    text = self._extract_provider_response(resp, model)
                    if text is not None:
                        return text

                    attempt_statuses.append(resp.status_code)
                    last_error = self._handle_non_200_response(resp, model, resolved_key)
                except BYOKConfigurationError:
                    raise
                except Exception as e:
                    attempt_statuses.append(None)
                    safe_err = self._redact_api_key(e, key=resolved_key)
                    last_error = safe_err
                    logger.warning(f"Lỗi khi gọi model {model} ({self.provider}): {safe_err}")
                    continue

        self._raise_execution_failure(resolved_key, models_to_try, attempt_statuses, last_error)

    def _execute(self, req: LLMRequest, model_name: Optional[str] = None) -> str:
        """Thực thi gọi LLM API đồng bộ (Sync) kèm fallback model."""
        resolved_key = self._ensure_api_key()
        models_to_try = self._resolve_models_to_try(model_name)

        last_error: Any = None
        attempt_statuses: List[Optional[int]] = []

        with httpx.Client(timeout=self.timeout) as client:
            for model in models_to_try:
                try:
                    url, headers, json_payload = self._prepare_provider_request(model, req, resolved_key)
                    post_kwargs: Dict[str, Any] = {"json": json_payload}
                    if headers is not None:
                        post_kwargs["headers"] = headers

                    resp = client.post(url, **post_kwargs)
                    text = self._extract_provider_response(resp, model)
                    if text is not None:
                        return text

                    attempt_statuses.append(resp.status_code)
                    last_error = self._handle_non_200_response(resp, model, resolved_key)
                except BYOKConfigurationError:
                    raise
                except Exception as e:
                    attempt_statuses.append(None)
                    safe_err = self._redact_api_key(e, key=resolved_key)
                    last_error = safe_err
                    logger.warning(f"Lỗi khi gọi model {model} ({self.provider}): {safe_err}")
                    continue

        self._raise_execution_failure(resolved_key, models_to_try, attempt_statuses, last_error)

    # --------------------------------------------------------------------------
    # HEALTH CHECK / PING
    # --------------------------------------------------------------------------

    async def ping(
        self,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Tuple[bool, str, float]:
        """
        Kiểm tra kết nối trực tiếp tới LLM Provider bằng request `ping` tối giản.
        Phục vụ UI Test Key và Health Check; luôn redact API key khỏi mọi lỗi.
        """
        try:
            key = self._ensure_api_key()
        except Exception:
            return False, "API Key không được để trống.", 0.0

        timeout_val = (
            float(timeout)
            if (timeout is not None and float(timeout) > 0)
            else (self.timeout if self.timeout and self.timeout > 0 else 30.0)
        )
        model_target = (
            (model or "").strip()
            or self.model_name
            or (self.default_models[0] if self.default_models else get_default_model(self.provider))
        )
        ping_req = LLMRequest(
            prompt="ping",
            temperature=0.0,
            max_output_tokens=5,
            is_json=False,
        )

        start_time = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout_val) as client:
                url, headers, req_payload = self._prepare_provider_request(model_target, ping_req, key)
                post_kwargs: Dict[str, Any] = {"json": req_payload}
                if headers is not None:
                    post_kwargs["headers"] = headers

                res = await client.post(url, **post_kwargs)
                latency_ms = round((time.monotonic() - start_time) * 1000, 2)
                if res.status_code == 200:
                    provider_display = {
                        "google": "Google Gemini",
                        "openai": "ChatGPT / OpenAI",
                        "chatgpt": "ChatGPT / OpenAI",
                        "anthropic": "Anthropic Claude",
                        "custom": "Custom Provider",
                    }.get(self.provider, self.provider.upper())
                    return (
                        True,
                        f"Kết nối {provider_display} thành công (độ trễ {latency_ms} ms)",
                        latency_ms,
                    )

                err_msg = self._extract_error_message(res, key=key)
                return False, f"Provider từ chối ({res.status_code}): {err_msg[:160]}", latency_ms

        except httpx.TimeoutException:
            return (
                False,
                f"Kết nối đến {self.provider.upper()} quá thời gian chờ (Timeout {timeout_val}s).",
                0.0,
            )
        except Exception as e:
            safe_err = self._redact_api_key(e, key=key)
            return False, f"Lỗi kết nối kiểm tra: {safe_err}", 0.0

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
    ) -> str:
        """Gọi LLM API bất đồng bộ (async) với chế độ đầu ra JSON."""
        req = LLMRequest(
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            is_json=True,
        )
        return await self._aexecute(req, model_name=model_name)

    @track_llm_cost(operation="generate_json")
    def generate_json(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
    ) -> str:
        """Gọi LLM API đồng bộ (sync) với chế độ đầu ra JSON."""
        req = LLMRequest(
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            is_json=True,
        )
        return self._execute(req, model_name=model_name)

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
    ) -> str:
        """Gọi LLM API bất đồng bộ (async) để sinh văn bản tự nhiên (không ép JSON)."""
        req = LLMRequest(
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            is_json=False,
        )
        return await self._aexecute(req, model_name=model_name)

    @track_llm_cost(operation="generate_text")
    def generate_text(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 4096,
    ) -> str:
        """Gọi LLM API đồng bộ (sync) để sinh văn bản tự nhiên (không ép JSON)."""
        req = LLMRequest(
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            is_json=False,
        )
        return self._execute(req, model_name=model_name)

    # --------------------------------------------------------------------------
    # 3. GENERATE MULTIMODAL (DÀNH CHO OCR HÌNH ẢNH & THỊ GIÁC MÁY TÍNH)
    # --------------------------------------------------------------------------

    @track_llm_cost(operation="generate_multimodal_async")
    async def generate_multimodal_async(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        model_name: Optional[str] = None,
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
        is_json: bool = False,
    ) -> str:
        """Gọi LLM API Multimodal (ảnh + text) bất đồng bộ (async)."""
        b64_data = base64.b64encode(image_bytes).decode("utf-8")
        eff_mime = (mime_type or "image/png").strip() or "image/png"
        req = LLMRequest(
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            is_json=is_json,
            image_b64=b64_data,
            mime_type=eff_mime,
        )
        return await self._aexecute(req, model_name=model_name)

    @track_llm_cost(operation="generate_multimodal")
    def generate_multimodal(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        model_name: Optional[str] = None,
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
        is_json: bool = False,
    ) -> str:
        """Gọi LLM API Multimodal (ảnh + text) đồng bộ (sync)."""
        b64_data = base64.b64encode(image_bytes).decode("utf-8")
        eff_mime = (mime_type or "image/png").strip() or "image/png"
        req = LLMRequest(
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            is_json=is_json,
            image_b64=b64_data,
            mime_type=eff_mime,
        )
        return self._execute(req, model_name=model_name)


# Singleton instance dùng chung toàn server
llm_client = LLMClient()

__all__ = [
    "LLMClient",
    "llm_client",
]

