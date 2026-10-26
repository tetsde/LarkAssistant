"""
Transitional Facade Shim for ScopeService
=========================================
Vị trí: server/services/scope_service.py (Deprecated - Vui lòng import từ services.knowledge)

Module này re-export toàn bộ interface từ `services.knowledge.chat_scopes` để bảo đảm 100%
khả năng tương thích ngược cho các file routers, tests và utils hiện hành.
"""

from __future__ import annotations

import sys
from database.db import get_chat_scopes_collection
from services.weknora import weknora_service

from services.knowledge.chat_scopes import (
    ScopeService,
    scope_service,
    ChatScopeRecord,
    BASE_FIELD_MAP,
    _get_base_field,
    _sanitize_filename,
    _extract_document_items,
)

__all__ = [
    "ScopeService",
    "scope_service",
    "ChatScopeRecord",
    "BASE_FIELD_MAP",
    "get_chat_scopes_collection",
    "weknora_service",
    "_get_base_field",
    "_sanitize_filename",
    "_extract_document_items",
]
