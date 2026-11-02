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
import inspect
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

    # Trích xuất operator_id (admin thực hiện cài đặt/mở app)
    operator_id = ""
    if "operator" in event and isinstance(event["operator"], dict):
        op = event["operator"]
        op_id_obj = op.get("operator_id")
        if isinstance(op_id_obj, dict):
            operator_id = op_id_obj.get("open_id") or op_id_obj.get("user_id", "")
        elif isinstance(op_id_obj, str):
            operator_id = op_id_obj
    if not operator_id:
        operator_id = event.get("operator_id") or event.get("user_id") or ""

    record = {
        "tenant_key": tenant_key,
        "app_id": app_id,
        "status": normalized_status,
        "raw_event_type": event_type,
        "raw_status": raw_status,
        "updated_at": get_vietnam_now_iso(),
    }
    if operator_id:
        record["admin_open_id"] = operator_id

    try:
        col = get_tenants_collection()
        existing = None
        if tenant_key:
            finder = getattr(col, "find_one", None)
            if finder:
                found = finder({"tenant_key": tenant_key})
                existing = await found if inspect.isawaitable(found) else found
        if normalized_status == "active" and isinstance(existing, dict) and existing.get("status") in {"ready", "provisioning"}:
            logger.info(
                "[TENANT LIFECYCLE] Bỏ qua provisioning lặp cho tenant '%s' (status=%s)",
                tenant_key,
                existing.get("status"),
            )
            return True
        # Với active tenant, chỉ ghi một lần sau khi provision xong để tránh trạng thái
        # active giả và giữ event handler idempotent. Các trạng thái khác ghi ngay.
        if normalized_status != "active":
            await col.update_one(
                {"tenant_key": tenant_key},
                {"$set": record, "$setOnInsert": {"created_at": get_vietnam_now_iso()}},
                upsert=True,
            )
        logger.info(
            f"✔ [TENANT LIFECYCLE] Doanh nghiệp '{tenant_key}' đã ghi nhận trạng thái: "
            f"'{normalized_status}' (Sự kiện: {event_type})"
        )

        # Tự động cấp phát không gian WeKnora & Lark Base khi doanh nghiệp kích hoạt app (EDL-0020)
        if normalized_status == "active" and tenant_key:
            try:
                from services.knowledge.weknora_provision_service import weknora_provision_service
                tenant_cfg = await weknora_provision_service.provision_tenant_weknora(
                    tenant_key=tenant_key,
                    enterprise_name=f"Enterprise {tenant_key}",
                    admin_open_id=operator_id or None,
                )

                from services.lark.base_provision_service import base_provision_service
                await base_provision_service.provision_enterprise_base(
                    admin_open_id=operator_id or None,
                    tenant_key=tenant_key,
                )

                provisioned_tenant_id = (
                    tenant_cfg.get("weknora_tenant_id") if isinstance(tenant_cfg, dict)
                    else getattr(tenant_cfg, "weknora_tenant_id", None)
                )
                ready_status = "ready" if isinstance(provisioned_tenant_id, (str, int)) and provisioned_tenant_id else "active"
                await col.update_one(
                    {"tenant_key": tenant_key},
                    {"$set": {**record, "status": ready_status, "ready_at": get_vietnam_now_iso() if ready_status == "ready" else None},
                     "$setOnInsert": {"created_at": get_vietnam_now_iso()}},
                    upsert=True,
                )

                # Gửi Thẻ tương tác Chào mừng & Bàn giao tài nguyên cho Admin (EDL-0021)
                if operator_id and tenant_cfg:
                    from services.lark import lark_service
                    from services.lark.card_builder import build_marketplace_welcome_card

                    welcome_card = build_marketplace_welcome_card(tenant_cfg)
                    try:
                        res = await lark_service.send_bot_dm_to_owner(
                            text=welcome_card,
                            target_open_id=operator_id,
                            tenant_key=tenant_key,
                        )
                        if not res.get("success"):
                            raise RuntimeError(f"Gửi card thất bại: {res.get('msg')}")
                        logger.info(f"✔ [TENANT LIFECYCLE] Đã gửi Welcome Card tương tác tới Admin ({operator_id})")
                    except Exception as card_err:
                        logger.warning(f"Lỗi khi gửi Welcome Card, fallback sang tin nhắn văn bản: {card_err}")
                        handover_text = weknora_provision_service.build_handover_message(tenant_cfg)
                        await lark_service.send_bot_dm_to_owner(
                            text=handover_text,
                            target_open_id=operator_id,
                            tenant_key=tenant_key,
                        )
                        logger.info(f"✔ [TENANT LIFECYCLE] Đã gửi thông điệp bàn giao WeKnora (text fallback) tới Admin ({operator_id})")
            except Exception as prov_err:
                logger.error(f"Lỗi khi tự động cấp phát tài nguyên cho tenant {tenant_key}: {prov_err}", exc_info=True)
                await col.update_one(
                    {"tenant_key": tenant_key},
                    {"$set": {**record, "status": "provisioning_failed", "provisioning_error": str(prov_err), "updated_at": get_vietnam_now_iso()},
                     "$setOnInsert": {"created_at": get_vietnam_now_iso()}},
                    upsert=True,
                )
                return False

        return True
    except Exception as e:
        logger.error(f"Lỗi khi lưu trạng thái tenant lifecycle: {e}", exc_info=True)
        return False

