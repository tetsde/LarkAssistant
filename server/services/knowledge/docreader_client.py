"""
HiLark DocReader gRPC Service Client
====================================
Vị trí: server/services/docreader_service.py

Mục đích:
    Giao tiếp với microservice WeKnora-docreader qua gRPC (port 50051)
    để phân giải tệp nhị phân (Word .docx, PDF, Excel, PPTX, ảnh...)
    thành Markdown có cấu trúc với chi phí token bằng 0.

Tính năng:
    1. File Extension Gate: Chỉ xử lý các định dạng tệp hợp lệ được phép.
    2. File Size Gate: Giới hạn tệp tối đa 50MB (bảo vệ bộ nhớ & kết nối).
    3. Persistent Connection Pool: Tái sử dụng kênh kết nối gRPC (HTTP/2 channel reuse).
    4. Timeout & Safe Error Handling: Bắt lỗi gRPC RPCError an toàn, không làm gián đoạn hệ thống.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set

import grpc
import grpc.aio

# Đảm bảo đường dẫn import server modules và proto
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_ROOT = os.path.dirname(CURRENT_DIR)
PROTO_DIR = os.path.join(SERVER_ROOT, "proto")
for p in (SERVER_ROOT, PROTO_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from core.config import settings
from models.docreader import (
    DocReaderResult,
    MAX_FILE_SIZE_BYTES,
    SUPPORTED_DOCUMENT_EXTENSIONS,
)
from proto import docreader_pb2, docreader_pb2_grpc

logger = logging.getLogger("hilark.docreader")


# ==============================================================================
# 3. DOCREADER SERVICE IMPLEMENTATION
# ==============================================================================

class DocReaderService:
    """
    Service client kết nối tới WeKnora-docreader gRPC.
    Quản lý vòng đời gRPC channel, connection pool và điều phối yêu cầu phân giải.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
    ):
        self.host = host or getattr(settings, "DOCREADER_GRPC_HOST", "127.0.0.1")
        self.port = port or getattr(settings, "DOCREADER_GRPC_PORT", 50051)
        self.timeout = timeout_seconds or getattr(settings, "DOCREADER_TIMEOUT_SECONDS", 60)
        self.target = f"{self.host}:{self.port}"

        # Async channel & stub (tái sử dụng connection)
        self._async_channel: Optional[grpc.aio.Channel] = None
        self._async_stub: Optional[docreader_pb2_grpc.DocReaderStub] = None
        self._lock = asyncio.Lock()

    # -------------------------------------------------------------------------
    # GATE VALIDATION HELPERS
    # -------------------------------------------------------------------------

    @staticmethod
    def extract_extension(file_name: str) -> str:
        """Trích xuất phần mở rộng chuẩn hóa (lowercase kèm dấu chấm)."""
        if not file_name:
            return ""
        suffix = Path(file_name).suffix.lower().strip()
        return suffix

    @classmethod
    def is_supported_file(cls, file_name: str) -> bool:
        """Kiểm tra xem phần mở rộng của file có nằm trong danh sách hỗ trợ không."""
        ext = cls.extract_extension(file_name)
        return ext in SUPPORTED_DOCUMENT_EXTENSIONS

    # -------------------------------------------------------------------------
    # CHANNEL MANAGEMENT (CONNECTION REUSE & POOLING)
    # -------------------------------------------------------------------------

    async def _get_stub(self) -> docreader_pb2_grpc.DocReaderStub:
        """Lấy hoặc khởi tạo gRPC stub dùng chung (tối ưu TCP/HTTP/2 connection)."""
        if self._async_stub is not None:
            return self._async_stub

        async with self._lock:
            if self._async_stub is not None:
                return self._async_stub

            channel_options = [
                # Buffer 50MB cho cả 2 chiều gửi và nhận
                ("grpc.max_receive_message_length", MAX_FILE_SIZE_BYTES),
                ("grpc.max_send_message_length", MAX_FILE_SIZE_BYTES),
                # Keepalive cấu hình để duy trì kết nối ổn định lâu dài (tránh spam ping khi idle)
                ("grpc.keepalive_time_ms", 120000),
                ("grpc.keepalive_timeout_ms", 20000),
                ("grpc.keepalive_permit_without_calls", 0),
                ("grpc.http2.max_pings_without_data", 2),
            ]

            logger.info("[DOCREADER] channel_init target=%s buffer_mb=50", self.target)
            self._async_channel = grpc.aio.insecure_channel(
                self.target,
                options=channel_options,
            )
            self._async_stub = docreader_pb2_grpc.DocReaderStub(self._async_channel)
            return self._async_stub

    async def close(self) -> None:
        """Đóng kênh kết nối gRPC khi tắt server hoặc reload lifespan."""
        async with self._lock:
            if self._async_channel is not None:
                logger.info("[DOCREADER] channel_closing target=%s", self.target)
                await self._async_channel.close()
                self._async_channel = None
                self._async_stub = None

    # -------------------------------------------------------------------------
    # CORE PARSE / READ METHOD (ASYNC)
    # -------------------------------------------------------------------------

    async def read(
        self,
        file_content: bytes,
        file_name: str,
        file_type: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> DocReaderResult:
        """
        Phân giải nội dung tệp nhị phân sang Markdown qua gRPC AnyDoc.

        Args:
            file_content: Mảng byte dữ liệu nhị phân của tệp.
            file_name: Tên tệp gốc (ví dụ: 'Project_Charter_2026.docx').
            file_type: Loại định dạng (tùy chọn, nếu None sẽ tự suy từ file_name).
            timeout: Thời gian chờ tối đa (giây).

        Returns:
            DocReaderResult chứa markdown_content hoặc error nếu thất bại.
        """
        start_time = time.perf_counter()
        clean_filename = file_name.strip() if file_name else "unknown_document"
        ext = self.extract_extension(clean_filename)

        # ---------------------------------------------------------------------
        # GATE 1: KIỂM TRA ĐUÔI TỆP HỢP LỆ (FILE EXTENSION GATE)
        # ---------------------------------------------------------------------
        if not self.is_supported_file(clean_filename):
            valid_list = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
            err_msg = (
                f"Định dạng tệp '{ext or '(không có đuôi)'}' không được hỗ trợ. "
                f"Hệ thống chỉ xử lý các tệp tài liệu: {valid_list}"
            )
            logger.warning("[DOCREADER] rejected reason=unsupported_extension file=%r ext=%s", clean_filename, ext or "-")
            return DocReaderResult(
                success=False,
                file_name=clean_filename,
                file_type=ext.lstrip("."),
                error=err_msg,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        # ---------------------------------------------------------------------
        # GATE 2: KIỂM TRA DUNG LƯỢNG TỆP (FILE SIZE GATE <= 50MB)
        # ---------------------------------------------------------------------
        file_size = len(file_content) if file_content else 0
        if file_size == 0:
            return DocReaderResult(
                success=False,
                file_name=clean_filename,
                file_type=ext.lstrip("."),
                error="Tệp rỗng (0 bytes), không thể phân giải.",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        if file_size > MAX_FILE_SIZE_BYTES:
            size_mb = file_size / (1024 * 1024)
            err_msg = f"Kích thước tệp ({size_mb:.2f}MB) vượt quá giới hạn tối đa cho phép (50MB)."
            logger.warning("[DOCREADER] rejected reason=size_exceeded file=%r size_mb=%.2f", clean_filename, size_mb)
            return DocReaderResult(
                success=False,
                file_name=clean_filename,
                file_type=ext.lstrip("."),
                error=err_msg,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        # Xác định file_type cho Protobuf (bỏ dấu chấm: .docx -> docx)
        inferred_type = (file_type or ext.lstrip(".")).lower()
        effective_timeout = timeout or self.timeout

        # ---------------------------------------------------------------------
        # THỰC THI GỌI gRPC SANG WEKNORA-DOCREADER
        # -------------------------------------------------------------------------
        try:
            stub = await self._get_stub()
            req = docreader_pb2.ReadRequest(
                file_content=file_content,
                file_name=clean_filename,
                file_type=inferred_type,
            )

            logger.info(
                "[DOCREADER] request file=%r size_kb=%.1f type=%s target=%s",
                clean_filename,
                file_size / 1024,
                inferred_type,
                self.target,
            )

            resp = await stub.Read(req, timeout=effective_timeout)
            exec_ms = (time.perf_counter() - start_time) * 1000

            if resp.error:
                logger.error("[DOCREADER] server_error file=%r error=%s", clean_filename, resp.error)
                return DocReaderResult(
                    success=False,
                    file_name=clean_filename,
                    file_type=inferred_type,
                    error=resp.error,
                    metadata=dict(resp.metadata or {}),
                    execution_time_ms=exec_ms,
                )

            md_text = resp.markdown_content or ""
            logger.info(
                "[DOCREADER] parsed file=%r chars=%d duration_ms=%.1f",
                clean_filename,
                len(md_text),
                exec_ms,
            )

            return DocReaderResult(
                success=True,
                markdown_content=md_text,
                file_name=clean_filename,
                file_type=inferred_type,
                metadata=dict(resp.metadata or {}),
                execution_time_ms=exec_ms,
            )

        except grpc.aio.AioRpcError as rpc_err:
            exec_ms = (time.perf_counter() - start_time) * 1000
            code = rpc_err.code()
            details = rpc_err.details() or str(rpc_err)
            err_msg = f"Lỗi kết nối gRPC AnyDoc ({code}): {details}"
            logger.error("[DOCREADER] rpc_error file=%r code=%s details=%s", clean_filename, code, details)
            return DocReaderResult(
                success=False,
                file_name=clean_filename,
                file_type=inferred_type,
                error=err_msg,
                execution_time_ms=exec_ms,
            )
        except asyncio.TimeoutError:
            exec_ms = (time.perf_counter() - start_time) * 1000
            err_msg = f"Timeout khi phân giải tệp sau {effective_timeout}s."
            logger.error("[DOCREADER] timeout file=%r timeout_s=%s", clean_filename, effective_timeout)
            return DocReaderResult(
                success=False,
                file_name=clean_filename,
                file_type=inferred_type,
                error=err_msg,
                execution_time_ms=exec_ms,
            )
        except Exception as e:
            exec_ms = (time.perf_counter() - start_time) * 1000
            err_msg = f"Ngoại lệ không xác định khi phân giải tệp: {e}"
            logger.error("[DOCREADER] error file=%r error=%s", clean_filename, e, exc_info=True)
            return DocReaderResult(
                success=False,
                file_name=clean_filename,
                file_type=inferred_type,
                error=err_msg,
                execution_time_ms=exec_ms,
            )

    # -------------------------------------------------------------------------
    # SYNC WRAPPER
    # -------------------------------------------------------------------------

    def read_sync(
        self,
        file_content: bytes,
        file_name: str,
        file_type: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> DocReaderResult:
        """Hàm bọc đồng bộ (Sync Wrapper) cho các tác vụ CLI hoặc background thread."""
        try:
            loop = asyncio.get_running_loop()
            # Nếu đang trong event loop, chạy qua asyncio task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run,
                    self.read(file_content, file_name, file_type, timeout),
                ).result()
        except RuntimeError:
            return asyncio.run(self.read(file_content, file_name, file_type, timeout))


# ==============================================================================
# 4. GLOBAL SERVICE INSTANCE
# ==============================================================================

docreader_service = DocReaderService()
