"""
HiLark - Tenant Configuration Models
====================================
Vị trí: server/models/tenant.py

Định nghĩa cấu trúc dữ liệu cho hồ sơ Doanh nghiệp khách thuê (Tenant ISV)
bao gồm ánh xạ WeKnora Multi-Tenant và Lark Base (Bitable).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

from models.memory import get_vietnam_now_iso


class WeKnoraAdminCredentials(BaseModel):
    """Thông tin đăng nhập WeKnora Web dành cho Admin doanh nghiệp (Giải pháp B)."""
    username: str = Field(..., description="Tên đăng nhập WeKnora Web của Admin")
    initial_password: str = Field(..., description="Mật khẩu ban đầu")
    web_url: str = Field(default="http://localhost/login", description="Đường dẫn truy cập WeKnora Web UI")
    email: Optional[str] = Field(default=None, description="Email của Admin")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "username": self.username,
            "initial_password": self.initial_password,
            "web_url": self.web_url,
            "email": self.email,
        }


class TenantConfigRecord(BaseModel):
    """Hồ sơ cấu hình toàn diện cho một Doanh nghiệp khách thuê (Tenant ISV)."""
    tenant_key: str = Field(..., description="Mã định danh doanh nghiệp Lark (header.tenant_key)")
    enterprise_name: Optional[str] = Field(default=None, description="Tên doanh nghiệp")

    # WeKnora Multi-Tenant Mapping
    weknora_tenant_id: Optional[Union[int, str]] = Field(default=None, description="ID Tenant trong WeKnora")
    weknora_url: Optional[str] = Field(default=None, description="Địa chỉ WeKnora Web/API")
    weknora_policy_dataset_id: Optional[str] = Field(default=None, description="KB Chính sách toàn công ty")
    weknora_wiki_dataset_id: Optional[str] = Field(default=None, description="KB Wiki & Daily Digests")
    weknora_default_dataset_id: Optional[str] = Field(default=None, description="KB Dự án mặc định")
    weknora_admin_user: Optional[WeKnoraAdminCredentials] = Field(default=None, description="Tài khoản WeKnora Web")

    # Lark Base (Bitable) Mapping
    bitable_app_token: Optional[str] = Field(default=None, description="App token của file Bitable trên Drive khách")
    bitable_app_url: Optional[str] = Field(default=None, description="Đường link mở Bitable trên Lark")
    chat_scope_table_id: Optional[str] = Field(default=None, description="Table ID bảng Nhóm chat")
    company_policy_table_id: Optional[str] = Field(default=None, description="Table ID bảng Chính sách")

    # Quản trị vòng đời
    status: str = Field(default="active", description="active, paused, uninstalled")
    created_at: str = Field(default_factory=get_vietnam_now_iso)
    updated_at: str = Field(default_factory=get_vietnam_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TenantConfigRecord:
        d = dict(data)
        if "weknora_admin_user" in d and isinstance(d["weknora_admin_user"], dict):
            d["weknora_admin_user"] = WeKnoraAdminCredentials(**d["weknora_admin_user"])
        return cls(**d)
