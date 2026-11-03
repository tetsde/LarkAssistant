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
    tenant_key: Optional[str] = Field(default=None, description="Mã tenant của doanh nghiệp (Multi-Tenant)")


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
    tenant_key: Optional[str] = Field(default=None, description="Mã tenant của doanh nghiệp (Multi-Tenant)")


class MemoryRequest(BaseModel):
    text: str


class ApproveDraftRequest(BaseModel):
    """
    Request duyệt gửi bản nháp (Gửi / Sửa / Bỏ).
    """
    message_id: str = Field(..., description="Lark message ID cần reply")
    action: str = Field(..., description="Hành động: 'send' (Gửi), 'edit' (Sửa), 'discard' (Bỏ)")
    content: Optional[str] = Field(default=None, description="Nội dung gửi (nếu action='send' hoặc sau khi sửa nếu action='edit')")


import uuid
from typing import Any, Dict
from models.memory import get_vietnam_now_iso


class PendingDraft(BaseModel):
    """
    Bản nháp câu trả lời chờ chủ nhân (owner) phê duyệt trước khi gửi về nhóm chat Lark.
    Lưu trong MongoDB collection 'draft_logs'.
    """
    owner_id: str = Field(..., description="Lark open_id của chủ nhân duyệt draft")
    message_id: str = Field(..., description="Message ID của tin nhắn gốc cần reply")
    chat_id: str = Field(..., description="ID cuộc trò chuyện trên Lark")
    query: str = Field(..., description="Nội dung câu hỏi của người dùng")
    draft_answer: str = Field(..., description="Nội dung câu trả lời do AI soạn sẵn")
    user_name: str = Field(default="bạn", description="Tên hiển thị của người hỏi")
    responder_name: Optional[str] = Field(default=None, description="Tên người phản hồi danh nghĩa")
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    status: str = Field(default="pending", description="Trạng thái: pending, sent, discarded, failed")
    approved_content: Optional[str] = Field(default=None, description="Nội dung thực tế sau khi duyệt/sửa")
    bot_reply_message_id: Optional[str] = Field(default=None, description="Message ID của tin nhắn reply Bot gửi vào nhóm")
    tenant_key: Optional[str] = Field(default=None, description="Mã định danh doanh nghiệp (Multi-Tenant ISV)")
    last_error: Optional[str] = Field(default=None, description="Lỗi gần nhất nếu gửi thất bại")
    created_at: str = Field(default_factory=get_vietnam_now_iso)
    updated_at: str = Field(default_factory=get_vietnam_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_document(cls, document: Dict[str, Any]) -> "PendingDraft":
        return cls(
            id=document.get("id") or str(document.get("_id", uuid.uuid4().hex)),
            owner_id=document["owner_id"],
            message_id=document.get("message_id", ""),
            chat_id=document.get("chat_id", ""),
            query=document.get("query", ""),
            draft_answer=document.get("draft_answer", ""),
            user_name=document.get("user_name", "bạn"),
            responder_name=document.get("responder_name"),
            status=document.get("status", "pending"),
            approved_content=document.get("approved_content"),
            bot_reply_message_id=document.get("bot_reply_message_id"),
            tenant_key=document.get("tenant_key"),
            last_error=document.get("last_error"),
            created_at=document.get("created_at") or get_vietnam_now_iso(),
            updated_at=document.get("updated_at") or get_vietnam_now_iso(),
        )

