"""
Transitional Facade Shim for ChatService & Chat Pipeline
========================================================
Vị trí: server/services/chat_service.py (Deprecated - Vui lòng import từ services.workflows.chat_workflow)
"""

from __future__ import annotations

from services.workflows.chat_workflow import (  # noqa: F401
    ChatService,
    chat_service,
    process_chat_pipeline,
    process_document_to_claims,
    GLOBAL_LLM_SEMAPHORE,
    llm_client,
    weknora_service,
    jev_service,
    lark_service,
    scope_service,
)
import services.workflows.chat_workflow as _chat_mod
from services.workflows.chat_workflow import *  # noqa: F401, F403

__all__ = [name for name in dir(_chat_mod) if not name.startswith("_")]
