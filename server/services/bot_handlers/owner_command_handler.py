"""
Owner Command Handler for Lark Bot (DM 1-1)
===========================================
Vị trí: server/services/bot_handlers/owner_command_handler.py

Mục đích:
    - Xử lý các câu lệnh điều hành của Chủ nhân (Owner) trong hội thoại riêng DM 1-1:
      1. Xem, duyệt hoặc từ chối Daily Digest / Master Daily Digest.
      2. Duyệt gửi, hủy bỏ hoặc chỉnh sửa nội dung Bản nháp câu trả lời (Human-in-the-loop Draft Approval).
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from models.lark import LarkMessage
from services.digest_service import digest_service
from services.draft_service import draft_service
from services.lark import lark_service as default_lark_service

logger = logging.getLogger("hilark.bot.owner_command_handler")


def _resolve_lark_service():
    bs = sys.modules.get("services.bot_service")
    return getattr(bs, "lark_service", default_lark_service) if bs else default_lark_service


async def handle_owner_dm_command(msg: LarkMessage) -> bool:
    """
    Xử lý các câu lệnh phê duyệt / điều hành từ Chủ nhân trong DM 1-1.
    Trả về True nếu tin nhắn khớp lệnh điều hành và đã xử lý, ngược lại trả về False.
    """
    if not msg.text:
        return False

    lark_service = _resolve_lark_service()

    clean_text = msg.text.strip()
    text_lower = clean_text.lower()
    print(f"👑 [LARK DM CHỦ NHÂN] Nhận lệnh từ chủ nhân: '{clean_text}'")

    # -------------------------------------------------------------------------
    # A. LỆNH XEM CHI TIẾT DAILY DIGEST
    # -------------------------------------------------------------------------
    if "xem digest" in text_lower or "chi tiết digest" in text_lower:
        latest_master = await digest_service.get_latest_pending_master_digest()
        if latest_master:
            dm_text = latest_master.to_executive_dm_text()
            await lark_service.send_bot_dm_to_owner(dm_text)
            return True

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
        return True

    # -------------------------------------------------------------------------
    # B. LỆNH DUYỆT DAILY DIGEST (MASTER DIGEST HOẶC ĐƠN LẺ)
    # -------------------------------------------------------------------------
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
            return True

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
        return True

    # -------------------------------------------------------------------------
    # C. LỆNH TỪ CHỐI / HỦY DAILY DIGEST
    # -------------------------------------------------------------------------
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
            return True

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
        return True

    # -------------------------------------------------------------------------
    # D. LỆNH DUYỆT & GỬI BẢN NHÁP CÂU TRẢ LỜI: [Gửi] / [Duyệt] / [OK]
    # -------------------------------------------------------------------------
    send_keywords = ("gửi", "gui", "ok", "duyệt", "duyet", "gửi đi", "gui di", "send", "yes", "1")
    if text_lower in send_keywords or text_lower.startswith(("gửi ", "gui ", "duyệt ")):
        ok, detail, draft, _ = await draft_service.send_latest(msg.sender_id)
        if not draft:
            await lark_service.send_bot_dm_to_owner(f"⚠️ {detail}")
            return True
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
        return True

    # -------------------------------------------------------------------------
    # E. LỆNH BỎ BẢN NHÁP: [Bỏ] / [Hủy]
    # -------------------------------------------------------------------------
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
        return True

    # -------------------------------------------------------------------------
    # F. LỆNH SỬA BẢN NHÁP: [Sửa: <nội dung>]
    # -------------------------------------------------------------------------
    if text_lower.startswith(("sửa:", "sua:", "sửa ", "sua ", "edit:")):
        separator = ":" if ":" in clean_text else " "
        parts = clean_text.split(separator, 1)
        edited_content = parts[1].strip() if len(parts) > 1 else ""
        if not edited_content:
            await lark_service.send_bot_dm_to_owner(
                "⚠️ Vui lòng nhập nội dung chỉnh sửa sau dấu hai chấm. Ví dụ:\n"
                "Sửa: Dự án này do Tuấn PM lead."
            )
            return True

        print(f"✏️ [DM APPROVAL] Chỉnh sửa và gửi nội dung mới vào nhóm: \"{edited_content[:80]}...\"")
        ok, detail, draft, _ = await draft_service.send_latest(
            msg.sender_id,
            approved_content=edited_content,
        )
        if not draft:
            await lark_service.send_bot_dm_to_owner(f"⚠️ {detail}")
            return True
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
        return True

    return False
