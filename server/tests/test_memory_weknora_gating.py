import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.chat import MemoryRequest
from routers.chat import add_memory, process_chat_pipeline


class TestMemoryWeKnoraGating(unittest.IsolatedAsyncioTestCase):
    async def test_memory_and_draft_persists_memory_and_never_replies_directly(self):
        with (
            patch("routers.chat.jev_service.classify_message", new_callable=AsyncMock) as classify,
            patch("routers.chat.process_memory_extraction", new_callable=AsyncMock) as extract_memory,
            patch("routers.chat.get_mongo_facts", new_callable=AsyncMock) as get_facts,
            patch("routers.chat.weknora_service.retrieve", new_callable=AsyncMock) as retrieve,
            patch("routers.chat.ContextComposer") as composer_type,
            patch("routers.chat.generate_grounded_answer", new_callable=AsyncMock) as generate_answer,
            patch("routers.chat.draft_store.create", new_callable=AsyncMock) as create_draft,
            patch("routers.chat.lark_service.get_current_user") as get_current_user,
            patch("routers.chat.lark_service.send_bot_dm_to_owner", new_callable=AsyncMock) as send_draft,
            patch("routers.chat.lark_service.areply_text", new_callable=AsyncMock) as direct_reply,
            patch("routers.chat.weknora_service.save_to_kb", new_callable=AsyncMock) as save_raw_to_kb,
        ):
            classify.return_value = {"action": "MEMORY_AND_DRAFT", "confidence": 0.95}
            extract_memory.return_value = {"facts": [{"id": "fact-1"}]}
            get_facts.return_value = []
            retrieve.return_value = []
            composer_type.return_value.compose.return_value = {"context_text": "facts context"}
            generate_answer.return_value = "Draft answer"
            get_current_user.return_value = {"open_id": "owner-1"}

            result = await process_chat_pipeline(
                query="Cập nhật deadline dự án ngay nhé",
                sender="sender-1",
                chat_id="chat-1",
                message_id="message-1",
                reply_to_lark=True,
                user_name="Member",
                responder_name="Owner",
                role="Project lead",
            )

        self.assertEqual(result["jev_action"], "MEMORY_AND_DRAFT")
        self.assertEqual(result["status"], "memory_and_draft_pending_approval")
        self.assertEqual(result["extraction"]["facts"][0]["id"], "fact-1")
        create_draft.assert_awaited_once()
        send_draft.assert_awaited_once()
        direct_reply.assert_not_awaited()
        save_raw_to_kb.assert_not_awaited()

    @patch("routers.chat.weknora_service.save_to_kb", new_callable=AsyncMock)
    @patch("routers.chat.process_memory_extraction", new_callable=AsyncMock)
    @patch("routers.chat.jev_service.classify_message", new_callable=AsyncMock)
    async def test_memory_only_chat_does_not_upload_raw_message(
        self,
        classify_message,
        process_memory_extraction,
        save_to_kb,
    ):
        classify_message.return_value = {"action": "MEMORY_ONLY", "confidence": 1.0}
        process_memory_extraction.return_value = {"saved_to_mongodb": True}

        result = await process_chat_pipeline(query="Cập nhật deadline dự án")

        self.assertEqual(result["status"], "memorized")
        process_memory_extraction.assert_awaited_once()
        save_to_kb.assert_not_awaited()

    @patch("routers.chat.weknora_service.save_to_kb", new_callable=AsyncMock)
    @patch("routers.chat.save_extraction_to_mongo", new_callable=AsyncMock)
    @patch("routers.chat.extract_async", new_callable=AsyncMock)
    @patch("routers.chat.get_mongo_facts", new_callable=AsyncMock)
    @patch("routers.chat.get_mongo_entities", new_callable=AsyncMock)
    async def test_manual_memory_endpoint_only_persists_to_mongodb(
        self,
        get_entities,
        get_facts,
        extract,
        save_to_mongo,
        save_to_kb,
    ):
        get_entities.return_value = []
        get_facts.return_value = []
        extract.return_value = {"entities": [], "facts": []}
        save_to_mongo.return_value = {"entities": [], "facts": []}

        result = await add_memory(MemoryRequest(text="Cập nhật deadline dự án"))

        self.assertTrue(result["saved_to_mongodb"])
        self.assertNotIn("weknora_data", result)
        save_to_mongo.assert_awaited_once()
        save_to_kb.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()