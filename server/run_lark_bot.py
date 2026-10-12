"""
HiLark Bot - Runner Trả Lời Trực Tiếp Bằng Danh Tính User (Không Dùng Bot)
========================================================================
Vị trí: server/run_lark_bot.py

Chạy:
    uv run python run_lark_bot.py

Cơ chế:
    - Nhận tin nhắn qua Lark WebSocket thời gian thực.
    - Trả lời tin nhắn BẰNG CHÍNH DANH TÍNH CỦA BẠN (Tống Phước Hoài Nam).
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


# =============================================================================
# ĐĂNG KÝ HÀM XỬ LÝ: TRẢ LỜI BẰNG CHÍNH DANH TÍNH CỦA USER
# =============================================================================

@lark_service.on_message
async def handle_incoming_message(msg: LarkMessage):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("\n" + "=" * 65)
    print("🔔 [LARK EVENT] BẮT ĐƯỢC TIN NHẮN TỪ LARK:")
    print("-" * 65)
    print(f"🕒 Thời gian    : {now_str}")
    print(f"💬 Cuộc trò chuyện: {msg.chat_id} (Loại: {msg.chat_type})")
    print(f"👤 Người gửi    : {msg.sender_id} {'[CHÍNH BẠN]' if msg.is_self else '[USER KHÁC]'}")
    print(f"🆔 Message ID   : {msg.message_id}")
    print(f"📄 NỘI DUNG     : \"{msg.text}\"")
    print("-" * 65)

    # Tránh lặp vô hạn nếu chính tài khoản của bạn vừa gửi câu trả lời này
    if msg.is_self and msg.text.startswith("[Trợ lý Nam]"):
        print("ℹ️ Bỏ qua tin nhắn do chính tiến trình tự động phát ra.")
        return

    # Chuẩn bị nội dung trả lời nhân danh Tống Phước Hoài Nam
    user_info = lark_service.get_current_user()
    user_name = user_info.get("name", "Tống Phước Hoài Nam")
    
    reply_text = f"[Trợ lý {user_name}]: Đã nhận được thông tin: '{msg.text}'. Mình đang xử lý nhé!"
    print(f"👉 Đang gửi tin nhắn trả lời nhân danh '{user_name}' (as_user=True)...")

    # GỬI REPLY DƯỚI DANH NGHĨA USER (TỐNG PHƯỚC HOÀI NAM)
    res = await lark_service.areply_text(
        message_id=msg.message_id,
        text=reply_text,
        as_user=True,  # 👈 QUAN TRỌNG: Gửi bằng danh tính User, KHÔNG PHẢI BOT
    )

    if res.get("success"):
        print(f"✔ ĐÃ TRẢ LỜI THÀNH CÔNG NHÂN DANH {user_name.upper()}!")
        print(f"   (Tin nhắn trên Lark sẽ hiển thị tên và avatar của bạn, KHÔNG CÓ MÁC BOT)")
    else:
        print(f"❌ Lỗi khi gửi tin nhắn as_user: {res}")

    print("=" * 65 + "\n")


def main():
    print("\n" + "=" * 65)
    print("🚀 KHỞI ĐỘNG HILARK - TRẢ LỜI BẰNG CHÍNH DANH TÍNH CỦA USER")
    print("=" * 65)
    print(f"App ID : {lark_service.app_id}")
    print(f"Domain : {lark_service.domain}")

    # Lấy thông tin User hiện tại từ token trong .env
    user_info = lark_service.get_current_user()
    if "name" in user_info:
        print(f"👤 DANH TÍNH HOẠT ĐỘNG: {user_info['name']}")
        print(f"   - Open ID           : {user_info['open_id']}")
        print(f"   - Chế độ gửi tin    : 100% USER IDENTITY (as_user=True)")
    else:
        print(f"⚠️ User Token         : {user_info.get('error')}")

    print("-" * 65)
    print("Đang mở kết nối WebSocket tới Lark...")
    print("💡 Mọi tin nhắn phản hồi sẽ hiện ra dưới danh tính Tống Phước Hoài Nam!")
    print("=" * 65)

    lark_service.start_ws_client(background=False)


if __name__ == "__main__":
    main()
