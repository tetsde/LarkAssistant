
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

import asyncio
import json
import logging
import sys
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("hilark.bot.card_action_handler")

# Cache chống xử lý trùng lặp và lưu kết quả thẻ đã xử lý (chống race condition khi Lark retry / gửi webhook song song)
# key: dedup_key -> (timestamp, Optional[result_tuple])
_PROCESSED_CARD_ACTIONS: OrderedDict[str, Tuple[float, Optional[Tuple[bool, str, Optional[Dict[str, Any]]]]]] = OrderedDict()
_ACTION_LOCK = threading.Lock()

READ_ONLY_ACTIONS = {
    "view_owner_hub",
    "view_weknora_info",
    "view_digest_detail",
    "manual_edit_draft",
    "cancel_manual_edit",
}

from services.claim_service import claim_service as default_claim_service
from services.digest_service import digest_service as default_digest_service
from services.draft_service import draft_service as default_draft_service
from services.lark import lark_service as default_lark_service
from services.lark.card_builder import (
    PROPERTY_LABELS,
    build_draft_card,
    build_draft_edit_form_card,
    build_onboarding_welcome_card,
    build_owner_control_hub_card,
    build_project_digest_detail_card,
    build_updated_status_card,
)


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

    # Trích xuất form_value nếu có (hỗ trợ component form & textarea trong Card JSON 2.0)
    event_dict = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    action_dict = event_dict.get("action") if event_dict else (payload.get("action") or {})
    form_val = (
        event_dict.get("form_value")
        or (action_dict.get("form_value") if isinstance(action_dict, dict) else None)
        or payload.get("form_value")
    )
    if form_val and isinstance(form_val, dict) and "form_value" not in action_val:
        action_val["form_value"] = form_val
    input_val = (
        event_dict.get("input_value")
        or (action_dict.get("input_value") if isinstance(action_dict, dict) else None)
        or payload.get("input_value")
    )
    if input_val and "input_value" not in action_val:
        action_val["input_value"] = input_val
    name_val = (
        (action_dict.get("name") if isinstance(action_dict, dict) else None)
        or event_dict.get("name")
        or payload.get("name")
    )
    if name_val and "name" not in action_val:
        action_val["name"] = name_val
    tag_val = (
        (action_dict.get("tag") if isinstance(action_dict, dict) else None)
        or event_dict.get("tag")
        or payload.get("tag")
    )
    if tag_val and "tag" not in action_val:
        action_val["tag"] = tag_val

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
    """Điều phối xử lý hành động thẻ: chống race condition, cache kết quả và gọi hàm thực thi."""
    action = action_value.get("action")
    if not action:
        btn_name = str(action_value.get("name") or "").strip()
        form_val = action_value.get("form_value") or {}

        if btn_name in ("btn_approve_draft", "approve_draft"):
            action = "approve_draft"
        elif btn_name in ("btn_manual_edit_draft", "manual_edit_draft"):
            action = "manual_edit_draft"
        elif btn_name in ("btn_discard_draft", "discard_draft"):
            action = "discard_draft"
        elif btn_name in ("submit_manual_edit", "btn_submit_manual_edit", "submit_btn", "btn_submit"):
            action = "submit_manual_edit"
        elif btn_name in ("cancel_manual_edit", "btn_cancel_manual_edit", "cancel_btn", "btn_cancel"):
            action = "cancel_manual_edit"
        elif ("edited_content" in form_val) or ("edited_content" in action_value) or (form_val and not action):
            action = "submit_manual_edit"
        elif btn_name in ("btn_approve_claim", "approve_claim"):
            action = "approve_claim"
        elif btn_name in ("btn_reject_claim", "reject_claim"):
            action = "reject_claim"
        elif btn_name in ("btn_edit_claim", "edit_claim"):
            action = "edit_claim"
        elif btn_name in ("btn_approve_digest", "approve_digest"):
            action = "approve_digest"
        elif btn_name in ("btn_discard_digest", "discard_digest"):
            action = "discard_digest"

    if not action:
        return False, "Không xác định được hành động từ thẻ", None

    dedup_key = f"{open_id}:{message_id}:{action}:{action_value.get('draft_id', '')}"
    now = time.time()
    wait_for_in_flight = False

    with _ACTION_LOCK:
        while _PROCESSED_CARD_ACTIONS and (now - next(iter(_PROCESSED_CARD_ACTIONS.values()))[0] > 15.0):
            _PROCESSED_CARD_ACTIONS.popitem(last=False)

        if dedup_key in _PROCESSED_CARD_ACTIONS:
            cached_ts, cached_res = _PROCESSED_CARD_ACTIONS[dedup_key]
            if (now - cached_ts) < 8.0:
                if cached_res is not None:
                    logger.debug("[CARD_ACTION] dedup_cache_hit key=%s", dedup_key)
                    return cached_res
                else:
                    wait_for_in_flight = True
            else:
                _PROCESSED_CARD_ACTIONS[dedup_key] = (now, None)
        else:
            _PROCESSED_CARD_ACTIONS[dedup_key] = (now, None)

    if wait_for_in_flight:
        for _ in range(25):
            await asyncio.sleep(0.1)
            with _ACTION_LOCK:
                if dedup_key in _PROCESSED_CARD_ACTIONS:
                    _, cached_res = _PROCESSED_CARD_ACTIONS[dedup_key]
                    if cached_res is not None:
                        logger.debug("[CARD_ACTION] dedup_wait_hit key=%s", dedup_key)
                        return cached_res

        if action not in READ_ONLY_ACTIONS:
            logger.info("[CARD_ACTION] dedup_skipped key=%s", dedup_key)
            return True, "Thao tác đã được ghi nhận", None
        logger.debug("[CARD_ACTION] dedup_fallback_render action=%s", action)

    result: Tuple[bool, str, Optional[Dict[str, Any]]] = (False, "Lỗi chưa xác định", None)
    try:
        result = await _do_execute_card_action(open_id, message_id, action, action_value, tenant_key)
    finally:
        with _ACTION_LOCK:
            _PROCESSED_CARD_ACTIONS[dedup_key] = (time.time(), result)

    return result


async def _do_execute_card_action(
    open_id: str,
    message_id: str,
    action: str,
    action_value: Dict[str, Any],
    tenant_key: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Thực thi logic nội bộ hành động thẻ với tenant context đã xác định."""
    # Lazy load lark_svc khi thực sự cần (tránh lãng phí 2000-3000ms query DB + refresh OIDC token cho các action đơn giản)
    _cached_lark_svc = None

    async def _get_action_lark_svc():
        nonlocal _cached_lark_svc
        if _cached_lark_svc is None:
            _cached_lark_svc = _resolve_service("lark_service", default_lark_service)
            if tenant_key:
                try:
                    from services.lark_app_service import lark_app_service
                    from services.lark.runtime import get_or_create_lark_service
                    app_rec = await lark_app_service.get_by_tenant_key(tenant_key)
                    if app_rec:
                        _cached_lark_svc = await get_or_create_lark_service(app_rec)
                except Exception as e:
                    logger.debug(f"Không thể resolve lark_svc cho tenant {tenant_key}: {e}")
        return _cached_lark_svc

    draft_svc = _resolve_service("draft_service", default_draft_service)
    claim_svc = _resolve_service("claim_service", default_claim_service)
    digest_svc = _resolve_service("digest_service", default_digest_service)

    logger.info(
        "[CARD_ACTION] execute action=%s user=%s msg=%s tenant=%s",
        action,
        open_id,
        message_id,
        tenant_key or "-",
    )

    # =========================================================================
    # 1. HÀNH ĐỘNG DUYỆT BẢN NHÁP CÂU TRẢ LỜI
    # =========================================================================
    if action == "approve_draft":
        try:
            ok, detail, draft, _ = await draft_svc.send_latest(open_id, tenant_key=tenant_key, background=True)
        except TypeError:
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
            # Lưu ý: Cập nhật thẻ đồng bộ qua Sync Response (tránh double patch gây xung đột version và lỗi 200341)
            return True, "Đã gửi câu trả lời vào nhóm thành công", updated_card

        # Idempotency check: Nếu bấm đúp hoặc retry do mạng chậm, kiểm tra xem bản nháp đã vừa được gửi chưa
        try:
            from services.workflows.draft_store import _get_collection, inject_tenant_filter
            recent_sent = await _get_collection().find_one(
                inject_tenant_filter({"owner_id": open_id, "status": "sent"}, tenant_key),
                sort=[("updated_at", -1)],
            )
            if recent_sent:
                resp_name = recent_sent.get("responder_name") or "User"
                appr_content = recent_sent.get("approved_content") or recent_sent.get("draft_answer") or ""
                updated_card = build_updated_status_card(
                    title="Bản nháp câu trả lời",
                    status_message="Đã duyệt và gửi câu trả lời vào nhóm thảo luận",
                    detail_lines=[
                        f"Người trả lời: {resp_name}",
                        f"Nội dung đã gửi: \"{appr_content}\"",
                    ],
                    template="green",
                )
                return True, "Đã gửi câu trả lời vào nhóm thành công", updated_card
        except Exception as check_err:
            logger.debug(f"Không thể kiểm tra idempotency recent_sent: {check_err}")

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
            return True, "Đã hủy bỏ bản nháp thành công", updated_card
        return False, "Hiện không có bản nháp nào đang chờ duyệt để hủy", None

    if action == "manual_edit_draft":
        target_draft_id = action_value.get("draft_id")
        draft = None
        if target_draft_id:
            try:
                from services.workflows.draft_store import _get_collection, inject_tenant_filter
                doc = await _get_collection().find_one(
                    inject_tenant_filter({"status": "pending", "$or": [{"id": target_draft_id}, {"message_id": target_draft_id}]}, tenant_key)
                )
                if doc:
                    from models.chat import PendingDraft
                    draft = PendingDraft.from_document(doc)
            except Exception as e:
                logger.debug(f"Không thể tìm draft theo draft_id {target_draft_id}: {e}")
        if not draft:
            draft = await draft_svc.get_latest_pending(open_id, tenant_key=tenant_key)
        if draft:
            d_query = getattr(draft, "query", "") or (draft.get("query") if isinstance(draft, dict) else "") or ""
            d_answer = (
                getattr(draft, "approved_content", None)
                or (draft.get("approved_content") if isinstance(draft, dict) else None)
                or getattr(draft, "draft_answer", "")
                or (draft.get("draft_answer") if isinstance(draft, dict) else "")
                or ""
            )
            d_user = getattr(draft, "user_name", "Thành viên") or (draft.get("user_name") if isinstance(draft, dict) else "Thành viên") or "Thành viên"
            d_id = getattr(draft, "id", "") or (draft.get("id") if isinstance(draft, dict) else "") or action_value.get("draft_id", "")
            d_chat_id = getattr(draft, "chat_id", "") or (draft.get("chat_id") if isinstance(draft, dict) else "") or "Nhóm thảo luận"

            edit_card = build_draft_edit_form_card(
                draft_id=d_id,
                chat_title=d_chat_id,
                user_name=d_user,
                query=d_query,
                draft_answer=d_answer,
                tenant_key=tenant_key,
            )
            return True, "Đã mở khung chỉnh sửa câu trả lời", edit_card
        return False, "Hiện không có bản nháp nào đang chờ duyệt để chỉnh sửa", None

    if action == "submit_manual_edit":
        # Trích xuất nội dung sau khi chỉnh sửa từ form_value hoặc action_value (hỗ trợ linh hoạt mọi key component)
        form_val = action_value.get("form_value") or {}
        single_form_val = list(form_val.values())[0] if form_val and isinstance(form_val, dict) and len(form_val) == 1 else ""
        edited_content = (
            form_val.get("edited_content")
            or action_value.get("edited_content")
            or action_value.get("input_value")
            or single_form_val
            or ""
        )
        if not edited_content or not str(edited_content).strip():
            return False, "Vui lòng nhập nội dung câu trả lời trước khi gửi", None

        target_draft_id = action_value.get("draft_id")
        try:
            ok, detail, draft, _ = await draft_svc.send_latest(
                open_id,
                approved_content=str(edited_content).strip(),
                tenant_key=tenant_key,
                background=True,
                draft_id=target_draft_id,
            )
        except TypeError:
            ok, detail, draft, _ = await draft_svc.send_latest(
                open_id,
                approved_content=str(edited_content).strip(),
                tenant_key=tenant_key,
                background=True,
            )
        if ok and draft:
            resp_name = getattr(draft, "responder_name", None) or (draft.get("responder_name") if isinstance(draft, dict) else None) or "User"
            appr_content = getattr(draft, "approved_content", None) or (draft.get("approved_content") if isinstance(draft, dict) else None) or str(edited_content).strip()
            updated_card = build_updated_status_card(
                title="Bản nháp câu trả lời",
                status_message="Đã chỉnh sửa và gửi câu trả lời vào nhóm thảo luận",
                detail_lines=[
                    f"Người trả lời: {resp_name}",
                    f"Nội dung đã gửi: \"{appr_content}\"",
                ],
                template="green",
            )
            return True, "Đã gửi câu trả lời đã chỉnh sửa vào nhóm thành công", updated_card

        # Idempotency check: Nếu bấm đúp hoặc retry do mạng chậm, kiểm tra xem bản nháp đã vừa được gửi chưa
        try:
            from services.workflows.draft_store import _get_collection, inject_tenant_filter
            sent_filters: Dict[str, Any] = {"status": "sent"}
            if target_draft_id:
                sent_filters["$or"] = [{"id": target_draft_id}, {"message_id": target_draft_id}]
            else:
                sent_filters["owner_id"] = open_id
            recent_sent = await _get_collection().find_one(
                inject_tenant_filter(sent_filters, tenant_key),
                sort=[("updated_at", -1)],
            )
            if recent_sent:
                resp_name = recent_sent.get("responder_name") or "User"
                appr_content = recent_sent.get("approved_content") or recent_sent.get("draft_answer") or str(edited_content).strip()
                updated_card = build_updated_status_card(
                    title="Bản nháp câu trả lời",
                    status_message="Đã chỉnh sửa và gửi câu trả lời vào nhóm thảo luận",
                    detail_lines=[
                        f"Người trả lời: {resp_name}",
                        f"Nội dung đã gửi: \"{appr_content}\"",
                    ],
                    template="green",
                )
                return True, "Đã gửi câu trả lời đã chỉnh sửa vào nhóm thành công", updated_card
        except Exception as check_err:
            logger.debug(f"Không thể kiểm tra idempotency recent_sent: {check_err}")

        return False, f"Chưa thể gửi bản nháp đã sửa: {detail}", None

    if action == "cancel_manual_edit":
        target_draft_id = action_value.get("draft_id")
        draft = None
        if target_draft_id:
            try:
                from services.workflows.draft_store import _get_collection, inject_tenant_filter
                doc = await _get_collection().find_one(
                    inject_tenant_filter({"status": "pending", "$or": [{"id": target_draft_id}, {"message_id": target_draft_id}]}, tenant_key)
                )
                if doc:
                    from models.chat import PendingDraft
                    draft = PendingDraft.from_document(doc)
            except Exception as e:
                logger.debug(f"Không thể tìm draft theo draft_id {target_draft_id}: {e}")
        if not draft:
            draft = await draft_svc.get_latest_pending(open_id, tenant_key=tenant_key)
        if draft:
            d_query = getattr(draft, "query", "") or (draft.get("query") if isinstance(draft, dict) else "") or ""
            d_answer = (
                getattr(draft, "approved_content", None)
                or (draft.get("approved_content") if isinstance(draft, dict) else None)
                or getattr(draft, "draft_answer", "")
                or (draft.get("draft_answer") if isinstance(draft, dict) else "")
                or ""
            )
            d_user = getattr(draft, "user_name", "Thành viên") or (draft.get("user_name") if isinstance(draft, dict) else "Thành viên") or "Thành viên"
            d_id = getattr(draft, "id", "") or (draft.get("id") if isinstance(draft, dict) else "") or action_value.get("draft_id", "")
            d_chat_id = getattr(draft, "chat_id", "") or (draft.get("chat_id") if isinstance(draft, dict) else "") or "Nhóm thảo luận"

            original_card = build_draft_card(
                draft_id=d_id,
                chat_title=d_chat_id,
                user_name=d_user,
                query=d_query,
                draft_answer=d_answer,
                reason="Bản nháp câu trả lời đang chờ duyệt.",
                tenant_key=tenant_key,
            )
            return True, "Đã quay lại bản nháp ban đầu", original_card
        return True, "Đã đóng khung chỉnh sửa", None

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
            return True, "Đã từ chối thông tin đề xuất", updated_card
        return False, f"Không thể từ chối thông tin: {msg_reply}", None

    if action == "edit_claim":
        msg_prompt = "Vui lòng nhắn trong cuộc trò chuyện này: Sửa fact: <giá trị mới> để cập nhật giá trị và phê duyệt thành chính thức."
        active_lark_svc = await _get_action_lark_svc()
        await active_lark_svc.send_bot_dm_to_owner(msg_prompt, target_open_id=open_id, tenant_key=tenant_key)
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
            return True, "Đã từ chối báo cáo thành công", updated_card
        return False, f"Không thể từ chối báo cáo: {msg_reply}", None

    if action == "view_digest_detail":
        latest_master = await digest_svc.get_latest_pending_master_digest(tenant_key=tenant_key)
        if latest_master:
            detail_card = build_project_digest_detail_card(latest_master)
            return True, "Đã mở chi tiết báo cáo các nhóm", detail_card
        return False, "Không tìm thấy nội dung chi tiết báo cáo", None

    if action == "summarize_digest":
        latest_master = await digest_svc.get_latest_pending_master_digest(tenant_key=tenant_key)
        if latest_master:
            summary = latest_master.executive_summary or "Không có tóm tắt chung."
            active_lark_svc = await _get_action_lark_svc()
            await active_lark_svc.send_bot_dm_to_owner(
                f"Tóm tắt điều hành ngày {latest_master.date}:\n{summary}",
                target_open_id=open_id,
                tenant_key=tenant_key,
            )
            return True, "Đã gửi tóm tắt ngắn vào tin nhắn", None
        return False, "Không tìm thấy báo cáo để tóm tắt", None

    if action in ("open_onboarding", "open_onboarding_web"):
        return True, "Đang mở Trình hướng dẫn thiết lập HiLark...", None

    # =========================================================================
    # 4. HÀNH ĐỘNG ĐIỀU PHỐI QUẢN TRỊ (EXECUTIVE CONTROL HUB)
    # =========================================================================
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
            return True, "Đã hiển thị thông tin WeKnora", info_card
        return False, "Không tìm thấy cấu hình WeKnora cho doanh nghiệp", None

    return False, f"Chưa hỗ trợ thao tác '{action}'", None

