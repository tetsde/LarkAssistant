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
    P2ImChatMemberBotAddedV1,
    P2ImChatMemberBotDeletedV1,
)
from lark_oapi.api.drive.v1 import (
    P2DriveFileBitableRecordChangedV1,
    P2DriveFileBitableFieldChangedV1,
    P2DriveFileEditV1,
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

        # Khởi tạo EventDispatcherHandler của Lark
        self.event_dispatcher = self._build_event_dispatcher()

    def _build_event_dispatcher(self) -> lark.EventDispatcherHandler:
        """Xây dựng bộ lắng nghe sự kiện Lark (Event Dispatcher)."""
        builder = lark.EventDispatcherHandler.builder(
            self.encrypt_key or "",
            self.verification_token or "",
        )
        builder.register_p2_im_message_receive_v1(self._internal_on_message_event)
        builder.register_p2_im_chat_member_bot_added_v1(self._internal_on_bot_added_event)
        builder.register_p2_im_chat_member_bot_deleted_v1(self._internal_on_bot_deleted_event)
        builder.register_p2_drive_file_bitable_record_changed_v1(self._internal_on_bitable_record_changed_event)
        builder.register_p2_drive_file_bitable_field_changed_v1(self._internal_on_bitable_field_changed_event)
        builder.register_p2_drive_file_edit_v1(self._internal_on_drive_file_edit_event)
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

        print(f"⚡ [LARK DISPATCHER] Bắt được tin nhắn từ Lark: '{lark_msg.text}' (người gửi: {lark_msg.sender_id}, is_self={lark_msg.is_self}, is_bot={lark_msg.is_bot})")

        # 1. Bỏ qua tin nhắn từ Bot / App
        if lark_msg.is_bot:
            print(f"ℹ️ [LARK DISPATCHER] Bỏ qua vì tin nhắn phát từ Bot/App: {lark_msg.message_id}")
            return

        # 2. Bỏ qua tin nhắn do chính hệ thống vừa phát ngôn gửi đi (tránh bắt lại tin nhắn reply của chính bot)
        if lark_msg.message_id in self._sent_message_ids:
            print(f"ℹ️ [LARK DISPATCHER] Bỏ qua tin nhắn do hệ thống vừa gửi đi: {lark_msg.message_id}")
            return

        # 3. Bỏ qua tin nhắn trùng lặp (Idempotency)
        if self._is_duplicate_message(lark_msg.message_id):
            logger.info(f"Bỏ qua tin nhắn trùng lặp: {lark_msg.message_id}")
            return

        # 4. Nhận diện tin nhắn từ tài khoản của bạn (Chủ nhân)
        if lark_msg.is_self:
            if lark_msg.chat_type == "group":
                print(f"👑 [LARK DISPATCHER] Bắt được tin nhắn từ chủ nhân trong Group: '{lark_msg.text}' -> Chuyển tiếp tới handler (chế độ chỉ ghi nhớ/ignore)!")
            else:
                print(f"📩 [LARK DISPATCHER] Nhận tin nhắn trực tiếp từ chủ nhân trong DM 1-1: '{lark_msg.text}'")

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

            # Tự động đồng bộ vào Lark Base (Bitable)
            from services.larkbase import lark_base_service

            base_record = None
            try:
                base_record = lark_base_service.find_record_by_chat_id(chat_id)
                if not base_record:
                    base_record = lark_base_service.create_record({
                        "Dự án / Nhóm": chat_name,
                        "ID Group": chat_id,
                    })
                    logger.info(f"✅ Đã tự động tạo dòng mới trong Lark Base cho nhóm '{chat_name}' (Record: {base_record.record_id})")
                else:
                    logger.info(f"ℹ️ Nhóm '{chat_name}' ({chat_id}) đã tồn tại trong Lark Base (Record: {base_record.record_id})")

                # Đồng bộ tức thì nhóm chat mới vào MongoDB (chat_scopes)
                if base_record:
                    from services.scope_service import scope_service
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(scope_service.sync_group_from_base_record(base_record))
                    except RuntimeError:
                        try:
                            asyncio.run(scope_service.sync_group_from_base_record(base_record))
                        except Exception as sync_err:
                            logger.warning(f"Không thể sync ngay sang MongoDB: {sync_err}")
            except Exception as e:
                logger.error(f"⚠️ Lỗi khi đồng bộ nhóm vào Lark Base: {e}", exc_info=True)

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

            for handler in self._bitable_record_handlers:
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
