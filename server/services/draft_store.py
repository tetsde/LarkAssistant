"""MongoDB persistence for Lark reply drafts awaiting approval."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pymongo import ReturnDocument

from database.db import get_draft_logs_collection
from models.memory import get_vietnam_now_iso


@dataclass
class PendingDraft:
    owner_id: str
    message_id: str
    chat_id: str
    query: str
    draft_answer: str
    user_name: str
    responder_name: Optional[str] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "pending"
    approved_content: Optional[str] = None
    last_error: Optional[str] = None
    created_at: str = field(default_factory=get_vietnam_now_iso)
    updated_at: str = field(default_factory=get_vietnam_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "owner_id": self.owner_id,
            "message_id": self.message_id,
            "chat_id": self.chat_id,
            "query": self.query,
            "draft_answer": self.draft_answer,
            "user_name": self.user_name,
            "responder_name": self.responder_name,
            "status": self.status,
            "approved_content": self.approved_content,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_document(cls, document: Dict[str, Any]) -> PendingDraft:
        return cls(
            id=document.get("id") or str(document.get("_id", uuid.uuid4().hex)),
            owner_id=document["owner_id"],
            message_id=document.get("message_id", ""),
            chat_id=document.get("chat_id", ""),
            query=document.get("query", ""),
            draft_answer=document.get("draft_answer", ""),
            user_name=document.get("user_name", "bạn"),
            responder_name=document.get("responder_name"),
            status=document.get("status", "pending"),
            approved_content=document.get("approved_content"),
            last_error=document.get("last_error"),
            created_at=document.get("created_at") or get_vietnam_now_iso(),
            updated_at=document.get("updated_at") or get_vietnam_now_iso(),
        )


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
