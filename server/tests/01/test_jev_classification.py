import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.jev import JevService


class TestJevClassification(unittest.IsolatedAsyncioTestCase):
    @patch("services.jev.httpx.AsyncClient")
    async def test_memory_and_draft_is_requested_and_returned(self, async_client_factory):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "answers": {
                "message_action": {
                    "choice": "MEMORY_AND_DRAFT",
                    "confidence": 0.95,
                    "probabilities": {"MEMORY_AND_DRAFT": 0.95},
                }
            }
        }
        http_client = AsyncMock()
        http_client.post.return_value = response
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=http_client)
        client_context.__aexit__ = AsyncMock(return_value=False)
        async_client_factory.return_value = client_context

        service = JevService()
        service.api_key = "test-key"

        result = await service.classify_message("Cần cập nhật và trả lời gấp")

        payload = http_client.post.call_args.kwargs["json"]
        criteria = payload["questions"]["message_action"]["criteria"]
        self.assertIn("MEMORY_AND_DRAFT", criteria)
        self.assertNotIn("MEMORY_AND_REPLY", criteria)
        self.assertEqual(result["action"], "MEMORY_AND_DRAFT")

    async def test_check_forbidden_query_empty_inputs(self):
        service = JevService()
        # Empty query
        res1 = await service.check_forbidden_query("", "Ngân sách, Chi phí")
        self.assertFalse(res1["is_forbidden"])
        self.assertEqual(res1["reason"], "empty_query")

        # Empty forbidden_labels
        res2 = await service.check_forbidden_query("Dự án thế nào rồi?", "")
        self.assertFalse(res2["is_forbidden"])
        self.assertEqual(res2["reason"], "no_forbidden_labels")

        # None forbidden_labels
        res3 = await service.check_forbidden_query("Dự án thế nào rồi?", None)
        self.assertFalse(res3["is_forbidden"])
        self.assertEqual(res3["reason"], "no_forbidden_labels")

    async def test_check_forbidden_query_keyword_fast_match(self):
        service = JevService()
        service.api_key = ""  # No API key to test fast keyword fallback
        res = await service.check_forbidden_query(
            "Cho mình xem bảng lương tháng này với",
            "Ngân sách, Bảng lương, Hợp đồng"
        )
        self.assertTrue(res["is_forbidden"])
        self.assertEqual(res["matched_label"], "Bảng lương")
        self.assertIn("keyword", res["reason"])

    @patch("services.jev.httpx.AsyncClient")
    async def test_check_forbidden_query_jev_api_forbidden(self, async_client_factory):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "answers": {
                "forbidden_intent": {
                    "choice": "FORBIDDEN",
                    "probabilities": {"FORBIDDEN": 0.88, "ALLOWED": 0.12},
                }
            }
        }
        http_client = AsyncMock()
        http_client.post.return_value = response
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=http_client)
        client_context.__aexit__ = AsyncMock(return_value=False)
        async_client_factory.return_value = client_context

        service = JevService()
        service.api_key = "test-key"

        res = await service.check_forbidden_query(
            "Sếp đã chi bao nhiêu tiền cho việc này?",
            ["Ngân sách", "Chi phí"]
        )
        self.assertTrue(res["is_forbidden"])
        self.assertEqual(res["choice"], "FORBIDDEN")
        self.assertGreaterEqual(res["confidence"], 0.7)

    @patch("services.jev.httpx.AsyncClient")
    async def test_check_forbidden_query_jev_api_allowed(self, async_client_factory):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "answers": {
                "forbidden_intent": {
                    "choice": "ALLOWED",
                    "probabilities": {"FORBIDDEN": 0.05, "ALLOWED": 0.95},
                }
            }
        }
        http_client = AsyncMock()
        http_client.post.return_value = response
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=http_client)
        client_context.__aexit__ = AsyncMock(return_value=False)
        async_client_factory.return_value = client_context

        service = JevService()
        service.api_key = "test-key"

        res = await service.check_forbidden_query(
            "Tiến độ công việc sprint này đến đâu rồi?",
            ["Ngân sách", "Chi phí", "Bảng lương"]
        )
        self.assertFalse(res["is_forbidden"])
        self.assertEqual(res["choice"], "ALLOWED")


if __name__ == "__main__":
    unittest.main()

