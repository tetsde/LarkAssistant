"""
Transitional Facade Shim for DocParserService
=============================================
Vị trí: server/services/doc_parser_service.py (Deprecated - Vui lòng import từ services.knowledge)

Module này re-export toàn bộ interface từ `services.knowledge.doc_parser` để bảo đảm 100%
khả năng tương thích ngược cho các file routers, tests và utils hiện hành.
"""

from __future__ import annotations

from services.knowledge.doc_parser import (
    DocParserService,
    doc_parser_service,
    DOCX_URL_PATTERN,
    WIKI_URL_PATTERN,
)

__all__ = [
    "DocParserService",
    "doc_parser_service",
    "DOCX_URL_PATTERN",
    "WIKI_URL_PATTERN",
]
