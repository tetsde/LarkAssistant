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
    DeleteMessageRequest,
    GetMessageRequest,
    ListMessageRequest,
    PatchMessageRequest,
    PatchMessageRequestBody,
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

    async def send_bot_dm_to_owner(self, text: str | Dict[str, Any], target_open_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Gửi tin nhắn riêng (DM 1-1) từ Bot tới tài khoản của chủ nhân.
        Tự động chuyển tiếp sang send_bot_card_to_owner nếu nội dung truyền vào là cấu trúc Thẻ tương tác.
        """
        if not text:
            return {"success": False, "error": "text không được rỗng"}

        # Tự động nhận diện nếu người gọi truyền vào card dictionary hoặc card JSON
        if isinstance(text, dict):
            return await self.send_bot_card_to_owner(text, target_open_id=target_open_id)
        if isinstance(text, str) and text.strip().startswith("{") and '"elements"' in text:
            return await self.send_bot_card_to_owner(text, target_open_id=target_open_id)

        owner_open_id = target_open_id or self.owner_open_id
        if not owner_open_id:
            logger.error("[LARK BOT DM] Không tìm thấy open_id của chủ nhân để gửi tin.")
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
                logger.error(f"[LARK BOT DM] Thất bại khi gửi tin tới chủ nhân ({owner_open_id}): code={response.code}, msg={response.msg}")
                return {"success": False, "code": response.code, "msg": response.msg}
            logger.info(f"[LARK BOT DM] Đã gửi tin nhắn tới chủ nhân ({owner_open_id}) thành công")
            return {"success": True, "data": response.data}
        except Exception as e:
            logger.error(f"[LARK BOT DM] Lỗi ngoại lệ khi gửi tin nhắn tới chủ nhân: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # Tương thích ngược tên hàm cũ
    send_to_owner_as_bot = send_bot_dm_to_owner

    # -------------------------------------------------------------------------
    # GỬI THẺ TIN NHẮN TƯƠNG TÁC (INTERACTIVE CARD) TỚI CHỦ NHÂN BẰNG BOT
    # -------------------------------------------------------------------------

    async def send_bot_card_to_owner(
        self,
        card_payload: Dict[str, Any] | str,
        target_open_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Gửi Thẻ tin nhắn tương tác (Lark Interactive Card) trực tiếp tới Chủ nhân qua tài khoản Bot.
        """
        if not card_payload:
            return {"success": False, "error": "card_payload không được rỗng"}

        owner_open_id = target_open_id or self.owner_open_id
        if not owner_open_id:
            logger.error("[LARK BOT DM CARD] Không tìm thấy open_id của chủ nhân để gửi thẻ.")
            return {"success": False, "error": "Chưa xác định được open_id của chủ nhân."}

        content_json = (
            card_payload if isinstance(card_payload, str)
            else json.dumps(card_payload, ensure_ascii=False)
        )

        request = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(owner_open_id)
                .msg_type("interactive")
                .content(content_json)
                .build()
            )
            .build()
        )

        try:
            response = await self.client.im.v1.message.acreate(request)
            if not response.success():
                logger.error(
                    f"[LARK BOT DM CARD] Thất bại khi gửi thẻ tới chủ nhân ({owner_open_id}): "
                    f"code={response.code}, msg={response.msg}"
                )
                return {"success": False, "code": response.code, "msg": response.msg}

            mid = getattr(response.data, "message_id", None) if response.data else None
            logger.info(f"[LARK BOT DM CARD] Đã gửi thẻ tương tác tới chủ nhân ({owner_open_id}) thành công, message_id={mid}")
            return {"success": True, "data": response.data, "message_id": mid}
        except Exception as e:
            logger.error(f"[LARK BOT DM CARD] Lỗi ngoại lệ khi gửi thẻ tới chủ nhân: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # CẬP NHẬT THẺ TIN NHẮN TƯƠNG TÁC TẠI CHỖ (IN-PLACE CARD UPDATE)
    # -------------------------------------------------------------------------

    async def update_card_message(
        self,
        message_id: str,
        card_payload: Dict[str, Any] | str,
        as_user: bool = False,
    ) -> Dict[str, Any]:
        """
        Cập nhật nội dung một thẻ tin nhắn đã gửi (In-place update).
        Dùng để cập nhật trạng thái sau khi Lãnh đạo bấm nút (ví dụ: đã duyệt, đã hủy),
        vô hiệu hóa các nút bấm nhằm chống bấm lặp lại.
        """
        if not message_id or not card_payload:
            return {"success": False, "error": "message_id và card_payload không được rỗng"}

        content_json = (
            card_payload if isinstance(card_payload, str)
            else json.dumps(card_payload, ensure_ascii=False)
        )

        request = (
            PatchMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                PatchMessageRequestBody.builder()
                .content(content_json)
                .build()
            )
            .build()
        )

        opt = None
        if as_user:
            try:
                opt = self._get_user_request_option()
            except Exception as e:
                logger.error(f"[LARK CARD UPDATE] Không lấy được quyền User: {e}")
                return {"success": False, "error": str(e)}

        try:
            response = await self.client.im.v1.message.apatch(request, option=opt)
            if not response.success():
                logger.error(
                    f"[LARK CARD UPDATE] Cập nhật thẻ {message_id} thất bại: "
                    f"code={response.code}, msg={response.msg}"
                )
                return {"success": False, "code": response.code, "msg": response.msg}

            logger.info(f"[LARK CARD UPDATE] Cập nhật thẻ {message_id} thành công")
            return {"success": True, "data": getattr(response, "data", None)}
        except Exception as e:
            logger.error(f"[LARK CARD UPDATE] Lỗi ngoại lệ khi cập nhật thẻ {message_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

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
        resp_data = getattr(response, "data", None)
        if resp_data and getattr(resp_data, "message_id", None):
            sent_mid = getattr(resp_data, "message_id")
            self._record_sent_message_id(sent_mid)

        logger.info(f"✔ Đã {action_desc} thành công")
        return {"success": True, "data": resp_data}

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
    # THU HỒI TIN NHẮN (RECALL / DELETE MESSAGE)
    # -------------------------------------------------------------------------

    async def arecall_message(
        self,
        message_id: str,
        as_user: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Thu hồi (Delete/Recall) tin nhắn trên Lark (async).
        Nếu as_user=True: thu hồi với User Access Token.
        Nếu as_user=False: thu hồi với Tenant/Bot Access Token.
        Nếu as_user=None: tự động thử với User Access Token (nếu có), nếu lỗi/không có thì thử với Tenant Token.
        """
        if not message_id:
            return {"success": False, "error": "message_id không được rỗng"}

        request = DeleteMessageRequest.builder().message_id(message_id).build()

        async def _do_delete(opt: Optional[lark.RequestOption]):
            return await self.client.im.v1.message.adelete(request, option=opt)

        if as_user is True:
            opt = self._get_request_option(as_user=True)
            try:
                response = await _do_delete(opt)
                return self._handle_im_response(response, f"thu hồi tin nhắn {message_id}")
            except Exception as e:
                logger.error(f"Lỗi khi thu hồi tin nhắn {message_id} as user: {e}", exc_info=True)
                return {"success": False, "error": str(e)}

        elif as_user is False:
            try:
                response = await _do_delete(None)
                return self._handle_im_response(response, f"thu hồi tin nhắn {message_id} as bot")
            except Exception as e:
                logger.error(f"Lỗi khi thu hồi tin nhắn {message_id} as bot: {e}", exc_info=True)
                return {"success": False, "error": str(e)}

        else:
            opt = None
            try:
                token_check = self.check_user_access_token()
                if token_check.is_valid:
                    opt = self._get_request_option(as_user=True)
            except Exception:
                opt = None

            try:
                response = await _do_delete(opt)
                if response.success():
                    return self._handle_im_response(response, f"thu hồi tin nhắn {message_id}")
                if opt is not None:
                    fallback_resp = await _do_delete(None)
                    if fallback_resp.success():
                        return self._handle_im_response(fallback_resp, f"thu hồi tin nhắn {message_id} as bot fallback")
                return self._handle_im_response(response, f"thu hồi tin nhắn {message_id}")
            except Exception as e:
                logger.error(f"Exception khi thu hồi tin nhắn {message_id}: {e}", exc_info=True)
                return {"success": False, "error": str(e)}

    def recall_message(
        self,
        message_id: str,
        as_user: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Thu hồi (Delete/Recall) tin nhắn trên Lark (sync)."""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(self.arecall_message(message_id, as_user=as_user))
        except RuntimeError:
            return asyncio.run(self.arecall_message(message_id, as_user=as_user))

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

        # 1. Parse JSON payload và xử lý URL Verification Challenge
        payload: Dict[str, Any] = {}
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

        # 2. Xử lý sự kiện Card Action Callback (khi người dùng bấm nút trên Thẻ tương tác)
        is_card_action = False
        if isinstance(payload, dict):
            if "action" in payload or payload.get("open_message_id"):
                is_card_action = True
            elif payload.get("header", {}).get("event_type") == "card.action.trigger":
                is_card_action = True

        if is_card_action:
            from services.lark.handlers.card_action_handler import handle_card_action, parse_card_action_payload
            open_id, message_id, action_val = parse_card_action_payload(payload)
            if action_val:
                ok, toast_msg, updated_card = await handle_card_action(open_id, message_id, action_val)
                resp_data: Dict[str, Any] = {}
                if toast_msg:
                    resp_data["toast"] = {
                        "type": "success" if ok else "warning",
                        "content": toast_msg,
                    }
                if updated_card:
                    resp_data["card"] = updated_card
                return Response(
                    content=json.dumps(resp_data, ensure_ascii=False),
                    media_type="application/json; charset=utf-8",
                    status_code=200,
                )

        # 3. Xây dựng RawRequest cho Lark SDK EventDispatcher
        raw_req = RawRequest()
        raw_req.uri = request.url.path
        raw_req.body = body_bytes
        raw_req.headers = dict(request.headers)

        # 4. Chuyển cho SDK Dispatcher xử lý
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

    async def handle_card_action_request(self, request: Request) -> Response:
        """Endpoint chuyên xử lý Card Action Callback từ Lark."""
        return await self.handle_fastapi_request(request)
