"""
Module kết nối, đọc và đồng bộ dữ liệu hai chiều từ Lark Base (Bitable) API.
Hỗ trợ cả cơ chế Đồng bộ (Sync) cho Scripts/Bot CLI và Bất đồng bộ Native (Async) cho FastAPI Server.

Vị trí: server/services/larkbase.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
import lark_oapi as lark
from lark_oapi.api.drive.v1 import (
    P2DriveFileBitableRecordChangedV1,
    P2DriveFileBitableFieldChangedV1,
    P2DriveFileEditV1,
)
from lark_oapi.api.im.v1 import (
    P2ImChatMemberBotAddedV1,
    P2ImChatMemberBotDeletedV1,
)

# Tự động nạp thư mục gốc của server vào sys.path để import nhất quán
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from core.config import settings
from models.larkbase import (
    BITABLE_FIELD_TYPE_MAP,
    LarkBaseField,
    LarkBaseRecord,
    LarkBaseQueryResult,
)
from services.lark.cleaner import (
    clean_field_value,
    clean_record_fields,
    inspect_bitable_token,
)
from services.auth.token_verifier import decode_jwt_token_payload
from services.auth.tenant_token_manager import token_broker
from services.tenancy.tenant_resolver import TenantResources
from core.tenant_errors import (
    AppCredentialMissing,
    TenantConfigIncomplete,
    TenantContextMissing,
)

logger = logging.getLogger("hilark.larkbase")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

VIETNAM_TZ = timezone(timedelta(hours=7))

# Tên cột mặc định trong Lark Base (Hỗ trợ tương thích ngược)
DEFAULT_COL_CHAT_ID = "Chat ID"
DEFAULT_COL_PROJECT_NAME = "Tên dự án"
DEFAULT_COL_KB_ID = "Knowledge Base ID"

# Danh sách bí danh tương thích cho từng loại cột
FIELD_ALIASES = {
    "chat_id": ["Chat ID", "ID Group", "chat_id"],
    "project_name": ["Tên dự án", "Dự án / Nhóm", "Text", "chat_name", "Tên nhóm"],
    "status": ["Trạng thái hoạt động", "Trạng thái", "status"],
    "security_level": ["Cấp độ bảo mật", "Mức độ bảo mật", "security_level"],
    "documents": ["Danh mục tài liệu", "Documents", "Tài liệu", "Link tài liệu"],
    "owner": ["Người phụ trách", "Chủ sở hữu", "Owner"],
}


# =============================================================================
# HELPER: CREDENTIAL LOOKUP (STRICT, KHÔNG FALLBACK)
# =============================================================================

def _app_credentials_sync(tenant_key: Optional[str]) -> tuple[str, str]:
    """
    Lấy (app_id, app_secret) của CHÍNH tenant_key đó, qua resolver tập trung.

    Bản cũ có ba tầng: tenant → "App mới nhất trong DB" → `.env`. Hai tầng sau khiến
    một tenant vô tình dùng credential của tenant khác, nên bị bỏ hoàn toàn.
    """
    from services.tenancy.tenant_resolver import tenant_resolver

    creds = tenant_resolver.resolve_credentials_sync(tenant_key)
    return creds.app_id, creds.app_secret


# =============================================================================
# LARK BASE SERVICE CLASS
# =============================================================================

class LarkBaseService:
    """
    Service giao tiếp và thao tác dữ liệu với Lark Base (Bitable) API:
      - Quản lý xác thực qua User Access Token hoặc Bot Tenant Access Token.
      - Kiến trúc Tinh gọn: Đồng bộ (Sync) làm lõi xử lý, tích hợp Thread-based Async
        (asyncio.to_thread) non-blocking cho FastAPI endpoints & lifecycle mà không bị nhân đôi code.
      - Tái sử dụng HTTP connection pool, tự động bóc tách và chuẩn hóa dữ liệu.

    Hợp đồng đa tenant (Giai đoạn 3):
      - Một instance gắn với **một** tenant. `tenant_key` là tham số bắt buộc khi tạo.
      - `app_token`/`table_id` đến từ `TenantResources` của chính tenant đó, không vay `.env`.
      - Vì vậy không còn chuyện ghi đè field trên singleton dùng chung: hai request của hai
        tenant từng ghi đè nhau và đọc/ghi nhầm Base của nhau.
    """

    def __init__(
        self,
        tenant_key: Optional[str],
        app_token: Optional[str] = None,
        table_id: Optional[str] = None,
        user_access_token: Optional[str] = None,
        domain: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """Khởi tạo service cho MỘT tenant. `tenant_key=None` chỉ dành cho object tương thích import."""
        self.tenant_key = (tenant_key or "").strip() or None

        self.app_token = (app_token or "").strip().strip("\"'")
        self.table_id = (table_id or "").strip().strip("\"'")

        # Token không còn đọc từ `.env` hay document `primary_user_token`: mọi lối lấy
        # token đi qua broker theo (tenant_key, app_id, kind).
        self.user_access_token = (user_access_token or "").strip().strip("\"'")

        raw_domain = (
            domain
            or getattr(settings, "LARK_DOMAIN", "")
            or "https://open.larksuite.com"
        ).strip().rstrip("/")
        self.domain = raw_domain

        self.timeout = timeout

        # Persistent HTTP client (Connection Pooling)
        self._sync_client: Optional[httpx.Client] = None

    @classmethod
    def for_tenant(
        cls,
        resources: "TenantResources",
        app_token: Optional[str] = None,
        table_id: Optional[str] = None,
        timeout: float = 30.0,
    ) -> "LarkBaseService":
        """
        Tạo instance phục vụ RIÊNG tenant đã được resolver kiểm tra.

        Mặc định lấy `base_app_token`/`chat_scope_table_id` từ `resources`; caller chỉ
        truyền `app_token`/`table_id` khi muốn trỏ sang bảng khác **của cùng tenant**
        (ví dụ bảng Chính sách).
        """
        return cls(
            tenant_key=resources.tenant_key,
            app_token=(app_token or resources.base_app_token),
            table_id=(table_id or resources.chat_scope_table_id),
            timeout=timeout,
        )

    @classmethod
    def for_policy_table(cls, resources: "TenantResources") -> "LarkBaseService":
        """Instance trỏ vào bảng Sổ tay chính sách của tenant."""
        return cls(
            tenant_key=resources.tenant_key,
            app_token=resources.base_app_token,
            table_id=resources.company_policy_table_id,
        )

    # -------------------------------------------------------------------------
    # CLIENT & URL PROPERTIES
    # -------------------------------------------------------------------------

    @property
    def sync_client(self) -> httpx.Client:
        """Trả về HTTP sync client tái sử dụng connection pool."""
        if self._sync_client is None or self._sync_client.is_closed:
            self._sync_client = httpx.Client(timeout=self.timeout)
        return self._sync_client

    @property
    def _records_url(self) -> str:
        return f"{self.domain}/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records"

    @property
    def _fields_url(self) -> str:
        return f"{self.domain}/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/fields"

    @property
    def _tables_url(self) -> str:
        return f"{self.domain}/open-apis/bitable/v1/apps/{self.app_token}/tables"

    # -------------------------------------------------------------------------
    # VALIDATION & AUTHENTICATION HEADERS
    # -------------------------------------------------------------------------

    def _effective_tenant(self, tenant_key: Optional[str] = None) -> str:
        """tenant_key theo thứ tự: tham số gọi -> instance -> ContextVar. Không có → raise."""
        from database.db import get_current_tenant_key
        eff = tenant_key or self.tenant_key or get_current_tenant_key()
        if not eff:
            raise TenantContextMissing(
                "LarkBaseService không xác định được tenant; "
                "truyền tenant_key tường minh hoặc chạy trong tenant context."
            )
        return eff

    def get_tenant_access_token(self, force_refresh: bool = False, tenant_key: Optional[str] = None) -> str:
        """
        Lấy Bot Tenant Access Token (sync), chờ trên token loop riêng.

        Trước đây hàm này tự chế cache `self._tenant_token` trên singleton dùng chung,
        nên tenant B nhận token của tenant A. Cache giờ thuộc broker, khoá đủ ba chiều.
        """
        eff_tenant = self._effective_tenant(tenant_key)
        return token_broker.get_token_sync(eff_tenant, "bot", force_refresh=force_refresh)

    def _validate_config(self, use_tenant_token: bool = False, tenant_key: Optional[str] = None) -> None:
        """
        Kiểm tra điều kiện bắt buộc của một thao tác Base.

        `user_access_token` không còn là điều kiện khởi tạo: token do broker cấp theo
        tenant ngay trước mỗi request. Vì vậy thiếu token trong RAM không phải là lỗi
        cấu hình, mà thiếu `app_token`/`table_id` của chính tenant mới là lỗi cấu hình.
        """
        missing = []
        if not self.app_token:
            missing.append("app_token (bitable_app_token của tenant trong MongoDB)")
        if not self.table_id:
            missing.append("table_id (chat_scope_table_id / company_policy_table_id của tenant)")

        # Nêu yêu cầu tenant ngay lúc validate để lỗi rõ ràng, không đợi tới bước lấy token.
        from database.db import get_current_tenant_key

        try:
            self._effective_tenant(tenant_key)
        except TenantContextMissing:
            if not missing:
                raise

        if missing:
            err_msg = (
                f"Thiếu thông số bắt buộc để thao tác Lark Base của tenant "
                f"'{self.tenant_key or get_current_tenant_key()}': {', '.join(missing)}.\n"
                f"-> Tạo service qua `LarkBaseService.for_tenant(resources)` sau khi tenant "
                f"đã ở trạng thái 'ready'; hệ thống không còn đọc các giá trị này từ .env."
            )
            logger.error(err_msg)
            raise TenantConfigIncomplete(self.tenant_key or "?", [m.split(" (")[0] for m in missing])

    def _get_headers(self, use_tenant_token: bool = False, tenant_key: Optional[str] = None) -> Dict[str, str]:
        """Tạo header xác thực bằng User Access Token hoặc Bot Tenant Access Token."""
        self._validate_config(use_tenant_token=use_tenant_token, tenant_key=tenant_key)
        eff_tenant = self._effective_tenant(tenant_key)
        kind = "bot" if use_tenant_token else "user"

        # broker tự nhảy coroutine lên token loop riêng; không còn `asyncio.run(...)`
        # trong ThreadPoolExecutor - con đường từng làm treo request khi có tranh chấp.
        token = token_broker.get_token_sync(eff_tenant, kind)
        if not token:
            raise PermissionError(
                f"Không lấy được {kind}_access_token cho tenant '{eff_tenant}'."
            )

        if not use_tenant_token:
            # Giữ tương thích cho các chỗ đọc `self.user_access_token` (log, kiểm tra hạn).
            self.user_access_token = token

        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "HiLark-Base-Service/1.0",
        }

    def check_token_status(self) -> Dict[str, Any]:
        """Kiểm tra thời hạn và thông tin của User Access Token hiện tại."""
        return inspect_bitable_token(self.user_access_token)

    # -------------------------------------------------------------------------
    # ERROR HANDLING & RESPONSE PARSER (GOM GỌN DÙNG CHUNG)
    # -------------------------------------------------------------------------

    def _handle_api_error(self, response_json: Dict[str, Any], status_code: int) -> None:
        """Phân tích mã lỗi từ Lark API và ném ra Exception có hướng dẫn xử lý chi tiết."""
        code = response_json.get("code")
        msg = response_json.get("msg", "Unknown error")

        logger.error(f"Lark API Error: code={code}, msg={msg}, http_status={status_code}")

        if code in (99991663, 99991668, 99991677, 20005, 99991665):
            token_info = self.check_token_status()
            exp_msg = f" (Hạn token: {token_info.get('expires_at')})" if token_info.get("expires_at") else ""
            raise PermissionError(
                f"[Lark Base Error {code}] User Access Token đã hết hạn hoặc không hợp lệ{exp_msg}.\n"
                f"-> Chi tiết từ Lark: {msg}\n"
                f"-> HƯỚNG XỬ LÝ: Vui lòng đăng nhập lại trên Lark Developer Console hoặc lấy User Access Token mới "
                f"và cập nhật vào biến `access_token_user` trong file .env."
            )

        if code in (1254043, 1254044, 99991672, 1254041):
            raise PermissionError(
                f"[Lark Base Error {code}] Không có quyền truy cập Lark Base ({self.app_token}).\n"
                f"-> Chi tiết từ Lark: {msg}\n"
                f"-> HƯỚNG XỬ LÝ:\n"
                f"   1. Đảm bảo User sở hữu token đã được thêm quyền Xem hoặc Chỉnh sửa trong Bảng Base này.\n"
                f"   2. Đảm bảo Ứng dụng Lark đã được cấp quyền Scope `bitable:app` hoặc `bitable:app:readonly`."
            )

        if code == 1254003:
            raise ValueError(
                f"[Lark Base Error {code}] Không tìm thấy Lark Base (app_token='{self.app_token}').\n"
                f"-> Chi tiết: {msg}\n"
                f"-> HƯỚNG XỬ LÝ: Vui lòng kiểm tra lại mã app_token trong đường link Base (dạng https://.../base/<app_token>)."
            )

        if code == 1254004:
            raise ValueError(
                f"[Lark Base Error {code}] Không tìm thấy Bảng (table_id='{self.table_id}').\n"
                f"-> Chi tiết: {msg}\n"
                f"-> HƯỚNG XỬ LÝ: Vui lòng kiểm tra lại mã table_id (bắt đầu bằng tbl...)."
            )

        raise RuntimeError(f"[Lark Base Error {code}] Yêu cầu API thất bại: {msg} (HTTP {status_code})")

    def _parse_api_response(self, resp: httpx.Response, action_name: str = "Thao tác") -> Dict[str, Any]:
        """Bóc tách JSON và kiểm tra mã lỗi code != 0 thống nhất cho toàn bộ service."""
        try:
            data = resp.json()
        except Exception:
            snippet = resp.text[:300].strip()
            raise RuntimeError(f"{action_name} trả về HTTP {resp.status_code} (không phải JSON): {snippet}")

        if data.get("code") != 0:
            self._handle_api_error(data, resp.status_code)

        return data.get("data", {})

    def _record_from_data(self, record_data: Dict[str, Any], fallback_id: str = "") -> LarkBaseRecord:
        """Chuyển đổi raw record dict từ API sang LarkBaseRecord có clean_fields."""
        rec_id = record_data.get("record_id") or record_data.get("id", "") or fallback_id
        raw_f = record_data.get("fields", {})
        clean_f = clean_record_fields(raw_f)
        return LarkBaseRecord(record_id=rec_id, fields=raw_f, clean_fields=clean_f)

    def _build_record_params(
        self,
        page_size: int = 100,
        page_token: Optional[str] = None,
        filter: Optional[str] = None,
        sort: Optional[str] = None,
        field_names: Optional[List[str]] = None,
        view_id: Optional[str] = None,
        user_id_type: str = "open_id",
        text_field_as_array: bool = False,
    ) -> Dict[str, Any]:
        """Tạo query params chuẩn hóa cho endpoint lấy danh sách record."""
        params: Dict[str, Any] = {
            "page_size": min(page_size, 500),
            "user_id_type": user_id_type,
            "text_field_as_array": str(text_field_as_array).lower(),
        }
        if page_token:
            params["page_token"] = page_token
        if filter:
            params["filter"] = filter
        if sort:
            params["sort"] = sort
        if view_id:
            params["view_id"] = view_id
        if field_names:
            params["field_names"] = json.dumps(field_names, ensure_ascii=False)
        return params

    # -------------------------------------------------------------------------
    # CORE HTTP RUNNERS (DUAL TRANSPORT: SYNC & ASYNC)
    # -------------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        use_tenant_token: bool = False,
        action_name: str = "Thao tác",
    ) -> Dict[str, Any]:
        """Thực thi HTTP request Đồng bộ (Sync) qua httpx.Client."""
        headers = self._get_headers(use_tenant_token=use_tenant_token)
        resp = self.sync_client.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_data,
        )
        return self._parse_api_response(resp, action_name=action_name)

    # =========================================================================
    # 1. SYNCHRONOUS CRUD METHODS (DÙNG CHO BOT DISPATCHER & CLI)
    # =========================================================================

    def get_records(
        self,
        page_size: int = 100,
        page_token: Optional[str] = None,
        filter: Optional[str] = None,
        sort: Optional[str] = None,
        field_names: Optional[List[str]] = None,
        view_id: Optional[str] = None,
        user_id_type: str = "open_id",
        text_field_as_array: bool = False,
        use_tenant_token: bool = False,
    ) -> Dict[str, Any]:
        """Lấy một trang bản ghi từ bảng Lark Base (Sync)."""
        params = self._build_record_params(
            page_size=page_size,
            page_token=page_token,
            filter=filter,
            sort=sort,
            field_names=field_names,
            view_id=view_id,
            user_id_type=user_id_type,
            text_field_as_array=text_field_as_array,
        )
        return self._request("GET", self._records_url, params=params, use_tenant_token=use_tenant_token, action_name="Đọc records")

    def get_all_records(
        self,
        max_records: Optional[int] = None,
        filter: Optional[str] = None,
        sort: Optional[str] = None,
        field_names: Optional[List[str]] = None,
        view_id: Optional[str] = None,
        page_size: int = 100,
        use_tenant_token: bool = False,
    ) -> List[LarkBaseRecord]:
        """Tự động duyệt phân trang để lấy toàn bộ bản ghi trong bảng (Sync)."""
        all_records: List[LarkBaseRecord] = []
        page_token: Optional[str] = None

        while True:
            fetch_size = page_size
            if max_records is not None:
                remaining = max_records - len(all_records)
                if remaining <= 0:
                    break
                fetch_size = min(page_size, remaining)

            data = self.get_records(
                page_size=fetch_size,
                page_token=page_token,
                filter=filter,
                sort=sort,
                field_names=field_names,
                view_id=view_id,
                use_tenant_token=use_tenant_token,
            )

            items = data.get("items", []) or []
            for item in items:
                all_records.append(self._record_from_data(item))
                if max_records is not None and len(all_records) >= max_records:
                    break

            if not data.get("has_more") or not data.get("page_token"):
                break
            page_token = data.get("page_token")

        return all_records

    def get_fields(self, view_id: Optional[str] = None, use_tenant_token: bool = False) -> List[LarkBaseField]:
        """Đọc danh sách và thông tin schema của các cột (Fields) trong bảng (Sync)."""
        params = {"view_id": view_id} if view_id else None
        data = self._request("GET", self._fields_url, params=params, use_tenant_token=use_tenant_token, action_name="Đọc fields")
        items = data.get("items", []) or []
        return [LarkBaseField.from_api_dict(item) for item in items]

    def get_tables(self) -> List[Dict[str, Any]]:
        """Lấy danh sách tất cả các bảng (tables) trong Base (Sync)."""
        data = self._request("GET", self._tables_url, action_name="Đọc danh sách bảng")
        return data.get("items", []) or []

    def read_all(
        self,
        max_records: Optional[int] = None,
        filter: Optional[str] = None,
        fetch_fields: bool = True,
        use_tenant_token: bool = False,
    ) -> LarkBaseQueryResult:
        """Đọc toàn diện bảng Base: lấy toàn bộ records kèm cấu trúc schema cột (Sync)."""
        fields: List[LarkBaseField] = []
        if fetch_fields:
            try:
                fields = self.get_fields(use_tenant_token=use_tenant_token)
            except Exception as e:
                logger.warning(f"Không thể đọc danh sách field schema: {e}")

        records = self.get_all_records(
            max_records=max_records,
            filter=filter,
            use_tenant_token=use_tenant_token,
        )

        return LarkBaseQueryResult(
            app_token=self.app_token,
            table_id=self.table_id,
            total_records=len(records),
            records=records,
            fields=fields,
        )

    def _get_table_field_names(self, use_tenant_token: bool = True) -> List[str]:
        """Lấy danh sách tên các cột thực tế của bảng hiện tại (có cache độc lập theo app_token & table_id)."""
        now = time.time()
        cache_key = f"{self.app_token}:{self.table_id}"
        if not hasattr(self, "_table_fields_cache") or self._table_fields_cache is None:
            self._table_fields_cache = {}

        cached_entry = self._table_fields_cache.get(cache_key)
        if cached_entry:
            cached_time, cached_names = cached_entry
            if now - cached_time < 300 and cached_names:
                return cached_names

        try:
            fields = self.get_fields(use_tenant_token=use_tenant_token)
            names = [f.field_name for f in fields if f.field_name]
            if names:
                self._table_fields_cache[cache_key] = (now, names)
            return names
        except Exception as e:
            logger.debug(f"Không thể đọc schema trường của bảng ({cache_key}): {e}")
            return []

    def _adapt_fields(self, fields: Dict[str, Any], use_tenant_token: bool = True) -> Dict[str, Any]:
        """
        Tự động chuẩn hóa và ánh xạ tên cột để tương thích 100% với cấu trúc schema thực tế của bảng:
          - 'ID Group' <-> 'Chat ID'
          - 'Dự án / Nhóm' <-> 'Tên dự án'
          - 'Trạng thái' <-> 'Trạng thái hoạt động'
          - 'Mức độ bảo mật' <-> 'Cấp độ bảo mật'
          - 'Documents' / 'Link tài liệu' <-> 'Danh mục tài liệu'
        """
        table_cols = self._get_table_field_names(use_tenant_token=use_tenant_token)
        adapted: Dict[str, Any] = {}

        if table_cols:
            all_known_aliases = {a for aliases in FIELD_ALIASES.values() for a in aliases}
            for group_name, aliases in FIELD_ALIASES.items():
                val = None
                for a in aliases:
                    if a in fields and fields[a] is not None:
                        val = fields[a]
                        break
                if val is not None:
                    for col in aliases:
                        if col in table_cols:
                            adapted[col] = val
                            break

            for k, v in fields.items():
                if k not in all_known_aliases and k in table_cols:
                    adapted[k] = v

            return adapted

        # Fallback nếu không lấy được schema: Khử trùng lặp alias
        all_known_aliases = {a for aliases in FIELD_ALIASES.values() for a in aliases}
        for group_name, aliases in FIELD_ALIASES.items():
            for a in aliases:
                if a in fields and fields[a] is not None:
                    adapted[aliases[0]] = fields[a]
                    break

        for k, v in fields.items():
            if k not in all_known_aliases:
                adapted[k] = v

        return adapted or fields

    def find_record_by_chat_id(self, chat_id: str, use_tenant_token: bool = True) -> Optional[LarkBaseRecord]:
        """Tìm kiếm bản ghi đầu tiên có Chat ID hoặc ID Group trùng khớp với chat_id (Sync)."""
        if not chat_id:
            return None
        clean_chat_id = str(chat_id).strip()

        table_cols = self._get_table_field_names(use_tenant_token=use_tenant_token)
        chat_col = "Chat ID" if "Chat ID" in table_cols else ("ID Group" if "ID Group" in table_cols else DEFAULT_COL_CHAT_ID)

        try:
            records = self.get_all_records(
                filter=f'CurrentValue.[{chat_col}] = "{clean_chat_id}"',
                use_tenant_token=use_tenant_token,
            )
            if records:
                return records[0]
        except Exception as e:
            logger.debug(f"Filter trực tiếp theo cột '{chat_col}' thất bại, chuyển sang quét toàn bộ: {e}")

        # Quét dự phòng toàn bảng nếu filter Lark Base không hỗ trợ
        try:
            all_records = self.get_all_records(use_tenant_token=use_tenant_token)
            for r in all_records:
                for possible_key in ["Chat ID", "ID Group", DEFAULT_COL_CHAT_ID]:
                    raw_val = r.clean_fields.get(possible_key) or r.fields.get(possible_key)
                    if str(raw_val or "").strip() == clean_chat_id:
                        return r
        except Exception as e:
            logger.error(f"Lỗi khi tìm bản ghi theo chat_id '{clean_chat_id}': {e}")

        return None

    def create_record(
        self,
        fields: Dict[str, Any],
        user_id_type: str = "open_id",
        use_tenant_token: bool = True,
    ) -> LarkBaseRecord:
        """Tạo mới một bản ghi trong bảng Lark Base (Sync)."""
        adapted_fields = self._adapt_fields(fields, use_tenant_token=use_tenant_token)
        data = self._request(
            method="POST",
            url=self._records_url,
            params={"user_id_type": user_id_type},
            json_data={"fields": adapted_fields},
            use_tenant_token=use_tenant_token,
            action_name="Tạo record",
        )
        return self._record_from_data(data.get("record", {}))

    def update_record(
        self,
        record_id: str,
        fields: Dict[str, Any],
        user_id_type: str = "open_id",
        use_tenant_token: bool = True,
    ) -> LarkBaseRecord:
        """Cập nhật một bản ghi trong bảng Lark Base (Sync)."""
        if not record_id:
            raise ValueError("record_id không được để trống khi cập nhật.")

        adapted_fields = self._adapt_fields(fields, use_tenant_token=use_tenant_token)
        url = f"{self._records_url}/{record_id}"
        data = self._request(
            method="PUT",
            url=url,
            params={"user_id_type": user_id_type},
            json_data={"fields": adapted_fields},
            use_tenant_token=use_tenant_token,
            action_name="Cập nhật record",
        )
        return self._record_from_data(data.get("record", {}), fallback_id=record_id)

    def download_attachment(self, file_token: str, use_tenant_token: bool = True) -> bytes:
        """
        Tải file đính kèm từ cột Attachment của Lark Base qua Drive Media Download API (Sync).
        Trả về nội dung nhị phân (bytes) của file để sẵn sàng upload sang WeKnora.
        """
        if not file_token:
            raise ValueError("file_token không được để trống khi tải tệp đính kèm.")

        url = f"{self.domain}/open-apis/drive/v1/medias/{file_token}/download"
        headers = self._get_headers(use_tenant_token=use_tenant_token)

        try:
            resp = self.sync_client.get(url, headers=headers, timeout=60.0)
            if resp.status_code == 200:
                return resp.content
            else:
                logger.error(f"Lỗi tải attachment từ Lark (HTTP {resp.status_code}): {resp.text}")
                raise ValueError(f"Không thể tải file attachment {file_token} (HTTP {resp.status_code})")
        except Exception as e:
            logger.error(f"Lỗi khi tải attachment {file_token}: {e}")
            raise


    def get_bot_chats(self) -> List[Dict[str, Any]]:
        """Lấy danh sách tất cả các nhóm chat mà Bot đang tham gia trên Lark (Sync)."""
        headers = self._get_headers(use_tenant_token=True)
        url = f"{self.domain}/open-apis/im/v1/chats"
        params: Dict[str, Any] = {"page_size": 100}
        all_chats: List[Dict[str, Any]] = []
        page_token = None

        while True:
            if page_token:
                params["page_token"] = page_token
            resp = self.sync_client.get(url, headers=headers, params=params)
            try:
                data = resp.json()
            except Exception:
                break
            if data.get("code") != 0:
                logger.error(f"Lỗi khi lấy danh sách chat của Bot: {data}")
                break
            d = data.get("data", {})
            all_chats.extend(d.get("items", []) or [])
            if not d.get("has_more") or not d.get("page_token"):
                break
            page_token = d.get("page_token")

        return all_chats

    def sync_bot_chats(self) -> Dict[str, Any]:
        """
        Quét và tự động đồng bộ tất cả nhóm chat của Bot vào Lark Base.
        Nhóm nào chưa có trong Base sẽ được tự động điền (ưu tiên tận dụng dòng trống có sẵn).
        """
        chats = self.get_bot_chats()
        existing_records = self.get_all_records(use_tenant_token=True)

        existing_chat_ids = set()
        empty_records = []
        for r in existing_records:
            cid = r.clean_fields.get(DEFAULT_COL_CHAT_ID) or r.fields.get(DEFAULT_COL_CHAT_ID)
            if cid:
                existing_chat_ids.add(str(cid).strip())
            else:
                empty_records.append(r)

        added = []
        updated = []

        for c in chats:
            chat_id = c.get("chat_id")
            chat_name = c.get("name") or "Nhóm chat"
            if not chat_id or chat_id in existing_chat_ids:
                continue

            if empty_records:
                target_rec = empty_records.pop(0)
                self.update_record(target_rec.record_id, {
                    DEFAULT_COL_PROJECT_NAME: chat_name,
                    DEFAULT_COL_CHAT_ID: chat_id,
                })
                updated.append({"chat_id": chat_id, "name": chat_name, "record_id": target_rec.record_id})
                existing_chat_ids.add(chat_id)
            else:
                new_rec = self.create_record({
                    DEFAULT_COL_PROJECT_NAME: chat_name,
                    DEFAULT_COL_CHAT_ID: chat_id,
                })
                added.append({"chat_id": chat_id, "name": chat_name, "record_id": new_rec.record_id})
                existing_chat_ids.add(chat_id)

        synced_count = len(added) + len(updated)
        if synced_count > 0:
            logger.info(f"🔄 Đã tự động đồng bộ {synced_count} nhóm chat vào Base (Cập nhật dòng trống: {len(updated)}, Thêm mới: {len(added)})")
        return {"total_chats": len(chats), "added": added, "updated": updated}

    def subscribe_events(self, app_token: Optional[str] = None, tenant_key: Optional[str] = None) -> bool:
        """Đăng ký nhận sự kiện thay đổi của bảng Base (Bitable) qua Drive Subscribe API (hỗ trợ tenant_key)."""
        try:
            target_token = app_token or self.app_token
            if not target_token:
                logger.warning("Không có app_token để subscribe sự kiện Base.")
                return False

            from database.db import get_current_tenant_key
            eff_tenant = tenant_key or get_current_tenant_key()
            t_token = self.get_tenant_access_token(tenant_key=eff_tenant)
            if not t_token:
                logger.warning(f"Không lấy được tenant_access_token để subscribe sự kiện Base (tenant: {eff_tenant}).")
                return False

            url = f"{self.domain}/open-apis/drive/v1/files/{target_token}/subscribe?file_type=bitable"
            headers = {
                "Authorization": f"Bearer {t_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            resp = self.sync_client.post(url, headers=headers, json={})
            if resp.status_code == 200 and resp.json().get("code") == 0:
                logger.info(f"✅ Đã đăng ký (subscribe) thành công sự kiện cho Base: {target_token} (tenant: {eff_tenant})")
                return True
            else:
                logger.warning(f"⚠️ Subscribe Base {target_token} trả về mã HTTP {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            logger.warning(f"Không thể gọi API subscribe Base {target_token}: {e}")
            return False


    # =========================================================================
    # 2. ASYNCHRONOUS WRAPPER METHODS (DÙNG CHO FASTAPI ROUTES & LIFECYCLE)
    # =========================================================================

    async def aget_records(self, *args, **kwargs) -> Dict[str, Any]:
        """Lấy một trang bản ghi từ bảng Lark Base (Async qua to_thread)."""
        return await asyncio.to_thread(self.get_records, *args, **kwargs)

    async def aget_all_records(self, *args, **kwargs) -> List[LarkBaseRecord]:
        """Tự động duyệt phân trang lấy toàn bộ bản ghi (Async qua to_thread)."""
        return await asyncio.to_thread(self.get_all_records, *args, **kwargs)

    async def aget_fields(self, *args, **kwargs) -> List[LarkBaseField]:
        """Đọc danh sách schema các cột trong bảng (Async qua to_thread)."""
        return await asyncio.to_thread(self.get_fields, *args, **kwargs)

    async def aread_all(self, *args, **kwargs) -> LarkBaseQueryResult:
        """Đọc toàn diện bảng Base: lấy toàn bộ records kèm schema (Async qua to_thread)."""
        return await asyncio.to_thread(self.read_all, *args, **kwargs)

    async def afind_record_by_chat_id(self, *args, **kwargs) -> Optional[LarkBaseRecord]:
        """Tìm kiếm bản ghi theo chat_id (Async qua to_thread)."""
        return await asyncio.to_thread(self.find_record_by_chat_id, *args, **kwargs)

    async def adownload_attachment(self, *args, **kwargs) -> bytes:
        """Tải file đính kèm từ cột Attachment của Lark Base (Async qua to_thread)."""
        return await asyncio.to_thread(self.download_attachment, *args, **kwargs)

   



# =============================================================================
# TOP-LEVEL CONVENIENCE FUNCTIONS
# =============================================================================

# Singleton tương thích import. Nó **không** mang cấu hình của tenant nào:
# `app_token`/`table_id` rỗng và `tenant_key=None`, nên mọi thao tác gọi lên nó đều
# raise TenantContextMissing/TenantConfigIncomplete thay vì âm thầm dùng dữ liệu cũ.
# Code nghiệp vụ phải tạo service riêng qua `LarkBaseService.for_tenant(resources)`.
lark_base_service = LarkBaseService(tenant_key=None)


def base_service_for_current_tenant(
    app_token: Optional[str] = None,
    table_id: Optional[str] = None,
    policy_table: bool = False,
) -> LarkBaseService:
    """Tạo LarkBaseService theo tenant của ngữ cảnh request hiện tại (đọc từ ContextVar)."""
    from database.db import get_current_tenant_key
    from services.tenancy.tenant_resolver import tenant_resolver

    resources = tenant_resolver.resolve_sync(get_current_tenant_key())
    if policy_table:
        return LarkBaseService.for_policy_table(resources)
    return LarkBaseService.for_tenant(resources, app_token=app_token, table_id=table_id)


def find_lark_base_record_by_chat_id(chat_id: str) -> Optional[LarkBaseRecord]:
    """Hàm tiện ích tra cứu nhanh bản ghi theo chat_id."""
    return base_service_for_current_tenant().find_record_by_chat_id(chat_id)




def read_lark_base_records(
    tenant_key: Optional[str] = None,
    app_token: Optional[str] = None,
    table_id: Optional[str] = None,
    user_access_token: Optional[str] = None,
    clean: bool = True,
    max_records: Optional[int] = None,
    filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Hàm tiện ích nhanh nhất để đọc toàn bộ dữ liệu trong bảng Lark Base thành list of dicts (Sync)."""
    from database.db import get_current_tenant_key
    from services.tenancy.tenant_resolver import tenant_resolver

    eff_tenant = tenant_key or get_current_tenant_key()
    resources = tenant_resolver.resolve_sync(eff_tenant)
    svc = LarkBaseService.for_tenant(
        resources,
        app_token=app_token,
        table_id=table_id,
    )
    if user_access_token:
        svc.user_access_token = user_access_token
    records = svc.get_all_records(max_records=max_records, filter=filter)
    return [r.to_dict(clean=clean) for r in records]


async def aread_lark_base_records(*args, **kwargs) -> List[Dict[str, Any]]:
    """Hàm bất đồng bộ tương ứng của read_lark_base_records (bọc qua asyncio.to_thread)."""
    return await asyncio.to_thread(read_lark_base_records, *args, **kwargs)


# =============================================================================
# STANDALONE BITABLE REAL-TIME LISTENER (WEBSOCKET)
# =============================================================================

def start_bitable_ws_listener(service: LarkBaseService) -> None:
    """
    Khởi động tiến trình Đồng bộ và Lắng nghe sự kiện Lark Base (Bitable) Real-time:
      - Tự động đồng bộ toàn bộ nhóm chat của Bot vào bảng Lark Base.
      - Lắng nghe sự kiện thay đổi dữ liệu bảng (Bitable) và sự kiện Bot tham gia nhóm theo thời gian thực.
    """

    # Listener này là công cụ dev chạy cho MỘT tenant. Trước đây nó lấy "App bất kỳ
    # mới nhất trong DB" rồi fallback `.env`, nên có thể gắn nhầm App của tenant khác.
    if not service.tenant_key:
        raise TenantContextMissing(
            "start_bitable_ws_listener() yêu cầu LarkBaseService được tạo kèm tenant_key."
        )
    app_id, app_secret = _app_credentials_sync(service.tenant_key)

    from database.db import get_sync_db
    from services.user_settings_service import user_settings_service

    db = get_sync_db()
    collection = getattr(settings, "MONGO_LARK_APPS_COLLECTION", "lark_app_credentials")
    app_record = db[collection].find_one(
        {"tenant_key": service.tenant_key, "status": {"$ne": "revoked"}}
    ) or {}
    encrypt_key = user_settings_service.decrypt_key(app_record.get("encrypted_encrypt_key", ""))
    verification_token = user_settings_service.decrypt_key(
        app_record.get("encrypted_verification_token", "")
    )
    if not encrypt_key or not verification_token:
        raise AppCredentialMissing(service.tenant_key)

    print("\n" + "=" * 70)
    print("⚡ HILARK - ĐỒNG BỘ VÀ LẮNG NGHE SỰ KIỆN LARK BASE REAL-TIME")
    print("=" * 70)
    print(f"App ID     : {app_id}")
    print(f"Domain     : {service.domain}")
    print(f"Base Token : {service.app_token}")
    print(f"Table ID   : {service.table_id}")

    # 1. ĐỒNG BỘ NHÓM CHAT BOT VÀO LARK BASE
    print("\n🔄 Đang quét và đồng bộ nhóm chat của Bot vào Base...")
    try:
        res = service.sync_bot_chats()
        total_chats = res.get("total_chats", 0)
        added = res.get("added", [])
        updated = res.get("updated", [])
        print(f"✔ Tổng số nhóm chat tìm thấy : {total_chats}")
        print(f"✔ Đã thêm mới vào Base       : {len(added)}")
        print(f"✔ Đã cập nhật vào dòng trống : {len(updated)}")
        for item in added + updated:
            print(f"   • {item.get('name')}: {item.get('chat_id')} -> Record: {item.get('record_id')}")
    except Exception as e:
        logger.warning(f"⚠️  Không thể đồng bộ nhóm chat vào Base: {e}")

    # Bước 2: Đọc trước schema các trường để hiển thị tên cột thay vì field_id khó hiểu
    field_name_map: Dict[str, str] = {}
    try:
        fields = service.get_fields(use_tenant_token=True)
        for f in fields:
            field_name_map[f.field_id] = f.field_name
    except Exception as e:
        logger.warning(f"Không thể tải schema cột để map tên: {e}")

    def on_record_changed(data: P2DriveFileBitableRecordChangedV1) -> None:
        try:
            event = getattr(data, "event", None)
            if not event:
                return
            file_token = getattr(event, "file_token", "")
            table_id = getattr(event, "table_id", "")
            action_list = getattr(event, "action_list", []) or []
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            print("\n" + "=" * 65)
            print("📊 [LARK BASE] PHÁT HIỆN DỮ LIỆU THAY ĐỔI:")
            print("-" * 65)
            print(f"🕒 Thời gian    : {now_str}")
            print(f"📦 Base Token   : {file_token}")
            print(f"📊 Table ID     : {table_id}")
            print(f"📝 Số hành động : {len(action_list)}")

            for idx, act in enumerate(action_list, 1):
                rec_id = getattr(act, "record_id", "")
                action_type = getattr(act, "action", "")
                print(f"  [{idx}] Record ID: {rec_id} | Hành động: {action_type}")

                before_list = getattr(act, "before_value", []) or []
                after_list = getattr(act, "after_value", []) or []
                if before_list or after_list:
                    b_map = {getattr(b, "field_id", ""): getattr(b, "field_value", "") for b in before_list}
                    a_map = {getattr(a, "field_id", ""): getattr(a, "field_value", "") for a in after_list}
                    all_fids = set(b_map.keys()) | set(a_map.keys())
                    for fid in all_fids:
                        col_label = field_name_map.get(fid, fid)
                        old_v = b_map.get(fid, "(trống)")
                        new_v = a_map.get(fid, "(trống)")
                        print(f"      • {col_label} ({fid}): {old_v} -> {new_v}")
            print("=" * 65 + "\n")
        except Exception as e:
            logger.error(f"Lỗi khi xử lý sự kiện bitable_record_changed: {e}")

    def on_field_changed(data: P2DriveFileBitableFieldChangedV1) -> None:
        try:
            event = getattr(data, "event", None)
            table_id = getattr(event, "table_id", "") if event else ""
            print(f"\n📐 [LARK BASE] Cấu trúc cột của bảng '{table_id}' vừa thay đổi.")
        except Exception as e:
            logger.error(f"Lỗi khi xử lý sự kiện bitable_field_changed: {e}")

    def on_bot_added(data: P2ImChatMemberBotAddedV1) -> None:
        try:
            event = getattr(data, "event", None)
            chat_id = getattr(event, "chat_id", "") if event else ""
            chat_name = getattr(event, "name", "") if event else "Nhóm chat"
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            print("\n" + "=" * 65)
            print("🎉 [LARK BOT] PHÁT HIỆN BOT VỪA ĐƯỢC THÊM VÀO NHÓM CHAT MỚI!")
            print("-" * 65)
            print(f"🕒 Thời gian : {now_str}")
            print(f"💬 Tên nhóm  : {chat_name}")
            print(f"🆔 Chat ID   : {chat_id}")
            print("🔄 Đang tự động đồng bộ nhóm mới vào Lark Base...")

            res = service.sync_bot_chats()
            items = res.get("added", []) + res.get("updated", [])
            if items:
                for item in items:
                    print(f"✔ Đã cập nhật vào Base: {item.get('name')} -> Record: {item.get('record_id')}")
            else:
                print(f"ℹ️ Nhóm đã tồn tại trong Lark Base.")
            print("=" * 65 + "\n")
        except Exception as e:
            logger.error(f"Lỗi khi xử lý sự kiện bot_added: {e}")

    def on_bot_deleted(data: P2ImChatMemberBotDeletedV1) -> None:
        try:
            event = getattr(data, "event", None)
            chat_id = getattr(event, "chat_id", "") if event else ""
            chat_name = getattr(event, "name", "") if event else "Nhóm chat"
            print(f"\nℹ️ [LARK BOT] Bot vừa bị gỡ khỏi nhóm: '{chat_name}' ({chat_id})\n")
        except Exception as e:
            logger.error(f"Lỗi khi xử lý sự kiện bot_deleted: {e}")

    def on_file_edit(data: P2DriveFileEditV1) -> None:
        # Sự kiện cấp Drive đi kèm khi sửa bảng Base, bỏ qua vì đã xử lý chi tiết ở on_record_changed
        pass

    # Build EventDispatcher cho Base và Sự kiện thành viên Bot (Không can thiệp vào IM text chat)
    dispatcher = (
        lark.EventDispatcherHandler.builder(encrypt_key, verification_token)
        .register_p2_drive_file_bitable_record_changed_v1(on_record_changed)
        .register_p2_drive_file_bitable_field_changed_v1(on_field_changed)
        .register_p2_drive_file_edit_v1(on_file_edit)
        .register_p2_im_chat_member_bot_added_v1(on_bot_added)
        .register_p2_im_chat_member_bot_deleted_v1(on_bot_deleted)
        .build()
    )

    ws_client = lark.ws.Client(
        app_id=app_id,
        app_secret=app_secret,
        event_handler=dispatcher,
        domain=service.domain,
        log_level=lark.LogLevel.INFO,
    )

    # Đăng ký subscribe sự kiện trên Lark Cloud
    sub_ok = service.subscribe_events()
    if sub_ok:
        print("✅ Đã kích hoạt theo dõi bảng Bitable thành công trên Lark Cloud!")
    else:
        print("ℹ️ Đang kết nối trực tiếp với Lark WebSocket...")

    print("👉 Hãy thử mở Lark Base trên trình duyệt, thêm dòng hoặc sửa 1 ô bất kỳ...")
    print("-" * 70)

    try:
        ws_client.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Đã dừng lắng nghe sự kiện Lark Base an toàn.")
        os._exit(0)
    except Exception as e:
        logger.error(f"Lỗi khi chạy WebSocket client: {e}")
        os._exit(1)


# =============================================================================
# CLI / STANDALONE EXECUTABLE RUNNER
# =============================================================================

def main():
    """Hàm thực thi độc lập khi chạy script bằng python server/services/larkbase.py."""
    parser = argparse.ArgumentParser(
        description="HiLark - Script đọc dữ liệu hiện có trong Lark Base (Bitable) bằng User Access Token"
    )
    parser.add_argument(
        "--tenant-key",
        type=str,
        default=None,
        help="Tenant cần đọc (mặc định lấy theo biến môi trường HILARK_TENANT_KEY / ngữ cảnh đang chạy)",
    )
    parser.add_argument(
        "--app-token",
        type=str,
        default=None,
        help="Lark Base App Token (mặc định lấy từ LARK_BASE_APP_TOKEN trong .env)",
    )
    parser.add_argument(
        "--table-id",
        type=str,
        default=None,
        help="Table ID cần đọc (mặc định lấy từ LARK_BASE_TABLE_ID trong .env)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="User Access Token (mặc định lấy từ access_token_user trong .env)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Giới hạn số bản ghi đọc về (mặc định lấy tất cả)",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="In ra kết quả dưới dạng bảng Markdown",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="In ra toàn bộ dữ liệu dưới dạng JSON thô",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Giữ nguyên trường thô không chuẩn hóa (clean)",
    )
    parser.add_argument(
        "--listen",
        action="store_true",
        help="Đồng bộ toàn bộ nhóm chat bot vào Lark Base và lắng nghe sự kiện thay đổi dữ liệu thời gian thực (WebSocket)",
    )

    args = parser.parse_args()

    # CLI cũng phải đi qua resolver: một lần chạy chỉ phục vụ MỘT tenant, không vay `.env`.
    from database.db import get_current_tenant_key
    from services.tenancy.tenant_resolver import tenant_resolver

    eff_tenant = args.tenant_key or get_current_tenant_key()
    resources = tenant_resolver.resolve_sync(eff_tenant)

    if args.listen:
        service = LarkBaseService.for_tenant(resources, app_token=args.app_token, table_id=args.table_id)
        start_bitable_ws_listener(service)
        return

    service = LarkBaseService.for_tenant(
        resources,
        app_token=args.app_token,
        table_id=args.table_id,
    )
    if args.token:
        service.user_access_token = args.token

    print("\n" + "=" * 70)
    print("🚀 HILARK - TRÌNH ĐỌC DỮ LIỆU LARK BASE (BITABLE)")
    print("=" * 70)
    print(f"📍 Domain endpoint : {service.domain}")
    print(f"📦 Lark Base App   : {service.app_token or '[CHƯA CẤU HÌNH]'}")
    print(f"📊 Table ID        : {service.table_id or '[CHƯA CẤU HÌNH]'}")

    token_preview = (
        service.user_access_token[:10] + "..." + service.user_access_token[-8:]
        if len(service.user_access_token) > 20
        else (service.user_access_token or "[CHƯA CẤU HÌNH]")
    )
    print(f"🔑 User Token      : {token_preview}")

    token_status = service.check_token_status()
    if token_status.get("status") == "expired":
        print(f"⚠️  CẢNH BÁO TOKEN : ĐÃ HẾT HẠN vào lúc {token_status.get('expires_at')}")
        print(f"    (Có thể gặp lỗi 99991663/20005 khi gọi API. Vui lòng lấy token mới nếu lỗi)")
    elif token_status.get("status") == "valid":
        print(f"✅ Trạng thái Token : Hợp lệ (Hết hạn lúc {token_status.get('expires_at')})")
    print("-" * 70)

    try:
        print("🔍 Đang đọc cấu trúc các cột (Fields Schema)...")
        fields = []
        try:
            fields = service.get_fields()
            print(f"   Tìm thấy {len(fields)} cột trong bảng:")
            for f in fields:
                primary_tag = " [PRIMARY KEY]" if f.is_primary else ""
                print(f"    - {f.field_name} (ID: {f.field_id}) : {f.type_name}{primary_tag}")
        except Exception as e:
            print(f"   ⚠️ Không thể đọc schema cột: {e}")

        print("-" * 70)

        print(f"📥 Đang tải các bản ghi từ bảng {service.table_id}...")
        records = service.get_all_records(max_records=args.limit)

        print("-" * 70)
        print(f"🎉 TỔNG KẾT: Đã đọc thành công {len(records)} bản ghi!")
        print("=" * 70 + "\n")

        if not records:
            print("ℹ️ Bảng hiện chưa có bản ghi nào.")
            return

        if args.json:
            result_dicts = [r.to_dict(clean=not args.raw) for r in records]
            print(json.dumps(result_dicts, ensure_ascii=False, indent=2))
        elif args.markdown:
            query_res = LarkBaseQueryResult(
                app_token=service.app_token,
                table_id=service.table_id,
                total_records=len(records),
                records=records,
                fields=fields,
            )
            print(query_res.to_markdown_table(max_rows=args.limit))
        else:
            for idx, r in enumerate(records, 1):
                print(f"[{idx}/{len(records)}] 🆔 Record ID: {r.record_id}")
                display_fields = r.fields if args.raw else r.clean_fields
                for col_name, val in display_fields.items():
                    print(f"   • {col_name}: {val}")
                print()

    except Exception as e:
        print(f"\n❌ ĐÃ XẢY RA LỖI:")
        print(f"{e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
