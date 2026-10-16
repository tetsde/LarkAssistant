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


if __name__ == "__main__":
    unittest.main()
