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
from typing import Any, Dict

from models.memory import get_vietnam_now_iso
from services.tenancy.tenant_state import (
    INACTIVE,
    PROVISIONING,
    READY,
    tenant_state,
    InvalidTenantTransition,
)

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

    if not tenant_key:
        logger.error("[TENANT_LIFECYCLE] ignored event=%s reason=missing_tenant_key", event_type)
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

    # app_id PHẢI đến từ chính sự kiện. Trước đây thiếu app_id thì handler mượn
    # `settings.LARK_APP_ID` và ghi vào tenant, tức là tenant B bị gắn với App của
    # một doanh nghiệp khác ngay trong bảng `tenants`.
    app_id = event.get("app_id") or header.get("app_id") or ""
    if not app_id:
        logger.error(
            "[TENANT_LIFECYCLE] ignored event=%s tenant=%s reason=missing_app_id",
            event_type,
            tenant_key,
        )
        return False

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
        # Đọc trạng thái hiện tại qua đúng một cửa: `tenant_state` là nơi duy nhất hiểu
        # schema của document `tenants` cho vòng đời này.
        existing = await tenant_state.get_status(tenant_key)
        current_status = existing.get("status") if isinstance(existing, dict) else None

        if normalized_status == "active" and current_status in {READY, PROVISIONING}:
            logger.info(
                "[TENANT_LIFECYCLE] provisioning_skipped tenant=%s status=%s",
                tenant_key,
                current_status,
            )
            return True

        # Với tenant đã bật, chỉ ghi một lần sau khi provision xong để tránh trạng thái
        # active giả và giữ event handler idempotent. Các trạng thái khác ghi ngay,
        # và MỌI lần ghi đều đi qua tenant_state (kèm invalidate cache).
        if normalized_status != "active":
            if normalized_status == "uninstalled":
                await tenant_state.mark_uninstalled(tenant_key, raw_event_type=event_type, app_id=app_id)
            elif normalized_status == INACTIVE:
                await tenant_state.mark_inactive(tenant_key, raw_event_type=event_type, app_id=app_id)
            else:
                await tenant_state.transition(
                    tenant_key, normalized_status, raw_event_type=event_type, app_id=app_id
                )
            logger.info(
                "[TENANT_LIFECYCLE] status_updated tenant=%s status=%s event=%s",
                tenant_key,
                normalized_status,
                event_type,
            )
            return True

        # Tự động cấp phát không gian WeKnora & Lark Base khi doanh nghiệp kích hoạt app (EDL-0020)
        if normalized_status == "active" and tenant_key:
            await tenant_state.transition(
                tenant_key,
                PROVISIONING,
                app_id=app_id,
                admin_open_id=operator_id or None,
                raw_event_type=event_type,
            )
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
                if provisioned_tenant_id:
                    # Cùng một điểm hẹn ready cho cả setup wizard lẫn App Store:
                    # tenant_state.mark_ready luôn invalidate resolver + token broker.
                    await tenant_state.mark_ready(
                        tenant_key,
                        app_id=app_id,
                        raw_event_type=event_type,
                        admin_open_id=operator_id or None,
                    )
                else:
                    await tenant_state.transition(
                        tenant_key, "active", app_id=app_id, raw_event_type=event_type
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
                        logger.info("[TENANT_LIFECYCLE] welcome_card_sent tenant=%s admin=%s", tenant_key, operator_id)
                    except Exception as card_err:
                        logger.warning("[TENANT_LIFECYCLE] welcome_card_failed tenant=%s error=%s action=text_fallback", tenant_key, card_err)
                        handover_text = weknora_provision_service.build_handover_message(tenant_cfg)
                        await lark_service.send_bot_dm_to_owner(
                            text=handover_text,
                            target_open_id=operator_id,
                            tenant_key=tenant_key,
                        )
                        logger.info("[TENANT_LIFECYCLE] welcome_text_sent tenant=%s admin=%s", tenant_key, operator_id)
            except Exception as prov_err:
                logger.error("[TENANT_LIFECYCLE] provision_failed tenant=%s error=%s", tenant_key, prov_err, exc_info=True)
                await tenant_state.mark_provisioning_failed(tenant_key, str(prov_err))
                return False

        return True
    except InvalidTenantTransition as trans_err:
        # Hai luồng đang tự viết status sai thứ tự — ghi log rõ ràng, không âm thầm ghi đè.
        logger.error("[TENANT_LIFECYCLE] invalid_transition error=%s", trans_err)
        return False
    except Exception as e:
        logger.error("[TENANT_LIFECYCLE] save_failed error=%s", e, exc_info=True)
        return False

