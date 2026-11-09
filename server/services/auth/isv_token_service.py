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
from core.tenant_errors import TenantContextMissing, TokenUnavailable
from database.db import get_isv_auth_collection, get_sync_db

logger = logging.getLogger("hilark.isv_token")
logger.setLevel(logging.INFO)

ISV_TICKET_DOC_ID = "isv_app_ticket"
VIETNAM_TZ = timezone(timedelta(hours=7))


# =============================================================================
# HELPER: RESOLVE APP CREDENTIALS -> KHÔNG CÒN Ở ĐÂY
# =============================================================================
# Hai hàm `_resolve_app_credentials_sync_safe` / `_resolve_app_credentials_async` trước
# đây trả lời câu hỏi "App của tenant này là gì" theo ba tầng: tenant_key → "App mới nhất
# trong DB" → `.env`. Hai tầng sau khiến một tenant vô tình gọi Lark bằng credential của
# tenant khác mà không có dấu hiệu nào. Nay điểm vào duy nhất là
# `services.tenancy.tenant_resolver.tenant_resolver.resolve_credentials()` — thiếu dữ
# liệu của chính tenant là raise exception có kiểu.


class ISVTokenService:
    """Service điều phối vòng đời Token ISV / Marketplace Multi-Tenant của Lark."""

    def __init__(self):
        self._app_lock = asyncio.Lock()
        self._tenant_lock = asyncio.Lock()
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
            logger.debug("[ISV_TICKET] mongo_read_failed mode=async error=%s", e)

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
            logger.debug("[ISV_TICKET] mongo_read_failed mode=sync error=%s", e)

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
            logger.warning("[ISV_TICKET] ignored reason=empty")
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
            logger.info("[ISV_TICKET] persisted target=mongodb")
        except Exception as e:
            logger.error("[ISV_TICKET] persist_failed error=%s", e)

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
            logger.info("[ISV_TICKET] received source=webhook prefix=%s", ticket_val[:8])
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
            logger.warning("[ISV_TICKET] resend_skipped reason=missing_app_credentials")
            return False

        url = f"{domain}/open-apis/auth/v3/app_ticket/resend"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json={"app_id": app_id, "app_secret": app_secret})
                data = resp.json()
                if data.get("code") == 0:
                    logger.info("[ISV_TICKET] resend_requested status=ok")
                    return True
                else:
                    logger.warning("[ISV_TICKET] resend_rejected response=%s", data)
                    return False
        except Exception as e:
            logger.error("[ISV_TICKET] resend_failed error=%s", e)
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

        async with self._app_lock:
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
                logger.info("[ISV_AUTH] app_token_refreshed ttl_s=%d", expires_in)
                return new_token
            except Exception as e:
                logger.error("[ISV_AUTH] app_token_failed error=%s", e)
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
        Lấy tenant_access_token cho MỘT doanh nghiệp cụ thể, chỉ dành cho ISV/Marketplace App:
          1. Đọc cache in-memory theo tenant_key (nếu còn > 10 phút).
          2. Nếu hết hạn: đổi app_access_token + tenant_key lấy tenant_access_token mới.
          3. Lưu cache RAM và MongoDB.

        Custom App (không phải ISV) bị từ chối ở đây: token của nó phải đi qua
        `token_broker` để broker chọn provider theo `settings.IS_ISV_MODE`.
        """
        # Custom App dùng endpoint /internal; tenant_key không biến nó thành ISV App.
        # Chỉ Store/ISV App mới dùng app_access_token + tenant_key.
        isv_active = self.is_isv_mode or bool(self._app_ticket or self._app_access_token)
        if not isv_active:
            # Custom App không còn dùng đường này. Caller phải gọi token_broker để broker
            # tự chọn provider theo mode; nếu gọi thẳng vào đây nghĩa là chọn sai provider.
            raise TokenUnavailable(
                "get_tenant_access_token() chỉ dùng cho ISV/Marketplace App. "
                "Custom App phải lấy token qua token_broker.",
                tenant_key=tenant_key,
                kind="tenant",
            )

        if not tenant_key:
            # ISV mà không biết tenant nào thì không thể chọn app_ticket: thà raise còn
            # hơn trả "" (caller sẽ gửi request với Bearer rỗng rồi lỗi mù ở Lark).
            raise TenantContextMissing("get_tenant_access_token() trong ISV mode bắt buộc tenant_key.")

        now = time.time()
        cached = self._tenant_tokens.get(tenant_key)
        if not force_refresh and cached and (now < cached.get("expires_at", 0) - 600):
            return cached.get("token", "")

        # 1. Đảm bảo app_access_token khả dụng trước khi vào lock của tenant
        app_token = await self.get_app_access_token()

        async with self._tenant_lock:
            # Double check sau khi acquire lock
            cached = self._tenant_tokens.get(tenant_key)
            if not force_refresh and cached and (now < cached.get("expires_at", 0) - 600):
                return cached.get("token", "")

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
                    logger.debug("[ISV_AUTH] tenant_token_persist_failed tenant=%s error=%s", tenant_key, db_err)

                logger.info("[ISV_AUTH] tenant_token_refreshed tenant=%s ttl_s=%d", tenant_key, expires_in)
                return new_tenant_token
            except Exception as e:
                logger.error("[ISV_AUTH] tenant_token_failed tenant=%s error=%s", tenant_key, e)
                raise

    def get_tenant_access_token_sync(
        self,
        tenant_key: str = "",
        force_refresh: bool = False,
    ) -> str:
        """
        Wrapper đồng bộ. Trước đây hàm này gọi `asyncio.run(...)` trong thread phụ -
        đúng con đường tạo event loop mới rồi đóng lại trong khi lock của token manager
        thuộc loop khác (gây treo). Nay mọi lối lấy token đều đi qua token loop duy nhất.
        """
        from services.auth.tenant_token_manager import token_broker

        return token_broker.get_token_sync(tenant_key, "bot", force_refresh=force_refresh)

    # -------------------------------------------------------------------------
    # 4. CUSTOM APP TOKEN: KHÔNG CÒN Ở ĐÂY
    # -------------------------------------------------------------------------
    # Nhánh Custom App (`_get_custom_app_tenant_token` / `..._sync`) đã được chuyển vào
    # `services.auth.tenant_token_manager.CustomAppProvider`. Lý do: hai hàm cũ tự
    # resolve credential theo kiểu "App bất kỳ trong DB → .env" và không cache gì,
    # nên mỗi lần gọi là một request Lark mới và có thể gắn nhầm App của tenant khác.

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

