"""
Router quản lý và đồng bộ Chính sách Doanh nghiệp (Lark Base <-> WeKnora).
Vị trí: server/routers/policy.py
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query
from core.config import settings
from core.tenant_errors import TenantResolutionError, TokenUnavailable
from services.knowledge_service import policy_sync_service, weknora_service

router = APIRouter(prefix="/policy", tags=["Company Policy Sync"])


@router.get("/status")
async def get_policy_sync_status(
    tenant_key: Optional[str] = Query(None, description="Mã định danh tenant (Custom App Multi-Tenant)")
) -> Dict[str, Any]:
    """
    Lấy trạng thái cấu hình và kết quả đồng bộ chính sách của MỘT doanh nghiệp.

    Không còn mặc định `settings.WEKNORA_POLICY_DATASET_ID` / `WEKNORA_POLICY_DATASOURCE_ID` /
    `LARK_BASE_POLICY_TABLE_ID`: ba giá trị đó từng là hardcode của doanh nghiệp đầu tiên, nên
    gọi `/policy/status` mà không kèm `tenant_key` sẽ lộ bảng + kho + data source của công ty khác.
    Thiếu tenant là 400 (`TenantContextMissing`), thiếu field là chuỗi rỗng chứ không mượn của ai.
    """
    from database.db import get_current_tenant_key, get_tenant_config
    from core.tenant_errors import TenantContextMissing

    eff_tenant = (tenant_key or "").strip() or get_current_tenant_key()
    if not eff_tenant:
        raise TenantContextMissing(
            "/policy/status cần `tenant_key` để trả đúng cấu hình của doanh nghiệp được hỏi."
        )

    t_cfg = await get_tenant_config(eff_tenant) or {}
    ds_id = t_cfg.get("weknora_policy_datasource_id") or ""
    pol_kb_id = t_cfg.get("weknora_policy_dataset_id") or ""
    pol_tbl_id = t_cfg.get("company_policy_table_id") or ""
    interval = int(t_cfg.get("policy_sync_interval_seconds") or settings.POLICY_SYNC_INTERVAL_SECONDS or 3600)
    last_sync = t_cfg.get("last_policy_sync") or {}
    recent_logs = policy_sync_service.get_recent_logs(eff_tenant)
    if not recent_logs and last_sync.get("logs"):
        recent_logs = last_sync.get("logs")

    ds_status = {}
    if ds_id:
        ds_status = await weknora_service.get_datasource_sync_status(ds_id)

    return {
        "tenant_key": eff_tenant,
        "sync_enabled": settings.POLICY_SYNC_ENABLED,
        "sync_interval_seconds": interval,
        "policy_table_id": pol_tbl_id,
        "policy_kb_id": pol_kb_id,
        "policy_datasource_id": ds_id,
        "datasource_status": ds_status,
        "last_sync": last_sync,
        "recent_logs": recent_logs or [],
    }


@router.post("/sync")
async def trigger_policy_sync(
    force: bool = Query(True, description="Bắt buộc đồng bộ kể cả khi danh sách token không đổi"),
    tenant_key: Optional[str] = Query(None, description="Mã định danh tenant (Custom App Multi-Tenant)"),
) -> Dict[str, Any]:
    """
    Kích hoạt quét bảng chính sách trên Lark Base và đồng bộ sang WeKnora.
    """
    try:
        result = await policy_sync_service.sync_policies(force=force, tenant_key=tenant_key)
        recent_logs = policy_sync_service.get_recent_logs(tenant_key) or result.get("logs", [])
        return {
            "success": True,
            "tenant_key": tenant_key,
            "result": result,
            "logs": recent_logs,
        }
    except (TenantResolutionError, TokenUnavailable):
        # 400/409/401/503 theo hợp đồng lỗi tầng tenant (handler ở main.py) — không gộp vào 500.
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi đồng bộ chính sách: {str(e)}")


@router.post("/interval")
async def update_policy_interval(
    interval_seconds: int = Query(..., ge=60, le=604800, description="Chu kỳ quét định kỳ (giây)"),
    tenant_key: Optional[str] = Query(None, description="Mã định danh tenant (Custom App Multi-Tenant)"),
) -> Dict[str, Any]:
    """Cập nhật chu kỳ quét định kỳ chính sách cho một doanh nghiệp."""
    from database.db import get_current_tenant_key, get_tenants_collection
    from core.tenant_errors import TenantContextMissing

    eff_tenant = (tenant_key or "").strip() or get_current_tenant_key()
    if not eff_tenant:
        raise TenantContextMissing("/policy/interval cần `tenant_key` để lưu chu kỳ đúng doanh nghiệp.")

    col = get_tenants_collection()
    await col.update_one(
        {"tenant_key": eff_tenant},
        {"$set": {"policy_sync_interval_seconds": int(interval_seconds)}},
    )
    return {
        "success": True,
        "tenant_key": eff_tenant,
        "policy_sync_interval_seconds": int(interval_seconds),
        "message": f"Đã cập nhật chu kỳ quét chính sách thành {interval_seconds} giây.",
    }
