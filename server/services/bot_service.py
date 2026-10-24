"""
HiLark Bot Service - Unified Background Runner & Event Dispatcher
=================================================================
Vị trí: server/services/bot_service.py

Mục đích:
    - Điều phối toàn bộ vòng đời của Lark Bot (WebSocket Connection, Handlers, Scheduler).
    - Tích hợp trực tiếp vào FastAPI Lifespan để chạy trên 1 tiến trình duy nhất.
    - Hỗ trợ chạy độc lập qua run_lark_bot.py nếu cần.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from datetime import datetime
from typing import Optional

from core.config import settings
from models.lark import LarkMessage
from models.memory import get_vietnam_now
from services.chat_service import process_chat_pipeline
from services.digest_service import digest_service
from services.draft_service import draft_service
from services.lark import lark_service
from services.larkbase import lark_base_service
from services.scope_service import scope_service
from utils.chat_queue import chat_queue_service
from utils.digest import get_current_digest_date

logger = logging.getLogger("hilark.bot")

# Quản lý trạng thái background thread
_scheduler_stop_event = threading.Event()
_scheduler_thread: Optional[threading.Thread] = None
_ws_thread: Optional[threading.Thread] = None
_bot_started = False


# =============================================================================
# 1. HÀM XỬ LÝ SỰ KIỆN TIN NHẮN TỪ LARK (CORE DISPATCHER)
# =============================================================================

async def handle_lark_incoming_message(msg: LarkMessage) -> None:
    """
    Dispatcher xử lý mọi tin nhắn đến từ Lark (cả WebSocket lẫn Webhook):
      1. Bỏ qua tin nhắn từ Bot / App
      2. Điều phối tin nhắn của Chủ nhân (Owner) trong Group (Staging) hoặc DM (Duyệt Draft / Digest)
      3. Xử lý tin nhắn của Thành viên qua Chat Pipeline (JEV Routing -> Grounded QA -> Reply)
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("\n" + "=" * 65)
    print("🔔 [LARK EVENT] BẮT ĐƯỢC TIN NHẮN TỪ LARK:")
    print("-" * 65)
    print(f"🕒 Thời gian      : {now_str}")
    print(f"💬 Cuộc trò chuyện: {msg.chat_id} (Loại: {msg.chat_type})")
    print(f"👤 Người gửi      : {msg.sender_id} {'[CHÍNH BẠN]' if msg.is_self else '[USER KHÁC]'}")
    print(f"🆔 Message ID     : {msg.message_id}")
    print(f"📄 NỘI DUNG       : \"{msg.text}\"")
    print("-" * 65)

    # 1. Bỏ qua tin nhắn từ Bot
    if msg.is_bot:
        print(f"ℹ️ Bỏ qua tin nhắn từ Bot ứng dụng ({msg.sender_id}).")
        return

    # -------------------------------------------------------------------------
    # 2. XỬ LÝ TIN NHẮN TỪ CHÍNH BẠN (CHỦ NHÂN) TRONG DM 1-1
    # -------------------------------------------------------------------------
    is_owner = bool(
        msg.is_self
        or (lark_service.owner_open_id and msg.sender_id == lark_service.owner_open_id)
    )
    if is_owner and msg.chat_type == "p2p":
        # [LUỒNG CHÍNH - USER FACING] Chủ nhân chat/ra lệnh trực tiếp cho Bot trong DM 1-1 trên Lark:
        # Không cần dùng REST API: duyệt bằng cách nhắn "duyệt digest", "hủy digest", hoặc duyệt nháp "Gửi", "Sửa", "Bỏ".
        clean_text = msg.text.strip()
        text_lower = clean_text.lower()
        print(f"👑 [LARK DM CHỦ NHÂN] Nhận lệnh từ chủ nhân: '{clean_text}'")

        # --- A. LỆNH DUYỆT / HỦY / XEM DAILY DIGEST (MASTER DIGEST HOẶC ĐƠN LẺ) ---
        if "xem digest" in text_lower or "chi tiết digest" in text_lower:
            latest_master = await digest_service.get_latest_pending_master_digest()
            if latest_master:
                dm_text = latest_master.to_executive_dm_text()
                await lark_service.send_bot_dm_to_owner(dm_text)
                return

            latest_pending = await digest_service.get_latest_pending_approval_digest()
            if not latest_pending:
                await lark_service.send_bot_dm_to_owner("ℹ️ Hiện không có bản Daily Digest nào đang chờ duyệt.")
            else:
                md_preview = latest_pending.to_weknora_markdown()
                preview_text = md_preview[:1500] + ("\n...(còn tiếp)" if len(md_preview) > 1500 else "")
                await lark_service.send_bot_dm_to_owner(
                    f"CHI TIẾT DAILY DIGEST: {latest_pending.id}]\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{preview_text}\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "👉 Nhắn 'Duyệt digest' để nạp vào WeKnora hoặc 'Hủy digest' để từ chối."
                )
            return

        digest_approve_keywords = ("duyệt digest", "duyet digest", "ok digest", "duyệt kb", "duyet kb", "ok kb", "approve digest")
        if any(kw in text_lower for kw in digest_approve_keywords):
            parts = clean_text.split()
            target_id = parts[2] if len(parts) >= 3 and (parts[2].startswith("digest_") or parts[2].startswith("master_digest_")) else None

            # Ưu tiên duyệt Master Daily Digest nếu có hoặc nếu chỉ định ID master
            if (target_id and target_id.startswith("master_digest_")) or (not target_id and await digest_service.get_latest_pending_master_digest()):
                print(f"🚀 [DM APPROVAL] Tiến hành DUYỆT Master Daily Digest ({target_id or 'bản gần nhất'})...")
                ok, msg_reply, mrec = await digest_service.approve_and_sync_master_digest(target_id, approver_open_id=msg.sender_id)
                if ok and mrec:
                    reply_confirm = (
                        "✔ ĐÃ DUYỆT VÀ ĐỒNG BỘ TOÀN BỘ MASTER DAILY DIGEST THÀNH CÔNG!\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📅 Ngày ghi nhận : {mrec.date}\n"
                        f"🆔 Mã Master     : {mrec.id}\n"
                        f"👥 Số nhóm duyệt : {mrec.total_groups} nhóm ({mrec.total_messages} tin nhắn)\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "Tri thức của từng nhóm đã được phân phối nạp chính xác vào đúng Knowledge Base WeKnora tương ứng!"
                    )
                    await lark_service.send_bot_dm_to_owner(reply_confirm)
                else:
                    await lark_service.send_bot_dm_to_owner(f"❌ {msg_reply}")
                return

            print(f"🚀 [DM APPROVAL] Tiến hành DUYỆT Daily Digest đơn lẻ ({target_id or 'bản gần nhất'})...")
            ok, msg_reply, rec = await digest_service.approve_and_sync_digest(target_id)
            if ok and rec:
                reply_confirm = (
                    "✔ ĐÃ DUYỆT VÀ ĐỒNG BỘ DAILY DIGEST LÊN WEKNORA THÀNH CÔNG!\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📅 Ngày ghi nhận : {rec.date}\n"
                    f"💬 Nhóm chat     : {rec.chat_name or rec.chat_id}\n"
                    f"🆔 Mã Digest     : {rec.id}\n"
                    f"📚 WeKnora Doc ID: {rec.weknora_doc_id}\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Knowledge Base đã được cập nhật tri thức mới sẵn sàng cho RAG!"
                )
                await lark_service.send_bot_dm_to_owner(reply_confirm)
            else:
                await lark_service.send_bot_dm_to_owner(f"❌ {msg_reply}")
            return

        digest_reject_keywords = ("hủy digest", "huy digest", "bỏ digest", "bo digest", "reject digest")
        if any(kw in text_lower for kw in digest_reject_keywords):
            parts = clean_text.split()
            target_id = parts[2] if len(parts) >= 3 and (parts[2].startswith("digest_") or parts[2].startswith("master_digest_")) else None

            if (target_id and target_id.startswith("master_digest_")) or (not target_id and await digest_service.get_latest_pending_master_digest()):
                print(f"🗑 [DM APPROVAL] Tiến hành HỦY Master Daily Digest ({target_id or 'bản gần nhất'})...")
                ok, msg_reply, mrec = await digest_service.reject_master_digest(target_id)
                if ok and mrec:
                    reply_confirm = (
                        "🗑 ĐÃ TỪ CHỐI BẢN MASTER DAILY DIGEST!\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🆔 Mã Master : {mrec.id}\n"
                        f"📅 Ngày      : {mrec.date}\n"
                        "Trạng thái đã chuyển sang 'rejected'. Toàn bộ dữ liệu các nhóm KHÔNG được nạp vào WeKnora."
                    )
                    await lark_service.send_bot_dm_to_owner(reply_confirm)
                else:
                    await lark_service.send_bot_dm_to_owner(f"❌ {msg_reply}")
                return

            print(f"🗑 [DM APPROVAL] Tiến hành HỦY Daily Digest đơn lẻ ({target_id or 'bản gần nhất'})...")
            ok, msg_reply, rec = await digest_service.reject_digest(target_id)
            if ok and rec:
                reply_confirm = (
                    "🗑 ĐÃ TỪ CHỐI BẢN DAILY DIGEST!\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🆔 Mã Digest : {rec.id}\n"
                    "Trạng thái đã chuyển sang 'rejected'. Dữ liệu KHÔNG được nạp vào WeKnora."
                )
                await lark_service.send_bot_dm_to_owner(reply_confirm)
            else:
                await lark_service.send_bot_dm_to_owner(f"❌ {msg_reply}")
            return

        # --- B. LỆNH DUYỆT & GỬI BẢN NHÁP CÂU TRẢ LỜI: [Gửi] / [Duyệt] / [OK] ---
        send_keywords = ("gửi", "gui", "ok", "duyệt", "duyet", "gửi đi", "gui di", "send", "yes", "1")
        if text_lower in send_keywords or text_lower.startswith(("gửi ", "gui ", "duyệt ")):
            ok, detail, draft, _ = await draft_service.send_latest(msg.sender_id)
            if not draft:
                await lark_service.send_bot_dm_to_owner(f"⚠️ {detail}")
                return
            if ok:
                confirm_text = (
                    "✔ ĐÃ GỬI CÂU TRẢ LỜI VÀO NHÓM!\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 Người trả lời: {draft.responder_name or 'User'}\n"
                    f"💬 Câu hỏi gốc: \"{draft.query}\"\n\n"
                    f"📄 Nội dung đã gửi:\n\"{draft.approved_content}\"\n"
                    "📌 Trạng thái: sent\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )
                await lark_service.send_bot_dm_to_owner(confirm_text)
            else:
                await lark_service.send_bot_dm_to_owner(
                    f"❌ Chưa xác nhận gửi thành công. Draft vẫn chờ xử lý. Lỗi: {detail}"
                )
            return

        # --- C. LỆNH BỎ BẢN NHÁP: [Bỏ] / [Hủy] ---
        discard_keywords = ("bỏ", "bo", "hủy", "huy", "bỏ qua", "bo qua", "discard", "cancel", "no", "0")
        if text_lower in discard_keywords:
            draft = await draft_service.discard_latest(msg.sender_id)
            if draft:
                print(f"🗑 [DM APPROVAL] Chủ nhân đã BỎ bản nháp cho message_id={draft.message_id}")
                await lark_service.send_bot_dm_to_owner(
                    "🗑 ĐÃ HỦY BỎ BẢN NHÁP THÀNH CÔNG!\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Bản nháp cho câu hỏi \"{draft.query}\" đã bị hủy.\n"
                    "Không có tin nhắn nào được gửi vào nhóm."
                )
            else:
                await lark_service.send_bot_dm_to_owner("⚠️ Hiện không có bản nháp nào đang chờ duyệt để hủy.")
            return

        # --- D. LỆNH SỬA BẢN NHÁP: [Sửa: <nội dung>] ---
        if text_lower.startswith(("sửa:", "sua:", "sửa ", "sua ", "edit:")):
            separator = ":" if ":" in clean_text else " "
            parts = clean_text.split(separator, 1)
            edited_content = parts[1].strip() if len(parts) > 1 else ""
            if not edited_content:
                await lark_service.send_bot_dm_to_owner(
                    "⚠️ Vui lòng nhập nội dung chỉnh sửa sau dấu hai chấm. Ví dụ:\n"
                    "Sửa: Dự án này do Tuấn PM lead."
                )
                return

            print(f"✏️ [DM APPROVAL] Chỉnh sửa và gửi nội dung mới vào nhóm: \"{edited_content[:80]}...\"")
            ok, detail, draft, _ = await draft_service.send_latest(
                msg.sender_id,
                approved_content=edited_content,
            )
            if not draft:
                await lark_service.send_bot_dm_to_owner(f"⚠️ {detail}")
                return
            if ok:
                confirm_text = (
                    "✔ ĐÃ GỬI BẢN CHỈNH SỬA VÀO NHÓM!\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 Người trả lời: {draft.responder_name or 'User'}\n"
                    f"📄 Nội dung đã gửi:\n\"{edited_content}\"\n"
                    "📌 Trạng thái: sent\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )
                await lark_service.send_bot_dm_to_owner(confirm_text)
            else:
                await lark_service.send_bot_dm_to_owner(
                    f"❌ Chưa xác nhận gửi thành công. Draft vẫn chờ xử lý. Lỗi: {detail}"
                )
            return

    # -------------------------------------------------------------------------
    # 4. XỬ LÝ TIN NHẮN TỪ THÀNH VIÊN KHÁC (CHAT PIPELINE)
    # -------------------------------------------------------------------------
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


# =============================================================================
# 2. DAEMON SCHEDULER: ĐẶT GIỜ TỔNG HỢP DAILY DIGEST
# =============================================================================

def start_digest_scheduler_daemon() -> threading.Thread:
    """Khởi động daemon thread chạy hẹn giờ tổng hợp Daily Digest."""
    global _scheduler_stop_event, _scheduler_thread

    _scheduler_stop_event.clear()

    def _worker():
        last_run_date = ""
        target_hm = (settings.DIGEST_SCHEDULE_TIME or "23:00").strip()
        print(f"⏰ [DIGEST SCHEDULER] Đã khởi động background thread (Giờ chạy hẹn trước: {target_hm})")

        while not _scheduler_stop_event.is_set():
            try:
                # Ngủ ngắt quãng an toàn (kiểm tra stop_event mỗi 5s, tối đa 30s)
                if _scheduler_stop_event.wait(timeout=30):
                    break

                now_vn = get_vietnam_now()
                current_hm = now_vn.strftime("%H:%M")
                today_str = get_current_digest_date()

                if current_hm == target_hm and last_run_date != today_str:
                    print(f"\n⏰ [DIGEST SCHEDULER] Đến giờ hẹn ({target_hm})! Bắt đầu tổng hợp tin nhắn trong ngày...")
                    last_run_date = today_str

                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        master_digest = loop.run_until_complete(
                            digest_service.run_scheduled_daily_digests(
                                date=today_str,
                                require_approval=settings.DIGEST_REQUIRE_APPROVAL,
                            )
                        )
                        if master_digest and master_digest.total_groups > 0:
                            print(f"✔ [DIGEST SCHEDULER] Hoàn tất Master Daily Digest ({master_digest.id}) cho {master_digest.total_groups} nhóm ({master_digest.total_messages} tin nhắn).")
                        else:
                            print(f"ℹ️ [DIGEST SCHEDULER] Không có nhóm chat nào có tin nhắn hoạt động ngày {today_str}.")
                    finally:
                        loop.close()
            except Exception as e:
                print(f"⚠️ [DIGEST SCHEDULER] Lỗi: {e}")

        logger.info("Digest Scheduler đã dừng an toàn.")

    thread = threading.Thread(target=_worker, daemon=True, name="DigestScheduler")
    thread.start()
    _scheduler_thread = thread
    return thread


# =============================================================================
# 3. QUẢN LÝ VÒNG ĐỜI BOT SERVICE (LIFESPAN INTEGRATION)
# =============================================================================

def start_bot_service() -> None:
    """
    Khởi động toàn bộ dịch vụ Lark Bot:
      - Đăng ký hàm handle_lark_incoming_message vào Lark Service
      - Bật Digest Scheduler daemon thread
      - Kết nối Lark WebSocket Client (Pure WebSocket) ở background thread
    """
    global _bot_started, _ws_thread

    if _bot_started:
        logger.info("Lark Bot Service đã được khởi động trước đó.")
        return

    print("\n" + "=" * 65)
    print("🚀 KHỞI ĐỘNG HILARK BOT SERVICE (INTEGRATED LIFESPAN)")
    print("=================================================================")
    print(f"App ID : {lark_service.app_id}")
    print(f"Domain : {lark_service.domain}")

    # 1. Đăng ký Message Handler vào Lark Service
    lark_service.register_handler(handle_lark_incoming_message)

    # 1.1 Khởi động Throttled Chat Queue Service (Debouncer & Cooldown Worker)
    chat_queue_service.start()

    # 2. Khởi động Digest Scheduler
    start_digest_scheduler_daemon()

    # 3. Kiểm tra tính hợp lệ và Ping User Access Token (Chống Crash)
    from utils.lark_token import check_and_warn_token
    token_res = check_and_warn_token()

    # 4. Thông tin người dùng
    user_info = lark_service.get_current_user()
    if "name" in user_info:
        status_suffix = "" if token_res.is_valid else " ⚠️ [Chế độ An Toàn - Token hết hạn]"
        print(f"👤 DANH TÍNH HOẠT ĐỘNG: {user_info['name']}{status_suffix}")
        print(f"   - Open ID           : {user_info.get('open_id')}")

    enable_polling = getattr(settings, "ENABLE_DM_POLLING", False)
    poll_interval = getattr(settings, "DM_POLL_INTERVAL", 60.0)

    if enable_polling:
        print(f"   - DM 1-1 Chats      : 🔄 User Token Polling (Chu kỳ {poll_interval}s)")
        print(f"   - Chế độ gửi tin    : 100% USER IDENTITY (as_user=True)")
    else:
        print(f"   - Group & DM        : ⚡ Pure WebSocket Real-time (0 Quota used!)")
        print(f"   - Chế độ gửi tin    : 100% USER IDENTITY (as_user=True)")

    print("-" * 65)
    print(f"💡 Danh tính phản hồi: {user_info.get('name') or settings.LARK_USER_NAME or 'User'}")
    print("=" * 65)

    # 4. Khởi động WebSocket Client ở background thread
    if enable_polling:
        _ws_thread = threading.Thread(
            target=lark_service.start_hybrid_runner,
            kwargs={"dm_poll_interval": poll_interval},
            daemon=True,
            name="LarkHybridRunner",
        )
        _ws_thread.start()
    else:
        print("🚀 Đang kết nối Lark WebSocket Client (Pure WebSocket Mode)...")
        _ws_thread = lark_service.start_ws_client(background=True)

    # 5. Khởi động Lark Base (Bitable) Sync & Subscribe Service
    if lark_base_service.app_token:
        try:
            # A. Đăng ký subscribe sự kiện trên Lark Cloud
            sub_ok = lark_base_service.subscribe_events()
            if sub_ok:
                print(f"📊 [LARK BASE] Đã đăng ký theo dõi sự kiện Bitable (App: {lark_base_service.app_token})")

            # B. Quét và đồng bộ các nhóm chat bot ban đầu vào Base
            sync_res = lark_base_service.sync_bot_chats()
            items = sync_res.get("added", []) + sync_res.get("updated", [])
            if items:
                print(f"🔄 [LARK BASE] Đã đồng bộ ban đầu {len(items)} nhóm chat vào Base.")

            # D. Đăng ký handler tự động đồng bộ Documents sang WeKnora & MongoDB khi có sự kiện Bitable
            lark_service.register_bitable_record_handler(scope_service.handle_bitable_record_changed_event)

            # E. Quét và đồng bộ ban đầu các tài liệu và phân quyền nhóm từ Base sang WeKnora & MongoDB
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(scope_service.sync_all_groups_from_base())
                if getattr(settings, "POLICY_SYNC_ENABLED", True):
                    from services.policy_sync_service import start_policy_sync_loop
                    loop.create_task(start_policy_sync_loop())
                from services.token_service import start_token_refresh_loop
                loop.create_task(start_token_refresh_loop())
            except RuntimeError:
                pass
        except Exception as e:
            logger.warning(f"Lỗi khởi tạo Lark Base Service trong lifecycle: {e}")

    _bot_started = True
    logger.info("✔ Lark Bot Service đã sẵn sàng!")


def stop_bot_service() -> None:
    """Dừng an toàn toàn bộ background threads của Bot khi tắt server."""
    global _bot_started, _scheduler_stop_event
    logger.info("Đang dừng Lark Bot Service...")
    _scheduler_stop_event.set()

    # Dừng worker của Chat Queue Service
    try:
        chat_queue_service.stop()
    except Exception as e:
        logger.debug(f"Lỗi khi dừng Chat Queue worker: {e}")

    _bot_started = False
    logger.info("✔ Đã dừng Lark Bot Service thành công.")


def run_standalone_bot() -> None:
    """Dành cho việc chạy độc lập bằng lệnh `python run_lark_bot.py`."""
    start_bot_service()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nĐang dừng bot...")
        stop_bot_service()
