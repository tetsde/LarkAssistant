"""
HiLark Bot - Runner Trả Lời Trực Tiếp Bằng Danh Tính User (Không Dùng Bot)
========================================================================
Vị trí: server/run_lark_bot.py

Chạy:
    uv run python run_lark_bot.py

Cơ chế:
    - Nhận tin nhắn qua Lark WebSocket thời gian thực.
    - Trả lời tin nhắn BẰNG CHÍNH DANH TÍNH CỦA BẠN .
    - Trên Lark sẽ hiện ra như chính bạn đang tự gõ trả lời, KHÔNG CÓ LOGO HAY MÁC BOT!
"""

import os
import sys
from datetime import datetime

# Đảm bảo import được module từ server
SERVER_ROOT = os.path.dirname(os.path.abspath(__file__))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from services.lark import lark_service, LarkMessage
from services.draft_store import draft_store, PendingDraft
from routers.chat import process_chat_pipeline


# =============================================================================
# ĐĂNG KÝ HÀM XỬ LÝ: CHAT PIPELINE (TEXT_FILTER + JEV ROUTING + AS_USER REPLY)
# =============================================================================

@lark_service.on_message
async def handle_incoming_message(msg: LarkMessage):
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

    # 2. Xử lý tin nhắn do chính bạn gửi:
    is_owner = bool(msg.is_self or msg.sender_id == lark_service.known_user_open_id)
    if is_owner:
        # Nếu nhắn trong GROUP: Bỏ qua để chống loop tự trả lời chính mình
        if msg.chat_type == "group":
            print(f"ℹ️ Bỏ qua tin nhắn do chính bạn gửi trong GROUP ({msg.sender_id}) - Đã chặn vòng lặp.")
            return

        # Nếu nhắn trong DM 1-1: Đây là chủ nhân đang chat/ra lệnh trực tiếp cho Bot!
        clean_text = msg.text.strip()
        text_lower = clean_text.lower()
        print(f"👑 [LARK DM CHỦ NHÂN] Nhận lệnh từ chủ nhân: '{clean_text}'")

        # --- A. LỆNH DUYỆT & GỬI BẢN NHÁP: [Gửi] / [Duyệt] / [OK] ---
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

        # --- B. LỆNH BỎ BẢN NHÁP: [Bỏ] / [Hủy] ---
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

        # --- C. LỆNH SỬA BẢN NHÁP: [Sửa: <nội dung>] ---
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

    channel_type = "GROUP (WebSocket Real-time)" if msg.chat_type == "group" else "DM 1-1 (User Polling)"
    print(f"📡 Kênh tiếp nhận : {channel_type}")

    # Chuẩn bị danh tính User phản hồi (Tống Phước Hoài Nam)
    user_info = lark_service.get_current_user()
    responder_name = user_info.get("name", "Tống Phước Hoài Nam")
    print(f"👤 Danh tính phản hồi: {responder_name}")

    # Nhận diện tên đích danh người hỏi (VD: Hoài Phước)
    target_user_name = "bạn"
    # 1. Nếu có mention ai đó mà KHÔNG PHẢI là bot và KHÔNG PHẢI là responder (chủ nhân)
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

    # 2. Nếu người hỏi mention chính responder, lấy tên của người gửi tin nhắn (sender_id)
    if target_user_name == "bạn" and msg.sender_id:
        sender_real_name = lark_service.get_user_name(msg.sender_id)
        if sender_real_name:
            target_user_name = sender_real_name

    # 3. Fallback theo từ khóa xưng hô trong tin nhắn
    if target_user_name == "bạn":
        if "phước" in msg.text.lower() or "phuoc" in msg.text.lower():
            target_user_name = "Hoài Phước"

    # 3. Chuyển vào Unified Chat Pipeline (text_filter -> JEV Routing -> Memory/RAG)
    print(f"⚙️ Đang xử lý qua Chat Pipeline (đích danh: '{target_user_name}' -> JEV Routing)...")
    try:
        result = await process_chat_pipeline(
            query=msg.text,
            sender=msg.sender_id,
            channel=f"lark_{msg.chat_type}",
            message_id=msg.message_id,
            chat_id=msg.chat_id,
            reply_to_lark=True,  # Tự động gửi reply nhân danh User khi JEV yêu cầu
            user_name=target_user_name,
            responder_name=responder_name,
            role="Project Lead",
        )
    except Exception as e:
        print(f"❌ Lỗi khi thực thi pipeline: {e}")
        import traceback
        traceback.print_exc()
        return

    # 4. Hiển thị kết quả chi tiết theo quyết định định tuyến của JEV
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
        print(f"   (Không gửi tin nhắn trả lời để tránh làm phiền)")

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
            print(f"   (Tin nhắn trên Lark hiển thị avatar & tên của bạn, KHÔNG CÓ LOGO BOT)")
        else:
            print(f"⚠️ Trạng thái gửi reply Lark: {lark_res}")

    print("=" * 65 + "\n")


def main():
    print("\n" + "=" * 65)
    print("🚀 KHỞI ĐỘNG HILARK - MÔ HÌNH HYBRID (GROUP = EVENT, DM = POLLING)")
    print("=" * 65)
    print(f"App ID : {lark_service.app_id}")
    print(f"Domain : {lark_service.domain}")

    # Lấy thông tin User hiện tại từ token trong .env
    user_info = lark_service.get_current_user()
    if "name" in user_info:
        print(f"👤 DANH TÍNH HOẠT ĐỘNG: {user_info['name']}")
        print(f"   - Open ID           : {user_info['open_id']}")
        print(f"   - Group Chats       : ⚡ WebSocket Event (Real-time 0ms)")
        print(f"   - DM 1-1 Chats      : 🔄 User Token Polling (Chu kỳ 2.5s)")
        print(f"   - Chế độ gửi tin    : 100% USER IDENTITY (as_user=True)")
    else:
        print(f"⚠️ User Token         : {user_info.get('error')}")

    print("-" * 65)
    print("💡 Mọi tin nhắn phản hồi sẽ hiện ra dưới danh tính Tống Phước Hoài Nam!")
    print("=" * 65)

    # Khởi động chế độ Hybrid
    lark_service.start_hybrid_runner(dm_poll_interval=2.5)


if __name__ == "__main__":
    main()
