"""
Message Recall Orchestrator for Lark Bot
========================================
Vị trí: server/services/lark/handlers/recall_handler.py

Mục đích:
    Xử lý sự kiện thu hồi tin nhắn từ Lark (im.message.recalled_v1):
      1. Tầng 1: Đánh dấu is_recalled: True trong conversation_staging (loại bỏ khỏi Daily Digest).
      2. Tầng 2: Huỷ bỏ các đề xuất tri thức PROPOSED -> REVOKED, gắn cờ source_recalled cho CURRENT facts.
      3. Tầng 3: Huỷ các bản nháp (drafts) đang chờ duyệt liên quan đến tin nhắn gốc.
      4. Tầng 4: Tự động thu hồi câu trả lời của Bot nếu bot từng reply tin nhắn này.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional

from lark_oapi.api.im.v1 import P2ImMessageRecalledV1

from database.db import (
    cancel_pending_drafts_by_message_id,
    recall_staging_message,
    revoke_claims_by_message_id,
)
from services.lark import lark_service as default_lark_service

logger = logging.getLogger("hilark.bot.recall_handler")


def _resolve_lark_service():
    """Lấy lark_service instance phù hợp từ context runtime."""
    from services.lark.runtime import get_current_lark_service
    bs = sys.modules.get("services.bot_service") or sys.modules.get("services.lark.bot_runner")
    fallback = getattr(bs, "lark_service", default_lark_service) if bs else default_lark_service
    return get_current_lark_service(fallback)


async def handle_message_recalled(event: P2ImMessageRecalledV1) -> Dict[str, Any]:
    """
    Xử lý sự kiện người dùng hoặc lãnh đạo thu hồi tin nhắn trên Lark (im.message.recalled_v1).
    Đồng bộ dữ liệu trên toàn bộ 4 tầng hệ thống.
    """
    event_data = getattr(event, "event", None)
    if not event_data:
        logger.warning("[RECALL] ignored reason=empty_event_data")
        return {"success": False, "error": "Event data is empty"}

    message_id = getattr(event_data, "message_id", "") or ""
    chat_id = getattr(event_data, "chat_id", "") or ""
    recall_time = getattr(event_data, "recall_time", "") or ""
    recall_type = getattr(event_data, "recall_type", "") or "message_owner"

    if not message_id:
        logger.warning("[RECALL] ignored reason=missing_message_id")
        return {"success": False, "error": "Missing message_id"}

    logger.info(
        "[RECALL] start msg=%s chat=%s type=%s recall_time=%s",
        message_id,
        chat_id or "-",
        recall_type,
        recall_time or "-",
    )

    lark_service = _resolve_lark_service()

    # ── [TẦNG 1: STAGING & DAILY DIGEST GUARD] ──
    recalled_stg = None
    try:
        recalled_stg = await recall_staging_message(
            message_id=message_id,
            recall_time=str(recall_time) if recall_time else None,
            recall_type=recall_type,
        )
        if recalled_stg:
            logger.debug("[RECALL] staging_marked msg=%s", message_id)
        else:
            logger.debug("[RECALL] staging_not_found msg=%s", message_id)
    except Exception as e:
        logger.error("[RECALL] staging_failed msg=%s error=%s", message_id, e, exc_info=True)

    # ── [TẦNG 2: TRI THỨC & CLAIMS REVOCATION] ──
    claims_revoked = 0
    claims_flagged = 0
    try:
        rev_res = await revoke_claims_by_message_id(
            message_id=message_id,
            reason=f"Tin nhắn gốc đã bị người dùng thu hồi (recall_type={recall_type})",
        )
        claims_revoked = rev_res.get("proposed_revoked", 0)
        claims_flagged = rev_res.get("current_flagged", 0)
        if claims_revoked > 0 or claims_flagged > 0:
            logger.info("[RECALL] claims_updated msg=%s revoked=%d flagged=%d", message_id, claims_revoked, claims_flagged)
        else:
            logger.debug("[RECALL] claims_none msg=%s", message_id)
    except Exception as e:
        logger.error("[RECALL] claims_failed msg=%s error=%s", message_id, e, exc_info=True)

    # ── [TẦNG 3: DRAFT LOGS CANCELLATION] ──
    drafts_cancelled = 0
    try:
        drafts_cancelled = await cancel_pending_drafts_by_message_id(
            message_id=message_id,
            reason="Tin nhắn gốc đã bị thu hồi trên Lark",
        )
        if drafts_cancelled > 0:
            logger.info("[RECALL] drafts_cancelled msg=%s count=%d", message_id, drafts_cancelled)
    except Exception as e:
        logger.error("[RECALL] drafts_failed msg=%s error=%s", message_id, e, exc_info=True)

    # ── [TẦNG 4: USER/BOT REPLY CASCADE RECALL] ──
    bot_reply_recalled = False
    reply_id = recalled_stg.get("bot_reply_message_id") if recalled_stg else None
    eff_tenant = recalled_stg.get("tenant_key") if recalled_stg else None

    # Fallback: Tra cứu trong draft_logs nếu staging chưa kịp lưu hoặc không có
    if not reply_id:
        try:
            from database.db import get_draft_logs_collection
            d_col = get_draft_logs_collection()
            d_doc = await d_col.find_one({
                "message_id": message_id,
                "bot_reply_message_id": {"$exists": True, "$ne": None},
            })
            if d_doc:
                reply_id = d_doc.get("bot_reply_message_id")
                if not eff_tenant:
                    eff_tenant = d_doc.get("tenant_key")
        except Exception as ex:
            logger.debug("[RECALL] draft_reply_lookup_failed msg=%s error=%s", message_id, ex)

    if reply_id:
        logger.debug("[RECALL] cascade_start msg=%s reply_id=%s", message_id, reply_id)
        try:
            recall_resp = await lark_service.arecall_message(reply_id, tenant_key=eff_tenant)
            if isinstance(recall_resp, dict) and recall_resp.get("success"):
                bot_reply_recalled = True
                logger.info("[RECALL] cascade_ok msg=%s reply_id=%s", message_id, reply_id)
            else:
                err_msg = recall_resp.get("msg") or recall_resp.get("error") if isinstance(recall_resp, dict) else str(recall_resp)
                logger.warning("[RECALL] cascade_failed msg=%s reply_id=%s error=%s", message_id, reply_id, err_msg)
        except Exception as e:
            logger.error("[RECALL] cascade_error msg=%s reply_id=%s error=%s", message_id, reply_id, e, exc_info=True)
    else:
        logger.debug("[RECALL] cascade_skipped msg=%s reason=no_reply_id", message_id)

    logger.info(
        "[RECALL] completed msg=%s staging=%s revoked=%d flagged=%d drafts=%d reply_recalled=%s",
        message_id,
        bool(recalled_stg),
        claims_revoked,
        claims_flagged,
        drafts_cancelled,
        bot_reply_recalled,
    )

    return {
        "success": True,
        "message_id": message_id,
        "chat_id": chat_id,
        "staging_recalled": bool(recalled_stg),
        "proposed_claims_revoked": claims_revoked,
        "current_claims_flagged": claims_flagged,
        "drafts_cancelled": drafts_cancelled,
        "bot_reply_recalled": bot_reply_recalled,
    }
