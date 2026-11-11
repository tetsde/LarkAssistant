"""
Unified Auth & Access Control Service Module
============================================
Vị trí: server/services/auth_service.py

Gom nhóm toàn bộ các dịch vụ xác thực, token và phân quyền truy cập:
  - Lark User Token Lifecycle (token_service, LarkTokenService) + sweeper giữ hạn token
    của từng tenant `ready` (start_tenant_token_sweeper).
  - Chat Scopes & Data Isolation Gatekeeper (scope_service, ScopeService, ChatScopeRecord)
"""

from __future__ import annotations

import httpx

from database.db import get_auth_collection, get_chat_scopes_collection
from services.auth.token_service import (
    VIETNAM_TZ,
    format_remaining_seconds,
    LarkTokenService,
    token_service,
)
from services.auth.tenant_refresh_sweeper import start_tenant_token_sweeper
from services.knowledge.chat_scopes import (
    ScopeService,
    scope_service,
    ChatScopeRecord,
    BASE_FIELD_MAP,
    _get_base_field,
    _sanitize_filename,
    _extract_document_items,
)
from services.knowledge.weknora_client import weknora_service

__all__ = [
    # Token / OAuth
    "VIETNAM_TZ",
    "format_remaining_seconds",
    "LarkTokenService",
    "token_service",
    "start_tenant_token_sweeper",
    "get_auth_collection",
    "httpx",
    # Scope / Permissions
    "ScopeService",
    "scope_service",
    "ChatScopeRecord",
    "BASE_FIELD_MAP",
    "get_chat_scopes_collection",
    "_get_base_field",
    "_sanitize_filename",
    "_extract_document_items",
    "weknora_service",
]
