"""
HiLark Chat Router
==================
Vị trí: server/routers/chat.py

Router tiếp nhận và điều phối HTTP endpoint:
  - POST /api/chat: Xử lý chat qua API hoặc benchmark RAG
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException

from models import ChatRequest
from services.chat_service import (
    process_chat_pipeline,
    # Re-export các dependencies cho unit tests
    ContextComposer,
    draft_store,
    jev_service,
    lark_service,
    weknora_service,
)

logger = logging.getLogger("hilark.chat")
router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("")
async def chat(request: ChatRequest):
    """Endpoint xử lý hội thoại tiêu chuẩn qua process_chat_pipeline."""
    result = await process_chat_pipeline(
        query=request.query,
        sender=request.sender_id or request.channel or "User",
        channel=request.channel,
        message_id=request.message_id,
        chat_id=request.chat_id,
        reply_to_lark=request.reply_to_lark,
        user_name=request.user_name,
        responder_name=request.responder_name,
        role=request.role,
    )

    if result.get("status") == "invalid_input":
        raise HTTPException(status_code=400, detail=result.get("message", "Tin nhắn không hợp lệ"))

    return result
