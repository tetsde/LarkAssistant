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

PRIMARY_TOKEN_DOC_ID = "primary_user_token"
VIETNAM_TZ = timezone(timedelta(hours=7))


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
        self._lock = asyncio.Lock()
        self._cached_token_data: Optional[Dict[str, Any]] = None
        # Cache app_access_token theo app_id: không còn biến `_app_access_token` duy nhất
        # cho cả process, vì một slot toàn cục sẽ phát token của App A cho yêu cầu của App B.
        self._app_access_tokens: Dict[str, Tuple[str, float]] = {}

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
        Lấy app_access_token của một App (cache in-memory theo app_id).

        Trước đây khi thiếu `app_secret`, hàm này đi mượn secret của App khác (`resolved_secret`)
        và vẫn giữ nguyên `app_id` — tạo ra cặp lai ID của App A + mật khẩu của App B, Lark
        trả 10014. Nay `app_id` và `app_secret` luôn lấy từ CÙNG MỘT document credential.
        """
        now = time.time()

        if not app_id or not app_secret:
            if not tenant_key:
                raise TenantContextMissing(
                    "get_app_access_token() cần (app_id + app_secret) hoặc tenant_key "
                    "để tra credential của đúng tenant."
                )
            creds = await tenant_resolver.resolve_credentials(tenant_key)
            if app_id and app_id != creds.app_id:
                raise TokenUnavailable(
                    f"App '{app_id}' không phải App đã đăng ký của tenant '{tenant_key}'.",
                    tenant_key=tenant_key,
                    kind="app",
                )
            app_id, app_secret = creds.app_id, creds.app_secret
        elif not tenant_key:
            tenant_key = get_current_tenant_key()

        if not app_id or not app_secret:
            raise TenantConfigIncomplete(tenant_key or "?", ["app_credentials"])

        cache_key = app_id
        if not force_refresh:
            cached = self._app_access_tokens.get(cache_key)
            if cached and now < cached[1] - 120:
                return cached[0]

        url = f"{settings.LARK_DOMAIN}/open-apis/auth/v3/app_access_token/internal"
        async with self._get_client_session() as client:
            resp = await client.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=10.0)
            data = resp.json()
            if data.get("code") == 0 and data.get("app_access_token"):
                new_token = data.get("app_access_token")
                expire_sec = data.get("expire", 7200)
                self._app_access_tokens[cache_key] = (new_token, now + expire_sec)
                return new_token
            raise TokenUnavailable(
                f"Lỗi khi lấy app_access_token từ Lark: code={data.get('code')}, "
                f"msg={data.get('msg') or data.get('message')}",
                tenant_key=tenant_key,
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
            logger.error(f"Lỗi khi đổi authorization code: code={data.get('code')}, msg={err_msg}")
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

        # Đóng gói document lưu vào MongoDB. Không còn ghi vào `_id="primary_user_token"`
        # vì document đó là danh tính dùng chung, khiến mọi tenant đọc nhầm token của nhau.
        token_doc_id = f"lark_app:{app_id}:user:{tenant_key}:{open_id}"
        doc = {
            "_id": token_doc_id,
            "app_id": app_id or "",
            "access_token": access_token,
            "refresh_token": refresh_token,
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

        # Lưu nguyên tử vào MongoDB
        col = self._get_auth_col()
        await col.update_one(
            {"_id": token_doc_id},
            {"$set": doc},
            upsert=True,
        )

        # Cập nhật cache in-memory chỉ dành cho đường legacy không tenant.
        # Token đã gắn tenant/app không được nạp vào cache global dùng chung.
        if token_doc_id == PRIMARY_TOKEN_DOC_ID:
            self._cached_token_data = doc
            self._sync_to_lark_client(access_token, open_id, user_name)

        logger.info(
            f"🎉 [OAUTH SUCCESS] Đã lưu User Token thành công cho: {user_name} (open_id: {open_id}). "
            f"Access token sống {expires_in}s, Refresh token sống {refresh_expires_in}s."
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
        Áp dụng Single-Use Token Rotation: Ghi đè ngay refresh_token mới vào MongoDB.
        """
        async with self._lock:
            stored_data = await self.get_stored_token_data(tenant_key=tenant_key, app_id=app_id)
            if not stored_data or not stored_data.get("refresh_token"):
                raise ValueError("Không tìm thấy refresh_token hợp lệ trong MongoDB để làm mới! Vui lòng cấp quyền qua /auth/lark/login trước.")

            current_refresh_token = stored_data["refresh_token"]
            now = time.time()

            # Nếu không phải force và token vẫn còn hạn > 10 phút thì không cần refresh
            if not force and stored_data.get("expires_at", 0) - now > 600:
                logger.info("Access token vẫn còn hạn tốt (>10 phút), bỏ qua refresh.")
                return {"success": True, "action": "skipped", "access_token": stored_data["access_token"]}

            effective_app_id = app_id or stored_data.get("app_id")
            if not app_secret and effective_app_id:
                try:
                    from services.lark_app_service import lark_app_service
                    app_record = await lark_app_service.get_by_app_id(effective_app_id)
                    app_secret = app_record.get("app_secret") if app_record else None
                except Exception as exc:
                    logger.warning("Không thể nạp App Secret theo app_id khi refresh: %s", exc)
            app_token = await self.get_app_access_token(
                app_id=effective_app_id,
                app_secret=app_secret,
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
                logger.error(f"Lỗi khi refresh token: code={err_code}, msg={err_msg}")
                if err_code in (20024, 20038):
                    try:
                        col = self._get_auth_col()
                        await col.update_one(
                            {"_id": stored_data.get("_id", PRIMARY_TOKEN_DOC_ID)},
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
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
                "expires_in": expires_in,
                "refresh_expires_in": refresh_expires_in,
                "expires_at": expires_at,
                "refresh_expires_at": refresh_expires_at,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            col = self._get_auth_col()
            await col.update_one(
                {"_id": stored_data.get("_id", PRIMARY_TOKEN_DOC_ID)},
                {"$set": update_fields},
            )

            # Cập nhật cache in-memory
            stored_data.update(update_fields)
            if stored_data.get("_id", PRIMARY_TOKEN_DOC_ID) == PRIMARY_TOKEN_DOC_ID:
                self._cached_token_data = stored_data
                self._sync_to_lark_client(
                    new_access_token,
                    stored_data.get("open_id", ""),
                    stored_data.get("user_name", "User"),
                )

            logger.info(
                f"🔄 [TOKEN ROTATED] Đã làm mới thành công User Token! "
                f"Access token mới hạn {expires_in}s, Refresh token mới xoay vòng hạn {refresh_expires_in}s."
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
                logger.debug("Không thể phân giải app_id cho tenant %s: %s", tenant_key, e)

        stored_data = await self.get_stored_token_data(tenant_key=tenant_key, app_id=effective_app_id)
        if not stored_data or not stored_data.get("access_token"):
            # Không mượn user token từ .env: token đó thuộc về MỘT danh tính cụ thể,
            # dùng cho tenant khác sẽ gửi tin nhắn bằng danh tính sai.
            # Caller (UserTokenProvider) sẽ chuyển None thành UserTokenMissing.
            return None

        if stored_data.get("status") == "invalid_refresh_token":
            logger.error(
                "Token bị vô hiệu hóa do refresh không hợp lệ (app=%s tenant=%s); cần OAuth lại.",
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
                logger.warning(f"Tự động refresh token thất bại: {e}.")
                # Nếu access token vẫn chưa hết hạn (còn < 10 phút nhưng expires_at > now), dùng tạm
                if expires_at > now:
                    logger.info("Access token sắp hết hạn nhưng vẫn còn hiệu lực tạm thời, tiếp tục sử dụng.")
                    return stored_data.get("access_token")
                # Đã hết hạn hoàn toàn và refresh thất bại -> không trả về token chết
                logger.error("❌ Access token đã hết hạn hoàn toàn và refresh thất bại. Cần đăng nhập lại qua /auth/lark/login.")
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
        """Lấy token theo App + tenant; không dùng cache global cho tenant-scoped token."""
        if not tenant_key and not app_id and self._cached_token_data:
            return self._cached_token_data
        col = self._get_auth_col()

        effective_app_id = app_id
        if tenant_key:
            try:
                from services.lark_app_service import lark_app_service
                app_record = await lark_app_service.get_by_tenant_key(tenant_key)
                if app_record and app_record.get("app_id"):
                    if not effective_app_id or effective_app_id == getattr(settings, "LARK_APP_ID", ""):
                        effective_app_id = app_record["app_id"]
            except Exception as e:
                logger.debug("Không thể phân giải app_id cho tenant %s: %s", tenant_key, e)

        query: Dict[str, Any]
        if effective_app_id and tenant_key:
            query = {"app_id": effective_app_id, "tenant_key": tenant_key}
        elif effective_app_id:
            query = {"app_id": effective_app_id}
        elif tenant_key:
            query = {"tenant_key": tenant_key}
        else:
            query = {"_id": PRIMARY_TOKEN_DOC_ID}

        doc = None
        if tenant_key or effective_app_id:
            # Ưu tiên 1: Lấy bản ghi hợp lệ (không bị invalid_refresh_token), mới nhất
            query_valid = dict(query)
            query_valid["status"] = {"$ne": "invalid_refresh_token"}
            doc = await col.find_one(query_valid, sort=[("updated_at", -1)])

            # Ưu tiên 2: Nếu không có bản ghi hợp lệ, lấy bản ghi mới nhất theo query ban đầu
            if not doc:
                doc = await col.find_one(query, sort=[("updated_at", -1)])
        else:
            doc = await col.find_one(query)

        if doc and not tenant_key and not effective_app_id:
            self._cached_token_data = doc
        return doc

    async def get_token_status(self) -> Dict[str, Any]:
        """Trả về toàn bộ trạng thái sống còn của Token dưới định dạng chi tiết."""
        data = await self.get_stored_token_data()
        now = time.time()
        if not data:
            return {
                "has_token": False,
                "is_valid": False,
                "message": "Chưa có token nào được lưu trong MongoDB. Vui lòng truy cập /auth/lark/login để kết nối.",
                "user_name": None,
                "open_id": None,
            }

        expires_at = data.get("expires_at", 0)
        refresh_expires_at = data.get("refresh_expires_at", 0)
        access_remaining = expires_at - now
        refresh_remaining = refresh_expires_at - now

        is_access_valid = access_remaining > 0
        is_refresh_valid = refresh_remaining > 0

        return {
            "has_token": True,
            "is_valid": is_access_valid,
            "status": "valid" if is_access_valid else ("refreshable" if is_refresh_valid else "expired"),
            "user_name": data.get("user_name"),
            "open_id": data.get("open_id"),
            "access_token_preview": f"{data.get('access_token', '')[:10]}...{data.get('access_token', '')[-6:]}" if data.get("access_token") else "",
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
        Startup: không nạp `primary_user_token` toàn cục vào RAM nữa.

        Bản cũ lấy document legacy `_id="primary_user_token"` rồi nhét vào singleton
        `lark_service`/`lark_base_service`. Document đó thuộc về MỘT App/tenant, nên khi
        chạy nhiều doanh nghiệp, tenant B có thể gửi tin bằng danh tính của tenant A.
        User token bây giờ chỉ được cấp qua broker theo `(tenant_key, app_id, "user")`;
        việc giữ token còn hạn là trách nhiệm của sweeper.
        """
        from core import token_loop

        token_loop.get_loop()  # khởi động sớm để lần lấy token đầu tiên không chờ tạo thread
        logger.info(
            "ℹ️ Startup không nạp legacy primary_user_token; user token được cấp theo tenant "
            "qua token broker (sweeper sẽ giữ cho các tenant 'ready' còn token hợp lệ)."
        )

    def _clear_lark_client_token(self) -> None:
        """Xóa sạch user token trong Lark client khi token đã chết."""
        try:
            from services.lark import lark_service
            if lark_service:
                lark_service.user_access_token = ""
                lark_service._last_token_check = None
        except Exception:
            pass

    def _sync_to_lark_client(self, access_token: str, open_id: str, name: str) -> None:
        """
        Đồng bộ danh tính người dùng vào `lark_service` (chỉ phục vụ hiển thị/profile).

        `lark_base_service` không còn nhận token ghi thẳng vào field: nó là singleton
        dùng chung, còn token user luôn gắn với một tenant cụ thể. Bitable lấy token
        từ broker theo từng request.
        """
        try:
            from services.lark import lark_service
            if lark_service:
                lark_service.user_access_token = access_token
                lark_service._last_token_check = None
                if open_id:
                    lark_service.known_user_open_id = open_id
                if not lark_service._current_user_profile:
                    lark_service._current_user_profile = {}
                lark_service._current_user_profile["name"] = name
                lark_service._current_user_profile["open_id"] = open_id
            logger.info(f"🔄 Đã đồng bộ User Token vào lark_service (User: {name})")
        except Exception as ex:
            logger.warning(f"Không thể đồng bộ vào lark_service singleton: {ex}")

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
            logger.warning(f"Lỗi khi gọi user_info endpoint: {e}")
        return {}


# Singleton instance toàn hệ thống
token_service = LarkTokenService()


# Vòng lặp refresh toàn cục `start_token_refresh_loop()` đã được xoá khỏi file này
# (GĐ5). Nhánh cũ của nó có thể quay vòng `primary_user_token` legacy — tức token
# của một doanh nghiệp khác. Trách nhiệm giữ token hợp lệ giờ thuộc
# `services.auth.tenant_refresh_sweeper`: quét theo `tenants.status == "ready"` và
# luôn hỏi broker theo `(tenant_key, app_id, "user")`.
