"""
Unit Tests: Master Executive Daily Digest
=========================================
Kiểm thử toàn diện kiến trúc Master Daily Digest:
1. Model MasterDailyDigestRecord & phương thức to_executive_dm_text()
2. generate_master_daily_digest: gom nhiều nhóm chat thành 1 báo cáo duy nhất
3. approve_and_sync_master_digest: duyệt 1 lệnh, nạp từng group digest vào đúng KB WeKnora của nhóm
4. reject_master_digest: từ chối master digest
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from models.digest import (
    CommitmentItem,
    DailyDigestRecord,
    DecisionItem,
    MasterDailyDigestRecord,
    SourceReference,
    StagingMessage,
    StatusCategory,
    StatusChangeItem,
)
from services.digest_service import DigestService


class TestMasterDailyDigest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.service = DigestService(gemini_api_key="mock_key")

        # Mock source reference
        src = SourceReference.create(
            message_id="om_msg_001",
            speaker_name="Nguyễn Văn A",
            speaker_id="ou_user_a",
            timestamp="10:30 16/10/2026",
            quote="Chốt chuyển sang dùng FastAPI nhé",
        )

        # Mock group digest 1 (Nhóm Dự Án A)
        self.digest_group_a = DailyDigestRecord(
            id="digest_20261016_oc_group_a",
            date="2026-10-16",
            chat_id="oc_group_a",
            chat_name="Nhóm Dự Án Alpha",
            project_tag="Alpha",
            overview_summary="Nhóm Alpha đã chốt kiến trúc API và kế hoạch release.",
            decisions=[
                DecisionItem(
                    id="dec_01",
                    title="Chuyển sang FastAPI",
                    content="Đồng ý chuyển toàn bộ backend sang FastAPI",
                    source=src,
                )
            ],
            commitments=[
                CommitmentItem(
                    id="cmt_01",
                    promiser_name="Nguyễn Văn A",
                    task="Hoàn thiện router Payment",
                    deadline="17:00 ngày 20/10/2026",
                    source=src,
                )
            ],
            status_changes=[
                StatusChangeItem(
                    id="stc_01",
                    category=StatusCategory.BLOCKER,
                    target_object="Cổng thanh toán",
                    summary="Thiếu API key sandbox từ phía đối tác",
                    new_state="Đang tắc nghẽn",
                    blocker_reason="Cần PM liên hệ đối tác cấp key",
                    source=src,
                )
            ],
            message_count=15,
            weknora_kb_id="kb_dataset_alpha",
        )

        # Mock group digest 2 (Nhóm Dự Án B)
        self.digest_group_b = DailyDigestRecord(
            id="digest_20261016_oc_group_b",
            date="2026-10-16",
            chat_id="oc_group_b",
            chat_name="Nhóm Dự Án Beta",
            project_tag="Beta",
            overview_summary="Nhóm Beta hoàn thành kiểm thử giao diện người dùng.",
            decisions=[],
            commitments=[
                CommitmentItem(
                    id="cmt_02",
                    promiser_name="Trần Thị B",
                    task="Fix lỗi hiển thị dark mode trên iOS",
                    deadline="Thứ 6 tuần này",
                    source=src,
                )
            ],
            status_changes=[
                StatusChangeItem(
                    id="stc_02",
                    category=StatusCategory.MILESTONE,
                    target_object="UI/UX Sprint 2",
                    summary="Đã nghiệm thu thiết kế mobile app",
                    new_state="Hoàn thành",
                    source=src,
                )
            ],
            message_count=25,
            weknora_kb_id="kb_dataset_beta",
        )

    def test_master_digest_dm_text_format(self):
        """Kiểm tra MasterDailyDigestRecord.to_executive_dm_text() tạo văn bản phân cấp trực quan."""
        master = MasterDailyDigestRecord(
            id="master_digest_20261016",
            date="2026-10-16",
            executive_summary="Bức tranh toàn cảnh: Dự án Alpha gặp nghẽn cổng thanh toán, trong khi Beta đã nghiệm thu Sprint 2 đúng hạn.",
            group_digests=[self.digest_group_a, self.digest_group_b],
            total_messages=40,
            total_groups=2,
            status="pending_approval",
        )

        dm_text = master.to_executive_dm_text()

        # Kiểm tra các phần cốt lõi
        self.assertIn("BÁO CÁO TỔNG HỢP TOÀN BỘ CÁC NHÓM", dm_text)
        self.assertIn("Số nhóm hoạt động:** 2", dm_text)
        self.assertIn("Tổng tin nhắn:** 40", dm_text)
        self.assertIn("I. TỔNG QUAN ĐIỀU HÀNH", dm_text)
        self.assertIn("Bức tranh toàn cảnh:", dm_text)
        self.assertIn("II. CHI TIẾT TỪNG NHÓM DỰ ÁN", dm_text)

        # Kiểm tra chi tiết Nhóm A
        self.assertIn("Nhóm Dự Án Alpha", dm_text)
        self.assertIn("Chuyển sang FastAPI", dm_text)
        self.assertIn("17:00 ngày 20/10/2026", dm_text)
        self.assertIn("🔴 [BLOCKER]", dm_text)
        self.assertIn("Cần PM liên hệ đối tác cấp key", dm_text)

        # Kiểm tra chi tiết Nhóm B
        self.assertIn("Nhóm Dự Án Beta", dm_text)
        self.assertIn("Fix lỗi hiển thị dark mode trên iOS", dm_text)
        self.assertIn("🟢 [MILESTONE]", dm_text)

        # Kiểm tra hướng dẫn duyệt
        self.assertIn("duyệt digest", dm_text)
        self.assertIn("hủy digest", dm_text)

    async def test_generate_master_daily_digest(self):
        """Kiểm tra generate_master_daily_digest gom các nhóm và gửi đúng 1 tin DM."""
        with patch.object(self.service, "get_active_chat_ids_today", new_callable=AsyncMock) as mock_chats, \
             patch.object(self.service, "get_staging_messages", new_callable=AsyncMock) as mock_msgs, \
             patch.object(self.service, "extract_digest_from_messages", new_callable=AsyncMock) as mock_extract, \
             patch.object(self.service, "save_digest_to_mongo", new_callable=AsyncMock) as mock_save_digest, \
             patch.object(self.service, "save_master_digest_to_mongo", new_callable=AsyncMock) as mock_save_master, \
             patch.object(self.service, "send_master_approval_request", new_callable=AsyncMock) as mock_send_approval, \
             patch.object(self.service, "_generate_executive_overview", new_callable=AsyncMock) as mock_exec_overview, \
             patch("services.scope_service.scope_service.get_scope_by_chat_id", new_callable=AsyncMock) as mock_scope:

            mock_chats.return_value = ["oc_group_a", "oc_group_b"]
            mock_msgs.return_value = [MagicMock(chat_name="Group")]
            mock_extract.side_effect = [self.digest_group_a, self.digest_group_b]
            mock_exec_overview.return_value = "Tổng quan điều hành test."
            mock_scope.return_value = None
            mock_send_approval.return_value = True

            master = await self.service.generate_master_daily_digest(date="2026-10-16", require_approval=True)

            self.assertEqual(master.total_groups, 2)
            self.assertEqual(master.status, "pending_approval")
            self.assertEqual(len(master.group_digests), 2)
            self.assertEqual(master.executive_summary, "Tổng quan điều hành test.")

            # Kiểm tra chỉ gửi DUY NHẤT 1 DM xin duyệt
            mock_send_approval.assert_awaited_once_with(master)
            mock_save_master.assert_awaited_once()

    async def test_approve_and_sync_master_digest(self):
        """Kiểm tra approve_and_sync_master_digest phân tách và đồng bộ từng group vào đúng KB."""
        master_doc = {
            "id": "master_digest_20261016",
            "date": "2026-10-16",
            "executive_summary": "Tổng quan",
            "group_digests": [self.digest_group_a.model_dump(), self.digest_group_b.model_dump()],
            "total_messages": 40,
            "total_groups": 2,
            "status": "pending_approval",
            "created_at": "2026-10-16T23:00:00",
            "updated_at": "2026-10-16T23:00:00",
        }

        with patch("services.digest_service.get_master_daily_digests_collection") as mock_get_col, \
             patch.object(self.service, "sync_digest_to_weknora", new_callable=AsyncMock) as mock_sync_weknora:

            mock_col = MagicMock()
            mock_col.find_one = AsyncMock(return_value=master_doc)
            mock_col.update_one = AsyncMock()
            mock_get_col.return_value = mock_col
            mock_sync_weknora.return_value = True

            ok, msg, mrec = await self.service.approve_and_sync_master_digest(
                master_digest_id="master_digest_20261016",
                approver_open_id="ou_owner_999",
            )

            self.assertTrue(ok)
            self.assertIn("2/2 nhóm", msg)
            self.assertEqual(mrec.status, "synced")
            self.assertEqual(mrec.approved_by, "ou_owner_999")

            # Đảm bảo WeKnora sync được gọi cho từng nhóm
            self.assertEqual(mock_sync_weknora.await_count, 2)

    async def test_reject_master_digest(self):
        """Kiểm tra reject_master_digest đánh dấu rejected và không nạp WeKnora."""
        master_doc = {
            "id": "master_digest_20261016",
            "date": "2026-10-16",
            "executive_summary": "Tổng quan",
            "group_digests": [self.digest_group_a.model_dump()],
            "total_messages": 15,
            "total_groups": 1,
            "status": "pending_approval",
            "created_at": "2026-10-16T23:00:00",
            "updated_at": "2026-10-16T23:00:00",
        }

        with patch("services.digest_service.get_master_daily_digests_collection") as mock_get_col:
            mock_col = MagicMock()
            mock_col.find_one = AsyncMock(return_value=master_doc)
            mock_col.update_one = AsyncMock()
            mock_get_col.return_value = mock_col

            ok, msg, mrec = await self.service.reject_master_digest("master_digest_20261016")

            self.assertTrue(ok)
            self.assertIn("từ chối", msg.lower())
            self.assertEqual(mrec.status, "rejected")
            mock_col.update_one.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
