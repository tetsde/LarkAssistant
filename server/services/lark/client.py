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
from core.tenant_errors import TenantContextMissing, TokenUnavailable
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
        """Khởi tạo Lark Client và các biến quản lý danh tính."""
        if config is not None:
            self.config = config
        else:
            # Ưu tiên lấy token sống từ MongoDB lark_auth nếu có và còn hạn
            stored_user_token = ""
            stored_open_id = ""
            try:
                import time
                from database.db import get_sync_db
                db = get_sync_db()
                doc = db[settings.MONGO_AUTH_COLLECTION].find_one({"_id": "primary_user_token"})
                if doc:
                    stored_open_id = doc.get("open_id", "")
                    if doc.get("access_token") and doc.get("expires_at", 0) > time.time():
                        stored_user_token = doc["access_token"]
                    else:
                            app_collection = getattr(settings, "MONGO_LARK_APPS_COLLECTION", "lark_app_credentials")
                            scoped_app = db[app_collection].find_one({
                                "tenant_key": {"$exists": True, "$nin": [None, ""]},
                                "status": {"$ne": "revoked"},
                            }, {"_id": 1})
                            if not scoped_app:
                                logger.debug("[LARK_CLIENT] legacy_token_expired action=skip")
            except Exception:
                pass

            self.config = LarkConfig(
                app_id=app_id or "",
                app_secret=app_secret or "",
                verification_token=verification_token or settings.LARK_VERIFICATION_TOKEN or "",
                encrypt_key=encrypt_key or settings.LARK_ENCRYPT_KEY or "",
                domain=domain or settings.LARK_DOMAIN or lark.LARK_DOMAIN,
                user_access_token=user_access_token or stored_user_token or settings.LARK_USER_ACCESS_TOKEN or "",
                user_open_id=user_open_id or stored_open_id or settings.LARK_USER_OPEN_ID or "",
            )

        self.app_id = self.config.app_id
        self.app_secret = self.config.app_secret
        self.verification_token = self.config.verification_token
        self.encrypt_key = self.config.encrypt_key
        self.domain = self.config.domain or lark.LARK_DOMAIN
        self.user_access_token = self.config.user_access_token

        # Khởi tạo Lark API Client (bật enable_set_token để cho phép dùng user_access_token)
        self.client: lark.Client = (
            lark.Client.builder()
            .app_id(self.app_id)
            .app_secret(self.app_secret)
            .domain(self.domain)
            .enable_set_token(True)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

        # Cache thông tin của User hiện tại (open_id đọc từ .env hoặc settings)
        self.known_user_open_id = (
            getattr(self.config, "user_open_id", "")
            or settings.LARK_USER_OPEN_ID
            or os.getenv("user_open_id", "")
        )
        self._current_user_profile: Optional[Dict[str, Any]] = None

        # Danh sách các message_id do chính hệ thống gửi đi (chống vòng lặp tự reply)
        self._sent_message_ids: OrderedDict[str, float] = OrderedDict()
        # Cache tên người dùng với giới hạn bộ nhớ (user_id -> (name, cached_at))
        self._user_name_cache: OrderedDict[str, Tuple[str, float]] = OrderedDict()

    # -------------------------------------------------------------------------
    # QUẢN LÝ DANH TÍNH USER (USER IDENTITY MANAGEMENT)
    # -------------------------------------------------------------------------

    def get_current_user(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Tra cứu thông tin hồ sơ của User được cấp quyền bởi `access_token_user`.
        """
        if self._current_user_profile and not force_refresh:
            return self._current_user_profile

        fallback_profile = {
            "name": settings.LARK_USER_NAME or "",
            "open_id": self.known_user_open_id,
            "union_id": "",
            "avatar_url": "",
            "email": "",
            "mobile": "",
            "tenant_key": "",
        }

        if not self.user_access_token:
            self._current_user_profile = fallback_profile
            return fallback_profile

        opt = self._get_request_option(as_user=True)
        try:
            req = GetUserInfoRequest.builder().build()
            resp = self.client.authen.v1.user_info.get(req, opt)
            if not resp.success():
                logger.warning(
                    "[LARK_CLIENT] user_info_failed code=%s msg=%s fallback=profile",
                    resp.code,
                    resp.msg,
                )
                self._current_user_profile = fallback_profile
                return fallback_profile

            data = resp.data
            open_id = getattr(data, "open_id", "") or self.known_user_open_id
            profile = {
                "name": getattr(data, "name", "") or "",
                "open_id": open_id,
                "union_id": getattr(data, "union_id", ""),
                "avatar_url": getattr(data, "avatar_url", ""),
                "email": getattr(data, "email", "") or getattr(data, "enterprise_email", ""),
                "mobile": getattr(data, "mobile", ""),
                "tenant_key": getattr(data, "tenant_key", ""),
            }
            self._current_user_profile = profile
            if open_id:
                self.known_user_open_id = open_id
            logger.debug("[LARK_CLIENT] user_profile_loaded open_id=%s", profile["open_id"])
            return profile
        except Exception as e:
            logger.error("[LARK_CLIENT] user_info_error error=%s", e, exc_info=True)
            self._current_user_profile = fallback_profile
            return fallback_profile

    @property
    def owner_open_id(self) -> str:
        """
        Tự động trích xuất và trả về Open ID của chủ nhân từ User Access Token hoặc cấu hình Onboarding.
        Không cần phải cấu hình thủ công user_open_id hay digest_approver_id trong .env.
        """
        if self.known_user_open_id:
            return self.known_user_open_id
        if getattr(settings, "LARK_USER_OPEN_ID", None) and settings.LARK_USER_OPEN_ID.strip():
            self.known_user_open_id = settings.LARK_USER_OPEN_ID.strip()
            return self.known_user_open_id
        if self._current_user_profile and self._current_user_profile.get("open_id"):
            self.known_user_open_id = self._current_user_profile["open_id"]
            return self.known_user_open_id

        # Thử lấy từ MongoDB đồng bộ nếu đã được lưu từ Onboarding Screen Guide
        try:
            from database.db import get_sync_db
            sdb = get_sync_db()
            us_doc = sdb["user_settings"].find_one({"open_id": {"$exists": True, "$ne": ""}}, sort=[("updated_at", -1)])
            if us_doc and us_doc.get("open_id") and str(us_doc["open_id"]).strip():
                self.known_user_open_id = str(us_doc["open_id"]).strip()
                return self.known_user_open_id
            adm_doc = sdb["system_config"].find_one({"config_key": "lark_admin_config"})
            if adm_doc and adm_doc.get("admin_open_id") and str(adm_doc["admin_open_id"]).strip():
                self.known_user_open_id = str(adm_doc["admin_open_id"]).strip()
                return self.known_user_open_id
            t_doc = sdb["tenants"].find_one({"admin_open_id": {"$exists": True, "$ne": ""}})
            if t_doc and t_doc.get("admin_open_id") and str(t_doc["admin_open_id"]).strip():
                self.known_user_open_id = str(t_doc["admin_open_id"]).strip()
                return self.known_user_open_id
        except Exception:
            pass

        prof = self.get_current_user()
        found_id = prof.get("open_id") or getattr(settings, "LARK_USER_OPEN_ID", "") or ""
        if found_id:
            self.known_user_open_id = found_id
        return found_id

    def check_user_access_token(self, force_ping: bool = False) -> Any:
        """
        Kiểm tra và ping trực tiếp User Access Token xem còn sống hay đã hết hạn (expire).
        Hỗ trợ cache để tránh spam network, force_ping=True để ping lại tức thì.
        """
        if not hasattr(self, "_last_token_check") or force_ping or not self._last_token_check:
            from services.auth.token_verifier import ping_user_access_token
            self._last_token_check = ping_user_access_token(
                token=self.user_access_token,
                domain=self.domain,
            )
        return self._last_token_check

    def is_user_token_valid(self) -> bool:
        """Kiểm tra nhanh xem token còn hợp lệ không."""
        res = self.check_user_access_token()
        return bool(res and res.is_valid)

    def get_user_name(self, user_id: str) -> Optional[str]:
        """Lấy họ tên hiển thị của một người dùng theo open_id/user_id (kèm TTL 1h & max size 1000)."""
        if not user_id:
            return None
        if not hasattr(self, "_user_name_cache") or self._user_name_cache is None:
            self._user_name_cache = OrderedDict()

        now = time.time()
        # Kiểm tra cache còn hạn (TTL 3600s = 1 giờ)
        if user_id in self._user_name_cache:
            name, cached_at = self._user_name_cache[user_id]
            if now - cached_at < 3600:
                return name
            del self._user_name_cache[user_id]

        try:
            from lark_oapi.api.contact.v3 import GetUserRequest
            opt = self._get_request_option(as_user=True)
            req = GetUserRequest.builder().user_id(user_id).user_id_type("open_id").build()
            resp = self.client.contact.v3.user.get(req, opt)
            if not resp.success() and opt is not None:
                req_bot = GetUserRequest.builder().user_id(user_id).user_id_type("open_id").build()
                resp = self.client.contact.v3.user.get(req_bot)
            if resp.success() and resp.data and resp.data.user:
                name = resp.data.user.name
                if name:
                    # Dọn dẹp cache quá hạn 1 giờ
                    while self._user_name_cache and (now - next(iter(self._user_name_cache.values()))[1] > 3600):
                        self._user_name_cache.popitem(last=False)
                    self._user_name_cache[user_id] = (name, now)
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

    def _get_user_request_option(self) -> lark.RequestOption:
        """
        BẮT BUỘC tạo RequestOption mang User Access Token.
        Tuyệt đối không bao giờ trả về None (vì trả về None sẽ khiến Lark SDK tự lấy Bot App Token để gửi).
        """
        if not self.user_access_token:
            raise ValueError("Chưa cấu hình `access_token_user` trong .env! Hệ thống chỉ được phép gửi bằng danh tính người dùng.")
        return lark.RequestOption.builder().user_access_token(self.user_access_token).build()

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
    ) -> Optional[lark.RequestOption]:
        """Tạo RequestOption mang danh tính User (user token) hoặc Bot (tenant token)."""
        if as_user:
            eff_tenant = self._effective_tenant(tenant_key)
            valid_token = self._token_via_broker(eff_tenant, "user")
            if not valid_token:
                raise TokenUnavailable(
                    f"Broker trả về user token rỗng cho tenant '{eff_tenant}'.",
                    tenant_key=eff_tenant,
                    kind="user",
                )
            self.user_access_token = valid_token
            return self._build_user_option(valid_token, tenant_key)

        if tenant_key:
            if getattr(settings, "IS_ISV_MODE", False):
                from services.auth.isv_token_service import isv_token_service
                return isv_token_service.build_request_option(tenant_key=tenant_key)
            # Custom App: gửi bằng danh tính Bot của đúng App thuộc tenant này.
            bot_token = self._token_via_broker(tenant_key, "bot")
            builder = lark.RequestOption.builder().tenant_access_token(bot_token)
            return builder.tenant_key(tenant_key).build()
        return None

    # -------------------------------------------------------------------------
    # TẢI TÀI NGUYÊN & PHÂN GIẢI TÀI LIỆU (DOCUMENT & RESOURCE ACCESS)
    # -------------------------------------------------------------------------

    async def adownload_message_resource(
        self,
        message_id: str,
        file_key: str,
        resource_type: str = "file",
    ) -> Optional[bytes]:
        """
        Tải tài nguyên nhị phân (tệp đính kèm hoặc hình ảnh) từ tin nhắn Lark IM (async).

        Args:
            message_id: ID của tin nhắn chứa tệp.
            file_key: Key của tệp (file_key cho file hoặc image_key cho ảnh).
            resource_type: 'file' (mặc định) hoặc 'image'.

        Returns:
            bytes nếu tải thành công, None nếu thất bại.
        """
        if not message_id or not file_key:
            logger.warning("[LARK_IM] download_skipped reason=empty_ids")
            return None

        from lark_oapi.api.im.v1 import GetMessageResourceRequest
        opt = self._get_request_option(as_user=True)
        req = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(file_key)
            .type(resource_type)
            .build()
        )
        try:
            resp = await self.client.im.v1.message_resource.aget(req, opt)
            if not resp.success() and opt is not None:
                logger.warning(
                    "[LARK_IM] resource_download_retry mode=bot code=%s msg=%s",
                    resp.code,
                    resp.msg,
                )
                req_bot = (
                    GetMessageResourceRequest.builder()
                    .message_id(message_id)
                    .file_key(file_key)
                    .type(resource_type)
                    .build()
                )
                resp = await self.client.im.v1.message_resource.aget(req_bot)

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
        except Exception as e:
            logger.error("[LARK_IM] resource_download_error key=%s error=%s", file_key, e, exc_info=True)
            return None

    def download_message_resource(
        self,
        message_id: str,
        file_key: str,
        resource_type: str = "file",
    ) -> Optional[bytes]:
        """Phiên bản đồng bộ của adownload_message_resource."""
        if not message_id or not file_key:
            return None

        from lark_oapi.api.im.v1 import GetMessageResourceRequest
        opt = self._get_request_option(as_user=True)
        req = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(file_key)
            .type(resource_type)
            .build()
        )
        try:
            resp = self.client.im.v1.message_resource.get(req, opt)
            if not resp.success() and opt is not None:
                logger.warning(
                    "[LARK_IM] resource_download_retry mode=bot code=%s msg=%s",
                    resp.code,
                    resp.msg,
                )
                req_bot = (
                    GetMessageResourceRequest.builder()
                    .message_id(message_id)
                    .file_key(file_key)
                    .type(resource_type)
                    .build()
                )
                resp = self.client.im.v1.message_resource.get(req_bot)

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
        except Exception as e:
            logger.error("[LARK_IM] resource_download_error key=%s error=%s", file_key, e, exc_info=True)
            return None

    async def aget_docx_raw_content(self, document_id: str, tenant_key: Optional[str] = None) -> Optional[str]:
        """
        Lấy nội dung Markdown nguyên bản của tài liệu Lark DocX qua OpenAPI (async, 0 token cost).

        Args:
            document_id: ID của tài liệu DocX (document_id hoặc obj_token).
            tenant_key: Tenant key để xác định context (WS7 fix).

        Returns:
            Chuỗi Markdown thuần nếu thành công, None nếu thất bại.
        """
        if not document_id:
            return None

        from lark_oapi.api.docx.v1 import RawContentDocumentRequest
        opt = self._get_request_option(as_user=True, tenant_key=tenant_key)
        req = RawContentDocumentRequest.builder().document_id(document_id).build()
        try:
            resp = await self.client.docx.v1.document.araw_content(req, opt)
            if not resp.success() and opt is not None:
                logger.warning(
                    "[LARK_DOCX] raw_content_retry mode=bot code=%s msg=%s",
                    resp.code,
                    resp.msg,
                )
                req_bot = RawContentDocumentRequest.builder().document_id(document_id).build()
                resp = await self.client.docx.v1.document.araw_content(req_bot)

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
        except Exception as e:
            logger.error("[LARK_DOCX] raw_content_error doc=%s error=%s", document_id, e, exc_info=True)
            return None

    def get_docx_raw_content(self, document_id: str) -> Optional[str]:
        """Phiên bản đồng bộ của aget_docx_raw_content."""
        if not document_id:
            return None

        from lark_oapi.api.docx.v1 import RawContentDocumentRequest
        opt = self._get_request_option(as_user=True)
        req = RawContentDocumentRequest.builder().document_id(document_id).build()
        try:
            resp = self.client.docx.v1.document.raw_content(req, opt)
            if not resp.success() and opt is not None:
                logger.warning(
                    "[LARK_DOCX] raw_content_retry mode=bot code=%s msg=%s",
                    resp.code,
                    resp.msg,
                )
                req_bot = RawContentDocumentRequest.builder().document_id(document_id).build()
                resp = self.client.docx.v1.document.raw_content(req_bot)

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
        except Exception as e:
            logger.error("[LARK_DOCX] raw_content_error doc=%s error=%s", document_id, e, exc_info=True)
            return None

    async def aresolve_wiki_token(self, wiki_token: str, tenant_key: Optional[str] = None) -> Optional[Dict[str, str]]:
        """
        Giải mã wiki node token thành obj_token và obj_type (ví dụ: docx, sheet, bitable).

        Args:
            wiki_token: Token của trang Wiki.
            tenant_key: Tenant key để xác định context (WS7 fix).

        Returns:
            Dict {"obj_token": str, "obj_type": str, "title": str} nếu thành công, None nếu thất bại.
        """
        if not wiki_token:
            return None

        from lark_oapi.api.wiki.v2 import GetNodeSpaceRequest
        opt = self._get_request_option(as_user=True, tenant_key=tenant_key)
        req = GetNodeSpaceRequest.builder().token(wiki_token).build()
        try:
            resp = await self.client.wiki.v2.space.aget_node(req, opt)
            if not resp.success() and opt is not None:
                logger.warning(
                    "[LARK_WIKI] get_node_retry mode=bot code=%s msg=%s",
                    resp.code,
                    resp.msg,
                )
                req_bot = GetNodeSpaceRequest.builder().token(wiki_token).build()
                resp = await self.client.wiki.v2.space.aget_node(req_bot)

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
        except Exception as e:
            logger.error("[LARK_WIKI] get_node_error token=%s error=%s", wiki_token, e, exc_info=True)
            return None

    def resolve_wiki_token(self, wiki_token: str) -> Optional[Dict[str, str]]:
        """Phiên bản đồng bộ của aresolve_wiki_token."""
        if not wiki_token:
            return None

        from lark_oapi.api.wiki.v2 import GetNodeSpaceRequest
        opt = self._get_request_option(as_user=True)
        req = GetNodeSpaceRequest.builder().token(wiki_token).build()
        try:
            resp = self.client.wiki.v2.space.get_node(req, opt)
            if not resp.success() and opt is not None:
                logger.warning(
                    "[LARK_WIKI] get_node_retry mode=bot code=%s msg=%s",
                    resp.code,
                    resp.msg,
                )
                req_bot = GetNodeSpaceRequest.builder().token(wiki_token).build()
                resp = self.client.wiki.v2.space.get_node(req_bot)

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

        Args:
            folder_token: Token của thư mục Lark Drive (e.g. 'fldcnXXXXXXXX').
            page_size: Số lượng tệp mỗi trang (mặc định 50).
            max_files: Giới hạn tối đa số tệp thu thập để tránh bùng nổ tài nguyên.
            tenant_key: Định danh tenant để đảm bảo cô lập token (fail-closed).

        Returns:
            Danh sách dict: [{"token": str, "name": str, "type": str, "url": str, "parent_token": str}]
        """
        if not folder_token:
            return []

        from lark_oapi.api.drive.v1 import ListFileRequest
        opt = self._get_request_option(as_user=True, tenant_key=tenant_key)
        files: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        has_more = True

        try:
            while has_more and len(files) < max_files:
                builder = ListFileRequest.builder().folder_token(folder_token).page_size(page_size)
                if page_token:
                    builder.page_token(page_token)
                req = builder.build()

                resp = await self.client.drive.v1.file.alist(req, opt)
                if not resp.success() and opt is not None:
                    logger.warning(
                        "[LARK_DRIVE] folder_list_retry mode=bot code=%s msg=%s",
                        resp.code,
                        resp.msg,
                    )
                    bot_opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
                    resp = await self.client.drive.v1.file.alist(req, bot_opt)

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
        """Phiên bản đồng bộ của alist_drive_folder_files."""
        if not folder_token:
            return []

        from lark_oapi.api.drive.v1 import ListFileRequest
        opt = self._get_request_option(as_user=True, tenant_key=tenant_key)
        files: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        has_more = True

        try:
            while has_more and len(files) < max_files:
                builder = ListFileRequest.builder().folder_token(folder_token).page_size(page_size)
                if page_token:
                    builder.page_token(page_token)
                req = builder.build()

                resp = self.client.drive.v1.file.list(req, opt)
                if not resp.success() and opt is not None:
                    logger.warning(
                        "[LARK_DRIVE] folder_list_retry mode=bot code=%s msg=%s",
                        resp.code,
                        resp.msg,
                    )
                    bot_opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
                    resp = self.client.drive.v1.file.list(req, bot_opt)

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
        except Exception as e:
            logger.error("[LARK_DRIVE] folder_list_error folder=%s error=%s", folder_token, e, exc_info=True)
            return files

    async def adownload_drive_file(self, file_token: str, tenant_key: Optional[str] = None) -> Optional[bytes]:
        """
        Tải nội dung nhị phân của tệp từ Lark Drive qua OpenAPI (async).

        Args:
            file_token: Token của tệp trên Drive.
            tenant_key: Định danh tenant để đảm bảo cô lập token (fail-closed).

        Returns:
            bytes nếu thành công, None nếu thất bại.
        """
        if not file_token:
            return None

        from lark_oapi.api.drive.v1 import DownloadFileRequest
        opt = self._get_request_option(as_user=True, tenant_key=tenant_key)
        req = DownloadFileRequest.builder().file_token(file_token).build()

        try:
            resp = await self.client.drive.v1.file.adownload(req, opt)
            if not resp.success() and opt is not None:
                logger.warning(
                    "[LARK_DRIVE] file_download_retry mode=bot code=%s msg=%s",
                    resp.code,
                    resp.msg,
                )
                bot_opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
                resp = await self.client.drive.v1.file.adownload(req, bot_opt)

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
        except Exception as e:
            logger.error("[LARK_DRIVE] file_download_error token=%s error=%s", file_token, e, exc_info=True)
            return None

    def download_drive_file(self, file_token: str, tenant_key: Optional[str] = None) -> Optional[bytes]:
        """Phiên bản đồng bộ của adownload_drive_file."""
        if not file_token:
            return None

        from lark_oapi.api.drive.v1 import DownloadFileRequest
        opt = self._get_request_option(as_user=True, tenant_key=tenant_key)
        req = DownloadFileRequest.builder().file_token(file_token).build()

        try:
            resp = self.client.drive.v1.file.download(req, opt)
            if not resp.success() and opt is not None:
                logger.warning(
                    "[LARK_DRIVE] file_download_retry mode=bot code=%s msg=%s",
                    resp.code,
                    resp.msg,
                )
                bot_opt = self._get_request_option(as_user=False, tenant_key=tenant_key)
                resp = self.client.drive.v1.file.download(req, bot_opt)

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
        except Exception as e:
            logger.error("[LARK_DRIVE] file_download_error token=%s error=%s", file_token, e, exc_info=True)
            return None

