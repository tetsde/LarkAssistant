"""
HiLark - Tenant App Lifecycle Event Handler (EDL-0020)
======================================================
Vị trí: server/services/lark/handlers/tenant_lifecycle_handler.py

Chịu trách nhiệm:
  1. Lắng nghe và xử lý các sự kiện vòng đời ứng dụng trên Lark App Store:
     - `app_status_change`: Doanh nghiệp bật/tắt ứng dụng (start_by_tenant / stop_by_tenant).
     - `app_uninstalled`: Doanh nghiệp gỡ cài đặt ứng dụng.
     - `open_app`: Doanh nghiệp lần đầu mở/kích hoạt ứng dụng.
  2. Ghi nhận và cập nhật trạng thái doanh nghiệp vào MongoDB collection `tenants`.
  3. Tự động khởi tạo ngữ cảnh cho doanh nghiệp mới.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from core.config import settings
from database.db import get_tenants_collection
from models.memory import get_vietnam_now_iso

logger = logging.getLogger("hilark.tenant_lifecycle")
logger.setLevel(logging.INFO)


async def handle_tenant_lifecycle_event(payload: Dict[str, Any]) -> bool:
    """
    Xử lý sự kiện vòng đời của Tenant từ Lark Event Ingress Webhook.

    Returns:
        True nếu sự kiện được nhận diện và xử lý thành công, False nếu bỏ qua.
    """
    if not isinstance(payload, dict):
        return False

    header = payload.get("header") or {}
    event = payload.get("event") or {}

    event_type = header.get("event_type") or payload.get("type") or ""
    tenant_key = header.get("tenant_key") or event.get("tenant_key") or ""

    if not event_type or event_type not in ("app_status_change", "app_uninstalled", "open_app"):
        return False

    # Xác định trạng thái chuẩn hóa
    raw_status = event.get("status", "")
    if event_type == "app_uninstalled":
        normalized_status = "uninstalled"
    elif event_type == "open_app":
        normalized_status = "active"
    elif raw_status == "start_by_tenant":
        normalized_status = "active"
    elif raw_status == "stop_by_tenant":
        normalized_status = "inactive"
    else:
        normalized_status = raw_status or "active"

    app_id = event.get("app_id") or header.get("app_id") or getattr(settings, "LARK_APP_ID", "")

    record = {
        "tenant_key": tenant_key,
        "app_id": app_id,
        "status": normalized_status,
        "raw_event_type": event_type,
        "raw_status": raw_status,
        "updated_at": get_vietnam_now_iso(),
    }

    try:
        col = get_tenants_collection()
        await col.update_one(
            {"tenant_key": tenant_key},
            {
                "$set": record,
                "$setOnInsert": {"created_at": get_vietnam_now_iso()},
            },
            upsert=True,
        )
        logger.info(
            f"✔ [TENANT LIFECYCLE] Doanh nghiệp '{tenant_key}' đã ghi nhận trạng thái: "
            f"'{normalized_status}' (Sự kiện: {event_type})"
        )
        return True
    except Exception as e:
        logger.error(f"Lỗi khi lưu trạng thái tenant lifecycle: {e}", exc_info=True)
        return False

