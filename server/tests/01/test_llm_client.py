"""
Unit tests for Unified LLM Client (HiLark)
===========================================
File: server/tests/test_llm_client.py
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.llm_client import GeminiClient, LLMClient, llm_client


class TestLLMClient(unittest.IsolatedAsyncioTestCase):

    def test_alias_compatibility(self):
        """Kiểm tra alias GeminiClient trỏ đúng về LLMClient."""
        self.assertIs(GeminiClient, LLMClient)
        self.assertIsInstance(llm_client, LLMClient)

    def test_missing_api_key_raises_value_error(self):
        """Không có API key thì phải raise ValueError khi gọi API."""
        client = LLMClient(api_key="")
        with patch.object(client, "_ensure_api_key", side_effect=ValueError("Missing key")):
            with self.assertRaises(ValueError):
                client._get_url("gemini-2.5-flash")

    @patch("httpx.AsyncClient.post")
    async def test_generate_json_async_success(self, mock_post):
        """Test gọi generate_json_async thành công với responseMimeType='application/json'."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"entities": [{"name": "Dự án A"}]}'}]
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        client = LLMClient(api_key="mock_key")
        result = await client.generate_json_async("Trích xuất thông tin")
        self.assertIn("Dự án A", result)

        # Kiểm tra payload
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["generationConfig"]["thinkingConfig"]["thinkingBudget"], 0)

    @patch("httpx.AsyncClient.post")
    async def test_generate_text_async_success(self, mock_post):
        """Test sinh văn bản tự nhiên (Grounded QA, Digest) không ép JSON."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Dự án A đang chạy đúng tiến độ."}]
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        client = LLMClient(api_key="mock_key")
        result = await client.generate_text_async("Tiến độ thế nào?")
        self.assertEqual(result, "Dự án A đang chạy đúng tiến độ.")

        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        self.assertNotIn("responseMimeType", payload["generationConfig"])

    @patch("httpx.AsyncClient.post")
    async def test_model_fallback(self, mock_post):
        """Test cơ chế fallback khi model đầu tiên trả về 404."""
        resp_404 = MagicMock()
        resp_404.status_code = 404
        resp_404.text = "Model not found"

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"text": "Thành công từ model fallback"}]}}
            ]
        }

        mock_post.side_effect = [resp_404, resp_200]

        client = LLMClient(api_key="mock_key", default_models=["model-fail", "model-ok"])
        result = await client.generate_text_async("Xin chào")
        self.assertEqual(result, "Thành công từ model fallback")
        self.assertEqual(mock_post.call_count, 2)

    @patch("httpx.Client.post")
    def test_generate_json_sync_success(self, mock_post):
        """Test gọi đồng bộ (sync) sinh JSON."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"text": "{\"status\": \"ok\"}"}]}}
            ]
        }
        mock_post.return_value = mock_resp

        client = LLMClient(api_key="mock_key")
        result = client.generate_json("Prompt sync")
        self.assertEqual(result, "{\"status\": \"ok\"}")


if __name__ == "__main__":
    unittest.main()
