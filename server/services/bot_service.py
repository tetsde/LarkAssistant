"""
Transitional Facade Shim for BotService
=======================================
Vị trí: server/services/bot_service.py (Deprecated - Vui lòng import từ services.lark.bot_runner)
"""

from __future__ import annotations

from services.lark.bot_runner import (  # noqa: F401
    handle_lark_incoming_message,
    start_bot_service,
    stop_bot_service,
    start_digest_scheduler_daemon,
    run_standalone_bot,
    lark_service,
    doc_parser_service,
    process_document_to_claims,
    process_chat_pipeline,
    digest_service,
    draft_service,
    lark_base_service,
    scope_service,
    handle_document_or_links,
    handle_owner_dm_command,
    handle_member_message,
)
import services.lark.bot_runner as _bot_mod
from services.lark.bot_runner import *  # noqa: F401, F403

__all__ = [name for name in dir(_bot_mod) if not name.startswith("_")]
