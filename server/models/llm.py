"""
HiLark - Common LLM Data Models
===============================
Vị trí: server/models/llm.py

Định nghĩa các cấu trúc dữ liệu dùng chung cho tầng gọi Multi-Provider LLM:
  - LLMModelOption: Metadata mô tả một lựa chọn model hiển thị trên UI / catalog
  - LLMRequest: Gói tham số chuẩn hóa cho một lượt gọi LLM (text hoặc multimodal)
  - LLMUsage: Thông số mức tiêu thụ token chuẩn hóa đa nhà cung cấp
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class LLMModelOption(BaseModel):
    """Metadata mô tả một tùy chọn model LLM trong danh mục hệ thống."""
    id: str = Field(..., description="ID định danh model (VD: gemini-flash-latest, gpt-4o-mini)")
    label: str = Field(..., description="Tên hiển thị trên UI")
    family: str = Field(default="latest", description="Nhóm/thế hệ model")
    tier: str = Field(default="standard", description="Phân tầng: recommended | latest | standard | lite | pro")
    is_default: bool = Field(default=False, description="Đánh dấu model mặc định")


@dataclass(frozen=True)
class LLMRequest:
    """Gói tham số bất biến cho một lượt gọi LLM (văn bản thuần hoặc đa phương thức)."""
    prompt: str
    temperature: float
    max_output_tokens: int
    is_json: bool = False
    image_b64: Optional[str] = None
    mime_type: Optional[str] = None

    @property
    def is_multimodal(self) -> bool:
        """Trả về True nếu yêu cầu có đính kèm dữ liệu hình ảnh/multimodal."""
        return bool(self.image_b64)


class LLMUsage(BaseModel):
    """Thống kê số lượng token đã chuẩn hóa sau một lượt gọi LLM."""
    provider: str = Field(default="google", description="Nhà cung cấp LLM chuẩn hóa")
    model: str = Field(default="", description="Tên model thực tế đã gọi")
    is_byok: bool = Field(default=False, description="Lượt gọi dùng key BYOK hay system key")
    input_tokens: int = Field(default=0, ge=0, description="Số token đầu vào")
    output_tokens: int = Field(default=0, ge=0, description="Số token đầu ra")
    thinking_tokens: int = Field(default=0, ge=0, description="Số token suy luận (thoughtsTokenCount / reasoning_tokens)")
    total_tokens: int = Field(default=0, ge=0, description="Tổng số token của lượt gọi")
    thinking_included_in_output: bool = Field(
        default=False,
        description="True nếu provider đã gộp thinking_tokens vào output_tokens (VD: OpenAI)",
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
