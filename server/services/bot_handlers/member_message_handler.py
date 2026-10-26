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
from models.lark import LarkMessage
from services.chat_service import process_chat_pipeline
from services.digest_service import digest_service
from services.lark import lark_service as default_lark_service
from utils.chat_queue import chat_queue_service

logger = logging.getLogger("hilark.bot.member_message_handler")


def _resolve_lark_service():
    bs = sys.modules.get("services.bot_service")
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
        print(f"👑 [LARK GROUP CHỦ NHÂN] Tin nhắn của chủ nhân -> Chat Pipeline (chế độ chỉ ghi nhớ/ignore, cấm reply)...")
        try:
            result = await process_chat_pipeline(
                query=msg.text,
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
