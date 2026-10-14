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
    user_name: Optional[str] = Field(default=None, description="Tên hiển thị của người hỏi")
    responder_name: Optional[str] = Field(default=None, description="Tên người trả lời")
    role: Optional[str] = Field(default=None, description="Vai trò của người trả lời")
    reply_to_lark: bool = False


class UserChatRequest(BaseModel):
    """
    Request chuyên biệt cho endpoint chat trả lời ĐÍCH DANH người dùng.
    """
    query: str = Field(..., description="Câu hỏi hoặc tin nhắn của người dùng")
    user_name: str = Field(default="bạn", description="Tên hiển thị của người nhận câu trả lời")
    responder_name: Optional[str] = Field(default=None, description="Tên người trực tiếp phản hồi")
    role: Optional[str] = Field(default=None, description="Vai trò của người phản hồi")
    channel: str = Field(default="lark", description="Kênh liên lạc")
    message_id: Optional[str] = Field(default=None, description="Lark message ID để reply trực tiếp")
    chat_id: Optional[str] = Field(default=None, description="Lark chat ID")
    sender_id: Optional[str] = Field(default=None, description="Lark open_id của người hỏi")
    reply_to_lark: bool = Field(default=False, description="Tự động gửi reply về Lark")
    retrieve_count: int = Field(default=5, description="Số lượng chunks truy xuất từ WeKnora")


class MemoryRequest(BaseModel):
    text: str


class ApproveDraftRequest(BaseModel):
    """
    Request duyệt gửi bản nháp (Gửi / Sửa / Bỏ).
    """
    message_id: str = Field(..., description="Lark message ID cần reply")
    action: str = Field(..., description="Hành động: 'send' (Gửi), 'edit' (Sửa), 'discard' (Bỏ)")
    content: Optional[str] = Field(default=None, description="Nội dung gửi (nếu action='send' hoặc sau khi sửa nếu action='edit')")

