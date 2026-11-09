"""
HiLark Bot Service - Unified Background Runner & Event Dispatcher
=================================================================
Vị trí: server/services/bot_service.py

Mục đích:
    - Điều phối toàn bộ vòng đời của Lark Bot (Webhook Event Handlers, Queue, Scheduler, Base Sync).
    - Tích hợp trực tiếp vào FastAPI Lifespan để chạy trên 1 tiến trình duy nhất.
    - Cung cấp Root Dispatcher thanh lịch điều phối tới các bot_handlers chuyên biệt.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime
from typing import Dict, Optional, Tuple

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
from services.knowledge.chat_scopes import scope_service

# `lark_base_service` chi được import ở đây để giữ tương thích với các module/test cũ
# tham chiếu `services.lark.bot_runner.lark_base_service`; bot_runner không còn ghi
# field lên singleton này.
from services.lark.bitable import lark_base_service  # noqa: F401 (import-compat)

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
_bot_started = False


def _get_startup_tenant_counts() -> Tuple[int, int]:
    """Return (registered_apps, ready_tenants) counts stored in MongoDB."""
    try:
        from database.db import get_sync_db

        db = get_sync_db()
        app_col = getattr(settings, "MONGO_LARK_APPS_COLLECTION", "lark_app_credentials")
        tenant_col = getattr(settings, "MONGO_TENANTS_COLLECTION", "tenants")
        registered_apps = db[app_col].count_documents({
            "tenant_key": {"$exists": True, "$nin": [None, ""]},
            "status": {"$ne": "revoked"},
        })
        ready_tenants = db[tenant_col].count_documents({"status": "ready"})
        return int(registered_apps), int(ready_tenants)
    except Exception as exc:
        logger.debug("[BOT] tenant_count_lookup_failed error=%s", exc)
        return 0, 0


# =============================================================================
# 1. HÀM XỬ LÝ SỰ KIỆN TIN NHẮN TỪ LARK (CORE DISPATCHER)
# =============================================================================

async def handle_lark_incoming_message(msg: LarkMessage) -> None:
    """
    Dispatcher xử lý mọi tin nhắn đến từ Lark (qua HTTP Webhook Gateway):
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
                logger.debug("[BOT] tenant_admin_lookup_failed tenant=%s error=%s", msg.tenant_key, te)

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
        last_run_slots: Dict[str, str] = {}
        default_target_hm = (settings.DIGEST_SCHEDULE_TIME or "23:00").strip()
        logger.info("[SCHEDULER] started default_time=%s source=mongo_tenants", default_target_hm)

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
                                # Chỉ tenant `ready` được tổng hợp digest: provisioning chưa có
                                # dataset/table, còn inactive/uninstalled đã ngừng nhận báo cáo.
                                async for t_doc in t_col.find({"status": "ready"}):
                                    tk = t_doc.get("tenant_key")
                                    if tk:
                                        active_tenants.append(tk)
                            except Exception as te:
                                logger.debug("[SCHEDULER] tenant_list_failed error=%s", te)

                            # Không còn nhánh "single-tenant fallback": chạy digest mà không có
                            # tenant_key sẽ lấy KB/dataset của doanh nghiệp khác (GĐ2/GĐ5).
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

                                    schedule_key = f"{today_str}|{target_hm}"
                                    if current_hm != target_hm or last_run_slots.get(tk) == schedule_key:
                                        continue

                                    logger.info("[SCHEDULER] digest_started tenant=%s time=%s", tk, target_hm)
                                    m = await digest_service.run_scheduled_daily_digests(
                                        date=today_str,
                                        require_approval=settings.DIGEST_REQUIRE_APPROVAL,
                                        tenant_key=tk,
                                    )
                                    last_run_slots[tk] = schedule_key
                                    if m and m.total_groups > 0:
                                        logger.info(
                                            "[SCHEDULER] digest_completed tenant=%s groups=%d messages=%d",
                                            tk, m.total_groups, m.total_messages,
                                        )
                                except Exception as ex:
                                    logger.error("[SCHEDULER] digest_failed tenant=%s error=%s", tk, ex)

                        loop.run_until_complete(_run_all_tenants())
                    finally:
                        loop.close()
            except Exception as e:
                logger.error("[SCHEDULER] loop_error error=%s", e, exc_info=True)

        logger.info("[SCHEDULER] stopped")

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
      - Khởi động Chat Queue Service (Debouncer & Cooldown Worker)
      - Bật Digest Scheduler daemon thread
      - Kích hoạt chế độ nhận sự kiện qua HTTP Webhook Gateway (/api/lark/events)
    """
    global _bot_started

    if _bot_started:
        logger.debug("[BOT] start_skipped reason=already_started")
        return

    registered_apps, ready_tenants = _get_startup_tenant_counts()
    logger.info(
        "[BOT] starting mode=webhook domain=%s registered_apps=%d ready_tenants=%d",
        lark_service.domain,
        registered_apps,
        ready_tenants,
    )

    # 0. Không nạp `primary_user_token` legacy vào singleton nữa.
    #    Document đó thuộc về MỘT App/tenant cụ thể. Nạp vào `lark_service`/
    #    `lark_base_service` dùng chung sẽ khiến doanh nghiệp B trả lời tin nhắn bằng
    #    danh tính của doanh nghiệp A. User token giờ chỉ đi qua token broker theo
    #    `(tenant_key, app_id, "user")`; sweeper giữ cho các tenant 'ready' còn hạn.
    if getattr(settings, "LARK_USER_ACCESS_TOKEN", ""):
        logger.debug("[BOT] env_user_token_ignored=true reason=tenant_broker_active")

    # 1. Đăng ký Message Handler vào Lark Service
    lark_service.register_handler(handle_lark_incoming_message)

    # 1.1 Khởi động Throttled Chat Queue Service (Debouncer & Cooldown Worker)
    chat_queue_service.start()

    # 2. Khởi động Digest Scheduler
    start_digest_scheduler_daemon()

    # 3. Khởi động Lark Base (Bitable) Sync & Subscribe Service
    try:
        from services.knowledge.chat_scopes import scope_service
        # D. Đăng ký handler tự động đồng bộ Documents sang WeKnora & MongoDB khi có sự kiện Bitable
        lark_service.register_bitable_record_handler(scope_service.handle_bitable_record_changed_event)

        # E. Non-blocking Bootstrap: mọi thao tác Base chạy theo TỪNG tenant, trên
        #    instance `LarkBaseService.for_tenant()` riêng. Trước đây hàm này ghi
        #    `lark_base_service.app_token/table_id` từ "config đang hoạt động" rồi dùng
        #    singleton đó cho tất cả tenant -> Base của tenant A bị tenant B đọc/ghi.
        async def _async_bitable_bootstrap():
            from database.db import get_tenants_collection
            from services.lark.bitable import LarkBaseService
            from services.lark.base_provision_service import base_provision_service
            from services.knowledge.policy_sync import policy_sync_service
            from services.tenancy.tenant_resolver import tenant_resolver
            from core.tenant_errors import TenantResolutionError

            tenant_keys: list[str] = []
            try:
                t_col = get_tenants_collection()
                async for t_doc in t_col.find(
                    {"status": {"$nin": ["uninstalled"]}}, {"tenant_key": 1}
                ):
                    tk = t_doc.get("tenant_key")
                    if tk:
                        tenant_keys.append(str(tk))
            except Exception as t_err:
                logger.debug("[BITABLE] tenant_list_failed error=%s", t_err)

            for tk in tenant_keys:
                try:
                    resources = await tenant_resolver.resolve(tk)
                except TenantResolutionError as res_err:
                    logger.info(
                        "[BITABLE] bootstrap_skipped tenant=%s reason=%s error=%s",
                        tk, type(res_err).__name__, res_err,
                    )
                    continue

                # Mỗi tenant một service riêng, gắn đúng app_token/table_id của nó.
                base_service = LarkBaseService.for_tenant(resources)
                try:
                    sub_ok = await asyncio.to_thread(
                        base_service.subscribe_events, resources.base_app_token
                    )
                    if sub_ok:
                        logger.info("[BITABLE] subscribed tenant=%s app_token=%s", tk, resources.base_app_token)
                except Exception as sub_err:
                    logger.warning("[BITABLE] subscribe_failed tenant=%s error=%s", tk, sub_err)

                try:
                    await base_provision_service.repair_enterprise_base_schema(tk)
                except Exception as rep_err:
                    logger.debug("[BITABLE] repair_schema_failed tenant=%s error=%s", tk, rep_err)

                try:
                    # force=False: dùng hash so sánh, chỉ upload khi doc thực sự thay đổi.
                    # force=True chỉ nên dùng khi user bấm nút "Đồng bộ ngay" trên UI.
                    await policy_sync_service.sync_policies(force=False, tenant_key=tk)
                except Exception as pol_err:
                    logger.debug("[BITABLE] policy_sync_failed tenant=%s error=%s", tk, pol_err)

                try:
                    sync_res = await asyncio.to_thread(base_service.sync_bot_chats)
                    items = sync_res.get("added", []) + sync_res.get("updated", [])
                    if items:
                        logger.info("[BITABLE] chats_synced tenant=%s count=%d", tk, len(items))
                except Exception as sync_err:
                    logger.warning("[BITABLE] sync_chats_failed tenant=%s error=%s", tk, sync_err)

                try:
                    await scope_service.sync_all_groups_from_base(tenant_key=tk)
                except Exception as ex:
                    logger.warning("[BITABLE] scope_sync_failed tenant=%s error=%s", tk, ex)

            if not tenant_keys:
                logger.debug("[BITABLE] bootstrap_skipped reason=no_tenants")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_async_bitable_bootstrap())
            if getattr(settings, "POLICY_SYNC_ENABLED", True):
                from services.knowledge_service import policy_sync_service
                loop.create_task(policy_sync_service.start_loop())
            # Background loop định kỳ đồng bộ Chat Scopes & Nhãn từ Lark Base.
            # Interval 1800s (30 phút) — trước đây hardcode 30s gây 480 Lark Drive
            # requests/giờ + trigger rebuild WeKnora liên tục. Fix: EDL-0073.
            loop.create_task(scope_service.start_loop(interval_seconds=1800))
            # Sweeper tenant-scoped thay cho `start_token_refresh_loop` cũ (vốn còn
            # nhánh fallback đọc legacy token).
            from services.auth.tenant_refresh_sweeper import start_tenant_token_sweeper
            loop.create_task(start_tenant_token_sweeper())
        except RuntimeError:
            pass
    except Exception as e:
        logger.warning("[BOT] bitable_init_failed error=%s", e)

    _bot_started = True
    logger.info("[BOT] ready endpoints=/api/lark/events,/api/lark/card-action")


def stop_bot_service() -> None:
    """Dừng an toàn toàn bộ background threads của Bot khi tắt server."""
    global _bot_started, _scheduler_stop_event
    logger.info("[BOT] stopping")
    _scheduler_stop_event.set()

    # Dừng worker của Chat Queue Service
    try:
        chat_queue_service.stop()
    except Exception as e:
        logger.debug("[BOT] queue_stop_failed error=%s", e)

    _bot_started = False
    logger.info("[BOT] stopped")
