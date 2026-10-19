"""
HiLark Chat Queue Models
========================
Vị trí: server/models/chat_queue.py

Định nghĩa cấu trúc dữ liệu cho gói tin nhắn sau khi gom (debounced)
và xếp hàng điều phối (throttled queue).
"""

from __future__ import annotations

import time
from typing import List, Optional
from pydantic import BaseModel, Field


class ChatQueueItem(BaseModel):
    """
    Gói dữ liệu yêu cầu hội thoại đã được gom qua MessageDebouncer,
    chuẩn bị được đưa vào ThrottledChatQueue để thực thi tuần tự.
    """
    chat_id: str = Field(..., description="ID cuộc trò chuyện trên Lark")
    sender_id: str = Field(..., description="Lark Open ID của người gửi câu hỏi")
    combined_text: str = Field(..., description="Nội dung câu hỏi đã được gom từ các tin ngắt dòng")
    anchor_message_id: str = Field(..., description="Lark Message ID của tin nhắn cuối cùng để reply")
    chat_type: str = Field(default="group", description="Loại cuộc trò chuyện: 'group' hoặc 'p2p'")
    user_name: str = Field(default="bạn", description="Tên hiển thị của người hỏi")
    responder_name: Optional[str] = Field(default=None, description="Tên người phát ngôn đại diện bot")
    is_owner: bool = Field(default=False, description="Có phải tin nhắn từ chính Chủ nhân hay không")
    role: Optional[str] = Field(default=None, description="Vai trò của người phản hồi")
    created_at: float = Field(default_factory=time.time, description="Thời điểm gom xong tin nhắn (timestamp)")
    message_ids: List[str] = Field(default_factory=list, description="Danh sách toàn bộ message_id đã gom")
