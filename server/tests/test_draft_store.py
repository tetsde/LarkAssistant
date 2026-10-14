import unittest
from unittest.mock import AsyncMock, patch

from pymongo import ReturnDocument

from services.draft_service import DraftService
from services.draft_store import DraftStore, PendingDraft


def draft_document(**overrides):
    document = {
        "id": "draft-1",
        "owner_id": "owner-1",
        "message_id": "message-1",
        "chat_id": "chat-1",
        "query": "Question?",
        "draft_answer": "Draft answer",
        "user_name": "Member",
        "responder_name": "Responder",
        "status": "sending",
        "approved_content": None,
        "last_error": None,
        "created_at": "2026-10-14T10:00:00+07:00",
        "updated_at": "2026-10-14T10:00:00+07:00",
    }
    document.update(overrides)
    return document


class TestDraftStore(unittest.IsolatedAsyncioTestCase):
    @patch("services.draft_store.get_draft_logs_collection")
    async def test_create_persists_pending_draft(self, get_collection):
        collection = AsyncMock()
        get_collection.return_value = collection
        draft = PendingDraft(
            owner_id="owner-1",
            message_id="message-1",
            chat_id="chat-1",
            query="Question?",
            draft_answer="Draft answer",
            user_name="Member",
        )

        saved = await DraftStore().create(draft)

        self.assertEqual(saved.status, "pending")
        collection.insert_one.assert_awaited_once_with(draft.to_dict())

    @patch("services.draft_store.get_draft_logs_collection")
    async def test_claim_latest_pending_sets_sending_atomically(self, get_collection):
        collection = AsyncMock()
        collection.find_one_and_update.return_value = draft_document()
        get_collection.return_value = collection

        draft = await DraftStore().claim_latest_pending("owner-1")

        self.assertIsNotNone(draft)
        self.assertEqual(draft.status, "sending")
        query, update = collection.find_one_and_update.call_args.args[:2]
        self.assertEqual(query, {"owner_id": "owner-1", "status": "pending"})
        self.assertEqual(update["$set"]["status"], "sending")
        self.assertEqual(collection.find_one_and_update.call_args.kwargs["return_document"], ReturnDocument.AFTER)

    @patch("services.draft_store.get_draft_logs_collection")
    async def test_mark_pending_records_failure_and_content(self, get_collection):
        collection = AsyncMock()
        collection.update_one.return_value.modified_count = 1
        get_collection.return_value = collection

        updated = await DraftStore().mark_pending("draft-1", "Lark unavailable", "Edited text")

        self.assertTrue(updated)
        query, update = collection.update_one.call_args.args
        self.assertEqual(query, {"id": "draft-1", "status": "sending"})
        self.assertEqual(update["$set"]["status"], "pending")
        self.assertEqual(update["$set"]["approved_content"], "Edited text")
        self.assertEqual(update["$set"]["last_error"], "Lark unavailable")

    @patch("services.draft_store.get_draft_logs_collection")
    async def test_mark_sent_persists_only_after_confirmation(self, get_collection):
        collection = AsyncMock()
        collection.update_one.return_value.modified_count = 1
        get_collection.return_value = collection

        updated = await DraftStore().mark_sent("draft-1", "Approved answer")

        self.assertTrue(updated)
        query, update = collection.update_one.call_args.args
        self.assertEqual(query, {"id": "draft-1", "status": "sending"})
        self.assertEqual(update["$set"]["status"], "sent")
        self.assertEqual(update["$set"]["approved_content"], "Approved answer")


class TestDraftService(unittest.IsolatedAsyncioTestCase):
    @patch("services.draft_service.lark_service")
    @patch("services.draft_service.draft_store")
    async def test_failed_lark_send_returns_draft_to_pending(self, store, lark):
        store.claim_latest_pending = AsyncMock(return_value=PendingDraft(
            owner_id="owner-1",
            message_id="message-1",
            chat_id="chat-1",
            query="Question?",
            draft_answer="Draft answer",
            user_name="Member",
            id="draft-1",
            status="sending",
        ))
        store.mark_pending = AsyncMock(return_value=True)
        lark.areply_text = AsyncMock(return_value={"success": False, "msg": "temporary failure"})
        service = DraftService()

        success, detail, _, _ = await service.send_latest("owner-1")

        self.assertFalse(success)
        self.assertEqual(detail, "temporary failure")
        store.mark_pending.assert_awaited_once_with("draft-1", "temporary failure", "Draft answer")
        store.mark_sent.assert_not_called()

    @patch("services.draft_service.lark_service")
    @patch("services.draft_service.draft_store")
    async def test_no_success_report_when_mongo_does_not_mark_sent(self, store, lark):
        store.claim_latest_pending = AsyncMock(return_value=PendingDraft(
            owner_id="owner-1",
            message_id="message-1",
            chat_id="chat-1",
            query="Question?",
            draft_answer="Draft answer",
            user_name="Member",
            id="draft-1",
            status="sending",
        ))
        store.mark_sent = AsyncMock(return_value=False)
        lark.areply_text = AsyncMock(return_value={"success": True})
        service = DraftService()

        success, detail, _, _ = await service.send_latest("owner-1")

        self.assertFalse(success)
        self.assertIn("không lưu được trạng thái sent", detail)
        store.mark_pending.assert_not_called()