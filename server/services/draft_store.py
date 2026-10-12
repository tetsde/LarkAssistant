"""
HiLark Pending Draft Store
==========================
Vị trí: server/services/draft_store.py

Mục đích:
    Lưu trữ và quản lý các bản nháp câu trả lời đang chờ duyệt (DRAFT_PENDING_APPROVAL)
    từ sếp/người dùng. Hỗ trợ tra cứu nhanh khi nhận lệnh trực tiếp từ Lark DM:
      - [Gửi] / [Sửa] / [Bỏ]
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class PendingDraft:
    message_id: str
    chat_id: str
    query: str
    draft_answer: str
    user_name: str
    responder_name: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "chat_id": self.chat_id,
            "query": self.query,
            "draft_answer": self.draft_answer,
            "user_name": self.user_name,
            "responder_name": self.responder_name,
            "created_at": self.created_at,
        }


class DraftStore:
    def __init__(self):
        # Lưu trữ bản nháp mới nhất theo owner_open_id
        self._owner_drafts: Dict[str, PendingDraft] = {}
        # Lưu trữ bản nháp theo message_id gốc
        self._message_drafts: Dict[str, PendingDraft] = {}

    def set_draft(self, owner_id: str, draft: PendingDraft) -> None:
        """Lưu bản nháp mới vào hàng đợi chờ duyệt."""
        self._owner_drafts[owner_id] = draft
        if draft.message_id:
            self._message_drafts[draft.message_id] = draft

    def get_latest_draft(self, owner_id: str) -> Optional[PendingDraft]:
        """Lấy bản nháp mới nhất của owner."""
        return self._owner_drafts.get(owner_id)

    def get_draft_by_message_id(self, message_id: str) -> Optional[PendingDraft]:
        """Lấy bản nháp theo message_id gốc."""
        return self._message_drafts.get(message_id)

    def pop_draft(self, owner_id: str) -> Optional[PendingDraft]:
        """Lấy và xóa bản nháp khỏi hàng đợi (khi đã Gửi hoặc Bỏ)."""
        draft = self._owner_drafts.pop(owner_id, None)
        if draft and draft.message_id in self._message_drafts:
            self._message_drafts.pop(draft.message_id, None)
        return draft

    def clear(self, owner_id: Optional[str] = None) -> None:
        """Xóa bản nháp."""
        if owner_id:
            self.pop_draft(owner_id)
        else:
            self._owner_drafts.clear()
            self._message_drafts.clear()

    def has_pending(self, owner_id: str) -> bool:
        """Kiểm tra xem owner có bản nháp nào đang chờ không."""
        return owner_id in self._owner_drafts


# Singleton instance
draft_store = DraftStore()

__all__ = ["PendingDraft", "DraftStore", "draft_store"]
