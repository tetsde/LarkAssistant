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
    provider: Optional[str] = Field(default="google", description="Nhà cung cấp: google, openai, chatgpt, anthropic, custom, jev")
    base_url: Optional[str] = Field(default=None, description="Base URL tùy chỉnh")
    model_name: Optional[str] = Field(default=None, description="Tên mô hình")
    timeout: Optional[float] = Field(default=30.0, description="Thời gian chờ timeout (giây)")


class SaveSettingsRequest(BaseModel):
    """Payload lưu trữ cấu hình người dùng từ Onboarding Wizard."""
    open_id: str = Field(..., description="Lark Open ID của người dùng (ou_xxx)")
    user_name: Optional[str] = Field(default=None, description="Tên người dùng")
    is_byok_enabled: bool = Field(default=False, description="Kích hoạt BYOK hay không")
    raw_llm_key: Optional[str] = Field(default=None, description="Khóa API LLM mới (nếu có)")
    llm_provider: Optional[str] = Field(default="google", description="Nhà cung cấp LLM: google, openai, anthropic, custom")
    llm_base_url: Optional[str] = Field(default=None, description="Base URL tùy chỉnh")
    llm_model: Optional[str] = Field(default=None, description="Tên mô hình")
    llm_timeout: Optional[float] = Field(default=60.0, description="Timeout (giây)")
    is_jev_byok_enabled: bool = Field(default=False, description="Kích hoạt BYOK cho JEV System 1 Classifier hay không")
    raw_jev_key: Optional[str] = Field(default=None, description="Khóa API JEV mới (nếu có)")
    digest_schedule_time: str = Field(default="18:00", description="Giờ nhận Daily Digest")
    hitl_mode_enabled: bool = Field(default=True, description="Bật chế độ duyệt an toàn HITL")
    policy_sync_interval_seconds: Optional[int] = Field(default=3600, description="Chu kỳ quét định kỳ chính sách doanh nghiệp (giây)")
    tenant_key: Optional[str] = Field(default=None, description="Mã định danh tenant nếu có")
    app_id: Optional[str] = Field(default=None, description="Lark App ID (cli_xxx)")
    app_secret: Optional[str] = Field(default=None, description="Lark App Secret")
    custom_mongo_url: Optional[str] = Field(default=None, description="MongoDB Connection URI tùy chọn")


class ProvisionBaseRequest(BaseModel):
    """Payload yêu cầu tự động khởi tạo Lark Base Quản trị Doanh nghiệp."""
    admin_open_id: Optional[str] = Field(default=None, description="Lark Open ID của Admin")
    tenant_key: Optional[str] = Field(default=None, description="Mã định danh tenant nếu có")


class ProvisionWeKnoraRequest(BaseModel):
    """Payload yêu cầu khởi tạo không gian tri thức WeKnora đa doanh nghiệp."""
    tenant_key: Optional[str] = Field(default=None, description="Mã định danh tenant")
    enterprise_name: Optional[str] = Field(default=None, description="Tên doanh nghiệp")
    admin_open_id: Optional[str] = Field(default=None, description="Lark Open ID của Admin")
    admin_email: Optional[str] = Field(default=None, description="Email của Admin")


class TestBotCredentialsRequest(BaseModel):
    """Payload kiểm tra tính hợp lệ của cặp App ID và App Secret với Lark Open Platform."""
    app_id: str = Field(..., description="Mã ứng dụng Lark (bắt đầu bằng cli_)")
    app_secret: str = Field(..., description="Khóa bí mật của ứng dụng Lark")


class RegisterLarkAppRequest(TestBotCredentialsRequest):
    """Đăng ký Custom App vào registry mà không ghi đè cấu hình global."""
    verification_token: Optional[str] = Field(default="", description="Verification Token của App event webhook")
    encrypt_key: Optional[str] = Field(default="", description="Encrypt Key của App event webhook")


class SaveBotConfigRequest(BaseModel):
    """Payload lưu cấu hình Bot theo App/Tenant (không ghi đè cấu hình global)."""
    app_id: str = Field(..., description="Mã ứng dụng Lark (cli_xxx)")
    app_secret: Optional[str] = Field(default=None, description="Khóa bí mật của ứng dụng Lark")
    verification_token: Optional[str] = Field(default=None, description="Verification Token của App event webhook")
    encrypt_key: Optional[str] = Field(default=None, description="Encrypt Key của App event webhook")
    tenant_key: Optional[str] = Field(default=None, description="Mã định danh tenant nếu đã xác định")
    custom_mongo_url: Optional[str] = Field(default=None, description="URI MongoDB tùy chọn")


class TestMongoRequest(BaseModel):
    """Payload kiểm tra kết nối tới cơ sở dữ liệu MongoDB."""
    mongo_url: str = Field(..., description="URI kết nối MongoDB (mongodb:// hoặc mongodb+srv://)")
    mongo_db: Optional[str] = Field(default="LarkAssistant", description="Tên database")

