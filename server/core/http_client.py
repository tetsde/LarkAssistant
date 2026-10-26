"""
HiLark Core HTTP Client
=======================
Vị trí: server/core/http_client.py

Mục đích:
    Cung cấp Persistent Singleton `httpx.AsyncClient` với HTTP Keep-Alive & Connection Pooling
    cho toàn bộ hệ thống (WeKnora, JEV, Lark Token Service, LLM Client).

Lợi ích:
    1. Tiết kiệm 100-300ms bắt tay TCP + TLS mỗi request.
    2. Chống rò rỉ socket và cạn kiệt cổng mạng (Socket Exhaustion).
    3. Đóng kết nối sạch sẽ trong vòng đời FastAPI lifespan.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger("hilark.core.http_client")

# Singleton persistent client instance
_http_client: Optional[httpx.AsyncClient] = None

# Cấu hình Connection Pool & Timeout tối ưu cho hệ thống
DEFAULT_LIMITS = httpx.Limits(
    max_keepalive_connections=20,
    max_connections=100,
    keepalive_expiry=30.0,
)
DEFAULT_TIMEOUT = httpx.Timeout(timeout=30.0, connect=10.0)


def get_http_client() -> httpx.AsyncClient:
    """
    Lấy persistent HTTP client dùng chung.
    Tự động khởi tạo lazy nếu client chưa được tạo hoặc đã bị đóng (an toàn cho unit test/scripts).
    """
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            limits=DEFAULT_LIMITS,
            timeout=DEFAULT_TIMEOUT,
        )
        logger.debug("Khởi tạo mới Persistent httpx.AsyncClient (Lazy Init).")
    return _http_client


async def init_http_client() -> httpx.AsyncClient:
    """
    Khởi tạo connection pool trước khi server nhận request.
    Được gọi trong FastAPI lifespan startup.
    """
    client = get_http_client()
    logger.info("✔ [HTTP POOL] Persistent httpx.AsyncClient đã sẵn sàng (Connection Pooling: max=100, keepalive=20).")
    return client


async def close_http_client() -> None:
    """
    Đóng sạch sẽ connection pool và giải phóng toàn bộ sockets.
    Được gọi trong FastAPI lifespan shutdown.
    """
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        try:
            await _http_client.aclose()
            logger.info("✔ [HTTP POOL] Đã đóng persistent httpx.AsyncClient an toàn.")
        except Exception as e:
            logger.warning(f"Lỗi khi đóng httpx.AsyncClient: {e}")
        finally:
            _http_client = None
