"""
HiLark Lark Webhook & Event Router
===================================
Vị trí: server/routers/lark.py

Mục đích:
    Cung cấp endpoint Webhook cho Lark Open Platform:
      - POST /api/lark/events: Nhận sự kiện từ Lark (xác thực challenge, tin nhắn mới, ...)
"""

from fastapi import APIRouter, Request, Response
from services.lark import lark_service

router = APIRouter(prefix="/api/lark", tags=["Lark Integration"])


@router.post("/events", summary="Lark Event Subscription Webhook")
async def handle_lark_events(request: Request) -> Response:
    """
    Endpoint nhận tất cả các sự kiện từ Lark Event Subscriptions:
      - Trả về Challenge Code khi Lark gửi request xác thực URL (URL Verification).
      - Nhận và phân phối sự kiện tin nhắn người dùng gửi cho Bot (im.message.receive_v1).
      - Nhận sự kiện tương tác bấm nút trên Thẻ tương tác (card.action.trigger).
    """
    return await lark_service.handle_fastapi_request(request)


@router.post("/card-action", summary="Lark Interactive Card Action Webhook")
async def handle_lark_card_action(request: Request) -> Response:
    """
    Endpoint nhận trực tiếp các sự kiện bấm nút trên Thẻ tương tác (Lark Interactive Card Action Callback).
    """
    return await lark_service.handle_card_action_request(request)
