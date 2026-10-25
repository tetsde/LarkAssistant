"""
HiLark Document Parsing & DocReader Models
==========================================
Vị trí: server/models/docreader.py

Mục đích:
    Định nghĩa các cấu trúc dữ liệu cho:
      1. DocReaderResult: Kết quả phân giải từ microservice AnyDoc gRPC.
      2. DocParseResult: Kết quả phân giải hợp nhất từ Document Parsing Layer
         (hỗ trợ cả tệp đính kèm nhị phân và đường link Lark DocX/Wiki).
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class DocReaderResult(BaseModel):
    """Kết quả phân giải tệp nhị phân từ WeKnora-docreader qua gRPC."""
    success: bool
    markdown_content: str = ""
    file_name: str = ""
    file_type: str = ""
    error: Optional[str] = None
    metadata: Dict[str, str] = Field(default_factory=dict)
    execution_time_ms: float = 0.0


class DocParseResult(BaseModel):
    """
    Kết quả phân giải hợp nhất từ Document Parsing Layer.
    Chuẩn hóa nội dung từ Lark DocX URL, Wiki URL, hoặc Tệp đính kèm sang Markdown sạch.
    """
    success: bool
    markdown_content: str = ""
    doc_name: str = ""
    source_type: str = ""  # "binary_attachment", "lark_docx", "lark_wiki"
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
