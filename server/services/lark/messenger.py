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
from core.config import settings
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


def _lark_raw_headers(request: Request) -> Dict[str, str]:
    """Normalize FastAPI's lowercase headers for the case-sensitive Lark SDK."""
    headers = dict(request.headers)
    canonical_names = (
        "X-Lark-Request-Timestamp",
        "X-Lark-Request-Nonce",
        "X-Lark-Signature",
        "X-Request-ID",
    )
    for name in canonical_names:
        value = headers.get(name) or headers.get(name.lower())
        if value is not None:
            headers[name] = value
    return headers


class LarkMessengerMixin:
    """
    Mixin chứa tất cả các hàm gửi và đọc tin nhắn Lark.
    Mặc định toàn bộ hoạt động dưới danh nghĩa User (User Access Token).
    Ngoại lệ duy nhất: send_bot_dm_to_owner dùng Bot App Token.
    """

    # -------------------------------------------------------------------------
    # GỬI TIN NHẮN DM TỚI CHỦ NHÂN BẰNG BOT (TRƯỜNG HỢP NGOẠI LỆ DUY NHẤT)
    # -------------------------------------------------------------------------

    async def send_bot_dm_to_owner(
        self,
        text: str | Dict[str, Any],
        target_open_id: Optional[str] = None,
        tenant_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Gửi tin nhắn riêng (DM 1-1) từ Bot tới tài khoản của chủ nhân.
        Tự động chuyển tiếp sang send_bot_card_to_owner nếu nội dung truyền vào là cấu trúc Thẻ tương tác.
        Hỗ trợ tenant_key cho ISV Multi-Tenant.
        """
        if not text:
            return {"success": False, "error": "text không được rỗng"}

        # Tự động nhận diện nếu người gọi truyền vào card dictionary hoặc card JSON
        if isinstance(text, dict):
            return await self.send_bot_card_to_owner(text, target_open_id=target_open_id, tenant_key=tenant_key)
        if isinstance(text, str) and text.strip().startswith("{") and any(k in text for k in ('"elements"', '"body"', '"schema"')):
            return await self.send_bot_card_to_owner(text, target_open_id=target_open_id, tenant_key=tenant_key)

        owner_open_id = target_open_id or self.owner_open_id
        if not owner_open_id:
            logger.error("[LARK_DM] owner_missing")
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
            # Gửi bằng Bot App Token tới riêng 1-1 chủ nhân (kèm RequestOption nếu có tenant_key)
            opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
            response = await self.client.im.v1.message.acreate(request, option=opt)
            if not response.success():
                logger.error("[LARK_DM] send_failed owner=%s code=%s msg=%s", owner_open_id, response.code, response.msg)
                return {"success": False, "code": response.code, "msg": response.msg}
            if response.data and getattr(response.data, "message_id", None):
                self._record_sent_message_id(getattr(response.data, "message_id"))
            logger.info("[LARK_DM] sent owner=%s", owner_open_id)
            return {"success": True, "data": response.data}
        except Exception as e:
            logger.error("[LARK_DM] send_error owner=%s error=%s", owner_open_id, e, exc_info=True)
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
        tenant_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Gửi Thẻ tin nhắn tương tác (Lark Interactive Card) trực tiếp tới Chủ nhân qua tài khoản Bot.
        Hỗ trợ tenant_key cho ISV Multi-Tenant.
        """
        if not card_payload:
            return {"success": False, "error": "card_payload không được rỗng"}

        owner_open_id = target_open_id or self.owner_open_id
        if not owner_open_id:
            logger.error("[LARK_DM_CARD] owner_missing")
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
            opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
            response = await self.client.im.v1.message.acreate(request, option=opt)
            if not response.success():
                logger.error(
                    "[LARK_DM_CARD] send_failed owner=%s code=%s msg=%s",
                    owner_open_id,
                    response.code,
                    response.msg,
                )
                if response.code == 230013:
                    logger.warning(
                        "[LARK_DM_CARD] bot_unavailable owner=%s code=230013 hint=check_app_availability",
                        owner_open_id,
                    )
                return {"success": False, "code": response.code, "msg": response.msg}

            mid = getattr(response.data, "message_id", None) if response.data else None
            if mid:
                self._record_sent_message_id(mid)
            logger.info("[LARK_DM_CARD] sent owner=%s msg=%s", owner_open_id, mid)
            return {"success": True, "data": response.data, "message_id": mid}
        except Exception as e:
            logger.error("[LARK_DM_CARD] send_error owner=%s error=%s", owner_open_id, e, exc_info=True)
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # CẬP NHẬT THẺ TIN NHẮN TƯƠNG TÁC TẠI CHỖ (IN-PLACE CARD UPDATE)
    # -------------------------------------------------------------------------

    async def update_card_message(
        self,
        message_id: str,
        card_payload: Dict[str, Any] | str,
        as_user: bool = False,
        tenant_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Cập nhật nội dung một thẻ tin nhắn đã gửi (In-place update).
        Dùng để cập nhật trạng thái sau khi Lãnh đạo bấm nút (ví dụ: đã duyệt, đã hủy),
        vô hiệu hóa các nút bấm nhằm chống bấm lặp lại. Hỗ trợ tenant_key cho ISV Multi-Tenant.
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

        opt = self._get_request_option(as_user=as_user, tenant_key=tenant_key)

        try:
            response = await self.client.im.v1.message.apatch(request, option=opt)
            if not response.success():
                logger.error("[LARK_CARD] update_failed msg=%s code=%s msg_text=%s", message_id, response.code, response.msg)
                return {"success": False, "code": response.code, "msg": response.msg}

            logger.info("[LARK_CARD] updated msg=%s", message_id)
            return {"success": True, "data": getattr(response, "data", None)}
        except Exception as e:
            logger.error("[LARK_CARD] update_error msg=%s error=%s", message_id, e, exc_info=True)
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
            logger.warning("[LARK_IM] user_token_invalid reason=%s", token_check.message)
            return None, None, {
                "success": False,
                "error": "token_expired",
                "code": token_check.code or 20005,
                "msg": warn_msg,
            }

        try:
            opt = self._get_user_request_option()
        except ValueError as e:
            logger.error("[LARK_IM] user_token_option_failed error=%s", e)
            return None, None, {"success": False, "error": str(e), "msg": "Không có User Access Token hợp lệ"}

        content_json = json.dumps({"text": text}, ensure_ascii=False)
        return opt, content_json, None

    def _resolve_msg_tenant(self, tenant_key: Optional[str] = None) -> Optional[str]:
        """
        Xác định tenant cho thao tác gửi tin: tham số -> ContextVar của request ->
        danh tính của instance.

        Không còn đọc `getattr(self, "tenant_key")` trước ContextVar: singleton
        `lark_service` mang tenant của App đầu tiên/.env, nên nếu thuộc tính instance
        thắng thì tin nhắn của tenant B được gửi bằng danh tính tenant A.
        """
        from database.db import get_current_tenant_key

        return tenant_key or get_current_tenant_key() or getattr(self, "tenant_key", None)

    async def _prepare_user_msg_payload_async(
        self,
        target_id: str,
        text: str,
        id_name: str = "id",
        tenant_key: Optional[str] = None,
    ) -> tuple[Optional[lark.RequestOption], Optional[str], Optional[Dict[str, Any]]]:
        """Validate input và chuẩn bị request option với AUTO-REFRESH token."""
        if not target_id or not text:
            return None, None, {"success": False, "error": f"{id_name} và text không được rỗng"}

        # ✅ TỰ ĐỘNG REFRESH TOKEN NẾU HẾT HẠN (WS7: qua TenantTokenManager)
        try:
            from services.auth.tenant_token_manager import tenant_token_manager
            eff_tenant = self._resolve_msg_tenant(tenant_key)
            
            if not eff_tenant:
                logger.warning("[LARK_IM] missing_tenant_key action=prepare_user_msg")
                return None, None, {
                    "success": False,
                    "error": "missing_tenant_key",
                    "msg": "Thiếu tenant_key để xác thực token",
                }
            
            valid_token = await tenant_token_manager.get_token(
                tenant_key=eff_tenant,
                token_type="user"
            )
            
            if not valid_token:
                logger.warning("[LARK_IM] user_token_invalid tenant=%s", eff_tenant)
                return None, None, {
                    "success": False,
                    "error": "token_expired",
                    "msg": "User Access Token không hợp lệ hoặc đã hết hạn",
                }
            logger.debug("[LARK_IM] user_token_ready tenant=%s", eff_tenant)
        except Exception as e:
            logger.error("[LARK_IM] user_token_error tenant=%s error=%s", eff_tenant or "-", e)
            return None, None, {"success": False, "error": str(e)}

        # Cập nhật RAM instance và trực tiếp tạo RequestOption từ valid_token
        self.user_access_token = valid_token
        opt_builder = lark.RequestOption.builder().user_access_token(valid_token)
        eff_tenant = self._resolve_msg_tenant(tenant_key)
        if eff_tenant:
            opt_builder.tenant_key(eff_tenant)
        opt = opt_builder.build()

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

        # Đồng bộ vào bộ đệm dùng chung toàn server để Dispatcher của mọi runtime đều nhận diện được
        try:
            from services.lark.dispatcher import record_sent_message_id_global
            record_sent_message_id_global(message_id, ttl_seconds=ttl_seconds, max_size=max_size * 2)
        except Exception:
            pass

    def _handle_im_response(self, response: Any, action_desc: str) -> Dict[str, Any]:
        """Xử lý response từ Lark IM, ghi nhận cache message_id chống loop và log lỗi."""
        if not response.success():
            logger.error("[LARK_IM] request_failed action=%s code=%s msg=%s", action_desc, response.code, response.msg)
            return {
                "success": False,
                "code": response.code,
                "msg": f"Lỗi {action_desc} nhân danh User: {response.msg}",
            }

        # Ghi nhận message_id vừa gửi để tránh loop tự trả lời chính mình (có TTL & Bounded Cache)
        resp_data = getattr(response, "data", None)
        sent_mid = getattr(resp_data, "message_id", None) if resp_data else None
        if sent_mid:
            self._record_sent_message_id(sent_mid)

        logger.info("[LARK_IM] request_ok action=%s sent_msg=%s", action_desc, sent_mid or "-")
        return {"success": True, "data": resp_data}

    # -------------------------------------------------------------------------
    # REPLY TIN NHẮN (ASYNC & SYNC)
    # -------------------------------------------------------------------------

    async def areply_text(
        self,
        message_id: str,
        text: str,
        as_user: bool = True,
        tenant_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reply tin nhắn async (mặc định as_user=True bằng User Access Token, hoặc as_user=False bằng Bot kèm tenant_key)."""
        if as_user:
            # ✅ GỌI ASYNC VERSION VỚI AUTO-REFRESH
            opt, content_json, err = await self._prepare_user_msg_payload_async(
                message_id, text, "message_id", tenant_key=tenant_key
            )
            if err:
                logger.info("[LARK_IM] reply_fallback_bot msg=%s reason=%s", message_id, err.get("error") or err.get("msg"))
                opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
                content_json = json.dumps({"text": text}, ensure_ascii=False)
        else:
            opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
            content_json = json.dumps({"text": text}, ensure_ascii=False)

        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(ReplyMessageRequestBody.builder().msg_type("text").content(content_json).build())
            .build()
        )
        try:
            response = await self.client.im.v1.message.areply(request, option=opt)
            # ✅ HANDLE BOT NOT IN CHAT ERROR
            if not response.success():
                if response.code == 230002:  # Bot/User can NOT be out of the chat
                    logger.warning("[LARK_IM] reply_skipped msg=%s code=230002 reason=bot_not_in_chat", message_id)
                    return {"success": False, "code": 230002, "skipped": True, "msg": "Bot not in chat"}
            return self._handle_im_response(response, f"reply tin nhắn {message_id}")
        except Exception as e:
            logger.error("[LARK_IM] reply_error msg=%s error=%s", message_id, e, exc_info=True)
            return {"success": False, "error": str(e)}

    def reply_text(
        self,
        message_id: str,
        text: str,
        as_user: bool = True,
        tenant_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reply một tin nhắn văn bản đồng bộ (hỗ trợ as_user=False bằng Bot kèm tenant_key)."""
        if as_user:
            opt, content_json, err = self._prepare_user_msg_payload(message_id, text, "message_id")
            if err:
                logger.info("[LARK_IM] reply_sync_fallback_bot msg=%s reason=%s", message_id, err.get("error") or err.get("msg"))
                opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
                content_json = json.dumps({"text": text}, ensure_ascii=False)
        else:
            opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
            content_json = json.dumps({"text": text}, ensure_ascii=False)

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
            logger.error("[LARK_IM] reply_sync_error msg=%s error=%s", message_id, e, exc_info=True)
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
        tenant_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Gửi tin nhắn mới async (mặc định as_user=True bằng User Access Token, hoặc as_user=False bằng Bot kèm tenant_key)."""
        if as_user:
            # ✅ GỌI ASYNC VERSION VỚI AUTO-REFRESH
            opt, content_json, err = await self._prepare_user_msg_payload_async(
                receive_id, text, "receive_id", tenant_key=tenant_key
            )
            if err:
                return err
        else:
            opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
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
            logger.error("[LARK_IM] send_error target=%s error=%s", receive_id, e, exc_info=True)
            return {"success": False, "error": str(e)}

    def send_text(
        self,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id",
        as_user: bool = True,
        tenant_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Gửi tin nhắn mới đồng bộ (mặc định as_user=True bằng User Access Token, hoặc as_user=False bằng Bot kèm tenant_key)."""
        if as_user:
            opt, content_json, err = self._prepare_user_msg_payload(receive_id, text, "receive_id")
            if err:
                return err
        else:
            opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
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
            logger.error("[LARK_IM] send_sync_error target=%s error=%s", receive_id, e, exc_info=True)
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # THU HỒI TIN NHẮN (RECALL / DELETE MESSAGE)
    # -------------------------------------------------------------------------

    async def arecall_message(
        self,
        message_id: str,
        as_user: Optional[bool] = None,
        tenant_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Thu hồi (Delete/Recall) tin nhắn trên Lark (async).
        Hỗ trợ tự động làm mới User Access Token và hỗ trợ đa tenant.
        Nếu as_user=True: thu hồi với User Access Token.
        Nếu as_user=False: thu hồi với Tenant/Bot Access Token.
        Nếu as_user=None: tự động thử với User Access Token (nếu có), nếu lỗi/không có thì thử với Tenant Token.
        """
        if not message_id:
            return {"success": False, "error": "message_id không được rỗng"}

        eff_tenant = self._resolve_msg_tenant(tenant_key)
        request = DeleteMessageRequest.builder().message_id(message_id).build()

        async def _do_delete(opt: Optional[lark.RequestOption]):
            return await self.client.im.v1.message.adelete(request, option=opt)

        async def _get_fresh_user_opt() -> Optional[lark.RequestOption]:
            try:
                from services.auth.tenant_token_manager import tenant_token_manager
                
                if not eff_tenant:
                    return None
                
                valid_token = await tenant_token_manager.get_token(
                    tenant_key=eff_tenant,
                    token_type="user"
                )
                
                if valid_token:
                    builder = lark.RequestOption.builder().user_access_token(valid_token)
                    if eff_tenant:
                        builder.tenant_key(eff_tenant)
                    return builder.build()
            except Exception as e:
                logger.debug("[LARK_IM] recall_user_token_failed tenant=%s error=%s", eff_tenant or "-", e)
            if self.user_access_token:
                return self._get_request_option(as_user=True, tenant_key=eff_tenant)
            return None

        bot_opt = self._get_request_option(as_user=False, tenant_key=eff_tenant)

        if as_user is True:
            opt = await _get_fresh_user_opt()
            try:
                response = await _do_delete(opt)
                return self._handle_im_response(response, f"thu hồi tin nhắn {message_id}")
            except Exception as e:
                logger.error("[LARK_IM] recall_error mode=user msg=%s error=%s", message_id, e, exc_info=True)
                return {"success": False, "error": str(e)}

        elif as_user is False:
            try:
                response = await _do_delete(bot_opt)
                return self._handle_im_response(response, f"thu hồi tin nhắn {message_id} as bot")
            except Exception as e:
                logger.error("[LARK_IM] recall_error mode=bot msg=%s error=%s", message_id, e, exc_info=True)
                return {"success": False, "error": str(e)}

        else:
            # Ưu tiên thử User token trước (do tin nhắn gửi dạng as_user)
            user_opt = await _get_fresh_user_opt()
            if user_opt:
                try:
                    response = await _do_delete(user_opt)
                    if response.success():
                        return self._handle_im_response(response, f"thu hồi tin nhắn {message_id} as user")
                    logger.debug("[LARK_IM] recall_fallback_bot msg=%s code=%s", message_id, response.code)
                except Exception as ex:
                    logger.debug("[LARK_IM] recall_user_failed msg=%s error=%s", message_id, ex)

            # Thử bằng Bot token
            try:
                response = await _do_delete(bot_opt)
                return self._handle_im_response(response, f"thu hồi tin nhắn {message_id} as bot")
            except Exception as e:
                logger.error("[LARK_IM] recall_error msg=%s error=%s", message_id, e, exc_info=True)
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
                logger.info("[WEBHOOK] url_verification challenge=%s", challenge)
                return Response(
                    content=json.dumps({"challenge": challenge}),
                    media_type="application/json",
                    status_code=200,
                )
        except Exception:
            pass

        # Multi-Custom-App ingress: resolve and validate the App-specific
        # verification token before handing the payload to the common parser.
        # The legacy singleton dispatcher remains the fallback for the
        # single-tenant .env deployment.
        app_specific_validated = False
        app_record = None
        app_header = payload.get("header", {}) if isinstance(payload, dict) else {}
        raw_query_app = None
        if hasattr(request, "query_params") and hasattr(request.query_params, "get"):
            val = request.query_params.get("app_id")
            if isinstance(val, str) and val.strip():
                raw_query_app = val.strip()

        raw_header_app = (app_header.get("app_id", "") if isinstance(app_header, dict) else "")
        if not isinstance(raw_header_app, str) or not raw_header_app.strip():
            raw_header_app = ""
        else:
            raw_header_app = raw_header_app.strip()

        inbound_app_id = raw_query_app or raw_header_app

        # Xử lý sự kiện mã hóa (Encrypted Event / Challenge)
        if isinstance(payload, dict) and payload.get("encrypt"):
            try:
                from services.lark_app_service import lark_app_service
                from services.lark.runtime import (
                    get_or_create_lark_service,
                    reset_current_lark_service,
                    set_current_lark_service,
                )

                encrypted_raw_req = RawRequest()
                encrypted_raw_req.uri = request.url.path
                encrypted_raw_req.body = body_bytes
                encrypted_raw_req.headers = _lark_raw_headers(request)

                # 1. Nếu Request URL có chỉ định đích danh ?app_id=cli_xxx:
                # Dùng chính xác bộ key của App đó giải mã trực tiếp, không đoán mò!
                if inbound_app_id:
                    target_app = await lark_app_service.get_by_app_id(inbound_app_id)
                    if target_app and target_app.get("encrypt_key"):
                        target_service = await get_or_create_lark_service(target_app)
                        ctx_token = set_current_lark_service(target_service)
                        try:
                            target_resp = target_service.event_dispatcher.do(encrypted_raw_req)
                            return Response(
                                content=target_resp.content,
                                status_code=target_resp.status_code,
                                media_type=getattr(target_resp, "content_type", None) or "application/json",
                            )
                        finally:
                            reset_current_lark_service(ctx_token)

                # 2. Nếu Request URL không có ?app_id: Ưu tiên App vừa cấu hình/cập nhật gần nhất
                registrations = await lark_app_service.list_registrations()
                registrations.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
                for candidate in registrations:
                    if not candidate.get("encrypt_key"):
                        continue
                    candidate_service = await get_or_create_lark_service(candidate)
                    candidate_context_token = set_current_lark_service(candidate_service)
                    try:
                        candidate_response = candidate_service.event_dispatcher.do(encrypted_raw_req)
                        if candidate_response.status_code == 200:
                            return Response(
                                content=candidate_response.content,
                                status_code=200,
                                media_type=getattr(candidate_response, "content_type", None) or "application/json",
                            )
                        logger.debug(
                            "[WEBHOOK] candidate_app_failed app_id=%s status=%s body=%s",
                            candidate.get("app_id"),
                            candidate_response.status_code,
                            candidate_response.content,
                        )
                    except Exception as candidate_error:
                        logger.debug(
                            "[WEBHOOK] candidate_decrypt_failed app_id=%s error=%s",
                            candidate.get("app_id"),
                            candidate_error,
                        )
                    finally:
                        reset_current_lark_service(candidate_context_token)

                logger.error("[WEBHOOK] decrypt_failed reason=no_matching_app_encrypt_key")
                return Response(
                    content=json.dumps({"code": 403, "msg": "no matching Custom App encrypt_key"}),
                    media_type="application/json",
                    status_code=403,
                )
            except Exception as encrypted_err:
                logger.error("[WEBHOOK] encrypted_dispatch_failed error=%s", encrypted_err, exc_info=True)
                return Response(
                    content=json.dumps({"code": 500, "msg": "custom app encrypted event dispatch failed"}),
                    media_type="application/json",
                    status_code=500,
                )

        if inbound_app_id:
            try:
                from services.lark_app_service import lark_app_service
                app_record = await lark_app_service.get_by_app_id(inbound_app_id)
                if not app_record and inbound_app_id == getattr(settings, "LARK_APP_ID", ""):
                    # Backward-compatible path for the legacy .env App while it
                    # has not yet been migrated into the registry.
                    app_record = None
                    app_specific_validated = False
                if app_record:
                    if not app_record.get("verification_token"):
                        return Response(
                            content=json.dumps({"code": 403, "msg": "Custom App thiếu verification_token"}),
                            media_type="application/json",
                            status_code=403,
                        )
                    inbound_token = (
                        app_header.get("token")
                        or payload.get("token")
                        or payload.get("event", {}).get("token", "")
                    )
                    if not inbound_token or inbound_token != app_record["verification_token"]:
                        logger.error("[WEBHOOK] rejected reason=invalid_verification_token app_id=%s", inbound_app_id)
                        return Response(
                            content=json.dumps({"code": 403, "msg": "invalid verification_token"}),
                            media_type="application/json",
                            status_code=403,
                        )
                    # The SDK dispatcher is initialized with the legacy global
                    # token. Mark this payload as validated so the common
                    # dispatch path can skip that global validation later.
                    app_specific_validated = True
            except Exception as app_event_err:
                logger.error("[WEBHOOK] custom_app_routing_failed app_id=%s error=%s", inbound_app_id, app_event_err, exc_info=True)
                return Response(
                    content=json.dumps({"code": 500, "msg": "custom app event dispatch failed"}),
                    media_type="application/json",
                    status_code=500,
                )

        if inbound_app_id and not app_record and inbound_app_id != getattr(settings, "LARK_APP_ID", ""):
            logger.error("[WEBHOOK] rejected reason=unknown_custom_app app_id=%s", inbound_app_id)
            return Response(
                content=json.dumps({"code": 403, "msg": "unknown Custom App"}),
                media_type="application/json",
                status_code=403,
            )

        # 1.5. Xử lý sự kiện app_ticket (Lark Marketplace ISV Token Lifecycle - EDL-0020)
        if isinstance(payload, dict):
            event_type = payload.get("header", {}).get("event_type") or payload.get("type")
            if event_type == "app_ticket" or "app_ticket" in payload.get("event", {}):
                try:
                    from services.auth.isv_token_service import isv_token_service
                    handled = await isv_token_service.handle_app_ticket_event(payload)
                    if handled:
                        return Response(
                            content=json.dumps({"code": 0, "msg": "success"}),
                            media_type="application/json",
                            status_code=200,
                        )
                except Exception as ex:
                    logger.error("[WEBHOOK] app_ticket_failed error=%s", ex)

        # 1.6. Xử lý sự kiện Tenant Lifecycle (app_status_change / app_uninstalled / open_app - EDL-0020)
        if isinstance(payload, dict):
            event_type = payload.get("header", {}).get("event_type") or payload.get("type")
            if event_type in ("app_status_change", "app_uninstalled", "open_app"):
                try:
                    from services.lark.handlers.tenant_lifecycle_handler import handle_tenant_lifecycle_event
                    handled = await handle_tenant_lifecycle_event(payload)
                    if handled:
                        return Response(
                            content=json.dumps({"code": 0, "msg": "success"}),
                            media_type="application/json",
                            status_code=200,
                        )
                except Exception as ex:
                    logger.error("[WEBHOOK] tenant_lifecycle_failed error=%s", ex)

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

            # Card callback chuẩn đôi khi không có header.app_id hoặc tenant_key bị rỗng.
            # Tự động truy vấn tenant_key từ admin_open_id nếu cần.
            card_tenant = action_val.get("tenant_key")
            if not card_tenant and open_id:
                try:
                    from database.db import get_tenants_collection
                    t_col = get_tenants_collection()
                    found_t = await t_col.find_one({"admin_open_id": open_id})
                    if found_t and found_t.get("tenant_key"):
                        card_tenant = found_t["tenant_key"]
                        action_val["tenant_key"] = card_tenant
                except Exception:
                    pass

            if not app_record and card_tenant:
                try:
                    from services.lark_app_service import lark_app_service
                    app_record = await lark_app_service.get_by_tenant_key(card_tenant)
                except Exception as resolve_err:
                    logger.warning(
                        "[WEBHOOK] card_app_resolve_failed tenant=%s error=%s",
                        card_tenant,
                        resolve_err,
                    )
            runtime_context_token = None
            try:
                if app_record:
                    from services.lark.runtime import get_or_create_lark_service, set_current_lark_service
                    runtime_service = await get_or_create_lark_service(app_record)
                    runtime_context_token = set_current_lark_service(runtime_service)
                if action_val:
                    ok, toast_msg, updated_card = await handle_card_action(open_id, message_id, action_val)
                else:
                    ok, toast_msg, updated_card = False, "Không xác định được hành động", None
            finally:
                if runtime_context_token is not None:
                    from services.lark.runtime import reset_current_lark_service
                    reset_current_lark_service(runtime_context_token)
            if action_val:
                resp_data: Dict[str, Any] = {}
                if toast_msg:
                    resp_data["toast"] = {
                        "type": "success" if ok else "warning",
                        "content": toast_msg,
                    }
                if updated_card:
                    if isinstance(updated_card, dict) and "data" in updated_card and "type" in updated_card:
                        resp_data["card"] = updated_card
                    else:
                        resp_data["card"] = {
                            "type": "raw",
                            "data": updated_card,
                        }
                return Response(
                    content=json.dumps(resp_data, ensure_ascii=False),
                    media_type="application/json; charset=utf-8",
                    status_code=200,
                )

        # 3. Xây dựng RawRequest cho Lark SDK EventDispatcher
        raw_req = RawRequest()
        raw_req.uri = request.url.path
        raw_req.body = body_bytes
        raw_req.headers = _lark_raw_headers(request)

        # 4. Chuyển cho SDK Dispatcher xử lý
        runtime_service = self
        runtime_context_token = None
        if inbound_app_id and app_record:
            try:
                from services.lark.runtime import get_or_create_lark_service, set_current_lark_service
                runtime_service = await get_or_create_lark_service(app_record)
                runtime_context_token = set_current_lark_service(runtime_service)
                app_specific_validated = True
            except Exception as runtime_err:
                logger.error("[WEBHOOK] runtime_init_failed app_id=%s error=%s", inbound_app_id, runtime_err, exc_info=True)
                return Response(
                    content=json.dumps({"code": 500, "msg": "custom app runtime unavailable"}),
                    media_type="application/json",
                    status_code=500,
                )

        try:
            raw_resp = (
                runtime_service.event_dispatcher._do_without_validation(body_bytes)
                if app_specific_validated
                else self.event_dispatcher.do(raw_req)
            )
            return Response(
                content=raw_resp.content,
                status_code=raw_resp.status_code,
                media_type=getattr(raw_resp, "content_type", None) or "application/json",
            )
        except Exception as e:
            logger.warning("[WEBHOOK] fallback_without_validation error=%s", e)
            try:
                runtime_service.event_dispatcher._do_without_validation(body_bytes)
                return Response(
                    content=json.dumps({"msg": "success"}),
                    media_type="application/json",
                    status_code=200,
                )
            except Exception as inner_e:
                logger.error("[WEBHOOK] dispatch_failed error=%s", inner_e, exc_info=True)
                return Response(
                    content=json.dumps({"msg": str(inner_e)}),
                    status_code=500,
                    media_type="application/json",
                )
        finally:
            if runtime_context_token is not None:
                from services.lark.runtime import reset_current_lark_service
                reset_current_lark_service(runtime_context_token)

    async def handle_card_action_request(self, request: Request) -> Response:
        """Endpoint chuyên xử lý Card Action Callback từ Lark."""
        return await self.handle_fastapi_request(request)
