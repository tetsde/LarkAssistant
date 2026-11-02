"""Approval and Lark delivery operations for persisted reply drafts."""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional, Tuple

from services.workflows.draft_store import PendingDraft, draft_store

logger = logging.getLogger(__name__)


def _get_draft_store():
    shim = sys.modules.get("services.draft_service")
    if shim and hasattr(shim, "draft_store"):
        return shim.draft_store
    return draft_store


def _get_lark_service():
    shim = sys.modules.get("services.draft_service")
    if shim and hasattr(shim, "lark_service"):
        return shim.lark_service
    from services.lark import lark_service
    from services.lark.runtime import get_current_lark_service
    return get_current_lark_service(lark_service)


class DraftService:
    def __init__(self, store=None):
        self.store = store or _get_draft_store()

    async def send_latest(
        self,
        owner_id: str,
        approved_content: Optional[str] = None,
        tenant_key: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[PendingDraft], Optional[Dict[str, Any]]]:
        # Tự động refresh store nếu đang bị mock patch
        self.store = _get_draft_store()
        draft = await self.store.claim_latest_pending(owner_id, tenant_key=tenant_key)
        if not draft:
            return False, "Không có bản nháp nào đang chờ duyệt.", None, None
        content = approved_content or draft.approved_content or draft.draft_answer
        return await self._send_claimed(draft, content)

    async def discard_latest(self, owner_id: str, tenant_key: Optional[str] = None) -> Optional[PendingDraft]:
        self.store = _get_draft_store()
        return await self.store.discard_latest_pending(owner_id, tenant_key=tenant_key)

    async def get_latest_pending(self, owner_id: str, tenant_key: Optional[str] = None) -> Optional[PendingDraft]:
        self.store = _get_draft_store()
        return await self.store.get_latest_pending(owner_id, tenant_key=tenant_key)

    async def update_content(self, draft_id: str, new_draft_answer: str) -> bool:
        self.store = _get_draft_store()
        return await self.store.update_draft_content(draft_id, new_draft_answer)

    async def _send_claimed(
        self,
        draft: PendingDraft,
        content: str,
    ) -> Tuple[bool, str, PendingDraft, Optional[Dict[str, Any]]]:
        lark = _get_lark_service()

        try:
            response = await lark.areply_text(
                message_id=draft.message_id,
                text=content,
                as_user=True,
                tenant_key=draft.tenant_key,  # ✅ FIX: truyền đúng tenant để lấy đúng token
            )
        except Exception as exc:
            error = await self._restore_pending(draft, str(exc), content)
            return False, error, draft, None

        if not isinstance(response, dict) or not response.get("success"):
            error = "Lark không xác nhận đã gửi tin nhắn."
            if isinstance(response, dict):
                error = response.get("msg") or response.get("error") or error
            state_error = await self._restore_pending(draft, error, content)
            return False, state_error, draft, response if isinstance(response, dict) else None

        if not await self.store.mark_sent(draft.id, content):
            return False, "Lark đã nhận tin nhưng không lưu được trạng thái sent vào MongoDB.", draft, response

        draft.status = "sent"
        draft.approved_content = content
        return True, "sent", draft, response

    async def _restore_pending(self, draft: PendingDraft, error: str, content: str) -> str:
        try:
            restored = await self.store.mark_pending(draft.id, error, content)
        except Exception as exc:
            logger.exception("Could not restore draft %s to pending", draft.id)
            return f"{error}; MongoDB cũng không lưu được trạng thái pending: {exc}"
        if not restored:
            return f"{error}; MongoDB không xác nhận trạng thái pending cho draft này."
        return error


draft_service = DraftService()

__all__ = ["DraftService", "draft_service"]
