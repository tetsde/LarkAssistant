"""MongoDB persistence for Lark reply drafts awaiting approval."""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pymongo import ReturnDocument

from database.db import get_draft_logs_collection as default_get_collection
from database.scoped_query import inject_tenant_filter, get_current_tenant_key
from models.chat import PendingDraft
from models.memory import get_vietnam_now_iso


def _get_collection():
    shim = sys.modules.get("services.draft_service") or sys.modules.get("services.draft_store")
    if shim and hasattr(shim, "get_draft_logs_collection"):
        return shim.get_draft_logs_collection()
    return default_get_collection()


class DraftStore:
    """Read and update draft approval state in MongoDB with tenant isolation."""

    async def create(self, draft: PendingDraft) -> PendingDraft:
        if not draft.tenant_key:
            draft.tenant_key = get_current_tenant_key()
        await _get_collection().insert_one(draft.to_dict())
        return draft

    async def get_latest_pending(
        self,
        owner_id: str,
        tenant_key: Optional[str] = None,
    ) -> Optional[PendingDraft]:
        eff_tenant = tenant_key or get_current_tenant_key()
        query = inject_tenant_filter({"owner_id": owner_id, "status": "pending"}, eff_tenant)
        document = await _get_collection().find_one(
            query,
            sort=[("created_at", -1)],
        )
        return PendingDraft.from_document(document) if document else None

    async def claim_draft(
        self,
        owner_id: str,
        draft_id: Optional[str] = None,
        tenant_key: Optional[str] = None,
    ) -> Optional[PendingDraft]:
        eff_tenant = tenant_key or get_current_tenant_key()
        filters: Dict[str, Any] = {"status": "pending"}
        if draft_id:
            filters["$or"] = [{"id": draft_id}, {"message_id": draft_id}]
        else:
            filters["owner_id"] = owner_id
        query = inject_tenant_filter(filters, eff_tenant)
        document = await _get_collection().find_one_and_update(
            query,
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

    async def claim_latest_pending(
        self,
        owner_id: str,
        tenant_key: Optional[str] = None,
    ) -> Optional[PendingDraft]:
        eff_tenant = tenant_key or get_current_tenant_key()
        query = inject_tenant_filter({"owner_id": owner_id, "status": "pending"}, eff_tenant)
        document = await _get_collection().find_one_and_update(
            query,
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
        result = await _get_collection().update_one(
            {"id": draft_id, "status": "sending"},
            {"$set": updates},
        )
        return result.modified_count == 1

    async def mark_sent(
        self,
        draft_id: str,
        content: str,
        bot_reply_message_id: Optional[str] = None,
    ) -> bool:
        now = get_vietnam_now_iso()
        update_fields: Dict[str, Any] = {
            "status": "sent",
            "approved_content": content,
            "sent_at": now,
            "updated_at": now,
            "last_error": None,
        }
        if bot_reply_message_id:
            update_fields["bot_reply_message_id"] = bot_reply_message_id
        result = await _get_collection().update_one(
            {"id": draft_id, "status": "sending"},
            {"$set": update_fields},
        )
        return result.modified_count == 1

    async def discard_latest_pending(
        self,
        owner_id: str,
        tenant_key: Optional[str] = None,
    ) -> Optional[PendingDraft]:
        eff_tenant = tenant_key or get_current_tenant_key()
        query = inject_tenant_filter({"owner_id": owner_id, "status": "pending"}, eff_tenant)
        document = await _get_collection().find_one_and_update(
            query,
            {"$set": {"status": "discarded", "updated_at": get_vietnam_now_iso()}},
            sort=[("created_at", -1)],
            return_document=ReturnDocument.AFTER,
        )
        return PendingDraft.from_document(document) if document else None

    async def update_draft_content(self, draft_id: str, new_draft_answer: str) -> bool:
        """Cập nhật nội dung bản nháp đang ở trạng thái pending."""
        result = await _get_collection().update_one(
            {"id": draft_id, "status": "pending"},
            {
                "$set": {
                    "draft_answer": new_draft_answer,
                    "updated_at": get_vietnam_now_iso(),
                }
            },
        )
        return result.modified_count == 1


draft_store = DraftStore()

__all__ = ["PendingDraft", "DraftStore", "draft_store"]
