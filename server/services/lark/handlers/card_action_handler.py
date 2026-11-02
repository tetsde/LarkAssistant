
"""
Card Action Handler for Lark Interactive Cards
===============================================
Vị trí: server/services/lark/handlers/card_action_handler.py

Mục đích:
    - Xử lý các sự kiện tương tác khi Lãnh đạo bấm nút trên Thẻ tin nhắn tương tác (Lark Interactive Card):
      1. Bản nháp câu trả lời: Duyệt gửi, Hủy bỏ, Nhờ AI sửa, Tự sửa.
      2. Thông tin đề xuất (Claims/Facts): Duyệt thông tin, Từ chối, Sửa giá trị.
      3. Báo cáo ngày (Master Daily Digest): Duyệt và lưu tri thức, Hủy báo cáo, Xem chi tiết, Tóm tắt ngắn.
    - Cập nhật thẻ tin nhắn tại chỗ (In-place update) sang thẻ trạng thái đã xử lý (build_updated_status_card).
    - Cung cấp phản hồi thông báo (toast) cho giao diện Lark.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Dict, Optional, Tuple

from services.claim_service import claim_service as default_claim_service
from services.digest_service import digest_service as default_digest_service
from services.draft_service import draft_service as default_draft_service
from services.lark import lark_service as default_lark_service
from services.lark.card_builder import (
    PROPERTY_LABELS,
    build_admin_status_card,
    build_digest_approval_card,
    build_onboarding_welcome_card,
    build_owner_control_hub_card,
    build_project_digest_detail_card,
    build_updated_status_card,
)


logger = logging.getLogger("hilark.bot.card_action_handler")


def _resolve_service(name: str, default: Any) -> Any:
    from services.lark.runtime import get_current_lark_service
    bs = sys.modules.get("services.bot_service") or sys.modules.get("services.lark.bot_runner")
    fallback = getattr(bs, name, default) if bs else default
    return get_current_lark_service(fallback) if name == "lark_service" else fallback


def parse_card_action_payload(payload: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any]]:
    """
    Bóc tách payload sự kiện bấm nút từ Lark (hỗ trợ cả Card Callback chuẩn và Event 2.0).
    Trả về: (open_id, message_id, action_value_dict)
    """
    if not isinstance(payload, dict):
        return "", "", {}

    header_tenant = payload.get("header", {}).get("tenant_key") if payload.get("header") else None

    # Case 1: Schema 2.0 event (header.event_type == 'card.action.trigger')
    if payload.get("header") and payload.get("event"):
        event = payload.get("event") or {}
        operator = event.get("operator") or {}
        open_id = operator.get("open_id") or operator.get("user_id") or ""
        context = event.get("context") or {}
        message_id = context.get("open_message_id") or context.get("message_id") or ""
        raw_val = event.get("action", {}).get("value") or {}
    else:
        # Case 2: Card Callback chuẩn
        open_id = payload.get("open_id") or payload.get("user_id") or ""
        message_id = payload.get("open_message_id") or payload.get("message_id") or ""
        raw_val = payload.get("action", {}).get("value") or {}

    action_val: Dict[str, Any] = {}
    if isinstance(raw_val, dict):
        action_val = dict(raw_val)
    elif isinstance(raw_val, str):
        try:
            action_val = json.loads(raw_val)
        except Exception:
            action_val = {"raw": raw_val}

    if header_tenant and not action_val.get("tenant_key"):
        action_val["tenant_key"] = header_tenant

    return open_id, message_id, action_val


async def handle_card_action(
    open_id: str,
    message_id: str,
    action_value: Dict[str, Any],
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Điều phối xử lý hành động khi bấm nút trên Thẻ tương tác có cô lập theo tenant_key.
    Trả về: (thành_công, thông_báo_toast, thẻ_cập_nhật_nếu_có)
    """
    from database.db import async_tenant_context, get_current_tenant_key, get_tenants_collection

    eff_tenant = action_value.get("tenant_key") or get_current_tenant_key()
    if not eff_tenant and open_id:
        try:
            t_col = get_tenants_collection()
            found_t = await t_col.find_one({"admin_open_id": open_id})
            if found_t and found_t.get("tenant_key"):
                eff_tenant = found_t["tenant_key"]
        except Exception:
            pass

    async with async_tenant_context(eff_tenant):
        return await _execute_card_action(open_id, message_id, action_value, eff_tenant)


async def _execute_card_action(
    open_id: str,
    message_id: str,
    action_value: Dict[str, Any],
    tenant_key: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Thực thi logic nội bộ hành động thẻ với tenant context đã xác định."""
    action = action_value.get("action")
    if not action:
        return False, "Không xác định được hành động từ thẻ", None

    lark_svc = _resolve_service("lark_service", default_lark_service)
    draft_svc = _resolve_service("draft_service", default_draft_service)
    claim_svc = _resolve_service("claim_service", default_claim_service)
    digest_svc = _resolve_service("digest_service", default_digest_service)

    logger.info(f"Nhận hành động thẻ: action='{action}' từ open_id='{open_id}' cho message_id='{message_id}' (tenant: {tenant_key})")

    # =========================================================================
    # 1. HÀNH ĐỘNG DUYỆT BẢN NHÁP CÂU TRẢ LỜI
    # =========================================================================
    if action == "approve_draft":
        ok, detail, draft, _ = await draft_svc.send_latest(open_id, tenant_key=tenant_key)
        if ok and draft:
            resp_name = getattr(draft, "responder_name", None) or (draft.get("responder_name") if isinstance(draft, dict) else None) or "User"
            appr_content = getattr(draft, "approved_content", None) or (draft.get("approved_content") if isinstance(draft, dict) else None) or getattr(draft, "draft_answer", None) or (draft.get("draft_answer") if isinstance(draft, dict) else None) or ""
            updated_card = build_updated_status_card(
                title="Bản nháp câu trả lời",
                status_message="Đã duyệt và gửi câu trả lời vào nhóm thảo luận",
                detail_lines=[
                    f"Người trả lời: {resp_name}",
                    f"Nội dung đã gửi: \"{appr_content}\"",
                ],
                template="green",
            )
            if message_id:
                try:
                    await lark_svc.update_card_message(message_id, updated_card, tenant_key=tenant_key)
                except Exception as e:
                    logger.warning(f"Không thể cập nhật thẻ tại chỗ: {e}")
            return True, "Đã gửi câu trả lời vào nhóm thành công", updated_card
        return False, f"Chưa thể gửi bản nháp: {detail}", None

    if action == "discard_draft":
        draft = await draft_svc.discard_latest(open_id, tenant_key=tenant_key)
        if draft:
            draft_query = getattr(draft, "query", None) or (draft.get("query") if isinstance(draft, dict) else "") or ""
            updated_card = build_updated_status_card(
                title="Bản nháp câu trả lời",
                status_message="Đã hủy bỏ bản nháp",
                detail_lines=[
                    f"Câu hỏi: \"{draft_query}\"",
                    "Không có nội dung nào được gửi vào nhóm thảo luận.",
                ],
                template="grey",
            )
            if message_id:
                try:
                    await lark_svc.update_card_message(message_id, updated_card, tenant_key=tenant_key)
                except Exception as e:
                    logger.warning(f"Không thể cập nhật thẻ tại chỗ: {e}")
            return True, "Đã hủy bỏ bản nháp thành công", updated_card
        return False, "Hiện không có bản nháp nào đang chờ duyệt để hủy", None

    if action == "ai_rewrite_draft":
        msg_prompt = "Vui lòng nhắn trong cuộc trò chuyện này: Sửa AI: <yêu cầu cụ thể> để AI điều chỉnh câu trả lời theo chỉ đạo."
        await lark_svc.send_bot_dm_to_owner(msg_prompt, target_open_id=open_id, tenant_key=tenant_key)
        return True, "Nhắn 'Sửa AI: <yêu cầu>' để viết lại", None

    if action == "manual_edit_draft":
        msg_prompt = "Vui lòng nhắn trong cuộc trò chuyện này: Sửa: <nội dung mới> để cập nhật và gửi trực tiếp câu trả lời vào nhóm."
        await lark_svc.send_bot_dm_to_owner(msg_prompt, target_open_id=open_id, tenant_key=tenant_key)
        return True, "Nhắn 'Sửa: <nội dung>' để tự sửa", None

    # =========================================================================
    # 2. HÀNH ĐỘNG DUYỆT THÔNG TIN ĐỀ XUẤT (CLAIMS / FACTS)
    # =========================================================================
    if action == "approve_claim":
        claim_id = action_value.get("claim_id")
        ok, msg_reply, target_claim = await claim_svc.approve_claim(
            claim_id=claim_id,
            approver_info={"user_id": open_id, "user_name": "Lãnh đạo"},
            tenant_key=tenant_key,
        )
        if ok and target_claim:
            prop = target_claim.get("property") or target_claim.get("predicate") or "thông tin"
            prop_label = PROPERTY_LABELS.get(str(prop).lower(), str(prop))
            ent_name = target_claim.get("entity_id") or "Dự án"
            val = target_claim.get("value") or ""
            updated_card = build_updated_status_card(
                title="Thông tin đề xuất",
                status_message="Đã phê duyệt và chuyển thành thông tin chính thức",
                detail_lines=[
                    f"Thực thể: {ent_name}",
                    f"Thuộc tính: {prop_label}",
                    f"Giá trị chính thức: {val}",
                    "Hiệu lực: Đã có hiệu lực cho câu trả lời của nhóm",
                ],
                template="green",
            )
            target_msg_id = message_id or action_value.get("message_id")
            if target_msg_id:
                try:
                    await lark_svc.update_card_message(target_msg_id, updated_card, tenant_key=tenant_key)
                except Exception as e:
                    logger.warning(f"Không thể cập nhật thẻ tại chỗ: {e}")
            return True, "Đã duyệt thông tin đề xuất thành công", updated_card
        return False, f"Không thể duyệt thông tin: {msg_reply}", None

    if action == "reject_claim":
        claim_id = action_value.get("claim_id")
        ok, msg_reply, target_claim = await claim_svc.reject_claim(
            claim_id=claim_id,
            tenant_key=tenant_key,
        )
        if ok and target_claim:
            prop = target_claim.get("property") or target_claim.get("predicate") or "thông tin"
            prop_label = PROPERTY_LABELS.get(str(prop).lower(), str(prop))
            ent_name = target_claim.get("entity_id") or "Dự án"
            val = target_claim.get("value") or ""
            updated_card = build_updated_status_card(
                title="Thông tin đề xuất",
                status_message="Đã từ chối thông tin đề xuất",
                detail_lines=[
                    f"Thực thể: {ent_name}",
                    f"Thuộc tính: {prop_label}",
                    f"Giá trị: {val}",
                    "Trạng thái: Đã từ chối (Không đưa vào bộ tri thức nhóm)",
                ],
                template="grey",
            )
            target_msg_id = message_id or action_value.get("message_id")
            if target_msg_id:
                try:
                    await lark_svc.update_card_message(target_msg_id, updated_card, tenant_key=tenant_key)
                except Exception as e:
                    logger.warning(f"Không thể cập nhật thẻ tại chỗ: {e}")
            return True, "Đã từ chối thông tin đề xuất", updated_card
        return False, f"Không thể từ chối thông tin: {msg_reply}", None

    if action == "edit_claim":
        msg_prompt = "Vui lòng nhắn trong cuộc trò chuyện này: Sửa fact: <giá trị mới> để cập nhật giá trị và phê duyệt thành chính thức."
        await lark_svc.send_bot_dm_to_owner(msg_prompt, target_open_id=open_id, tenant_key=tenant_key)
        return True, "Nhắn 'Sửa fact: <giá trị mới>' để sửa", None

    # =========================================================================
    # 3. HÀNH ĐỘNG DUYỆT BÁO CÁO NGÀY (MASTER DAILY DIGEST)
    # =========================================================================
    if action in ("approve_all_digest_claims", "approve_digest"):
        digest_id = action_value.get("digest_id")
        date_str = action_value.get("date")

        # 1. Thăng hạng toàn bộ thông tin đề xuất (claims) trong ngày thành current
        promoted_count = 0
        try:
            promoted_count, _ = await claim_svc.approve_all_pending_claims_for_date(
                date_str=date_str,
                approver_info={"user_id": open_id, "user_name": "Lãnh đạo"},
                tenant_key=tenant_key,
            )
        except Exception as e:
            logger.warning(f"Lỗi khi duyệt hàng loạt thông tin đề xuất: {e}")

        # 2. Phê duyệt và đồng bộ Master Daily Digest vào WeKnora
        ok, msg_reply, mrec = await digest_svc.approve_and_sync_master_digest(
            digest_id,
            approver_open_id=open_id,
            tenant_key=tenant_key,
        )
        if ok and mrec:
            detail_lines = [
                f"Ngày ghi nhận: {mrec.date}",
                f"Mã báo cáo: {mrec.id}",
                f"Số nhóm: {mrec.total_groups} nhóm ({mrec.total_messages} tin nhắn)",
            ]
            if promoted_count > 0:
                detail_lines.append(f"Thông tin đã duyệt: Đã thăng hạng {promoted_count} thông tin đề xuất thành chính thức")
            detail_lines.append("Trạng thái: Đã phân phối nạp chính xác vào kho tri thức WeKnora")

            updated_card = build_updated_status_card(
                title="Báo cáo tổng hợp trong ngày",
                status_message="Đã duyệt toàn bộ thông tin và đồng bộ kho tri thức thành công",
                detail_lines=detail_lines,
                template="green",
            )
            if message_id:
                try:
                    await lark_svc.update_card_message(message_id, updated_card, tenant_key=tenant_key)
                except Exception as e:
                    logger.warning(f"Không thể cập nhật thẻ tại chỗ: {e}")
            return True, "Đã duyệt và đồng bộ báo cáo thành công", updated_card
        return False, f"Không thể duyệt báo cáo: {msg_reply}", None

    if action == "reject_digest":
        digest_id = action_value.get("digest_id")
        ok, msg_reply, mrec = await digest_svc.reject_master_digest(digest_id, tenant_key=tenant_key)
        if ok and mrec:
            updated_card = build_updated_status_card(
                title="Báo cáo tổng hợp trong ngày",
                status_message="Đã từ chối báo cáo tổng hợp hôm nay",
                detail_lines=[
                    f"Mã báo cáo: {mrec.id}",
                    f"Ngày ghi nhận: {mrec.date}",
                    "Trạng thái: Đã hủy (Dữ liệu không nạp vào WeKnora)",
                ],
                template="grey",
            )
            if message_id:
                try:
                    await lark_svc.update_card_message(message_id, updated_card, tenant_key=tenant_key)
                except Exception as e:
                    logger.warning(f"Không thể cập nhật thẻ tại chỗ: {e}")
            return True, "Đã từ chối báo cáo thành công", updated_card
        return False, f"Không thể từ chối báo cáo: {msg_reply}", None

    if action == "view_digest_detail":
        latest_master = await digest_svc.get_latest_pending_master_digest(tenant_key=tenant_key)
        if latest_master:
            detail_card = build_project_digest_detail_card(latest_master)
            if message_id:
                try:
                    await lark_svc.update_card_message(message_id, detail_card, tenant_key=tenant_key)
                    return True, "Đã mở chi tiết báo cáo các nhóm", detail_card
                except Exception as e:
                    logger.warning(f"Không thể cập nhật thẻ chi tiết tại chỗ: {e}")
            await lark_svc.send_bot_card_to_owner(detail_card, target_open_id=open_id, tenant_key=tenant_key)
            return True, "Đã gửi chi tiết báo cáo vào tin nhắn", detail_card
        return False, "Không tìm thấy nội dung chi tiết báo cáo", None

    if action == "view_master_digest":
        latest_master = await digest_svc.get_latest_pending_master_digest(tenant_key=tenant_key)
        if latest_master:
            pending_claims = []
            try:
                pending_claims = await claim_svc.get_pending_claims_for_date(
                    date_str=getattr(latest_master, "date", None),
                    tenant_key=tenant_key,
                )
            except Exception as e:
                logger.warning(f"Không thể lấy pending claims khi quay lại master digest: {e}")

            cost_summary = None
            try:
                from decorators.cost_telemetry import get_cost_telemetry_summary
                cost_summary = await get_cost_telemetry_summary(hours=24)
            except Exception as e:
                logger.warning(f"Không thể lấy cost_summary khi quay lại master digest: {e}")
            master_card = build_digest_approval_card(
                latest_master,
                pending_claims=pending_claims,
                cost_summary=cost_summary,
                tenant_key=tenant_key,
            )
            if message_id:
                try:
                    await lark_svc.update_card_message(message_id, master_card, tenant_key=tenant_key)
                    return True, "Đã quay lại báo cáo tổng quan", master_card
                except Exception as e:
                    logger.warning(f"Không thể cập nhật thẻ báo cáo tại chỗ: {e}")
            await lark_svc.send_bot_card_to_owner(master_card, target_open_id=open_id, tenant_key=tenant_key)
            return True, "Đã gửi báo cáo tổng quan vào tin nhắn", master_card
        return False, "Không tìm thấy báo cáo tổng quan", None

    if action == "summarize_digest":
        latest_master = await digest_svc.get_latest_pending_master_digest(tenant_key=tenant_key)
        if latest_master:
            summary = latest_master.executive_summary or "Không có tóm tắt chung."
            await lark_svc.send_bot_dm_to_owner(
                f"Tóm tắt điều hành ngày {latest_master.date}:\n{summary}",
                target_open_id=open_id,
                tenant_key=tenant_key,
            )
            return True, "Đã gửi tóm tắt ngắn vào tin nhắn", None
        return False, "Không tìm thấy báo cáo để tóm tắt", None
        return False, "Không tìm thấy báo cáo để tóm tắt", None

    if action in ("open_onboarding", "open_onboarding_web"):
        return True, "Đang mở Trình hướng dẫn thiết lập HiLark...", None

    # =========================================================================
    # 4. HÀNH ĐỘNG ĐIỀU PHỐI QUẢN TRỊ (EXECUTIVE CONTROL HUB & STATUS)
    # =========================================================================
    if action == "view_tenant_status":
        tenant_key = action_value.get("tenant_key")
        if not tenant_key:
            try:
                from database.db import get_tenants_collection
                t_col = get_tenants_collection()
                found_t = await t_col.find_one({"admin_open_id": open_id})
                if found_t:
                    tenant_key = found_t.get("tenant_key")
            except Exception as e:
                logger.debug(f"Không thể tìm tenant cho admin {open_id}: {e}")

        tenant_cfg = None
        if tenant_key:
            from database.db import get_tenant_config
            tenant_cfg = await get_tenant_config(tenant_key)

        active_chat_count = 0
        if tenant_key:
            try:
                from database.db import get_chat_scopes_collection
                c_col = get_chat_scopes_collection()
                active_chat_count = await c_col.count_documents({"tenant_key": tenant_key})
            except Exception:
                pass

        if tenant_cfg:
            from models.tenant import TenantConfigRecord
            rec = TenantConfigRecord.from_dict(tenant_cfg) if isinstance(tenant_cfg, dict) else tenant_cfg
            status_card = build_admin_status_card(rec, active_chat_count=active_chat_count)
            if message_id:
                try:
                    await lark_svc.update_card_message(message_id, status_card, tenant_key=tenant_key)
                    return True, "Đã mở báo cáo trạng thái doanh nghiệp", status_card
                except Exception as e:
                    logger.warning(f"Không thể cập nhật thẻ tại chỗ: {e}")
            await lark_svc.send_bot_card_to_owner(status_card, target_open_id=open_id, tenant_key=tenant_key)
            return True, "Đã gửi báo cáo trạng thái doanh nghiệp", status_card
        return False, "Chưa tìm thấy cấu hình doanh nghiệp cho tài khoản của bạn", None

    if action == "view_owner_hub":
        tenant_key = action_value.get("tenant_key")
        if not tenant_key:
            try:
                from database.db import get_tenants_collection
                t_col = get_tenants_collection()
                found_t = await t_col.find_one({"admin_open_id": open_id})
                if found_t:
                    tenant_key = found_t.get("tenant_key")
            except Exception:
                pass

        tenant_cfg = None
        if tenant_key:
            from database.db import get_tenant_config
            tenant_cfg = await get_tenant_config(tenant_key)

        active_chat_count = 0
        if tenant_key:
            try:
                from database.db import get_chat_scopes_collection
                c_col = get_chat_scopes_collection()
                active_chat_count = await c_col.count_documents({"tenant_key": tenant_key})
            except Exception:
                pass

        latest_master = None
        try:
            latest_master = await digest_svc.get_latest_pending_master_digest(tenant_key=tenant_key)
        except Exception:
            pass

        if tenant_cfg:
            hub_card = build_owner_control_hub_card(
                tenant_config=tenant_cfg,
                open_id=open_id,
                pending_digest=latest_master,
                active_chat_count=active_chat_count,
            )
        else:
            hub_card = build_onboarding_welcome_card(open_id=open_id, tenant_key=tenant_key)

        if message_id:
            try:
                await lark_svc.update_card_message(message_id, hub_card, tenant_key=tenant_key)
                return True, "Đã mở Bảng điều khiển quản trị", hub_card
            except Exception as e:
                logger.warning(f"Không thể cập nhật thẻ tại chỗ: {e}")
        await lark_svc.send_bot_card_to_owner(hub_card, target_open_id=open_id, tenant_key=tenant_key)
        return True, "Bảng điều khiển quản trị", hub_card

    if action == "view_weknora_info":
        tenant_key = action_value.get("tenant_key")
        if not tenant_key:
            try:
                from database.db import get_tenants_collection
                t_col = get_tenants_collection()
                found_t = await t_col.find_one({"admin_open_id": open_id})
                if found_t:
                    tenant_key = found_t.get("tenant_key")
            except Exception:
                pass

        tenant_cfg = None
        if tenant_key:
            from database.db import get_tenant_config
            tenant_cfg = await get_tenant_config(tenant_key)

        if tenant_cfg:
            from models.tenant import TenantConfigRecord
            rec = TenantConfigRecord.from_dict(tenant_cfg) if isinstance(tenant_cfg, dict) else tenant_cfg
            creds = rec.weknora_admin_user
            ent_name = rec.enterprise_name
            uname = creds.username if creds else "admin"
            pwd = creds.initial_password if creds else ""
            wurl = creds.web_url if creds else getattr(settings, "WEKNORA_WEB_URL", "http://localhost/login")

            info_card = build_updated_status_card(
                title=f"Kho Tri Thức WeKnora — {ent_name}",
                status_message="Thông tin tài khoản WeKnora Web Console riêng biệt",
                detail_lines=[
                    f"Cổng đăng nhập: {wurl}",
                    f"Tài khoản quản trị: {uname}",
                    f"Mật khẩu ban đầu: {pwd}",
                    "Quyền hạn: Toàn quyền truy xuất và tra cứu Wiki toàn công ty",
                ],
                template="wathet",
            )
            if message_id:
                try:
                    await lark_svc.update_card_message(message_id, info_card, tenant_key=tenant_key)
                    return True, "Đã hiển thị thông tin WeKnora", info_card
                except Exception as e:
                    logger.warning(f"Không thể cập nhật thẻ tại chỗ: {e}")
            await lark_svc.send_bot_card_to_owner(info_card, target_open_id=open_id, tenant_key=tenant_key)
            return True, "Đã gửi thông tin WeKnora", info_card
        return False, "Không tìm thấy cấu hình WeKnora cho doanh nghiệp", None

    return False, f"Chưa hỗ trợ thao tác '{action}'", None

