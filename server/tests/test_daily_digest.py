"""
HiLark - Daily Digest & Staging Test Suite
==========================================
Vị trí: server/tests/test_daily_digest.py

Kiểm thử toàn diện:
  1. Models (server/models/digest.py):
     - SourceReference (Lark deep link, speaker, timestamp, quote)
     - DecisionItem, CommitmentItem, StatusChangeItem
     - StagingMessage
     - DailyDigestRecord.to_weknora_markdown()
  2. Utilities (server/utils/digest.py):
     - build_lark_message_link
     - get_current_digest_date
     - format_human_timestamp
     - clean_markdown_text
  3. Service (server/services/digest_service.py):
     - LLM Extraction parsing with provenance
     - WeKnora sync handling
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.digest import (
    CommitmentItem,
    DailyDigestRecord,
    DecisionItem,
    SourceReference,
    StagingMessage,
    StatusCategory,
    StatusChangeItem,
)
from services.digest_service import DigestService
from utils.digest import (
    build_lark_message_link,
    clean_markdown_text,
    format_human_timestamp,
    get_current_digest_date,
)


class TestDigestModelsAndUtils(unittest.TestCase):
    """Kiểm thử các Data Structure và hàm tiện ích."""

    def test_build_lark_message_link(self):
        msg_id = "om_test_12345"
        link = build_lark_message_link(msg_id)
        expected = f"https://applink.larksuite.com/client/message/open?open_message_id={msg_id}"
        self.assertEqual(link, expected)
        self.assertEqual(build_lark_message_link(""), "")
        self.assertEqual(build_lark_message_link("   "), "")

    def test_source_reference_create(self):
        src = SourceReference.create(
            message_id="om_abc999",
            speaker_name="Lê Nam",
            speaker_id="ou_user_1",
            timestamp="14:30 12/10/2026",
            quote="Chốt dùng MongoDB làm staging nhé anh em.",
        )
        self.assertEqual(src.message_id, "om_abc999")
        self.assertIn("om_abc999", src.message_link)
        self.assertTrue(src.message_link.startswith("https://applink.larksuite.com/client/message/open"))
        self.assertEqual(src.speaker_name, "Lê Nam")
        self.assertEqual(src.speaker_id, "ou_user_1")
        self.assertEqual(src.timestamp, "14:30 12/10/2026")
        self.assertEqual(src.quote, "Chốt dùng MongoDB làm staging nhé anh em.")

    def test_get_current_digest_date_format(self):
        date_str = get_current_digest_date()
        parts = date_str.split("-")
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[0]), 4)
        self.assertEqual(len(parts[1]), 2)
        self.assertEqual(len(parts[2]), 2)

    def test_clean_markdown_text(self):
        raw = "   Dự án \t\t  HiLark    \r\n\r\n\r\n   triển khai   "
        cleaned = clean_markdown_text(raw)
        self.assertEqual(cleaned, "Dự án HiLark\n\ntriển khai")


    def test_to_weknora_markdown_full_content(self):
        # 1. Decision
        src1 = SourceReference.create(
            message_id="om_dec_1",
            speaker_name="Nam Lê",
            timestamp="10:00 12/10/2026",
            quote="Thống nhất chuyển toàn bộ API sang REST và JWT authentication.",
        )
        dec = DecisionItem(
            id="dec_01",
            title="Chuẩn hóa API và Auth",
            content="Toàn bộ module auth sử dụng JWT, hạn chế session-based.",
            scope="Toàn bộ backend",
            source=src1,
        )

        # 2. Commitment
        src2 = SourceReference.create(
            message_id="om_cmt_1",
            speaker_name="Tuấn Dev",
            timestamp="11:15 12/10/2026",
            quote="Em sẽ hoàn thành bộ test case cho payment trước 17h thứ Sáu.",
        )
        cmt = CommitmentItem(
            id="cmt_01",
            promiser_name="Tuấn Dev",
            task="Hoàn thành bộ test case cho module Payment",
            deadline="17:00 16/10/2026",
            recipient_name="Tech Lead",
            source=src2,
        )

        # 3. Status Changes (Progress, Milestone, Blocker)
        src3 = SourceReference.create(
            message_id="om_stc_1",
            speaker_name="Hùng Backend",
            timestamp="15:30 12/10/2026",
            quote="Tích hợp VietQR đang bị vướng do phía ngân hàng chưa cấp sandbox key.",
        )
        stc = StatusChangeItem(
            id="stc_01",
            category=StatusCategory.BLOCKER,
            target_object="Cổng thanh toán VietQR",
            summary="Đình trệ do chưa nhận được sandbox key từ đối tác",
            previous_state="Đang phát triển",
            new_state="Bị nghẽn (Block)",
            blocker_reason="Chờ ngân hàng duyệt và gửi API Sandbox Key",
            source=src3,
        )

        digest = DailyDigestRecord(
            id="digest_20261012_oc_team_dev",
            date="2026-10-12",
            chat_id="oc_team_dev",
            chat_name="HiLark Core Team",
            project_tag="HiLark-2026",
            overview_summary="Ngày hôm nay chốt kiến trúc API Auth, cam kết deadline Payment và ghi nhận 1 blocker ngân hàng.",
            decisions=[dec],
            commitments=[cmt],
            status_changes=[stc],
            message_count=35,
        )

        md = digest.to_weknora_markdown()

        # Kiểm tra tiêu đề và metadata
        self.assertIn("# NHẬT KÝ TRAO ĐỔI LẬP TRÌNH & DỰ ÁN: HILARK CORE TEAM", md)
        self.assertIn("**Ngày ghi nhận:** 2026-10-12 | **Dự án:** HiLark-2026", md)
        self.assertIn("**Số lượng tin nhắn tổng hợp:** 35", md)

        # Kiểm tra mục Quyết định
        self.assertIn("## 2. CÁC QUYẾT ĐỊNH ĐÃ THỐNG NHẤT (DECISIONS)", md)
        self.assertIn("2.1. Chuẩn hóa API và Auth", md)
        self.assertIn("Chốt bởi **Nam Lê** lúc `10:00 12/10/2026`", md)
        self.assertIn("[📎 Xem tin nhắn gốc](https://applink.larksuite.com/client/message/open?open_message_id=om_dec_1)", md)

        # Kiểm tra mục Cam kết
        self.assertIn("## 3. CAM KẾT VÀ HẠN CHÓT (COMMITMENTS & PROMISES)", md)
        self.assertIn("Tuấn Dev cam kết: Hoàn thành bộ test case cho module Payment", md)
        self.assertIn("`17:00 16/10/2026`", md)
        self.assertIn("Cam kết với:** Tech Lead", md)
        self.assertIn("[📎 Xem tin nhắn gốc](https://applink.larksuite.com/client/message/open?open_message_id=om_cmt_1)", md)

        # Kiểm tra mục Thay đổi trạng thái
        self.assertIn("## 4. THAY ĐỔI TRẠNG THÁI (TIẾN ĐỘ, MỐC, BLOCKER)", md)
        self.assertIn("[🔴 BLOCKER] Cổng thanh toán VietQR", md)
        self.assertIn("Vướng mắc / Cần hỗ trợ:** Chờ ngân hàng duyệt và gửi API Sandbox Key", md)
        self.assertIn("[📎 Xem tin nhắn gốc](https://applink.larksuite.com/client/message/open?open_message_id=om_stc_1)", md)


class TestDigestService(unittest.IsolatedAsyncioTestCase):
    """Kiểm thử tầng Service xử lý LLM và đồng bộ WeKnora."""

    async def test_extract_digest_from_messages_with_mock_llm(self):
        service = DigestService(gemini_api_key="mock_key")

        # Fake messages input
        msgs = [
            StagingMessage(
                id="stg_1",
                message_id="om_msg_101",
                chat_id="oc_test",
                speaker_name="Trưởng nhóm",
                text="Chốt kiến trúc: Chúng ta sẽ dùng MongoDB làm Staging đệm tin nhắn nhé.",
                timestamp="09:15 12/10/2026",
            ),
            StagingMessage(
                id="stg_2",
                message_id="om_msg_102",
                chat_id="oc_test",
                speaker_name="Đức Dev",
                text="Ok anh, em sẽ code xong service digest trước 18h hôm nay.",
                timestamp="09:20 12/10/2026",
            ),
            StagingMessage(
                id="stg_3",
                message_id="om_msg_103",
                chat_id="oc_test",
                speaker_name="An QA",
                text="Hiện tại test môi trường dev đang bị blocker vì thiếu SSL certificate.",
                timestamp="11:45 12/10/2026",
            ),
        ]

        mock_llm_json = {
            "overview_summary": "Nhóm thống nhất kiến trúc Staging và đặt mục tiêu hoàn thành digest service.",
            "decisions": [
                {
                    "id": "dec_1",
                    "title": "Kiến trúc Staging",
                    "content": "Sử dụng MongoDB làm tầng đệm staging tin nhắn",
                    "scope": "Module Ingestion",
                    "message_id": "om_msg_101",
                    "speaker_name": "Trưởng nhóm",
                    "timestamp": "09:15 12/10/2026",
                    "quote": "Chúng ta sẽ dùng MongoDB làm Staging đệm tin nhắn nhé.",
                }
            ],
            "commitments": [
                {
                    "id": "cmt_1",
                    "promiser_name": "Đức Dev",
                    "task": "Code hoàn thiện digest service",
                    "deadline": "18:00 12/10/2026",
                    "recipient_name": "Trưởng nhóm",
                    "message_id": "om_msg_102",
                    "speaker_name": "Đức Dev",
                    "timestamp": "09:20 12/10/2026",
                    "quote": "em sẽ code xong service digest trước 18h hôm nay",
                }
            ],
            "status_changes": [
                {
                    "id": "stc_1",
                    "category": "blocker",
                    "target_object": "Môi trường Dev",
                    "summary": "Thiếu SSL certificate khiến việc test bị đình trệ",
                    "previous_state": "Sẵn sàng",
                    "new_state": "Blocker",
                    "blocker_reason": "Thiếu chứng chỉ SSL cho domain dev",
                    "message_id": "om_msg_103",
                    "speaker_name": "An QA",
                    "timestamp": "11:45 12/10/2026",
                    "quote": "test môi trường dev đang bị blocker vì thiếu SSL certificate",
                }
            ],
        }

        # Mock LLM API call trả về chuỗi bọc bởi Markdown ```json ... ```
        llm_raw_output = f"```json\n{json.dumps(mock_llm_json, ensure_ascii=False)}\n```"

        with patch.object(service, "_call_gemini", new_callable=AsyncMock) as mock_gemini:
            mock_gemini.return_value = llm_raw_output

            digest = await service.extract_digest_from_messages(
                messages=msgs,
                chat_id="oc_test",
                chat_name="Phòng Kỹ Thuật",
                date="2026-10-12",
                project_tag="HiLark",
            )

            # Xác thực kết quả trích xuất
            self.assertEqual(digest.chat_id, "oc_test")
            self.assertEqual(digest.chat_name, "Phòng Kỹ Thuật")
            self.assertEqual(digest.date, "2026-10-12")
            self.assertEqual(digest.message_count, 3)

            # 1. Decisions
            self.assertEqual(len(digest.decisions), 1)
            dec = digest.decisions[0]
            self.assertEqual(dec.title, "Kiến trúc Staging")
            self.assertEqual(dec.source.message_id, "om_msg_101")
            self.assertEqual(dec.source.speaker_name, "Trưởng nhóm")
            self.assertTrue(dec.source.message_link.startswith("https://applink.larksuite.com"))

            # 2. Commitments
            self.assertEqual(len(digest.commitments), 1)
            cmt = digest.commitments[0]
            self.assertEqual(cmt.promiser_name, "Đức Dev")
            self.assertEqual(cmt.deadline, "18:00 12/10/2026")
            self.assertEqual(cmt.source.message_id, "om_msg_102")

            # 3. Status changes
            self.assertEqual(len(digest.status_changes), 1)
            stc = digest.status_changes[0]
            self.assertEqual(stc.category, StatusCategory.BLOCKER)
            self.assertIn("SSL", stc.blocker_reason)
            self.assertEqual(stc.source.message_id, "om_msg_103")

    async def test_sync_digest_to_weknora_success(self):
        service = DigestService(gemini_api_key="mock_key")
        digest = DailyDigestRecord(
            id="digest_20261012_oc_123",
            date="2026-10-12",
            chat_id="oc_123",
            chat_name="Test Chat",
            overview_summary="Tóm tắt kiểm thử.",
        )

        mock_weknora_response = {
            "code": 0,
            "data": {"id": "weknora_doc_abc123"},
            "message": "success",
        }

        # Mock weknora_service.save_to_kb & Mongo collection
        mock_mongo_coll = MagicMock()
        mock_mongo_coll.update_one = AsyncMock(return_value=None)

        with patch("services.digest_service.weknora_service.save_to_kb", new_callable=AsyncMock) as mock_kb, \
             patch("services.digest_service.get_daily_digests_collection", return_value=mock_mongo_coll):
            mock_kb.return_value = mock_weknora_response

            success = await service.sync_digest_to_weknora(digest, dataset_id="mock_dataset_id")
            self.assertTrue(success)
            self.assertEqual(digest.sync_status, "synced")
            self.assertEqual(digest.weknora_doc_id, "weknora_doc_abc123")
            self.assertEqual(digest.weknora_kb_id, "mock_dataset_id")
            mock_mongo_coll.update_one.assert_called_once()

    async def test_sync_digest_by_id_from_mongodb(self):
        service = DigestService(gemini_api_key="mock_key")
        mock_doc = {
            "id": "digest_test_id",
            "date": "2026-10-12",
            "chat_id": "oc_test",
            "chat_name": "Test Chat",
            "overview_summary": "Tổng hợp test",
            "sync_status": "pending",
        }

        mock_mongo_coll = MagicMock()
        mock_mongo_coll.find_one = AsyncMock(return_value=mock_doc)
        mock_mongo_coll.update_one = AsyncMock(return_value=None)

        with patch("services.digest_service.get_daily_digests_collection", return_value=mock_mongo_coll), \
             patch("services.digest_service.weknora_service.save_to_kb", new_callable=AsyncMock) as mock_kb:
            mock_kb.return_value = {"code": 0, "data": {"id": "doc_from_db"}}

            ok = await service.sync_digest_by_id("digest_test_id", dataset_id="kb_123")
            self.assertTrue(ok)
            mock_mongo_coll.find_one.assert_called_once_with({"id": "digest_test_id"})

    async def test_sync_pending_digests(self):
        service = DigestService(gemini_api_key="mock_key")
        mock_docs = [
            {"id": "digest_1", "date": "2026-10-11", "chat_id": "oc_1", "sync_status": "pending"},
            {"id": "digest_2", "date": "2026-10-12", "chat_id": "oc_2", "sync_status": "failed"},
        ]

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=mock_docs)
        mock_mongo_coll = MagicMock()
        mock_mongo_coll.find.return_value.limit.return_value = mock_cursor
        mock_mongo_coll.update_one = AsyncMock(return_value=None)

        with patch("services.digest_service.get_daily_digests_collection", return_value=mock_mongo_coll), \
             patch("services.digest_service.weknora_service.save_to_kb", new_callable=AsyncMock) as mock_kb:
            mock_kb.return_value = {"code": 0, "data": {"id": "weknora_doc_batch"}}

            result = await service.sync_pending_digests(limit=10, dataset_id="kb_123")
            self.assertEqual(result["total_found"], 2)
            self.assertEqual(result["synced_count"], 2)
            self.assertEqual(len(result["synced_ids"]), 2)

    async def test_process_daily_digest_requires_approval(self):
        service = DigestService(gemini_api_key="mock_key")
        mock_mongo_coll = MagicMock()
        mock_mongo_coll.update_one = AsyncMock(return_value=None)
        mock_staging_coll = MagicMock()
        mock_staging_coll.find.return_value.sort.return_value.to_list = AsyncMock(return_value=[])
        mock_staging_coll.update_many = AsyncMock(return_value=None)

        with patch("services.digest_service.get_staging_collection", return_value=mock_staging_coll), \
             patch("services.digest_service.get_daily_digests_collection", return_value=mock_mongo_coll), \
             patch.object(service, "send_approval_request", new_callable=AsyncMock) as mock_send_approval, \
             patch.object(service, "sync_digest_to_weknora", new_callable=AsyncMock) as mock_sync_kb:
            mock_send_approval.return_value = True

            digest = await service.process_and_sync_daily_digest(
                chat_id="oc_test_approval",
                chat_name="Group Test",
                date="2026-10-12",
                require_approval=True,
            )

            # Phải lưu với sync_status là pending_approval
            self.assertEqual(digest.sync_status, "pending_approval")
            # Phải gửi tin nhắn chờ duyệt
            mock_send_approval.assert_called_once_with(digest)
            # KHÔNG ĐƯỢC tự tiện đẩy lên WeKnora khi chưa duyệt
            mock_sync_kb.assert_not_called()

    async def test_approve_and_sync_digest(self):
        service = DigestService(gemini_api_key="mock_key")
        mock_doc = {
            "id": "digest_to_approve",
            "date": "2026-10-12",
            "chat_id": "oc_test",
            "sync_status": "pending_approval",
            "overview_summary": "Tóm tắt test",
        }

        mock_mongo_coll = MagicMock()
        mock_mongo_coll.find_one = AsyncMock(return_value=mock_doc)
        mock_mongo_coll.update_one = AsyncMock(return_value=None)

        with patch("services.digest_service.get_daily_digests_collection", return_value=mock_mongo_coll), \
             patch("services.digest_service.weknora_service.save_to_kb", new_callable=AsyncMock) as mock_kb:
            mock_kb.return_value = {"code": 0, "data": {"id": "doc_approved_123"}}

            ok, msg, rec = await service.approve_and_sync_digest("digest_to_approve")
            self.assertTrue(ok)
            self.assertIn("thành công", msg)
            self.assertEqual(rec.sync_status, "synced")
            self.assertEqual(rec.weknora_doc_id, "doc_approved_123")

    async def test_reject_digest(self):
        service = DigestService(gemini_api_key="mock_key")
        mock_doc = {
            "id": "digest_to_reject",
            "date": "2026-10-12",
            "chat_id": "oc_test",
            "sync_status": "pending_approval",
            "overview_summary": "Tóm tắt test",
        }

        mock_mongo_coll = MagicMock()
        mock_mongo_coll.find_one = AsyncMock(return_value=mock_doc)
        mock_mongo_coll.update_one = AsyncMock(return_value=None)

        with patch("services.digest_service.get_daily_digests_collection", return_value=mock_mongo_coll):
            ok, msg, rec = await service.reject_digest("digest_to_reject")
            self.assertTrue(ok)
            self.assertIn("từ chối", msg)
            self.assertEqual(rec.sync_status, "rejected")
            mock_mongo_coll.update_one.assert_called_once()


if __name__ == "__main__":
    unittest.main()


