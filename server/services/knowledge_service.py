"""
Unified Knowledge Service Module
================================
Vị trí: server/services/knowledge_service.py

Gom nhóm toàn bộ các dịch vụ cơ sở tri thức (Knowledge Domain):
  - WeKnora RAG Client (weknora_service, WeKnoraService)
  - Doc Parser Service (doc_parser_service, DocParserService)
  - AnyDoc gRPC DocReader Service (docreader_service, DocReaderService)
  - Policy Sync Background Service (policy_sync_service, PolicySyncService)
  - Rule Engine (rule_engine, UnifiedRuleEngine)
  - Context Composer (context_composer, ContextComposer)
"""

from __future__ import annotations

import httpx

from core.config import settings
from services.knowledge.weknora_client import (
    WeKnoraService,
    weknora_service,
)
from services.knowledge.doc_parser import (
    DocParserService,
    doc_parser_service,
    DOCX_URL_PATTERN,
    WIKI_URL_PATTERN,
)
from services.knowledge.docreader_client import (
    DocReaderService,
    docreader_service,
)
from models.docreader import (
    DocReaderResult,
    DocParseResult,
    SUPPORTED_DOCUMENT_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
)
from services.knowledge.policy_sync import (
    PolicySyncService,
    policy_sync_service,
    extract_lark_token,
    start_policy_sync_loop,
)
from services.knowledge.rule_engine import (
    UnifiedRuleEngine,
    rule_engine,
)
from services.knowledge.context_composer import (
    ContextComposer,
    context_composer,
)

__all__ = [
    # WeKnora
    "WeKnoraService",
    "weknora_service",
    # Doc Parser
    "DocParserService",
    "doc_parser_service",
    "DOCX_URL_PATTERN",
    "WIKI_URL_PATTERN",
    # DocReader gRPC
    "DocReaderService",
    "docreader_service",
    "DocReaderResult",
    "DocParseResult",
    "SUPPORTED_DOCUMENT_EXTENSIONS",
    "MAX_FILE_SIZE_BYTES",
    # Policy Sync
    "PolicySyncService",
    "policy_sync_service",
    "extract_lark_token",
    "start_policy_sync_loop",
    # Rules & Context
    "UnifiedRuleEngine",
    "rule_engine",
    "ContextComposer",
    "context_composer",
]
