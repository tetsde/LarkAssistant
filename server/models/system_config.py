"""
HiLark - System Configuration & Lark Base Model
================================================
Vị trí: server/models/system_config.py

Định nghĩa cấu trúc dữ liệu cấu hình hệ thống:
  - Thông tin Lark Bitable (Base) được tự động khởi tạo hoặc liên kết động.
  - Ánh xạ Table ID quản lý danh mục nhóm/dự án (chat_scopes) và chính sách (company_policies).
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from models.memory import get_vietnam_now_iso


class SystemBaseConfigRecord(BaseModel):
    """Bản ghi cấu hình Lark Base Quản trị trong MongoDB collection 'system_config'."""
    config_key: str = Field(default="lark_base_config", description="Khóa cấu hình duy nhất")
    tenant_key: str = Field(default="default", description="Mã tổ chức hoặc tenant trên Lark")
    app_token: str = Field(..., description="App token của Lark Bitable (app_xxx hoặc bascnxxx)")
    app_url: str = Field(..., description="Đường dẫn trực tiếp mở Lark Base trên trình duyệt/Lark Client")
    chat_scope_table_id: str = Field(..., description="Table ID quản lý Danh mục Dự án & Nhóm chat")
    policy_table_id: str = Field(..., description="Table ID quản lý Chính sách & Quy định công ty")
    is_auto_provisioned: bool = Field(default=True, description="Tự động khởi tạo bởi Bot hay cấu hình tay")
    provisioned_by: Optional[str] = Field(default=None, description="Lark Open ID của Admin khởi tạo")
    provisioned_at: str = Field(default_factory=get_vietnam_now_iso)
    updated_at: str = Field(default_factory=get_vietnam_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

