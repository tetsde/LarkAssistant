import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.weknora import WeKnoraService


class TestWeKnoraThresholds(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = WeKnoraService()
        self.service.api_key = "test-key"
        self.service.base_url = "http://weknora.test/api/v1"
        self.service.headers = {"X-API-Key": "test-key"}

    def mock_async_client(self, factory):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": []}

        client = AsyncMock()
        client.post.return_value = response

        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = context
        return client

    @patch("services.weknora.httpx.AsyncClient")
    async def test_retrieve_uses_configured_thresholds_by_default(self, factory):
        client = self.mock_async_client(factory)
        with (
            patch("services.weknora.settings.vector_threshold", 0.75),
            patch("services.weknora.settings.keyword_threshold", 0.65),
        ):
            await self.service.retrieve("project deadline", knowledge_base_ids=["kb-1"])

        payload = client.post.await_args.kwargs["json"]
        self.assertEqual(payload["vector_threshold"], 0.75)
        self.assertEqual(payload["keyword_threshold"], 0.65)

    @patch("services.weknora.httpx.AsyncClient")
    async def test_explicit_thresholds_override_config(self, factory):
        client = self.mock_async_client(factory)
        with (
            patch("services.weknora.settings.vector_threshold", 0.75),
            patch("services.weknora.settings.keyword_threshold", 0.65),
        ):
            await self.service.retrieve(
                "project deadline",
                knowledge_base_ids=["kb-1"],
                vector_threshold=0.4,
                keyword_threshold=0.3,
            )

        payload = client.post.await_args.kwargs["json"]
        self.assertEqual(payload["vector_threshold"], 0.4)
        self.assertEqual(payload["keyword_threshold"], 0.3)


if __name__ == "__main__":
    unittest.main()
