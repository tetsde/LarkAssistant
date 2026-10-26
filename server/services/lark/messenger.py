"""
HiLark Lark Messenger
=====================
Vị trí: server/services/lark_messenger.py

Mục đích:
    Tất cả các chức năng GỬI và ĐỌC tin nhắn trên Lark:
      1. send_bot_dm_to_owner    - Bot gửi DM tới chủ nhân (trường hợp duy nhất dùng Bot token)
      2. areply_text / reply_text - Reply tin nhắn (async/sync) nhân danh User
      3. asend_text / send_text   - Gửi tin nhắn mới (async/sync) nhân danh User
      4. get_message             - Đọc chi tiết 1 tin nhắn
      5. list_messages           - Đọc danh sách tin nhắn trong một chat
      6. handle_fastapi_request  - Webhook handler cho FastAPI route /api/lark/events

Import:
    from services.lark_messenger import LarkMessengerMixin
"""

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

import lark_oapi as lark
from fastapi import Request, Response
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    GetMessageRequest,
    ListMessageRequest,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)
from lark_oapi.core.const import UTF_8
from lark_oapi.core.model import RawRequest

logger = logging.getLogger("hilark.lark")


class LarkMessengerMixin:
    """
    Mixin chứa tất cả các hàm gửi và đọc tin nhắn Lark.
    Mặc định toàn bộ hoạt động dưới danh nghĩa User (User Access Token).
    Ngoại lệ duy nhất: send_bot_dm_to_owner dùng Bot App Token.
    """

    # -------------------------------------------------------------------------
    # GỬI TIN NHẮN DM TỚI CHỦ NHÂN BẰNG BOT (TRƯỜNG HỢP NGOẠI LỆ DUY NHẤT)
    # -------------------------------------------------------------------------

    async def send_bot_dm_to_owner(self, text: str, target_open_id: Optional[str] = None) -> Dict[str, Any]:
        """
        ĐÂY LÀ ĐOẠN LOGIC DUY NHẤT TRONG HỆ THỐNG MÀ BOT GỬI TIN NHẮN DƯỚI DANH NGHĨA BOT:
        Bot chỉ có quyền gửi tin nhắn riêng (DM 1-1) tới CHÍNH ĐÍCH DANH CHỦ SỞ HỮU ACCESS_TOKEN.
        """
        if not text:
            return {"success": False, "error": "text không được rỗng"}

        owner_open_id = target_open_id or self.owner_open_id
        if not owner_open_id:
            logger.error("❌ [LARK BOT DM] Không tìm thấy open_id của chủ nhân (từ token hoặc cấu hình) để gửi tin.")
            return {"success": False, "error": "Chưa xác định được open_id của chủ nhân."}

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
    # HÀM HELPER NỘI BỘ
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

    def _record_sent_message_id(self, message_id: str, ttl_seconds: float = 600.0, max_size: int = 1000) -> None:
        """Ghi nhận message_id vừa gửi và dọn dẹp cache quá hạn / vượt kích thước tối đa."""
        if not message_id:
            return
        if not hasattr(self, "_sent_message_ids") or self._sent_message_ids is None:
            self._sent_message_ids = OrderedDict()

        now = time.time()
        # Dọn dẹp tin nhắn quá hạn TTL (mặc định 10 phút)
        while self._sent_message_ids and (now - next(iter(self._sent_message_ids.values())) > ttl_seconds):
            self._sent_message_ids.popitem(last=False)

        self._sent_message_ids[message_id] = now
        # Giới hạn kích thước tối đa (FIFO)
        while len(self._sent_message_ids) > max_size:
            self._sent_message_ids.popitem(last=False)

    def _handle_im_response(self, response: Any, action_desc: str) -> Dict[str, Any]:
        """Xử lý response từ Lark IM, ghi nhận cache message_id chống loop và log lỗi."""
        if not response.success():
            logger.error(f"Lỗi {action_desc}: code={response.code}, msg={response.msg}")
            return {
                "success": False,
                "code": response.code,
                "msg": f"Lỗi {action_desc} nhân danh User: {response.msg}",
            }

        # Ghi nhận message_id vừa gửi để tránh loop tự trả lời chính mình (có TTL & Bounded Cache)
        if response.data and getattr(response.data, "message_id", None):
            sent_mid = getattr(response.data, "message_id")
            self._record_sent_message_id(sent_mid)

        logger.info(f"✔ Đã {action_desc} thành công nhân danh User")
        return {"success": True, "data": response.data}

    # -------------------------------------------------------------------------
    # REPLY TIN NHẮN (ASYNC & SYNC)
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # GỬI TIN NHẮN MỚI (ASYNC & SYNC)
    # -------------------------------------------------------------------------

    async def asend_text(
        self,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id",  # "chat_id", "open_id", "user_id"
        as_user: bool = True,
    ) -> Dict[str, Any]:
        """Gửi tin nhắn mới async (mặc định as_user=True bằng User Access Token, hoặc as_user=False bằng Bot)."""
        if as_user:
            opt, content_json, err = self._prepare_user_msg_payload(receive_id, text, "receive_id")
            if err:
                return err
        else:
            opt = None
            content_json = json.dumps({"text": text}, ensure_ascii=False)

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
        """Gửi tin nhắn mới đồng bộ (mặc định as_user=True bằng User Access Token, hoặc as_user=False bằng Bot)."""
        if as_user:
            opt, content_json, err = self._prepare_user_msg_payload(receive_id, text, "receive_id")
            if err:
                return err
        else:
            opt = None
            content_json = json.dumps({"text": text}, ensure_ascii=False)

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
    # ĐỌC TIN NHẮN TRÊN DANH NGHĨA USER (READ MESSAGES AS USER)
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
    # FASTAPI EVENT WEBHOOK HANDLER
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
