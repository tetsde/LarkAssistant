"""
HiLark - Tenant Token Broker (Multi-Tenant Centralized Token Orchestrator)
==========================================================================
Vị trí: server/services/auth/tenant_token_manager.py

Điểm tiếp cận DUY NHẤT cho mọi service cần token Lark.

Bốn bảo đảm của tầng này:
  1. **Một event loop**: mọi thao tác token chạy trên `core.token_loop`, nên lock/cache
     không bao giờ bị chạm từ hai loop (nguyên nhân gây treo trước đây).
  2. **Khoá cache đủ ba chiều**: (tenant_key, app_id, kind). Trước đây khoá chỉ có
     tenant_key (và `bitable` còn cache không khoá nào), nên tenant B có thể nhận token
     của tenant A.
  3. **Không fallback**: thiếu tenant_key hoặc thiếu credential của chính tenant đó là
     raise exception có kiểu. Không mượn App khác, không đọc `.env`.
  4. **Single-flight**: mỗi khoá có lock riêng, double-check sau khi lấy lock.

`kind`:
  - "app"    : app_access_token (tuỳ mode)
  - "tenant" : tenant_access_token của bot ("bot" là alias để tương thích)
  - "user"   : user_access_token theo OAuth của admin tenant

Lịch sử:
  - 2026-11-02: Initial implementation (WS1)
  - 2026-11-02: Giai đoạn 1 - chuyển thành broker một loop, khoá cache 3 chiều,
                bỏ raise "chỉ hỗ trợ ISV" ở nhánh bot token, thêm provider Custom App.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from core.config import settings
from core.http_client import get_http_client
from core.tenant_errors import (
    AppCredentialMissing,
    TenantContextMissing,
    TokenUnavailable,
    UserTokenMissing,
)
from core import token_loop
from models.auth import TokenCacheEntry, TokenType
from services.tenancy.tenant_resolver import tenant_resolver

logger = logging.getLogger("hilark.tenant_token_manager")
logger.setLevel(logging.INFO)

# (tenant_key, app_id, kind)
CacheKey = Tuple[str, str, str]

_ALIAS = {"bot": "tenant"}
KINDS = ("app", "tenant", "user")


def _normalize_kind(token_type: str) -> str:
    kind = _ALIAS.get(str(token_type), str(token_type))
    if kind not in KINDS:
        raise ValueError(f"Loại token không được hỗ trợ: '{token_type}'")
    return kind


async def _post_for_token(url: str, payload: Dict[str, Any], *, tenant_key: str, kind: str) -> Tuple[str, float]:
    """
    Gọi một endpoint cấp token của Lark và trả về (token, expires_at).

    Raise `TokenUnavailable` kèm mã lỗi Lark khi Lark từ chối - không trả chuỗi rỗng,
    vì chuỗi rỗng khiến tầng trên báo sai nguyên nhân (PermissionError không rõ lý do).
    """
    try:
        client = get_http_client()
        resp = await client.post(url, json=payload, timeout=15.0)
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise TokenUnavailable(
            f"Không gọi được endpoint cấp token Lark ({exc.__class__.__name__}): {exc}",
            tenant_key=tenant_key,
            kind=kind,
        ) from exc

    code = data.get("code")
    token_key = {"app": "app_access_token", "tenant": "tenant_access_token"}.get(kind)
    token = data.get(token_key) if token_key else None
    if code != 0 or not token:
        raise TokenUnavailable(
            f"Lark từ chối cấp {kind} token: code={code}, msg={data.get('msg') or data.get('message')}",
            tenant_key=tenant_key,
            kind=kind,
            lark_code=code if isinstance(code, int) else None,
        )
    return token, time.time() + float(data.get("expire", 7200))


class CustomAppProvider:
    """Cấp app/tenant access token cho Custom App theo đúng cặp (app_id, app_secret)."""

    async def app_token(self, app_id: str, app_secret: str, tenant_key: str) -> Tuple[str, float]:
        return await _post_for_token(
            f"{settings.LARK_DOMAIN}/open-apis/auth/v3/app_access_token/internal",
            {"app_id": app_id, "app_secret": app_secret},
            tenant_key=tenant_key,
            kind="app",
        )

    async def tenant_token(self, app_id: str, app_secret: str, tenant_key: str) -> Tuple[str, float]:
        return await _post_for_token(
            f"{settings.LARK_DOMAIN}/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": app_id, "app_secret": app_secret},
            tenant_key=tenant_key,
            kind="tenant",
        )


class ISVProvider:
    """ISV/Marketplace: ủy quyền cho isv_token_service (app_ticket + tenant_key)."""

    async def app_token(self, app_id: str, app_secret: str, tenant_key: str) -> Tuple[str, float]:
        from services.auth.isv_token_service import isv_token_service

        token = await isv_token_service.get_app_access_token()
        if not token:
            raise TokenUnavailable(
                "isv_token_service không trả về app_access_token.", tenant_key=tenant_key, kind="app"
            )
        return token, time.time() + 7200

    async def tenant_token(self, app_id: str, app_secret: str, tenant_key: str) -> Tuple[str, float]:
        from services.auth.isv_token_service import isv_token_service

        token = await isv_token_service.get_tenant_access_token(tenant_key=tenant_key, force_refresh=False)
        if not token:
            raise TokenUnavailable(
                f"isv_token_service không trả về tenant_access_token cho tenant '{tenant_key}'.",
                tenant_key=tenant_key,
                kind="tenant",
            )
        cache = isv_token_service._tenant_tokens.get(tenant_key, {})
        return token, float(cache.get("expires_at") or time.time() + 7200)


class UserTokenProvider:
    """User access token của admin tenant, lưu trong `lark_auth` theo (app_id, tenant_key)."""

    async def fetch(self, app_id: str, app_secret: str, tenant_key: str) -> Tuple[str, float]:
        from services.auth.token_service import token_service

        token = await token_service.get_valid_user_token(tenant_key=tenant_key, app_id=app_id)
        if not token:
            raise UserTokenMissing(tenant_key, app_id=app_id)

        stored = await token_service.get_stored_token_data(tenant_key=tenant_key, app_id=app_id)
        expires_at = float((stored or {}).get("expires_at") or time.time() + 7200)
        return token, expires_at


class TenantTokenManager:
    """Broker token tập trung; chỉ giữ cache và điều phối, không tự gọi Lark."""

    def __init__(self) -> None:
        self._cache: Dict[CacheKey, TokenCacheEntry] = {}
        self._locks: Dict[CacheKey, asyncio.Lock] = {}
        self._cache_buffer_seconds: float = 300.0
        self.custom_app_provider = CustomAppProvider()
        self.isv_provider = ISVProvider()
        self.user_provider = UserTokenProvider()
        logger.debug("[TOKEN_BROKER] initialized cache_dims=3")

    # -------------------------------------------------------------------------
    # CREDENTIAL LOOKUP
    # -------------------------------------------------------------------------

    async def _credentials_for(self, tenant_key: str) -> Tuple[str, str]:
        """
        Lấy (app_id, app_secret) của CHÍNH tenant_key đó, qua resolver tập trung.

        Không có nhánh "lấy App mới nhất trong DB" và không đọc `.env`: đó là hai đường
        làm một tenant vô tình dùng credential của tenant khác.
        """
        creds = await tenant_resolver.resolve_credentials(tenant_key)
        return creds.app_id, creds.app_secret

    # -------------------------------------------------------------------------
    # CACHE
    # -------------------------------------------------------------------------

    def _get_entry(self, key: CacheKey) -> Optional[TokenCacheEntry]:
        return self._cache.get(key)

    def _set_entry(self, key: CacheKey, entry: TokenCacheEntry) -> None:
        self._cache[key] = entry
        logger.debug(
            "[TOKEN_BROKER] cached kind=%s tenant=%s app=%s ttl_s=%d",
            key[2], key[0], key[1], int(entry.expires_at - time.time()),
        )

    def _drop_entries(self, tenant_key: str, kind: Optional[str] = None) -> int:
        removed = 0
        for key in list(self._cache):
            if key[0] == tenant_key and (kind is None or key[2] == kind):
                self._cache.pop(key, None)
                removed += 1
        return removed

    def _get_or_create_lock(self, key: CacheKey) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    # -------------------------------------------------------------------------
    # FETCH
    # -------------------------------------------------------------------------

    def _isv_mode(self) -> bool:
        return bool(getattr(settings, "IS_ISV_MODE", False))

    async def _fetch_fresh(self, tenant_key: str, app_id: str, app_secret: str, kind: str) -> TokenCacheEntry:
        if kind == "user":
            token, expires_at = await self.user_provider.fetch(app_id, app_secret, tenant_key)
        elif self._isv_mode():
            token, expires_at = await (
                self.isv_provider.app_token(app_id, app_secret, tenant_key)
                if kind == "app"
                else self.isv_provider.tenant_token(app_id, app_secret, tenant_key)
            )
        else:
            token, expires_at = await (
                self.custom_app_provider.app_token(app_id, app_secret, tenant_key)
                if kind == "app"
                else self.custom_app_provider.tenant_token(app_id, app_secret, tenant_key)
            )

        if not token:
            raise TokenUnavailable(
                f"Provider trả về {kind} token rỗng cho tenant '{tenant_key}'.",
                tenant_key=tenant_key,
                kind=kind,
            )
        return TokenCacheEntry(
            token=token,
            expires_at=expires_at,
            tenant_key=tenant_key,
            token_type=TokenType(kind),
            app_id=app_id,
        )

    async def _get_on_token_loop(
        self,
        tenant_key: str,
        kind: str,
        force_refresh: bool,
        app_id_hint: Optional[str],
    ) -> str:
        app_id, app_secret = await self._credentials_for(tenant_key)
        if app_id_hint and app_id_hint != app_id:
            raise TokenUnavailable(
                f"App '{app_id_hint}' không phải App đã đăng ký của tenant '{tenant_key}' "
                f"(App thực tế: '{app_id}').",
                tenant_key=tenant_key,
                kind=kind,
            )

        key: CacheKey = (tenant_key, app_id, kind)

        if not force_refresh:
            cached = self._get_entry(key)
            if cached and not cached.is_expired(buffer_seconds=self._cache_buffer_seconds):
                return cached.token

        async with self._get_or_create_lock(key):
            if not force_refresh:
                cached = self._get_entry(key)
                if cached and not cached.is_expired(buffer_seconds=self._cache_buffer_seconds):
                    return cached.token

            logger.info(
                "[TOKEN_BROKER] fetch kind=%s tenant=%s app=%s force=%s",
                kind, tenant_key, app_id, bool(force_refresh),
            )
            try:
                entry = await self._fetch_fresh(tenant_key, app_id, app_secret, kind)
            except Exception:
                # Không để lại entry cũ đã hỏng trong cache.
                self._drop_entries(tenant_key, kind)
                raise
            self._set_entry(key, entry)
            return entry.token

    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    async def get(self, tenant_key: str, kind: str = "user", **kwargs) -> str:
        """API công khai ngắn gọn theo hợp đồng broker: `await get(tenant_key, "tenant")`."""
        return await self.get_token(tenant_key, kind, **kwargs)

    def get_sync(self, tenant_key: str, kind: str = "user", **kwargs) -> str:
        """Phiên bản blocking tương ứng, dùng cho caller sync (bitable, client)."""
        return self.get_token_sync(tenant_key, kind, **kwargs)

    async def invalidate(self, tenant_key: str, kind: Optional[str] = None) -> None:
        """Xoá cache của tenant theo tên API của kế hoạch (`invalidate(tenant_key, kind=None)`).

        `kind=None` xoá **mọi** key có `tenant_key` đó, bất kể App nào đang gắn với tenant.
        """
        await self.invalidate_tenant_cache(tenant_key, kind)

    async def get_token(
        self,
        tenant_key: str,
        token_type: str = "user",
        force_refresh: bool = False,
        app_id: Optional[str] = None,
    ) -> str:
        """
        Lấy token hợp lệ cho một tenant. Entry point công khai duy nhất.

        Raises:
            TenantContextMissing: tenant_key rỗng/không hợp lệ.
            AppCredentialMissing: tenant chưa có credential trong DB.
            UserTokenMissing: cần uỷ quyền lại (chỉ kind "user").
            TokenUnavailable: Lark từ chối hoặc lỗi mạng.
        """
        if not tenant_key or not isinstance(tenant_key, str) or not tenant_key.strip():
            raise TenantContextMissing("get_token() yêu cầu tenant_key tường minh.")
        kind = _normalize_kind(token_type)
        return await token_loop.asubmit(
            self._get_on_token_loop(tenant_key.strip(), kind, bool(force_refresh), app_id)
        )

    def get_token_sync(
        self,
        tenant_key: str,
        token_type: str = "user",
        force_refresh: bool = False,
        app_id: Optional[str] = None,
        timeout: float = 15.0,
    ) -> str:
        """
        Phiên bản blocking cho caller sync (bitable, client).

        Thay chỗ cho `asyncio.run(tenant_token_manager.get_token(...))` từng gây treo:
        coroutine được đưa lên token loop rồi chờ qua future, không tạo loop mới.
        """
        if not tenant_key or not isinstance(tenant_key, str) or not tenant_key.strip():
            raise TenantContextMissing("get_token_sync() yêu cầu tenant_key tường minh.")
        kind = _normalize_kind(token_type)
        try:
            return token_loop.submit(
                self._get_on_token_loop(tenant_key.strip(), kind, bool(force_refresh), app_id),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:  # pragma: no cover - phụ thuộc timing
            raise TokenUnavailable(
                f"Hết thời gian chờ {kind} token cho tenant '{tenant_key}'.",
                tenant_key=tenant_key,
                kind=kind,
            ) from exc
        except TimeoutError as exc:  # concurrent.futures.TimeoutError trên Py >= 3.11
            raise TokenUnavailable(
                f"Hết thời gian chờ {kind} token cho tenant '{tenant_key}'.",
                tenant_key=tenant_key,
                kind=kind,
            ) from exc

    # Giữ tên cũ cho các caller đang dùng.
    async def get_user_token(self, tenant_key: str, force_refresh: bool = False) -> str:
        return await self.get_token(tenant_key, "user", force_refresh)

    async def get_bot_token(self, tenant_key: str, force_refresh: bool = False) -> str:
        return await self.get_token(tenant_key, "bot", force_refresh)

    # -------------------------------------------------------------------------
    # PUBLIC API: CACHE MANAGEMENT
    # -------------------------------------------------------------------------

    async def invalidate_tenant_cache(
        self,
        tenant_key: str,
        token_type: Optional[str] = None,
    ) -> None:
        """
        Xoá cache của một tenant. Gọi khi uninstall/stop app, đăng ký lại credential,
        hoặc khi setup chuyển sang `ready`.

        `token_type` nhận "user"/"bot"/"tenant"/"app"; None = xoá hết.
        """
        if not tenant_key:
            raise TenantContextMissing("invalidate_tenant_cache() yêu cầu tenant_key.")
        kind = _normalize_kind(token_type) if token_type else None
        removed = await token_loop.asubmit(self._invalidate_on_token_loop(tenant_key.strip(), kind))
        logger.info(
            "[TOKEN_BROKER] cache_invalidated kind=%s tenant=%s entries=%d",
            token_type or "all", tenant_key, removed,
        )

    async def _invalidate_on_token_loop(self, tenant_key: str, kind: Optional[str]) -> int:
        return self._drop_entries(tenant_key, kind)

    def invalidate_tenant_cache_sync(self, tenant_key: str, token_type: Optional[str] = None) -> int:
        """Phiên bản blocking cho caller sync (lifecycle handler chạy trong thread)."""
        if not tenant_key:
            raise TenantContextMissing("invalidate_tenant_cache_sync() yêu cầu tenant_key.")
        kind = _normalize_kind(token_type) if token_type else None
        return token_loop.submit(self._invalidate_on_token_loop(tenant_key.strip(), kind), timeout=5.0)

    # -------------------------------------------------------------------------
    # PUBLIC API: MONITORING
    # -------------------------------------------------------------------------

    def _count_by_kind(self, kind: str) -> int:
        return sum(1 for key in self._cache if key[2] == kind)

    def get_cache_stats(self) -> Dict[str, Any]:
        """Thống kê cache cho monitoring/debugging."""
        tenants = {key[0] for key in self._cache}
        return {
            "user_tokens_cached": self._count_by_kind("user"),
            "bot_tokens_cached": self._count_by_kind("tenant"),
            "app_tokens_cached": self._count_by_kind("app"),
            "total_tenants_tracked": len(tenants),
            "locks_created": len(self._locks),
            "cache_buffer_seconds": self._cache_buffer_seconds,
        }

    def get_tenant_cache_status(self, tenant_key: str) -> Dict[str, Any]:
        """Trạng thái cache của một tenant (mọi App), dùng cho health/debug."""
        now = time.time()
        result: Dict[str, Any] = {"tenant_key": tenant_key}
        for kind, label in (("user", "user"), ("tenant", "bot"), ("app", "app")):
            entries = [e for key, e in self._cache.items() if key[0] == tenant_key and key[2] == kind]
            best = max(entries, key=lambda e: e.expires_at) if entries else None
            result[f"has_{label}_token"] = best is not None
            result[f"{label}_token_expires_in"] = int(best.expires_at - now) if best else None
            result[f"{label}_token_valid"] = bool(
                best and not best.is_expired(buffer_seconds=self._cache_buffer_seconds)
            )
        return result


# -------------------------------------------------------------------------
# SINGLETON INSTANCE
# -------------------------------------------------------------------------

tenant_token_manager = TenantTokenManager()
"""Singleton broker. Tên cũ giữ nguyên để không phá các caller hiện có."""

token_broker = tenant_token_manager
"""Alias thống nhất theo kiến trúc mới: mọi caller nên dùng `token_broker`."""
