"""
HiLark Unit Tests: Chat Scope & Data Permission Management
==========================================================
Vị trí: server/tests/test_chat_scope.py

Chạy:
    uv run python -m unittest tests/test_chat_scope.py
"""

import unittest
from unittest.mock import AsyncMock, patch
from core.config import settings
from models.chat_scope import ChatScopeRecord
from services.lark import lark_service
from services.scope_service import ScopeService


class TestChatScope(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = ScopeService()
        self.admin_id = "ou_admin_123"
        self.attacker_id = "ou_hacker_456"
        self.service.get_admin_open_ids = lambda: [self.admin_id]

    def test_model_serialization(self):
        """Kiểm tra ChatScopeRecord to_dict và khởi tạo."""
        rec = ChatScopeRecord(
            chat_id="oc_test_group",
            chat_name="Nhóm Backend",
            dataset_id="kb_backend_uuid",
            dataset_name="Kho Kỹ Thuật Backend",
            updated_by=self.admin_id,
            updated_by_name="Admin Nam",
        )
        d = rec.to_dict()
        self.assertEqual(d["chat_id"], "oc_test_group")
        self.assertEqual(d["dataset_id"], "kb_backend_uuid")
        self.assertEqual(d["dataset_name"], "Kho Kỹ Thuật Backend")
        self.assertEqual(d["updated_by"], self.admin_id)

    def test_is_admin_user(self):
        """Kiểm tra phân quyền: Admin được phép, User thường bị chặn."""
        self.assertTrue(self.service.is_admin_user(self.admin_id))
        self.assertFalse(self.service.is_admin_user(self.attacker_id))
        self.assertFalse(self.service.is_admin_user(""))

    @patch("services.scope_service.weknora_service.get_kb_info")
    @patch("services.scope_service.get_chat_scopes_collection")
    async def test_set_chat_kb_unauthorized_attacker_blocked(self, mock_coll_getter, mock_get_kb):
        """Kiểm tra nhân viên lạ cố tình chạy set-kb bị chặn đứng ngay lập tức."""
        ok, msg, rec = await self.service.set_chat_kb(
            chat_id="oc_test_group",
            dataset_id="kb_fake_id",
            operator_open_id=self.attacker_id,
        )
        self.assertFalse(ok)
        self.assertIn("TỪ CHỐI", msg)
        self.assertIn("không có quyền quản trị", msg)
        self.assertIsNone(rec)
        # WeKnora và DB không bao giờ được gọi
        mock_get_kb.assert_not_called()
        mock_coll_getter.assert_not_called()

    @patch("services.scope_service.weknora_service.get_kb_info")
    async def test_set_chat_kb_invalid_dataset_id_rejected(self, mock_get_kb):
        """Kiểm tra Admin gõ sai Dataset ID hoặc ID không tồn tại trên WeKnora."""
        mock_get_kb.return_value = None  # WeKnora báo không tìm thấy

        ok, msg, rec = await self.service.set_chat_kb(
            chat_id="oc_test_group",
            dataset_id="kb_invalid_uuid",
            operator_open_id=self.admin_id,
        )
        self.assertFalse(ok)
        self.assertIn("không tồn tại hoặc không hợp lệ trên WeKnora", msg)
        self.assertIsNone(rec)

    @patch("services.scope_service.weknora_service.get_kb_info")
    @patch("services.scope_service.get_chat_scopes_collection")
    async def test_set_chat_kb_success_with_kb_name(self, mock_coll_getter, mock_get_kb):
        """Kiểm tra Admin gán KB thành công và log thông báo có đầy đủ Tên của KB."""
        mock_get_kb.return_value = {
            "id": "kb_paystream_001",
            "name": "Tài Liệu Cổng Thanh Toán PayStream",
            "description": "Kho tri thức microservices",
        }

        mock_coll = AsyncMock()
        mock_coll.find_one.return_value = None
        mock_coll.update_one.return_value = AsyncMock(acknowledged=True)
        mock_coll_getter.return_value = mock_coll

        ok, msg, rec = await self.service.set_chat_kb(
            chat_id="oc_paystream_team",
            dataset_id="kb_paystream_001",
            operator_open_id=self.admin_id,
            operator_name="Tống Phước Hoài Nam",
            chat_name="PayStream Core Team",
        )

        self.assertTrue(ok)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.dataset_name, "Tài Liệu Cổng Thanh Toán PayStream")
        # Kiểm tra thông báo có chứa tên KB
        self.assertIn("Tài Liệu Cổng Thanh Toán PayStream", msg)
        self.assertIn("Đã liên kết nhóm thành công với Knowledge Base", msg)

        # Xác minh đã lưu vào MongoDB
        mock_coll.update_one.assert_called_once()
        call_args = mock_coll.update_one.call_args[0]
        self.assertEqual(call_args[0], {"chat_id": "oc_paystream_team"})
        self.assertEqual(call_args[1]["$set"]["dataset_name"], "Tài Liệu Cổng Thanh Toán PayStream")

    @patch("services.scope_service.get_chat_scopes_collection")
    async def test_get_kb_for_chat_fallback_and_custom(self, mock_coll_getter):
        """Kiểm tra tra cứu: nhóm đã cấu hình lấy riêng, nhóm chưa cấu hình fallback về mặc định."""
        mock_coll = AsyncMock()

        async def find_one_side_effect(filter_dict):
            if filter_dict.get("chat_id") == "oc_configured_group":
                return {
                    "chat_id": "oc_configured_group",
                    "dataset_id": "kb_custom_123",
                    "dataset_name": "KB Riêng Của Nhóm",
                }
            return None

        mock_coll.find_one.side_effect = find_one_side_effect
        mock_coll_getter.return_value = mock_coll

        # Nhóm đã cấu hình
        kb_custom = await self.service.get_kb_for_chat("oc_configured_group")
        self.assertEqual(kb_custom, "kb_custom_123")

        # Nhóm lạ chưa cấu hình -> fallback về default
        kb_default = await self.service.get_kb_for_chat("oc_unknown_group")
        self.assertEqual(kb_default, settings.WEKNORA_DATASET_ID)

    @patch("services.scope_service.get_chat_scopes_collection")
    async def test_reset_chat_kb(self, mock_coll_getter):
        """Kiểm tra reset-kb: chỉ Admin mới được reset, xóa bản ghi khỏi Mongo."""
        # Kẻ lạ bị chặn
        ok_attack, msg_attack = await self.service.reset_chat_kb("oc_group", self.attacker_id)
        self.assertFalse(ok_attack)
        self.assertIn("không có quyền quản trị", msg_attack)

        # Admin reset thành công
        mock_coll = AsyncMock()
        mock_coll.delete_one.return_value = AsyncMock(deleted_count=1)
        mock_coll_getter.return_value = mock_coll

        ok_admin, msg_admin = await self.service.reset_chat_kb("oc_group", self.admin_id)
        self.assertTrue(ok_admin)
        self.assertIn("Đã gỡ bỏ Knowledge Base riêng", msg_admin)
        mock_coll.delete_one.assert_called_once_with({"chat_id": "oc_group"})

    @patch("services.scope_service.get_chat_scopes_collection")
    @patch("services.scope_service.weknora_service.upload_file")
    @patch("services.larkbase.lark_base_service.adownload_attachment")
    async def test_sync_group_from_base_record(self, mock_download, mock_upload, mock_coll_getter):
        mock_coll = AsyncMock()
        mock_coll.find_one.return_value = None
        mock_coll.update_one.return_value = AsyncMock()
        mock_coll_getter.return_value = mock_coll

        mock_download.return_value = b"mock pdf bytes"
        mock_upload.return_value = {"success": True, "knowledge_id": "k_id_999"}

        raw_record = {
            "record_id": "rec_test_1",
            "fields": {
                "ID Group": "oc_group_alpha",
                "Dự án / Nhóm": "Dự án Alpha",
                "Trạng thái": "Hoạt động",
                "Nhãn cấm xem": "Ngân sách, Chi phí, Bảng lương",
                "Documents": [
                    {
                        "file_token": "tok_file_1",
                        "name": "spec.pdf",
                        "size": 12345,
                        "type": "application/pdf",
                    }
                ],
            },
        }

        rec = await self.service.sync_group_from_base_record(raw_record)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.chat_id, "oc_group_alpha")
        self.assertEqual(rec.chat_name, "Dự án Alpha")
        self.assertEqual(rec.status, "Hoạt động")
        self.assertTrue(rec.is_active)
        self.assertEqual(rec.forbidden_labels, ["Ngân sách", "Chi phí", "Bảng lương"])
        self.assertEqual(rec.knowledge_ids, ["k_id_999"])
        self.assertEqual(len(rec.documents), 1)
        self.assertEqual(rec.documents[0]["knowledge_id"], "k_id_999")

    def test_security_level_properties(self):
        """Kiểm tra các thuộc tính phân loại mức độ bảo mật (Nội bộ vs Tuyệt mật)."""
        rec_conf = ChatScopeRecord(chat_id="oc_conf", security_level="Tuyệt mật")
        self.assertTrue(rec_conf.is_confidential)
        self.assertFalse(rec_conf.is_internal)

        rec_inter = ChatScopeRecord(chat_id="oc_inter", security_level="Nội bộ")
        self.assertFalse(rec_conf := rec_inter.is_confidential)
        self.assertTrue(rec_inter.is_internal)

    @patch("services.scope_service.weknora_service.upload_file", new_callable=AsyncMock)
    @patch("services.scope_service.get_chat_scopes_collection")
    async def test_sync_group_extracts_security_level(self, mock_coll_getter, mock_upload):
        mock_coll = AsyncMock()
        mock_coll.find_one.return_value = None
        mock_coll.update_one.return_value = AsyncMock(acknowledged=True)
        mock_coll_getter.return_value = mock_coll

        raw_record = {
            "record_id": "rec_sec_01",
            "fields": {
                "ID Group": "oc_group_secret",
                "Dự án / Nhóm": "Dự án LogiChain Tuyệt Mật",
                "Mức độ bảo mật": "Tuyệt mật",
                "Trạng thái": "Hoạt động",
            },
        }

        rec = await self.service.sync_group_from_base_record(raw_record)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.security_level, "Tuyệt mật")
        self.assertTrue(rec.is_confidential)

    async def test_chat_pipeline_downgrades_reply_to_draft_on_confidential_group(self):
        """Kiểm tra nhóm ở mức độ 'Tuyệt mật' thì 100% câu hỏi tự trả lời đều bị ép sang draft chờ duyệt."""
        from services.chat_service import process_chat_pipeline

        mock_scope = ChatScopeRecord(
            chat_id="oc_group_secret",
            chat_name="Dự án Tuyệt Mật",
            security_level="Tuyệt mật",
            status="Hoạt động",
        )

        with (
            patch("services.chat_service.scope_service.get_scope_by_chat_id", new_callable=AsyncMock) as mock_get_scope,
            patch("services.chat_service.jev_service.classify_message", new_callable=AsyncMock) as mock_classify,
            patch("services.chat_service.get_mongo_facts", new_callable=AsyncMock) as mock_get_facts,
            patch("services.chat_service.weknora_service.retrieve", new_callable=AsyncMock) as mock_retrieve,
            patch("services.chat_service.ContextComposer") as mock_composer_cls,
            patch("services.chat_service.generate_grounded_answer", new_callable=AsyncMock) as mock_gen_answer,
            patch("services.chat_service.draft_store.create", new_callable=AsyncMock) as mock_create_draft,
            patch("services.chat_service.lark_service.send_bot_dm_to_owner", new_callable=AsyncMock) as mock_send_dm,
            patch("services.chat_service.lark_service.areply_text", new_callable=AsyncMock) as mock_areply,
            patch.object(lark_service, "known_user_open_id", "ou_owner_123"),
        ):
            mock_get_scope.return_value = mock_scope
            mock_classify.return_value = {"action": "REPLY_ONLY", "confidence": 0.99}
            mock_get_facts.return_value = []
            mock_retrieve.return_value = [{"content": "Tài liệu bí mật", "document_name": "NDA.pdf"}]
            mock_composer_cls.return_value.compose.return_value = {"context_text": "Tài liệu bí mật"}
            mock_gen_answer.return_value = "Câu trả lời đã soạn nháp."

            res = await process_chat_pipeline(
                query="Kế hoạch thử nghiệm dự án bí mật thế nào?",
                sender="ou_member_99",
                chat_id="oc_group_secret",
                message_id="msg_secret_1",
                reply_to_lark=True,
                user_name="Thành viên bí mật",
            )

            # JEV ban đầu là REPLY_ONLY nhưng do nhóm là Tuyệt mật -> Ép sang DRAFT_PENDING_APPROVAL!
            self.assertEqual(res["jev_action"], "DRAFT_PENDING_APPROVAL")
            self.assertEqual(res["status"], "draft_pending_approval")
            mock_create_draft.assert_awaited_once()
            mock_send_dm.assert_awaited_once()
            # TUYỆT ĐỐI không reply trực tiếp vào nhóm!
            mock_areply.assert_not_awaited()

    async def test_sync_group_skip_empty_chat_id(self):
        raw_record = {
            "record_id": "rec_empty",
            "fields": {
                "Dự án / Nhóm": "Nhóm không có ID Group",
            },
        }
        rec = await self.service.sync_group_from_base_record(raw_record)
        self.assertIsNone(rec)


if __name__ == "__main__":
    unittest.main()

