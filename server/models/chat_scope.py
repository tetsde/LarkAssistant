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
    dataset_id: str = Field(default="", description="ID Knowledge Base / Dataset trên WeKnora")
    dataset_name: str = Field(default="", description="Tên hiển thị của Knowledge Base trên WeKnora")
    project_tag: Optional[str] = Field(default=None, description="Mã thẻ dự án (nếu có)")
    status: str = Field(default="Hoạt động", description="Trạng thái nhóm trên Lark Base: Hoạt động / Tạm dừng...")
    forbidden_labels: list[str] = Field(default_factory=list, description="Danh sách nhãn cấm xem (Ngân sách, Chi phí...)")
    allowed_labels: list[str] = Field(default_factory=list, description="Danh sách nhãn được phép xem")
    documents: list[Dict[str, Any]] = Field(default_factory=list, description="Danh sách tài liệu file đính kèm")
    knowledge_ids: list[str] = Field(default_factory=list, description="Danh sách knowledge_id tài liệu trên WeKnora")
    record_id: Optional[str] = Field(default=None, description="Record ID trên Lark Base")
    updated_by: str = Field(default="", description="Lark open_id của người thực hiện cài đặt")
    updated_by_name: str = Field(default="", description="Tên người thực hiện cài đặt")
    created_at: str = Field(default_factory=get_vietnam_now_iso)
    updated_at: str = Field(default_factory=get_vietnam_now_iso)

    @property
    def is_active(self) -> bool:
        """Kiểm tra nhóm có đang ở trạng thái Hoạt động hay không."""
        if not self.status:
            return True
        st = self.status.strip().lower()
        return st in ("hoạt động", "active", "enable", "enabled", "true", "1")

    def to_dict(self) -> Dict[str, Any]:
        d = self.model_dump()
        d["is_active"] = self.is_active
        return d

