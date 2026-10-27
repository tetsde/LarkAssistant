"""
HiLark Bot Service - Unified Background Runner & Event Dispatcher
=================================================================
Vị trí: server/services/bot_service.py

Mục đích:
    - Điều phối toàn bộ vòng đời của Lark Bot (WebSocket Connection, Handlers, Scheduler).
    - Tích hợp trực tiếp vào FastAPI Lifespan để chạy trên 1 tiến trình duy nhất.
    - Cung cấp Root Dispatcher thanh lịch điều phối tới các bot_handlers chuyên biệt.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Optional

from core.config import settings
from models.lark import LarkMessage
from models.memory import get_vietnam_now

# Re-exports for backward compatibility and test mock patching
from services.workflows.chat_workflow import process_chat_pipeline, process_document_to_claims
from services.workflows.digest_workflow import digest_service
from services.workflows.draft_workflow import draft_service
from services.workflows.chat_queue import chat_queue_service
from services.workflows.digest_formatters import get_current_digest_date
from services.knowledge.doc_parser import doc_parser_service
from services.lark import lark_service
from services.lark.bitable import lark_base_service
from services.knowledge.chat_scopes import scope_service

# Modular Handlers (EDL-0009 Phase 3 Refactoring)
from services.lark.handlers import (
    handle_document_or_links,
    handle_member_message,
    handle_owner_dm_command,
)

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
      1. Bỏ qua tin nhắn từ Bot / App.
      2. Phân giải tệp đính kèm nhị phân hoặc liên kết tài liệu Lark (document_handler).
      3. Điều phối câu lệnh điều hành của Chủ nhân trong DM 1-1 (owner_command_handler).
      4. Điều phối tin nhắn thông thường vào Staging và Chat Pipeline / Queue (member_message_handler).
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

    # 2. Xác định danh tính Chủ nhân (Lãnh đạo)
    is_owner = bool(
        msg.is_self
        or (lark_service.owner_open_id and msg.sender_id == lark_service.owner_open_id)
    )

    # 3. Xử lý tệp đính kèm hoặc liên kết tài liệu Lark (EDL-0010)
    if await handle_document_or_links(msg, is_owner=is_owner):
        return

    # 4. Xử lý lệnh của Chủ nhân trong DM 1-1
    if is_owner and msg.chat_type == "p2p":
        if await handle_owner_dm_command(msg):
            return

    # 5. Điều phối tin nhắn thành viên/chủ nhân trong nhóm chat
    await handle_member_message(msg, is_owner=is_owner)


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

    # 0. Đồng bộ User Token mới nhất từ MongoDB vào lark_service (nếu có)
    try:
        from database.db import get_sync_db
        db = get_sync_db()
        doc = db[settings.MONGO_AUTH_COLLECTION].find_one({"_id": "primary_user_token"})
        if doc and doc.get("access_token"):
            lark_service.user_access_token = doc["access_token"]
            lark_service._last_token_check = None
            if doc.get("open_id"):
                lark_service.known_user_open_id = doc["open_id"]
            if not lark_service._current_user_profile:
                lark_service._current_user_profile = {}
            lark_service._current_user_profile["name"] = doc.get("user_name", "User")
            lark_service._current_user_profile["open_id"] = doc.get("open_id", "")
            if lark_base_service:
                lark_base_service.user_access_token = doc["access_token"]
    except Exception as e:
        logger.debug(f"Không thể nạp token sync từ MongoDB: {e}")

    # 1. Đăng ký Message Handler vào Lark Service
    lark_service.register_handler(handle_lark_incoming_message)

    # 1.1 Khởi động Throttled Chat Queue Service (Debouncer & Cooldown Worker)
    chat_queue_service.start()

    # 2. Khởi động Digest Scheduler
    start_digest_scheduler_daemon()

    # 3. Kiểm tra tính hợp lệ và Ping User Access Token (Chống Crash)
    from services.auth.token_verifier import check_and_warn_token
    token_res = check_and_warn_token(token=lark_service.user_access_token)

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
            # D. Đăng ký handler tự động đồng bộ Documents sang WeKnora & MongoDB khi có sự kiện Bitable
            lark_service.register_bitable_record_handler(scope_service.handle_bitable_record_changed_event)

            # E. Non-blocking Bootstrap: Chuyển các network call đồng bộ lúc startup sang background task
            async def _async_bitable_bootstrap():
                try:
                    # A. Đăng ký subscribe sự kiện trên Lark Cloud trong threadpool
                    sub_ok = await asyncio.to_thread(lark_base_service.subscribe_events)
                    if sub_ok:
                        print(f"📊 [LARK BASE] Đã đăng ký theo dõi sự kiện Bitable (App: {lark_base_service.app_token})")

                    # B. Quét và đồng bộ các nhóm chat bot ban đầu vào Base trong threadpool
                    sync_res = await asyncio.to_thread(lark_base_service.sync_bot_chats)
                    items = sync_res.get("added", []) + sync_res.get("updated", [])
                    if items:
                        print(f"🔄 [LARK BASE] Đã đồng bộ ban đầu {len(items)} nhóm chat vào Base.")
                except Exception as ex:
                    logger.warning(f"Lỗi trong background bitable bootstrap: {ex}")

                # Quét và đồng bộ ban đầu các tài liệu và phân quyền nhóm từ Base sang WeKnora & MongoDB
                try:
                    await scope_service.sync_all_groups_from_base()
                except Exception as ex:
                    logger.warning(f"Lỗi trong sync_all_groups_from_base: {ex}")

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_async_bitable_bootstrap())
                if getattr(settings, "POLICY_SYNC_ENABLED", True):
                    from services.knowledge_service import policy_sync_service
                    loop.create_task(policy_sync_service.start_loop())
                from services.auth_service import start_token_refresh_loop
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
