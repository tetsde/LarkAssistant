"""
HiLark Token Service
====================
Vị trí: server/services/token_service.py

Mục đích:
    Quản lý xác thực OAuth 2.0 / OIDC của Lark Open Platform:
      1. Sinh URL ủy quyền (Authorization URL) với scope `offline_access`.
      2. Đổi mã `code` (Authorization Code) lấy cặp `(access_token, refresh_token)` ban đầu.
      3. Lưu trữ bền vững vào MongoDB collection `lark_auth`.
      4. Tự động xoay vòng làm mới (Single-Use Token Rotation) khi access_token sắp hết hạn (< 10 phút).
      5. Đồng bộ tức thời vào bộ nhớ RAM của `lark_client` mà không cần restart server.
"""

from __future__ import annotations

import asyncio
import logging
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple

import contextlib
import sys 
import httpx

from core.config import settings
from core.http_client import get_http_client
from core.tenant_errors import (
    TenantConfigIncomplete,
    TenantContextMissing,
    TenantNotReady,
    TenantNotFound,
    TenantResolutionError,
    TokenUnavailable,
    UserTokenMissing,
)
from database.db import get_auth_collection, get_current_tenant_key
from services.tenancy.tenant_resolver import tenant_resolver

logger = logging.getLogger("hilark.token_service")
logger.setLevel(logging.INFO)

VIETNAM_TZ = timezone(timedelta(hours=7))


def mask_token_preview(raw_token: Any) -> str:
    """Che giấu giá trị token nguyên văn khi hiển thị ra UI / status."""
    tok = str(raw_token or "").strip()
    if not tok:
        return ""
    if len(tok) > 12:
        return f"{tok[:6]}...{tok[-4:]}"
    return "***"


def _encrypt_auth_secret(raw_value: Any) -> str:
    """Mã hóa AES-256 Fernet cho token lưu vào `lark_auth`; rỗng giữ nguyên rỗng."""
    val = str(raw_value or "").strip()
    if not val:
        return ""
    from services.ai.ai_config_manager import ai_config_manager

    if val.startswith("gAAAAA") and ai_config_manager.decrypt_key(val):
        return val
    return ai_config_manager.encrypt_key(val)


def _decrypt_auth_secret(stored_value: Any, *, encrypted_flag: bool = False) -> str:
    """Giải mã dual-read: hỗ trợ cả bản ghi đã mã hóa Fernet lẫn bản ghi plaintext legacy."""
    val = str(stored_value or "").strip()
    if not val:
        return ""
    if encrypted_flag or val.startswith("gAAAAA"):
        from services.ai.ai_config_manager import ai_config_manager

        return ai_config_manager.decrypt_key(val)
    return val


async def _find_one_sorted(
    col: Any,
    query: Dict[str, Any],
    *,
    sort: Optional[list] = None,
) -> Optional[Dict[str, Any]]:
    """Thực thi `find_one` kèm `sort`, fallback an toàn với collection mock không nhận `sort`."""
    if not sort:
        return await col.find_one(query)
    try:
        return await col.find_one(query, sort=sort)
    except TypeError:
        return await col.find_one(query)


def format_remaining_seconds(seconds: Optional[float]) -> str:
    """Chuyển đổi số giây còn lại thành chuỗi dễ đọc bằng tiếng Việt."""
    if seconds is None:
        return "Không xác định"
    abs_sec = int(abs(seconds))
    days = abs_sec // 86400
    hours = (abs_sec % 86400) // 3600
    minutes = (abs_sec % 3600) // 60
    secs = abs_sec % 60

    parts = []
    if days > 0:
        parts.append(f"{days} ngày")
    if hours > 0:
        parts.append(f"{hours} giờ")
    if minutes > 0 or hours > 0:
        parts.append(f"{minutes} phút")
    parts.append(f"{secs} giây")
    time_str = " ".join(parts)

    if seconds > 0:
        return f"Còn lại {time_str}"
    elif seconds == 0:
        return "Hết hạn ngay lúc này"
    else:
        return f"Đã hết hạn cách đây {time_str}"


class LarkTokenService:
    """Service điều phối toàn bộ vòng đời Token OAuth của Lark."""

    def __init__(self):
        # Lock xoay vòng Single-Use Refresh Token tạo lười TRÊN core.token_loop theo cặp (app_id, tenant_key)
        self._refresh_locks: Dict[Tuple[str, str], asyncio.Lock] = {}

    def _get_refresh_lock(self, app_id: Optional[str], tenant_key: Optional[str]) -> asyncio.Lock:
        """Lấy lock riêng cho cặp `(app_id, tenant_key)` trên `core.token_loop`."""
        key = (str(app_id or "").strip(), str(tenant_key or "").strip())
        lock = self._refresh_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._refresh_locks[key] = lock
        return lock

    def _get_auth_col(self):
        """Lấy auth collection từ MongoDB, hỗ trợ mock từ services.auth_service hoặc services.token_service nếu test patch vào đó."""
        shim_mod = sys.modules.get("services.auth_service") or sys.modules.get("services.token_service")
        if shim_mod and hasattr(shim_mod, "get_auth_collection"):
            fn = getattr(shim_mod, "get_auth_collection")
            if fn is not get_auth_collection:
                return fn()
        return get_auth_collection()

    @contextlib.asynccontextmanager
    async def _get_client_session(self, client: Optional[httpx.AsyncClient] = None):
        """Helper quản lý HTTP client: ưu tiên client được truyền vào hoặc mock trong test,
        ngược lại tái sử dụng persistent connection pool toàn hệ thống.
        """
        if client is not None:
            yield client
            return

        # Kiểm tra mock tại httpx module hoặc mock tại transitional shim services.auth_service
        shim_mod = sys.modules.get("services.auth_service") or sys.modules.get("services.token_service")
        shim_httpx = getattr(shim_mod, "httpx", None) if shim_mod else None
        target_httpx = shim_httpx or httpx

        is_mocked = type(target_httpx.AsyncClient).__name__ in ("MagicMock", "AsyncMock")
        if is_mocked:
            async with target_httpx.AsyncClient() as mocked_client:
                yield mocked_client
            return

        yield get_http_client()

    # -------------------------------------------------------------------------
    # 1. APP ACCESS TOKEN (Cần thiết để gọi các API OAuth OIDC của Lark)
    # -------------------------------------------------------------------------

    async def get_app_access_token(
        self,
        force_refresh: bool = False,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        tenant_key: Optional[str] = None,
    ) -> str:
        """
        Điều phối `app_access_token` thống nhất (Custom App Multi-Tenant):
          - Khi tenant đã liên kết DB (`tenant_key` thực, không phải `pending:...`): đi qua `token_broker.get(tenant_key, "app")`.
          - Chỉ khi setup/exchange trước lúc `link_tenant` truyền tường minh `(app_id, app_secret)`:
            gọi stateless endpoint Custom App `/internal` không cache riêng.
        """
        eff_tenant = str(tenant_key or "").strip()
        is_pending = eff_tenant.startswith("pending:")
        has_explicit_pair = bool(app_id and app_secret)

        if eff_tenant and not is_pending and not has_explicit_pair:
            from services.auth.tenant_token_manager import token_broker

            return await token_broker.get(
                eff_tenant,
                "app",
                force_refresh=force_refresh,
                app_id=app_id,
            )

        if eff_tenant and not is_pending and has_explicit_pair:
            from services.auth.tenant_token_manager import token_broker

            try:
                return await token_broker.get(
                    eff_tenant,
                    "app",
                    force_refresh=force_refresh,
                    app_id=app_id,
                )
            except (TenantConfigIncomplete, TenantNotFound):
                # Chưa link tenant vào DB (hoặc unit test truyền trực tiếp cặp app_id/app_secret)
                pass

        if not has_explicit_pair:
            if not eff_tenant or is_pending:
                raise TenantContextMissing(
                    "get_app_access_token() cần tenant_key hoặc cặp (app_id + app_secret) tường minh."
                )
            raise TenantConfigIncomplete(eff_tenant, ["app_credentials"])

        url = f"{settings.LARK_DOMAIN}/open-apis/auth/v3/app_access_token/internal"
        async with self._get_client_session() as client:
            resp = await client.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=10.0)
            data = resp.json()
            if data.get("code") == 0 and data.get("app_access_token"):
                return str(data.get("app_access_token"))
            raise TokenUnavailable(
                f"Lỗi khi lấy app_access_token từ Lark: code={data.get('code')}, "
                f"msg={data.get('msg') or data.get('message')}",
                tenant_key=eff_tenant or None,
                kind="app",
                lark_code=data.get("code") if isinstance(data.get("code"), int) else None,
            )

    # -------------------------------------------------------------------------
    # 2. SINH URL ỦY QUYỀN (AUTHORIZE URL)
    # -------------------------------------------------------------------------

    def get_authorize_url(
        self,
        redirect_uri: Optional[str] = None,
        state: str = "hilark_oauth",
        scope: Optional[str] = None,
        app_id: Optional[str] = None,
    ) -> str:
        """
        Sinh URL ủy quyền OAuth của Lark để Sếp truy cập từ trình duyệt.
        Bắt buộc kèm scope offline_access để nhận refresh_token.

        `app_id` là BẮT BUỘC: URL ủy quyền phải nêu danh tính App mà người dùng sẽ
        cấp quyền cho. Trước đây khi thiếu app_id, hàm này rơi về `settings.LARK_APP_ID`,
        nên người dùng của doanh nghiệp B có thể unknowingly cấp quyền cho App của
        doanh nghiệp A.
        """
        if not app_id or not str(app_id).strip():
            raise TenantContextMissing(
                "get_authorize_url() yêu cầu app_id của tenant đang yêu cầu ủy quyền "
                "(không được lấy app_id từ .env)."
            )
        target_redirect_uri = redirect_uri or settings.LARK_OAUTH_REDIRECT_URI
        default_scopes = (
            "offline_access "
            "im:message.send_as_user "
            "im:chat:readonly "
            "im:chat "
            "im:message "
            "bitable:app "
            "contact:user.base:readonly "
            "wiki:node:read "
            "wiki:wiki:readonly "
            "docx:document:readonly "
            "drive:drive:readonly"
        )
        target_scope = scope or default_scopes

        base_url = "https://accounts.larksuite.com/open-apis/authen/v1/authorize"
        params = {
            "client_id": str(app_id).strip(),
            "redirect_uri": target_redirect_uri,
            "response_type": "code",
            "scope": target_scope,
            "state": state,
        }
        encoded_query = urllib.parse.urlencode(params)
        return f"{base_url}?{encoded_query}"

    # -------------------------------------------------------------------------
    # 3. ĐỔI AUTHORIZATION CODE LẤY TOKENS (CALLBACK STEP)
    # -------------------------------------------------------------------------

    async def exchange_code_for_token(
        self,
        code: str,
        redirect_uri: Optional[str] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        expected_tenant_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Đổi Authorization Code lấy cặp access_token và refresh_token từ Lark.
        Sau đó lưu vào MongoDB collection `lark_auth`.

        Hợp đồng mới: (app_id + app_secret) bắt buộc, và nếu caller đưa
        `expected_tenant_key` thì tenant_key trả về từ hồ sơ Lark PHẢI khớp. Token của
        doanh nghiệp khác không được ghi nhầm vào tenant đang yêu cầu.
        """
        if not code or not code.strip():
            raise ValueError("Mã authorization code không được để trống!")
        if not app_id or not app_secret:
            raise TenantContextMissing(
                "exchange_code_for_token() cần app_id + app_secret tường minh của tenant "
                "đang ủy quyền; không tự mượn credential từ .env."
            )

        app_token = await self.get_app_access_token(
            app_id=app_id, app_secret=app_secret, tenant_key=expected_tenant_key
        )
        url = f"{settings.LARK_DOMAIN}/open-apis/authen/v1/oidc/access_token"
        headers = {
            "Authorization": f"Bearer {app_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "grant_type": "authorization_code",
            "code": code.strip(),
        }

        async with self._get_client_session() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=15.0)
            data = resp.json()

        if data.get("code") != 0:
            err_msg = data.get("message") or data.get("msg") or "Unknown error"
            logger.error("[OAUTH] code_exchange_failed code=%s msg=%s", data.get("code"), err_msg)
            raise RuntimeError(f"Lark từ chối đổi authorization code: {err_msg} (Mã lỗi {data.get('code')})")

        token_info = data.get("data", {})
        access_token = token_info.get("access_token", "")
        refresh_token = token_info.get("refresh_token", "")
        expires_in = int(token_info.get("expires_in", 7200))
        refresh_expires_in = int(token_info.get("refresh_expires_in", 2592000))
        token_scope = token_info.get("scope", "")

        now = time.time()
        expires_at = now + expires_in
        refresh_expires_at = now + refresh_expires_in

        # Lấy thông tin User profile từ User Token
        user_info = await self._fetch_user_profile(access_token)
        open_id = user_info.get("open_id") or ""
        user_name = user_info.get("name") or "User"
        tenant_key = user_info.get("tenant_key") or ""

        if expected_tenant_key and tenant_key and tenant_key != expected_tenant_key:
            # Người dùng đăng nhập bằng tài khoản doanh nghiệp khác App đang cấu hình.
            raise TenantResolutionError(
                f"Tài khoản Lark vừa ủy quyền thuộc tenant '{tenant_key}', không khớp "
                f"tenant '{expected_tenant_key}' của App '{app_id}'. Không lưu token.",
                tenant_key=expected_tenant_key,
            )
        if not tenant_key:
            tenant_key = expected_tenant_key or ""
        if not (open_id and tenant_key):
            raise TenantConfigIncomplete(
                tenant_key or "?", ["oauth_user_open_id", "oauth_tenant_key"]
            )

        # Đóng gói document lưu vào MongoDB (mã hóa AES-256 Fernet tại nghỉ).
        # Không còn ghi vào `_id="primary_user_token"` vì document đó là danh tính dùng chung.
        token_doc_id = f"lark_app:{app_id}:user:{tenant_key}:{open_id}"
        doc = {
            "_id": token_doc_id,
            "app_id": app_id or "",
            "access_token": _encrypt_auth_secret(access_token),
            "refresh_token": _encrypt_auth_secret(refresh_token),
            "token_encrypted": True,
            "expires_in": expires_in,
            "refresh_expires_in": refresh_expires_in,
            "expires_at": expires_at,
            "refresh_expires_at": refresh_expires_at,
            "open_id": open_id,
            "user_name": user_name,
            "tenant_key": tenant_key,
            "avatar_url": user_info.get("avatar_url", ""),
            "email": user_info.get("email", ""),
            "scope": token_scope,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Lưu nguyên tử vào MongoDB theo (app_id, tenant_key, open_id)
        col = self._get_auth_col()
        await col.update_one(
            {"_id": token_doc_id},
            {"$set": doc},
            upsert=True,
        )

        # Vô hiệu hoá cache "user" trên token_broker cho tenant vừa OAuth lại
        try:
            from services.auth.tenant_token_manager import token_broker
            token_broker._drop_entries(tenant_key, "user")
        except Exception:
            pass

        logger.info(
            "[OAUTH] token_saved open_id=%s tenant=%s expires_in_s=%d refresh_expires_in_s=%d",
            open_id,
            tenant_key,
            expires_in,
            refresh_expires_in,
        )

        return {
            "success": True,
            "user_name": user_name,
            "open_id": open_id,
            "tenant_key": tenant_key,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "refresh_expires_in": refresh_expires_in,
            "expires_at_readable": datetime.fromtimestamp(expires_at, tz=VIETNAM_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "refresh_expires_at_readable": datetime.fromtimestamp(refresh_expires_at, tz=VIETNAM_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        }

    # -------------------------------------------------------------------------
    # 4. TỰ ĐỘNG XOAY VÒNG REFRESH TOKEN (SINGLE-USE ROTATION)
    # -------------------------------------------------------------------------

    async def refresh_user_token(
        self,
        force: bool = False,
        tenant_key: Optional[str] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Gọi API Lark để đổi refresh_token lấy cặp (access_token, refresh_token) MỚI.
        Chạy 100% trên `core.token_loop` với lock riêng theo cặp `(app_id, tenant_key)`.
        """
        from core import token_loop

        eff_tenant = (tenant_key or "").strip() or (get_current_tenant_key() if tenant_key is None else None)
        eff_app = (app_id or "").strip() or None
        if not eff_tenant and not eff_app:
            raise TenantContextMissing("refresh_user_token() yêu cầu tenant_key hoặc app_id.")

        return await token_loop.asubmit(
            self._refresh_user_token_on_loop(
                force=force,
                tenant_key=eff_tenant,
                app_id=eff_app,
                app_secret=app_secret,
            )
        )

    async def _refresh_user_token_on_loop(
        self,
        *,
        force: bool = False,
        tenant_key: Optional[str] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not tenant_key and not app_id:
            raise TenantContextMissing("refresh_user_token() yêu cầu tenant_key hoặc app_id.")
        lock_app_id = app_id
        lock_tenant = tenant_key
        if lock_tenant and not lock_app_id:
            try:
                creds = await tenant_resolver.resolve_credentials(lock_tenant)
                lock_app_id = creds.app_id
            except TenantResolutionError:
                pass

        async with self._get_refresh_lock(lock_app_id, lock_tenant):
            stored_data = await self.get_stored_token_data(tenant_key=tenant_key, app_id=app_id)
            if not stored_data or not stored_data.get("refresh_token") or not stored_data.get("_id"):
                raise ValueError("Không tìm thấy refresh_token hợp lệ trong MongoDB để làm mới! Vui lòng cấp quyền qua /auth/lark/login trước.")

            doc_id = stored_data["_id"]
            current_refresh_token = stored_data["refresh_token"]
            now = time.time()

            # Nếu không phải force và token vẫn còn hạn > 10 phút thì không cần refresh
            if not force and stored_data.get("expires_at", 0) - now > 600:
                logger.debug("[TOKEN_SERVICE] refresh_skipped reason=still_valid")
                return {"success": True, "action": "skipped", "access_token": stored_data["access_token"]}

            effective_tenant = tenant_key or stored_data.get("tenant_key")
            effective_app_id = app_id or stored_data.get("app_id")
            if not app_secret and effective_tenant:
                try:
                    creds = await tenant_resolver.resolve_credentials(effective_tenant)
                    if not effective_app_id or effective_app_id == creds.app_id:
                        effective_app_id = creds.app_id
                        app_secret = creds.app_secret
                except TenantResolutionError:
                    pass
            if not app_secret and effective_app_id and not effective_tenant:
                try:
                    from services.lark_app_service import lark_app_service
                    app_record = await lark_app_service.get_by_app_id(effective_app_id)
                    app_secret = app_record.get("app_secret") if app_record else None
                except Exception as exc:
                    logger.warning("[TOKEN_SERVICE] app_secret_lookup_failed app=%s error=%s", effective_app_id, exc)

            app_token = await self.get_app_access_token(
                app_id=effective_app_id,
                app_secret=app_secret,
                tenant_key=effective_tenant,
            )
            url = f"{settings.LARK_DOMAIN}/open-apis/authen/v1/oidc/refresh_access_token"
            headers = {
                "Authorization": f"Bearer {app_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": current_refresh_token,
            }

            async with self._get_client_session() as client:
                resp = await client.post(url, headers=headers, json=payload, timeout=15.0)
                data = resp.json()

            if data.get("code") != 0:
                err_code = data.get("code")
                err_msg = data.get("message") or data.get("msg") or "Refresh token error"
                logger.error("[TOKEN_SERVICE] refresh_failed code=%s msg=%s", err_code, err_msg)
                if err_code in (20024, 20038):
                    try:
                        col = self._get_auth_col()
                        await col.update_one(
                            {"_id": doc_id},
                            {"$set": {
                                "status": "invalid_refresh_token",
                                "invalid_reason": err_msg,
                                "invalidated_at": datetime.now(timezone.utc).isoformat(),
                                "updated_at": datetime.now(timezone.utc).isoformat()
                            }},
                        )
                    except Exception:
                        pass
                raise RuntimeError(f"Lark từ chối refresh token: {err_msg} (Mã lỗi {err_code})")

            token_info = data.get("data", {})
            new_access_token = token_info.get("access_token", "")
            new_refresh_token = token_info.get("refresh_token", "")
            expires_in = int(token_info.get("expires_in", 7200))
            refresh_expires_in = int(token_info.get("refresh_expires_in", 2592000))

            expires_at = now + expires_in
            refresh_expires_at = now + refresh_expires_in

            update_fields = {
                "access_token": _encrypt_auth_secret(new_access_token),
                "refresh_token": _encrypt_auth_secret(new_refresh_token),
                "token_encrypted": True,
                "expires_in": expires_in,
                "refresh_expires_in": refresh_expires_in,
                "expires_at": expires_at,
                "refresh_expires_at": refresh_expires_at,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            col = self._get_auth_col()
            await col.update_one(
                {"_id": doc_id},
                {"$set": update_fields},
            )

            if effective_tenant:
                from services.auth.tenant_token_manager import token_broker
                token_broker._drop_entries(effective_tenant, "user")

            logger.info(
                "[TOKEN_SERVICE] token_rotated app=%s tenant=%s expires_in_s=%d refresh_expires_in_s=%d",
                effective_app_id,
                effective_tenant,
                expires_in,
                refresh_expires_in,
            )

            return {
                "success": True,
                "action": "refreshed",
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
                "expires_in": expires_in,
                "expires_at_readable": datetime.fromtimestamp(expires_at, tz=VIETNAM_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            }

    # -------------------------------------------------------------------------
    # 5. LẤY TOKEN CÒN HIỆU LỰC (LAZY AUTO-REFRESH TRƯỚC KHI TRẢ VỀ)
    # -------------------------------------------------------------------------

    async def get_valid_user_token(
        self,
        tenant_key: Optional[str] = None,
        app_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Lấy access_token còn hiệu lực.
        Tự động kiểm tra thời hạn và tự refresh ngầm nếu còn dưới 10 phút.
        Nếu access_token đã hết hạn và refresh thất bại, trả về None (không trả về token chết).
        """
        now = time.time()
        effective_app_id = app_id
        if tenant_key:
            try:
                from services.lark_app_service import lark_app_service
                app_record = await lark_app_service.get_by_tenant_key(tenant_key)
                if app_record and app_record.get("app_id"):
                    if not effective_app_id or effective_app_id == getattr(settings, "LARK_APP_ID", ""):
                        effective_app_id = app_record["app_id"]
            except Exception as e:
                logger.debug("[TOKEN_SERVICE] resolve_app_id_failed tenant=%s error=%s", tenant_key, e)

        stored_data = await self.get_stored_token_data(tenant_key=tenant_key, app_id=effective_app_id)
        if not stored_data or not stored_data.get("access_token"):
            # Không mượn user token từ .env: token đó thuộc về MỘT danh tính cụ thể,
            # dùng cho tenant khác sẽ gửi tin nhắn bằng danh tính sai.
            # Caller (UserTokenProvider) sẽ chuyển None thành UserTokenMissing.
            return None

        if stored_data.get("status") == "invalid_refresh_token":
            logger.error(
                "[TOKEN_SERVICE] token_invalidated reason=invalid_refresh_token app=%s tenant=%s",
                stored_data.get("app_id"),
                stored_data.get("tenant_key"),
            )
            return None

        expires_at = stored_data.get("expires_at", 0)

        # Nếu còn hơn 10 phút (> 600 giây): Dùng trực tiếp
        if expires_at - now > 600:
            return stored_data["access_token"]

        # Nếu còn dưới 10 phút hoặc đã hết hạn: Kích hoạt refresh
        if stored_data.get("refresh_token"):
            try:
                res = await self.refresh_user_token(tenant_key=tenant_key, app_id=effective_app_id)
                return res.get("access_token")
            except Exception as e:
                logger.warning("[TOKEN_SERVICE] auto_refresh_failed error=%s", e)
                # Nếu access token vẫn chưa hết hạn (còn < 10 phút nhưng expires_at > now), dùng tạm
                if expires_at > now:
                    logger.debug("[TOKEN_SERVICE] using_expiring_token tenant=%s", tenant_key)
                    return stored_data.get("access_token")
                # Đã hết hạn hoàn toàn và refresh thất bại -> không trả về token chết
                logger.error("[TOKEN_SERVICE] token_expired_unrecoverable tenant=%s action=reauth_required", tenant_key)
                return None

        # Không có refresh_token: kiểm tra hạn trực tiếp
        if expires_at > now:
            return stored_data.get("access_token")
        return None

    # -------------------------------------------------------------------------
    # 6. TRUY VẤN THÔNG TIN TRẠNG THÁI (STATUS / HEALTH)
    # -------------------------------------------------------------------------

    async def get_stored_token_data(
        self,
        tenant_key: Optional[str] = None,
        app_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Lấy token theo (app_id, tenant_key); từ chối gọi thiếu ngữ cảnh tenant/app."""
        eff_tenant = (tenant_key or "").strip() or (get_current_tenant_key() if tenant_key is None else None)
        eff_app_arg = (app_id or "").strip() or None
        if not eff_tenant and not eff_app_arg:
            raise TenantContextMissing("get_stored_token_data() yêu cầu tenant_key hoặc app_id.")

        col = self._get_auth_col()

        effective_app_id = eff_app_arg
        if eff_tenant:
            try:
                from services.lark_app_service import lark_app_service
                app_record = await lark_app_service.get_by_tenant_key(eff_tenant)
                if app_record and app_record.get("app_id"):
                    if not effective_app_id or effective_app_id == getattr(settings, "LARK_APP_ID", ""):
                        effective_app_id = app_record["app_id"]
            except Exception as e:
                logger.debug("[TOKEN_SERVICE] resolve_app_id_failed tenant=%s error=%s", eff_tenant, e)

        query: Dict[str, Any]
        if effective_app_id and eff_tenant:
            query = {"app_id": effective_app_id, "tenant_key": eff_tenant}
        elif effective_app_id:
            query = {"app_id": effective_app_id}
        else:
            query = {"tenant_key": eff_tenant}

        admin_open_id: Optional[str] = None
        if eff_tenant:
            try:
                from database.db import get_tenants_collection

                tdoc = await get_tenants_collection().find_one({"tenant_key": eff_tenant})
                raw_admin = str((tdoc or {}).get("admin_open_id") or "").strip() if isinstance(tdoc, dict) else ""
                if raw_admin and raw_admin not in ("ou_default_admin", "ou_admin_fallback"):
                    admin_open_id = raw_admin
            except Exception as exc:
                logger.debug("[TOKEN_SERVICE] resolve_admin_open_id_failed tenant=%s error=%s", eff_tenant, exc)

        doc: Optional[Dict[str, Any]] = None
        if admin_open_id:
            admin_query = dict(query)
            admin_query["open_id"] = admin_open_id
            admin_valid_query = dict(admin_query)
            admin_valid_query["status"] = {"$ne": "invalid_refresh_token"}
            doc = await _find_one_sorted(col, admin_valid_query, sort=[("updated_at", -1)])
            if not doc:
                doc = await _find_one_sorted(col, admin_query, sort=[("updated_at", -1)])

        # Fallback: lấy bản ghi hợp lệ (không bị invalid_refresh_token), mới nhất theo (app_id, tenant_key)
        if not doc:
            query_valid = dict(query)
            query_valid["status"] = {"$ne": "invalid_refresh_token"}
            doc = await _find_one_sorted(col, query_valid, sort=[("updated_at", -1)])

        # Cuối cùng: nếu không có bản ghi hợp lệ, lấy bản ghi mới nhất theo query ban đầu
        if not doc:
            doc = await _find_one_sorted(col, query, sort=[("updated_at", -1)])

        if not doc:
            return None

        decrypted_doc = dict(doc)
        encrypted_flag = bool(decrypted_doc.get("token_encrypted"))
        if "access_token" in decrypted_doc and decrypted_doc["access_token"] is not None:
            decrypted_doc["access_token"] = _decrypt_auth_secret(
                decrypted_doc["access_token"],
                encrypted_flag=encrypted_flag,
            )
        if "refresh_token" in decrypted_doc and decrypted_doc["refresh_token"] is not None:
            decrypted_doc["refresh_token"] = _decrypt_auth_secret(
                decrypted_doc["refresh_token"],
                encrypted_flag=encrypted_flag,
            )
        return decrypted_doc

    async def get_token_status(
        self,
        tenant_key: Optional[str] = None,
        app_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Trả về trạng thái sống còn của User Token theo đúng tenant/app."""
        eff_tenant = (tenant_key or "").strip() or (get_current_tenant_key() if tenant_key is None else None)
        eff_app = (app_id or "").strip() or None
        if not eff_tenant and not eff_app:
            raise TenantContextMissing("get_token_status() yêu cầu tenant_key hoặc app_id.")

        data = await self.get_stored_token_data(tenant_key=eff_tenant, app_id=eff_app)
        now = time.time()
        if not data:
            return {
                "tenant_key": eff_tenant,
                "app_id": eff_app,
                "has_token": False,
                "is_valid": False,
                "message": "Chưa có User Access Token cho doanh nghiệp này. Vui lòng kết nối qua /auth/lark/login.",
                "user_name": None,
                "open_id": None,
            }

        expires_at = data.get("expires_at", 0)
        refresh_expires_at = data.get("refresh_expires_at", 0)
        access_remaining = expires_at - now
        refresh_remaining = refresh_expires_at - now

        is_access_valid = access_remaining > 0
        is_refresh_valid = refresh_remaining > 0
        raw_access = data.get("access_token") or ""
        preview = mask_token_preview(raw_access)

        return {
            "tenant_key": data.get("tenant_key") or eff_tenant,
            "app_id": data.get("app_id") or eff_app,
            "has_token": True,
            "is_valid": is_access_valid,
            "status": "valid" if is_access_valid else ("refreshable" if is_refresh_valid else "expired"),
            "user_name": data.get("user_name"),
            "open_id": data.get("open_id"),
            "access_token_preview": preview,
            "token_encrypted": bool(data.get("token_encrypted")),
            "access_token_remaining_sec": int(access_remaining),
            "access_token_remaining": format_remaining_seconds(access_remaining),
            "refresh_token_remaining_sec": int(refresh_remaining),
            "refresh_token_remaining": format_remaining_seconds(refresh_remaining),
            "can_auto_refresh": is_refresh_valid,
            "updated_at": data.get("updated_at"),
        }

    # -------------------------------------------------------------------------
    # 7. KHỞI TẠO STARTUP & HELPER METHODS
    # -------------------------------------------------------------------------

    async def init_token_on_startup(self) -> None:
        """
        Startup: khởi động `core.token_loop`; không nạp token toàn cục vào RAM.
        User token được cấp phát qua `token_broker` theo `(tenant_key, app_id, "user")`.
        """
        from core import token_loop

        token_loop.get_loop()  # khởi động sớm để lần lấy token đầu tiên không chờ tạo thread
        logger.info("[TOKEN_SERVICE] mode=tenant_broker legacy_preload=disabled")

    async def _fetch_user_profile(self, access_token: str) -> Dict[str, Any]:
        """Gọi endpoint user_info của Lark để lấy thông tin người dùng."""
        url = f"{settings.LARK_DOMAIN}/open-apis/authen/v1/user_info"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with self._get_client_session() as client:
                resp = await client.get(url, headers=headers, timeout=10.0)
                data = resp.json()
                if data.get("code") == 0 and data.get("data"):
                    return data["data"]
        except Exception as e:
            logger.warning("[OAUTH] user_info_fetch_failed error=%s", e)
        return {}


# Singleton instance toàn hệ thống
token_service = LarkTokenService()


# Vòng lặp refresh toàn cục `start_token_refresh_loop()` đã được xoá khỏi file này
# (GĐ5). Nhánh cũ của nó có thể quay vòng `primary_user_token` legacy — tức token
# của một doanh nghiệp khác. Trách nhiệm giữ token hợp lệ giờ thuộc
# `services.auth.tenant_refresh_sweeper`: quét theo `tenants.status == "ready"` và
# luôn hỏi broker theo `(tenant_key, app_id, "user")`.
