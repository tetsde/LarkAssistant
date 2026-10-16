#!/usr/bin/env python3
"""
Kiểm thử Unit Test cho Token Health Check Utility
===================================================
Vị trí: server/tests/test_token_ping.py

Chạy bằng:
    PYTHONPATH=. uv run python tests/test_token_ping.py
"""

import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

# Đảm bảo import được module từ server
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from utils.lark_token import (
    TokenCheckResult,
    parse_jwt_expiration,
    ping_user_access_token,
    check_and_warn_token,
)
from services.lark import lark_service


class TestTokenHealthCheck(unittest.TestCase):

    def test_missing_token(self):
        """Kiểm tra xử lý an toàn khi token rỗng hoặc None."""
        res = ping_user_access_token(token="")
        self.assertFalse(res.is_valid)
        self.assertTrue(res.is_expired)
        self.assertEqual(res.status, "missing")
        self.assertIn("Chưa cấu hình", res.message)

    def test_expired_jwt_detection(self):
        """Kiểm tra phát hiện token JWT đã quá hạn (timestamp trong quá khứ)."""
        import base64, json
        # Tạo fake payload với exp cách đây 1 giờ
        header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode("utf-8").rstrip("=")
        past_exp = int(datetime.now(timezone.utc).timestamp()) - 3600
        payload = base64.urlsafe_b64encode(
            json.dumps({"exp": past_exp, "user_id": "ou_test"}).encode("utf-8")
        ).decode("utf-8").rstrip("=")
        fake_token = f"{header}.{payload}.signature"

        is_exp, exp_dt, remaining, p = parse_jwt_expiration(fake_token)
        self.assertTrue(is_exp)
        self.assertIsNotNone(remaining)
        self.assertLess(remaining, 0)

        # Ping function cũng phải trả về status='expired' an toàn không crash
        res = ping_user_access_token(token=fake_token)
        self.assertFalse(res.is_valid)
        self.assertTrue(res.is_expired)
        self.assertEqual(res.status, "expired")
        self.assertEqual(res.code, 20005)
        self.assertIn("ĐÃ HẾT HẠN", res.message)

    def test_valid_jwt_timestamp(self):
        """Kiểm tra token còn thời hạn trong tương lai."""
        import base64, json
        header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode("utf-8").rstrip("=")
        future_exp = int(datetime.now(timezone.utc).timestamp()) + 7200 # 2 giờ nữa
        payload = base64.urlsafe_b64encode(
            json.dumps({"exp": future_exp, "user_id": "ou_test"}).encode("utf-8")
        ).decode("utf-8").rstrip("=")
        fake_token = f"{header}.{payload}.signature"

        is_exp, exp_dt, remaining, p = parse_jwt_expiration(fake_token)
        self.assertFalse(is_exp)
        self.assertGreater(remaining, 7000)

    def test_lark_service_token_guard(self):
        """Kiểm tra LarkService chặn crash an toàn khi token expired."""
        service = lark_service
        # Gọi check token
        res = service.check_user_access_token()
        self.assertIsInstance(res, TokenCheckResult)

        # Thao tác prepare message không được crash
        opt, content, err = service._prepare_user_msg_payload("ou_test", "Xin chào")
        if not res.is_valid:
            # Nếu token hiện tại trong .env đã hết hạn, hệ thống trả err dict an toàn
            self.assertIsNone(opt)
            self.assertIsNotNone(err)
            self.assertFalse(err.get("success"))
            self.assertEqual(err.get("error"), "token_expired")


if __name__ == "__main__":
    unittest.main()
