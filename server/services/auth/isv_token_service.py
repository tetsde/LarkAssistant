"""
HiLark ISV Token Service (Lark Store App Multi-Tenant Engine)
=============================================================
Vị trí: server/services/auth/isv_token_service.py

Chịu trách nhiệm:
  1. Nhận, xác thực và lưu trữ bền vững `app_ticket` do Lark bắn định kỳ (1h/lần).
  2. Quản lý vòng đời `app_access_token` của Ứng dụng Store (ISV App).
  3. Quản lý và làm mới bộ đệm `tenant_access_token` động theo từng doanh nghiệp (`tenant_key`).
  4. Tạo Lark RequestOption đa doanh nghiệp chuẩn xác cho mọi OpenAPI call.
  5. Bảo lưu chế độ Dual-Mode: Tương thích ngược 100% với Single-Tenant / Custom App.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple

import httpx
import lark_oapi as lark

from core.config import settings
from core.http_client import get_http_client
from database.db import get_isv_auth_collection, get_sync_db

logger = logging.getLogger("hilark.isv_token")
logger.setLevel(logging.INFO)

ISV_TICKET_DOC_ID = "isv_app_ticket"
VIETNAM_TZ = timezone(timedelta(hours=7))


class ISVTokenService:
    """Service điều phối vòng đời Token ISV / Marketplace Multi-Tenant của Lark."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._app_ticket: Optional[str] = (
            getattr(settings, "LARK_APP_TICKET", "") or os.getenv("LARK_APP_TICKET", "") or None
        )
        self._app_ticket_updated_at: float = 0.0

        # Cache app_access_token (ISV App-level token)
        self._app_access_token: Optional[str] = None
        self._app_access_token_expires_at: float = 0.0

        # Cache tenant_access_token theo từng tenant_key (Enterprise-level token)
        # { tenant_key: {"token": str, "expires_at": float} }
        self._tenant_tokens: Dict[str, Dict[str, Any]] = {}

    @property
    def is_isv_mode(self) -> bool:
        """Kiểm tra xem hệ thống có đang vận hành ở chế độ Lark Store / ISV Multi-Tenant hay không."""
        return getattr(settings, "IS_ISV_MODE", False)

    # -------------------------------------------------------------------------
    # 1. QUẢN LÝ APP TICKET
    # -------------------------------------------------------------------------

    async def get_app_ticket(self) -> Optional[str]:
        """
        Lấy app_ticket hiện hành:
          1. Ưu tiên trong RAM cache.
          2. Tra cứu trong MongoDB collection 'isv_auth'.
          3. Fallback sang file .env nếu có.
        """
        if self._app_ticket:
            return self._app_ticket

        try:
            col = get_isv_auth_collection()
            doc = await col.find_one({"_id": ISV_TICKET_DOC_ID})
            if doc and doc.get("app_ticket"):
                self._app_ticket = doc["app_ticket"]
                self._app_ticket_updated_at = doc.get("updated_at_timestamp", time.time())
                return self._app_ticket
        except Exception as e:
            logger.debug(f"Không thể đọc app_ticket từ async MongoDB: {e}")

        # Fallback env
        ticket = getattr(settings, "LARK_APP_TICKET", "") or os.getenv("LARK_APP_TICKET", "")
        if ticket:
            self._app_ticket = ticket
            return ticket
        return None

    def get_app_ticket_sync(self) -> Optional[str]:
        """Phiên bản đồng bộ đọc app_ticket cho scripts hoặc đồng bộ lúc khởi động."""
        if self._app_ticket:
            return self._app_ticket

        try:
            db = get_sync_db()
            col = db[getattr(settings, "MONGO_ISV_AUTH_COLLECTION", "isv_auth")]
            doc = col.find_one({"_id": ISV_TICKET_DOC_ID})
            if doc and doc.get("app_ticket"):
                self._app_ticket = doc["app_ticket"]
                self._app_ticket_updated_at = doc.get("updated_at_timestamp", time.time())
                return self._app_ticket
        except Exception as e:
            logger.debug(f"Không thể đọc app_ticket từ sync MongoDB: {e}")

        ticket = getattr(settings, "LARK_APP_TICKET", "") or os.getenv("LARK_APP_TICKET", "")
        if ticket:
            self._app_ticket = ticket
            return ticket
        return None

    async def set_app_ticket(self, app_ticket: str) -> None:
        """
        Cập nhật app_ticket mới nhận được từ Lark Webhook:
          - Ghi đè vào bộ nhớ RAM.
          - Lưu bền vững vào MongoDB collection 'isv_auth'.
        """
        if not app_ticket or not app_ticket.strip():
            logger.warning("Bỏ qua app_ticket rỗng.")
            return

        clean_ticket = app_ticket.strip()
        now = time.time()
        self._app_ticket = clean_ticket
        self._app_ticket_updated_at = now

        try:
            col = get_isv_auth_collection()
            await col.update_one(
                {"_id": ISV_TICKET_DOC_ID},
                {
                    "$set": {
                        "app_ticket": clean_ticket,
                        "updated_at_timestamp": now,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
                upsert=True,
            )
            logger.info("✔ [ISV TICKET] Đã lưu app_ticket mới bền vững vào MongoDB.")
        except Exception as e:
            logger.error(f"Lỗi khi lưu app_ticket vào MongoDB: {e}")

    async def handle_app_ticket_event(self, payload: Dict[str, Any]) -> bool:
        """
        Bóc tách và xử lý sự kiện app_ticket từ Lark Webhook:
          - Hỗ trợ cả Lark Event Schema 2.0 (`header.event_type == 'app_ticket'`)
          - Hỗ trợ cả Lark Event Schema 1.0 (`type == 'app_ticket'`)
        """
        if not isinstance(payload, dict):
            return False

        header = payload.get("header") or {}
        event_type = header.get("event_type") or payload.get("type")

        ticket_val = None
        if event_type == "app_ticket":
            event_data = payload.get("event") or {}
            ticket_val = event_data.get("app_ticket") or payload.get("app_ticket")
        elif "app_ticket" in payload.get("event", {}):
            ticket_val = payload["event"].get("app_ticket")

        if ticket_val:
            await self.set_app_ticket(ticket_val)
            logger.info(f"✔ [ISV TICKET] Bắt được sự kiện app_ticket từ Lark Webhook: {ticket_val[:8]}...")
            return True

        return False

    async def resend_app_ticket(self) -> bool:
        """
        Gửi yêu cầu tới Lark Open Platform để yêu cầu bắn lại app_ticket:
          POST /open-apis/auth/v3/app_ticket/resend
        """
        app_id = getattr(settings, "LARK_APP_ID", "") or os.getenv("LARK_APP_ID", "")
        app_secret = getattr(settings, "LARK_APP_SECRET", "") or os.getenv("LARK_APP_SECRET", "")
        domain = getattr(settings, "LARK_DOMAIN", "https://open.larksuite.com")

        if not app_id or not app_secret:
            logger.warning("Thiếu LARK_APP_ID hoặc LARK_APP_SECRET để gọi resend_app_ticket.")
            return False

        url = f"{domain}/open-apis/auth/v3/app_ticket/resend"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json={"app_id": app_id, "app_secret": app_secret})
                data = resp.json()
                if data.get("code") == 0:
                    logger.info("✔ Đã gửi yêu cầu Lark Open Platform bắn lại app_ticket thành công.")
                    return True
                else:
                    logger.warning(f"Lark từ chối yêu cầu resend app_ticket: {data}")
                    return False
        except Exception as e:
            logger.error(f"Lỗi khi gửi yêu cầu resend app_ticket: {e}")
            return False

    # -------------------------------------------------------------------------
    # 2. QUẢN LÝ APP ACCESS TOKEN (ISV APP-LEVEL)
    # -------------------------------------------------------------------------

    async def get_app_access_token(self, force_refresh: bool = False) -> str:
        """
        Lấy app_access_token của ISV App:
          - Dùng bộ đệm in-memory nếu còn hạn > 10 phút (> 600 giây).
          - Nếu sắp hết hạn: gọi Lark API đổi (app_id, app_secret, app_ticket) lấy app_access_token mới.
        """
        now = time.time()
        if not force_refresh and self._app_access_token and (now < self._app_access_token_expires_at - 600):
            return self._app_access_token

        async with self._lock:
            # Double check sau khi acquire lock
            if not force_refresh and self._app_access_token and (now < self._app_access_token_expires_at - 600):
                return self._app_access_token

            app_id = getattr(settings, "LARK_APP_ID", "") or os.getenv("LARK_APP_ID", "")
            app_secret = getattr(settings, "LARK_APP_SECRET", "") or os.getenv("LARK_APP_SECRET", "")
            domain = getattr(settings, "LARK_DOMAIN", "https://open.larksuite.com")
            ticket = await self.get_app_ticket()

            if not ticket:
                raise ValueError("Chưa có app_ticket! Vui lòng chờ Lark push app_ticket hoặc cấu hình LARK_APP_TICKET.")

            url = f"{domain}/open-apis/auth/v3/app_access_token"
            payload = {
                "app_id": app_id,
                "app_secret": app_secret,
                "app_ticket": ticket,
            }

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, json=payload)
                    data = resp.json()

                if data.get("code") != 0 or not data.get("app_access_token"):
                    raise RuntimeError(f"Lark từ chối cấp app_access_token: {data}")

                new_token = data["app_access_token"]
                expires_in = int(data.get("expire", 7200))
                self._app_access_token = new_token
                self._app_access_token_expires_at = now + expires_in
                logger.info(f"✔ [ISV AUTH] Đã cấp mới app_access_token (hiệu lực {expires_in}s).")
                return new_token
            except Exception as e:
                logger.error(f"Lỗi khi lấy app_access_token ISV: {e}")
                raise

    # -------------------------------------------------------------------------
    # 3. QUẢN LÝ TENANT ACCESS TOKEN ĐỘNG THEO DOANH NGHIỆP (TENANT-LEVEL)
    # -------------------------------------------------------------------------

    async def get_tenant_access_token(
        self,
        tenant_key: str,
        force_refresh: bool = False,
    ) -> str:
        """
        Lấy tenant_access_token cho một doanh nghiệp cụ thể (dựa vào tenant_key):
          - Nếu không truyền tenant_key hoặc không ở chế độ ISV: Fallback về internal Custom App token.
          - Nếu ở chế độ ISV:
            1. Đọc cache in-memory theo tenant_key (nếu còn > 10 phút).
            2. Nếu hết hạn: Đổi app_access_token + tenant_key lấy tenant_access_token mới.
            3. Lưu cache RAM và MongoDB.
        """
        # Fallback Single-Tenant / Custom App nếu không có tenant_key
        if not tenant_key and not self.is_isv_mode:
            return await self._get_custom_app_tenant_token(force_refresh=force_refresh)

        if not tenant_key:
            logger.warning("get_tenant_access_token được gọi trong ISV mode nhưng thiếu tenant_key.")
            return ""

        now = time.time()
        cached = self._tenant_tokens.get(tenant_key)
        if not force_refresh and cached and (now < cached.get("expires_at", 0) - 600):
            return cached.get("token", "")

        async with self._lock:
            # Double check sau khi acquire lock
            cached = self._tenant_tokens.get(tenant_key)
            if not force_refresh and cached and (now < cached.get("expires_at", 0) - 600):
                return cached.get("token", "")

            # 1. Đảm bảo app_access_token khả dụng
            app_token = await self.get_app_access_token()
            domain = getattr(settings, "LARK_DOMAIN", "https://open.larksuite.com")
            url = f"{domain}/open-apis/auth/v3/tenant_access_token"

            payload = {
                "app_access_token": app_token,
                "tenant_key": tenant_key,
            }

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, json=payload)
                    data = resp.json()

                if data.get("code") != 0 or not data.get("tenant_access_token"):
                    raise RuntimeError(f"Lark từ chối cấp tenant_access_token cho tenant {tenant_key}: {data}")

                new_tenant_token = data["tenant_access_token"]
                expires_in = int(data.get("expire", 7200))
                expires_at = now + expires_in

                self._tenant_tokens[tenant_key] = {
                    "token": new_tenant_token,
                    "expires_at": expires_at,
                }

                # Lưu MongoDB bền vững
                try:
                    col = get_isv_auth_collection()
                    await col.update_one(
                        {"_id": f"tenant_token:{tenant_key}"},
                        {
                            "$set": {
                                "tenant_key": tenant_key,
                                "tenant_access_token": new_tenant_token,
                                "expires_at": expires_at,
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }
                        },
                        upsert=True,
                    )
                except Exception as db_err:
                    logger.debug(f"Không thể ghi tenant_token vào DB: {db_err}")

                logger.info(f"✔ [ISV AUTH] Đã cấp mới tenant_access_token cho tenant '{tenant_key}' (hạn {expires_in}s).")
                return new_tenant_token
            except Exception as e:
                logger.error(f"Lỗi khi lấy tenant_access_token cho tenant {tenant_key}: {e}")
                raise

    def get_tenant_access_token_sync(
        self,
        tenant_key: str = "",
        force_refresh: bool = False,
    ) -> str:
        """Wrapper đồng bộ cho các lệnh gọi đồng bộ (LarkBaseService, CLI scripts)."""
        if not tenant_key and not self.is_isv_mode:
            return self._get_custom_app_tenant_token_sync(force_refresh=force_refresh)

        # Kiểm tra RAM cache trước
        now = time.time()
        cached = self._tenant_tokens.get(tenant_key)
        if not force_refresh and cached and (now < cached.get("expires_at", 0) - 600):
            return cached.get("token", "")

        try:
            loop = asyncio.get_running_loop()
            # Đang trong event loop -> tạo task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(asyncio.run, self.get_tenant_access_token(tenant_key, force_refresh))
                return fut.result(timeout=15.0)
        except RuntimeError:
            # Chưa có event loop
            return asyncio.run(self.get_tenant_access_token(tenant_key, force_refresh))

    # -------------------------------------------------------------------------
    # 4. TƯƠNG THÍCH NGƯỢC (FALLBACK CUSTOM APP TOKEN)
    # -------------------------------------------------------------------------

    async def _get_custom_app_tenant_token(self, force_refresh: bool = False) -> str:
        """Lấy tenant_access_token cho Custom App (Single-Tenant) qua endpoint /internal."""
        app_id = getattr(settings, "LARK_APP_ID", "") or os.getenv("LARK_APP_ID", "")
        app_secret = getattr(settings, "LARK_APP_SECRET", "") or os.getenv("LARK_APP_SECRET", "")
        domain = getattr(settings, "LARK_DOMAIN", "https://open.larksuite.com")

        if not app_id or not app_secret:
            return ""

        url = f"{domain}/open-apis/auth/v3/tenant_access_token/internal"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json={"app_id": app_id, "app_secret": app_secret})
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("tenant_access_token", "")
        except Exception as e:
            logger.error(f"Lỗi lấy internal tenant token: {e}")
        return ""

    def _get_custom_app_tenant_token_sync(self, force_refresh: bool = False) -> str:
        """Lấy internal tenant token đồng bộ."""
        app_id = getattr(settings, "LARK_APP_ID", "") or os.getenv("LARK_APP_ID", "")
        app_secret = getattr(settings, "LARK_APP_SECRET", "") or os.getenv("LARK_APP_SECRET", "")
        domain = getattr(settings, "LARK_DOMAIN", "https://open.larksuite.com")

        if not app_id or not app_secret:
            return ""

        url = f"{domain}/open-apis/auth/v3/tenant_access_token/internal"
        try:
            resp = httpx.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=10.0)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("tenant_access_token", "")
        except Exception as e:
            logger.error(f"Lỗi lấy internal tenant token sync: {e}")
        return ""

    # -------------------------------------------------------------------------
    # 5. REQUEST OPTION BUILDER CHO LARK SDK
    # -------------------------------------------------------------------------

    def build_request_option(
        self,
        tenant_key: Optional[str] = None,
        user_access_token: Optional[str] = None,
    ) -> lark.RequestOption:
        """
        Xây dựng lark.RequestOption phù hợp với chế độ ISV hoặc Custom App:
          - Nếu có user_access_token: gán user_access_token.
          - Nếu có tenant_key: gán tenant_key và app_ticket cho SDK.
        """
        builder = lark.RequestOption.builder()
        if user_access_token:
            builder.user_access_token(user_access_token)

        if tenant_key:
            builder.tenant_key(tenant_key)
            ticket = self.get_app_ticket_sync()
            if ticket:
                builder.app_ticket(ticket)
        elif self.is_isv_mode:
            ticket = self.get_app_ticket_sync()
            if ticket:
                builder.app_ticket(ticket)

        return builder.build()


# Singleton toàn hệ thống
isv_token_service = ISVTokenService()

