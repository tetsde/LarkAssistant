"""
HiLark Cost Telemetry & Tracking Decorators
==========================================
Vị trí: server/decorators/cost_telemetry.py

Cung cấp các Decorator đo lường chi phí, độ trễ và số lượng token cho:
  1. @track_llm_cost: Các điểm gọi Gemini LLM (generate_text_async, generate_json_async, generate_multimodal_async...)
  2. @track_jev_cost: Các điểm gọi JEV System 1 Gatekeeper (classify_message, classify_thread_decision...)

Đặc điểm kiến trúc:
  - Tách biệt độc lập trong thư mục `server/decorators/`, không làm ô nhiễm business logic của services.
  - Hỗ trợ cả hàm bất đồng bộ (async def) lẫn hàm đồng bộ (def).
  - Tự động trích xuất chính xác token từ usageMetadata của Gemini hoặc ước lượng heuristic nếu API không trả về.
  - Ghi log có cấu trúc [COST_TRACKER] và lưu trữ bất đồng bộ (non-blocking) vào MongoDB `cost_telemetry`.
  - Tuyệt đối không làm thay đổi giá trị trả về hoặc nuốt ngoại lệ nghiệp vụ.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import functools
import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar, Union
import uuid

logger = logging.getLogger("hilark.telemetry")

# ContextVar lưu trữ ngữ cảnh gọi (chat_id, user_id, request_id)
current_telemetry_context: ContextVar[Dict[str, Any]] = ContextVar(
    "current_telemetry_context", default={}
)

# ContextVar nhận usageMetadata từ response thực tế của Gemini API
last_llm_usage: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "last_llm_usage", default=None
)

# Tỷ giá quy đổi tạm thời USD -> VND
USD_TO_VND_RATE = 25400.0

# Bảng giá chuẩn Gemini Flash (USD / 1.000.000 tokens)
# Input: $0.075 / 1M tokens ($0.000000075 / token)
# Output: $0.30 / 1M tokens ($0.00000030 / token)
GEMINI_FLASH_INPUT_COST_PER_TOKEN = 0.075 / 1_000_000
GEMINI_FLASH_OUTPUT_COST_PER_TOKEN = 0.30 / 1_000_000

# JEV System 1 chi phí ước tính ($0 token LLM cost, flat rate $0.0001 / request)
JEV_FLAT_COST_PER_REQUEST = 0.0001


def _get_vietnam_now_iso() -> str:
    from zoneinfo import ZoneInfo
    try:
        vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
        return datetime.now(vn_tz).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


@dataclass
class TelemetryRecord:
    """Bản ghi đo lường chi phí và hiệu năng một lần gọi API."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=_get_vietnam_now_iso)
    service: str = "gemini"  # "gemini" hoặc "jev"
    operation: str = ""
    model: str = ""
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    candidates_tokens: int = 0
    total_tokens: int = 0
    input_chars: int = 0
    output_chars: int = 0
    estimated_cost_usd: float = 0.0
    estimated_cost_vnd: float = 0.0
    status: str = "success"  # "success" hoặc "error"
    error_message: Optional[str] = None
    chat_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def calculate_gemini_cost(prompt_tokens: int, candidates_tokens: int, model_name: str = "") -> Tuple[float, float]:
    """Tính chi phí ước tính theo USD và VND cho lượt gọi Gemini."""
    cost_usd = (prompt_tokens * GEMINI_FLASH_INPUT_COST_PER_TOKEN) + (
        candidates_tokens * GEMINI_FLASH_OUTPUT_COST_PER_TOKEN
    )
    cost_vnd = cost_usd * USD_TO_VND_RATE
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
    logger.info(
        f"[COST_TRACKER] service={record.service} | op={record.operation} | model={record.model} "
        f"| tokens={record.total_tokens} (in={record.prompt_tokens}, out={record.candidates_tokens}) "
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


F = TypeVar("F", bound=Callable[..., Any])


def track_llm_cost(
    operation: Optional[str] = None,
    default_model: str = "gemini-2.5-flash",
) -> Callable[[F], F]:
    """
    Decorator đo lường chi phí, số lượng token và thời gian phản hồi cho các điểm gọi Gemini LLM.
    Hoạt động trong suốt với cả hàm async lẫn hàm sync.
    """
    def decorator(func: F) -> F:
        op_name = operation or func.__name__

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Reset last usage metadata cho lượt gọi này
                last_llm_usage.set(None)

                # Thu thập thông tin input
                prompt_text = ""
                if len(args) > 1 and isinstance(args[1], str):
                    prompt_text = args[1]
                elif "prompt" in kwargs and isinstance(kwargs["prompt"], str):
                    prompt_text = kwargs["prompt"]
                elif len(args) > 0 and isinstance(args[0], str):
                    prompt_text = args[0]

                model_name = kwargs.get("model_name") or default_model
                if not model_name and len(args) > 2 and isinstance(args[2], str):
                    model_name = args[2]

                ctx = current_telemetry_context.get()
                start_time = time.perf_counter()
                error_msg: Optional[str] = None
                raw_output: Any = None
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

                    # Trích xuất số token
                    usage = last_llm_usage.get()
                    if usage and isinstance(usage, dict):
                        p_tokens = int(usage.get("promptTokenCount") or 0)
                        c_tokens = int(usage.get("candidatesTokenCount") or 0)
                        t_tokens = int(usage.get("totalTokenCount") or (p_tokens + c_tokens))
                    else:
                        p_tokens = estimate_tokens_from_chars(prompt_text)
                        c_tokens = estimate_tokens_from_chars(output_text)
                        t_tokens = p_tokens + c_tokens

                    cost_usd, cost_vnd = calculate_gemini_cost(p_tokens, c_tokens, model_name)

                    rec = TelemetryRecord(
                        service="gemini",
                        operation=op_name,
                        model=str(model_name),
                        latency_ms=duration_ms,
                        prompt_tokens=p_tokens,
                        candidates_tokens=c_tokens,
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
                            "is_multimodal": "image_bytes" in kwargs or any(isinstance(a, (bytes, bytearray)) for a in args),
                        },
                    )
                    _save_record_fire_and_forget(rec)

            return async_wrapper  # type: ignore

        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                last_llm_usage.set(None)

                prompt_text = ""
                if len(args) > 1 and isinstance(args[1], str):
                    prompt_text = args[1]
                elif "prompt" in kwargs and isinstance(kwargs["prompt"], str):
                    prompt_text = kwargs["prompt"]
                elif len(args) > 0 and isinstance(args[0], str):
                    prompt_text = args[0]

                model_name = kwargs.get("model_name") or default_model
                if not model_name and len(args) > 2 and isinstance(args[2], str):
                    model_name = args[2]

                ctx = current_telemetry_context.get()
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

                    usage = last_llm_usage.get()
                    if usage and isinstance(usage, dict):
                        p_tokens = int(usage.get("promptTokenCount") or 0)
                        c_tokens = int(usage.get("candidatesTokenCount") or 0)
                        t_tokens = int(usage.get("totalTokenCount") or (p_tokens + c_tokens))
                    else:
                        p_tokens = estimate_tokens_from_chars(prompt_text)
                        c_tokens = estimate_tokens_from_chars(output_text)
                        t_tokens = p_tokens + c_tokens

                    cost_usd, cost_vnd = calculate_gemini_cost(p_tokens, c_tokens, model_name)

                    rec = TelemetryRecord(
                        service="gemini",
                        operation=op_name,
                        model=str(model_name),
                        latency_ms=duration_ms,
                        prompt_tokens=p_tokens,
                        candidates_tokens=c_tokens,
                        total_tokens=t_tokens,
                        input_chars=len(prompt_text),
                        output_chars=len(output_text),
                        estimated_cost_usd=cost_usd,
                        estimated_cost_vnd=cost_vnd,
                        status="success" if not error_msg else "error",
                        error_message=error_msg,
                        chat_id=ctx.get("chat_id"),
                        user_id=ctx.get("user_id"),
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
                input_str = ""
                if len(args) > 1 and isinstance(args[1], str):
                    input_str = args[1]
                elif "message" in kwargs:
                    input_str = str(kwargs["message"])
                elif "query" in kwargs:
                    input_str = str(kwargs["query"])

                ctx = current_telemetry_context.get()
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
                    cost_usd = JEV_FLAT_COST_PER_REQUEST
                    cost_vnd = cost_usd * USD_TO_VND_RATE

                    rec = TelemetryRecord(
                        service="jev",
                        operation=op_name,
                        model="jev-latest",
                        latency_ms=duration_ms,
                        prompt_tokens=0,
                        candidates_tokens=0,
                        total_tokens=0,
                        input_chars=len(input_str),
                        output_chars=0,
                        estimated_cost_usd=cost_usd,
                        estimated_cost_vnd=cost_vnd,
                        status="success" if not error_msg else "error",
                        error_message=error_msg,
                        chat_id=ctx.get("chat_id"),
                        user_id=ctx.get("user_id"),
                    )
                    _save_record_fire_and_forget(rec)

            return async_wrapper  # type: ignore

        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                input_str = ""
                if len(args) > 1 and isinstance(args[1], str):
                    input_str = args[1]
                elif "message" in kwargs:
                    input_str = str(kwargs["message"])

                ctx = current_telemetry_context.get()
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
                    cost_usd = JEV_FLAT_COST_PER_REQUEST
                    cost_vnd = cost_usd * USD_TO_VND_RATE

                    rec = TelemetryRecord(
                        service="jev",
                        operation=op_name,
                        model="jev-latest",
                        latency_ms=duration_ms,
                        prompt_tokens=0,
                        candidates_tokens=0,
                        total_tokens=0,
                        input_chars=len(input_str),
                        output_chars=0,
                        estimated_cost_usd=cost_usd,
                        estimated_cost_vnd=cost_vnd,
                        status="success" if not error_msg else "error",
                        error_message=error_msg,
                        chat_id=ctx.get("chat_id"),
                        user_id=ctx.get("user_id"),
                    )
                    _save_record_fire_and_forget(rec)

            return sync_wrapper  # type: ignore

    return decorator


async def get_cost_telemetry_summary(hours: int = 24) -> Dict[str, Any]:
    """
    Truy vấn báo cáo tổng hợp chi phí trong khoảng thời gian qua từ MongoDB.
    """
    try:
        from database.db import get_telemetry_collection
        from datetime import timedelta
        col = get_telemetry_collection()

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        pipeline = [
            {"$match": {"timestamp": {"$gte": cutoff}}},
            {
                "$group": {
                    "_id": "$service",
                    "total_calls": {"$sum": 1},
                    "success_calls": {"$sum": {"$cond": [{"$eq": ["$status", "success"]}, 1, 0]}},
                    "error_calls": {"$sum": {"$cond": [{"$eq": ["$status", "error"]}, 1, 0]}},
                    "total_tokens": {"$sum": "$total_tokens"},
                    "prompt_tokens": {"$sum": "$prompt_tokens"},
                    "candidates_tokens": {"$sum": "$candidates_tokens"},
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
