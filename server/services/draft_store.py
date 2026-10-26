"""
Transitional Facade Shim for DraftStore
=======================================
Vị trí: server/services/draft_store.py (Deprecated - Vui lòng import từ services.workflows.draft_store)
"""

from __future__ import annotations

from database.db import get_draft_logs_collection  # noqa: F401
from services.workflows.draft_store import (  # noqa: F401
    DraftStore,
    PendingDraft,
    draft_store,
)
import services.workflows.draft_store as _store_mod
from services.workflows.draft_store import *  # noqa: F401, F403

__all__ = [name for name in dir(_store_mod) if not name.startswith("_")]
