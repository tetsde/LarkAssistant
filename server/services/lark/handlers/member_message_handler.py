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

from core.config import settings
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
from services.workflows.chat_queue import chat_queue_service

logger = logging.getLogger("hilark.bot.member_message_handler")


def _resolve_lark_service():
    bs = sys.modules.get("services.bot_service") or sys.modules.get("services.lark.bot_runner")
    return getattr(bs, "lark_service", default_lark_service) if bs else default_lark_service


async def handle_member_message(msg: LarkMessage, is_owner: bool = False) -> None:
    """
    Điều phối tin nhắn thông thường của người dùng vào Staging và Chat Pipeline / Queue.
    """
    lark_service = _resolve_lark_service()
    channel_type = "GROUP (WebSocket Real-time)" if msg.chat_type == "group" else "DM 1-1 (User Polling)"
    print(f"📡 Kênh tiếp nhận : {channel_type}")

    # Dùng danh tính và chức danh từ hồ sơ/cấu hình nếu có.
    user_info = lark_service.get_current_user()
    responder_name = user_info.get("name") or settings.LARK_USER_NAME or None
    responder_label = responder_name or "User"
    print(f"👤 Danh tính phản hồi: {responder_label}")

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
        sender_real_name = lark_service.get_user_name(msg.sender_id)
        if sender_real_name:
            target_user_name = sender_real_name

    target_user_name = target_user_name or "bạn"

    # Tự động lưu tin nhắn vào staging cho Daily Digest
    if msg.chat_type == "group" and msg.text:
        try:
            speaker = target_user_name if target_user_name != "bạn" else "Thành viên"
            await digest_service.add_staging_message(
                message_id=msg.message_id,
                chat_id=msg.chat_id,
                text=msg.text,
                speaker_name=speaker,
                speaker_id=msg.sender_id,
                chat_name=msg.chat_id,
            )
            print(f"📥 [STAGING] Đã lưu tin nhắn thành viên vào conversation_staging ({msg.message_id})")
        except Exception as e:
            print(f"⚠️ [STAGING] Lỗi lưu staging: {e}")

    # Chuyển vào Unified Chat Pipeline
    if is_owner:
        query_to_run = msg.text

        # ── [TIER 2: SMART THREAD REPLY VIA JEV] ──
        # Nếu Lãnh đạo đang reply một tin nhắn cụ thể trong thread
        if msg.parent_id:
            parent_text: Optional[str] = None
            try:
                parent_doc = await get_staging_collection().find_one({"message_id": msg.parent_id})
                if parent_doc and parent_doc.get("text"):
                    parent_text = parent_doc["text"]
            except Exception as e:
                logger.debug(f"Không lấy được parent text từ staging: {e}")

            if not parent_text:
                try:
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
                print(f"🧵 [THREAD REPLY PHÁT HIỆN] Sếp reply tin nhắn '{msg.parent_id}': \"{parent_text[:80]}...\"")
                decision_res = await jev_service.classify_thread_decision(
                    parent_text=parent_text,
                    reply_text=msg.text,
                )
                decision = decision_res.get("decision", "CHAT_ONLY")
                conf = decision_res.get("confidence", 0.0)
                print(f"🎯 [THREAD JEV DECISION] Quyết định của Sếp: {decision} (Độ tin cậy: {conf:.2f})")

                approver_info = {
                    "user_id": msg.sender_id,
                    "user_name": responder_name,
                    "role": "owner",
                }

                if decision == "APPROVE_AS_IS":
                    # FAST-LANE: 0 TOKEN LLM, 0ms latency, 0% regex!
                    promoted = await promote_claims_by_message_id(msg.parent_id, approver_info=approver_info)
                    print(f"🎉 [THREAD APPROVAL FAST-LANE] Sếp reply '{msg.text}' -> APPROVE_AS_IS! Đã thăng hạng {promoted} fact(s) thành CURRENT (0 LLM tokens).")
                    return

                elif decision == "REJECT":
                    rejected = await reject_claims_by_message_id(msg.parent_id)
                    print(f"🛑 [THREAD REJECT] Sếp reply '{msg.text}' -> REJECT! Đã từ chối {rejected} fact(s).")
                    return

                elif decision == "APPROVE_WITH_CHANGES":
                    # LLM MODIFICATION LANE: Nối ngữ cảnh đề xuất + điều chỉnh của sếp
                    print(f"📝 [THREAD MODIFICATION] Sếp reply '{msg.text}' -> APPROVE_WITH_CHANGES! Kích hoạt LLM cập nhật giá trị mới...")
                    query_to_run = (
                        f"Đề xuất ban đầu từ nhân sự: \"{parent_text}\"\n"
                        f"Quyết định điều chỉnh và phê duyệt của Lãnh đạo: \"{msg.text}\""
                    )

        print(f"👑 [LARK GROUP CHỦ NHÂN] Tin nhắn của chủ nhân -> Chat Pipeline (chế độ chỉ ghi nhớ/ignore, cấm reply)...")
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
                role=settings.LARK_USER_ROLE or None,
                is_owner=True,
            )
        except Exception as e:
            print(f"❌ Lỗi khi thực thi pipeline: {e}")
            logger.error(f"Lỗi pipeline: {e}", exc_info=True)
            return

        # Hiển thị kết quả định tuyến của JEV cho chủ nhân
        jev_action = result.get("jev_action", "IGNORE")
        confidence = result.get("jev_confidence", 0.0)
        status = result.get("status", "")

        print(f"🎯 Phân loại JEV  : {jev_action} (Độ tin cậy: {confidence:.2f})")
        print(f"📊 Trạng thái     : {status}")

        if status == "forbidden_query":
            chk = result.get("forbidden_check") or {}
            matched = chk.get("matched_label") or "Chủ đề bị cấm"
            print(f"🚫 [FORBIDDEN DROP] Câu hỏi vi phạm nhãn cấm '{matched}'. Kích hoạt Zero-response (Im lặng tuyệt đối).")
        elif status == "group_inactive":
            print(f"🛑 [GROUP INACTIVE] Nhóm chat tạm dừng hoạt động. Bỏ qua tin nhắn.")
        elif jev_action == "IGNORE":
            print(f"🔇 [IGNORE] Tin rác/chào hỏi không quan trọng. Không lưu, không trả lời.")
        elif jev_action == "MEMORY_ONLY":
            ext = result.get("extraction") or {}
            num_ent = len(ext.get("entities", []))
            num_facts = len(ext.get("facts", []))
            print(f"💾 [MEMORY_ONLY] Đã âm thầm trích xuất & lưu vào MongoDB.")
            print(f"   • Thực thể mới : {num_ent}")
            print(f"   • Facts mới    : {num_facts}")
        print("=" * 65 + "\n")
    else:
        # Thành viên trong nhóm: đưa vào Smart Debouncer (1.75s) và Throttled Queue
        print(f"📥 [DEBOUNCE BUFFER] Đưa tin nhắn của '{target_user_name}' vào bộ đệm gom 1.75s...")
        await chat_queue_service.push_incoming_message(
            msg=msg,
            user_name=target_user_name,
            responder_name=responder_name,
            role=settings.LARK_USER_ROLE or None,
        )
