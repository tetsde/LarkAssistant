"""
HiLark - Dedicated Token Event Loop
===================================
Vị trí: server/core/token_loop.py

Lý do tồn tại: các service sync (bitable, client) phải gọi hàm async để lấy token.
Trước đây mỗi lần gọi chúng dùng `asyncio.run(...)`, tạo event loop mới rồi đóng lại.
`asyncio.Lock` của token manager lại được tạo trên loop khác và dùng chung, nên khi
tranh chấp, `release()` ở loop này gọi `set_result()` trên Future của loop đã đóng —
bên chờ không bao giờ được đánh thức. Kết quả là treo vĩnh viễn, không exception,
không timeout.

Cách sửa: mọi thao tác token chạy trên **đúng một** event loop của process. Lock và
cache chỉ tồn tại trong loop đó, nên không còn đường tạo ra lỗi treo chéo loop.

API:
  - `submit(coro, timeout)`   : cho caller sync (không chạy trong event loop nào)
  - `asubmit(coro)`           : cho caller async ở bất kỳ loop nào
  - `stop()`                  : gọi khi process tắt

Lịch sử:
  - 2026-11-02: Giai đoạn 1 của kế hoạch sửa Tenant Resolution & Token Flow.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from typing import Any, Coroutine, Optional

logger = logging.getLogger("hilark.token_loop")

THREAD_NAME = "hilark-token-loop"

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()
    # Đóng các task còn nợ để không nuốt lỗi khi process thoát.
    try:
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    except RuntimeError:
        pass
    finally:
        loop.close()


def get_loop() -> asyncio.AbstractEventLoop:
    """Trả về token loop, khởi động thread lần đầu khi cần. An toàn khi gọi đa thread."""
    global _thread, _loop

    loop = _loop
    if loop is not None and not loop.is_closed():
        return loop

    with _lock:
        if _loop is not None and not _loop.is_closed():
            return _loop
        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=_run_loop,
            args=(loop,),
            name=THREAD_NAME,
            daemon=True,
        )
        _loop, _thread = loop, thread
        thread.start()
        logger.info("[TOKEN_LOOP] started thread=%s", THREAD_NAME)
        return loop


def on_token_loop() -> bool:
    """True nếu thread hiện tại chính là thread của token loop."""
    return threading.current_thread() is _thread


def is_async_caller() -> bool:
    """True nếu thread hiện tại đang chạy một event loop (phải dùng `asubmit`)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def submit(coro: Coroutine[Any, Any, Any], timeout: float = 15.0) -> Any:
    """
    Chạy coroutine trên token loop và chờ kết quả theo kiểu blocking.

    Chỉ dành cho caller **sync**. Nếu caller đang ở trong một event loop, blocking ở
    đây sẽ làm chết loop đó, nên ta raise để buộc dùng `asubmit`.

    Raises:
        RuntimeError: khi bị gọi từ trong event loop đang chạy.
        concurrent.futures.TimeoutError: khi quá `timeout`.
        Exception: lỗi phát sinh bên trong coroutine.
    """
    if on_token_loop():
        # Không thể chờ chính loop mình đang chạy.
        raise RuntimeError(
            "submit() không thể gọi từ trong token loop; dùng await trực tiếp."
        )
    if is_async_caller():
        raise RuntimeError(
            "submit() không thể gọi từ thread đang có event loop; dùng await asubmit(...)."
        )
    future = asyncio.run_coroutine_threadsafe(coro, get_loop())
    return future.result(timeout)


async def asubmit(coro: Coroutine[Any, Any, Any]) -> Any:
    """
    Chạy coroutine trên token loop từ bất kỳ loop async nào khác.

    Nếu đang chạy ngay trên token loop thì await trực tiếp để tránh tự chờ nhau.
    """
    if on_token_loop():
        return await coro
    loop = get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return await asyncio.wrap_future(future)


def stop(timeout: float = 5.0) -> None:
    """Dừng token loop khi process tắt. Idempotent."""
    global _thread, _loop

    with _lock:
        loop, thread = _loop, _thread
        _loop, _thread = None, None

    if loop is None or loop.is_closed():
        return
    loop.call_soon_threadsafe(loop.stop)
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=timeout)
    if not loop.is_closed():
        loop.close()
    logger.info("[TOKEN_LOOP] stopped")
