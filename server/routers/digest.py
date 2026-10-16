"""
HiLark - Daily Digest Router
============================
Vị trí: server/routers/digest.py

Cung cấp các endpoint REST API:
  - Xem chi tiết bản ghi digest theo ID hoặc bản gần nhất
  - Phê duyệt / Từ chối bản ghi Daily Digest
  - Kích hoạt tổng hợp ngày cho tất cả nhóm chat hoặc 1 nhóm chat
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.digest_service import digest_service

router = APIRouter(prefix="/api/digests", tags=["Daily Digest"])


class ProcessDailyRequest(BaseModel):
    chat_id: str = Field(..., description="ID cuộc trò chuyện Lark (oc_xxx)")
    chat_name: Optional[str] = Field(default="", description="Tên nhóm chat")
    date: Optional[str] = Field(default=None, description="Ngày cần tổng hợp (YYYY-MM-DD), mặc định hôm nay")
    project_tag: Optional[str] = Field(default=None, description="Tag dự án")
    weknora_kb_id: Optional[str] = Field(default=None, description="WeKnora Knowledge Base ID đích")
    require_approval: Optional[bool] = Field(default=None, description="Gửi tin nhắn xin duyệt trước khi nạp KB hay không")


@router.get("/pending/latest")
async def get_latest_pending():
    """Lấy bản ghi Daily Digest gần nhất đang chờ phê duyệt."""
    record = await digest_service.get_latest_pending_approval_digest()
    if not record:
        return {"code": 0, "data": None, "message": "Không có digest nào đang chờ duyệt."}
    return {"code": 0, "data": record.to_dict()}


@router.get("/{digest_id}")
async def get_digest(digest_id: str):
    """Lấy chi tiết một bản ghi Daily Digest từ MongoDB."""
    record = await digest_service.get_digest_by_id(digest_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy digest với id: {digest_id}")
    return {"code": 0, "data": record.to_dict()}


@router.post("/{digest_id}/approve")
async def approve_digest_endpoint(
    digest_id: str,
    dataset_id: Optional[str] = Query(None, description="WeKnora dataset ID"),
):
    """Duyệt Daily Digest: Đẩy bản ghi lên WeKnora và cập nhật trạng thái synced."""
    ok, msg, rec = await digest_service.approve_and_sync_digest(digest_id, dataset_id=dataset_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"code": 0, "message": msg, "data": rec.to_dict() if rec else None}


@router.post("/{digest_id}/reject")
async def reject_digest_endpoint(digest_id: str):
    """Từ chối Daily Digest: Đánh dấu rejected và không nạp vào WeKnora."""
    ok, msg, rec = await digest_service.reject_digest(digest_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"code": 0, "message": msg, "data": rec.to_dict() if rec else None}


@router.post("/run-scheduled")
async def run_scheduled_digests_endpoint(
    date: Optional[str] = Query(None, description="Ngày cần chạy (YYYY-MM-DD)"),
    require_approval: Optional[bool] = Query(None, description="Có gửi tin duyệt trước không"),
):
    """Kích hoạt thủ công luồng chạy định kỳ cuối ngày cho tất cả các nhóm chat hoạt động."""
    records = await digest_service.run_scheduled_daily_digests(
        date=date,
        require_approval=require_approval,
    )
    return {
        "code": 0,
        "message": f"Đã chạy tổng hợp cho {len(records)} nhóm chat.",
        "data": [r.to_dict() for r in records],
    }


@router.post("/process-daily")
async def process_and_sync_daily(req: ProcessDailyRequest):
    """
    Kích hoạt luồng trọn gói cho 1 chat:
      1. Đọc tin nhắn staging từ MongoDB
      2. LLM bóc tách (Quyết định, Cam kết, Trạng thái)
      3. Lưu vào daily_digests trong MongoDB
      4. Nếu require_approval == True: Gửi tin nhắn xin duyệt tới Lark DM, chờ người duyệt OK mới đẩy lên WeKnora.
    """
    digest = await digest_service.process_and_sync_daily_digest(
        chat_id=req.chat_id,
        chat_name=req.chat_name or "",
        date=req.date,
        project_tag=req.project_tag,
        weknora_kb_id=req.weknora_kb_id,
        require_approval=req.require_approval,
    )
    return {
        "code": 0,
        "message": "Đã tổng hợp daily digest thành công",
        "data": digest.to_dict(),
    }
