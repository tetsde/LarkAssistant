"""Approval and Lark delivery operations for persisted reply drafts."""

from typing import Any, Dict, Optional, Tuple

import logging

from services.draft_store import PendingDraft, draft_store
from services.lark import lark_service

logger = logging.getLogger(__name__)


class DraftService:
    def __init__(self):
        self.store = draft_store

    async def send_latest(
        self,
        owner_id: str,
        approved_content: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[PendingDraft], Optional[Dict[str, Any]]]:
        draft = await self.store.claim_latest_pending(owner_id)
        if not draft:
            return False, "Không có bản nháp nào đang chờ duyệt.", None, None
        content = approved_content or draft.approved_content or draft.draft_answer
        return await self._send_claimed(draft, content)

    async def send_by_message_id(
        self,
        message_id: str,
        content: str,
    ) -> Tuple[bool, str, Optional[PendingDraft], Optional[Dict[str, Any]]]:
        draft = await self.store.claim_by_message_id(message_id)
        if not draft:
            return False, "Không tìm thấy draft đang chờ cho message_id này.", None, None
        return await self._send_claimed(draft, content)

    async def discard_latest(self, owner_id: str) -> Optional[PendingDraft]:
        return await self.store.discard_latest_pending(owner_id)

    async def discard_by_message_id(self, message_id: str) -> Optional[PendingDraft]:
        return await self.store.discard_by_message_id(message_id)

    async def _send_claimed(
        self,
        draft: PendingDraft,
        content: str,
    ) -> Tuple[bool, str, PendingDraft, Optional[Dict[str, Any]]]:
        try:
            response = await lark_service.areply_text(
                message_id=draft.message_id,
                text=content,
                as_user=True,
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