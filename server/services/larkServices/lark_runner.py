"""
HiLark Lark Runner
==================
Vị trí: server/services/lark_runner.py

Mục đích:
    Quản lý kết nối thời gian thực với Lark:
      1. WebSocket Client   - Kết nối liên tục với Lark (không cần Public IP)
      2. DM Polling         - Quét hộp thư 1-1 theo chu kỳ
      3. Hybrid Runner      - Kết hợp cả hai: WebSocket cho Group, Polling cho DM 1-1

Import:
    from services.lark_runner import LarkRunnerMixin
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict, List, Optional

import lark_oapi as lark
import lark_oapi.ws as lark_ws

from models.lark import LarkMessage

logger = logging.getLogger("hilark.lark")


class LarkRunnerMixin:
    """
    Mixin quản lý kết nối thời gian thực:
      - WebSocket (nhận sự kiện Group chat tức thì)
      - DM Polling (quét hộp thư 1-1 theo chu kỳ)
      - Hybrid Runner (kết hợp cả hai, phân luồng tự động)
    """

    # -------------------------------------------------------------------------
    # WEBSOCKET CLIENT (LOCAL DEV KHÔNG CẦN DOMAIN/NGROK)
    # -------------------------------------------------------------------------

    def start_ws_client(self, background: bool = False):
        """
        Khởi động kết nối WebSocket (Persistent Connection) trực tiếp với Lark.
        Tạo event loop riêng biệt để tránh xung đột với FastAPI / Uvicorn.
        """
        # Chủ động nạp thông tin User Profile khi khởi động
        try:
            user_prof = self.get_current_user()
            if "name" in user_prof:
                logger.info(f"👤 Khởi động Lark Service đại diện cho User: {user_prof['name']}")
        except Exception:
            pass

        def _run_client():
            # Tạo event loop riêng biệt cho background thread của WebSocket
            # để tránh xung đột với event loop đang chạy của FastAPI / Uvicorn
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            import lark_oapi.ws.client as ws_module
            ws_module.loop = new_loop

            ws_client = lark_ws.Client(
                app_id=self.app_id,
                app_secret=self.app_secret,
                event_handler=self.event_dispatcher,
                domain=self.domain,
                log_level=lark.LogLevel.INFO,
            )
            try:
                ws_client.start()
            except Exception as e:
                logger.error(f"Lark WebSocket gặp lỗi khi chạy: {e}", exc_info=True)
            finally:
                try:
                    new_loop.close()
                except Exception:
                    pass

        if background:
            thread = threading.Thread(target=_run_client, daemon=True, name="LarkWebSocketThread")
            thread.start()
            logger.info("🚀 Lark WebSocket Client đã khởi động ở chế độ Background Thread!")
            return thread
        else:
            logger.info("🚀 Lark WebSocket Client đang lắng nghe sự kiện trực tiếp từ Lark...")
            _run_client()

    # -------------------------------------------------------------------------
    # KIỂM TRA LOẠI CHAT (GROUP / DM 1-1)
    # -------------------------------------------------------------------------

    def is_dm_chat(self, chat_id: str, chat_obj: Optional[Any] = None) -> bool:
        """
        Kiểm tra xem cuộc trò chuyện có phải là DM 1-1 (Direct Message) giữa 2 người hay không.
        """
        if chat_obj:
            mode = getattr(chat_obj, "chat_mode", "")
            if mode == "p2p" or getattr(chat_obj, "p2p_target_id", None):
                return True

        opt = self._get_request_option(as_user=True)
        try:
            req = lark.api.im.v1.GetChatRequest.builder().chat_id(chat_id).build()
            resp = self.client.im.v1.chat.get(req, option=opt)
            if resp.success():
                c = resp.data
                mode = getattr(c, "chat_mode", "")
                count = getattr(c, "user_count", None)
                name = getattr(c, "name", "")
                if mode == "p2p":
                    return True
                # Một số DM hai người có tên chat dạng "Tên người gửi, Tên người nhận"
                if count is not None and int(count) == 2 and "," in name:
                    return True
        except Exception:
            pass
        return False

    # -------------------------------------------------------------------------
    # DM POLLING - QUÉT HỘP THƯ 1-1
    # -------------------------------------------------------------------------

    def poll_dm_messages_once(
        self,
        chat_cache: Dict[str, bool],
        last_seen: Dict[str, str],
    ) -> List[LarkMessage]:
        """
        Thực hiện một chu kỳ quét các cuộc trò chuyện DM 1-1 để tìm tin nhắn mới.
        """
        new_messages: List[LarkMessage] = []
        if not self.user_access_token:
            return new_messages

        opt = self._get_request_option(as_user=True)
        try:
            req = (
                lark.api.im.v1.ListChatRequest.builder()
                .sort_type("ByActiveTimeDesc")
                .page_size(10)
                .build()
            )
            resp = self.client.im.v1.chat.list(req, option=opt)
            if not resp.success():
                raw_status = getattr(getattr(resp, "raw", None), "status_code", 0)
                err_msg = getattr(resp, "msg", "") or ""
                if raw_status == 429 or "frequency" in err_msg.lower() or "too many" in err_msg.lower():
                    logger.warning("⚠️ [LARK RATE LIMIT] Đang chạm ngưỡng tần suất gọi API của Lark (HTTP 429). Tạm nghỉ 10s...")
                    time.sleep(10.0)
                return new_messages
            if not resp.data or not resp.data.items:
                return new_messages

            my_open_id = self._current_user_profile.get("open_id", "") if self._current_user_profile else ""

            for chat in resp.data.items:
                cid = chat.chat_id
                if cid not in chat_cache:
                    chat_cache[cid] = self.is_dm_chat(cid, chat)

                if not chat_cache[cid]:
                    # Là group nhiều người -> Giao cho WebSocket xử lý
                    continue

                # Là DM 1-1 -> Lấy tin nhắn mới nhất
                msg_req = (
                    lark.api.im.v1.ListMessageRequest.builder()
                    .container_id_type("chat")
                    .container_id(cid)
                    .sort_type("ByCreateTimeDesc")
                    .page_size(1)
                    .build()
                )
                msg_resp = self.client.im.v1.message.list(msg_req, option=opt)
                if not msg_resp.success() or not msg_resp.data.items:
                    continue

                latest_item = msg_resp.data.items[0]
                mid = getattr(latest_item, "message_id", "")
                if not mid:
                    continue

                # Đã ghi nhận ở vòng trước của chat này -> Bỏ qua
                if last_seen.get(cid) == mid:
                    continue

                last_seen[cid] = mid

                # Đã được WebSocket hoặc vòng trước xử lý -> Bỏ qua
                if self._is_duplicate_message(mid):
                    continue

                # Bỏ qua tin nhắn do chính bạn gửi hoặc tin nhắn system
                sender = getattr(latest_item, "sender", None)
                sender_id = getattr(sender, "id", "") if sender else ""
                msg_type = getattr(latest_item, "msg_type", "")
                if (my_open_id and sender_id == my_open_id) or msg_type != "text":
                    continue

                parsed = self.parse_list_message_item(latest_item, chat_type="p2p")
                if parsed:
                    new_messages.append(parsed)

        except Exception as e:
            err_str = str(e)
            is_transient_net = any(k in err_str.lower() for k in ["ssl", "tls", "connection", "retry", "timeout", "reset", "broken pipe"])
            if is_transient_net:
                logger.warning(f"⚠️ Mạng tạm thời chập chờn khi poll DM ({type(e).__name__}): {err_str[:120]}. Sẽ tự thử lại ở chu kỳ tiếp...")
            else:
                logger.error(f"Lỗi khi poll DM messages: {e}", exc_info=True)

        return new_messages

    # -------------------------------------------------------------------------
    # HYBRID RUNNER (WEBSOCKET + DM POLLING)
    # -------------------------------------------------------------------------

    def start_hybrid_runner(self, dm_poll_interval: float = 4.0):
        """
        Khởi động chế độ HYBRID:
          - Làn 1: WebSocket Client (sự kiện thời gian thực) cho Group chats.
          - Làn 2: Polling Worker (quét ngầm mỗi dm_poll_interval giây) cho DM 1-1.
          - Shared Deduplication Cache: đảm bảo không bao giờ bị trùng tin.
          - Mọi tin nhắn phản hồi đều mang danh nghĩa User (as_user=True).
        """
        self.get_current_user()

        # Khởi động WebSocket ở background thread cho Group chats
        self.start_ws_client(background=True)

        logger.info(f"🔄 Đang kích hoạt Poller cho DM 1-1 (chu kỳ quét: {dm_poll_interval}s)...")
        chat_cache: Dict[str, bool] = {}
        last_seen: Dict[str, str] = {}

        # Warm-up: Ghi nhận các tin nhắn hiện tại để không rep nhầm tin lịch sử
        try:
            logger.info("⏳ Đang nạp trạng thái ban đầu cho các cuộc trò chuyện DM...")
            opt = self._get_request_option(as_user=True)
            req = (
                lark.api.im.v1.ListChatRequest.builder()
                .sort_type("ByActiveTimeDesc")
                .page_size(10)
                .build()
            )
            init_resp = self.client.im.v1.chat.list(req, option=opt)
            if init_resp.success() and init_resp.data.items:
                for c in init_resp.data.items:
                    cid = c.chat_id
                    chat_cache[cid] = self.is_dm_chat(cid, c)
                    if chat_cache[cid]:
                        m_req = (
                            lark.api.im.v1.ListMessageRequest.builder()
                            .container_id_type("chat")
                            .container_id(cid)
                            .sort_type("ByCreateTimeDesc")
                            .page_size(1)
                            .build()
                        )
                        m_resp = self.client.im.v1.message.list(m_req, option=opt)
                        if m_resp.success() and m_resp.data.items:
                            top_m = m_resp.data.items[0]
                            last_seen[cid] = top_m.message_id
                            self._is_duplicate_message(top_m.message_id)
            logger.info("✔ Khởi tạo xong! Hệ thống Hybrid (Group = WebSocket, DM = Polling) sẵn sàng nhận tin!")
        except Exception as e:
            logger.warning(f"Lỗi khi warm-up DM poller: {e}")

        # Vòng lặp Polling DM trên main thread
        try:
            while True:
                time.sleep(dm_poll_interval)
                new_dms = self.poll_dm_messages_once(chat_cache, last_seen)
                for dm_msg in new_dms:
                    logger.info(
                        f"📨 [DM POLLING] Bắt được tin nhắn 1-1 mới từ {dm_msg.sender_id}: '{dm_msg.text}'"
                    )
                    self._dispatch_to_handlers(dm_msg)
        except KeyboardInterrupt:
            logger.info("Dừng hệ thống Hybrid Runner.")
