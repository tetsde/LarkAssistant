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

import asyncio
import logging
from typing import Dict, Optional

import httpx

logger = logging.getLogger("hilark.core.http_client")

# Map lưu trữ Persistent Client instance theo từng Event Loop (Loop ID -> AsyncClient)
_clients_by_loop: Dict[int, httpx.AsyncClient] = {}

# Cấu hình Connection Pool & Timeout tối ưu cho hệ thống
DEFAULT_LIMITS = httpx.Limits(
    max_keepalive_connections=20,
    max_connections=100,
    keepalive_expiry=30.0,
)
DEFAULT_TIMEOUT = httpx.Timeout(timeout=30.0, connect=10.0)


def get_http_client() -> httpx.AsyncClient:
    """
    Lấy persistent HTTP client theo event loop hiện tại.
    Mỗi event loop (FastAPI Main Loop, Lark WebSocket Thread Loop, Test Loops)
    sở hữu một connection pool riêng để tránh xung đột asyncio.locks giữa các loop.
    """
    try:
        current_loop = asyncio.get_running_loop()
        loop_id = id(current_loop)
    except RuntimeError:
        loop_id = 0

    client = _clients_by_loop.get(loop_id)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            limits=DEFAULT_LIMITS,
            timeout=DEFAULT_TIMEOUT,
        )
        _clients_by_loop[loop_id] = client
        logger.debug(f"Khởi tạo mới Persistent httpx.AsyncClient cho loop {loop_id}.")
    return client


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
    Đóng sạch sẽ connection pool của tất cả event loops và giải phóng toàn bộ sockets.
    Được gọi trong FastAPI lifespan shutdown.
    """
    global _clients_by_loop
    for loop_id, client in list(_clients_by_loop.items()):
        if client and not client.is_closed:
            try:
                await client.aclose()
                logger.info(f"✔ [HTTP POOL] Đã đóng persistent httpx.AsyncClient cho loop {loop_id} an toàn.")
            except Exception as e:
                logger.warning(f"Lỗi khi đóng httpx.AsyncClient loop {loop_id}: {e}")
    _clients_by_loop.clear()
