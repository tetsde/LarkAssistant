"""
Transitional Facade Shim for DraftService
=========================================
Vị trí: server/services/draft_service.py (Deprecated - Vui lòng import từ services.workflows.draft_workflow)
"""

from __future__ import annotations

from services.workflows.draft_store import draft_store  # noqa: F401
from services.lark import lark_service  # noqa: F401
from services.workflows.draft_workflow import (  # noqa: F401
    DraftService,
    PendingDraft,
    draft_service,
)
import services.workflows.draft_workflow as _draft_mod
from services.workflows.draft_workflow import *  # noqa: F401, F403

__all__ = [name for name in dir(_draft_mod) if not name.startswith("_")]