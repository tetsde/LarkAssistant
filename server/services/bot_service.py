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

import logging
import os
import re
import threading
import time
from datetime import datetime
from typing import Optional

from core.config import settings
from models.lark import LarkMessage
from models.memory import get_vietnam_now
from routers.chat import process_chat_pipeline
from services.digest_service import digest_service
from services.draft_store import PendingDraft, draft_store
from services.lark import lark_service
from services.scope_service import scope_service
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
      2. Quản lý phân quyền Knowledge Base (get-kb, set-kb, reset-kb)
      3. Điều phối tin nhắn của Chủ nhân (Owner) trong Group (Staging) hoặc DM (Duyệt Draft / Digest)
      4. Xử lý tin nhắn của Thành viên qua Chat Pipeline (JEV Routing -> Grounded QA -> Reply)
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
    # 2. XỬ LÝ LỆNH PHÂN QUYỀN KNOWLEDGE BASE (SET-KB / GET-KB / RESET-KB)
    # -------------------------------------------------------------------------
    raw_cmd = re.sub(r"@\S+", "", msg.text or "").strip()
    cmd_lower = raw_cmd.lower()

    # A. Xem Knowledge Base hiện tại của nhóm: get-kb / xem kb
    if cmd_lower in ("get-kb", "get_kb", "xem kb", "kb info", "check kb") or cmd_lower.startswith(("get-kb", "get_kb", "xem kb")):
        scope = await scope_service.get_scope_by_chat_id(msg.chat_id)
        if scope and scope.dataset_id:
            reply_text = (
                f"📚 [KNOWLEDGE BASE CỦA NHÓM NÀY]\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📖 Tên KB       : {scope.dataset_name or 'Chưa đặt tên'}\n"
                f"🆔 Dataset ID   : {scope.dataset_id}\n"
                f"👤 Người cài đặt: {scope.updated_by_name or scope.updated_by}\n"
                f"🕒 Cập nhật lúc : {scope.updated_at}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )
        else:
            default_id, default_name = await scope_service.get_kb_info_for_chat(None)
            reply_text = (
                f"ℹ️ Nhóm chat này chưa được cài đặt Knowledge Base riêng.\n"
                f"Hiện đang sử dụng Knowledge Base mặc định: '{default_name}' (ID: {default_id}).\n\n"
                f"👉 Admin có thể dùng lệnh 'set-kb <dataset_id>' để liên kết Knowledge Base riêng cho nhóm."
            )

        if msg.chat_type == "group":
            await lark_service.areply_text(message_id=msg.message_id, text=reply_text, as_user=True)
        else:
            await lark_service.send_bot_dm_to_owner(reply_text)
        return

    # B. Gỡ bỏ liên kết Knowledge Base: reset-kb / hủy kb
    if cmd_lower in ("reset-kb", "reset_kb", "hủy kb", "huy kb", "xóa kb", "xoa kb"):
        if not scope_service.is_admin_user(msg.sender_id):
            deny_msg = "⛔ [TỪ CHỐI] Bạn không có quyền quản trị! Chỉ Admin mới được phép gỡ bỏ Knowledge Base của nhóm."
            if msg.chat_type == "group":
                await lark_service.areply_text(message_id=msg.message_id, text=deny_msg, as_user=True)
            else:
                await lark_service.send_bot_dm_to_owner(deny_msg)
            await lark_service.send_bot_dm_to_owner(
                f"⚠️ [CẢNH BÁO BẢO MẬT] Người dùng ({msg.sender_id}) vừa cố tình gõ lệnh reset-kb trong nhóm {msg.chat_id} nhưng đã bị chặn!"
            )
            return

        ok, reset_msg = await scope_service.reset_chat_kb(chat_id=msg.chat_id, operator_open_id=msg.sender_id)
        if msg.chat_type == "group":
            await lark_service.areply_text(message_id=msg.message_id, text=reset_msg, as_user=True)
        else:
            await lark_service.send_bot_dm_to_owner(reset_msg)
        return

    # C. Cài đặt Knowledge Base cho nhóm: set-kb <dataset_id>
    if cmd_lower.startswith(("set-kb", "set_kb", "cài kb", "cai kb", "gán kb", "gan kb")):
        parts = raw_cmd.split()
        if len(parts) < 2:
            guide_msg = "⚠️ Vui lòng nhập Dataset ID cần liên kết. Ví dụ:\nset-kb bca87123-973d-46e4-97aa-290d7d769aef"
            if msg.chat_type == "group":
                await lark_service.areply_text(message_id=msg.message_id, text=guide_msg, as_user=True)
            else:
                await lark_service.send_bot_dm_to_owner(guide_msg)
            return

        target_dataset_id = parts[1].strip()

        if not scope_service.is_admin_user(msg.sender_id):
            deny_msg = "⛔ [TỪ CHỐI] Bạn không có quyền quản trị! Chỉ Admin mới được phép thay đổi Knowledge Base của nhóm chat này."
            if msg.chat_type == "group":
                await lark_service.areply_text(message_id=msg.message_id, text=deny_msg, as_user=True)
            else:
                await lark_service.send_bot_dm_to_owner(deny_msg)
            await lark_service.send_bot_dm_to_owner(
                f"⚠️ [CẢNH BÁO BẢO MẬT] Người dùng ({msg.sender_id}) vừa cố tình đổi KB của nhóm {msg.chat_id} sang ID '{target_dataset_id}' nhưng đã bị chặn!"
            )
            return

        sender_name = lark_service.get_user_name(msg.sender_id) or "Admin"
        ok, res_msg, rec = await scope_service.set_chat_kb(
            chat_id=msg.chat_id,
            dataset_id=target_dataset_id,
            operator_open_id=msg.sender_id,
            operator_name=sender_name,
        )

        if ok and rec:
            confirm_text = (
                f"✔ ĐÃ LIÊN KẾT NHÓM THÀNH CÔNG VỚI KNOWLEDGE BASE!\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📚 Tên KB       : {rec.dataset_name}\n"
                f"🆔 Dataset ID   : {rec.dataset_id}\n"
                f"💬 Nhóm chat    : {msg.chat_id}\n"
                f"👤 Người cài đặt: {rec.updated_by_name}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Tất cả tổng hợp Daily Digest và truy vấn RAG của nhóm sẽ tự động liên kết với Knowledge Base này!"
            )
            print(f"✔ Đã liên kết nhóm {msg.chat_id} thành công với Knowledge Base '{rec.dataset_name}' (ID: {rec.dataset_id})")
            if msg.chat_type == "group":
                await lark_service.areply_text(message_id=msg.message_id, text=confirm_text, as_user=True)
            else:
                await lark_service.send_bot_dm_to_owner(confirm_text)
        else:
            err_text = f"❌ {res_msg}"
            if msg.chat_type == "group":
                await lark_service.areply_text(message_id=msg.message_id, text=err_text, as_user=True)
            else:
                await lark_service.send_bot_dm_to_owner(err_text)
        return

    # -------------------------------------------------------------------------
    # 3. XỬ LÝ TIN NHẮN TỪ CHÍNH BẠN (CHỦ NHÂN)
    # -------------------------------------------------------------------------
    is_owner = bool(msg.is_self or msg.sender_id == lark_service.known_user_open_id)
    if is_owner:
        # Nếu nhắn trong DM 1-1 (chat_type == "p2p"): Đây là chủ nhân đang chat/ra lệnh trực tiếp cho Bot!
        if msg.chat_type == "p2p":
            clean_text = msg.text.strip()
            text_lower = clean_text.lower()
            print(f"👑 [LARK DM CHỦ NHÂN] Nhận lệnh từ chủ nhân: '{clean_text}'")

        # --- A. LỆNH DUYỆT / HỦY / XEM DAILY DIGEST ---
        if "xem digest" in text_lower or "chi tiết digest" in text_lower:
            latest_pending = await digest_service.get_latest_pending_approval_digest()
            if not latest_pending:
                await lark_service.send_bot_dm_to_owner("ℹ️ Hiện không có bản Daily Digest nào đang chờ duyệt.")
            else:
                md_preview = latest_pending.to_weknora_markdown()
                preview_text = md_preview[:1500] + ("\n...(còn tiếp)" if len(md_preview) > 1500 else "")
                await lark_service.send_bot_dm_to_owner(
                    f"📄 [CHI TIẾT DAILY DIGEST: {latest_pending.id}]\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{preview_text}\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "👉 Nhắn 'Duyệt digest' để nạp vào WeKnora hoặc 'Hủy digest' để từ chối."
                )
            return

        digest_approve_keywords = ("duyệt digest", "duyet digest", "ok digest", "duyệt kb", "duyet kb", "ok kb", "approve digest")
        if any(kw in text_lower for kw in digest_approve_keywords):
            parts = clean_text.split()
            target_id = parts[2] if len(parts) >= 3 and parts[2].startswith("digest_") else None

            print(f"🚀 [DM APPROVAL] Tiến hành DUYỆT Daily Digest ({target_id or 'bản gần nhất'})...")
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
            target_id = parts[2] if len(parts) >= 3 and parts[2].startswith("digest_") else None

            print(f"🗑 [DM APPROVAL] Tiến hành HỦY Daily Digest ({target_id or 'bản gần nhất'})...")
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
            draft = draft_store.get_latest_draft(msg.sender_id)
            if not draft:
                print(f"⚠️ [DM APPROVAL] Không tìm thấy bản nháp đang chờ duyệt cho {msg.sender_id}")
                await lark_service.send_bot_dm_to_owner(
                    "⚠️ Hiện không tìm thấy bản nháp nào đang chờ duyệt.\n"
                    "(Có thể bản nháp đã được gửi rồi hoặc vừa khởi động lại bot)."
                )
                return

            print(f"🚀 [DM APPROVAL] Tiến hành DUYỆT & GỬI bản nháp vào nhóm nhân danh User (msg_id: {draft.message_id})...")
            try:
                reply_resp = await lark_service.areply_text(
                    message_id=draft.message_id,
                    text=draft.draft_answer,
                    as_user=True,
                )
                draft_store.pop_draft(msg.sender_id)
                if reply_resp.get("success"):
                    confirm_text = (
                        "✔ ĐÃ DUYỆT VÀ GỬI THÀNH CÔNG VÀO NHÓM!\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"👤 Danh tính gửi : {draft.responder_name}\n"
                        f"💬 Câu hỏi gốc   : \"{draft.query}\"\n\n"
                        f"📄 Nội dung đã phát ngôn:\n"
                        f"\"{draft.draft_answer}\"\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    )
                    await lark_service.send_bot_dm_to_owner(confirm_text)
                    print(f"✔ [DM APPROVAL] Đã gửi câu trả lời vào nhóm và xác nhận về DM thành công!")
                else:
                    err_msg = reply_resp.get("msg") or reply_resp.get("error") or "Không rõ lỗi"
                    await lark_service.send_bot_dm_to_owner(f"❌ Có lỗi khi gửi tin nhắn vào nhóm: {err_msg}")
            except Exception as e:
                print(f"❌ [DM APPROVAL] Lỗi gửi duyệt: {e}")
                await lark_service.send_bot_dm_to_owner(f"❌ Exception khi duyệt gửi: {str(e)}")
            return

        # --- C. LỆNH BỎ BẢN NHÁP: [Bỏ] / [Hủy] ---
        discard_keywords = ("bỏ", "bo", "hủy", "huy", "bỏ qua", "bo qua", "discard", "cancel", "no", "0")
        if text_lower in discard_keywords:
            draft = draft_store.pop_draft(msg.sender_id)
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

            draft = draft_store.pop_draft(msg.sender_id)
            if not draft:
                await lark_service.send_bot_dm_to_owner("⚠️ Không tìm thấy bản nháp đang chờ để sửa.")
                return

            print(f"✏️ [DM APPROVAL] Chỉnh sửa và gửi nội dung mới vào nhóm: \"{edited_content[:80]}...\"")
            try:
                reply_resp = await lark_service.areply_text(
                    message_id=draft.message_id,
                    text=edited_content,
                    as_user=True,
                )
                if reply_resp.get("success"):
                    confirm_text = (
                        "✔ ĐÃ GỬI BẢN CHỈNH SỬA VÀO NHÓM THÀNH CÔNG!\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"👤 Danh tính gửi: {draft.responder_name}\n"
                        f"📄 Nội dung mới đã gửi:\n"
                        f"\"{edited_content}\"\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    )
                    await lark_service.send_bot_dm_to_owner(confirm_text)
                else:
                    await lark_service.send_bot_dm_to_owner(f"❌ Lỗi gửi bản chỉnh sửa: {reply_resp.get('msg')}")
            except Exception as e:
                await lark_service.send_bot_dm_to_owner(f"❌ Exception khi gửi bản sửa: {str(e)}")
            return

    # -------------------------------------------------------------------------
    # 4. XỬ LÝ TIN NHẮN TỪ THÀNH VIÊN KHÁC (CHAT PIPELINE)
    # -------------------------------------------------------------------------
    channel_type = "GROUP (WebSocket Real-time)" if msg.chat_type == "group" else "DM 1-1 (User Polling)"
    print(f"📡 Kênh tiếp nhận : {channel_type}")

    # Chuẩn bị danh tính User phản hồi (Tống Phước Hoài Nam)
    user_info = lark_service.get_current_user()
    responder_name = user_info.get("name", "Tống Phước Hoài Nam")
    print(f"👤 Danh tính phản hồi: {responder_name}")

    # Nhận diện tên đích danh người hỏi
    target_user_name = "bạn"
    if msg.mentions:
        for m in msg.mentions:
            m_name = m.get("name", "")
            if m_name and not (
                "bot" in m_name.lower()
                or "hilark" in m_name.lower()
                or m_name.lower() in responder_name.lower()
                or responder_name.lower() in m_name.lower()
            ):
                target_user_name = m_name
                break

    if target_user_name == "bạn" and msg.sender_id:
        sender_real_name = lark_service.get_user_name(msg.sender_id)
        if sender_real_name:
            target_user_name = sender_real_name

    if target_user_name == "bạn":
        if "phước" in msg.text.lower() or "phuoc" in msg.text.lower():
            target_user_name = "Hoài Phước"

    # Tự động lưu tin nhắn vào staging cho Daily Digest
    if msg.chat_type == "group" and msg.text:
        try:
            speaker = target_user_name if target_user_name != "bạn" else (lark_service.get_user_name(msg.sender_id) or "Thành viên")
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
    else:
        print(f"⚙️ Đang xử lý qua Chat Pipeline (đích danh: '{target_user_name}' -> JEV Routing)...")

    try:
        result = await process_chat_pipeline(
            query=msg.text,
            sender=msg.sender_id,
            channel=f"lark_{msg.chat_type}",
            message_id=msg.message_id,
            chat_id=msg.chat_id,
            reply_to_lark=not is_owner,
            user_name=target_user_name,
            responder_name=responder_name,
            role="Project Lead",
            is_owner=is_owner,
        )
    except Exception as e:
        print(f"❌ Lỗi khi thực thi pipeline: {e}")
        logger.error(f"Lỗi pipeline: {e}", exc_info=True)
        return

    # Hiển thị kết quả định tuyến của JEV
    jev_action = result.get("jev_action", "IGNORE")
    confidence = result.get("jev_confidence", 0.0)
    status = result.get("status", "")

    print(f"🎯 Phân loại JEV  : {jev_action} (Độ tin cậy: {confidence:.2f})")
    print(f"📊 Trạng thái     : {status}")

    if jev_action == "IGNORE":
        print(f"🔇 [IGNORE] Tin rác/chào hỏi không quan trọng. Không lưu, không trả lời.")

    elif jev_action == "MEMORY_ONLY":
        ext = result.get("extraction") or {}
        num_ent = len(ext.get("entities", []))
        num_facts = len(ext.get("facts", []))
        print(f"💾 [MEMORY_ONLY] Đã âm thầm trích xuất & lưu vào bộ nhớ MongoDB/KB.")
        print(f"   • Thực thể mới : {num_ent}")
        print(f"   • Facts mới    : {num_facts}")

    elif jev_action == "DRAFT_PENDING_APPROVAL":
        draft_ans = result.get("draft_answer") or result.get("answer", "")
        print(f"📝 [DRAFT_PENDING_APPROVAL] CÂU HỎI CÓ RỦI RO -> SOẠN NHÁP CHỜ DUYỆT:")
        print(f"   • Bản nháp: \"{draft_ans[:150]}{'...' if len(draft_ans) > 150 else ''}\"")
        print(f"   • Tùy chọn: [Gửi] / [Sửa] / [Bỏ]")
        print(f"   (Đã gửi thông báo riêng tới DM của {responder_name}, KHÔNG phát ngôn vào nhóm)")

    elif jev_action in ("REPLY_ONLY", "MEMORY_AND_REPLY"):
        if jev_action == "MEMORY_AND_REPLY":
            ext = result.get("extraction") or {}
            print(f"💾 [MEMORY_AND_REPLY] Đã cập nhật bộ nhớ ({len(ext.get('facts', []))} facts mới).")

        answer = result.get("answer", "")
        print(f"💬 [TRẢ LỜI] Câu trả lời đã tạo ({len(answer)} ký tự):")
        print(f"   \"{answer[:150]}{'...' if len(answer) > 150 else ''}\"")

        lark_res = result.get("lark_response") or {}
        if lark_res.get("success"):
            print(f"✔ ĐÃ GỬI PHẢN HỒI THÀNH CÔNG NHÂN DANH {responder_name.upper()}!")
        else:
            print(f"⚠️ Trạng thái gửi reply Lark: {lark_res}")

    print("=" * 65 + "\n")


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
                        digests = loop.run_until_complete(
                            digest_service.run_scheduled_daily_digests(
                                date=today_str,
                                require_approval=settings.DIGEST_REQUIRE_APPROVAL,
                            )
                        )
                        if digests:
                            print(f"✔ [DIGEST SCHEDULER] Hoàn tất trích xuất Daily Digest cho {len(digests)} nhóm vào MongoDB.")
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
    print("💡 Mọi tin nhắn phản hồi sẽ hiện ra dưới danh tính Tống Phước Hoài Nam!")
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

    _bot_started = True
    logger.info("✔ Lark Bot Service đã sẵn sàng!")


def stop_bot_service() -> None:
    """Dừng an toàn toàn bộ background threads của Bot khi tắt server."""
    global _bot_started, _scheduler_stop_event
    logger.info("Đang dừng Lark Bot Service...")
    _scheduler_stop_event.set()
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
