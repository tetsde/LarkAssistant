"""
HiLark Cost Telemetry & Tracking Decorators
==========================================
Vị trí: server/decorators/cost_telemetry.py

Cung cấp các Decorator đo lường chi phí, độ trễ và số lượng token cho:
  1. @track_llm_cost: Các điểm gọi Multi-Provider LLM (Gemini, OpenAI, Anthropic, Custom)
  2. @track_jev_cost: Các điểm gọi JEV System 1 Gatekeeper (classify_message, classify_thread_decision...)

Đặc điểm kiến trúc:
  - Tách biệt độc lập trong thư mục `server/decorators/`, không làm ô nhiễm business logic của services.
  - Hỗ trợ cả hàm bất đồng bộ (async def) lẫn hàm đồng bộ (def).
  - Tự động trích xuất token đa định dạng (Gemini usageMetadata, OpenAI usage, Anthropic usage) hoặc ước lượng heuristic.
  - Hỗ trợ đầy đủ metadata Multi-Tenant & BYOK (tenant_key, provider, is_byok).
  - Ghi log có cấu trúc [COST_TRACKER] và lưu trữ bất đồng bộ (non-blocking) vào MongoDB `cost_telemetry`.
  - Tuyệt đối không làm thay đổi giá trị trả về hoặc nuốt ngoại lệ nghiệp vụ.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import functools
import logging
import math
import time
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar, Union

from core.config import settings
from models.llm import LLMUsage
from models.telemetry import ModelPricing, TelemetryRecord

# Khớp với services.ai.model_catalog.DEFAULT_GEMINI_MODEL (tránh import chéo decorators -> services)
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"

logger = logging.getLogger("hilark.telemetry")

# ContextVar lưu trữ ngữ cảnh gọi (chat_id, user_id, tenant_key, request_id)
current_telemetry_context: ContextVar[Dict[str, Any]] = ContextVar(
    "current_telemetry_context", default={}
)

# ContextVar nhận usage metadata từ response thực tế của LLM API
last_llm_usage: ContextVar[Optional[Union[LLMUsage, Dict[str, Any]]]] = ContextVar(
    "last_llm_usage", default=None
)

# ContextVar nhận metadata thực tế từ lần gọi JEV API (tenant_key, is_byok, ...)
last_jev_usage: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "last_jev_usage", default=None
)

_TOKEN_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "thinking_tokens",
    "total_tokens",
    "promptTokenCount",
    "prompt_tokens",
    "candidatesTokenCount",
    "completion_tokens",
    "thoughtsTokenCount",
    "totalTokenCount",
)


def safe_get_current_tenant_key() -> Optional[str]:
    """Lấy tenant_key hiện tại từ scoped_query một cách an toàn."""
    try:
        from database.scoped_query import get_current_tenant_key
        val = get_current_tenant_key()
        if isinstance(val, str):
            cleaned = val.strip()
            return cleaned or None
        return None
    except Exception:
        return None


def _first_non_empty_str(*values: Any) -> Optional[str]:
    for val in values:
        if isinstance(val, str):
            cleaned = val.strip()
            if cleaned:
                return cleaned
    return None


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _first_present_int(mapping: Dict[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return _safe_int(mapping[key])
    return None


def _extract_llm_prompt_text(args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> str:
    if len(args) > 1 and isinstance(args[1], str):
        return args[1]
    if "prompt" in kwargs and isinstance(kwargs["prompt"], str):
        return kwargs["prompt"]
    if len(args) > 0 and isinstance(args[0], str):
        return args[0]
    return ""


def _extract_jev_input_text(args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> str:
    if len(args) > 1 and isinstance(args[1], str):
        return args[1]
    if "message" in kwargs and kwargs["message"] is not None:
        return str(kwargs["message"])
    if "query" in kwargs and kwargs["query"] is not None:
        return str(kwargs["query"])
    if len(args) > 0 and isinstance(args[0], str):
        return args[0]
    return ""


def _get_usd_to_vnd_rate() -> float:
    raw_rate = getattr(settings, "USD_TO_VND_RATE", 25400.0)
    try:
        rate = float(raw_rate)
        if math.isfinite(rate) and rate > 0.0:
            return rate
    except (TypeError, ValueError):
        pass
    return 25400.0


def _validate_pricing_entry(entry: Any, *, label: str) -> Optional[ModelPricing]:
    if isinstance(entry, ModelPricing):
        return entry
    if not isinstance(entry, dict):
        logger.warning(
            "Cấu hình giá %s không phải dict hợp lệ (%s); chuyển tầng fallback.",
            label,
            type(entry).__name__,
        )
        return None
    try:
        return ModelPricing(**entry)
    except Exception as exc:
        logger.warning(
            "Cấu hình giá %s lỗi validation ModelPricing (%s); chuyển tầng fallback.",
            label,
            exc,
        )
        return None


def _resolve_model_pricing(provider_norm: str, clean_model: str) -> ModelPricing:
    """
    Tìm bảng giá phù hợp theo thứ tự ưu tiên:
      1. Composite key "<provider>/<model>" (chính xác -> prefix dài nhất)
      2. Key model không chứa "/" (chính xác -> prefix dài nhất)
      3. Provider default pricing trong settings.get_provider_default_pricing()
      4. Fallback toàn cục settings.LLM_DEFAULT_*
    """
    raw_model_table: Any = {}
    try:
        raw_model_table = settings.get_model_pricing_table()
    except Exception as exc:
        logger.warning("Lỗi đọc bảng giá model từ settings (%s); fallback {}.", exc)
        raw_model_table = {}

    model_table: Dict[str, Any] = {}
    if isinstance(raw_model_table, dict):
        for raw_k, raw_v in raw_model_table.items():
            k_norm = str(raw_k or "").strip().lower()
            if k_norm:
                model_table[k_norm] = raw_v

    if clean_model:
        # 1. Composite key "<provider>/<model>"
        if provider_norm:
            composite_exact = f"{provider_norm}/{clean_model}"
            if composite_exact in model_table:
                validated = _validate_pricing_entry(
                    model_table[composite_exact],
                    label=f"model[{composite_exact}]",
                )
                if validated is not None:
                    return validated

            provider_prefix = f"{provider_norm}/"
            composite_candidates = [
                (key[len(provider_prefix):], key, val)
                for key, val in model_table.items()
                if key.startswith(provider_prefix)
                and key != composite_exact
                and len(key) > len(provider_prefix)
                and clean_model.startswith(key[len(provider_prefix):])
            ]
            composite_candidates.sort(key=lambda item: len(item[0]), reverse=True)
            for _, comp_key, comp_val in composite_candidates:
                validated = _validate_pricing_entry(
                    comp_val,
                    label=f"model[{comp_key}]",
                )
                if validated is not None:
                    return validated

        # 2. Key model không chứa "/"
        if "/" not in clean_model and clean_model in model_table:
            validated = _validate_pricing_entry(
                model_table[clean_model],
                label=f"model[{clean_model}]",
            )
            if validated is not None:
                return validated

        plain_candidates = [
            (key, val)
            for key, val in model_table.items()
            if "/" not in key and key != clean_model and clean_model.startswith(key)
        ]
        plain_candidates.sort(key=lambda item: len(item[0]), reverse=True)
        for plain_key, plain_val in plain_candidates:
            validated = _validate_pricing_entry(
                plain_val,
                label=f"model[{plain_key}]",
            )
            if validated is not None:
                return validated

    # 3. Provider default pricing
    raw_provider_table: Any = {}
    try:
        raw_provider_table = settings.get_provider_default_pricing()
    except Exception as exc:
        logger.warning("Lỗi đọc bảng giá provider mặc định từ settings (%s); fallback {}.", exc)
        raw_provider_table = {}

    provider_table: Dict[str, Any] = {}
    if isinstance(raw_provider_table, dict):
        for raw_k, raw_v in raw_provider_table.items():
            k_norm = str(raw_k or "").strip().lower()
            if k_norm:
                provider_table[k_norm] = raw_v

    if provider_norm:
        provider_keys_to_try = [provider_norm]
        if provider_norm == "chatgpt":
            provider_keys_to_try.append("openai")
        for p_key in provider_keys_to_try:
            if p_key in provider_table:
                validated = _validate_pricing_entry(
                    provider_table[p_key],
                    label=f"provider[{p_key}]",
                )
                if validated is not None:
                    return validated

    # 4. Fallback mặc định toàn cục từ settings.LLM_DEFAULT_*
    default_entry = {
        "input_per_1m_usd": getattr(settings, "LLM_DEFAULT_INPUT_COST_PER_1M_USD", 0.075),
        "output_per_1m_usd": getattr(settings, "LLM_DEFAULT_OUTPUT_COST_PER_1M_USD", 0.30),
        "thinking_per_1m_usd": getattr(settings, "LLM_DEFAULT_THINKING_COST_PER_1M_USD", None),
    }
    validated_default = _validate_pricing_entry(default_entry, label="LLM_DEFAULT")
    if validated_default is not None:
        return validated_default

    return ModelPricing(input_per_1m_usd=0.075, output_per_1m_usd=0.30, thinking_per_1m_usd=None)


def calculate_llm_cost(
    provider: Optional[str],
    model: Optional[str],
    prompt_tokens: int,
    output_tokens: int,
    thinking_tokens: int = 0,
    *,
    thinking_included_in_output: bool = False,
) -> Tuple[float, float]:
    """Tính chi phí ước tính theo USD và VND cho lượt gọi Multi-Provider LLM."""
    provider_norm = (provider or "").strip().lower()
    clean_model = (model or "").strip().lower()
    if clean_model.startswith("models/"):
        clean_model = clean_model[len("models/"):].strip()

    pricing = _resolve_model_pricing(provider_norm, clean_model)
    usd_to_vnd = _get_usd_to_vnd_rate()

    in_toks = max(0, _safe_int(prompt_tokens, 0))
    out_toks = max(0, _safe_int(output_tokens, 0))
    think_toks = max(0, _safe_int(thinking_tokens, 0))

    input_cost = (in_toks / 1_000_000.0) * pricing.input_per_1m_usd
    output_cost = (out_toks / 1_000_000.0) * pricing.output_per_1m_usd

    thinking_cost = 0.0
    if not thinking_included_in_output and think_toks > 0:
        thinking_rate = (
            pricing.thinking_per_1m_usd
            if pricing.thinking_per_1m_usd is not None
            else pricing.output_per_1m_usd
        )
        thinking_cost = (think_toks / 1_000_000.0) * thinking_rate

    cost_usd = input_cost + output_cost + thinking_cost
    cost_vnd = cost_usd * usd_to_vnd
    return cost_usd, cost_vnd


def estimate_tokens_from_chars(text: str) -> int:
    """Ước lượng số token từ chuỗi ký tự (1 token ~ 3.5 ký tự tiếng Việt / tiếng Anh)."""
    if not text:
        return 0
    return max(1, int(len(text) / 3.5))


async def _async_persist_record(record: TelemetryRecord) -> None:
    """Lưu bản ghi vào MongoDB bất đồng bộ trong background task."""
    try:
        from database.db import get_telemetry_collection
        col = get_telemetry_collection()
        await col.insert_one(record.to_dict())
    except Exception as e:
        logger.debug(f"Không thể lưu telemetry vào MongoDB (non-critical): {e}")


def _save_record_fire_and_forget(record: TelemetryRecord) -> None:
    """Ghi log và đẩy việc lưu trữ vào background event loop (không chặn luồng chính)."""
    # 1. Log có cấu trúc ra console / file log
    err_str = f" | error={record.error_message}" if record.error_message else ""
    tenant_display = record.tenant_key or "-"
    logger.info(
        f"[COST_TRACKER] service={record.service} | provider={record.provider} | byok={record.is_byok} "
        f"| tenant={tenant_display} | op={record.operation} | model={record.model} "
        f"| tokens={record.total_tokens} (in={record.prompt_tokens}, out={record.output_tokens}, thinking={record.thinking_tokens}) "
        f"| latency={record.latency_ms:.1f}ms | cost=${record.estimated_cost_usd:.6f} ({record.estimated_cost_vnd:.1f}đ) "
        f"| status={record.status}{err_str}"
    )

    # 2. Lưu vào MongoDB nếu đang có event loop
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_async_persist_record(record))
    except RuntimeError:
        # Nếu đang ở sync thread không có event loop, bỏ qua lưu DB
        pass


def _build_llm_telemetry_record(
    *,
    op_name: str,
    default_model: str,
    client_obj: Any,
    args: Tuple[Any, ...],
    kwargs: Dict[str, Any],
    ctx: Dict[str, Any],
    duration_ms: float,
    prompt_text: str,
    output_text: str,
    error_msg: Optional[str],
) -> TelemetryRecord:
    usage = last_llm_usage.get()
    if isinstance(usage, LLMUsage):
        usage_dict: Dict[str, Any] = usage.to_dict()
    elif isinstance(usage, dict):
        usage_dict = usage
    else:
        usage_dict = {}

    raw_provider = _first_non_empty_str(
        usage_dict.get("provider"),
        getattr(client_obj, "provider", None),
        "google",
    )
    provider_name = (raw_provider or "google").lower()

    if "is_byok" in usage_dict and usage_dict["is_byok"] is not None:
        is_byok = bool(usage_dict["is_byok"])
    else:
        is_byok = bool(getattr(client_obj, "is_byok", False))

    is_multimodal_call = (
        "image_bytes" in kwargs
        or (len(args) > 2 and isinstance(args[2], (bytes, bytearray)))
        or any(isinstance(a, (bytes, bytearray)) for a in args)
    )
    arg_model: Optional[str] = None
    if len(args) > 2 and isinstance(args[2], (bytes, bytearray)):
        if len(args) > 4 and isinstance(args[4], str) and args[4].strip():
            arg_model = args[4]
    elif len(args) > 2 and isinstance(args[2], str) and args[2].strip():
        arg_model = args[2]
    client_default_models = getattr(client_obj, "default_models", None)
    first_default_model = (
        client_default_models[0]
        if isinstance(client_default_models, (list, tuple)) and len(client_default_models) > 0
        else None
    )
    resolved_model = (
        _first_non_empty_str(
            usage_dict.get("model"),
            kwargs.get("model_name"),
            arg_model,
            getattr(client_obj, "model_name", None),
            first_default_model,
            default_model,
            DEFAULT_GEMINI_MODEL,
        )
        or DEFAULT_GEMINI_MODEL
    )

    eff_tenant = _first_non_empty_str(
        ctx.get("tenant_key"),
        getattr(client_obj, "tenant_key", None),
        safe_get_current_tenant_key(),
    )

    service_name = provider_name

    if usage_dict and any(k in usage_dict for k in _TOKEN_USAGE_KEYS):
        p_val = _first_present_int(usage_dict, "input_tokens", "promptTokenCount", "prompt_tokens")
        o_val = _first_present_int(usage_dict, "output_tokens", "candidatesTokenCount", "completion_tokens")
        think_val = _first_present_int(usage_dict, "thinking_tokens", "thoughtsTokenCount")
        if think_val is None:
            details = usage_dict.get("completion_tokens_details")
            if isinstance(details, dict):
                think_val = _first_present_int(details, "reasoning_tokens")

        p_tokens = max(0, p_val) if p_val is not None else 0
        o_tokens = max(0, o_val) if o_val is not None else 0
        think_tokens = max(0, think_val) if think_val is not None else 0

        if (
            "thinking_included_in_output" in usage_dict
            and usage_dict["thinking_included_in_output"] is not None
        ):
            thinking_included = bool(usage_dict["thinking_included_in_output"])
        else:
            thinking_included = provider_name in ("openai", "chatgpt", "custom", "anthropic")

        t_val = _first_present_int(usage_dict, "total_tokens", "totalTokenCount")
        t_tokens = (
            t_val
            if (t_val is not None and t_val > 0)
            else (p_tokens + o_tokens + (0 if thinking_included else think_tokens))
        )
    else:
        p_tokens = estimate_tokens_from_chars(prompt_text)
        o_tokens = estimate_tokens_from_chars(output_text)
        think_tokens = 0
        thinking_included = False
        t_tokens = p_tokens + o_tokens

    cost_usd, cost_vnd = calculate_llm_cost(
        provider_name,
        str(resolved_model),
        p_tokens,
        o_tokens,
        think_tokens,
        thinking_included_in_output=thinking_included,
    )

    return TelemetryRecord(
        service=service_name,
        operation=op_name,
        model=str(resolved_model),
        latency_ms=duration_ms,
        prompt_tokens=p_tokens,
        output_tokens=o_tokens,
        thinking_tokens=think_tokens,
        total_tokens=t_tokens,
        input_chars=len(prompt_text),
        output_chars=len(output_text),
        estimated_cost_usd=cost_usd,
        estimated_cost_vnd=cost_vnd,
        status="success" if not error_msg else "error",
        error_message=error_msg,
        chat_id=ctx.get("chat_id"),
        user_id=ctx.get("user_id"),
        metadata={
            "is_multimodal": is_multimodal_call,
        },
        tenant_key=eff_tenant,
        provider=provider_name,
        is_byok=is_byok,
    )


def _build_jev_telemetry_record(
    *,
    op_name: str,
    kwargs: Dict[str, Any],
    ctx: Dict[str, Any],
    duration_ms: float,
    input_str: str,
    error_msg: Optional[str],
) -> TelemetryRecord:
    jev_meta = last_jev_usage.get()
    jev_meta_dict = jev_meta if isinstance(jev_meta, dict) else {}

    eff_tenant = _first_non_empty_str(
        kwargs.get("tenant_key"),
        jev_meta_dict.get("tenant_key"),
        ctx.get("tenant_key"),
        safe_get_current_tenant_key(),
    )
    jev_is_byok = bool(jev_meta_dict.get("is_byok")) if isinstance(jev_meta, dict) else False

    raw_jev_cost = getattr(settings, "JEV_FLAT_COST_PER_REQUEST", 0.0001)
    try:
        cost_usd = float(raw_jev_cost)
        if not math.isfinite(cost_usd) or cost_usd < 0.0:
            cost_usd = 0.0001
    except (TypeError, ValueError):
        cost_usd = 0.0001

    cost_vnd = cost_usd * _get_usd_to_vnd_rate()

    return TelemetryRecord(
        service="jev",
        operation=op_name,
        model="jev-latest",
        latency_ms=duration_ms,
        prompt_tokens=0,
        output_tokens=0,
        thinking_tokens=0,
        total_tokens=0,
        input_chars=len(input_str),
        output_chars=0,
        estimated_cost_usd=cost_usd,
        estimated_cost_vnd=cost_vnd,
        status="success" if not error_msg else "error",
        error_message=error_msg,
        chat_id=ctx.get("chat_id"),
        user_id=ctx.get("user_id"),
        tenant_key=eff_tenant,
        provider="jev",
        is_byok=jev_is_byok,
    )


F = TypeVar("F", bound=Callable[..., Any])


def track_llm_cost(
    operation: Optional[str] = None,
    default_model: str = DEFAULT_GEMINI_MODEL,
) -> Callable[[F], F]:
    """
    Decorator đo lường chi phí, số lượng token và thời gian phản hồi cho các điểm gọi Multi-Provider LLM.
    Hoạt động trong suốt với cả hàm async lẫn hàm sync.
    """
    def decorator(func: F) -> F:
        op_name = operation or func.__name__

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Reset last usage metadata cho lượt gọi này
                last_llm_usage.set(None)

                client_obj = args[0] if args and not isinstance(args[0], str) else None
                prompt_text = _extract_llm_prompt_text(args, kwargs)
                ctx = current_telemetry_context.get() or {}
                start_time = time.perf_counter()
                error_msg: Optional[str] = None
                output_text = ""

                try:
                    raw_output = await func(*args, **kwargs)
                    if isinstance(raw_output, str):
                        output_text = raw_output
                    return raw_output
                except Exception as e:
                    error_msg = str(e)
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    rec = _build_llm_telemetry_record(
                        op_name=op_name,
                        default_model=default_model,
                        client_obj=client_obj,
                        args=args,
                        kwargs=kwargs,
                        ctx=ctx,
                        duration_ms=duration_ms,
                        prompt_text=prompt_text,
                        output_text=output_text,
                        error_msg=error_msg,
                    )
                    _save_record_fire_and_forget(rec)

            return async_wrapper  # type: ignore

        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                last_llm_usage.set(None)

                client_obj = args[0] if args and not isinstance(args[0], str) else None
                prompt_text = _extract_llm_prompt_text(args, kwargs)
                ctx = current_telemetry_context.get() or {}
                start_time = time.perf_counter()
                error_msg: Optional[str] = None
                output_text = ""

                try:
                    raw_output = func(*args, **kwargs)
                    if isinstance(raw_output, str):
                        output_text = raw_output
                    return raw_output
                except Exception as e:
                    error_msg = str(e)
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    rec = _build_llm_telemetry_record(
                        op_name=op_name,
                        default_model=default_model,
                        client_obj=client_obj,
                        args=args,
                        kwargs=kwargs,
                        ctx=ctx,
                        duration_ms=duration_ms,
                        prompt_text=prompt_text,
                        output_text=output_text,
                        error_msg=error_msg,
                    )
                    _save_record_fire_and_forget(rec)

            return sync_wrapper  # type: ignore

    return decorator


def track_jev_cost(
    operation: Optional[str] = None,
) -> Callable[[F], F]:
    """
    Decorator đo lường độ trễ và chi phí cho các điểm gọi JEV System 1.
    """
    def decorator(func: F) -> F:
        op_name = operation or func.__name__

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                last_jev_usage.set(None)
                input_str = _extract_jev_input_text(args, kwargs)
                ctx = current_telemetry_context.get() or {}
                start_time = time.perf_counter()
                error_msg: Optional[str] = None

                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    error_msg = str(e)
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    rec = _build_jev_telemetry_record(
                        op_name=op_name,
                        kwargs=kwargs,
                        ctx=ctx,
                        duration_ms=duration_ms,
                        input_str=input_str,
                        error_msg=error_msg,
                    )
                    _save_record_fire_and_forget(rec)

            return async_wrapper  # type: ignore

        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                last_jev_usage.set(None)
                input_str = _extract_jev_input_text(args, kwargs)
                ctx = current_telemetry_context.get() or {}
                start_time = time.perf_counter()
                error_msg: Optional[str] = None

                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    error_msg = str(e)
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    rec = _build_jev_telemetry_record(
                        op_name=op_name,
                        kwargs=kwargs,
                        ctx=ctx,
                        duration_ms=duration_ms,
                        input_str=input_str,
                        error_msg=error_msg,
                    )
                    _save_record_fire_and_forget(rec)

            return sync_wrapper  # type: ignore

    return decorator


async def get_cost_telemetry_summary(
    hours: int = 24,
    tenant_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Truy vấn báo cáo tổng hợp chi phí trong khoảng thời gian qua từ MongoDB.
    Hỗ trợ lọc tùy chọn theo tenant_key khi được truyền vào.
    """
    try:
        from database.db import get_telemetry_collection
        col = get_telemetry_collection()

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        match_stage: Dict[str, Any] = {"timestamp": {"$gte": cutoff}}
        if isinstance(tenant_key, str) and tenant_key.strip():
            match_stage["tenant_key"] = tenant_key.strip()

        pipeline = [
            {"$match": match_stage},
            {
                "$group": {
                    "_id": "$service",
                    "total_calls": {"$sum": 1},
                    "success_calls": {"$sum": {"$cond": [{"$eq": ["$status", "success"]}, 1, 0]}},
                    "error_calls": {"$sum": {"$cond": [{"$eq": ["$status", "error"]}, 1, 0]}},
                    "total_tokens": {"$sum": "$total_tokens"},
                    "prompt_tokens": {"$sum": "$prompt_tokens"},
                    "output_tokens": {"$sum": "$output_tokens"},
                    "thinking_tokens": {"$sum": "$thinking_tokens"},
                    "total_cost_usd": {"$sum": "$estimated_cost_usd"},
                    "total_cost_vnd": {"$sum": "$estimated_cost_vnd"},
                    "avg_latency_ms": {"$avg": "$latency_ms"},
                }
            }
        ]

        cursor = col.aggregate(pipeline)
        services_data = await cursor.to_list(length=100)

        total_cost_usd = 0.0
        total_cost_vnd = 0.0
        total_tokens = 0
        total_calls = 0

        by_service: Dict[str, Any] = {}
        for row in services_data:
            svc_name = row["_id"]
            by_service[svc_name] = row
            total_cost_usd += row.get("total_cost_usd", 0.0)
            total_cost_vnd += row.get("total_cost_vnd", 0.0)
            total_tokens += row.get("total_tokens", 0)
            total_calls += row.get("total_calls", 0)

        return {
            "period_hours": hours,
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost_usd, 6),
            "total_cost_vnd": round(total_cost_vnd, 1),
            "by_service": by_service,
        }
    except Exception as e:
        logger.warning(f"Lỗi khi tổng hợp chi phí telemetry: {e}")
        return {
            "period_hours": hours,
            "total_calls": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "total_cost_vnd": 0.0,
            "by_service": {},
            "error": str(e),
        }
