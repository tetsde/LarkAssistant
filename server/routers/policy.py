"""
Router quản lý và đồng bộ Chính sách Doanh nghiệp (Lark Base <-> WeKnora).
Vị trí: server/routers/policy.py
"""

from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Query
from core.config import settings
from services.policy_sync_service import policy_sync_service
from services.weknora import weknora_service

router = APIRouter(prefix="/policy", tags=["Company Policy Sync"])


@router.get("/status")
async def get_policy_sync_status() -> Dict[str, Any]:
    """
    Lấy trạng thái cấu hình và kết quả đồng bộ chính sách gần nhất.
    """
    ds_id = settings.WEKNORA_POLICY_DATASOURCE_ID
    ds_status = {}
    if ds_id:
        ds_status = await weknora_service.get_datasource_sync_status(ds_id)

    return {
        "sync_enabled": settings.POLICY_SYNC_ENABLED,
        "sync_interval_seconds": settings.POLICY_SYNC_INTERVAL_SECONDS,
        "policy_table_id": settings.LARK_BASE_POLICY_TABLE_ID,
        "policy_kb_id": settings.WEKNORA_POLICY_DATASET_ID,
        "policy_datasource_id": ds_id,
        "datasource_status": ds_status,
    }


@router.post("/sync")
async def trigger_policy_sync(
    force: bool = Query(False, description="Bắt buộc đồng bộ kể cả khi danh sách token không đổi")
) -> Dict[str, Any]:
    """
    Kích hoạt quét bảng chính sách trên Lark Base và đồng bộ sang WeKnora.
    """
    try:
        result = await policy_sync_service.sync_policies(force=force)
        return {
            "success": True,
            "result": result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi đồng bộ chính sách: {str(e)}")
