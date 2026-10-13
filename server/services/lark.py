"""
HiLark Lark Service
===================
Vị trí: server/services/lark.py

Mục đích:
    Quản lý giao tiếp toàn diện với Lark Open Platform (LarkSuite / Feishu):
      1. Khởi tạo Lark Client & Event Dispatcher với cấu hình từ .env
      2. Hỗ trợ ĐỌC và THAO TÁC trên chính DANH TÍNH CỦA USER (access_token_user)
         - Gửi tin nhắn danh nghĩa User (as_user=True)
         - Đọc tin nhắn / lịch sử chat danh nghĩa User
         - Tra cứu thông tin hồ sơ User (get_current_user)
      3. Nhận & bóc tách sự kiện tin nhắn (P2ImMessageReceiveV1) từ Lark Event
      4. Cơ chế đăng ký Message Handlers (hỗ trợ cả sync & async callbacks)
      5. Gửi & Reply tin nhắn văn bản, thẻ tương tác (Card) tới người dùng / nhóm
      6. Bộ tích hợp sẵn cho FastAPI Endpoint (/api/lark/events) kèm tự động giải quyết URL Challenge
      7. Chống xử lý trùng lặp tin nhắn (Message Deduplication Cache)
      8. Lark WebSocket Client cho Local Dev không cần Public IP/Domain

Sử dụng:
    from services.lark import lark_service, LarkMessage

    # Đăng ký hàm xử lý khi có tin nhắn tới:
    @lark_service.on_message
    async def handle_message(msg: LarkMessage):
        print(f"Nhận tin từ {msg.sender_id}: {msg.text}")
        # Reply dưới danh nghĩa chính User (Hoài Nam)
        await lark_service.areply_text(msg.message_id, f"Đã nhận: {msg.text}", as_user=True)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Set, Union

import lark_oapi as lark
import lark_oapi.ws as lark_ws
from fastapi import Request, Response
from lark_oapi.api.authen.v1 import GetUserInfoRequest
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    GetMessageRequest,
    ListMessageRequest,
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)
from lark_oapi.core.const import APPLICATION_JSON, UTF_8
from lark_oapi.core.model import RawRequest

from core.config import settings
from models.lark import LarkConfig, LarkMention, LarkMessage, LarkUserProfile

logger = logging.getLogger("hilark.lark")
logger.setLevel(logging.INFO)


# =============================================================================
# LARK SERVICE CLASS
# =============================================================================

class LarkService:
    """
    Service quản lý kết nối, nhận sự kiện (Event) và gửi/reply tin nhắn với Lark
    hỗ trợ cả danh tính Bot và danh tính User (User Access Token).
    """

    def __init__(
        self,
        config: Optional[LarkConfig] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        verification_token: Optional[str] = None,
        encrypt_key: Optional[str] = None,
        domain: Optional[str] = None,
        user_access_token: Optional[str] = None,
        user_open_id: Optional[str] = None,
    ):
        if config is not None:
            self.config = config
        else:
            self.config = LarkConfig(
                app_id=app_id or settings.LARK_APP_ID or "",
                app_secret=app_secret or settings.LARK_APP_SECRET or "",
                verification_token=verification_token or settings.LARK_VERIFICATION_TOKEN or "",
                encrypt_key=encrypt_key or settings.LARK_ENCRYPT_KEY or "",
                domain=domain or settings.LARK_DOMAIN or lark.LARK_DOMAIN,
                user_access_token=user_access_token or settings.LARK_USER_ACCESS_TOKEN or "",
                user_open_id=user_open_id or settings.LARK_USER_OPEN_ID or "",
            )

        self.app_id = self.config.app_id
        self.app_secret = self.config.app_secret
        self.verification_token = self.config.verification_token
        self.encrypt_key = self.config.encrypt_key
        self.domain = self.config.domain or lark.LARK_DOMAIN
        self.user_access_token = self.config.user_access_token

        # Khởi tạo Lark API Client (bật enable_set_token để cho phép dùng user_access_token)
        self.client: lark.Client = (
            lark.Client.builder()
            .app_id(self.app_id)
            .app_secret(self.app_secret)
            .domain(self.domain)
            .enable_set_token(True)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

        # Cache thông tin của User hiện tại (Tên, open_id đọc từ .env hoặc settings)
        self.known_user_open_id = (
            getattr(self.config, "user_open_id", "")
            or settings.LARK_USER_OPEN_ID
            or os.getenv("user_open_id", "")
        )
        self._current_user_profile: Optional[Dict[str, Any]] = None


        # Danh sách các message_id do chính hệ thống tạo ra hoặc gửi đi (chống vòng lặp)
        self._sent_message_ids: OrderedDict[str, float] = OrderedDict()

        # Danh sách các hàm callback lắng nghe tin nhắn
        self._message_handlers: List[Callable[[LarkMessage], Any]] = []

        # Cache chống duplicate message_id (Lark có cơ chế retry nếu chưa nhận 200 trong 3s)
        self._processed_msg_ids: OrderedDict[str, float] = OrderedDict()
        self._dedup_lock = asyncio.Lock() if hasattr(asyncio, "Lock") else None

        # Khởi tạo EventDispatcherHandler của Lark
        self.event_dispatcher = self._build_event_dispatcher()

    def _build_event_dispatcher(self) -> lark.EventDispatcherHandler:
        """Xây dựng bộ lắng nghe sự kiện Lark (Event Dispatcher)."""
        builder = lark.EventDispatcherHandler.builder(
            self.encrypt_key or "",
            self.verification_token or "",
        )
        builder.register_p2_im_message_receive_v1(self._internal_on_message_event)
        return builder.build()

    def _get_user_request_option(self) -> lark.RequestOption:
        """
        BẮT BUỘC tạo RequestOption mang User Access Token.
        Tuyệt đối không bao giờ trả về None (vì trả về None sẽ khiến Lark SDK tự lấy Bot App Token để gửi).
        """
        if not self.user_access_token:
            raise ValueError("Chưa cấu hình `access_token_user` trong .env! Hệ thống chỉ được phép gửi bằng danh tính người dùng.")
        return lark.RequestOption.builder().user_access_token(self.user_access_token).build()

    def _get_request_option(self, as_user: bool = True) -> Optional[lark.RequestOption]:
        """Tạo RequestOption mang User Token nếu as_user=True."""
        if self.user_access_token:
            return lark.RequestOption.builder().user_access_token(self.user_access_token).build()
        return None

    # -------------------------------------------------------------------------
    # 1. THAO TÁC DANH TÍNH USER (USER IDENTITY MANAGEMENT)
    # -------------------------------------------------------------------------

    def get_current_user(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Tra cứu thông tin hồ sơ của User được cấp quyền bởi `access_token_user`.
        """
        if self._current_user_profile and not force_refresh:
            return self._current_user_profile

        fallback_profile = {
            "name": os.getenv("user_name", "Tống Phước Hoài Nam"),
            "open_id": self.known_user_open_id,
            "union_id": "",
            "avatar_url": "",
            "email": "",
            "mobile": "",
            "tenant_key": "",
        }

        if not self.user_access_token:
            self._current_user_profile = fallback_profile
            return fallback_profile

        opt = self._get_request_option(as_user=True)
        try:
            req = GetUserInfoRequest.builder().build()
            resp = self.client.authen.v1.user_info.get(req, opt)
            if not resp.success():
                logger.warning(f"Lỗi lấy thông tin user từ token ({resp.msg}, code {resp.code}). Sử dụng profile mặc định.")
                self._current_user_profile = fallback_profile
                return fallback_profile

            data = resp.data
            profile = {
                "name": getattr(data, "name", "") or "User",
                "open_id": getattr(data, "open_id", "") or self.known_user_open_id,
                "union_id": getattr(data, "union_id", ""),
                "avatar_url": getattr(data, "avatar_url", ""),
                "email": getattr(data, "email", "") or getattr(data, "enterprise_email", ""),
                "mobile": getattr(data, "mobile", ""),
                "tenant_key": getattr(data, "tenant_key", ""),
            }
            self._current_user_profile = profile
            logger.info(f"👤 Đang hoạt động dưới danh tính User: {profile['name']} (open_id: {profile['open_id']})")
            return profile
        except Exception as e:
            logger.error(f"Exception khi lấy user info: {e}", exc_info=True)
            self._current_user_profile = fallback_profile
            return fallback_profile

    def check_user_access_token(self, force_ping: bool = False) -> Any:
        """
        Kiểm tra và ping trực tiếp User Access Token xem còn sống hay đã hết hạn (expire).
        Hỗ trợ cache để tránh spam network, force_ping=True để ping lại tức thì.
        """
        if not hasattr(self, "_last_token_check") or force_ping or not self._last_token_check:
            from utils.lark_token import ping_user_access_token
            self._last_token_check = ping_user_access_token(
                token=self.user_access_token,
                domain=self.domain,
            )
        return self._last_token_check

    def is_user_token_valid(self) -> bool:
        """Kiểm tra nhanh xem token còn hợp lệ không."""
        res = self.check_user_access_token()
        return bool(res and res.is_valid)

    def get_user_name(self, user_id: str) -> Optional[str]:
        """Lấy họ tên hiển thị của một người dùng theo open_id/user_id."""
        if not user_id:
            return None
        if not hasattr(self, "_user_name_cache"):
            self._user_name_cache = {}
        if user_id in self._user_name_cache:
            return self._user_name_cache[user_id]
        try:
            from lark_oapi.api.contact.v3 import GetUserRequest
            opt = self._get_request_option(as_user=True)
            req = GetUserRequest.builder().user_id(user_id).user_id_type("open_id").build()
            resp = self.client.contact.v3.user.get(req, opt)
            if resp.success() and resp.data and resp.data.user:
                name = resp.data.user.name
                if name:
                    self._user_name_cache[user_id] = name
                    return name
        except Exception:
            pass
        return None

    # -------------------------------------------------------------------------
    # 2. BÓC TÁCH TIN NHẮN (PARSER)
    # -------------------------------------------------------------------------

    def parse_event(self, event: P2ImMessageReceiveV1) -> Optional[LarkMessage]:
        """
        Chuyển đổi sự kiện P2ImMessageReceiveV1 từ Lark SDK thành đối tượng LarkMessage tinh gọn.
        """
        if not event or not event.event:
            return None

        event_data = event.event
        msg = event_data.message
        sender = event_data.sender

        if not msg:
            return None

        # 1. Định danh người gửi & Bot detection
        sender_id = ""
        sender_type = sender.sender_type if sender else "user"
        if sender and sender.sender_id:
            sender_id = (
                sender.sender_id.open_id
                or sender.sender_id.user_id
                or sender.sender_id.union_id
                or ""
            )

        is_bot = sender_type == "app" or sender_type == "bot"

        # Kiểm tra xem có phải chính User của token gửi không
        my_open_id = self.known_user_open_id
        if self._current_user_profile and self._current_user_profile.get("open_id"):
            my_open_id = self._current_user_profile.get("open_id")
        is_self = bool(my_open_id and sender_id == my_open_id)

        # 2. Bóc tách nội dung Text
        raw_content = msg.content or "{}"
        clean_text = ""
        try:
            content_dict = json.loads(raw_content)
            if isinstance(content_dict, dict):
                clean_text = content_dict.get("text", "")
            elif isinstance(content_dict, str):
                clean_text = content_dict
        except Exception:
            clean_text = str(raw_content)

        # 3. Làm sạch mention tag (ví dụ: @_user_1)
        mentions_list: List[Dict[str, Any]] = []
        if msg.mentions:
            for m in msg.mentions:
                m_key = getattr(m, "key", "")
                m_name = getattr(m, "name", "")
                m_id = ""
                if getattr(m, "id", None):
                    m_id = getattr(m.id, "open_id", "") or getattr(m.id, "user_id", "")
                mentions_list.append({"key": m_key, "name": m_name, "id": m_id})
                if m_key and m_key in clean_text:
                    clean_text = clean_text.replace(m_key, "").strip()

        clean_text = re.sub(r"\s+", " ", clean_text).strip()

        return LarkMessage(
            message_id=msg.message_id or "",
            chat_id=msg.chat_id or "",
            chat_type=msg.chat_type or "p2p",
            sender_id=sender_id,
            sender_type=sender_type,
            message_type=msg.message_type or "text",
            text=clean_text,
            raw_content=raw_content,
            create_time=int(msg.create_time or time.time() * 1000),
            is_bot=is_bot,
            is_self=is_self,
            root_id=msg.root_id,
            parent_id=msg.parent_id,
            mentions=mentions_list,
            raw_event=event,
        )

    # -------------------------------------------------------------------------
    # 3. XỬ LÝ SỰ KIỆN NỘI BỘ (INTERNAL DISPATCHER)
    # -------------------------------------------------------------------------

    def _is_duplicate_message(self, message_id: str) -> bool:
        """Kiểm tra và lưu cache chống xử lý lặp lại tin nhắn."""
        if not message_id:
            return False

        now = time.time()
        while self._processed_msg_ids and (now - next(iter(self._processed_msg_ids.values())) > 600):
            self._processed_msg_ids.popitem(last=False)

        if message_id in self._processed_msg_ids:
            return True

        self._processed_msg_ids[message_id] = now
        if len(self._processed_msg_ids) > 1000:
            self._processed_msg_ids.popitem(last=False)
        return False

    def _internal_on_message_event(self, data: P2ImMessageReceiveV1) -> None:
        """Hàm callback nội bộ được gọi bởi Lark Event Dispatcher."""
        lark_msg = self.parse_event(data)
        if not lark_msg:
            print("⚠️ [LARK DISPATCHER] Nhận được event nhưng không parse được cấu trúc message.")
            return

        print(f"⚡ [LARK DISPATCHER] Bắt được tin nhắn từ Lark: '{lark_msg.text}' (người gửi: {lark_msg.sender_id}, is_self={lark_msg.is_self}, is_bot={lark_msg.is_bot})")

        # 1. Bỏ qua tin nhắn từ Bot / App
        if lark_msg.is_bot:
            print(f"ℹ️ [LARK DISPATCHER] Bỏ qua vì tin nhắn phát từ Bot/App: {lark_msg.message_id}")
            return

        # 2. Xử lý tin nhắn do chính tài khoản của bạn gửi:
        # - Trong GROUP chat: Bỏ qua để chống loop tự trả lời chính mình (TRỪ KHI ĐÂY LÀ LỆNH ĐIỀU KHIỂN BOT).
        # - Trong DM 1-1 (chat_type == "p2p"): Đây là bạn đang chat/ra lệnh trực tiếp cho Bot (ví dụ: Gửi / Sửa / Bỏ).
        if lark_msg.is_self:
            if lark_msg.chat_type == "group":
                import re
                raw_txt = re.sub(r"@\S+", "", lark_msg.text or "").strip().lower()
                command_prefixes = (
                    "set-kb", "set_kb", "cài kb", "cai kb", "gán kb", "gan kb",
                    "get-kb", "get_kb", "xem kb", "kb info", "check kb",
                    "reset-kb", "reset_kb", "hủy kb", "huy kb", "xóa kb", "xoa kb",
                )
                if any(raw_txt.startswith(p) for p in command_prefixes):
                    print(f"👑 [LARK DISPATCHER] Nhận LỆNH ĐIỀU KHIỂN từ chủ nhân trong Group: '{lark_msg.text}' -> Cho phép xử lý!")
                else:
                    print(f"ℹ️ [LARK DISPATCHER] Bỏ qua tin nhắn do chính bạn gửi trong Group ({lark_msg.sender_id}): {lark_msg.message_id}")
                    return
            else:
                print(f"📩 [LARK DISPATCHER] Nhận tin nhắn trực tiếp từ chủ nhân trong DM 1-1: '{lark_msg.text}'")

        # 3. Bỏ qua tin nhắn nằm trong danh sách vừa gửi của hệ thống
        if lark_msg.message_id in self._sent_message_ids:
            print(f"ℹ️ [LARK DISPATCHER] Bỏ qua tin nhắn do hệ thống vừa gửi đi: {lark_msg.message_id}")
            return

        if self._is_duplicate_message(lark_msg.message_id):
            logger.info(f"Bỏ qua tin nhắn trùng lặp: {lark_msg.message_id}")
            return

        logger.info(
            f"📨 Nhận tin nhắn Lark [{lark_msg.chat_type}] từ {lark_msg.sender_id}: "
            f"'{lark_msg.text}' (msg_id: {lark_msg.message_id})"
        )

        self._dispatch_to_handlers(lark_msg)

    def _dispatch_to_handlers(self, lark_msg: LarkMessage) -> None:
        """Phân phối tin nhắn tới các handlers đã đăng ký."""
        for handler in self._message_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(handler(lark_msg))
                    except RuntimeError:
                        asyncio.run(handler(lark_msg))
                else:
                    handler(lark_msg)
            except Exception as e:
                logger.error(f"Lỗi khi thực thi message handler {handler.__name__}: {e}", exc_info=True)

    # -------------------------------------------------------------------------
    # 4. ĐĂNG KÝ MESSAGE HANDLERS
    # -------------------------------------------------------------------------

    def on_message(self, func: Callable[[LarkMessage], Any]) -> Callable[[LarkMessage], Any]:
        """x
        Decorator để đăng ký hàm xử lý tin nhắn tới.
        Hỗ trợ cả async def và def thông thường.
        """
        self.register_handler(func)
        return func

    def register_handler(self, handler: Callable[[LarkMessage], Any]) -> None:
        """Đăng ký hàm xử lý tin nhắn."""
        if handler not in self._message_handlers:
            self._message_handlers.append(handler)

    # -------------------------------------------------------------------------
    # 5. GỬI & REPLY TIN NHẮN (100% USER ACCESS TOKEN - GỠ BỎ HOÀN TOÀN BOT CHAT)
    # -------------------------------------------------------------------------

    async def send_bot_dm_to_owner(self, text: str) -> Dict[str, Any]:
        """
        ĐÂY LÀ ĐOẠN LOGIC DUY NHẤT TRONG HỆ THỐNG MÀ BOT GỬI TIN NHẮN DƯỚI DANH NGHĨA BOT:
        Bot chỉ có quyền gửi tin nhắn riêng (DM 1-1) tới CHÍNH ĐÍCH DANH CHỦ SỞ HỮU ACCESS_TOKEN.
        Đích đến được hardcode cố định tới open_id của chủ nhân, không thể gửi vào nhóm hay người khác.
        """
        if not text:
            return {"success": False, "error": "text không được rỗng"}

        owner_open_id = self.known_user_open_id
        if self._current_user_profile and self._current_user_profile.get("open_id"):
            owner_open_id = self._current_user_profile.get("open_id")

        content_json = json.dumps({"text": text}, ensure_ascii=False)
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(owner_open_id)
                .msg_type("text")
                .content(content_json)
                .build()
            )
            .build()
        )

        try:
            # Gửi bằng Bot App Token tới riêng 1-1 chủ nhân
            response = await self.client.im.v1.message.acreate(request)
            if not response.success():
                logger.error(f"❌ [LARK BOT DM] Thất bại khi gửi tin tới chủ nhân ({owner_open_id}): code={response.code}, msg={response.msg}")
                return {"success": False, "code": response.code, "msg": response.msg}
            logger.info(f"✔ [LARK BOT DM] Đã gửi tin nhắn tới chủ nhân ({owner_open_id}) thành công")
            return {"success": True, "data": response.data}
        except Exception as e:
            logger.error(f"❌ [LARK BOT DM] Exception khi gửi tin nhắn tới chủ nhân: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # Tương thích ngược tên hàm cũ
    send_to_owner_as_bot = send_bot_dm_to_owner

    # -------------------------------------------------------------------------
    # 5. GỬI & REPLY TIN NHẮN (100% USER ACCESS TOKEN - GỠ BỎ HOÀN TOÀN BOT CHAT)
    # -------------------------------------------------------------------------

    def _prepare_user_msg_payload(
        self,
        target_id: str,
        text: str,
        id_name: str = "id",
    ) -> tuple[Optional[lark.RequestOption], Optional[str], Optional[Dict[str, Any]]]:
        """Validate input và chuẩn bị request option cùng JSON text content."""
        if not target_id or not text:
            return None, None, {"success": False, "error": f"{id_name} và text không được rỗng"}

        # Kiểm tra nhanh trạng thái User Access Token trước khi gọi API Lark
        token_check = self.check_user_access_token()
        if not token_check.is_valid:
            warn_msg = f"User Access Token không hợp lệ hoặc đã hết hạn: {token_check.message}"
            logger.warning(f"⚠️ [SAFE FALLBACK] {warn_msg}")
            return None, None, {
                "success": False,
                "error": "token_expired",
                "code": token_check.code or 20005,
                "msg": warn_msg,
            }

        try:
            opt = self._get_user_request_option()
        except ValueError as e:
            logger.error(f"Từ chối thao tác gửi tin nhắn: {e}")
            return None, None, {"success": False, "error": str(e), "msg": "Không có User Access Token hợp lệ"}

        content_json = json.dumps({"text": text}, ensure_ascii=False)
        return opt, content_json, None

    def _handle_im_response(self, response: Any, action_desc: str) -> Dict[str, Any]:
        """Xử lý response từ Lark IM, ghi nhận cache message_id chống loop và log lỗi."""
        if not response.success():
            logger.error(f"Lỗi {action_desc}: code={response.code}, msg={response.msg}")
            return {
                "success": False,
                "code": response.code,
                "msg": f"Lỗi {action_desc} nhân danh User: {response.msg}",
            }

        # Ghi nhận message_id vừa gửi để tránh loop tự trả lời chính mình
        if response.data and getattr(response.data, "message_id", None):
            sent_mid = getattr(response.data, "message_id")
            self._sent_message_ids[sent_mid] = time.time()

        logger.info(f"✔ Đã {action_desc} thành công nhân danh User")
        return {"success": True, "data": response.data}

    async def areply_text(
        self,
        message_id: str,
        text: str,
        as_user: bool = True,
    ) -> Dict[str, Any]:
        """Reply tin nhắn async BẰNG DUY NHẤT DANH TÍNH NGƯỜI DÙNG (User Access Token)."""
        opt, content_json, err = self._prepare_user_msg_payload(message_id, text, "message_id")
        if err:
            return err

        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(ReplyMessageRequestBody.builder().msg_type("text").content(content_json).build())
            .build()
        )
        try:
            response = await self.client.im.v1.message.areply(request, option=opt)
            return self._handle_im_response(response, f"reply tin nhắn {message_id}")
        except Exception as e:
            logger.error(f"Exception khi reply tin nhắn {message_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def reply_text(
        self,
        message_id: str,
        text: str,
        as_user: bool = True,
    ) -> Dict[str, Any]:
        """Reply một tin nhắn văn bản đồng bộ BẰNG DUY NHẤT DANH TÍNH NGƯỜI DÙNG."""
        opt, content_json, err = self._prepare_user_msg_payload(message_id, text, "message_id")
        if err:
            return err

        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(ReplyMessageRequestBody.builder().msg_type("text").content(content_json).build())
            .build()
        )
        try:
            response = self.client.im.v1.message.reply(request, option=opt)
            return self._handle_im_response(response, f"reply sync tin nhắn {message_id}")
        except Exception as e:
            logger.error(f"Exception khi reply sync tin nhắn {message_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def asend_text(
        self,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id",  # "chat_id", "open_id", "user_id"
        as_user: bool = True,
    ) -> Dict[str, Any]:
        """Gửi tin nhắn mới async BẰNG DUY NHẤT DANH TÍNH NGƯỜI DÙNG (User Access Token)."""
        opt, content_json, err = self._prepare_user_msg_payload(receive_id, text, "receive_id")
        if err:
            return err

        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(CreateMessageRequestBody.builder().receive_id(receive_id).msg_type("text").content(content_json).build())
            .build()
        )
        try:
            response = await self.client.im.v1.message.acreate(request, option=opt)
            return self._handle_im_response(response, f"gửi tin nhắn tới {receive_id}")
        except Exception as e:
            logger.error(f"Exception khi gửi tin nhắn tới {receive_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def send_text(
        self,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id",
        as_user: bool = True,
    ) -> Dict[str, Any]:
        """Gửi tin nhắn mới đồng bộ BẰNG DUY NHẤT DANH TÍNH NGƯỜI DÙNG."""
        opt, content_json, err = self._prepare_user_msg_payload(receive_id, text, "receive_id")
        if err:
            return err

        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(CreateMessageRequestBody.builder().receive_id(receive_id).msg_type("text").content(content_json).build())
            .build()
        )
        try:
            response = self.client.im.v1.message.create(request, option=opt)
            return self._handle_im_response(response, f"gửi sync tin nhắn tới {receive_id}")
        except Exception as e:
            logger.error(f"Exception khi gửi sync tin nhắn tới {receive_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}


    # -------------------------------------------------------------------------
    # 6. ĐỌC TIN NHẮN TRÊN DANH NGHĨA USER (READ MESSAGES AS USER)
    # -------------------------------------------------------------------------

    def get_message(self, message_id: str, as_user: bool = True) -> Dict[str, Any]:
        """Đọc chi tiết 1 tin nhắn theo message_id."""
        if not message_id:
            return {"error": "message_id không được rỗng"}

        req = GetMessageRequest.builder().message_id(message_id).build()
        opt = self._get_request_option(as_user=as_user)
        try:
            resp = self.client.im.v1.message.get(req, option=opt)
            if not resp.success():
                return {"error": resp.msg, "code": resp.code}
            return {"success": True, "data": resp.data}
        except Exception as e:
            return {"error": str(e)}

    def list_messages(
        self,
        chat_id: str,
        page_size: int = 20,
        page_token: Optional[str] = None,
        as_user: bool = True,
    ) -> Dict[str, Any]:
        """
        Đọc danh sách tin nhắn trong một cuộc trò chuyện (Chat) trên danh nghĩa User.
        """
        if not chat_id:
            return {"error": "chat_id không được rỗng"}

        builder = (
            ListMessageRequest.builder()
            .container_id_type("chat")
            .container_id(chat_id)
            .page_size(page_size)
        )
        if page_token:
            builder.page_token(page_token)

        opt = self._get_request_option(as_user=as_user)
        try:
            resp = self.client.im.v1.message.list(builder.build(), option=opt)
            if not resp.success():
                return {"error": resp.msg, "code": resp.code}
            return {"success": True, "items": getattr(resp.data, "items", [])}
        except Exception as e:
            return {"error": str(e)}

    # -------------------------------------------------------------------------
    # 7. FASTAPI EVENT WEBHOOK HANDLER
    # -------------------------------------------------------------------------

    async def handle_fastapi_request(self, request: Request) -> Response:
        """
        Handler tiêu chuẩn dùng trực tiếp trong FastAPI route:
            @router.post("/events")
            async def lark_events(request: Request):
                return await lark_service.handle_fastapi_request(request)
        """
        body_bytes = await request.body()

        # 1. Xử lý tức thì URL Verification Challenge
        try:
            payload = json.loads(body_bytes.decode(UTF_8)) if body_bytes else {}
            if isinstance(payload, dict) and payload.get("type") == "url_verification":
                challenge = payload.get("challenge", "")
                logger.info(f"✔ Đã phản hồi Lark URL Verification Challenge: {challenge}")
                return Response(
                    content=json.dumps({"challenge": challenge}),
                    media_type="application/json",
                    status_code=200,
                )
        except Exception:
            pass

        # 2. Xây dựng RawRequest cho Lark SDK
        raw_req = RawRequest()
        raw_req.uri = request.url.path
        raw_req.body = body_bytes
        raw_req.headers = dict(request.headers)

        # 3. Chuyển cho SDK Dispatcher xử lý
        try:
            raw_resp = self.event_dispatcher.do(raw_req)
            return Response(
                content=raw_resp.content,
                status_code=raw_resp.status_code,
                media_type=raw_resp.content_type or "application/json",
            )
        except Exception as e:
            logger.warning(f"Fallback do_without_validation do: {e}")
            try:
                self.event_dispatcher._do_without_validation(body_bytes)
                return Response(
                    content=json.dumps({"msg": "success"}),
                    media_type="application/json",
                    status_code=200,
                )
            except Exception as inner_e:
                logger.error(f"Lỗi khi xử lý sự kiện Lark: {inner_e}", exc_info=True)
                return Response(
                    content=json.dumps({"msg": str(inner_e)}),
                    status_code=500,
                    media_type="application/json",
                )

    # -------------------------------------------------------------------------
    # 8. LARK WEBSOCKET LONG CONNECTION (LOCAL DEV KHÔNG CẦN DOMAIN/NGROK)
    # -------------------------------------------------------------------------

    def start_ws_client(self, background: bool = False):
        """
        Khởi động kết nối WebSocket (Persistent Connection) trực tiếp với Lark.
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
            # để tránh xung đột với event loop đang chạy của FastAPI / Uvicorn (RuntimeError: This event loop is already running)
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            import lark_oapi.ws.client as ws_module
            ws_module.loop = new_loop

            ws_client = lark_ws.Client(
                app_id=self.app_id,
                app_secret=self.app_secret,
                event_handler=self.event_dispatcher,
                domain=self.domain,
                log_level=lark.LogLevel.DEBUG,
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
    # 9. HYBRID RUNNER: WEBSOCKET CHO GROUP + POLLING CHO DM 1-1
    # -------------------------------------------------------------------------

    def parse_list_message_item(self, item: Any, chat_type: str = "p2p") -> Optional[LarkMessage]:
        """
        Chuyển đổi một đối tượng tin nhắn trả về từ API list_messages thành LarkMessage.
        """
        if not item:
            return None

        sender = getattr(item, "sender", None)
        sender_id = getattr(sender, "id", "") if sender else ""
        sender_type = getattr(sender, "sender_type", "user") if sender else "user"
        is_bot = sender_type in ("app", "bot")

        my_open_id = ""
        if self._current_user_profile:
            my_open_id = self._current_user_profile.get("open_id", "")
        is_self = bool(my_open_id and sender_id == my_open_id)

        body = getattr(item, "body", None)
        raw_content = getattr(body, "content", "{}") if body else "{}"
        clean_text = ""
        try:
            content_dict = json.loads(raw_content)
            if isinstance(content_dict, dict):
                clean_text = content_dict.get("text", "")
            elif isinstance(content_dict, str):
                clean_text = content_dict
        except Exception:
            clean_text = str(raw_content)

        clean_text = re.sub(r"\s+", " ", clean_text).strip()
        msg_type = getattr(item, "msg_type", "text")
        create_time = int(getattr(item, "create_time", 0) or time.time() * 1000)

        return LarkMessage(
            message_id=getattr(item, "message_id", ""),
            chat_id=getattr(item, "chat_id", ""),
            chat_type=chat_type,
            sender_id=sender_id,
            sender_type=sender_type,
            message_type=msg_type,
            text=clean_text,
            raw_content=raw_content,
            create_time=create_time,
            is_bot=is_bot,
            is_self=is_self,
            root_id=getattr(item, "root_id", None),
            parent_id=getattr(item, "parent_id", None),
        )

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
                # Nhóm 2 người tạo tự động giữa 2 người (tên dạng: Tống Phước Hoài Nam, Tống Phước A)
                if count is not None and int(count) == 2 and "," in name:
                    return True
        except Exception:
            pass
        return False

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

    def start_hybrid_runner(self, dm_poll_interval: float = 4.0):
        """
        Khởi động chế độ HYBRID:
          - Làn 1: WebSocket Client (Event thời gian thực) cho Group chats.
          - Làn 2: Polling Worker (Quét ngầm mỗi dm_poll_interval giây) cho DM 1-1.
          - Shared Message Deduplication Cache: Đảm bảo không bao giờ bị trùng tin.
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



# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

lark_service = LarkService()

__all__ = [
    "LarkConfig",
    "LarkService",
    "lark_service",
    "LarkMessage",
    "LarkMention",
    "LarkUserProfile",
]
