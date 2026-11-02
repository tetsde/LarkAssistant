"""
HiLark - Daily Digest Router
============================
Vị trí: server/routers/digest.py

📌 GHI CHÚ QUAN TRỌNG (DÀNH CHO DEVELOPER / TÍCH HỢP):
------------------------------------------------------
1. LUỒNG CHÍNH (User-Facing):
   - Người dùng cuối (Chủ nhân / Quản trị viên) thao tác DUYỆT / HỦY / XEM Daily Digest 
     hoàn toàn trực tiếp qua tin nhắn Lark DM 1-1 với Bot (Lệnh: "duyệt digest", "hủy digest").
   - KHÔNG bắt buộc và KHÔNG cần phải gọi các REST API này trong luồng vận hành thực tế hàng ngày.

2. MỤC ĐÍCH CỦA CÁC ENDPOINT REST API DƯỚI ĐÂY:
   - Developer Testing: Test nhanh luồng trích xuất, xem trước hoặc kích hoạt tổng hợp bằng 
     Postman / cURL / Swagger Docs (/docs) mà không cần đợi tới 23:00 đêm.
   - External Triggers / Cronjobs: Cho phép các hệ thống lập lịch bên ngoài (Linux Crontab, 
     Cloud Scheduler, GitHub Actions, Airflow) gọi kích hoạt tổng hợp ngày nếu cần.
   - Web Dashboard / Admin UI: Dành sẵn cho việc xây dựng cổng thông tin quản trị Web UI 
     trong tương lai (xem danh sách báo cáo, nhấn nút Duyệt/Từ chối trên web).
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.digest_service import digest_service

router = APIRouter(
    prefix="/api/digests",
    tags=["Daily Digest (Admin / Dev Tools / External Cron)"],
)


class ProcessDailyRequest(BaseModel):
    chat_id: str = Field(..., description="ID cuộc trò chuyện Lark (oc_xxx)")
    chat_name: Optional[str] = Field(default="", description="Tên nhóm chat")
    date: Optional[str] = Field(default=None, description="Ngày cần tổng hợp (YYYY-MM-DD), mặc định hôm nay")
    project_tag: Optional[str] = Field(default=None, description="Tag dự án")
    weknora_kb_id: Optional[str] = Field(default=None, description="WeKnora Knowledge Base ID đích")
    require_approval: Optional[bool] = Field(default=None, description="Gửi tin nhắn xin duyệt trước khi nạp KB hay không")
    tenant_key: Optional[str] = Field(default=None, description="Mã định danh tenant (ISV Multi-Tenant)")


# ==============================================================================
# MASTER DAILY DIGEST ENDPOINTS (TOÀN BỘ CÁC NHÓM)
# ==============================================================================

@router.get("/master/pending/latest")
async def get_latest_master_pending(
    tenant_key: Optional[str] = Query(None, description="Lọc theo tenant_key (ISV)"),
):
    """Lấy bản ghi Master Daily Digest gần nhất đang chờ phê duyệt (hỗ trợ tenant_key)."""
    record = await digest_service.get_latest_pending_master_digest(tenant_key=tenant_key)
    if not record:
        return {"code": 0, "data": None, "message": "Không có master digest nào đang chờ duyệt."}
    return {"code": 0, "data": record.to_dict()}


@router.get("/master/{master_id}")
async def get_master_digest(master_id: str, tenant_key: Optional[str] = Query(None, description="Mã định danh tenant (ISV)")):
    """Lấy chi tiết một bản ghi Master Daily Digest từ MongoDB."""
    record = await digest_service.get_master_digest_by_id(master_id, tenant_key=tenant_key)
    if not record:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy master digest với id: {master_id}")
    return {"code": 0, "data": record.to_dict()}


@router.post("/master/{master_id}/approve")
async def approve_master_digest_endpoint(
    master_id: str,
    approver_id: Optional[str] = Query(None, description="Lark open_id người duyệt"),
    tenant_key: Optional[str] = Query(None, description="Mã định danh tenant (ISV)"),
):
    """Duyệt Master Daily Digest: Đẩy từng group digest vào đúng Knowledge Base WeKnora của nhóm đó."""
    ok, msg, rec = await digest_service.approve_and_sync_master_digest(
        master_id,
        approver_open_id=approver_id,
        tenant_key=tenant_key,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"code": 0, "message": msg, "data": rec.to_dict() if rec else None}


@router.post("/master/{master_id}/reject")
async def reject_master_digest_endpoint(
    master_id: str,
    tenant_key: Optional[str] = Query(None, description="Mã định danh tenant (ISV)"),
):
    """Từ chối Master Daily Digest: Đánh dấu rejected và không nạp vào WeKnora."""
    ok, msg, rec = await digest_service.reject_master_digest(master_id, tenant_key=tenant_key)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"code": 0, "message": msg, "data": rec.to_dict() if rec else None}


@router.post("/master/generate")
async def generate_master_digest_endpoint(
    date: Optional[str] = Query(None, description="Ngày cần chạy (YYYY-MM-DD)"),
    require_approval: Optional[bool] = Query(None, description="Có gửi tin duyệt trước không"),
    tenant_key: Optional[str] = Query(None, description="Mã định danh tenant (ISV)"),
):
    """Kích hoạt tạo Master Daily Digest gom toàn bộ nhóm chat có cô lập theo tenant_key."""
    record = await digest_service.generate_master_daily_digest(
        date=date,
        require_approval=require_approval,
        tenant_key=tenant_key,
    )
    return {
        "code": 0,
        "message": f"Đã tạo Master Daily Digest cho {record.total_groups} nhóm chat ({record.total_messages} tin nhắn).",
        "data": record.to_dict(),
    }
    return {
        "code": 0,
        "message": f"Đã tạo Master Daily Digest cho {record.total_groups} nhóm chat ({record.total_messages} tin nhắn).",
        "data": record.to_dict(),
    }


# ==============================================================================
# SINGLE GROUP DIGEST ENDPOINTS (TỪNG NHÓM RIÊNG LẺ)
# ==============================================================================

@router.get("/pending/latest")
async def get_latest_pending(tenant_key: Optional[str] = Query(None, description="Mã định danh tenant (ISV)")):
    """Lấy bản ghi Daily Digest gần nhất đang chờ phê duyệt."""
    record = await digest_service.get_latest_pending_approval_digest(tenant_key=tenant_key)
    if not record:
        return {"code": 0, "data": None, "message": "Không có digest nào đang chờ duyệt."}
    return {"code": 0, "data": record.to_dict()}


@router.get("/{digest_id}")
async def get_digest(digest_id: str, tenant_key: Optional[str] = Query(None, description="Mã định danh tenant (ISV)")):
    """Lấy chi tiết một bản ghi Daily Digest từ MongoDB."""
    record = await digest_service.get_digest_by_id(digest_id, tenant_key=tenant_key)
    if not record:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy digest với id: {digest_id}")
    return {"code": 0, "data": record.to_dict()}


@router.post("/{digest_id}/approve")
async def approve_digest_endpoint(
    digest_id: str,
    dataset_id: Optional[str] = Query(None, description="WeKnora dataset ID"),
    tenant_key: Optional[str] = Query(None, description="Mã định danh tenant (ISV)"),
):
    """Duyệt Daily Digest: Đẩy bản ghi lên WeKnora và cập nhật trạng thái synced."""
    ok, msg, rec = await digest_service.approve_and_sync_digest(
        digest_id, dataset_id=dataset_id, tenant_key=tenant_key
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"code": 0, "message": msg, "data": rec.to_dict() if rec else None}


@router.post("/{digest_id}/reject")
async def reject_digest_endpoint(digest_id: str, tenant_key: Optional[str] = Query(None, description="Mã định danh tenant (ISV)")):
    """Từ chối Daily Digest: Đánh dấu rejected và không nạp vào WeKnora."""
    ok, msg, rec = await digest_service.reject_digest(digest_id, tenant_key=tenant_key)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"code": 0, "message": msg, "data": rec.to_dict() if rec else None}


@router.post("/run-scheduled")
async def run_scheduled_digests_endpoint(
    date: Optional[str] = Query(None, description="Ngày cần chạy (YYYY-MM-DD)"),
    require_approval: Optional[bool] = Query(None, description="Có gửi tin duyệt trước không"),
    tenant_key: Optional[str] = Query(None, description="Mã định danh tenant (ISV)"),
):
    """Kích hoạt thủ công luồng chạy định kỳ cuối ngày: tạo Master Daily Digest gom toàn bộ nhóm có cô lập theo tenant_key."""
    record = await digest_service.run_scheduled_daily_digests(
        date=date,
        require_approval=require_approval,
        tenant_key=tenant_key,
    )
    return {
        "code": 0,
        "message": f"Đã chạy tổng hợp Master Daily Digest cho {record.total_groups} nhóm chat ({record.total_messages} tin nhắn).",
        "data": record.to_dict(),
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
        tenant_key=req.tenant_key,
    )
    return {
        "code": 0,
        "message": "Đã tổng hợp daily digest thành công",
        "data": digest.to_dict(),
    }
