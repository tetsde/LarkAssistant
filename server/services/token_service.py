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

import httpx

from core.config import settings
from database.db import get_auth_collection

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
        self._app_access_token: Optional[str] = None
        self._app_access_token_expires_at: float = 0.0

    # -------------------------------------------------------------------------
    # 1. APP ACCESS TOKEN (Cần thiết để gọi các API OAuth OIDC của Lark)
    # -------------------------------------------------------------------------

    async def get_app_access_token(self, force_refresh: bool = False) -> str:
        """Lấy app_access_token của App (có cache in-memory 2h)."""
        now = time.time()
        if not force_refresh and self._app_access_token and (now < self._app_access_token_expires_at - 120):
            return self._app_access_token

        app_id = settings.LARK_APP_ID
        app_secret = settings.LARK_APP_SECRET
        if not app_id or not app_secret:
            raise ValueError("Chưa cấu hình LARK_APP_ID hoặc LARK_APP_SECRET trong .env!")

        url = f"{settings.LARK_DOMAIN}/open-apis/auth/v3/app_access_token/internal"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"app_id": app_id, "app_secret": app_secret})
            data = resp.json()
            if data.get("code") == 0 and data.get("app_access_token"):
                self._app_access_token = data.get("app_access_token")
                expire_sec = data.get("expire", 7200)
                self._app_access_token_expires_at = now + expire_sec
                return self._app_access_token
            else:
                raise RuntimeError(f"Lỗi khi lấy app_access_token từ Lark: {data}")

    # -------------------------------------------------------------------------
    # 2. SINH URL ỦY QUYỀN (AUTHORIZE URL)
    # -------------------------------------------------------------------------

    def get_authorize_url(
        self,
        redirect_uri: Optional[str] = None,
        state: str = "hilark_oauth",
        scope: Optional[str] = None,
    ) -> str:
        """
        Sinh URL ủy quyền OAuth của Lark để Sếp truy cập từ trình duyệt.
        Bắt buộc kèm scope offline_access để nhận refresh_token.
        """
        target_redirect_uri = redirect_uri or settings.LARK_OAUTH_REDIRECT_URI
        default_scopes = (
            "offline_access "
            "im:message.send_as_user "
            "im:chat:readonly "
            "im:chat "
            "im:message "
            "bitable:app "
            "contact:user.base:readonly"
        )
        target_scope = scope or default_scopes

        base_url = "https://accounts.larksuite.com/open-apis/authen/v1/authorize"
        params = {
            "client_id": settings.LARK_APP_ID,
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
    ) -> Dict[str, Any]:
        """
        Đổi Authorization Code lấy cặp access_token và refresh_token từ Lark.
        Sau đó lưu vào MongoDB collection `lark_auth` và nạp vào RAM.
        """
        if not code or not code.strip():
            raise ValueError("Mã authorization code không được để trống!")

        app_token = await self.get_app_access_token()
        url = f"{settings.LARK_DOMAIN}/open-apis/authen/v1/oidc/access_token"
        headers = {
            "Authorization": f"Bearer {app_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "grant_type": "authorization_code",
            "code": code.strip(),
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
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
        open_id = user_info.get("open_id") or settings.LARK_USER_OPEN_ID or ""
        user_name = user_info.get("name") or settings.LARK_USER_NAME or "User"

        # Đóng gói document lưu vào MongoDB
        doc = {
            "_id": PRIMARY_TOKEN_DOC_ID,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "refresh_expires_in": refresh_expires_in,
            "expires_at": expires_at,
            "refresh_expires_at": refresh_expires_at,
            "open_id": open_id,
            "user_name": user_name,
            "avatar_url": user_info.get("avatar_url", ""),
            "email": user_info.get("email", ""),
            "scope": token_scope,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Lưu nguyên tử vào MongoDB
        col = get_auth_collection()
        await col.update_one(
            {"_id": PRIMARY_TOKEN_DOC_ID},
            {"$set": doc},
            upsert=True,
        )

        # Cập nhật cache in-memory & nạp vào Lark Client
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

    async def refresh_user_token(self, force: bool = False) -> Dict[str, Any]:
        """
        Gọi API Lark để đổi refresh_token lấy cặp (access_token, refresh_token) MỚI.
        Áp dụng Single-Use Token Rotation: Ghi đè ngay refresh_token mới vào MongoDB.
        """
        async with self._lock:
            stored_data = await self.get_stored_token_data()
            if not stored_data or not stored_data.get("refresh_token"):
                raise ValueError("Không tìm thấy refresh_token hợp lệ trong MongoDB để làm mới! Vui lòng cấp quyền qua /auth/lark/login trước.")

            current_refresh_token = stored_data["refresh_token"]
            now = time.time()

            # Nếu không phải force và token vẫn còn hạn > 10 phút thì không cần refresh
            if not force and stored_data.get("expires_at", 0) - now > 600:
                logger.info("Access token vẫn còn hạn tốt (>10 phút), bỏ qua refresh.")
                return {"success": True, "action": "skipped", "access_token": stored_data["access_token"]}

            app_token = await self.get_app_access_token()
            url = f"{settings.LARK_DOMAIN}/open-apis/authen/v1/oidc/refresh_access_token"
            headers = {
                "Authorization": f"Bearer {app_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": current_refresh_token,
            }

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                data = resp.json()

            if data.get("code") != 0:
                err_msg = data.get("message") or data.get("msg") or "Refresh token error"
                logger.error(f"Lỗi khi refresh token: code={data.get('code')}, msg={err_msg}")
                raise RuntimeError(f"Lark từ chối refresh token: {err_msg} (Mã lỗi {data.get('code')})")

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

            col = get_auth_collection()
            await col.update_one(
                {"_id": PRIMARY_TOKEN_DOC_ID},
                {"$set": update_fields},
            )

            # Cập nhật cache in-memory
            stored_data.update(update_fields)
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

    async def get_valid_user_token(self) -> Optional[str]:
        """
        Lấy access_token còn hiệu lực.
        Tự động kiểm tra thời hạn và tự refresh ngầm nếu còn dưới 10 phút.
        """
        now = time.time()
        stored_data = await self.get_stored_token_data()
        if not stored_data or not stored_data.get("access_token"):
            # Fallback sang cấu hình trong .env nếu MongoDB chưa có
            return settings.LARK_USER_ACCESS_TOKEN or None

        expires_at = stored_data.get("expires_at", 0)

        # Nếu còn hơn 10 phút (> 600 giây): Dùng trực tiếp
        if expires_at - now > 600:
            return stored_data["access_token"]

        # Nếu còn dưới 10 phút hoặc đã hết hạn: Kích hoạt refresh
        if stored_data.get("refresh_token"):
            try:
                res = await self.refresh_user_token()
                return res.get("access_token")
            except Exception as e:
                logger.warning(f"Tự động refresh token thất bại: {e}. Sử dụng token hiện có làm fallback.")
                return stored_data.get("access_token")

        return stored_data.get("access_token")

    # -------------------------------------------------------------------------
    # 6. TRUY VẤN THÔNG TIN TRẠNG THÁI (STATUS / HEALTH)
    # -------------------------------------------------------------------------

    async def get_stored_token_data(self) -> Optional[Dict[str, Any]]:
        """Lấy dữ liệu token từ cache hoặc MongoDB."""
        if self._cached_token_data:
            return self._cached_token_data
        col = get_auth_collection()
        doc = await col.find_one({"_id": PRIMARY_TOKEN_DOC_ID})
        if doc:
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
        """Nạp token từ MongoDB vào RAM và Lark Client khi server khởi động."""
        try:
            data = await self.get_stored_token_data()
            if data and data.get("access_token"):
                self._sync_to_lark_client(
                    data["access_token"],
                    data.get("open_id", ""),
                    data.get("user_name", "User"),
                )
                logger.info(f"✅ Đã nạp User Token từ MongoDB vào RAM (User: {data.get('user_name')})")
            else:
                logger.info("ℹ️ Chưa có token trong MongoDB, hệ thống dùng cấu hình .env mặc định.")
        except Exception as e:
            logger.warning(f"Lỗi khi đọc token từ MongoDB lúc startup: {e}")

    def _sync_to_lark_client(self, access_token: str, open_id: str, name: str) -> None:
        """Đồng bộ token trực tiếp vào singleton lark_client và lark_base_service nếu có."""
        try:
            from services.bot_service import lark_client, lark_base_service
            if lark_client:
                lark_client.user_access_token = access_token
                lark_client._last_token_check = None
                if open_id:
                    lark_client.known_user_open_id = open_id
                if not lark_client._current_user_profile:
                    lark_client._current_user_profile = {}
                lark_client._current_user_profile["name"] = name
                lark_client._current_user_profile["open_id"] = open_id
            if lark_base_service:
                lark_base_service.user_access_token = access_token
        except Exception as ex:
            logger.debug(f"Không thể đồng bộ vào lark_client singleton: {ex}")

    async def _fetch_user_profile(self, access_token: str) -> Dict[str, Any]:
        """Gọi endpoint user_info của Lark để lấy thông tin người dùng."""
        url = f"{settings.LARK_DOMAIN}/open-apis/authen/v1/user_info"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                data = resp.json()
                if data.get("code") == 0 and data.get("data"):
                    return data["data"]
        except Exception as e:
            logger.warning(f"Lỗi khi gọi user_info endpoint: {e}")
        return {}


# Singleton instance toàn hệ thống
token_service = LarkTokenService()


async def start_token_refresh_loop() -> None:
    """
    Vòng lặp chạy nền định kỳ kiểm tra và tự động refresh token trước khi hết hạn.
    Mỗi 30 phút kiểm tra một lần. Nếu access_token còn < 15 phút, tiến hành làm mới.
    """
    logger.info("🔄 [TOKEN LOOP] Khởi động vòng lặp kiểm tra và refresh User Token định kỳ (mỗi 30m).")
    while True:
        try:
            await asyncio.sleep(1800)  # 30 phút
            token_data = await token_service.get_stored_token_data()
            if token_data and token_data.get("refresh_token"):
                now = time.time()
                expires_at = token_data.get("expires_at", 0)
                if expires_at - now < 900:  # còn dưới 15 phút
                    logger.info("⏰ [TOKEN LOOP] User Token sắp hết hạn (< 15 phút), tiến hành tự động refresh...")
                    await token_service.refresh_user_token()
        except asyncio.CancelledError:
            logger.info("⏹️ [TOKEN LOOP] Dừng vòng lặp refresh token.")
            break
        except Exception as e:
            logger.warning(f"⚠️ [TOKEN LOOP] Lỗi trong chu kỳ refresh token: {e}")
