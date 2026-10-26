"""
HiLark Chat Scope & Permission Router
=====================================
Vị trí: server/routers/scope.py

Cung cấp API quản lý phân quyền dữ liệu nhóm chat <---> Knowledge Base WeKnora.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.config import settings
from models.chat_scope import ChatScopeRecord
from services.auth_service import scope_service

router = APIRouter(prefix="/api/v1/scopes", tags=["Chat Scopes & Permissions"])


class SetScopeRequest(BaseModel):
    chat_id: str = Field(..., description="Lark chat_id (e.g. oc_xxx)")
    dataset_id: str = Field(..., description="WeKnora Knowledge Base ID")
    chat_name: Optional[str] = Field(default="", description="Tên nhóm chat hiển thị")
    project_tag: Optional[str] = Field(default=None, description="Mã dự án (nếu có)")
    operator_open_id: Optional[str] = Field(default=None, description="Lark open_id của người thực hiện")
    operator_name: Optional[str] = Field(default=None, description="Tên người thực hiện")


@router.get("", response_model=List[Dict[str, Any]], summary="Danh sách toàn bộ ánh xạ Chat <-> KB")
async def list_scopes():
    """Lấy danh sách tất cả các nhóm chat đã được gán Knowledge Base riêng trong MongoDB."""
    scopes = await scope_service.list_all_scopes()
    return [s.to_dict() for s in scopes]


@router.get("/{chat_id}", summary="Lấy thông tin Knowledge Base của một nhóm chat")
async def get_scope(chat_id: str):
    """Tra cứu Knowledge Base của một nhóm chat (nếu chưa gán riêng sẽ trả về KB mặc định)."""
    scope = await scope_service.get_scope_by_chat_id(chat_id)
    if scope:
        return {
            "configured": True,
            "scope": scope.to_dict(),
        }

    default_id, default_name = await scope_service.get_kb_info_for_chat(None)
    return {
        "configured": False,
        "dataset_id": default_id,
        "dataset_name": default_name,
        "message": "Nhóm chat này đang sử dụng Knowledge Base mặc định.",
    }


@router.post("", summary="Thiết lập liên kết Nhóm chat với Knowledge Base (Có kiểm tra quyền)")
async def set_scope(req: SetScopeRequest):
    """
    Liên kết nhóm chat với một Knowledge Base WeKnora.
    Kiểm tra quyền Admin và xác thực dataset_id trên WeKnora trước khi lưu vào MongoDB.
    """
    op_id = req.operator_open_id or settings.LARK_USER_OPEN_ID
    op_name = req.operator_name or "API Admin"

    ok, msg, rec = await scope_service.set_chat_kb(
        chat_id=req.chat_id,
        dataset_id=req.dataset_id,
        operator_open_id=op_id,
        operator_name=op_name,
        chat_name=req.chat_name or "",
        project_tag=req.project_tag,
    )

    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    return {
        "success": True,
        "message": msg,
        "data": rec.to_dict() if rec else None,
    }


@router.delete("/{chat_id}", summary="Gỡ bỏ Knowledge Base riêng của nhóm chat")
async def delete_scope(
    chat_id: str,
    operator_open_id: Optional[str] = Query(None, description="Open ID người thực hiện"),
):
    """Gỡ bỏ Knowledge Base riêng của nhóm chat, đưa nhóm về dùng Knowledge Base mặc định."""
    op_id = operator_open_id or settings.LARK_USER_OPEN_ID
    ok, msg = await scope_service.reset_chat_kb(chat_id=chat_id, operator_open_id=op_id)
    if not ok:
        raise HTTPException(status_code=403, detail=msg)

    return {
        "success": True,
        "message": msg,
    }
