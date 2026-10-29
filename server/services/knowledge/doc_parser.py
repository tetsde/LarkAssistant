"""
HiLark Document Parser Service (Unified Document Parsing Layer)
==============================================================
Vị trí: server/services/doc_parser_service.py

Mục đích:
    Tầng Phân Giải Tài Liệu Đa Phương Tiện (EDL-0010):
    Chuẩn hóa mọi nguồn tài liệu đầu vào thành Markdown có cấu trúc với chi phí 0 token:
      1. Tệp đính kèm nhị phân (Word .docx, PDF, Excel .xlsx, PPTX, hình ảnh...):
         - Tải từ Lark IM via message_resource API.
         - Áp dụng File Extension Gate & Size Gate.
         - Đẩy qua WeKnora AnyDoc gRPC microservice để phân giải sang Markdown.
      2. Tài liệu đám mây Lark DocX:
         - Phát hiện URL DocX qua regex.
         - Gọi Lark OpenAPI (raw_content) lấy Markdown trực tiếp.
      3. Tài liệu Lark Wiki:
         - Phát hiện URL Wiki qua regex.
         - Tra cứu obj_token qua Wiki Space Node API.
         - Nếu là DocX, lấy Markdown qua Lark DocX OpenAPI.

Kết quả trả về:
    DocParseResult (chứa markdown_content sạch, metadata, doc_name, source_type).
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Union

from models.docreader import (
    DocParseResult,
    DocReaderResult,
    SUPPORTED_DOCUMENT_EXTENSIONS,
)
from services.knowledge.docreader_client import docreader_service, DocReaderService

logger = logging.getLogger("hilark.docparser")

# Regex nhận diện các liên kết Lark DocX, Wiki và Drive Folder
DOCX_URL_PATTERN = re.compile(
    r"https?://[a-zA-Z0-9_\-\.]+(?:feishu\.cn|larksuite\.com)/docx/([a-zA-Z0-9]+)",
    re.IGNORECASE,
)
WIKI_URL_PATTERN = re.compile(
    r"https?://[a-zA-Z0-9_\-\.]+(?:feishu\.cn|larksuite\.com)/wiki/([a-zA-Z0-9]+)",
    re.IGNORECASE,
)
FOLDER_URL_PATTERN = re.compile(
    r"https?://[a-zA-Z0-9_\-\.]+(?:feishu\.cn|larksuite\.com)/(?:drive/)?folder/([a-zA-Z0-9]+)",
    re.IGNORECASE,
)

# Tập hợp các định dạng ảnh hỗ trợ OCR qua Gemini Multimodal Vision
IMAGE_EXTENSIONS: Set[str] = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}

# Prompt chuẩn hóa số hóa tài liệu cho Gemini Multimodal Vision OCR
OCR_PROMPT = (
    "Bạn là chuyên gia số hóa tài liệu và OCR hàng đầu. Hãy đọc toàn bộ văn bản trong hình ảnh này "
    "(bao gồm biên bản cuộc họp, ghi chú viết tay, sơ đồ, bảng biểu số liệu, kế hoạch công việc) "
    "và chuyển đổi thành định dạng Markdown chuẩn, rõ ràng.\n"
    "Yêu cầu:\n"
    "1. Giữ nguyên toàn bộ các chi tiết thông tin: số liệu, ngày tháng, thời hạn, tên người, quyết định, nội dung trao đổi.\n"
    "2. Nếu có bảng biểu, hãy định dạng dưới dạng Markdown table.\n"
    "3. Nếu có tiêu đề hoặc danh sách, hãy dùng heading (#, ##, ###) và bullet list (- ).\n"
    "4. Tuyệt đối chỉ trả về nội dung Markdown trích xuất được từ hình ảnh, không kèm lời giải thích hay lời mở đầu/kết thúc."
)


class DocParserService:
    """
    Dịch vụ điều phối phân giải tài liệu đa kênh (Tệp đính kèm & Lark Cloud Docs).
    Đảm bảo 100% tài liệu được chuẩn hóa thành Markdown sạch trước khi nạp vào LLM Extractor.
    Tự động định tuyến hình ảnh sang Gemini Multimodal Vision để OCR thành Markdown.
    """

    def __init__(
        self,
        docreader: Optional[DocReaderService] = None,
        lark_svc: Optional[Any] = None,
        llm: Optional[Any] = None,
    ):
        self._docreader = docreader or docreader_service
        self._lark_override = lark_svc
        self._llm_override = llm

    @property
    def _lark(self):
        if self._lark_override is not None:
            return self._lark_override
        from services.lark import lark_service
        return lark_service

    @property
    def _llm(self):
        if self._llm_override is not None:
            return self._llm_override
        from services.ai.gemini_client import llm_client
        return llm_client

    def is_image_file(self, file_name: str, resource_type: Optional[str] = None) -> bool:
        """Kiểm tra xem tệp hoặc resource có phải là hình ảnh hay không."""
        if resource_type == "image":
            return True
        if not file_name:
            return False
        import os
        ext = os.path.splitext(file_name.lower())[1]
        return ext in IMAGE_EXTENSIONS

    def get_image_mime_type(self, file_name: str) -> str:
        """Xác định MIME type của hình ảnh dựa trên phần mở rộng."""
        import os
        ext = os.path.splitext(file_name.lower())[1]
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".tiff": "image/tiff",
        }
        return mime_map.get(ext, "image/png")

    async def ocr_image_to_markdown(
        self,
        image_bytes: bytes,
        file_name: str = "image.png",
    ) -> DocParseResult:
        """
        Nhận diện ký tự và cấu trúc tài liệu từ hình ảnh sang Markdown sạch qua Gemini Multimodal Vision.

        Args:
            image_bytes: Mảng byte dữ liệu hình ảnh.
            file_name: Tên tệp ảnh (ví dụ: 'bien_ban_hop.png').

        Returns:
            DocParseResult chứa Markdown được OCR từ Gemini Vision.
        """
        start_time = time.perf_counter()
        mime_type = self.get_image_mime_type(file_name)

        try:
            markdown_content = await self._llm.generate_multimodal_async(
                prompt=OCR_PROMPT,
                image_bytes=image_bytes,
                mime_type=mime_type,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            if not markdown_content or not markdown_content.strip():
                return DocParseResult(
                    success=False,
                    doc_name=file_name,
                    source_type="image_ocr",
                    error=f"Không nhận diện được nội dung chữ từ hình ảnh '{file_name}'.",
                    execution_time_ms=elapsed_ms,
                    metadata={"file_size_bytes": len(image_bytes), "mime_type": mime_type},
                )

            cleaned_md = markdown_content.strip()
            if cleaned_md.startswith("```markdown"):
                cleaned_md = cleaned_md[len("```markdown"):].strip()
                if cleaned_md.endswith("```"):
                    cleaned_md = cleaned_md[:-3].strip()
            elif cleaned_md.startswith("```"):
                cleaned_md = cleaned_md[3:].strip()
                if cleaned_md.endswith("```"):
                    cleaned_md = cleaned_md[:-3].strip()

            logger.info(
                f"✔ [DOC PARSER OCR] Nhận diện ảnh thành công qua Gemini Vision: {file_name} "
                f"({len(cleaned_md)} chars, {elapsed_ms:.1f}ms)"
            )
            return DocParseResult(
                success=True,
                markdown_content=cleaned_md,
                doc_name=file_name,
                source_type="image_ocr",
                execution_time_ms=elapsed_ms,
                metadata={
                    "parser": "gemini_vision_ocr",
                    "file_size_bytes": len(image_bytes),
                    "mime_type": mime_type,
                    "char_count": len(cleaned_md),
                },
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"❌ [DOC PARSER OCR] Lỗi khi OCR ảnh {file_name} qua Gemini Vision: {e}", exc_info=True)
            return DocParseResult(
                success=False,
                doc_name=file_name,
                source_type="image_ocr",
                error=f"Lỗi khi nhận diện hình ảnh qua Gemini Vision: {str(e)}",
                execution_time_ms=elapsed_ms,
                metadata={"file_size_bytes": len(image_bytes), "mime_type": mime_type},
            )


    # =========================================================================
    # 1. URL DETECTION & LINK EXTRACTION
    # =========================================================================

    def extract_lark_links(self, text: str) -> List[Dict[str, str]]:
        """
        Quét và trích xuất tất cả các liên kết Lark DocX và Wiki từ văn bản.

        Args:
            text: Nội dung văn bản (tin nhắn trò chuyện, mô tả task, ...).

        Returns:
            Danh sách các dict: [{"type": "docx"|"wiki", "token": str, "url": str}]
        """
        if not text:
            return []

        results: List[Dict[str, str]] = []
        seen_tokens = set()

        # 1. Quét Lark DocX URLs
        for match in DOCX_URL_PATTERN.finditer(text):
            token = match.group(1)
            if token not in seen_tokens:
                seen_tokens.add(token)
                results.append({
                    "type": "docx",
                    "token": token,
                    "url": match.group(0),
                })

        # 2. Quét Lark Wiki URLs
        for match in WIKI_URL_PATTERN.finditer(text):
            token = match.group(1)
            if token not in seen_tokens:
                seen_tokens.add(token)
                results.append({
                    "type": "wiki",
                    "token": token,
                    "url": match.group(0),
                })

        return results

    # =========================================================================
    # 2. LARK CLOUD DOCUMENT PARSING (DOCX & WIKI)
    # =========================================================================

    async def parse_lark_docx(
        self,
        document_id: str,
        title: Optional[str] = None,
    ) -> DocParseResult:
        """
        Phân giải tài liệu Lark DocX thành Markdown qua OpenAPI (0 token cost).

        Args:
            document_id: ID của tài liệu DocX.
            title: Tiêu đề gợi ý (nếu có).

        Returns:
            DocParseResult chứa Markdown sạch.
        """
        start_time = time.perf_counter()
        doc_name = title or f"Lark DocX ({document_id})"

        try:
            content = await self._lark.aget_docx_raw_content(document_id)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            if content is None:
                return DocParseResult(
                    success=False,
                    doc_name=doc_name,
                    source_type="lark_docx",
                    error=f"Không thể truy cập tài liệu Lark DocX {document_id} (lỗi quyền hoặc tài liệu không tồn tại).",
                    execution_time_ms=elapsed_ms,
                    metadata={"document_id": document_id},
                )

            logger.info(
                f"✔ [DOC PARSER] Phân giải Lark DocX thành công: {doc_name} "
                f"({len(content)} chars, {elapsed_ms:.1f}ms)"
            )
            return DocParseResult(
                success=True,
                markdown_content=content,
                doc_name=doc_name,
                source_type="lark_docx",
                execution_time_ms=elapsed_ms,
                metadata={"document_id": document_id, "char_count": len(content)},
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"❌ [DOC PARSER] Exception khi đọc Lark DocX {document_id}: {e}", exc_info=True)
            return DocParseResult(
                success=False,
                doc_name=doc_name,
                source_type="lark_docx",
                error=f"Lỗi hệ thống khi đọc tài liệu DocX: {str(e)}",
                execution_time_ms=elapsed_ms,
                metadata={"document_id": document_id},
            )

    async def parse_lark_wiki(
        self,
        wiki_token: str,
    ) -> DocParseResult:
        """
        Phân giải trang Lark Wiki: tra cứu node token rồi đọc nội dung nếu là DocX.

        Args:
            wiki_token: Token của trang Wiki.

        Returns:
            DocParseResult chứa Markdown sạch.
        """
        start_time = time.perf_counter()
        try:
            node_info = await self._lark.aresolve_wiki_token(wiki_token)
            if not node_info:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                return DocParseResult(
                    success=False,
                    doc_name=f"Lark Wiki ({wiki_token})",
                    source_type="lark_wiki",
                    error=f"Không thể tra cứu thông tin trang Wiki với token '{wiki_token}'.",
                    execution_time_ms=elapsed_ms,
                    metadata={"wiki_token": wiki_token},
                )

            obj_token = node_info.get("obj_token", "")
            obj_type = node_info.get("obj_type", "")
            title = node_info.get("title", "") or f"Lark Wiki ({wiki_token})"

            if obj_type == "docx":
                result = await self.parse_lark_docx(document_id=obj_token, title=title)
                result.source_type = "lark_wiki"
                result.metadata["wiki_token"] = wiki_token
                result.metadata["obj_token"] = obj_token
                result.metadata["obj_type"] = obj_type
                return result
            else:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                logger.warning(
                    f"⚠️ [DOC PARSER] Trang Wiki '{title}' có kiểu '{obj_type}' chưa hỗ trợ trích xuất Markdown."
                )
                return DocParseResult(
                    success=False,
                    doc_name=title,
                    source_type="lark_wiki",
                    error=f"Hệ thống hiện tại chỉ hỗ trợ Wiki dạng DocX, chưa hỗ trợ dạng '{obj_type}'.",
                    execution_time_ms=elapsed_ms,
                    metadata={"wiki_token": wiki_token, "obj_token": obj_token, "obj_type": obj_type},
                )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"❌ [DOC PARSER] Exception khi đọc Wiki {wiki_token}: {e}", exc_info=True)
            return DocParseResult(
                success=False,
                doc_name=f"Lark Wiki ({wiki_token})",
                source_type="lark_wiki",
                error=f"Lỗi hệ thống khi tra cứu Wiki: {str(e)}",
                execution_time_ms=elapsed_ms,
                metadata={"wiki_token": wiki_token},
            )

    # =========================================================================
    # 3. BINARY ATTACHMENT PARSING (ANYDOC gRPC)
    # =========================================================================

    async def parse_attachment(
        self,
        message_id: str,
        file_key: str,
        file_name: str,
        resource_type: str = "file",
    ) -> DocParseResult:
        """
        Tải tệp đính kèm từ tin nhắn Lark IM và chuyển đổi sang Markdown bằng AnyDoc gRPC.

        Args:
            message_id: ID tin nhắn chứa tệp.
            file_key: Key tệp (file_key hoặc image_key).
            file_name: Tên tệp đầy đủ (ví dụ: 'Bien_Ban_Hop.docx').
            resource_type: 'file' hoặc 'image'.

        Returns:
            DocParseResult chứa Markdown sạch từ microservice WeKnora-docreader.
        """
        start_time = time.perf_counter()

        # 1. Gate: Kiểm tra định dạng tệp trước khi tốn băng thông tải
        if not self._docreader.is_supported_file(file_name) and not self.is_image_file(file_name, resource_type):
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            error_msg = (
                f"Định dạng tệp '{file_name}' không nằm trong danh mục hỗ trợ. "
                f"Chỉ hỗ trợ: {', '.join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))}"
            )
            logger.warning(f"🚫 [DOC PARSER GATE] {error_msg}")
            return DocParseResult(
                success=False,
                doc_name=file_name,
                source_type="binary_attachment",
                error=error_msg,
                execution_time_ms=elapsed_ms,
                metadata={"file_key": file_key, "message_id": message_id},
            )

        # 2. Tải binary content từ Lark IM
        logger.info(f"📥 [DOC PARSER] Đang tải tệp đính kèm: {file_name} (key: {file_key})...")
        file_bytes = await self._lark.adownload_message_resource(
            message_id=message_id,
            file_key=file_key,
            resource_type=resource_type,
        )

        if not file_bytes:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return DocParseResult(
                success=False,
                doc_name=file_name,
                source_type="binary_attachment",
                error=f"Không thể tải nội dung nhị phân của tệp '{file_name}' từ Lark IM.",
                execution_time_ms=elapsed_ms,
                metadata={"file_key": file_key, "message_id": message_id},
            )

        # 3. Phân nhánh xử lý: Nếu là hình ảnh, ưu tiên dùng Gemini Multimodal Vision OCR
        if self.is_image_file(file_name, resource_type):
            ocr_res = await self.ocr_image_to_markdown(
                image_bytes=file_bytes,
                file_name=file_name,
            )
            ocr_res.metadata["file_key"] = file_key
            ocr_res.metadata["message_id"] = message_id
            return ocr_res

        # 4. Chuyển đổi qua microservice AnyDoc gRPC cho các tệp văn phòng (.docx, .pdf, .xlsx, .pptx, .csv)
        reader_res: DocReaderResult = await self._docreader.read(
            file_content=file_bytes,
            file_name=file_name,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        if not reader_res.success:
            return DocParseResult(
                success=False,
                doc_name=file_name,
                source_type="binary_attachment",
                error=reader_res.error or "Lỗi không xác định từ AnyDoc gRPC Service.",
                execution_time_ms=elapsed_ms,
                metadata=reader_res.metadata,
            )

        logger.info(
            f"✔ [DOC PARSER] Phân giải tệp đính kèm thành công: {file_name} "
            f"({len(reader_res.markdown_content)} chars, {elapsed_ms:.1f}ms)"
        )
        return DocParseResult(
            success=True,
            markdown_content=reader_res.markdown_content,
            doc_name=file_name,
            source_type="binary_attachment",
            execution_time_ms=elapsed_ms,
            metadata={
                **reader_res.metadata,
                "file_size_bytes": len(file_bytes),
                "message_id": message_id,
                "file_key": file_key,
            },
        )

    async def parse_binary_bytes(
        self,
        file_content: bytes,
        file_name: str,
    ) -> DocParseResult:
        """
        Phân giải trực tiếp mảng bytes nhị phân sang Markdown (hỗ trợ API upload ngoài).
        Tự động nhận diện hình ảnh để gọi Gemini Multimodal Vision OCR.
        """
        if self.is_image_file(file_name):
            return await self.ocr_image_to_markdown(file_content, file_name)

        start_time = time.perf_counter()
        reader_res = await self._docreader.read(file_content, file_name)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return DocParseResult(
            success=reader_res.success,
            markdown_content=reader_res.markdown_content,
            doc_name=file_name,
            source_type="binary_attachment",
            error=reader_res.error,
            execution_time_ms=elapsed_ms,
            metadata={
                **reader_res.metadata,
                "file_size_bytes": len(file_content),
            },
        )

    # =========================================================================
    # 4. BATCH / TEXT LINK PARSER CONVENIENCE
    # =========================================================================

    async def parse_text_links(self, text: str) -> List[DocParseResult]:
        """
        Quét và phân giải tất cả các tài liệu Lark DocX/Wiki tìm thấy trong văn bản.

        Args:
            text: Chuỗi văn bản chứa liên kết.

        Returns:
            Danh sách kết quả DocParseResult cho từng liên kết tìm thấy.
        """
        links = self.extract_lark_links(text)
        if not links:
            return []

        results: List[DocParseResult] = []
        for link in links:
            if link["type"] == "docx":
                res = await self.parse_lark_docx(link["token"])
                results.append(res)
            elif link["type"] == "wiki":
                res = await self.parse_lark_wiki(link["token"])
                results.append(res)
        return results


# Singleton instance dùng chung toàn hệ thống
doc_parser_service = DocParserService()

__all__ = [
    "DocParserService",
    "doc_parser_service",
    "DOCX_URL_PATTERN",
    "WIKI_URL_PATTERN",
]
