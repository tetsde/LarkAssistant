"""
HiLark - Tenant Token Refresh Sweeper
=====================================
Vị trí: server/services/auth/tenant_refresh_sweeper.py

Thay thế `start_token_refresh_loop()` (GĐ5 kế hoạch Tenant Resolution & Token Fix).

Vì sao phải thay:
    Loop cũ duyệt collection `lark_app_credentials` rồi tự tay so `expires_at` và gọi
    `refresh_user_token()`. Nó trùng lặp một nửa trách nhiệm của token broker và vẫn
    giữ nhánh fallback "legacy token trong .env" — tức là có thể xoay vòng token của
    doanh nghiệp khác.

Cơ chế mới:
    Sweeper chỉ hỏi broker `await token_broker.get(tenant_key, "user")` cho từng tenant
    `status="ready"`. Broker đã có buffer 300s và single-flight lock, nên việc "còn hạn
    hay không" do broker quyết định; sweeper lo phần còn lại: chạy định kỳ, không bao giờ
    chết vì một tenant hỏng, và chỉ ghi warning khi thiếu/không lấy được token.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from core.tenant_errors import TenantResolutionError, TokenUnavailable, UserTokenMissing

logger = logging.getLogger("hilark.token_sweeper")

# Chu kỳ quét mặc định: 10 phút (token user sống ~2h, buffer broker 300s).
DEFAULT_SWEEP_INTERVAL_SECONDS = 600.0


class TenantTokenSweeper:
    def __init__(
        self,
        interval_seconds: float = DEFAULT_SWEEP_INTERVAL_SECONDS,
        tenant_filter: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.interval_seconds = float(interval_seconds)
        # Mặc định chỉ giữ tenant đang được phục vụ. `provisioning_failed` không được
        # quét vì chưa có tài nguyên; `inactive`/`uninstalled` cố ý để token chết tự nhiên.
        self.tenant_filter = tenant_filter or {"status": "ready"}
        self._stop_event: Optional[asyncio.Event] = None
        self._task: Optional[asyncio.Task] = None
        self._last_result: Dict[str, Any] = {}

    # -------------------------------------------------------------------------
    # Một vòng quét (tách ra để test không cần chờ chu kỳ)
    # -------------------------------------------------------------------------

    async def _ready_tenant_keys(self) -> List[str]:
        from database.db import get_tenants_collection

        col = get_tenants_collection()
        keys: List[str] = []
        cursor = col.find(self.tenant_filter, {"tenant_key": 1, "_id": 0})
        async for doc in cursor:
            tk = doc.get("tenant_key")
            if tk:
                keys.append(str(tk))
        return keys

    async def run_once(self) -> Dict[str, Any]:
        """
        Quét một vòng. Không ném exception: lỗi của từng tenant được gom lại để
        loop nền có thể chạy tiếp ở chu kỳ sau.
        """
        from services.auth.tenant_token_manager import token_broker

        result: Dict[str, Any] = {
            "checked": 0,
            "refreshed_or_valid": 0,
            "user_token_missing": 0,
            "unavailable": 0,
            "other_errors": 0,
            "errors": [],
        }
        try:
            tenant_keys = await self._ready_tenant_keys()
        except Exception as exc:  # DB lỗi thì chu kỳ sau thử lại
            logger.warning("⚠️ [SWEEPER] Không đọc được danh sách tenant: %s", exc)
            result["other_errors"] = 1
            result["errors"].append(f"list_tenants: {exc}")
            self._last_result = result
            return result

        for tenant_key in tenant_keys:
            result["checked"] += 1
            try:
                await token_broker.get(tenant_key, "user")
                result["refreshed_or_valid"] += 1
            except UserTokenMissing as exc:
                # Chưa uỷ quyền / refresh_token đã chết: cần người dùng login lại.
                result["user_token_missing"] += 1
                result["errors"].append(f"{tenant_key}: user_token_missing")
                logger.warning(
                    "⚠️ [SWEEPER] tenant '%s' chưa có User Token hợp lệ, cần uỷ quyền lại "
                    "qua /auth/lark/login (%s)",
                    tenant_key,
                    exc,
                )
            except TokenUnavailable as exc:
                result["unavailable"] += 1
                result["errors"].append(f"{tenant_key}: token_unavailable")
                logger.warning(
                    "⚠️ [SWEEPER] tenant '%s' không lấy được user token lần này: %s",
                    tenant_key,
                    exc,
                )
            except TenantResolutionError as exc:
                # Tenant bị xoá/uninstalled giữa chu kỳ — bỏ qua, không dừng loop.
                result["other_errors"] += 1
                result["errors"].append(f"{tenant_key}: {type(exc).__name__}")
                logger.info(
                    "ℹ️ [SWEEPER] Bỏ qua tenant '%s' (%s: %s)",
                    tenant_key,
                    type(exc).__name__,
                    exc,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - network/DB bất định
                result["other_errors"] += 1
                result["errors"].append(f"{tenant_key}: {exc}")
                logger.warning(
                    "⚠️ [SWEEPER] Lỗi không phân loại cho tenant '%s': %s", tenant_key, exc
                )

        logger.info(
            "🧹 [SWEEPER] completed checked=%d ok=%d missing=%d unavailable=%d other=%d",
            result["checked"],
            result["refreshed_or_valid"],
            result["user_token_missing"],
            result["unavailable"],
            result["other_errors"],
        )
        self._last_result = result
        return result

    # -------------------------------------------------------------------------
    # Vòng lặp nền
    # -------------------------------------------------------------------------

    async def loop(self) -> None:
        """Chạy cho tới khi `stop()` được gọi; không được tự kết thúc vì một tenant hỏng."""
        self._stop_event = self._stop_event or asyncio.Event()
        logger.info(
            "🔄 [SWEEPER] Khởi động tenant token sweeper (chu kỳ %.0fs, filter=%s)",
            self.interval_seconds,
            self.tenant_filter,
        )
        # Chờ server startup xong rồi quét ngay lần đầu để token vừa login không bị bỏ.
        if not await self._sleep_or_stop(5.0):
            return
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                logger.info("⏹️ [SWEEPER] Dừng vòng lặp quét token.")
                raise
            except Exception as exc:  # pragma: no cover - loop phải sống sót
                logger.warning("⚠️ [SWEEPER] Chu kỳ lỗi: %s", exc)
            if not await self._sleep_or_stop(self.interval_seconds):
                return
        logger.info("⏹️ [SWEEPER] Vòng lặp quét token đã dừng.")

    async def _sleep_or_stop(self, seconds: float) -> bool:
        """True nếu ngủ đủ chu kỳ, False nếu `stop()` được gọi giữa chừng."""
        assert self._stop_event is not None
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
            return False
        except asyncio.TimeoutError:
            return True

    def start(self) -> asyncio.Task:
        """Khởi động sweeper trên event loop đang chạy (gọi từ FastAPI lifespan)."""
        if self._task and not self._task.done():
            return self._task
        self._stop_event = asyncio.Event()
        self._task = asyncio.get_running_loop().create_task(self.loop())
        return self._task

    def stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()

    @property
    def last_result(self) -> Dict[str, Any]:
        return dict(self._last_result)


sweeper = TenantTokenSweeper()
"""Singleton sweeper dùng cho production lifespan."""


async def start_tenant_token_sweeper(
    interval_seconds: Optional[float] = None,
) -> asyncio.Task:
    """Điểm vào tương đương `start_token_refresh_loop()` nhưng tenant-scoped."""
    target = sweeper
    if interval_seconds is not None:
        target = TenantTokenSweeper(interval_seconds=interval_seconds)
    return target.start()


__all__ = [
    "TenantTokenSweeper",
    "sweeper",
    "start_tenant_token_sweeper",
    "DEFAULT_SWEEP_INTERVAL_SECONDS",
]
