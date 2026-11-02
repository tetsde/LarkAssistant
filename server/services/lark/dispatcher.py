"""
HiLark Lark Dispatcher
======================
Vị trí: server/services/lark_dispatcher.py

Mục đích:
    Xử lý tất cả sự kiện nhận về từ Lark:
      1. Parse sự kiện raw → LarkMessage tinh gọn
      2. Chống tin nhắn trùng lặp (Deduplication Cache)
      3. Lắng nghe và phân phối sự kiện: tin nhắn, bot thêm/xóa, Lark Base (Bitable)
      4. Đăng ký Message Handlers (hỗ trợ cả sync & async callbacks)

Import:
    from services.lark_dispatcher import LarkDispatcherMixin
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    P2ImMessageRecalledV1,
    P2ImChatMemberBotAddedV1,
    P2ImChatMemberBotDeletedV1,
    P2ImMessageReactionCreatedV1,
)
from lark_oapi.api.drive.v1 import (
    P2DriveFileBitableRecordChangedV1,
    P2DriveFileBitableFieldChangedV1,
    P2DriveFileEditV1,
)
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
    CallBackToast,
    CallBackCard,
)

from models.lark import LarkMessage

logger = logging.getLogger("hilark.lark")


class LarkDispatcherMixin:
    """
    Mixin xử lý sự kiện và phân phối tin nhắn:
      - Parse raw Lark event → LarkMessage
      - Deduplication cache (chống tin nhắn trùng)
      - Handlers registry (on_message, on_bitable_record_changed...)
    """

    def _init_dispatcher(self) -> None:
        """Khởi tạo các biến cần thiết cho Dispatcher."""
        # Danh sách các hàm callback lắng nghe tin nhắn
        self._message_handlers: List[Callable[[LarkMessage], Any]] = []

        # Danh sách các hàm callback lắng nghe sự kiện Lark Base (Bitable)
        self._bitable_record_handlers: List[Callable[[Any], Any]] = []
        self._bitable_field_handlers: List[Callable[[Any], Any]] = []

        # Cache chống duplicate message_id (Lark có cơ chế retry nếu chưa nhận 200 trong 3s)
        self._processed_msg_ids: OrderedDict[str, float] = OrderedDict()
        self._dedup_lock = asyncio.Lock() if hasattr(asyncio, "Lock") else None

        # Cache ánh xạ admin_open_id theo tenant_key (ISV Multi-Tenant)
        self._tenant_admin_cache: Dict[str, str] = {}

        # Khởi tạo EventDispatcherHandler của Lark
        self.event_dispatcher = self._build_event_dispatcher()

    def register_tenant_admin(self, tenant_key: str, admin_open_id: str) -> None:
        """Đăng ký / cập nhật admin open_id cho tenant trong bộ nhớ đệm."""
        if tenant_key and admin_open_id:
            self._tenant_admin_cache[tenant_key] = admin_open_id

    def get_tenant_admin(self, tenant_key: str) -> Optional[str]:
        """Lấy admin open_id của tenant nếu đã được cache."""
        return self._tenant_admin_cache.get(tenant_key)

    def _build_event_dispatcher(self) -> lark.EventDispatcherHandler:
        """Xây dựng bộ lắng nghe sự kiện Lark (Event Dispatcher)."""
        builder = lark.EventDispatcherHandler.builder(
            self.encrypt_key or "",
            self.verification_token or "",
        )
        builder.register_p2_im_message_receive_v1(self._internal_on_message_event)
        builder.register_p2_im_message_recalled_v1(self._internal_on_message_recalled_event)
        builder.register_p2_im_message_reaction_created_v1(self._internal_on_reaction_created_event)
        builder.register_p2_im_chat_member_bot_added_v1(self._internal_on_bot_added_event)
        builder.register_p2_im_chat_member_bot_deleted_v1(self._internal_on_bot_deleted_event)
        builder.register_p2_drive_file_bitable_record_changed_v1(self._internal_on_bitable_record_changed_event)
        builder.register_p2_drive_file_bitable_field_changed_v1(self._internal_on_bitable_field_changed_event)
        builder.register_p2_drive_file_edit_v1(self._internal_on_drive_file_edit_event)
        # Lark có thể phát event này khi user mở/đọc file Drive. HiLark không
        # cần xử lý nội dung đọc file ở event layer, nhưng vẫn phải đăng ký
        # để SDK acknowledge event thay vì báo "processor not found".
        builder.register_p2_customized_event("drive.file.read_v1", self._internal_on_drive_file_read_event)
        builder.register_p2_card_action_trigger(self._internal_on_card_action_trigger)
        return builder.build()

    # -------------------------------------------------------------------------
    # BÓC TÁCH TIN NHẮN (PARSER)
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

        # 0. Bóc tách tenant_key từ Header hoặc Sender (EDL-0020 Multi-Tenant)
        header = getattr(event, "header", None)
        tenant_key = ""
        if header:
            tenant_key = getattr(header, "tenant_key", "") or ""
        if not tenant_key and sender:
            tenant_key = getattr(sender, "tenant_key", "") or ""

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

        # Kiểm tra xem có phải chính User của token gửi không (hỗ trợ phân biệt theo tenant_key)
        my_open_id = self.known_user_open_id
        if tenant_key and tenant_key in self._tenant_admin_cache:
            my_open_id = self._tenant_admin_cache[tenant_key]
        elif self._current_user_profile and self._current_user_profile.get("open_id"):
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
            tenant_key=tenant_key,
            raw_event=event,
        )

    def parse_list_message_item(self, item: Any, chat_type: str = "p2p") -> Optional[LarkMessage]:
        """
        Chuyển đổi một đối tượng tin nhắn trả về từ API list_messages thành LarkMessage.
        Dùng cho DM Polling.
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

    # -------------------------------------------------------------------------
    # CHỐNG TIN NHẮN TRÙNG LẶP (DEDUPLICATION)
    # -------------------------------------------------------------------------

    def _is_duplicate_message(self, message_id: str) -> bool:
        """Kiểm tra và lưu cache chống xử lý lặp lại tin nhắn."""
        if not message_id:
            return False

        now = time.time()
        # Xoá các mã tin nhắn đã quá 10 phút khỏi cache
        while self._processed_msg_ids and (now - next(iter(self._processed_msg_ids.values())) > 600):
            self._processed_msg_ids.popitem(last=False)

        if message_id in self._processed_msg_ids:
            return True

        self._processed_msg_ids[message_id] = now
        if len(self._processed_msg_ids) > 1000:
            self._processed_msg_ids.popitem(last=False)
        return False

    # -------------------------------------------------------------------------
    # XỬ LÝ SỰ KIỆN NỘI BỘ (INTERNAL EVENT HANDLERS)
    # -------------------------------------------------------------------------

    def _internal_on_message_event(self, data: P2ImMessageReceiveV1) -> None:
        """Hàm callback nội bộ được gọi bởi Lark Event Dispatcher."""
        lark_msg = self.parse_event(data)
        if not lark_msg:
            print("⚠️ [LARK DISPATCHER] Nhận được event nhưng không parse được cấu trúc message.")
            return

        logger.debug("[DISPATCH] parsed msg=%s sender=%s bot=%s", lark_msg.message_id, lark_msg.sender_id, lark_msg.is_bot)

        # 1. Bỏ qua tin nhắn từ Bot / App
        if lark_msg.is_bot:
            logger.debug("[DROP] msg=%s reason=bot_message", lark_msg.message_id)
            return

        # 2. Bỏ qua tin nhắn do chính hệ thống vừa phát ngôn gửi đi (tránh bắt lại tin nhắn reply của chính bot)
        if lark_msg.message_id in self._sent_message_ids:
            logger.debug("[DROP] msg=%s reason=self_sent", lark_msg.message_id)
            return

        # 3. Bỏ qua tin nhắn trùng lặp (Idempotency)
        if self._is_duplicate_message(lark_msg.message_id):
            logger.info(f"Bỏ qua tin nhắn trùng lặp: {lark_msg.message_id}")
            return

        # 4. Nhận diện tin nhắn từ tài khoản của bạn (Chủ nhân)
        logger.info(
            "[DISPATCH] msg=%s chat_type=%s sender=%s self=%s",
            lark_msg.message_id, lark_msg.chat_type, lark_msg.sender_id, lark_msg.is_self,
        )

        self._dispatch_to_handlers(lark_msg)

    def _dispatch_to_handlers(self, lark_msg: LarkMessage) -> None:
        """Phân phối tin nhắn tới các handlers đã đăng ký (tự động kích hoạt TenantContext nếu có tenant_key)."""
        tenant_key = getattr(lark_msg, "tenant_key", "")

        for handler in self._message_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    async def _scoped_runner(h=handler, msg=lark_msg, tk=tenant_key):
                        if tk:
                            from database.scoped_query import async_tenant_context
                            async with async_tenant_context(tk):
                                await h(msg)
                        else:
                            await h(msg)

                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(_scoped_runner())
                    except RuntimeError:
                        asyncio.run(_scoped_runner())
                else:
                    if tenant_key:
                        from database.scoped_query import tenant_context
                        with tenant_context(tenant_key):
                            handler(lark_msg)
                    else:
                        handler(lark_msg)
            except Exception as e:
                logger.error(f"Lỗi khi thực thi message handler {handler.__name__}: {e}", exc_info=True)

    def _internal_on_reaction_created_event(self, data: P2ImMessageReactionCreatedV1) -> None:
        """
        [Fast Reaction Hook - Tier 1 Decision Governance]
        Xử lý sự kiện reaction (thả emoji) vào tin nhắn từ Lark (im.message.reaction.created_v1).
        Khi Lãnh đạo (Owner) thả emoji đồng thuận (👍, ✅, OK, THUMBSUP, etc.):
        Tự động thăng hạng các claim PROPOSED phát sinh từ message đó thành CURRENT.
        0 token LLM, 0ms latency, 0% regex!
        """
        try:
            event = getattr(data, "event", None)
            if not event:
                return

            message_id = getattr(event, "message_id", "")
            reaction_type = getattr(event, "reaction_type", None)
            emoji_type = getattr(reaction_type, "emoji_type", "") if reaction_type else ""
            user_id_obj = getattr(event, "user_id", None)
            user_open_id = getattr(user_id_obj, "open_id", "") if user_id_obj else ""

            if not message_id or not emoji_type:
                return

            print(f"👍 [LARK REACTION] Bắt được reaction '{emoji_type}' vào tin nhắn {message_id} từ {user_open_id}")

            # Kiểm tra xem có phải Lãnh đạo (Owner) thả reaction hay không
            is_owner = False
            from core.config import settings
            if user_open_id and settings.LARK_USER_OPEN_ID and user_open_id == settings.LARK_USER_OPEN_ID:
                is_owner = True
            elif hasattr(self, "_current_user_profile") and self._current_user_profile:
                owner_open_id = self._current_user_profile.get("open_id")
                if owner_open_id and user_open_id == owner_open_id:
                    is_owner = True

            if not is_owner:
                logger.debug(f"[Reaction Gate] User {user_open_id} không phải Owner, bỏ qua.")
                return

            # Danh sách Emoji phê duyệt chính thức
            APPROVAL_EMOJIS = {
                "THUMBSUP", "OK", "CHECK_MARK", "DONE", "APPLAUSE", "HEART",
                "FISTBUMP", "MUSCLE", "FIRE", "+1"
            }
            if emoji_type.upper() not in APPROVAL_EMOJIS:
                logger.debug(f"[Reaction Gate] Emoji '{emoji_type}' không phải emoji phê duyệt.")
                return

            # Kích hoạt thăng hạng claims thành CURRENT
            async def _promote():
                try:
                    from database.db import promote_claims_by_message_id
                    approver_info = {
                        "user_id": user_open_id,
                        "user_name": settings.LARK_USER_NAME or "Lãnh đạo",
                        "role": "owner",
                    }
                    promoted = await promote_claims_by_message_id(message_id, approver_info=approver_info)
                    if promoted > 0:
                        print(f"🎉 [FAST REACTION APPROVAL] Sếp đã thả {emoji_type} vào tin {message_id}! Đã thăng hạng {promoted} fact(s) thành CURRENT.")
                    else:
                        print(f"ℹ️ [FAST REACTION APPROVAL] Sếp thả {emoji_type} vào tin {message_id} (không có fact PROPOSED nào gắn với message này).")
                except Exception as e:
                    logger.error(f"Lỗi khi thăng hạng claim qua reaction: {e}", exc_info=True)

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_promote())
            except RuntimeError:
                try:
                    asyncio.run(_promote())
                except Exception as e:
                    logger.error(f"Lỗi chạy async promote: {e}")

        except Exception as e:
            logger.error(f"Lỗi xử lý reaction created event: {e}", exc_info=True)

    def _internal_on_message_recalled_event(self, data: P2ImMessageRecalledV1) -> None:
        """
        Xử lý sự kiện tin nhắn bị thu hồi từ Lark (im.message.recalled_v1).
        Kích hoạt đồng bộ dọn dẹp trên 4 tầng: Staging, Claims, Drafts, và Bot Reply.
        """
        print("⚡ [LARK DISPATCHER] Bắt được sự kiện thu hồi tin nhắn (im.message.recalled_v1) từ Lark!")
        try:
            from services.lark.handlers.recall_handler import handle_message_recalled

            async def _run():
                try:
                    await handle_message_recalled(data)
                except Exception as e:
                    logger.error(f"Lỗi khi thực thi handle_message_recalled: {e}", exc_info=True)

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_run())
            except RuntimeError:
                try:
                    asyncio.run(_run())
                except Exception as e:
                    logger.error(f"Lỗi chạy async recall task: {e}")
        except Exception as e:
            logger.error(f"Lỗi khi tiếp nhận sự kiện message recalled: {e}", exc_info=True)

    def _internal_on_bot_added_event(self, data: P2ImChatMemberBotAddedV1) -> None:
        """Xử lý sự kiện Bot được thêm vào nhóm chat (im.chat.member.bot.added_v1)."""
        try:
            event = getattr(data, "event", None)
            chat_id = getattr(event, "chat_id", "") if event else ""
            chat_name = getattr(event, "name", "") if event else "Nhóm chat"
            operator_id = ""
            if event and getattr(event, "operator_id", None):
                operator_id = getattr(event.operator_id, "open_id", "") or getattr(event.operator_id, "user_id", "")

            operator_name = self.get_user_name(operator_id) or operator_id or "Thành viên"
            print(f"\n" + "=" * 65)
            print(f"🎉 [LARK BOT EVENT] BOT ĐÃ ĐƯỢC THÊM VÀO NHÓM CHAT!")
            print(f"   • Tên nhóm : {chat_name}")
            print(f"   • Chat ID  : {chat_id}")
            print(f"   • Người thêm: {operator_name}")
            print("=" * 65 + "\n")
            logger.info(f"🎉 Bot được thêm vào nhóm '{chat_name}' ({chat_id}) bởi {operator_name}")

            if not chat_id:
                logger.warning("Không tìm thấy chat_id trong sự kiện bot_added. Bỏ qua ghi nhận Base.")
                return

            header = getattr(data, "header", None)
            tenant_key = getattr(header, "tenant_key", "") if header else ""

            async def _async_bot_added_handler():
                from contextlib import nullcontext
                from database.scoped_query import tenant_context
                from services.lark.bitable import lark_base_service
                from services.lark.base_provision_service import base_provision_service
                from services.knowledge.chat_scopes import scope_service

                ctx = tenant_context(tenant_key) if tenant_key else nullcontext()
                with ctx:
                    # 1. Định tuyến đúng Lark Base cho tenant nếu có
                    active_app_token, active_table_id = await base_provision_service.get_chat_scope_target(tenant_key=tenant_key)
                    if active_app_token:
                        lark_base_service.app_token = active_app_token
                    if active_table_id:
                        lark_base_service.table_id = active_table_id

                    base_record = None
                    try:
                        base_record = await asyncio.to_thread(lark_base_service.find_record_by_chat_id, chat_id)
                        if not base_record:
                            record_fields = {
                                "Chat ID": chat_id,
                                "ID Group": chat_id,
                                "Tên dự án": chat_name,
                                "Dự án / Nhóm": chat_name,
                                "Text": chat_name,
                                "Trạng thái hoạt động": "active",
                            }
                            # Lark thường tạo sẵn một dòng rỗng khi tạo Base.
                            # Lấp dòng đó trước để không sinh thêm row rác.
                            all_records = await asyncio.to_thread(lark_base_service.get_all_records)
                            empty_record = next(
                                (
                                    record for record in all_records
                                    if not (
                                        record.clean_fields.get("Chat ID")
                                        or record.clean_fields.get("ID Group")
                                        or record.clean_fields.get("Text")
                                        or record.clean_fields.get("Tên dự án")
                                        or record.clean_fields.get("Dự án / Nhóm")
                                    )
                                ),
                                None,
                            )
                            if empty_record:
                                base_record = await asyncio.to_thread(
                                    lark_base_service.update_record,
                                    empty_record.record_id,
                                    record_fields,
                                )
                                logger.info(f"✅ Đã điền dòng rỗng trong Lark Base cho nhóm '{chat_name}' (Record: {base_record.record_id})")
                            else:
                                base_record = await asyncio.to_thread(
                                    lark_base_service.create_record,
                                    record_fields,
                                )
                                logger.info(f"✅ Đã tự động tạo dòng mới trong Lark Base cho nhóm '{chat_name}' (Record: {base_record.record_id})")
                        else:
                            logger.info(f"ℹ️ Nhóm '{chat_name}' ({chat_id}) đã tồn tại trong Lark Base (Record: {base_record.record_id})")

                        # Đồng bộ tức thì nhóm chat mới vào MongoDB (chat_scopes)
                        if base_record:
                            await scope_service.sync_group_from_base_record(base_record)
                    except Exception as b_err:
                        logger.error(f"⚠️ Lỗi khi đồng bộ nhóm vào Lark Base: {b_err}", exc_info=True)

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_async_bot_added_handler())
            except RuntimeError:
                try:
                    asyncio.run(_async_bot_added_handler())
                except Exception as e:
                    logger.error(f"Lỗi chạy async bot_added task: {e}")

        except Exception as e:
            logger.error(f"Lỗi xử lý sự kiện bot_added: {e}", exc_info=True)

    def _internal_on_bot_deleted_event(self, data: P2ImChatMemberBotDeletedV1) -> None:
        """Xử lý sự kiện Bot bị gỡ khỏi nhóm chat (im.chat.member.bot.deleted_v1)."""
        try:
            event = getattr(data, "event", None)
            chat_id = getattr(event, "chat_id", "") if event else ""
            chat_name = getattr(event, "name", "") if event else "Nhóm chat"
            print(f"\nℹ️ [LARK BOT EVENT] Bot đã bị gỡ khỏi nhóm: '{chat_name}' ({chat_id})")
            logger.info(f"ℹ️ Bot bị gỡ khỏi nhóm '{chat_name}' ({chat_id})")
        except Exception as e:
            logger.error(f"Lỗi xử lý sự kiện bot_deleted: {e}", exc_info=True)

    def _internal_on_bitable_record_changed_event(self, data: P2DriveFileBitableRecordChangedV1) -> None:
        """Xử lý sự kiện bản ghi trong Lark Base bị thay đổi (drive.file.bitable_record_changed_v1)."""
        try:
            event = getattr(data, "event", None)
            if not event:
                return

            file_token = getattr(event, "file_token", "")
            table_id = getattr(event, "table_id", "")
            operator_id = ""
            if getattr(event, "operator_id", None):
                operator_id = getattr(event.operator_id, "open_id", "") or getattr(event.operator_id, "user_id", "")
            operator_name = self.get_user_name(operator_id) or operator_id or "Thành viên"

            action_list = getattr(event, "action_list", []) or []
            from datetime import datetime
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            print("\n" + "=" * 65)
            print("📊 [LARK BASE EVENT] PHÁT HIỆN DỮ LIỆU BẢNG BASE THAY ĐỔI:")
            print("-" * 65)
            print(f"🕒 Thời gian    : {now_str}")
            print(f"📦 Base Token   : {file_token}")
            print(f"📊 Table ID     : {table_id}")
            print(f"👤 Người sửa    : {operator_name} ({operator_id})")
            print(f"📝 Số hành động : {len(action_list)}")

            for idx, act in enumerate(action_list, 1):
                rec_id = getattr(act, "record_id", "")
                action_type = getattr(act, "action", "")
                print(f"  [{idx}] Record ID: {rec_id} | Hành động: {action_type}")

                before_list = getattr(act, "before_value", []) or []
                after_list = getattr(act, "after_value", []) or []
                if before_list or after_list:
                    field_ids = set()
                    b_map = {}
                    a_map = {}
                    for b in before_list:
                        fid = getattr(b, "field_id", "")
                        b_map[fid] = getattr(b, "field_value", "")
                        field_ids.add(fid)
                    for a in after_list:
                        fid = getattr(a, "field_id", "")
                        a_map[fid] = getattr(a, "field_value", "")
                        field_ids.add(fid)

                    for fid in field_ids:
                        old_v = b_map.get(fid, "(trống)")
                        new_v = a_map.get(fid, "(trống)")
                        print(f"      • Cột {fid}: {old_v} -> {new_v}")

            print("=" * 65 + "\n")
            logger.info(f"📊 Lark Base change event received for table {table_id} by {operator_name}")

            header = getattr(data, "header", None)
            tenant_key = getattr(header, "tenant_key", "") if header else ""

            for handler in self._bitable_record_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        async def _scoped_bitable_runner(h=handler, d=data, tk=tenant_key):
                            if tk:
                                from database.scoped_query import async_tenant_context
                                async with async_tenant_context(tk):
                                    await h(d)
                            else:
                                await h(d)

                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(_scoped_bitable_runner())
                        except RuntimeError:
                            asyncio.run(_scoped_bitable_runner())
                    else:
                        if tenant_key:
                            from database.scoped_query import tenant_context
                            with tenant_context(tenant_key):
                                handler(data)
                        else:
                            handler(data)
                except Exception as e:
                    logger.error(f"Lỗi khi thực thi bitable_record_handler: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Lỗi xử lý sự kiện bitable_record_changed: {e}", exc_info=True)

    def _internal_on_bitable_field_changed_event(self, data: P2DriveFileBitableFieldChangedV1) -> None:
        """Xử lý sự kiện cấu trúc cột trong Lark Base bị thay đổi (drive.file.bitable_field_changed_v1)."""
        try:
            event = getattr(data, "event", None)
            table_id = getattr(event, "table_id", "") if event else ""
            file_token = getattr(event, "file_token", "") if event else ""
            print(f"\n📐 [LARK BASE EVENT] Cấu trúc cột của Base '{file_token}' (bảng '{table_id}') vừa thay đổi.")
            logger.info(f"📐 Lark Base field changed for table {table_id}")

            for handler in self._bitable_field_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(handler(data))
                        except RuntimeError:
                            asyncio.run(handler(data))
                    else:
                        handler(data)
                except Exception as e:
                    logger.error(f"Lỗi khi thực thi bitable_field_handler: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Lỗi xử lý sự kiện bitable_field_changed: {e}", exc_info=True)

    def _internal_on_drive_file_edit_event(self, data: P2DriveFileEditV1) -> None:
        """Xử lý sự kiện chỉnh sửa file trên Drive (drive.file.edit_v1)."""
        logger.debug("Drive file edit event received (drive.file.edit_v1)")

    def _internal_on_drive_file_read_event(self, data: Any) -> None:
        """Acknowledge event đọc Drive; việc ingest tài liệu đi qua pipeline riêng."""
        logger.debug("Drive file read event ignored (drive.file.read_v1)")

    def _internal_on_card_action_trigger(self, data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        """
        Xử lý sự kiện khi người dùng bấm nút trên Thẻ tương tác (Interactive Card)
        nhận qua WebSocket persistent connection (card.action.trigger).
        """
        try:
            event = getattr(data, "event", None)
            if not event:
                return P2CardActionTriggerResponse()

            operator = getattr(event, "operator", None)
            open_id = getattr(operator, "open_id", "") if operator else ""

            context = getattr(event, "context", None)
            message_id = getattr(context, "open_message_id", "") if context else ""

            action = getattr(event, "action", None)
            action_val = getattr(action, "value", {}) if action else {}

            logger.info(f"🔘 [LARK WS CARD ACTION] Nhận tương tác nút bấm từ {open_id} trên thẻ {message_id}: {action_val}")

            from services.lark.handlers.card_action_handler import handle_card_action
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=1) as executor:
                ok, toast_msg, updated_card = executor.submit(
                    lambda: asyncio.run(handle_card_action(open_id, message_id, action_val))
                ).result(timeout=10.0)

            resp = P2CardActionTriggerResponse()
            if toast_msg:
                resp.toast = CallBackToast()
                resp.toast.type = "success" if ok else "warning"
                resp.toast.content = toast_msg
            if updated_card:
                resp.card = CallBackCard()
                resp.card.type = "raw"
                resp.card.data = updated_card
            return resp
        except Exception as e:
            logger.error(f"Lỗi khi xử lý card action trigger trong WebSocket: {e}", exc_info=True)
            err_resp = P2CardActionTriggerResponse()
            err_resp.toast = CallBackToast()
            err_resp.toast.type = "danger"
            err_resp.toast.content = "Đã xảy ra lỗi khi xử lý thao tác nút bấm."
            return err_resp

    # -------------------------------------------------------------------------
    # ĐĂNG KÝ HANDLERS (MESSAGE & BITABLE)
    # -------------------------------------------------------------------------

    def on_message(self, func: Callable[[LarkMessage], Any]) -> Callable[[LarkMessage], Any]:
        """Decorator để đăng ký hàm xử lý tin nhắn tới. Hỗ trợ cả async def và def thông thường."""
        self.register_handler(func)
        return func

    def register_handler(self, handler: Callable[[LarkMessage], Any]) -> None:
        """Đăng ký hàm xử lý tin nhắn."""
        if handler not in self._message_handlers:
            self._message_handlers.append(handler)

    def on_bitable_record_changed(self, func: Callable[[Any], Any]) -> Callable[[Any], Any]:
        """Decorator đăng ký hàm xử lý khi bản ghi trong Lark Base thay đổi."""
        self.register_bitable_record_handler(func)
        return func

    def register_bitable_record_handler(self, handler: Callable[[Any], Any]) -> None:
        """Đăng ký hàm xử lý sự kiện bitable record changed."""
        if handler not in self._bitable_record_handlers:
            self._bitable_record_handlers.append(handler)

    def on_bitable_field_changed(self, func: Callable[[Any], Any]) -> Callable[[Any], Any]:
        """Decorator đăng ký hàm xử lý khi cấu trúc cột trong Lark Base thay đổi."""
        self.register_bitable_field_handler(func)
        return func

    def register_bitable_field_handler(self, handler: Callable[[Any], Any]) -> None:
        """Đăng ký hàm xử lý sự kiện bitable field changed."""
        if handler not in self._bitable_field_handlers:
            self._bitable_field_handlers.append(handler)
