"""
Transitional Facade Shim for ChatQueueService & Debouncer
=========================================================
Vị trí: server/utils/chat_queue.py (Deprecated - Vui lòng import từ services.workflows.chat_queue)
"""

from __future__ import annotations

from services.workflows.chat_queue import (  # noqa: F401
    ChatQueueService,
    chat_queue_service,
    MessageDebouncer,
    ThrottledChatQueue,
)
import services.workflows.chat_queue as _q_mod
from services.workflows.chat_queue import *  # noqa: F401, F403

__all__ = [name for name in dir(_q_mod) if not name.startswith("_")]
