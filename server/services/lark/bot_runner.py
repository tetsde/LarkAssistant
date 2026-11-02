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
from typing import Dict, Optional

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


def _has_registered_custom_apps() -> bool:
    """Return whether this server is running tenant-scoped Custom Apps."""
    try:
        from database.db import get_sync_db

        db = get_sync_db()
        collection = getattr(settings, "MONGO_LARK_APPS_COLLECTION", "lark_app_credentials")
        return bool(db[collection].find_one({
            "tenant_key": {"$exists": True, "$nin": [None, ""]},
            "status": {"$ne": "revoked"},
        }, {"_id": 1}))
    except Exception as exc:
        logger.debug("Không kiểm tra được chế độ Custom App scoped: %s", exc)
        return False


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
    from services.lark.runtime import get_current_lark_service
    active_lark_service = get_current_lark_service(lark_service)
    logger.info(
        "[INGRESS] msg=%s chat=%s type=%s sender=%s owner_hint=%s text=%r",
        msg.message_id, msg.chat_id, msg.chat_type, msg.sender_id, msg.is_self, msg.text,
    )

    # 1. Bỏ qua tin nhắn từ Bot
    if msg.is_bot:
        logger.debug("[DROP] msg=%s reason=bot_message", msg.message_id)
        return

    # 2. Xác định danh tính Chủ nhân (Lãnh đạo) có hỗ trợ Multi-Tenant
    tenant_admin_open_id = None
    if msg.tenant_key:
        tenant_admin_open_id = active_lark_service.get_tenant_admin(msg.tenant_key)
        if not tenant_admin_open_id:
            try:
                from database.db import get_tenant_config
                t_cfg = await get_tenant_config(msg.tenant_key)
                if t_cfg and t_cfg.get("admin_open_id"):
                    tenant_admin_open_id = t_cfg["admin_open_id"]
                    active_lark_service.register_tenant_admin(msg.tenant_key, tenant_admin_open_id)
            except Exception as te:
                logger.debug(f"Không thể tra cứu admin_open_id cho tenant {msg.tenant_key}: {te}")

    if tenant_admin_open_id:
        is_owner = bool(msg.sender_id == tenant_admin_open_id)
        if is_owner:
            msg.is_self = True
    else:
        is_owner = bool(
            msg.is_self
            or (active_lark_service.owner_open_id and msg.sender_id == active_lark_service.owner_open_id)
            or (msg.chat_type == "p2p" and not active_lark_service.owner_open_id)
        )

    # 3. Xử lý tệp đính kèm hoặc liên kết tài liệu Lark (EDL-0010)
    if await handle_document_or_links(msg, is_owner=is_owner):
        return

    # 4. Xử lý tương tác trong DM 1-1 (P2P): chỉ kích hoạt khi nhắn riêng với Bot
    if msg.chat_type == "p2p":
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
        last_run_dates: Dict[str, str] = {}
        default_target_hm = (settings.DIGEST_SCHEDULE_TIME or "23:00").strip()
        logger.info("[SCHEDULER] Digest scheduler started default_time=%s", default_target_hm)

        while not _scheduler_stop_event.is_set():
            try:
                # Ngủ ngắt quãng an toàn (kiểm tra stop_event mỗi 5s, tối đa 30s)
                if _scheduler_stop_event.wait(timeout=30):
                    break

                now_vn = get_vietnam_now()
                current_hm = now_vn.strftime("%H:%M")
                today_str = get_current_digest_date()

                if True:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        async def _run_all_tenants():
                            from database.db import get_tenant_config, get_tenants_collection
                            active_tenants = []
                            try:
                                t_col = get_tenants_collection()
                                async for t_doc in t_col.find({"status": {"$ne": "uninstalled"}}):
                                    tk = t_doc.get("tenant_key")
                                    if tk:
                                        active_tenants.append(tk)
                            except Exception as te:
                                logger.debug(f"Không thể tra cứu danh sách tenant cho scheduler: {te}")

                            if active_tenants:
                                for tk in active_tenants:
                                    try:
                                        target_hm = default_target_hm
                                        t_doc = await get_tenant_config(tk)
                                        admin_id = t_doc.get("admin_open_id") if t_doc else None
                                        if admin_id:
                                            from services.user_settings_service import user_settings_service
                                            user_cfg = await user_settings_service.get_user_settings(admin_id, tenant_key=tk)
                                            if user_cfg and user_cfg.digest_schedule_time:
                                                target_hm = user_cfg.digest_schedule_time

                                        if current_hm != target_hm or last_run_dates.get(tk) == today_str:
                                            continue

                                        m = await digest_service.run_scheduled_daily_digests(
                                            date=today_str,
                                            require_approval=settings.DIGEST_REQUIRE_APPROVAL,
                                            tenant_key=tk,
                                        )
                                        last_run_dates[tk] = today_str
                                        logger.info("[SCHEDULER] tenant=%s time=%s digest=started", tk, target_hm)
                                        if m and m.total_groups > 0:
                                            logger.info("[SCHEDULER] tenant=%s digest=completed groups=%d messages=%d", tk, m.total_groups, m.total_messages)
                                    except Exception as ex:
                                        logger.error(f"Lỗi khi chạy scheduled digest cho tenant {tk}: {ex}")
                            else:
                                # Fallback Single-Tenant
                                if current_hm != default_target_hm or last_run_dates.get("__single__") == today_str:
                                    return
                                m = await digest_service.run_scheduled_daily_digests(
                                    date=today_str,
                                    require_approval=settings.DIGEST_REQUIRE_APPROVAL,
                                )
                                last_run_dates["__single__"] = today_str
                                if m and m.total_groups > 0:
                                    logger.info("[SCHEDULER] digest=completed groups=%d messages=%d", m.total_groups, m.total_messages)

                        loop.run_until_complete(_run_all_tenants())
                    finally:
                        loop.close()
            except Exception as e:
                logger.error("[SCHEDULER] digest scheduler error: %s", e, exc_info=True)

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

    # 3. Kiểm tra token. Với nhiều Custom App, không được ping token legacy
    # của singleton vì token thật được resolve/refresh theo từng tenant + app.
    scoped_apps_mode = _has_registered_custom_apps()
    if scoped_apps_mode:
        token_res = None
        print("🔐 TOKEN MODE: tenant-scoped Custom App (kiểm tra/refresh theo từng tenant)")
    else:
        from services.auth.token_verifier import check_and_warn_token
        token_res = check_and_warn_token(token=lark_service.user_access_token)

    # 4. Thông tin người dùng
    user_info = {} if scoped_apps_mode else lark_service.get_current_user()
    if "name" in user_info:
        status_suffix = "" if token_res and token_res.is_valid else " ⚠️ [Chế độ An Toàn - Token hết hạn]"
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
    try:
        # D. Đăng ký handler tự động đồng bộ Documents sang WeKnora & MongoDB khi có sự kiện Bitable
        lark_service.register_bitable_record_handler(scope_service.handle_bitable_record_changed_event)

        # E. Non-blocking Bootstrap: Chuyển các network call đồng bộ lúc startup sang background task
        async def _async_bitable_bootstrap():
            try:
                from services.lark.base_provision_service import base_provision_service
                from database.db import get_tenants_collection

                # 1. Phân giải cấu hình Base đang hoạt động (MongoDB system_config / tenants)
                active_cfg = await base_provision_service.get_active_base_config()
                if active_cfg and active_cfg.app_token:
                    lark_base_service.app_token = active_cfg.app_token
                    lark_base_service.table_id = active_cfg.chat_scope_table_id

                # A. Tập hợp tất cả các Base app_token cần subscribe
                base_tokens = set()
                if lark_base_service.app_token:
                    base_tokens.add(lark_base_service.app_token)
                if active_cfg and active_cfg.app_token:
                    base_tokens.add(active_cfg.app_token)

                tenant_keys = []
                try:
                    t_col = get_tenants_collection()
                    async for t_doc in t_col.find({"bitable_app_token": {"$exists": True, "$ne": ""}}):
                        btok = t_doc.get("bitable_app_token")
                        if btok:
                            base_tokens.add(btok)
                        tk = t_doc.get("tenant_key")
                        if tk:
                            tenant_keys.append(tk)
                except Exception as t_err:
                    logger.debug(f"Không thể đọc danh sách tenants để subscribe Base: {t_err}")

                # Đăng ký subscribe tất cả các Base trên Lark Cloud
                for btok in base_tokens:
                    sub_ok = await asyncio.to_thread(lark_base_service.subscribe_events, btok)
                    if sub_ok:
                        print(f"📊 [LARK BASE] Đã đăng ký theo dõi sự kiện Bitable (App: {btok})")

                # C. Dọn dẹp và chuẩn hóa schema cho các Base doanh nghiệp
                from services.lark.base_provision_service import base_provision_service
                for tk in tenant_keys:
                    try:
                        await base_provision_service.repair_enterprise_base_schema(tk)
                    except Exception as rep_err:
                        logger.debug(f"repair schema error cho tenant {tk}: {rep_err}")

                # D. Đồng bộ chính sách ban đầu cho từng tenant
                from services.knowledge.policy_sync import policy_sync_service
                for tk in tenant_keys:
                    try:
                        await policy_sync_service.sync_policies(force=True, tenant_key=tk)
                    except Exception as pol_err:
                        logger.debug(f"policy sync error cho tenant {tk}: {pol_err}")

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
