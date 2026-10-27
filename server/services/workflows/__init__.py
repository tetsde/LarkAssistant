"""
HiLark Business Workflows Domain Package (Workflows Domain)
===========================================================
Vị trí: server/services/workflows/

Đóng gói và điều phối toàn bộ các quy trình nghiệp vụ cốt lõi:
  - chat_workflow: Pipeline Q&A điều phối đa tầng (Claims -> WeKnora RAG -> Context Composer -> LLM).
  - digest_workflow: Pipeline tổng hợp tin nhắn nhóm (Daily Group Digest, Master Daily Digest).
  - draft_workflow & draft_store: Quản lý bản nháp câu trả lời, hàng đợi chờ duyệt và gửi tin nhắn Lark.
  - chat_queue: Concurrency controller, smart message debouncer và throttled queue làm mượt tốc độ.
  - digest_formatters: Tiện ích bóc tách ngày tháng, tạo applink và định dạng báo cáo digest.
"""

from services.workflows.draft_store import (
    DraftStore,
    PendingDraft,
    draft_store,
)
from services.workflows.draft_workflow import (
    DraftService,
    draft_service,
)
from services.workflows.digest_formatters import (
    build_lark_message_link,
    clean_markdown_text,
    format_human_timestamp,
    get_current_digest_date,
)
from services.workflows.chat_queue import (
    ChatQueueService,
    MessageDebouncer,
    ThrottledChatQueue,
    chat_queue_service,
)
from services.workflows.chat_workflow import (
    ChatService,
    chat_service,
    process_chat_pipeline,
    process_document_to_claims,
)
from services.workflows.digest_workflow import (
    DigestService,
    digest_service,
)
from services.workflows.claim_workflow import (
    ClaimService,
    claim_service,
)

__all__ = [
    # Claim Workflow
    "ClaimService",
    "claim_service",
    # Chat Workflow
    "ChatService",
    "chat_service",
    "process_chat_pipeline",
    "process_document_to_claims",
    # Digest Workflow
    "DigestService",
    "digest_service",
    # Draft Workflow & Store
    "DraftService",
    "draft_service",
    "DraftStore",
    "draft_store",
    "PendingDraft",
    # Chat Concurrency Queue & Debouncer
    "ChatQueueService",
    "chat_queue_service",
    "MessageDebouncer",
    "ThrottledChatQueue",
    # Digest Formatters & Helpers
    "build_lark_message_link",
    "get_current_digest_date",
    "format_human_timestamp",
    "clean_markdown_text",
]
