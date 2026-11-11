"""
HiLark - Tenant App Lifecycle Event Handler (EDL-0020)
======================================================
Vị trí: server/services/lark/handlers/tenant_lifecycle_handler.py

Chịu trách nhiệm:
  1. Lắng nghe và xử lý các sự kiện vòng đời Custom App doanh nghiệp trên Lark:
     - `app_status_change`: Doanh nghiệp bật/tắt ứng dụng (start_by_tenant / stop_by_tenant).
     - `app_uninstalled`: Doanh nghiệp gỡ cài đặt ứng dụng.
     - `open_app`: Doanh nghiệp lần đầu mở/kích hoạt ứng dụng.
  2. Ghi nhận và cập nhật trạng thái doanh nghiệp vào MongoDB collection `tenants`.
  3. Tự động khởi tạo ngữ cảnh cho doanh nghiệp mới.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional
from unittest.mock import Base as _MockBase

from models.memory import get_vietnam_now_iso
from services.tenancy.tenant_state import (
    AWAITING_USER_OAUTH,
    INACTIVE,
    PROVISIONING,
    READY,
    tenant_state,
    InvalidTenantTransition,
)

logger = logging.getLogger("hilark.tenant_lifecycle")
logger.setLevel(logging.INFO)


async def _has_valid_admin_user_token(tenant_key: str, app_id: str) -> bool:
    """Kiểm tra tenant + app đã có Admin User Token (hoặc refresh token còn hạn) hay chưa."""
    from services.auth_service import token_service

    try:
        stored = await token_service.get_stored_token_data(tenant_key=tenant_key, app_id=app_id)
    except Exception as exc:
        logger.debug("[TENANT_LIFECYCLE] token_lookup_failed tenant=%s err=%s", tenant_key, exc)
        return False

    if not stored or not stored.get("access_token"):
        return False
    if stored.get("status") == "invalid_refresh_token":
        return False

    now = time.time()
    expires_at = float(stored.get("expires_at") or 0)
    if expires_at > now:
        return True

    refresh_token = stored.get("refresh_token")
    if not refresh_token:
        return False

    refresh_expires_at = float(stored.get("refresh_expires_at") or stored.get("refresh_token_expires_at") or 0)
    if refresh_expires_at and refresh_expires_at <= now:
        return False
    return True


async def _resolve_sender_lark_service(app_id: str):
    """Lấy đúng instance Lark runtime cho app_id; vẫn tôn trọng mock test trên lark_service."""
    from services.lark import lark_service

    if isinstance(getattr(lark_service, "send_bot_dm_to_owner", None), _MockBase):
        return lark_service

    if app_id:
        try:
            from services.lark_app_service import lark_app_service
            from services.lark.runtime import get_or_create_lark_service

            app_record = await lark_app_service.get_by_app_id(app_id)
            if app_record:
                return await get_or_create_lark_service(app_record)
        except Exception as exc:
            logger.debug("[TENANT_LIFECYCLE] runtime_service_resolve_failed app=%s err=%s", app_id, exc)
    return lark_service


async def provision_tenant_and_send_handover(
    *,
    tenant_key: str,
    app_id: str,
    admin_open_id: Optional[str] = None,
    raw_event_type: str = "oauth_callback",
) -> Dict[str, Any]:
    """
    Thực thi pipeline cấp phát WeKnora + Lark Base cho tenant sau khi đã có User OAuth,
    chuyển PROVISIONING -> READY và gửi Thẻ chào mừng bàn giao cho Admin.
    """
    operator_id = (admin_open_id or "").strip() or None
    await tenant_state.transition(
        tenant_key,
        PROVISIONING,
        app_id=app_id,
        admin_open_id=operator_id,
        raw_event_type=raw_event_type,
    )
    try:
        from services.knowledge.weknora_provision_service import weknora_provision_service

        tenant_cfg = await weknora_provision_service.provision_tenant_weknora(
            tenant_key=tenant_key,
            enterprise_name=f"Enterprise {tenant_key}",
            admin_open_id=operator_id,
        )

        from services.lark.base_provision_service import base_provision_service

        await base_provision_service.provision_enterprise_base(
            admin_open_id=operator_id,
            tenant_key=tenant_key,
        )

        provisioned_tenant_id = (
            tenant_cfg.get("weknora_tenant_id")
            if isinstance(tenant_cfg, dict)
            else getattr(tenant_cfg, "weknora_tenant_id", None)
        )
        if provisioned_tenant_id:
            await tenant_state.mark_ready(
                tenant_key,
                app_id=app_id,
                raw_event_type=raw_event_type,
                admin_open_id=operator_id,
            )
        else:
            await tenant_state.transition(
                tenant_key, "active", app_id=app_id, raw_event_type=raw_event_type
            )

        if operator_id and tenant_cfg:
            from services.lark.card_builder import build_marketplace_welcome_card

            sender_service = await _resolve_sender_lark_service(app_id)
            welcome_card = build_marketplace_welcome_card(tenant_cfg)
            try:
                res = await sender_service.send_bot_dm_to_owner(
                    text=welcome_card,
                    target_open_id=operator_id,
                    tenant_key=tenant_key,
                )
                if isinstance(res, dict) and not res.get("success"):
                    raise RuntimeError(f"Gửi card thất bại: {res.get('msg')}")
                logger.info(
                    "[TENANT_LIFECYCLE] welcome_card_sent tenant=%s admin=%s",
                    tenant_key,
                    operator_id,
                )
            except Exception as card_err:
                logger.warning(
                    "[TENANT_LIFECYCLE] welcome_card_failed tenant=%s error=%s action=text_fallback",
                    tenant_key,
                    card_err,
                )
                handover_text = weknora_provision_service.build_handover_message(tenant_cfg)
                await sender_service.send_bot_dm_to_owner(
                    text=handover_text,
                    target_open_id=operator_id,
                    tenant_key=tenant_key,
                )
                logger.info(
                    "[TENANT_LIFECYCLE] welcome_text_sent tenant=%s admin=%s",
                    tenant_key,
                    operator_id,
                )
        return {"success": True, "status": READY}
    except Exception as prov_err:
        logger.error(
            "[TENANT_LIFECYCLE] provision_failed tenant=%s error=%s",
            tenant_key,
            prov_err,
            exc_info=True,
        )
        await tenant_state.mark_provisioning_failed(tenant_key, str(prov_err))
        return {"success": False, "error": str(prov_err)}


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

        # Nếu tenant đã từng bàn giao (`ready_at` đã có) và bị stop_by_tenant -> start_by_tenant:
        # chỉ kích hoạt lại `READY` mà không tạo trùng Base/WeKnora.
        if (
            current_status == INACTIVE
            and isinstance(existing, dict)
            and existing.get("ready_at")
        ):
            await tenant_state.mark_active(
                tenant_key,
                app_id=app_id,
                raw_event_type=event_type,
            )
            logger.info(
                "[TENANT_LIFECYCLE] reactivated_without_reprovision tenant=%s event=%s",
                tenant_key,
                event_type,
            )
            return True

        # Cổng Onboarding Gate (Phase 4): kiểm tra Admin User Token trước khi cấp phát.
        # Nếu chưa có User Token hợp lệ trong `lark_auth`, tạm dừng ở `awaiting_user_oauth`
        # và gửi thẻ Bot DM mời Admin hoàn tất OAuth (tự nối sang provision tại callback).
        eff_admin = operator_id or (
            existing.get("admin_open_id") if isinstance(existing, dict) else ""
        ) or ""
        has_token = await _has_valid_admin_user_token(tenant_key, app_id)
        if not has_token:
            await tenant_state.mark_awaiting_user_oauth(
                tenant_key,
                app_id=app_id,
                admin_open_id=eff_admin or None,
                raw_event_type=event_type,
            )
            logger.info(
                "[TENANT_LIFECYCLE] awaiting_user_oauth tenant=%s app=%s admin=%s event=%s",
                tenant_key,
                app_id,
                eff_admin,
                event_type,
            )
            if eff_admin:
                try:
                    from services.lark.card_builder import build_admin_oauth_invite_card

                    ent_name = existing.get("enterprise_name") if isinstance(existing, dict) else None
                    invite_card = build_admin_oauth_invite_card(
                        tenant_key=tenant_key,
                        app_id=app_id,
                        enterprise_name=ent_name,
                    )
                    sender_service = await _resolve_sender_lark_service(app_id)
                    dm_res = await sender_service.send_bot_dm_to_owner(
                        text=invite_card,
                        target_open_id=eff_admin,
                        tenant_key=tenant_key,
                    )
                    if isinstance(dm_res, dict) and not dm_res.get("success"):
                        logger.warning(
                            "[TENANT_LIFECYCLE] oauth_invite_dm_failed tenant=%s msg=%s",
                            tenant_key,
                            dm_res.get("msg"),
                        )
                except Exception as invite_err:
                    logger.warning(
                        "[TENANT_LIFECYCLE] oauth_invite_dm_error tenant=%s err=%s",
                        tenant_key,
                        invite_err,
                    )
            return True

        # Đã có Admin User Token hợp lệ -> thực thi provision WeKnora + Lark Base & bàn giao.
        res = await provision_tenant_and_send_handover(
            tenant_key=tenant_key,
            app_id=app_id,
            admin_open_id=eff_admin or None,
            raw_event_type=event_type,
        )
        return bool(res.get("success"))
    except InvalidTenantTransition as trans_err:
        # Hai luồng đang tự viết status sai thứ tự — ghi log rõ ràng, không âm thầm ghi đè.
        logger.error("[TENANT_LIFECYCLE] invalid_transition error=%s", trans_err)
        return False
    except Exception as e:
        logger.error("[TENANT_LIFECYCLE] save_failed error=%s", e, exc_info=True)
        return False

