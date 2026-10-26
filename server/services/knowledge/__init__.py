"""
HiLark Knowledge Domain Package
===============================
Vị trí: server/services/knowledge/

Chứa toàn bộ các dịch vụ và tiện ích liên quan đến Tri thức & Bối cảnh (Layer 3 RAG):
  - weknora_client: Giao tiếp WeKnora RAG API (truy xuất vector/keyword, upload file, quản lý KB).
  - docreader_client: Client gRPC WeKnora AnyDoc 50051 (phân giải PDF, Word, Excel sang Markdown).
  - doc_parser: Điều phối phân giải tài liệu đa kênh (tệp đính kèm nhị phân + Lark DocX/Wiki URL).
  - policy_sync: Đồng bộ chính sách công ty từ Lark Bitable sang WeKnora KB.
  - chat_scopes: Quản lý phân quyền tri thức theo nhóm chat (chat_id -> dataset_id & security level).
  - context_composer: Động cơ tổng hợp ngữ cảnh đa tầng (Hierarchical Context: WeKnora + MongoDB Claims).
  - rule_engine: Khử nhiễu, làm sạch dữ liệu, kiểm tra các câu hỏi/nội dung cấm bảo mật 0ms.
"""

from services.knowledge.weknora_client import WeKnoraService, weknora_service
from services.knowledge.docreader_client import DocReaderService, docreader_service
from services.knowledge.doc_parser import (
    DocParserService,
    doc_parser_service,
    DOCX_URL_PATTERN,
    WIKI_URL_PATTERN,
)
from services.knowledge.policy_sync import (
    PolicySyncService,
    policy_sync_service,
    extract_lark_token,
)
from services.knowledge.chat_scopes import (
    ScopeService,
    scope_service,
    ChatScopeRecord,
)
from services.knowledge.context_composer import (
    ContextComposer,
    context_composer,
    compose_context,
    RetrievedChunk,
    NormalizedClaim,
)
from services.knowledge.rule_engine import (
    UnifiedRuleEngine,
    rule_engine,
    sanitize,
    SanitizeResult,
    remove_vietnamese_accents,
    parse_labels,
)

__all__ = [
    "WeKnoraService",
    "weknora_service",
    "DocReaderService",
    "docreader_service",
    "DocParserService",
    "doc_parser_service",
    "DOCX_URL_PATTERN",
    "WIKI_URL_PATTERN",
    "PolicySyncService",
    "policy_sync_service",
    "extract_lark_token",
    "ScopeService",
    "scope_service",
    "ChatScopeRecord",
    "ContextComposer",
    "context_composer",
    "compose_context",
    "RetrievedChunk",
    "NormalizedClaim",
    "UnifiedRuleEngine",
    "rule_engine",
    "sanitize",
    "SanitizeResult",
    "remove_vietnamese_accents",
    "parse_labels",
]
