"""
Member Message & Group Chat Orchestrator for Lark Bot
=====================================================
Vị trí: server/services/bot_handlers/member_message_handler.py

Mục đích:
    - Xử lý các tin nhắn thông thường từ thành viên hoặc chủ nhân trong nhóm:
      1. Nhận diện danh tính người gửi / người được hỏi.
      2. Lưu tin nhắn vào conversation_staging phục vụ Daily Digest.
      3. Điều phối tin nhắn Chủ nhân vào Chat Pipeline (chế độ âm thầm trích xuất facts).
      4. Điều phối tin nhắn Thành viên vào Smart Debouncer Queue (1.75s gom tin).
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from core.tenant_errors import TenantResolutionError, TokenUnavailable
from database.scoped_query import inject_tenant_filter
from database.db import (
    get_staging_collection,
    promote_claims_by_message_id,
    reject_claims_by_message_id,
)
from models.lark import LarkMessage
from services.ai.jev_classifier import jev_service
from services.chat_service import process_chat_pipeline
from services.digest_service import digest_service
from services.lark import lark_service as default_lark_service
from services.lark.tenant_error_reply import notify_tenant_error
from services.workflows.chat_queue import chat_queue_service

logger = logging.getLogger("hilark.bot.member_message_handler")


def _resolve_lark_service():
    from services.lark.runtime import get_current_lark_service
    bs = sys.modules.get("services.bot_service") or sys.modules.get("services.lark.bot_runner")
    fallback = getattr(bs, "lark_service", default_lark_service) if bs else default_lark_service
    return get_current_lark_service(fallback)


async def handle_member_message(msg: LarkMessage, is_owner: bool = False) -> None:
    """
    Điều phối tin nhắn thông thường của người dùng vào Staging và Chat Pipeline / Queue.
    """
    lark_service = _resolve_lark_service()
    # Dùng danh tính và chức danh theo đúng tenant từ DB (không vay biến toàn cục .env).
    try:
        user_info = lark_service.get_current_user(tenant_key=msg.tenant_key)
    except TypeError:
        user_info = lark_service.get_current_user()
    responder_name = (user_info.get("name") if isinstance(user_info, dict) else None) or None

    # Nhận diện tên đích danh người hỏi
    target_user_name = None
    if msg.mentions:
        for m in msg.mentions:
            m_name = m.get("name", "")
            if m_name and not (
                "bot" in m_name.lower()
                or "hilark" in m_name.lower()
                or (responder_name and m_name.lower() in responder_name.lower())
                or (responder_name and responder_name.lower() in m_name.lower())
            ):
                target_user_name = m_name
                break

    if not target_user_name and msg.sender_id:
        try:
            sender_real_name = lark_service.get_user_name(msg.sender_id, tenant_key=msg.tenant_key)
        except TypeError:
            sender_real_name = lark_service.get_user_name(msg.sender_id)
        if sender_real_name:
            target_user_name = sender_real_name

    target_user_name = target_user_name or "bạn"

    # Tự động lưu tin nhắn vào staging cho Daily Digest
    if msg.chat_type == "group" and msg.text:
        try:
            if is_owner:
                speaker = (
                    responder_name
                    or user_info.get("name")
                    or (target_user_name if target_user_name != "bạn" else None)
                    or "Lãnh đạo"
                )
            else:
                speaker = target_user_name if target_user_name != "bạn" else "Thành viên"
            await digest_service.add_staging_message(
                message_id=msg.message_id,
                chat_id=msg.chat_id,
                text=msg.text,
                speaker_name=speaker,
                speaker_id=msg.sender_id,
                chat_name=msg.chat_id,
                tenant_key=msg.tenant_key,
            )
            logger.debug("[STORE] msg=%s staging=yes speaker=%s", msg.message_id, speaker)
        except Exception as e:
            logger.warning("[STORE] msg=%s staging=failed error=%s", msg.message_id, e)

    # Chuyển vào Unified Chat Pipeline
    if is_owner:
        query_to_run = msg.text

        # ── [TIER 2: SMART THREAD REPLY VIA JEV] ──
        # Nếu Lãnh đạo đang reply một tin nhắn cụ thể trong thread
        if msg.parent_id:
            parent_text: Optional[str] = None
            try:
                staging_query = inject_tenant_filter({"message_id": msg.parent_id}, msg.tenant_key)
                parent_doc = await get_staging_collection().find_one(staging_query)
                if parent_doc and parent_doc.get("text"):
                    parent_text = parent_doc["text"]
            except Exception as e:
                logger.debug(f"Không lấy được parent text từ staging: {e}")

            if not parent_text:
                try:
                    try:
                        res = lark_service.get_message(msg.parent_id, as_user=False, tenant_key=msg.tenant_key)
                    except TypeError:
                        res = lark_service.get_message(msg.parent_id)
                    if res.get("success") and res.get("data"):
                        data_obj = res["data"]
                        items = getattr(data_obj, "items", None) or [data_obj]
                        if items and len(items) > 0:
                            body = getattr(items[0], "body", None)
                            raw_c = getattr(body, "content", "{}") if body else "{}"
                            import json
                            c_dict = json.loads(raw_c) if isinstance(raw_c, str) else raw_c
                            parent_text = c_dict.get("text", "") if isinstance(c_dict, dict) else str(c_dict)
                except Exception as e:
                    logger.debug(f"Không lấy được parent message qua Lark API: {e}")

            if parent_text:
                logger.info("[THREAD] msg=%s parent=%s action=classify", msg.message_id, msg.parent_id)
                try:
                    decision_res = await jev_service.classify_thread_decision(
                        parent_text=parent_text,
                        reply_text=msg.text,
                        tenant_key=msg.tenant_key,
                        open_id=msg.sender_id,
                    )
                except (TenantResolutionError, TokenUnavailable) as e:
                    logger.warning(
                        "[DROP] msg=%s reason=%s error=%s",
                        msg.message_id,
                        getattr(e, "error_code", type(e).__name__),
                        e,
                    )
                    await notify_tenant_error(
                        e,
                        message_id=msg.message_id,
                        chat_id=msg.chat_id,
                        tenant_key=msg.tenant_key,
                    )
                    return
                decision = decision_res.get("decision", "CHAT_ONLY")
                conf = decision_res.get("confidence", 0.0)
                logger.info("[THREAD] msg=%s decision=%s confidence=%.2f", msg.message_id, decision, conf)

                # CHAT_ONLY nghĩa là phản hồi trao đổi bình thường trong thread.
                # Không được rơi tiếp xuống classify_message() chung, nếu không
                # câu trả lời của sếp sẽ bị hiểu nhầm là MEMORY_ONLY và tạo claims.
                if decision == "CHAT_ONLY":
                    logger.info("[THREAD] msg=%s decision=CHAT_ONLY staging=yes memory=no", msg.message_id)
                    return

                approver_info = {
                    "user_id": msg.sender_id,
                    "user_name": responder_name,
                    "role": "owner",
                }

                if decision == "APPROVE_AS_IS":
                    # FAST-LANE: 0 TOKEN LLM, 0ms latency, 0% regex!
                    promoted = await promote_claims_by_message_id(
                        msg.parent_id,
                        approver_info=approver_info,
                        tenant_key=msg.tenant_key,
                    )
                    logger.info("[THREAD] msg=%s decision=APPROVE_AS_IS promoted=%d", msg.message_id, promoted)
                    return

                elif decision == "REJECT":
                    rejected = await reject_claims_by_message_id(
                        msg.parent_id,
                        tenant_key=msg.tenant_key,
                    )
                    logger.info("[THREAD] msg=%s decision=REJECT rejected=%d", msg.message_id, rejected)
                    return

                elif decision == "APPROVE_WITH_CHANGES":
                    # LLM MODIFICATION LANE: Nối ngữ cảnh đề xuất + điều chỉnh của sếp
                    logger.info("[THREAD] msg=%s decision=APPROVE_WITH_CHANGES", msg.message_id)
                    query_to_run = (
                        f"Đề xuất ban đầu từ nhân sự: \"{parent_text}\"\n"
                        f"Quyết định điều chỉnh và phê duyệt của Lãnh đạo: \"{msg.text}\""
                    )

        logger.debug("[ROUTE] msg=%s speaker=owner pipeline=chat reply=false", msg.message_id)
        try:
            result = await process_chat_pipeline(
                query=query_to_run,
                sender=msg.sender_id,
                channel=f"lark_{msg.chat_type}",
                message_id=msg.message_id,
                chat_id=msg.chat_id,
                reply_to_lark=False,
                user_name=target_user_name,
                responder_name=responder_name,
                role=None,
                is_owner=True,
                tenant_key=msg.tenant_key,
            )
        except (TenantResolutionError, TokenUnavailable) as e:
            # Doanh nghiệp chưa ready / thiếu credential / cần uỷ quyền lại: nói rõ
            # trong chat thay vì chỉ log (GĐ5 hợp đồng phản hồi người dùng).
            logger.warning(
                "[DROP] msg=%s reason=%s error=%s", msg.message_id, e.error_code, e
            )
            await notify_tenant_error(
                e, message_id=msg.message_id, chat_id=msg.chat_id, tenant_key=msg.tenant_key
            )
            return
        except Exception as e:
            logger.error(f"Lỗi pipeline: {e}", exc_info=True)
            return

        # Hiển thị kết quả định tuyến của JEV cho chủ nhân
        jev_action = result.get("jev_action", "IGNORE")
        confidence = result.get("jev_confidence", 0.0)
        status = result.get("status", "")

        logger.info("[ROUTE] msg=%s action=%s confidence=%.2f status=%s", msg.message_id, jev_action, confidence, status)

        if status == "forbidden_query":
            chk = result.get("forbidden_check") or {}
            matched = chk.get("matched_label") or "Chủ đề bị cấm"
            logger.warning("[DROP] msg=%s reason=forbidden label=%s", msg.message_id, matched)
        elif status == "group_inactive":
            logger.info("[DROP] msg=%s reason=group_inactive", msg.message_id)
        elif jev_action == "IGNORE":
            logger.info("[STORE] msg=%s staging=yes memory=no reason=jev_ignore", msg.message_id)
        elif jev_action == "MEMORY_ONLY":
            ext = result.get("extraction") or {}
            num_ent = len(ext.get("entities", []))
            num_facts = len(ext.get("facts", []))
            logger.info("[STORE] msg=%s staging=yes memory=yes entities=%d facts=%d", msg.message_id, num_ent, num_facts)
    else:
        # Thành viên trong nhóm: đưa vào Smart Debouncer (1.75s) và Throttled Queue
        logger.debug(
            "[QUEUE] msg=%s speaker=%s debounce=%.2fs",
            msg.message_id,
            target_user_name,
            getattr(getattr(chat_queue_service, "debouncer", None), "debounce_seconds", 1.75),
        )
        await chat_queue_service.push_incoming_message(
            msg=msg,
            user_name=target_user_name,
            responder_name=responder_name,
            role=None,
        )
