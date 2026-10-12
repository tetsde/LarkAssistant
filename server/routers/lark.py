"""
HiLark Lark Webhook & Event Router
===================================
Vị trí: server/routers/lark.py

Mục đích:
    Cung cấp endpoint Webhook cho Lark Open Platform:
      - POST /api/lark/events: Nhận sự kiện từ Lark (xác thực challenge, tin nhắn mới, ...)
      - GET /api/lark/status: Kiểm tra trạng thái cấu hình Lark Service
      - POST /api/lark/reply-test: Test nhanh gửi tin nhắn phản hồi
"""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from typing import Optional

from services.lark import lark_service

router = APIRouter(prefix="/api/lark", tags=["Lark Integration"])


class TestSendMessageRequest(BaseModel):
    receive_id: str
    text: str
    receive_id_type: Optional[str] = "chat_id"  # chat_id, open_id, user_id


class TestReplyMessageRequest(BaseModel):
    message_id: str
    text: str


@router.post("/events", summary="Lark Event Subscription Webhook")
async def handle_lark_events(request: Request) -> Response:
    """
    Endpoint nhận tất cả các sự kiện từ Lark Event Subscriptions:
      - Trả về Challenge Code khi Lark gửi request xác thực URL (URL Verification).
      - Nhận và phân phối sự kiện tin nhắn người dùng gửi cho Bot (im.message.receive_v1).
    """
    return await lark_service.handle_fastapi_request(request)


@router.get("/status", summary="Kiểm tra trạng thái Lark Service")
async def get_lark_status():
    """Kiểm tra cấu hình App ID và Domain của Lark."""
    return {
        "status": "online",
        "app_id": lark_service.app_id,
        "domain": lark_service.domain,
        "has_secret": bool(lark_service.app_secret),
        "has_verification_token": bool(lark_service.verification_token),
        "has_encrypt_key": bool(lark_service.encrypt_key),
    }


