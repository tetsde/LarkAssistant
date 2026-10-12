from typing import Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str
    agent_enabled: bool = True
    agent_id: str = "builtin-quick-answer"
    channel: str = "api"
    message_id: Optional[str] = None
    chat_id: Optional[str] = None
    sender_id: Optional[str] = None
    reply_to_lark: bool = False


class MemoryRequest(BaseModel):
    text: str
