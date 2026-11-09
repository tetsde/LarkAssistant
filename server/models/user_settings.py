"""
HiLark - User Settings & BYOK Model
===================================
Vị trí: server/models/user_settings.py

Định nghĩa cấu trúc dữ liệu cấu hình người dùng:
  - Tùy chọn Bring Your Own Key (BYOK)
  - Khóa API LLM đã mã hóa AES-256
  - Khung giờ nhận báo cáo Daily Digest
  - Chế độ kiểm duyệt an toàn (HITL Mode)
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, model_validator

from models.memory import get_vietnam_now_iso


class UserSettingsRecord(BaseModel):
    """Bản ghi cấu hình cá nhân của người dùng trên MongoDB collection 'user_settings'."""
    open_id: str = Field(..., description="Lark Open ID của người dùng (ou_xxx)")
    tenant_key: Optional[str] = Field(default=None, description="Mã định danh doanh nghiệp (Multi-Tenant ISV)")
    user_name: Optional[str] = Field(default=None, description="Tên người dùng trên Lark")
    is_byok_enabled: bool = Field(default=False, description="Đang kích hoạt BYOK hay dùng System Key")
    llm_mode: str = Field(default="system", description="Chế độ LLM: system | byok")
    llm_provider: str = Field(default="google", description="Nhà cung cấp LLM: google, openai, anthropic, custom")
    encrypted_llm_api_key: Optional[str] = Field(default=None, description="API Key LLM đã mã hóa AES-256")
    masked_llm_api_key: Optional[str] = Field(default=None, description="Key LLM dạng ẩn (sk-•••••••• hoặc AIzaSy••••••••)")
    llm_base_url: Optional[str] = Field(default=None, description="Base URL tùy chỉnh cho LLM Provider")
    llm_model: Optional[str] = Field(default=None, description="Tên mô hình LLM cụ thể")
    llm_timeout: float = Field(default=60.0, description="Thời gian chờ tối đa (giây)")
    is_jev_byok_enabled: bool = Field(default=False, description="Kích hoạt BYOK cho JEV System 1 Classifier hay dùng System Key")
    jev_mode: str = Field(default="system", description="Chế độ JEV: system | byok")
    encrypted_jev_api_key: Optional[str] = Field(default=None, description="JEV API Key đã mã hóa AES-256")
    masked_jev_api_key: Optional[str] = Field(default=None, description="JEV API Key dạng ẩn")
    digest_schedule_time: str = Field(default="18:00", description="Khung giờ nhận Daily Digest (HH:MM)")
    hitl_mode_enabled: bool = Field(default=True, description="Bật chế độ duyệt an toàn HITL cho draft và digest")
    policy_sync_interval_seconds: int = Field(default=3600, description="Chu kỳ quét định kỳ chính sách doanh nghiệp (giây)")
    created_at: str = Field(default_factory=get_vietnam_now_iso)
    updated_at: str = Field(default_factory=get_vietnam_now_iso)

    @model_validator(mode="before")
    @classmethod
    def _strip_null_modes(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cleaned = dict(data)
            for key in ("llm_mode", "jev_mode"):
                if key in cleaned and cleaned[key] is None:
                    cleaned.pop(key)
            return cleaned
        return data

    @model_validator(mode="after")
    def _sync_byok_modes(self) -> "UserSettingsRecord":
        fields_set = self.model_fields_set

        # 1. Đồng bộ 2 chiều giữa is_byok_enabled <-> llm_mode
        llm_mode_norm = (self.llm_mode or "system").strip().lower()
        if llm_mode_norm not in ("system", "byok"):
            llm_mode_norm = "byok" if self.is_byok_enabled else "system"

        if "llm_mode" in fields_set and "is_byok_enabled" not in fields_set:
            self.llm_mode = llm_mode_norm
            self.is_byok_enabled = llm_mode_norm == "byok"
        elif "is_byok_enabled" in fields_set and "llm_mode" not in fields_set:
            self.llm_mode = "byok" if self.is_byok_enabled else "system"
        elif "llm_mode" in fields_set and "is_byok_enabled" in fields_set:
            if self.is_byok_enabled or llm_mode_norm == "byok":
                self.is_byok_enabled = True
                self.llm_mode = "byok"
            else:
                self.is_byok_enabled = False
                self.llm_mode = "system"
        else:
            self.llm_mode = "byok" if self.is_byok_enabled else "system"

        # 2. Đồng bộ 2 chiều giữa is_jev_byok_enabled <-> jev_mode
        jev_mode_norm = (self.jev_mode or "system").strip().lower()
        if jev_mode_norm not in ("system", "byok"):
            jev_mode_norm = "byok" if self.is_jev_byok_enabled else "system"

        if "jev_mode" in fields_set and "is_jev_byok_enabled" not in fields_set:
            self.jev_mode = jev_mode_norm
            self.is_jev_byok_enabled = jev_mode_norm == "byok"
        elif "is_jev_byok_enabled" in fields_set and "jev_mode" not in fields_set:
            self.jev_mode = "byok" if self.is_jev_byok_enabled else "system"
        elif "jev_mode" in fields_set and "is_jev_byok_enabled" in fields_set:
            if self.is_jev_byok_enabled or jev_mode_norm == "byok":
                self.is_jev_byok_enabled = True
                self.jev_mode = "byok"
            else:
                self.is_jev_byok_enabled = False
                self.jev_mode = "system"
        else:
            self.jev_mode = "byok" if self.is_jev_byok_enabled else "system"

        return self

    def resolved_llm_model(self) -> str:
        from services.ai.model_catalog import get_default_model

        return (self.llm_model or "").strip() or get_default_model(self.llm_provider)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

