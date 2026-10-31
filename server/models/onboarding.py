"""
HiLark - Onboarding & Screen Guide Models
=========================================
Vị trí: server/models/onboarding.py

Chứa các Pydantic models phục vụ:
  - Kiểm tra kết nối LLM Provider (TestKeyRequest)
  - Lưu cài đặt cá nhân hóa / BYOK (SaveSettingsRequest)
  - Yêu cầu tự động tạo Lark Base (ProvisionBaseRequest)
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class TestKeyRequest(BaseModel):
    """Payload kiểm tra kết nối API Key và đo độ trễ mạng."""
    api_key: str = Field(..., description="API Key cần kiểm tra")
    provider: Optional[str] = Field(default="google", description="Nhà cung cấp: google, openai, chatgpt, anthropic, custom")
    base_url: Optional[str] = Field(default=None, description="Base URL tùy chỉnh")
    model_name: Optional[str] = Field(default=None, description="Tên mô hình")
    timeout: Optional[float] = Field(default=30.0, description="Thời gian chờ timeout (giây)")


class SaveSettingsRequest(BaseModel):
    """Payload lưu trữ cấu hình người dùng từ Onboarding Wizard."""
    open_id: str = Field(..., description="Lark Open ID của người dùng (ou_xxx)")
    user_name: Optional[str] = Field(default=None, description="Tên người dùng")
    is_byok_enabled: bool = Field(default=False, description="Kích hoạt BYOK hay không")
    raw_gemini_key: Optional[str] = Field(default=None, description="Khóa API mới (nếu có)")
    llm_provider: Optional[str] = Field(default="google", description="Nhà cung cấp LLM: google, openai, anthropic, custom")
    llm_base_url: Optional[str] = Field(default=None, description="Base URL tùy chỉnh")
    llm_model: Optional[str] = Field(default=None, description="Tên mô hình")
    llm_timeout: Optional[float] = Field(default=60.0, description="Timeout (giây)")
    digest_schedule_time: str = Field(default="18:00", description="Giờ nhận Daily Digest")
    hitl_mode_enabled: bool = Field(default=True, description="Bật chế độ duyệt an toàn HITL")
    app_id: Optional[str] = Field(default=None, description="Lark App ID (cli_xxx)")
    app_secret: Optional[str] = Field(default=None, description="Lark App Secret")
    custom_mongo_url: Optional[str] = Field(default=None, description="MongoDB Connection URI tùy chọn")


class ProvisionBaseRequest(BaseModel):
    """Payload yêu cầu tự động khởi tạo Lark Base Quản trị Doanh nghiệp."""
    admin_open_id: Optional[str] = Field(default=None, description="Lark Open ID của Admin")


class TestBotCredentialsRequest(BaseModel):
    """Payload kiểm tra tính hợp lệ của cặp App ID và App Secret với Lark Open Platform."""
    app_id: str = Field(..., description="Mã ứng dụng Lark (bắt đầu bằng cli_)")
    app_secret: str = Field(..., description="Khóa bí mật của ứng dụng Lark")


class SaveBotConfigRequest(BaseModel):
    """Payload lưu cấu hình Bot và kết nối MongoDB tùy chọn."""
    app_id: str = Field(..., description="Mã ứng dụng Lark (cli_xxx)")
    app_secret: Optional[str] = Field(default=None, description="Khóa bí mật của ứng dụng Lark")
    custom_mongo_url: Optional[str] = Field(default=None, description="URI MongoDB tùy chọn")


class TestMongoRequest(BaseModel):
    """Payload kiểm tra kết nối tới cơ sở dữ liệu MongoDB."""
    mongo_url: str = Field(..., description="URI kết nối MongoDB (mongodb:// hoặc mongodb+srv://)")
    mongo_db: Optional[str] = Field(default="LarkAssistant", description="Tên database")

