"""
HiLark Chat Queue & Smart Message Debouncer
==========================================
Vị trí: server/utils/chat_queue.py

Cung cấp:
  1. MessageDebouncer: Gom tin nhắn gõ ngắt dòng của cùng 1 user trong 1 nhóm chat (mặc định 1.75s).
  2. ThrottledChatQueue: Hàng đợi bất đồng bộ làm mượt tốc độ (Rate Smoothing / Cooldown),
     bảo vệ quota LLM và tránh lỗi 429 mà không làm gián đoạn phòng chat (Silent Throttling).
  3. ChatQueueService: Dịch vụ tích hợp kết nối Debouncer, ThrottledQueue và Chat Pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

from core.config import settings
from database.scoped_query import async_tenant_context
from models.chat_queue import ChatQueueItem
from models.lark import LarkMessage

logger = logging.getLogger("hilark.queue")


class MessageDebouncer:
    """
    Bộ đệm gom tin nhắn theo cặp (chat_id, sender_id).
    Nếu người dùng gửi liên tiếp nhiều dòng trong khoảng debounce_seconds,
    hệ thống gom lại thành 1 văn bản nối bằng dấu xuống dòng.
    """

    def __init__(
        self,
        debounce_seconds: float = 1.75,
        on_flush: Optional[Callable[[ChatQueueItem], Coroutine[Any, Any, None]]] = None,
    ):
        self.debounce_seconds = debounce_seconds
        self.on_flush = on_flush
        self._buffers: Dict[Tuple[str, str], List[LarkMessage]] = {}
        self._timers: Dict[Tuple[str, str], asyncio.TimerHandle] = {}
        self._lock = asyncio.Lock()

    async def push(
        self,
        msg: LarkMessage,
        user_name: str,
        responder_name: Optional[str] = None,
        role: Optional[str] = None,
    ) -> None:
        """Đưa tin nhắn mới vào bộ đệm và thiết lập lại timer debounce."""
        key = (msg.chat_id, msg.sender_id)

        async with self._lock:
            # Hủy timer cũ nếu còn đang đếm
            old_timer = self._timers.get(key)
            if old_timer and not old_timer.cancelled():
                old_timer.cancel()

            # Thêm tin nhắn vào danh sách đệm
            if key not in self._buffers:
                self._buffers[key] = []
            self._buffers[key].append(msg)

            # Đặt timer mới
            loop = asyncio.get_running_loop()
            self._timers[key] = loop.call_later(
                self.debounce_seconds,
                lambda k=key, un=user_name, rn=responder_name, r=role: asyncio.create_task(
                    self._flush(k, un, rn, r)
                ),
            )

    async def _flush(
        self,
        key: Tuple[str, str],
        user_name: str,
        responder_name: Optional[str],
        role: Optional[str],
    ) -> None:
        """Kích hoạt khi hết thời gian debounce: Gom tin và đẩy ra ngoài."""
        async with self._lock:
            messages = self._buffers.pop(key, [])
            self._timers.pop(key, None)

        if not messages:
            return

        chat_id, sender_id = key
        # Gom nội dung text từ các tin nhắn
        valid_texts = [m.text.strip() for m in messages if m.text and m.text.strip()]
        combined_text = "\n".join(valid_texts)

        if not combined_text:
            return

        last_msg = messages[-1]
        all_ids = [m.message_id for m in messages if m.message_id]

        if len(messages) > 1:
            print(f"🧩 [DEBOUNCE] Đã gom {len(messages)} tin nhắn từ '{user_name}' ({sender_id}) trong {self.debounce_seconds}s:\n\"{combined_text}\"")

        item = ChatQueueItem(
            chat_id=chat_id,
            sender_id=sender_id,
            combined_text=combined_text,
            anchor_message_id=last_msg.message_id,
            chat_type=last_msg.chat_type,
            user_name=user_name,
            responder_name=responder_name,
            is_owner=last_msg.is_self,
            role=role,
            tenant_key=getattr(last_msg, "tenant_key", None),
            message_ids=all_ids,
        )

        if self.on_flush:
            await self.on_flush(item)


class ThrottledChatQueue:
    """
    Hàng đợi điều phối tốc độ xử lý tin nhắn:
      - Quản lý giãn cách (cooldown) theo từng user để tránh chạm quota 429.
      - Giới hạn tải song song qua Concurrency Semaphore.
      - Hoàn toàn im lặng (Silent Throttling), không gửi tin nhắn cảnh báo rác vào nhóm.
    """

    def __init__(
        self,
        cooldown_seconds: float = 4.0,
        max_concurrent: int = 3,
        max_size: int = 100,
        enqueue_timeout: float = 2.0,
        pipeline_executor: Optional[Callable[[ChatQueueItem], Coroutine[Any, Any, None]]] = None,
    ):
        self.cooldown_seconds = cooldown_seconds
        self.max_size = max_size
        self.enqueue_timeout = enqueue_timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.pipeline_executor = pipeline_executor
        self._queue: asyncio.Queue[ChatQueueItem] = asyncio.Queue(maxsize=max_size)
        self._last_user_processed: Dict[str, float] = {}
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Khởi động worker ngầm xử lý hàng đợi."""
        if self._running and self._worker_task and not self._worker_task.done():
            return
        self._running = True
        try:
            target_loop = loop or asyncio.get_running_loop()
            self._worker_task = target_loop.create_task(self._worker_loop(), name="ThrottledChatQueueWorker")
            logger.info("🚀 ThrottledChatQueue Worker đã khởi động.")
        except RuntimeError:
            # Chưa có loop chạy ở thread hiện tại, sẽ lazy-start khi enqueue
            pass

    def stop(self) -> None:
        """Dừng worker an toàn."""
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
        logger.info("🛑 ThrottledChatQueue Worker đã dừng.")

    async def enqueue(self, item: ChatQueueItem) -> bool:
        """
        Đưa một mục chat đã gom vào hàng đợi:
          - Nếu queue đầy, chờ tối đa enqueue_timeout giây (mặc định 2.0s).
          - Quá thời gian mà queue vẫn đầy: ghi log lỗi rõ ràng, bỏ qua tin mới.
          - Tạm thời giữ nguyên toàn bộ tin cũ trong queue (chưa tự động xóa).
          - Trả về True nếu xếp hàng thành công, False nếu timeout/lỗi.
        """
        if not self._worker_task or self._worker_task.done():
            self.start()

        try:
            await asyncio.wait_for(self._queue.put(item), timeout=self.enqueue_timeout)
            return True
        except asyncio.TimeoutError:
            err_msg = (
                f"❌ [QUEUE OVERFLOW] Hàng đợi Layer 1 đã đầy ({self._queue.qsize()}/{self.max_size}). "
                f"Đã chờ {self.enqueue_timeout}s nhưng không có chỗ trống! "
                f"Bỏ qua tin nhắn mới của '{item.user_name}' ({item.sender_id}) trong chat '{item.chat_id}' "
                f"(Anchor MsgID: {item.anchor_message_id}, Nội dung: \"{item.combined_text[:60]}...\"). "
                f"Tạm thời giữ nguyên các tin cũ trong hàng đợi."
            )
            print(f"\n{err_msg}")
            logger.error(err_msg)
            return False
        except Exception as e:
            err_msg = f"❌ [QUEUE ERROR] Lỗi không xác định khi đưa tin vào hàng đợi: {e}"
            print(f"\n{err_msg}")
            logger.error(err_msg, exc_info=True)
            return False

    async def _worker_loop(self) -> None:
        """Vòng lặp tiêu thụ tin nhắn trong hàng đợi."""
        while self._running:
            try:
                item = await self._queue.get()
            except asyncio.CancelledError:
                break

            now = time.time()
            last_time = self._last_user_processed.get(item.sender_id, 0.0)
            elapsed = now - last_time

            # Nếu user này vừa được trả lời cách đây ít hơn cooldown_seconds:
            # Tự động chờ bù thời gian (Silent Throttling)
            if elapsed < self.cooldown_seconds and not item.is_owner:
                delay = self.cooldown_seconds - elapsed
                print(f"⏳ [QUEUE COOLDOWN] Giãn cách {delay:.1f}s cho user '{item.user_name}' ({item.sender_id})...")
                await asyncio.sleep(delay)

            # Cập nhật mốc thời gian xử lý của user
            self._last_user_processed[item.sender_id] = time.time()

            # Chạy pipeline độc lập có Semaphore bảo vệ
            asyncio.create_task(self._process_with_semaphore(item))
            self._queue.task_done()

    async def _process_with_semaphore(self, item: ChatQueueItem) -> None:
        """Thực thi pipeline được giới hạn đồng thời bởi Semaphore."""
        async with self.semaphore:
            if self.pipeline_executor:
                try:
                    await self.pipeline_executor(item)
                except Exception as e:
                    logger.error(
                        f"Lỗi thực thi pipeline trong queue cho msg {item.anchor_message_id}: {e}",
                        exc_info=True,
                    )


class ChatQueueService:
    """Dịch vụ tích hợp kết hợp cả Debouncer và ThrottledQueue."""

    def __init__(self):
        self.debouncer = MessageDebouncer(
            debounce_seconds=getattr(settings, "DEBOUNCE_DELAY_SECONDS", 1.75),
            on_flush=self._on_debounced_ready,
        )
        self.queue = ThrottledChatQueue(
            cooldown_seconds=getattr(settings, "USER_COOLDOWN_SECONDS", 4.0),
            max_concurrent=getattr(settings, "MAX_CONCURRENT_CHAT_PIPELINES", 3),
            max_size=getattr(settings, "CHAT_QUEUE_MAX_SIZE", 100),
            enqueue_timeout=getattr(settings, "CHAT_QUEUE_ENQUEUE_TIMEOUT", 2.0),
            pipeline_executor=self._execute_pipeline,
        )

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Khởi động dịch vụ hàng đợi."""
        self.queue.start(loop=loop)

    def stop(self) -> None:
        """Dừng dịch vụ hàng đợi."""
        self.queue.stop()

    async def push_incoming_message(
        self,
        msg: LarkMessage,
        user_name: str,
        responder_name: Optional[str] = None,
        role: Optional[str] = None,
    ) -> None:
        """Điểm tiếp nhận tin nhắn từ bot_service."""
        await self.debouncer.push(msg, user_name, responder_name, role)

    async def _on_debounced_ready(self, item: ChatQueueItem) -> None:
        """Callback khi debouncer gom tin xong -> đẩy vào hàng đợi."""
        enqueued = await self.queue.enqueue(item)
        if not enqueued:
            logger.warning(
                f"⚠️ [CHAT QUEUE DROP] Không thể xếp hàng tin nhắn từ '{item.user_name}' "
                f"sau {self.queue.enqueue_timeout}s chờ đợi do hàng đợi đầy."
            )

    async def _execute_pipeline(self, item: ChatQueueItem) -> None:
        """Thực thi pipeline trò chuyện chuẩn của HiLark."""
        from services.workflows.chat_workflow import process_chat_pipeline

        print(f"\n⚙️ [QUEUE DISPATCH] Bắt đầu xử lý pipeline cho '{item.user_name}': \"{item.combined_text}\"")

        try:
            async with async_tenant_context(item.tenant_key):
                result = await process_chat_pipeline(
                    query=item.combined_text,
                    sender=item.sender_id,
                    channel=f"lark_{item.chat_type}",
                    message_id=item.anchor_message_id,
                    chat_id=item.chat_id,
                    reply_to_lark=not item.is_owner,
                    user_name=item.user_name,
                    responder_name=item.responder_name,
                    role=item.role,
                    is_owner=item.is_owner,
                    tenant_key=item.tenant_key,
                )

            jev_action = result.get("jev_action", "IGNORE")
            confidence = result.get("jev_confidence", 0.0)
            status = result.get("status", "")
            print(f"🎯 Phân loại JEV  : {jev_action} (Độ tin cậy: {confidence:.2f}) | Trạng thái: {status}")

            if status == "forbidden_query":
                chk = result.get("forbidden_check") or {}
                matched = chk.get("matched_label") or "Chủ đề bị cấm"
                print(f"🚫 [FORBIDDEN DROP] Câu hỏi vi phạm nhãn cấm '{matched}'. Kích hoạt Zero-response (Im lặng tuyệt đối).")
            elif status == "group_inactive":
                print(f"🛑 [GROUP INACTIVE] Nhóm chat tạm dừng hoạt động. Bỏ qua tin nhắn.")
            elif jev_action == "IGNORE":
                print(f"🔇 [IGNORE] Tin rác/chào hỏi không quan trọng. Không lưu, không trả lời.")
            elif jev_action == "MEMORY_ONLY":
                ext = result.get("extraction") or {}
                print(f"💾 [MEMORY_ONLY] Đã âm thầm trích xuất & lưu vào MongoDB ({len(ext.get('facts', []))} facts).")
            elif jev_action in ("DRAFT_PENDING_APPROVAL", "MEMORY_AND_DRAFT"):
                draft_ans = result.get("draft_answer") or result.get("answer", "")
                print(f"📝 [{jev_action}] SOẠN NHÁP CHỜ DUYỆT:")
                print(f"   • Bản nháp: \"{draft_ans[:150]}{'...' if len(draft_ans) > 150 else ''}\"")
                print(f"   (Đã gửi thông báo riêng tới DM của chủ nhân, KHÔNG phát ngôn vào nhóm)")
            elif jev_action == "REPLY_ONLY":
                answer = result.get("answer", "")
                print(f"💬 [TRẢ LỜI] Câu trả lời đã tạo ({len(answer)} ký tự):")
                print(f"   \"{answer[:150]}{'...' if len(answer) > 150 else ''}\"")
                lark_res = result.get("lark_response") or {}
                if lark_res.get("success"):
                    print(f"✔ ĐÃ GỬI PHẢN HỒI THÀNH CÔNG NHÂN DANH {(item.responder_name or 'User').upper()}!")
                else:
                    print(f"⚠️ Trạng thái gửi reply Lark: {lark_res}")
        except Exception as e:
            logger.error(f"Lỗi khi thực thi pipeline từ Queue: {e}", exc_info=True)


chat_queue_service = ChatQueueService()
