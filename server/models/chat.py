from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str
    agent_enabled: bool = True
    agent_id: str = "builtin-quick-answer"
    channel: str = "api"


class MemoryRequest(BaseModel):
    text: str
