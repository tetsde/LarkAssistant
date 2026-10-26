"""
Transitional Facade Shim for ChatService & Chat Pipeline
========================================================
Vị trí: server/services/chat_service.py (Deprecated - Vui lòng import từ services.workflows.chat_workflow)
"""

from __future__ import annotations

from database import (  # noqa: F401
    get_all_entities as get_mongo_entities,
    get_all_facts as get_mongo_facts,
    save_extraction_to_mongo,
)
from services.workflows.chat_workflow import (  # noqa: F401
    ChatService,
    chat_service,
    process_chat_pipeline,
    process_document_to_claims,
    process_memory_extraction,
    generate_grounded_answer,
    GLOBAL_LLM_SEMAPHORE,
    ContextComposer,
    draft_store,
    jev_service,
    lark_service,
    weknora_service,
    rule_engine,
    scope_service,
    llm_client,
)
import services.workflows.chat_workflow as _chat_mod
from services.workflows.chat_workflow import *  # noqa: F401, F403

__all__ = [name for name in dir(_chat_mod) if not name.startswith("_")]
