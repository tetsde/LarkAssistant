"""
HiLark Bot Handlers Package
===========================
Exports các handlers chuyên biệt cho Lark Bot:
  - document_handler: Xử lý tệp đính kèm (Word/PDF/ảnh) và link Lark DocX/Wiki.
  - owner_command_handler: Xử lý các câu lệnh DM 1-1 của Chủ nhân (Digest & Draft Approval).
  - member_message_handler: Xử lý tin nhắn nhóm, staging và chat queue.
"""

from .document_handler import handle_document_or_links
from .owner_command_handler import handle_owner_dm_command
from .member_message_handler import handle_member_message

__all__ = [
    "handle_document_or_links",
    "handle_owner_dm_command",
    "handle_member_message",
]
