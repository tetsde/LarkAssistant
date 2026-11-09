"""
Transitional Facade Shim for DigestService
==========================================
Vị trí: server/services/digest_service.py (Deprecated - Vui lòng import từ services.workflows.digest_workflow)
"""

from __future__ import annotations

from database.db import (  # noqa: F401
    get_staging_collection,
    get_daily_digests_collection,
    get_master_daily_digests_collection,
)
from services.knowledge.weknora_client import weknora_service  # noqa: F401
from services.ai.llm_client import llm_client  # noqa: F401
from services.workflows.digest_workflow import (  # noqa: F401
    CommitmentItem,
    DailyDigestRecord,
    DecisionItem,
    DigestService,
    MasterDailyDigestRecord,
    SourceReference,
    StagingMessage,
    StatusCategory,
    StatusChangeItem,
    digest_service,
)
import services.workflows.digest_workflow as _digest_mod
from services.workflows.digest_workflow import *  # noqa: F401, F403

__all__ = [name for name in dir(_digest_mod) if not name.startswith("_")]
