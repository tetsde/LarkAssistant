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

    # 1. Tránh lặp vô hạn nếu chính tài khoản của bạn vừa gửi tin nhắn này
    if msg.is_self or msg.sender_id == lark_service.known_user_open_id:
        print(f"ℹ️ Bỏ qua tin nhắn do chính bạn gửi ({msg.sender_id}) - Đã chặn vòng lặp.")
        return

    # 2. Bỏ qua tin nhắn từ Bot
    if msg.is_bot:
        print(f"ℹ️ Bỏ qua tin nhắn từ Bot ứng dụng ({msg.sender_id}).")
        return

    channel_type = "GROUP (WebSocket Real-time)" if msg.chat_type == "group" else "DM 1-1 (User Polling)"
    print(f"📡 Kênh tiếp nhận : {channel_type}")

    # Chuẩn bị danh tính User phản hồi (Tống Phước Hoài Nam)
    user_info = lark_service.get_current_user()
    responder_name = user_info.get("name", "Tống Phước Hoài Nam")
    print(f"👤 Danh tính phản hồi: {responder_name}")

    # Nhận diện tên đích danh người hỏi (VD: Hoài Phước)
    target_user_name = "bạn"
    if msg.mentions:
        for m in msg.mentions:
            m_name = m.get("name", "")
            if m_name and not ("bot" in m_name.lower() or "hilark" in m_name.lower()):
                target_user_name = m_name
                break
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
