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


if __name__ == "__main__":
    unittest.main()
