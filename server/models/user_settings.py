"""
HiLark - User Settings & BYOK Model
===================================
Vị trí: server/models/user_settings.py

Định nghĩa cấu trúc dữ liệu cấu hình người dùng:
  - Tùy chọn Bring Your Own Key (BYOK)
  - Khóa API Gemini đã mã hóa AES-256
  - Khung giờ nhận báo cáo Daily Digest
  - Chế độ kiểm duyệt an toàn (HITL Mode)
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from models.memory import get_vietnam_now_iso


class UserSettingsRecord(BaseModel):
    """Bản ghi cấu hình cá nhân của người dùng trên MongoDB collection 'user_settings'."""
    open_id: str = Field(..., description="Lark Open ID của người dùng (ou_xxx)")
    tenant_key: Optional[str] = Field(default=None, description="Mã định danh doanh nghiệp (Multi-Tenant ISV)")
    user_name: Optional[str] = Field(default=None, description="Tên người dùng trên Lark")
    is_byok_enabled: bool = Field(default=False, description="Đang kích hoạt BYOK hay dùng System Key")
    llm_provider: str = Field(default="google", description="Nhà cung cấp LLM: google, openai, anthropic, custom")
    encrypted_gemini_api_key: Optional[str] = Field(default=None, description="API Key đã mã hóa AES-256")
    masked_gemini_api_key: Optional[str] = Field(default=None, description="Key dạng ẩn (sk-•••••••• hoặc AIzaSy••••••••)")
    llm_base_url: Optional[str] = Field(default=None, description="Base URL tùy chỉnh cho LLM Provider")
    llm_model: Optional[str] = Field(default=None, description="Tên mô hình LLM cụ thể")
    llm_timeout: float = Field(default=60.0, description="Thời gian chờ tối đa (giây)")
    digest_schedule_time: str = Field(default="18:00", description="Khung giờ nhận Daily Digest (HH:MM)")
    hitl_mode_enabled: bool = Field(default=True, description="Bật chế độ duyệt an toàn HITL cho draft và digest")
    created_at: str = Field(default_factory=get_vietnam_now_iso)
    updated_at: str = Field(default_factory=get_vietnam_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

