"""MongoDB persistence for Lark reply drafts awaiting approval."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pymongo import ReturnDocument

from database.db import get_draft_logs_collection
from models.chat import PendingDraft
from models.memory import get_vietnam_now_iso


class DraftStore:
    """Read and update draft approval state in MongoDB."""

    async def create(self, draft: PendingDraft) -> PendingDraft:
        await get_draft_logs_collection().insert_one(draft.to_dict())
        return draft

    async def get_latest_pending(self, owner_id: str) -> Optional[PendingDraft]:
        document = await get_draft_logs_collection().find_one(
            {"owner_id": owner_id, "status": "pending"},
            sort=[("created_at", -1)],
        )
        return PendingDraft.from_document(document) if document else None

    async def claim_latest_pending(self, owner_id: str) -> Optional[PendingDraft]:
        document = await get_draft_logs_collection().find_one_and_update(
            {"owner_id": owner_id, "status": "pending"},
            {
                "$set": {
                    "status": "sending",
                    "updated_at": get_vietnam_now_iso(),
                    "last_error": None,
                }
            },
            sort=[("created_at", -1)],
            return_document=ReturnDocument.AFTER,
        )
        return PendingDraft.from_document(document) if document else None

    async def mark_pending(
        self,
        draft_id: str,
        error: str,
        approved_content: Optional[str] = None,
    ) -> bool:
        updates: Dict[str, Any] = {
            "status": "pending",
            "updated_at": get_vietnam_now_iso(),
            "last_error": error,
        }
        if approved_content is not None:
            updates["approved_content"] = approved_content
        result = await get_draft_logs_collection().update_one(
            {"id": draft_id, "status": "sending"},
            {"$set": updates},
        )
        return result.modified_count == 1

    async def mark_sent(self, draft_id: str, content: str) -> bool:
        now = get_vietnam_now_iso()
        result = await get_draft_logs_collection().update_one(
            {"id": draft_id, "status": "sending"},
            {
                "$set": {
                    "status": "sent",
                    "approved_content": content,
                    "sent_at": now,
                    "updated_at": now,
                    "last_error": None,
                }
            },
        )
        return result.modified_count == 1

    async def discard_latest_pending(self, owner_id: str) -> Optional[PendingDraft]:
        document = await get_draft_logs_collection().find_one_and_update(
            {"owner_id": owner_id, "status": "pending"},
            {"$set": {"status": "discarded", "updated_at": get_vietnam_now_iso()}},
            sort=[("created_at", -1)],
            return_document=ReturnDocument.AFTER,
        )
        return PendingDraft.from_document(document) if document else None


draft_store = DraftStore()

__all__ = ["PendingDraft", "DraftStore", "draft_store"]
