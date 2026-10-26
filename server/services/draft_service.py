"""
Unified Draft Service Module
============================
Vị trí: server/services/draft_service.py

Gom nhóm toàn bộ các dịch vụ quản lý bản nháp chờ duyệt:
  - MongoDB Draft Store (DraftStore, draft_store, PendingDraft, get_draft_logs_collection)
  - Approval & Execution Workflow (DraftService, draft_service)
"""

from __future__ import annotations

from database.db import get_draft_logs_collection  # noqa: F401
from services.lark import lark_service  # noqa: F401
from services.workflows.draft_store import (  # noqa: F401
    DraftStore,
    PendingDraft,
    draft_store,
)
from services.workflows.draft_workflow import (  # noqa: F401
    DraftService,
    draft_service,
)
import services.workflows.draft_workflow as _draft_mod
from services.workflows.draft_workflow import *  # noqa: F401, F403
import services.workflows.draft_store as _store_mod
from services.workflows.draft_store import *  # noqa: F401, F403

__all__ = [
    "DraftService",
    "draft_service",
    "DraftStore",
    "draft_store",
    "PendingDraft",
    "get_draft_logs_collection",
    "lark_service",
]