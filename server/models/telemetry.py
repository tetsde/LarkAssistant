"""
HiLark - Telemetry & Model Pricing Models
=========================================
Vị trí: server/models/telemetry.py

Định nghĩa cấu trúc dữ liệu cho định giá token theo model và bản ghi
telemetry đo lường chi phí, độ trễ, token cho các lượt gọi LLM & JEV.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional
import uuid
from pydantic import BaseModel, Field, model_validator

from models.memory import get_vietnam_now_iso


class ModelPricing(BaseModel):
    """Đơn giá token (USD trên mỗi 1 triệu tokens) cho một model LLM."""
    input_per_1m_usd: float = Field(..., ge=0.0, description="Đơn giá USD cho 1M input tokens")
    output_per_1m_usd: float = Field(..., ge=0.0, description="Đơn giá USD cho 1M output tokens")
    thinking_per_1m_usd: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Đơn giá USD cho 1M thinking tokens (None = dùng output_per_1m_usd)",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_short_pricing_keys(cls, data: Any) -> Any:
        """Hỗ trợ nạp cấu hình JSON ngắn gọn ('input', 'output', 'thinking') từ .env."""
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        key_mapping = (
            ("input", "input_per_1m_usd"),
            ("output", "output_per_1m_usd"),
            ("thinking", "thinking_per_1m_usd"),
        )
        for short_key, full_key in key_mapping:
            if short_key in normalized:
                short_val = normalized.pop(short_key)
                if full_key not in normalized:
                    normalized[full_key] = short_val
        return normalized


@dataclass
class TelemetryRecord:
    """Bản ghi đo lường chi phí, token và hiệu năng một lần gọi API."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=get_vietnam_now_iso)
    service: str = "google"  # "google", "openai", "anthropic", "custom" hoặc "jev"
    operation: str = ""
    model: str = ""
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
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
    tenant_key: Optional[str] = None
    provider: str = "google"
    is_byok: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
