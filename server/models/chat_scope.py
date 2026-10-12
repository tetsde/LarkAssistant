"""
HiLark Chat Scope & Permission Data Model
=========================================
Vị trí: server/models/chat_scope.py

Định nghĩa cấu trúc dữ liệu ánh xạ phân quyền:
  Lark Chat Group (chat_id) <---> WeKnora Knowledge Base (dataset_id)
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from models.memory import get_vietnam_now_iso


class ChatScopeRecord(BaseModel):
    """
    Bản ghi ánh xạ phân quyền dữ liệu giữa nhóm chat Lark và Knowledge Base WeKnora.
    Lưu trong MongoDB collection 'chat_scopes'.
    """
    chat_id: str = Field(..., description="ID duy nhất của Nhóm chat trên Lark (e.g. oc_xxx)")
    chat_name: str = Field(default="", description="Tên nhóm chat hiển thị trên Lark")
    dataset_id: str = Field(..., description="ID Knowledge Base / Dataset trên WeKnora")
    dataset_name: str = Field(default="", description="Tên hiển thị của Knowledge Base trên WeKnora")
    project_tag: Optional[str] = Field(default=None, description="Mã thẻ dự án (nếu có)")
    updated_by: str = Field(default="", description="Lark open_id của người thực hiện cài đặt")
    updated_by_name: str = Field(default="", description="Tên người thực hiện cài đặt")
    created_at: str = Field(default_factory=get_vietnam_now_iso)
    updated_at: str = Field(default_factory=get_vietnam_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
