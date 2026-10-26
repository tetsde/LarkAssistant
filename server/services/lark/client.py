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
                        logger.info("ℹ️ User Token trong MongoDB đã hết hạn, bỏ qua lúc init client.")
            except Exception:
                pass

            self.config = LarkConfig(
                app_id=app_id or settings.LARK_APP_ID or "",
                app_secret=app_secret or settings.LARK_APP_SECRET or "",
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

        # Cache thông tin của User hiện tại (Tên, open_id đọc từ .env hoặc settings)
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
            "name": settings.LARK_USER_NAME or "User",
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
                logger.warning(f"Lỗi lấy thông tin user từ token ({resp.msg}, code {resp.code}). Sử dụng profile mặc định.")
                self._current_user_profile = fallback_profile
                return fallback_profile

            data = resp.data
            open_id = getattr(data, "open_id", "") or self.known_user_open_id
            profile = {
                "name": getattr(data, "name", "") or "User",
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
            logger.info(f"👤 Đang hoạt động dưới danh tính User: {profile['name']} (open_id: {profile['open_id']})")
            return profile
        except Exception as e:
            logger.error(f"Exception khi lấy user info: {e}", exc_info=True)
            self._current_user_profile = fallback_profile
            return fallback_profile

    @property
    def owner_open_id(self) -> str:
        """
        Tự động trích xuất và trả về Open ID của chủ nhân từ User Access Token.
        Không cần phải cấu hình thủ công user_open_id hay digest_approver_id trong .env.
        """
        if self.known_user_open_id:
            return self.known_user_open_id
        if self._current_user_profile and self._current_user_profile.get("open_id"):
            return self._current_user_profile["open_id"]
        prof = self.get_current_user()
        return prof.get("open_id") or getattr(settings, "LARK_USER_OPEN_ID", "") or ""

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

    def _get_request_option(self, as_user: bool = True) -> Optional[lark.RequestOption]:
        """Tạo RequestOption mang User Token nếu as_user=True và token khả dụng."""
        if as_user and self.user_access_token:
            return lark.RequestOption.builder().user_access_token(self.user_access_token).build()
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
            logger.warning("adownload_message_resource: message_id hoặc file_key rỗng.")
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
                    f"⚠️ [LARK IM] Tải tài nguyên bằng User Token thất bại (code={resp.code}, msg={resp.msg}), fallback sang Bot token..."
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
                    f"❌ [LARK IM] Tải tài nguyên thất bại (msg_id={message_id}, key={file_key}): "
                    f"code={resp.code}, msg={resp.msg}"
                )
                return None

            if hasattr(resp, "file") and resp.file:
                if hasattr(resp.file, "read"):
                    return resp.file.read()
                elif isinstance(resp.file, (bytes, bytearray)):
                    return bytes(resp.file)
            return None
        except Exception as e:
            logger.error(f"❌ [LARK IM] Exception khi tải tài nguyên {file_key}: {e}", exc_info=True)
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
                    f"⚠️ [LARK IM] Tải tài nguyên bằng User Token thất bại (code={resp.code}, msg={resp.msg}), fallback sang Bot token..."
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
                    f"❌ [LARK IM] Tải tài nguyên thất bại (msg_id={message_id}, key={file_key}): "
                    f"code={resp.code}, msg={resp.msg}"
                )
                return None

            if hasattr(resp, "file") and resp.file:
                if hasattr(resp.file, "read"):
                    return resp.file.read()
                elif isinstance(resp.file, (bytes, bytearray)):
                    return bytes(resp.file)
            return None
        except Exception as e:
            logger.error(f"❌ [LARK IM] Exception khi tải tài nguyên {file_key}: {e}", exc_info=True)
            return None

    async def aget_docx_raw_content(self, document_id: str) -> Optional[str]:
        """
        Lấy nội dung Markdown nguyên bản của tài liệu Lark DocX qua OpenAPI (async, 0 token cost).

        Args:
            document_id: ID của tài liệu DocX (document_id hoặc obj_token).

        Returns:
            Chuỗi Markdown thuần nếu thành công, None nếu thất bại.
        """
        if not document_id:
            return None

        from lark_oapi.api.docx.v1 import RawContentDocumentRequest
        opt = self._get_request_option(as_user=True)
        req = RawContentDocumentRequest.builder().document_id(document_id).build()
        try:
            resp = await self.client.docx.v1.document.araw_content(req, opt)
            if not resp.success() and opt is not None:
                logger.warning(
                    f"⚠️ [LARK DOCX] Lấy raw content bằng User Token thất bại (code={resp.code}, msg={resp.msg}), fallback sang Bot token..."
                )
                req_bot = RawContentDocumentRequest.builder().document_id(document_id).build()
                resp = await self.client.docx.v1.document.araw_content(req_bot)

            if not resp.success():
                logger.error(
                    f"❌ [LARK DOCX] Lấy raw content document {document_id} thất bại: "
                    f"code={resp.code}, msg={resp.msg}"
                )
                return None

            if resp.data and hasattr(resp.data, "content"):
                return resp.data.content or ""
            return ""
        except Exception as e:
            logger.error(f"❌ [LARK DOCX] Exception khi lấy raw content document {document_id}: {e}", exc_info=True)
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
                    f"⚠️ [LARK DOCX] Lấy raw content bằng User Token thất bại (code={resp.code}, msg={resp.msg}), fallback sang Bot token..."
                )
                req_bot = RawContentDocumentRequest.builder().document_id(document_id).build()
                resp = self.client.docx.v1.document.raw_content(req_bot)

            if not resp.success():
                logger.error(
                    f"❌ [LARK DOCX] Lấy raw content document {document_id} thất bại: "
                    f"code={resp.code}, msg={resp.msg}"
                )
                return None

            if resp.data and hasattr(resp.data, "content"):
                return resp.data.content or ""
            return ""
        except Exception as e:
            logger.error(f"❌ [LARK DOCX] Exception khi lấy raw content document {document_id}: {e}", exc_info=True)
            return None

    async def aresolve_wiki_token(self, wiki_token: str) -> Optional[Dict[str, str]]:
        """
        Giải mã wiki node token thành obj_token và obj_type (ví dụ: docx, sheet, bitable).

        Args:
            wiki_token: Token của trang Wiki.

        Returns:
            Dict {"obj_token": str, "obj_type": str, "title": str} nếu thành công, None nếu thất bại.
        """
        if not wiki_token:
            return None

        from lark_oapi.api.wiki.v2 import GetNodeSpaceRequest
        opt = self._get_request_option(as_user=True)
        req = GetNodeSpaceRequest.builder().token(wiki_token).build()
        try:
            resp = await self.client.wiki.v2.space.aget_node(req, opt)
            if not resp.success() and opt is not None:
                logger.warning(
                    f"⚠️ [LARK WIKI] Tra cứu wiki node bằng User Token thất bại (code={resp.code}, msg={resp.msg}), fallback sang Bot token..."
                )
                req_bot = GetNodeSpaceRequest.builder().token(wiki_token).build()
                resp = await self.client.wiki.v2.space.aget_node(req_bot)

            if not resp.success():
                logger.error(
                    f"❌ [LARK WIKI] Tra cứu wiki node {wiki_token} thất bại: "
                    f"code={resp.code}, msg={resp.msg}"
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
            logger.error(f"❌ [LARK WIKI] Exception khi tra cứu wiki node {wiki_token}: {e}", exc_info=True)
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
                    f"⚠️ [LARK WIKI] Tra cứu wiki node bằng User Token thất bại (code={resp.code}, msg={resp.msg}), fallback sang Bot token..."
                )
                req_bot = GetNodeSpaceRequest.builder().token(wiki_token).build()
                resp = self.client.wiki.v2.space.get_node(req_bot)

            if not resp.success():
                logger.error(
                    f"❌ [LARK WIKI] Tra cứu wiki node {wiki_token} thất bại: "
                    f"code={resp.code}, msg={resp.msg}"
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
            logger.error(f"❌ [LARK WIKI] Exception khi tra cứu wiki node {wiki_token}: {e}", exc_info=True)
            return None

