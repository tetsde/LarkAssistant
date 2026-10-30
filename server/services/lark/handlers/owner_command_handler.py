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
from services.claim_service import claim_service as default_claim_service
claim_service = default_claim_service
from services.digest_service import digest_service
from services.draft_service import draft_service
from services.lark import lark_service as default_lark_service
from services.lark.card_builder import PROPERTY_LABELS

logger = logging.getLogger("hilark.bot.owner_command_handler")


def _resolve_lark_service():
    bs = sys.modules.get("services.bot_service") or sys.modules.get("services.lark.bot_runner")
    return getattr(bs, "lark_service", default_lark_service) if bs else default_lark_service


def _resolve_claim_service():
    bs = sys.modules.get("services.bot_service") or sys.modules.get("services.lark.bot_runner")
    return getattr(bs, "claim_service", default_claim_service) if bs else default_claim_service


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
    if any(kw in text_lower for kw in ("xem digest", "chi tiết digest", "xem báo cáo", "xem bao cao", "xem digest hôm nay")):
        latest_master = await digest_service.get_latest_pending_master_digest()
        if latest_master:
            from services.claim_service import claim_service
            from services.lark.card_builder import build_digest_approval_card

            target_date = getattr(latest_master, "date", None)
            date_str = target_date if isinstance(target_date, str) else None
            pending_claims = []
            if date_str:
                try:
                    pending_claims = await claim_service.get_pending_claims_for_date(
                        date_str=date_str
                    )
                except Exception as e:
                    print(f"Lỗi khi lấy pending claims cho lệnh xem digest: {e}")

            cost_summary = None
            try:
                from decorators.cost_telemetry import get_cost_telemetry_summary
                cost_summary = await get_cost_telemetry_summary(hours=24)
            except Exception as e:
                print(f"Lỗi khi lấy cost_summary cho lệnh xem digest: {e}")

            card = build_digest_approval_card(
                latest_master,
                pending_claims=pending_claims,
                cost_summary=cost_summary,
            )
            card_res = await lark_service.send_bot_card_to_owner(card, target_open_id=msg.sender_id)
            if not card_res or not card_res.get("success"):
                dm_text = latest_master.to_executive_dm_text()
                await lark_service.send_bot_dm_to_owner(dm_text)
            return True

        latest_pending = await digest_service.get_latest_pending_approval_digest()
        if not latest_pending:
            await lark_service.send_bot_dm_to_owner("Hiện không có bản báo cáo nào đang chờ duyệt.")
        else:
            md_preview = latest_pending.to_weknora_markdown()
            preview_text = md_preview[:1500] + ("\n...(còn tiếp)" if len(md_preview) > 1500 else "")
            await lark_service.send_bot_dm_to_owner(
                f"CHI TIẾT DAILY DIGEST: {latest_pending.id}\n"
                "------------------------------\n"
                f"{preview_text}\n"
                "------------------------------\n"
                "Nhắn 'Duyệt digest' để nạp vào WeKnora hoặc 'Hủy digest' để từ chối."
            )
        return True

    # -------------------------------------------------------------------------
    # B. LỆNH DUYỆT DAILY DIGEST (MASTER DIGEST HOẶC ĐƠN LẺ)
    # -------------------------------------------------------------------------
    digest_approve_keywords = ("duyệt digest", "duyet digest", "ok digest", "duyệt kb", "duyet kb", "ok kb", "approve digest", "duyệt toàn bộ", "duyet toan bo")
    if any(kw in text_lower for kw in digest_approve_keywords):
        parts = clean_text.split()
        target_id = parts[2] if len(parts) >= 3 and (parts[2].startswith("digest_") or parts[2].startswith("master_digest_")) else None

        # Ưu tiên duyệt Master Daily Digest nếu có hoặc nếu chỉ định ID master
        if (target_id and target_id.startswith("master_digest_")) or (not target_id and await digest_service.get_latest_pending_master_digest()):
            print(f"[DM APPROVAL] Tiến hành DUYỆT Master Daily Digest ({target_id or 'bản gần nhất'})...")
            from services.claim_service import claim_service
            promoted_count = 0
            try:
                promoted_count, _ = await claim_service.approve_all_pending_claims_for_date(
                    approver_info={"user_id": msg.sender_id, "user_name": "Lãnh đạo"}
                )
            except Exception as e:
                print(f"Lỗi khi thăng hạng claims theo lệnh text: {e}")

            ok, msg_reply, mrec = await digest_service.approve_and_sync_master_digest(target_id, approver_open_id=msg.sender_id)
            if ok and mrec:
                claims_info = f"\nThông tin đã duyệt: Đã thăng hạng {promoted_count} thông tin đề xuất thành chính thức." if promoted_count > 0 else ""
                reply_confirm = (
                    "ĐÃ DUYỆT VÀ ĐỒNG BỘ TOÀN BỘ MASTER DAILY DIGEST THÀNH CÔNG!\n"
                    "------------------------------\n"
                    f"Ngày ghi nhận : {mrec.date}\n"
                    f"Mã Master     : {mrec.id}\n"
                    f"Số nhóm duyệt : {mrec.total_groups} nhóm ({mrec.total_messages} tin nhắn)"
                    f"{claims_info}\n"
                    "------------------------------\n"
                    "Tri thức của từng nhóm đã được phân phối nạp chính xác vào đúng Knowledge Base WeKnora tương ứng!"
                )
                await lark_service.send_bot_dm_to_owner(reply_confirm)
            else:
                await lark_service.send_bot_dm_to_owner(f"Không thể duyệt báo cáo: {msg_reply}")
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
            await lark_service.send_bot_dm_to_owner(f"Thông báo: {msg_reply}")
        return True

    # -------------------------------------------------------------------------
    # D. LỆNH DUYỆT THÔNG TIN ĐỀ XUẤT (CLAIMS / FACTS): [Duyệt fact] / [Bỏ fact] / [Sửa fact: ...]
    # -------------------------------------------------------------------------
    claim_service = _resolve_claim_service()

    # 1. Sửa giá trị và duyệt fact
    claim_edit_triggers = (
        "sửa fact:", "sua fact:", "sửa fact ", "sua fact ",
        "sửa claim:", "sua claim:", "sửa claim ", "sua claim ",
    )
    if text_lower.startswith(claim_edit_triggers):
        separator = ":" if ":" in clean_text else " "
        parts = clean_text.split(separator, 1)
        new_val = parts[1].strip() if len(parts) > 1 else ""
        if not new_val:
            await lark_service.send_bot_dm_to_owner(
                "Vui lòng nhập giá trị mới sau dấu hai chấm. Ví dụ: Sửa fact: 50 triệu đồng"
            )
            return True

        ok, msg_reply, target_claim = await claim_service.edit_and_approve_claim(
            new_value=new_val,
            approver_info={"user_id": msg.sender_id, "user_name": "Lãnh đạo"},
        )
        if ok and target_claim:
            prop = target_claim.get("property") or target_claim.get("predicate") or "thông tin"
            prop_label = PROPERTY_LABELS.get(str(prop).lower(), str(prop))
            ent_name = target_claim.get("entity_id") or "Dự án"
            reply_confirm = (
                "Đã cập nhật và duyệt thông tin thành công.\n"
                "----------------------------------------\n"
                f"Thực thể: {ent_name}\n"
                f"Thuộc tính: {prop_label}\n"
                f"Giá trị mới: {new_val}\n"
                "Trạng thái: Chính thức (Đã có hiệu lực cho câu trả lời của nhóm)"
            )
            await lark_service.send_bot_dm_to_owner(reply_confirm)
        else:
            await lark_service.send_bot_dm_to_owner(f"Thông báo: {msg_reply}")
        return True

    # 2. Duyệt fact
    claim_approve_keywords = (
        "duyệt fact", "duyet fact", "ok fact",
        "duyệt claim", "duyet claim", "ok claim",
        "approve fact", "approve claim",
    )
    if any(text_lower == kw or text_lower.startswith(kw + " ") for kw in claim_approve_keywords):
        parts = clean_text.split()
        target_id = parts[2] if len(parts) >= 3 else None
        ok, msg_reply, target_claim = await claim_service.approve_claim(
            claim_id=target_id,
            approver_info={"user_id": msg.sender_id, "user_name": "Lãnh đạo"},
        )
        if ok and target_claim:
            prop = target_claim.get("property") or target_claim.get("predicate") or "thông tin"
            prop_label = PROPERTY_LABELS.get(str(prop).lower(), str(prop))
            ent_name = target_claim.get("entity_id") or "Dự án"
            reply_confirm = (
                "Đã duyệt thông tin đề xuất thành công.\n"
                "----------------------------------------\n"
                f"Thực thể: {ent_name}\n"
                f"Thuộc tính: {prop_label}\n"
                f"Giá trị chính thức: {target_claim.get('value')}\n"
                "Trạng thái: Chính thức (Đã có hiệu lực cho câu trả lời của nhóm)"
            )
            await lark_service.send_bot_dm_to_owner(reply_confirm)
        else:
            await lark_service.send_bot_dm_to_owner(f"Thông báo: {msg_reply}")
        return True

    # 3. Từ chối / Hủy fact
    claim_reject_keywords = (
        "hủy fact", "huy fact", "bỏ fact", "bo fact",
        "hủy claim", "huy claim", "bỏ claim", "bo claim",
        "reject fact", "reject claim",
    )
    if any(text_lower == kw or text_lower.startswith(kw + " ") for kw in claim_reject_keywords):
        parts = clean_text.split()
        target_id = parts[2] if len(parts) >= 3 else None
        ok, msg_reply, target_claim = await claim_service.reject_claim(claim_id=target_id)
        if ok and target_claim:
            prop = target_claim.get("property") or target_claim.get("predicate") or "thông tin"
            prop_label = PROPERTY_LABELS.get(str(prop).lower(), str(prop))
            ent_name = target_claim.get("entity_id") or "Dự án"
            reply_confirm = (
                "Đã từ chối thông tin đề xuất.\n"
                "----------------------------------------\n"
                f"Thực thể: {ent_name}\n"
                f"Thuộc tính: {prop_label}\n"
                f"Giá trị: {target_claim.get('value')}\n"
                "Trạng thái: Đã từ chối (Không đưa vào bộ tri thức nhóm)"
            )
            await lark_service.send_bot_dm_to_owner(reply_confirm)
        else:
            await lark_service.send_bot_dm_to_owner(f"Thông báo: {msg_reply}")
        return True

    # -------------------------------------------------------------------------
    # E. LỆNH DUYỆT & GỬI BẢN NHÁP CÂU TRẢ LỜI: [Gửi] / [Duyệt] / [OK]
    # -------------------------------------------------------------------------
    send_keywords = ("gửi", "gui", "ok", "duyệt", "duyet", "gửi đi", "gui di", "send", "yes", "1")
    if text_lower in send_keywords or text_lower.startswith(("gửi ", "gui ", "duyệt ")):
        ok, detail, draft, _ = await draft_service.send_latest(msg.sender_id)
        if not draft:
            await lark_service.send_bot_dm_to_owner(f"Thông báo: {detail}")
            return True
        if ok:
            confirm_text = (
                "Đã gửi câu trả lời vào nhóm thảo luận thành công.\n"
                "----------------------------------------\n"
                f"Người trả lời: {draft.responder_name or 'User'}\n"
                f"Câu hỏi: \"{draft.query}\"\n\n"
                f"Nội dung đã gửi:\n\"{draft.approved_content}\"\n"
                "Trạng thái: Đã gửi"
            )
            await lark_service.send_bot_dm_to_owner(confirm_text)
        else:
            await lark_service.send_bot_dm_to_owner(
                f"Chưa xác nhận gửi thành công. Bản nháp vẫn ở trạng thái chờ duyệt. Lỗi: {detail}"
            )
        return True

    # -------------------------------------------------------------------------
    # E. LỆNH BỎ BẢN NHÁP: [Bỏ] / [Hủy]
    # -------------------------------------------------------------------------
    discard_keywords = ("bỏ", "bo", "hủy", "huy", "bỏ qua", "bo qua", "discard", "cancel", "no", "0")
    if text_lower in discard_keywords:
        draft = await draft_service.discard_latest(msg.sender_id)
        if draft:
            print(f"[DM APPROVAL] Lãnh đạo đã hủy bản nháp cho message_id={draft.message_id}")
            await lark_service.send_bot_dm_to_owner(
                "Đã hủy bỏ bản nháp thành công.\n"
                "----------------------------------------\n"
                f"Bản nháp cho câu hỏi \"{draft.query}\" đã được hủy.\n"
                "Không có tin nhắn nào được gửi vào nhóm."
            )
        else:
            await lark_service.send_bot_dm_to_owner("Hiện không có bản nháp nào đang chờ duyệt để hủy.")
        return True

    # -------------------------------------------------------------------------
    # F. LỆNH NHỜ AI VIẾT LẠI BẢN NHÁP: [Sửa AI: <yêu cầu>] / [AI sửa: <yêu cầu>]
    # -------------------------------------------------------------------------
    ai_rewrite_triggers = (
        "sửa ai:", "sua ai:", "ai sửa:", "ai sua:",
        "nhờ ai:", "nho ai:", "viết lại:", "viet lai:",
        "sửa ai ", "sua ai ", "ai sửa ", "ai sua ",
    )
    if text_lower.startswith(ai_rewrite_triggers):
        separator = ":" if ":" in clean_text else " "
        parts = clean_text.split(separator, 1)
        boss_instruction = parts[1].strip() if len(parts) > 1 else ""
        if not boss_instruction:
            await lark_service.send_bot_dm_to_owner(
                "Vui lòng nhập yêu cầu cho AI sau dấu hai chấm. Ví dụ: Sửa AI: Từ chối khéo, nhắc em ấy liên hệ kế toán."
            )
            return True

        latest_draft = await draft_service.get_latest_pending(msg.sender_id)
        if not latest_draft:
            await lark_service.send_bot_dm_to_owner(
                "Hiện không có bản nháp nào đang chờ duyệt để viết lại."
            )
            return True

        await lark_service.send_bot_dm_to_owner(
            "Đang điều chỉnh câu trả lời theo chỉ đạo của anh, vui lòng đợi trong giây lát..."
        )

        from services.ai.draft_rewriter import rewrite_draft_with_llm
        rewritten_text = await rewrite_draft_with_llm(
            original_draft=latest_draft.draft_answer,
            query=latest_draft.query,
            boss_instruction=boss_instruction,
            user_name=latest_draft.user_name,
            responder_name=latest_draft.responder_name,
        )

        # Cập nhật bản nháp vào MongoDB
        await draft_service.update_content(latest_draft.id, rewritten_text)
        latest_draft.draft_answer = rewritten_text

        # Gửi thẻ mới với nội dung đã được viết lại
        from services.lark.card_builder import build_draft_card
        updated_card = build_draft_card(
            draft_id=latest_draft.message_id or latest_draft.id,
            chat_title=latest_draft.chat_id,
            user_name=latest_draft.user_name or "Thành viên",
            query=latest_draft.query,
            draft_answer=rewritten_text,
            reason=f"Đã điều chỉnh theo chỉ đạo: \"{boss_instruction}\"",
            is_confidential=False,
        )

        await lark_service.send_bot_card_to_owner(updated_card, target_open_id=msg.sender_id)
        return True

    # -------------------------------------------------------------------------
    # G. LỆNH TỰ SỬA BẢN NHÁP: [Sửa: <nội dung>]
    # -------------------------------------------------------------------------
    if text_lower.startswith(("sửa:", "sua:", "sửa ", "sua ", "edit:")):
        separator = ":" if ":" in clean_text else " "
        parts = clean_text.split(separator, 1)
        edited_content = parts[1].strip() if len(parts) > 1 else ""
        if not edited_content:
            await lark_service.send_bot_dm_to_owner(
                "Vui lòng nhập nội dung chỉnh sửa sau dấu hai chấm. Ví dụ:\n"
                "Sửa: Dự án này do Tuấn phụ trách chính."
            )
            return True

        print(f"[DM APPROVAL] Chỉnh sửa và gửi nội dung mới vào nhóm: \"{edited_content[:80]}...\"")
        ok, detail, draft, _ = await draft_service.send_latest(
            msg.sender_id,
            approved_content=edited_content,
        )
        if not draft:
            await lark_service.send_bot_dm_to_owner(f"Thông báo: {detail}")
            return True
        if ok:
            confirm_text = (
                "ĐÃ GỬI BẢN CHỈNH SỬA VÀO NHÓM THÀNH CÔNG!\n"
                "----------------------------------------\n"
                f"Người trả lời: {draft.responder_name or 'User'}\n"
                f"Nội dung đã gửi:\n\"{edited_content}\"\n"
                "Trạng thái: Đã gửi"
            )
            await lark_service.send_bot_dm_to_owner(confirm_text)
        else:
            await lark_service.send_bot_dm_to_owner(
                f"Chưa xác nhận gửi thành công. Bản nháp vẫn ở trạng thái chờ duyệt. Lỗi: {detail}"
            )
        return True

    # -------------------------------------------------------------------------
    # H. LỆNH CẤU HÌNH & ONBOARDING SCREEN GUIDE: [cài đặt / config / setup / byok / ...]
    # -------------------------------------------------------------------------
    config_keywords = (
         "/config", "/setup"
    )
    if any(text_lower == kw or text_lower.startswith(f"{kw} ") for kw in config_keywords):
        from services.lark.card_builder import build_onboarding_welcome_card

        user_name = getattr(msg, "user_name", "") or getattr(msg, "sender_name", "") or "bạn"
        card = build_onboarding_welcome_card(
            open_id=msg.sender_id,
            user_name=user_name,
        )
        await lark_service.send_bot_card_to_owner(card, target_open_id=msg.sender_id)
        return True

    return False

