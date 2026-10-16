import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from routers.chat import process_chat_pipeline


class TestMemoryWeKnoraGating(unittest.IsolatedAsyncioTestCase):
    async def test_memory_and_draft_persists_memory_and_never_replies_directly(self):
        with (
            patch("services.chat_service.jev_service.classify_message", new_callable=AsyncMock) as classify,
            patch("services.chat_service.process_memory_extraction", new_callable=AsyncMock) as extract_memory,
            patch("services.chat_service.get_mongo_facts", new_callable=AsyncMock) as get_facts,
            patch("services.chat_service.weknora_service.retrieve", new_callable=AsyncMock) as retrieve,
            patch("services.chat_service.ContextComposer") as composer_type,
            patch("services.chat_service.generate_grounded_answer", new_callable=AsyncMock) as generate_answer,
            patch("services.chat_service.draft_store.create", new_callable=AsyncMock) as create_draft,
            patch("services.chat_service.lark_service.get_current_user") as get_current_user,
            patch("services.chat_service.lark_service.send_bot_dm_to_owner", new_callable=AsyncMock) as send_draft,
            patch("services.chat_service.lark_service.areply_text", new_callable=AsyncMock) as direct_reply,
            patch("services.chat_service.weknora_service.save_to_kb", new_callable=AsyncMock) as save_raw_to_kb,
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

    @patch("services.chat_service.weknora_service.save_to_kb", new_callable=AsyncMock)
    @patch("services.chat_service.process_memory_extraction", new_callable=AsyncMock)
    @patch("services.chat_service.jev_service.classify_message", new_callable=AsyncMock)
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

    @patch("services.chat_service.weknora_service.retrieve", new_callable=AsyncMock)
    @patch("services.chat_service.jev_service.classify_message", new_callable=AsyncMock)
    @patch("services.chat_service.scope_service.get_scope_by_chat_id", new_callable=AsyncMock)
    async def test_group_inactive_stops_pipeline(self, mock_get_scope, mock_classify, mock_retrieve):
        from models.chat_scope import ChatScopeRecord
        mock_get_scope.return_value = ChatScopeRecord(
            chat_id="oc_inactive_group",
            chat_name="Nhóm Lưu Trữ",
            dataset_id="kb_1",
            status="Tạm dừng",
        )

        result = await process_chat_pipeline(
            query="Dự án này làm đến đâu rồi?",
            chat_id="oc_inactive_group",
            sender="user-1",
        )

        self.assertEqual(result["status"], "group_inactive")
        mock_classify.assert_not_awaited()
        mock_retrieve.assert_not_awaited()

    @patch("services.chat_service.lark_service.send_bot_dm_to_owner", new_callable=AsyncMock)
    @patch("services.chat_service.generate_grounded_answer", new_callable=AsyncMock)
    @patch("services.chat_service.weknora_service.retrieve", new_callable=AsyncMock)
    @patch("services.chat_service.jev_service.check_forbidden_query", new_callable=AsyncMock)
    @patch("services.chat_service.scope_service.get_scope_by_chat_id", new_callable=AsyncMock)
    async def test_forbidden_query_zero_response(
        self,
        mock_get_scope,
        mock_check_forbidden,
        mock_retrieve,
        mock_generate_answer,
        mock_send_dm,
    ):
        from models.chat_scope import ChatScopeRecord
        mock_get_scope.return_value = ChatScopeRecord(
            chat_id="oc_active_group",
            chat_name="Nhóm Dự Án",
            dataset_id="kb_1",
            status="Hoạt động",
            forbidden_labels=["Ngân sách", "Chi phí", "Bảng lương"],
        )
        mock_check_forbidden.return_value = {
            "is_forbidden": True,
            "confidence": 0.95,
            "choice": "FORBIDDEN",
            "matched_label": "Ngân sách",
            "reason": "jev_classified",
        }

        result = await process_chat_pipeline(
            query="Ngân sách dự án này là bao nhiêu vậy?",
            chat_id="oc_active_group",
            sender="user-1",
            channel="lark_group",
        )

        self.assertEqual(result["status"], "forbidden_query")
        self.assertIsNone(result["answer"])
        mock_retrieve.assert_not_awaited()
        mock_generate_answer.assert_not_awaited()
        mock_send_dm.assert_awaited_once()

    @patch("services.chat_service.lark_service.areply_text", new_callable=AsyncMock)
    @patch("services.chat_service.generate_grounded_answer", new_callable=AsyncMock)
    @patch("services.chat_service.weknora_service.retrieve", new_callable=AsyncMock)
    @patch("services.chat_service.jev_service.classify_message", new_callable=AsyncMock)
    @patch("services.chat_service.jev_service.check_forbidden_query", new_callable=AsyncMock)
    @patch("services.chat_service.scope_service.get_scope_by_chat_id", new_callable=AsyncMock)
    async def test_scoped_weknora_retrieve_with_knowledge_ids(
        self,
        mock_get_scope,
        mock_check_forbidden,
        mock_classify,
        mock_retrieve,
        mock_generate_answer,
        mock_reply,
    ):
        from models.chat_scope import ChatScopeRecord
        mock_get_scope.return_value = ChatScopeRecord(
            chat_id="oc_active_group",
            chat_name="Nhóm Dự Án",
            dataset_id="kb_project_1",
            status="Hoạt động",
            forbidden_labels=["Ngân sách"],
            knowledge_ids=["file_pdf_123", "file_docx_456"],
        )
        mock_check_forbidden.return_value = {"is_forbidden": False, "confidence": 0.0}
        mock_classify.return_value = {"action": "REPLY_ONLY", "confidence": 0.90}
        mock_retrieve.return_value = [
            {"content": "Tiến độ đạt 80%", "document_name": "spec.pdf", "id": "chunk_1"}
        ]
        mock_generate_answer.return_value = "Tiến độ hiện tại đang đạt 80%."

        result = await process_chat_pipeline(
            query="Tiến độ dự án hiện tại ra sao?",
            chat_id="oc_active_group",
            sender="user-1",
            message_id="msg_1",
            reply_to_lark=False,
        )

        self.assertEqual(result["status"], "auto_replied")
        self.assertEqual(result["answer"], "Tiến độ hiện tại đang đạt 80%.")
        mock_retrieve.assert_awaited_once_with(
            query="Tiến độ dự án hiện tại ra sao?",
            knowledge_base_ids=["kb_project_1"],
            knowledge_ids=["file_pdf_123", "file_docx_456"],
            match_count=5,
        )


if __name__ == "__main__":
    unittest.main()