"""
Unit Test & Demonstration cho LarkService
=========================================
Vị trí: server/tests/test_lark_service.py

Chạy:
    uv run python server/tests/test_lark_service.py
"""

import asyncio
import json
import os
import sys

# Đảm bảo import được module từ server
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from services.lark import LarkService, LarkMessage, lark_service
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1


def test_lark_client_auth():
    print("\n" + "=" * 60)
    print("TEST 1: KIỂM TRA XÁC THỰC LARK APP CREDENTIALS VỚI OPEN API")
    print("=" * 60)

    service = LarkService()
    print(f"App ID: {service.app_id}")
    print(f"Domain: {service.domain}")

    # Gọi kiểm tra auth qua tenant access token internal
    import lark_oapi as lark
    resp = service.client.auth.v3.tenant_access_token.internal(
        lark.api.auth.v3.InternalTenantAccessTokenRequest.builder()
        .request_body(
            lark.api.auth.v3.InternalTenantAccessTokenRequestBody.builder()
            .app_id(service.app_id)
            .app_secret(service.app_secret)
            .build()
        )
        .build()
    )
    print(f"Lark Auth API Result -> code: {resp.code}, msg: {resp.msg}")
    assert resp.code == 0
    assert resp.msg == "ok"
    print("✔ TEST 1 PASSED: Credentials Lark kết nối thành công 100%!")


def test_parse_message_event():
    print("\n" + "=" * 60)
    print("TEST 2: KIỂM TRA BÓC TÁCH TIN NHẮN (PARSE LARK EVENT)")
    print("=" * 60)

    # Giả lập payload sự kiện P2ImMessageReceiveV1 từ Lark
    mock_payload = {
        "event": {
            "sender": {
                "sender_id": {"open_id": "ou_test_user_999"},
                "sender_type": "user",
                "tenant_key": "tenant_123",
            },
            "message": {
                "message_id": "om_test_msg_888",
                "chat_id": "oc_test_chat_777",
                "chat_type": "group",
                "message_type": "text",
                "content": json.dumps({"text": "@_user_bot Sếp vừa chốt ngân sách lên 800 triệu nhé"}),
                "create_time": 1773000000000,
                "mentions": [
                    {
                        "key": "@_user_bot",
                        "id": {"open_id": "ou_bot_123"},
                        "name": "HiLark Assistant",
                    }
                ],
            },
        }
    }

    event = P2ImMessageReceiveV1(mock_payload)
    service = LarkService()
    parsed: LarkMessage = service.parse_event(event)

    print(f"Parsed Message ID: {parsed.message_id}")
    print(f"Parsed Sender ID: {parsed.sender_id}")
    print(f"Parsed Chat ID: {parsed.chat_id} ({parsed.chat_type})")
    print(f"Clean Text: '{parsed.text}'")
    print(f"Is Bot: {parsed.is_bot}")

    assert parsed is not None
    assert parsed.message_id == "om_test_msg_888"
    assert parsed.sender_id == "ou_test_user_999"
    assert parsed.chat_id == "oc_test_chat_777"
    assert parsed.chat_type == "group"
    # Mention @_user_bot phải được làm sạch khỏi nội dung câu hỏi
    assert parsed.text == "Sếp vừa chốt ngân sách lên 800 triệu nhé"
    assert parsed.is_bot is False
    print("✔ TEST 2 PASSED: Bóc tách tin nhắn & làm sạch mention hoàn hảo!")


def test_message_handler_dispatch():
    print("\n" + "=" * 60)
    print("TEST 3: ĐĂNG KÝ VÀ KÍCH HOẠT MESSAGE HANDLER CALLBACK")
    print("=" * 60)

    service = LarkService()
    received_msgs = []

    @service.on_message
    def on_user_chat(msg: LarkMessage):
        received_msgs.append(msg)

    # Giả lập phát sự kiện
    mock_payload = {
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user_1"}, "sender_type": "user"},
            "message": {
                "message_id": "om_unique_msg_1",
                "chat_id": "oc_chat_1",
                "message_type": "text",
                "content": json.dumps({"text": "Hello HiLark"}),
            },
        }
    }
    event = P2ImMessageReceiveV1(mock_payload)
    service._internal_on_message_event(event)

    assert len(received_msgs) == 1
    assert received_msgs[0].text == "Hello HiLark"

    # Kiểm tra Deduplication: Gửi lại cùng message_id om_unique_msg_1 ➔ Phải bị chặn
    service._internal_on_message_event(event)
    assert len(received_msgs) == 1  # Vẫn là 1, không bị tăng lên 2
    print("✔ TEST 3 PASSED: Callback thực thi thành công & Chống trùng lặp tin nhắn hoạt động chuẩn!")


async def test_fastapi_url_verification():
    print("\n" + "=" * 60)
    print("TEST 4: XÁC THỰC LARK WEBHOOK URL CHALLENGE (FASTAPI REQUEST)")
    print("=" * 60)

    service = LarkService()

    # Tạo mock request cho URL verification
    from starlette.requests import Request
    from starlette.datastructures import Headers

    challenge_str = "hilark_random_challenge_token_999"
    body_data = json.dumps({
        "type": "url_verification",
        "challenge": challenge_str,
        "token": "some_test_token"
    }).encode("utf-8")

    async def mock_receive():
        return {"type": "http.request", "body": body_data, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/lark/events",
        "headers": [(b"content-type", b"application/json")],
    }
    req = Request(scope=scope, receive=mock_receive)

    resp = await service.handle_fastapi_request(req)
    resp_body = json.loads(resp.body.decode("utf-8"))
    print(f"Status Code: {resp.status_code}")
    print(f"Response Body: {resp_body}")

    assert resp.status_code == 200
    assert resp_body.get("challenge") == challenge_str
    print("✔ TEST 4 PASSED: Tự động trả lời URL Challenge khi Lark ping xác thực!")


def test_user_identity():
    print("\n" + "=" * 60)
    print("TEST 5: KIỂM TRA THAO TÁC TRÊN DANH NGHĨA USER (ACCESS_TOKEN_USER)")
    print("=" * 60)

    service = LarkService()
    user_info = service.get_current_user()
    print(f"User Profile Lấy Được:")
    print(f"  - Tên: {user_info.get('name')}")
    print(f"  - Open ID: {user_info.get('open_id')}")
    print(f"  - Union ID: {user_info.get('union_id')}")
    print(f"  - Avatar: {user_info.get('avatar_url')[:40]}...")

    assert "name" in user_info
    assert user_info["name"] == "Tống Phước Hoài Nam"
    assert user_info["open_id"] == "ou_5a83a5e22269cfed0aaabeada2d3e603"
    print("✔ TEST 5 PASSED: Xác thực danh tính User Tống Phước Hoài Nam chuẩn 100%!")


async def main():
    test_lark_client_auth()
    test_parse_message_event()
    test_message_handler_dispatch()
    await test_fastapi_url_verification()
    test_user_identity()
    print("\n🎉 TOÀN BỘ 5/5 TESTS LARK SERVICE ĐÃ THÀNH CÔNG VƯỢT TRỘI!")


if __name__ == "__main__":
    asyncio.run(main())

