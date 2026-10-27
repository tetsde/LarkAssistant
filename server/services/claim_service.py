"""
Unified Claim Service Module
============================
Vị trí: server/services/claim_service.py

Gom nhóm toàn bộ các dịch vụ quản lý và phê duyệt thông tin đề xuất (Claims / Facts):
  - Workflow: ClaimService, claim_service
  - Card builder helper
"""

from __future__ import annotations

from services.lark import lark_service  # noqa: F401
from services.workflows.claim_workflow import (  # noqa: F401
    ClaimService,
    claim_service,
)
import services.workflows.claim_workflow as _claim_mod
from services.workflows.claim_workflow import *  # noqa: F401, F403

__all__ = [
    "ClaimService",
    "claim_service",
    "lark_service",
]
