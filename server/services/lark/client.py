"""
HiLark Lark Client
==================
Vị trí: server/services/lark_client.py

Mục đích:
    Quản lý kết nối cốt lõi với Lark Open Platform:
      1. Khởi tạo Lark SDK Client (app_id, app_secret, domain)
      2. Quản lý User Access Token (kiểm tra, lấy profile, lấy tên người dùng)
      3. Chuẩn bị RequestOption cho tất cả các lệnh gọi API

Import:
    from services.lark_client import LarkClientMixin
"""

from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

import lark_oapi as lark
from lark_oapi.api.authen.v1 import GetUserInfoRequest

from core.config import settings
from models.lark import LarkConfig
from services.auth.tenant_token_manager import token_broker
from core.tenant_errors import TenantContextMissing, TenantResolutionError, TokenUnavailable, UserTokenMissing
from core import token_loop

logger = logging.getLogger("hilark.lark")
logger.setLevel(logging.INFO)


class LarkClientMixin:
    """
    Mixin quản lý kết nối cốt lõi:
      - Khởi tạo lark.Client từ config/.env
      - Quản lý User Access Token (profile, tên người dùng)
      - Chuẩn bị RequestOption đúng danh tính (User hoặc Bot)
    """

    def _init_client(
        self,
        config: Optional[LarkConfig] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        verification_token: Optional[str] = None,
        encrypt_key: Optional[str] = None,
        domain: Optional[str] = None,
        user_access_token: Optional[str] = None,
        user_open_id: Optional[str] = None,
    ) -> None:
        """Khởi tạo Lark Client stateless (không nạp user token từ Mongo legacy hoặc .env)."""
        if config is not None:
            self.config = config
        else:
            self.config = LarkConfig(
                app_id=app_id or "",
                app_secret=app_secret or "",
                verification_token=verification_token or settings.LARK_VERIFICATION_TOKEN or "",
                encrypt_key=encrypt_key or settings.LARK_ENCRYPT_KEY or "",
                domain=domain or settings.LARK_DOMAIN or lark.LARK_DOMAIN,
                user_access_token="",
                user_open_id=user_open_id or "",
            )

        self.app_id = self.config.app_id
        self.app_secret = self.config.app_secret
        self.verification_token = self.config.verification_token
        self.encrypt_key = self.config.encrypt_key
        self.domain = self.config.domain or lark.LARK_DOMAIN
        self.user_access_token = ""

        # Khởi tạo Lark API Client (bật enable_set_token để truyền RequestOption per-call)
        self.client: lark.Client = (
            lark.Client.builder()
            .app_id(self.app_id)
            .app_secret(self.app_secret)
            .domain(self.domain)
            .enable_set_token(True)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

        # Danh tính Admin không còn đọc từ `.env`; truyền hoặc phân giải từ DB theo tenant
        self.known_user_open_id = getattr(self.config, "user_open_id", "") or ""
        self._current_user_profile: Optional[Dict[str, Any]] = None

        # Danh sách các message_id do chính hệ thống gửi đi (chống vòng lặp tự reply)
        self._sent_message_ids: OrderedDict[str, float] = OrderedDict()
        # Cache tên người dùng với giới hạn bộ nhớ (user_id -> (name, cached_at))
        self._user_name_cache: OrderedDict[str, Tuple[str, float]] = OrderedDict()

    # -------------------------------------------------------------------------
    # QUẢN LÝ DANH TÍNH USER (USER IDENTITY MANAGEMENT — TENANT-SCOPED DB)
    # -------------------------------------------------------------------------

    def _resolve_tenant_for_identity(self, tenant_key: Optional[str] = None) -> str:
        from database.db import get_current_tenant_key

        eff = tenant_key or get_current_tenant_key() or getattr(self, "tenant_key", None)
        return str(eff).strip() if eff else ""

    def _lookup_tenant_admin_record(
        self,
        tenant_key: Optional[str] = None,
        include_name: bool = True,
    ) -> Dict[str, str]:
        """
        Tra cứu (open_id, name) của Admin thuộc ĐÚNG tenant_key từ DB tenant-scoped:
          1. Cache _tenant_admin_cache / known_user_open_id (chỉ khi instance gắn đúng tenant)
          2. tenants (admin_open_id, admin_name)
          3. user_settings (open_id, user_name/name theo tenant_key)
          4. lark_auth (open_id, user_name/name theo tenant_key, bỏ qua doc legacy)
          5. system_config.lark_admin_config (theo tenant_key)

        Không đọc .env (LARK_USER_OPEN_ID/LARK_USER_NAME) và không query Mongo thiếu tenant_key.
        """
        eff_tenant = self._resolve_tenant_for_identity(tenant_key)
        resolved_open_id = ""
        resolved_name = ""

        if eff_tenant:
            cache = getattr(self, "_tenant_admin_cache", None)
            if isinstance(cache, dict) and cache.get(eff_tenant):
                resolved_open_id = str(cache[eff_tenant]).strip()

            name_cache = getattr(self, "_tenant_admin_name_cache", None)
            if name_cache is None:
                name_cache = {}
                try:
                    self._tenant_admin_name_cache = name_cache
                except Exception:
                    pass
            if include_name and isinstance(name_cache, dict) and name_cache.get(eff_tenant):
                resolved_name = str(name_cache[eff_tenant]).strip()

            if getattr(self, "tenant_key", None) == eff_tenant:
                if not resolved_open_id and getattr(self, "known_user_open_id", ""):
                    resolved_open_id = str(self.known_user_open_id).strip()
                prof = getattr(self, "_current_user_profile", None)
                if isinstance(prof, dict) and prof.get("tenant_key") in ("", eff_tenant):
                    if not resolved_open_id and prof.get("open_id"):
                        resolved_open_id = str(prof["open_id"]).strip()
                    if include_name and not resolved_name and prof.get("name"):
                        resolved_name = str(prof["name"]).strip()

            need_open_id = not resolved_open_id
            need_name = include_name and not resolved_name
            if need_open_id or need_name:
                try:
                    from database.db import get_sync_db

                    sdb = get_sync_db()
                    tdoc = sdb[getattr(settings, "MONGO_TENANTS_COLLECTION", "tenants")].find_one(
                        {"tenant_key": eff_tenant}
                    )
                    if tdoc:
                        if not resolved_open_id and tdoc.get("admin_open_id"):
                            resolved_open_id = str(tdoc["admin_open_id"]).strip()
                        if include_name and not resolved_name and tdoc.get("admin_name"):
                            resolved_name = str(tdoc["admin_name"]).strip()

                    if not resolved_open_id or (include_name and not resolved_name):
                        us_doc = sdb["user_settings"].find_one(
                            {"tenant_key": eff_tenant, "open_id": {"$exists": True, "$ne": ""}},
                            sort=[("updated_at", -1)],
                        )
                        if us_doc:
                            if not resolved_open_id and us_doc.get("open_id"):
                                resolved_open_id = str(us_doc["open_id"]).strip()
                            if include_name and not resolved_name:
                                raw_name = us_doc.get("user_name") or us_doc.get("name") or ""
                                if str(raw_name).strip():
                                    resolved_name = str(raw_name).strip()

                    if not resolved_open_id or (include_name and not resolved_name):
                        auth_doc = sdb[getattr(settings, "MONGO_AUTH_COLLECTION", "lark_auth")].find_one(
                            {"tenant_key": eff_tenant, "_id": {"$ne": "primary_user_token"}},
                            sort=[("updated_at", -1)],
                        )
                        if auth_doc:
                            if not resolved_open_id and auth_doc.get("open_id"):
                                resolved_open_id = str(auth_doc["open_id"]).strip()
                            if include_name and not resolved_name:
                                raw_name = auth_doc.get("user_name") or auth_doc.get("name") or ""
                                if str(raw_name).strip():
                                    resolved_name = str(raw_name).strip()

                    if not resolved_open_id or (include_name and not resolved_name):
                        adm_doc = sdb["system_config"].find_one(
                            {"config_key": "lark_admin_config", "tenant_key": eff_tenant}
                        )
                        if adm_doc:
                            if not resolved_open_id and adm_doc.get("admin_open_id"):
                                resolved_open_id = str(adm_doc["admin_open_id"]).strip()
                            if include_name and not resolved_name and adm_doc.get("admin_name"):
                                resolved_name = str(adm_doc["admin_name"]).strip()
                except Exception as exc:
                    logger.debug("[LARK_CLIENT] admin_lookup_failed tenant=%s error=%s", eff_tenant, exc)

            if resolved_open_id and isinstance(cache, dict):
                cache[eff_tenant] = resolved_open_id
            if include_name and resolved_name and isinstance(name_cache, dict):
                name_cache[eff_tenant] = resolved_name
            if getattr(self, "tenant_key", None) == eff_tenant and resolved_open_id:
                self.known_user_open_id = resolved_open_id
        else:
            # Không có tenant_key: chỉ giữ open_id gắn tường minh lúc khởi tạo instance (nếu có)
            if getattr(self, "known_user_open_id", ""):
                resolved_open_id = str(self.known_user_open_id).strip()
            prof = getattr(self, "_current_user_profile", None)
            if isinstance(prof, dict):
                if not resolved_open_id and prof.get("open_id"):
                    resolved_open_id = str(prof["open_id"]).strip()
                if include_name and not resolved_name and prof.get("name"):
                    resolved_name = str(prof["name"]).strip()

        return {
            "open_id": resolved_open_id,
            "name": resolved_name,
            "tenant_key": eff_tenant,
        }

    def get_current_user(
        self,
        force_refresh: bool = False,
        tenant_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Tra cứu danh tính Admin của tenant từ MongoDB tenant-scoped (tenants/user_settings/lark_auth).
        Đã tách hoàn toàn khỏi User Access Token và không dùng biến toàn cục .env.
        """
        eff_tenant = self._resolve_tenant_for_identity(tenant_key)
        ident = self._lookup_tenant_admin_record(tenant_key=eff_tenant, include_name=True)
        profile = {
            "name": ident.get("name", ""),
            "open_id": ident.get("open_id", ""),
            "union_id": "",
            "avatar_url": "",
            "email": "",
            "mobile": "",
            "tenant_key": eff_tenant,
        }
        if getattr(self, "tenant_key", None) and getattr(self, "tenant_key", None) == eff_tenant:
            self._current_user_profile = profile
        return profile

    @property
    def owner_open_id(self) -> str:
        """
        Trả về Open ID của Admin theo đúng tenant hiện tại (ContextVar hoặc instance tenant_key).
        """
        return self._lookup_tenant_admin_record(include_name=False).get("open_id", "")

    def check_user_access_token(
        self,
        force_ping: bool = False,
        tenant_key: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Any:
        """
        Kiểm tra User Access Token theo đúng tenant qua `token_broker` (không giữ state cache `_last_token_check`).
        Khi `force_ping=True` hoặc truyền `token` tường minh, thực hiện ping online tới Lark.
        """
        from services.auth.token_verifier import (
            TokenCheckResult,
            parse_jwt_expiration,
            ping_user_access_token,
        )

        target_token = (token or "").strip() if token is not None else ""
        if target_token:
            return ping_user_access_token(token=target_token, domain=self.domain, tenant_key=tenant_key)

        try:
            eff_tenant = self._effective_tenant(tenant_key)
        except TenantContextMissing as exc:
            return TokenCheckResult(
                is_valid=False,
                is_expired=True,
                status="missing",
                message=str(exc),
                code=None,
            )

        try:
            user_tok = self._token_via_broker(eff_tenant, "user")
        except Exception as exc:
            status = "missing" if getattr(exc, "error_code", None) == "user_token_missing" else "api_error"
            return TokenCheckResult(
                is_valid=False,
                is_expired=True,
                status=status,
                message=str(exc),
                code=None,
            )

        if force_ping:
            return ping_user_access_token(token=user_tok, domain=self.domain, tenant_key=eff_tenant)

        _, exp_dt, remaining_sec, payload = parse_jwt_expiration(user_tok)
        if remaining_sec is not None and remaining_sec <= 0:
            return TokenCheckResult(
                is_valid=False,
                is_expired=True,
                status="expired",
                message="User Access Token đã hết hạn theo JWT.",
                expires_at=exp_dt,
                expires_in_seconds=remaining_sec,
                code=20005,
                raw_payload=payload,
            )

        return TokenCheckResult(
            is_valid=True,
            is_expired=False,
            status="valid",
            message="User Access Token hợp lệ.",
            expires_at=exp_dt,
            expires_in_seconds=remaining_sec,
            code=0,
            raw_payload=payload,
        )

    def is_user_token_valid(
        self,
        tenant_key: Optional[str] = None,
        force_ping: bool = False,
    ) -> bool:
        """Kiểm tra nhanh xem User token của tenant còn hợp lệ qua `token_broker` không."""
        res = self.check_user_access_token(force_ping=force_ping, tenant_key=tenant_key)
        return bool(res and res.is_valid)

    @staticmethod
    def _is_lark_permission_denied(resp: Any) -> bool:
        """Nhận diện lỗi từ chối quyền từ Lark API để chỉ fallback User Token đúng điều kiện."""
        code = getattr(resp, "code", None)
        msg = str(getattr(resp, "msg", "") or "").lower()
        if code in (99991663, 1770032, 1254043, 1254044, 1061004, 131006, 99991672):
            return True
        return any(
            kw in msg
            for kw in ("forbidden", "no permission", "permission denied", "lack of permission")
        )

    def _try_get_user_request_option(self, tenant_key: Optional[str] = None) -> Optional[lark.RequestOption]:
        """Thử lấy User RequestOption làm fallback có điều kiện; trả về None nếu chưa uỷ quyền."""
        try:
            return self._get_request_option(as_user=True, tenant_key=tenant_key)
        except (UserTokenMissing, TokenUnavailable, TenantContextMissing) as exc:
            logger.info(
                "[LARK_CLIENT] user_fallback_unavailable tenant=%s reason=%s",
                tenant_key or "-",
                getattr(exc, "error_code", type(exc).__name__),
            )
            return None

    def get_user_name(self, user_id: str, tenant_key: Optional[str] = None) -> Optional[str]:
        """Lấy họ tên hiển thị của một người dùng qua Bot Token theo tenant (TTL 1h & max size 1000)."""
        if not user_id:
            return None
        if not hasattr(self, "_user_name_cache") or self._user_name_cache is None:
            self._user_name_cache = OrderedDict()

        eff_t = self._resolve_tenant_for_identity(tenant_key)
        cache_key = f"{eff_t}:{user_id}"
        now = time.time()
        # Kiểm tra cache còn hạn (TTL 3600s = 1 giờ)
        if cache_key in self._user_name_cache:
            name, cached_at = self._user_name_cache[cache_key]
            if now - cached_at < 3600:
                return name
            del self._user_name_cache[cache_key]

        try:
            from lark_oapi.api.contact.v3 import GetUserRequest

            opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
            req = GetUserRequest.builder().user_id(user_id).user_id_type("open_id").build()
            resp = self.client.contact.v3.user.get(req, opt)
            if resp.success() and resp.data and resp.data.user:
                name = resp.data.user.name
                if name:
                    # Dọn dẹp cache quá hạn 1 giờ
                    while self._user_name_cache and (now - next(iter(self._user_name_cache.values()))[1] > 3600):
                        self._user_name_cache.popitem(last=False)
                    self._user_name_cache[cache_key] = (name, now)
                    # Bounded size tối đa 1000 người dùng
                    while len(self._user_name_cache) > 1000:
                        self._user_name_cache.popitem(last=False)
                    return name
        except Exception:
            pass
        return None

    # -------------------------------------------------------------------------
    # CHUẨN BỊ REQUEST OPTION (TOKEN SELECTOR)
    # -------------------------------------------------------------------------

    def _effective_tenant(self, tenant_key: Optional[str] = None) -> str:
        """
        tenant_key theo thứ tự: tham số gọi -> ContextVar của request -> danh tính
        của instance.

        ContextVar phải đứng trước `self.tenant_key`: singleton `lark_service` mang
        tenant của .env/tenant đầu tiên, nên nếu ưu tiên thuộc tính instance thì một
        request của tenant B sẽ bị gửi bằng danh tính tenant A. Thuộc tính instance chỉ
        còn là fallback hợp lệ cho runtime service riêng theo App được tạo qua
        (`runtime.get_or_create_lark_service`).
        """
        from database.db import get_current_tenant_key
        eff = tenant_key or get_current_tenant_key() or getattr(self, "tenant_key", None)
        if not eff:
            raise TenantContextMissing(
                "LarkClient không xác định được tenant để lấy token "
                "(tham số, ContextVar request và thuộc tính instance đều trống)."
            )
        return eff

    def _token_via_broker(self, tenant_key: str, kind: str) -> str:
        """
        Gọi broker từ code sync, kể cả khi thread hiện tại đang có event loop.

        Thread phụ chỉ chờ một `concurrent.futures.Future` của token loop; nó không tạo
        event loop riêng nữa, nên không còn tình huống lock của broker bị chạm từ hai loop.
        """
        if token_loop.is_async_caller():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(
                    token_broker.get_token_sync, tenant_key, kind
                ).result(timeout=20.0)
        return token_broker.get_token_sync(tenant_key, kind)

    def _build_user_option(self, token: str, tenant_key: Optional[str]) -> lark.RequestOption:
        builder = lark.RequestOption.builder().user_access_token(token)
        if tenant_key:
            builder.tenant_key(tenant_key)
        return builder.build()

    def _get_request_option(
        self,
        as_user: bool = True,
        tenant_key: Optional[str] = None,
    ) -> lark.RequestOption:
        """Tạo RequestOption mang danh tính User (user token) hoặc Bot (tenant token) qua token_broker."""
        eff_tenant = self._effective_tenant(tenant_key)
        if as_user:
            valid_token = self._token_via_broker(eff_tenant, "user")
            if not valid_token:
                raise TokenUnavailable(
                    f"Broker trả về user token rỗng cho tenant '{eff_tenant}'.",
                    tenant_key=eff_tenant,
                    kind="user",
                )
            return self._build_user_option(valid_token, eff_tenant)

        bot_token = self._token_via_broker(eff_tenant, "bot")
        if not bot_token:
            raise TokenUnavailable(
                f"Broker trả về bot token rỗng cho tenant '{eff_tenant}'.",
                tenant_key=eff_tenant,
                kind="tenant",
            )
        return (
            lark.RequestOption.builder()
            .tenant_access_token(bot_token)
            .tenant_key(eff_tenant)
            .build()
        )

    # -------------------------------------------------------------------------
    # TẢI TÀI NGUYÊN & PHÂN GIẢI TÀI LIỆU (DOCUMENT & RESOURCE ACCESS)
    # -------------------------------------------------------------------------

    async def adownload_message_resource(
        self,
        message_id: str,
        file_key: str,
        resource_type: str = "file",
        tenant_key: Optional[str] = None,
    ) -> Optional[bytes]:
        """
        Tải tài nguyên nhị phân (tệp đính kèm hoặc hình ảnh) từ tin nhắn Lark IM bằng Bot Token (async).
        """
        if not message_id or not file_key:
            logger.warning("[LARK_IM] download_skipped reason=empty_ids")
            return None

        from lark_oapi.api.im.v1 import GetMessageResourceRequest
        opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
        req = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(file_key)
            .type(resource_type)
            .build()
        )
        try:
            resp = await self.client.im.v1.message_resource.aget(req, opt)

            if not resp.success():
                logger.error(
                    "[LARK_IM] resource_download_failed msg=%s key=%s code=%s error=%s",
                    message_id,
                    file_key,
                    resp.code,
                    resp.msg,
                )
                return None

            if hasattr(resp, "file") and resp.file:
                if hasattr(resp.file, "read"):
                    return resp.file.read()
                elif isinstance(resp.file, (bytes, bytearray)):
                    return bytes(resp.file)
            return None
        except (TenantResolutionError, TokenUnavailable):
            raise
        except Exception as e:
            logger.error("[LARK_IM] resource_download_error key=%s error=%s", file_key, e, exc_info=True)
            return None

    def download_message_resource(
        self,
        message_id: str,
        file_key: str,
        resource_type: str = "file",
        tenant_key: Optional[str] = None,
    ) -> Optional[bytes]:
        """Phiên bản đồng bộ của adownload_message_resource (dùng Bot Token kèm RequestOption)."""
        if not message_id or not file_key:
            return None

        from lark_oapi.api.im.v1 import GetMessageResourceRequest
        opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
        req = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(file_key)
            .type(resource_type)
            .build()
        )
        try:
            resp = self.client.im.v1.message_resource.get(req, opt)

            if not resp.success():
                logger.error(
                    "[LARK_IM] resource_download_failed msg=%s key=%s code=%s error=%s",
                    message_id,
                    file_key,
                    resp.code,
                    resp.msg,
                )
                return None

            if hasattr(resp, "file") and resp.file:
                if hasattr(resp.file, "read"):
                    return resp.file.read()
                elif isinstance(resp.file, (bytes, bytearray)):
                    return bytes(resp.file)
            return None
        except (TenantResolutionError, TokenUnavailable):
            raise
        except Exception as e:
            logger.error("[LARK_IM] resource_download_error key=%s error=%s", file_key, e, exc_info=True)
            return None

    async def aget_docx_raw_content(self, document_id: str, tenant_key: Optional[str] = None) -> Optional[str]:
        """
        Lấy nội dung Markdown nguyên bản của tài liệu Lark DocX qua OpenAPI (async, 0 token cost).
        Ưu tiên Bot Token trước; chỉ fallback sang User Token khi Lark từ chối quyền.
        """
        if not document_id:
            return None

        from lark_oapi.api.docx.v1 import RawContentDocumentRequest
        bot_opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
        req = RawContentDocumentRequest.builder().document_id(document_id).build()
        try:
            resp = await self.client.docx.v1.document.araw_content(req, bot_opt)
            if not resp.success() and self._is_lark_permission_denied(resp):
                user_opt = self._try_get_user_request_option(tenant_key=tenant_key)
                if user_opt is not None:
                    logger.info(
                        "[LARK_DOCX] raw_content_retry mode=user doc=%s code=%s msg=%s",
                        document_id,
                        resp.code,
                        resp.msg,
                    )
                    resp = await self.client.docx.v1.document.araw_content(req, user_opt)

            if not resp.success():
                logger.error(
                    "[LARK_DOCX] raw_content_failed doc=%s code=%s msg=%s",
                    document_id,
                    resp.code,
                    resp.msg,
                )
                return None

            if resp.data and hasattr(resp.data, "content"):
                return resp.data.content or ""
            return ""
        except (TenantResolutionError, TokenUnavailable):
            raise
        except Exception as e:
            logger.error("[LARK_DOCX] raw_content_error doc=%s error=%s", document_id, e, exc_info=True)
            return None

    def get_docx_raw_content(self, document_id: str, tenant_key: Optional[str] = None) -> Optional[str]:
        """Phiên bản đồng bộ của aget_docx_raw_content (Bot Token trước, User Token khi bị từ chối quyền)."""
        if not document_id:
            return None

        from lark_oapi.api.docx.v1 import RawContentDocumentRequest
        bot_opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
        req = RawContentDocumentRequest.builder().document_id(document_id).build()
        try:
            resp = self.client.docx.v1.document.raw_content(req, bot_opt)
            if not resp.success() and self._is_lark_permission_denied(resp):
                user_opt = self._try_get_user_request_option(tenant_key=tenant_key)
                if user_opt is not None:
                    logger.info(
                        "[LARK_DOCX] raw_content_retry mode=user doc=%s code=%s msg=%s",
                        document_id,
                        resp.code,
                        resp.msg,
                    )
                    resp = self.client.docx.v1.document.raw_content(req, user_opt)

            if not resp.success():
                logger.error(
                    "[LARK_DOCX] raw_content_failed doc=%s code=%s msg=%s",
                    document_id,
                    resp.code,
                    resp.msg,
                )
                return None

            if resp.data and hasattr(resp.data, "content"):
                return resp.data.content or ""
            return ""
        except (TenantResolutionError, TokenUnavailable):
            raise
        except Exception as e:
            logger.error("[LARK_DOCX] raw_content_error doc=%s error=%s", document_id, e, exc_info=True)
            return None

    async def aresolve_wiki_token(self, wiki_token: str, tenant_key: Optional[str] = None) -> Optional[Dict[str, str]]:
        """
        Giải mã wiki node token thành obj_token và obj_type.
        Ưu tiên Bot Token trước; chỉ fallback User Token khi Lark từ chối quyền.
        """
        if not wiki_token:
            return None

        from lark_oapi.api.wiki.v2 import GetNodeSpaceRequest
        bot_opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
        req = GetNodeSpaceRequest.builder().token(wiki_token).build()
        try:
            resp = await self.client.wiki.v2.space.aget_node(req, bot_opt)
            if not resp.success() and self._is_lark_permission_denied(resp):
                user_opt = self._try_get_user_request_option(tenant_key=tenant_key)
                if user_opt is not None:
                    logger.info(
                        "[LARK_WIKI] get_node_retry mode=user token=%s code=%s msg=%s",
                        wiki_token,
                        resp.code,
                        resp.msg,
                    )
                    resp = await self.client.wiki.v2.space.aget_node(req, user_opt)

            if not resp.success():
                logger.error(
                    "[LARK_WIKI] get_node_failed token=%s code=%s msg=%s",
                    wiki_token,
                    resp.code,
                    resp.msg,
                )
                return None

            if resp.data and hasattr(resp.data, "node") and resp.data.node:
                node = resp.data.node
                return {
                    "obj_token": getattr(node, "obj_token", "") or "",
                    "obj_type": getattr(node, "obj_type", "") or "",
                    "title": getattr(node, "title", "") or "",
                }
            return None
        except (TenantResolutionError, TokenUnavailable):
            raise
        except Exception as e:
            logger.error("[LARK_WIKI] get_node_error token=%s error=%s", wiki_token, e, exc_info=True)
            return None

    def resolve_wiki_token(self, wiki_token: str, tenant_key: Optional[str] = None) -> Optional[Dict[str, str]]:
        """Phiên bản đồng bộ của aresolve_wiki_token (Bot Token trước, User Token khi bị từ chối quyền)."""
        if not wiki_token:
            return None

        from lark_oapi.api.wiki.v2 import GetNodeSpaceRequest
        bot_opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
        req = GetNodeSpaceRequest.builder().token(wiki_token).build()
        try:
            resp = self.client.wiki.v2.space.get_node(req, bot_opt)
            if not resp.success() and self._is_lark_permission_denied(resp):
                user_opt = self._try_get_user_request_option(tenant_key=tenant_key)
                if user_opt is not None:
                    logger.info(
                        "[LARK_WIKI] get_node_retry mode=user token=%s code=%s msg=%s",
                        wiki_token,
                        resp.code,
                        resp.msg,
                    )
                    resp = self.client.wiki.v2.space.get_node(req, user_opt)

            if not resp.success():
                logger.error(
                    "[LARK_WIKI] get_node_failed token=%s code=%s msg=%s",
                    wiki_token,
                    resp.code,
                    resp.msg,
                )
                return None

            if resp.data and hasattr(resp.data, "node") and resp.data.node:
                node = resp.data.node
                return {
                    "obj_token": getattr(node, "obj_token", "") or "",
                    "obj_type": getattr(node, "obj_type", "") or "",
                    "title": getattr(node, "title", "") or "",
                }
            return None
        except (TenantResolutionError, TokenUnavailable):
            raise
        except Exception as e:
            logger.error("[LARK_WIKI] get_node_error token=%s error=%s", wiki_token, e, exc_info=True)
            return None

    async def alist_drive_folder_files(
        self,
        folder_token: str,
        page_size: int = 50,
        max_files: int = 200,
        tenant_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Liệt kê danh sách các tệp và thư mục con trong một thư mục Lark Drive (async).
        Ưu tiên Bot Token trước; chỉ fallback User Token khi Lark từ chối quyền.
        """
        if not folder_token:
            return []

        from lark_oapi.api.drive.v1 import ListFileRequest
        active_opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
        used_user_fallback = False
        files: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        has_more = True

        try:
            while has_more and len(files) < max_files:
                builder = ListFileRequest.builder().folder_token(folder_token).page_size(page_size)
                if page_token:
                    builder.page_token(page_token)
                req = builder.build()

                resp = await self.client.drive.v1.file.alist(req, active_opt)
                if not resp.success() and not used_user_fallback and self._is_lark_permission_denied(resp):
                    user_opt = self._try_get_user_request_option(tenant_key=tenant_key)
                    if user_opt is not None:
                        logger.info(
                            "[LARK_DRIVE] folder_list_retry mode=user folder=%s code=%s msg=%s",
                            folder_token,
                            resp.code,
                            resp.msg,
                        )
                        active_opt = user_opt
                        used_user_fallback = True
                        resp = await self.client.drive.v1.file.alist(req, active_opt)

                if not resp.success():
                    logger.error(
                        "[LARK_DRIVE] folder_list_failed folder=%s code=%s msg=%s",
                        folder_token,
                        resp.code,
                        resp.msg,
                    )
                    break

                if resp.data and hasattr(resp.data, "files") and resp.data.files:
                    for f in resp.data.files:
                        files.append({
                            "token": getattr(f, "token", "") or "",
                            "name": getattr(f, "name", "") or "",
                            "type": getattr(f, "type", "") or "",
                            "url": getattr(f, "url", "") or "",
                            "parent_token": getattr(f, "parent_token", "") or folder_token,
                        })

                has_more = getattr(resp.data, "has_more", False) if resp.data else False
                page_token = getattr(resp.data, "next_page_token", None) if resp.data else None
                if not page_token:
                    break

            logger.info("[LARK_DRIVE] folder_listed folder=%s items=%d", folder_token, len(files))
            return files
        except (TenantResolutionError, TokenUnavailable):
            raise
        except Exception as e:
            logger.error("[LARK_DRIVE] folder_list_error folder=%s error=%s", folder_token, e, exc_info=True)
            return files

    def list_drive_folder_files(
        self,
        folder_token: str,
        page_size: int = 50,
        max_files: int = 200,
        tenant_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Phiên bản đồng bộ của alist_drive_folder_files (Bot Token trước, User Token khi bị từ chối quyền)."""
        if not folder_token:
            return []

        from lark_oapi.api.drive.v1 import ListFileRequest
        active_opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
        used_user_fallback = False
        files: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        has_more = True

        try:
            while has_more and len(files) < max_files:
                builder = ListFileRequest.builder().folder_token(folder_token).page_size(page_size)
                if page_token:
                    builder.page_token(page_token)
                req = builder.build()

                resp = self.client.drive.v1.file.list(req, active_opt)
                if not resp.success() and not used_user_fallback and self._is_lark_permission_denied(resp):
                    user_opt = self._try_get_user_request_option(tenant_key=tenant_key)
                    if user_opt is not None:
                        logger.info(
                            "[LARK_DRIVE] folder_list_retry mode=user folder=%s code=%s msg=%s",
                            folder_token,
                            resp.code,
                            resp.msg,
                        )
                        active_opt = user_opt
                        used_user_fallback = True
                        resp = self.client.drive.v1.file.list(req, active_opt)

                if not resp.success():
                    logger.error(
                        "[LARK_DRIVE] folder_list_failed folder=%s code=%s msg=%s",
                        folder_token,
                        resp.code,
                        resp.msg,
                    )
                    break

                if resp.data and hasattr(resp.data, "files") and resp.data.files:
                    for f in resp.data.files:
                        files.append({
                            "token": getattr(f, "token", "") or "",
                            "name": getattr(f, "name", "") or "",
                            "type": getattr(f, "type", "") or "",
                            "url": getattr(f, "url", "") or "",
                            "parent_token": getattr(f, "parent_token", "") or folder_token,
                        })

                has_more = getattr(resp.data, "has_more", False) if resp.data else False
                page_token = getattr(resp.data, "next_page_token", None) if resp.data else None
                if not page_token:
                    break

            logger.info("[LARK_DRIVE] folder_listed folder=%s items=%d", folder_token, len(files))
            return files
        except (TenantResolutionError, TokenUnavailable):
            raise
        except Exception as e:
            logger.error("[LARK_DRIVE] folder_list_error folder=%s error=%s", folder_token, e, exc_info=True)
            return files

    async def adownload_drive_file(self, file_token: str, tenant_key: Optional[str] = None) -> Optional[bytes]:
        """
        Tải nội dung nhị phân của tệp từ Lark Drive qua OpenAPI (async).
        Ưu tiên Bot Token trước; chỉ fallback User Token khi Lark từ chối quyền.
        """
        if not file_token:
            return None

        from lark_oapi.api.drive.v1 import DownloadFileRequest
        bot_opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
        req = DownloadFileRequest.builder().file_token(file_token).build()

        try:
            resp = await self.client.drive.v1.file.adownload(req, bot_opt)
            if not resp.success() and self._is_lark_permission_denied(resp):
                user_opt = self._try_get_user_request_option(tenant_key=tenant_key)
                if user_opt is not None:
                    logger.info(
                        "[LARK_DRIVE] file_download_retry mode=user token=%s code=%s msg=%s",
                        file_token,
                        resp.code,
                        resp.msg,
                    )
                    resp = await self.client.drive.v1.file.adownload(req, user_opt)

            if not resp.success():
                logger.error(
                    "[LARK_DRIVE] file_download_failed token=%s code=%s msg=%s",
                    file_token,
                    resp.code,
                    resp.msg,
                )
                return None

            if hasattr(resp, "file") and resp.file:
                if hasattr(resp.file, "read"):
                    return resp.file.read()
                elif isinstance(resp.file, (bytes, bytearray)):
                    return bytes(resp.file)
            return None
        except (TenantResolutionError, TokenUnavailable):
            raise
        except Exception as e:
            logger.error("[LARK_DRIVE] file_download_error token=%s error=%s", file_token, e, exc_info=True)
            return None

    def download_drive_file(self, file_token: str, tenant_key: Optional[str] = None) -> Optional[bytes]:
        """Phiên bản đồng bộ của adownload_drive_file (Bot Token trước, User Token khi bị từ chối quyền)."""
        if not file_token:
            return None

        from lark_oapi.api.drive.v1 import DownloadFileRequest
        bot_opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
        req = DownloadFileRequest.builder().file_token(file_token).build()

        try:
            resp = self.client.drive.v1.file.download(req, bot_opt)
            if not resp.success() and self._is_lark_permission_denied(resp):
                user_opt = self._try_get_user_request_option(tenant_key=tenant_key)
                if user_opt is not None:
                    logger.info(
                        "[LARK_DRIVE] file_download_retry mode=user token=%s code=%s msg=%s",
                        file_token,
                        resp.code,
                        resp.msg,
                    )
                    resp = self.client.drive.v1.file.download(req, user_opt)

            if not resp.success():
                logger.error(
                    "[LARK_DRIVE] file_download_failed token=%s code=%s msg=%s",
                    file_token,
                    resp.code,
                    resp.msg,
                )
                return None

            if hasattr(resp, "file") and resp.file:
                if hasattr(resp.file, "read"):
                    return resp.file.read()
                elif isinstance(resp.file, (bytes, bytearray)):
                    return bytes(resp.file)
            return None
        except (TenantResolutionError, TokenUnavailable):
            raise
        except Exception as e:
            logger.error("[LARK_DRIVE] file_download_error token=%s error=%s", file_token, e, exc_info=True)
            return None

