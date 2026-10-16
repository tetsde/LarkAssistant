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
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

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
from utils.larkbase import (
    clean_field_value,
    clean_record_fields,
    decode_jwt_token_payload,
    inspect_bitable_token,
)

logger = logging.getLogger("hilark.larkbase")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

VIETNAM_TZ = timezone(timedelta(hours=7))

# Tên cột mặc định trong Lark Base
DEFAULT_COL_CHAT_ID = "ID Group"
DEFAULT_COL_PROJECT_NAME = "Dự án / Nhóm"
DEFAULT_COL_KB_ID = "Knowledge Base ID"


# =============================================================================
# LARK BASE SERVICE CLASS
# =============================================================================

class LarkBaseService:
    """
    Service giao tiếp và thao tác dữ liệu với Lark Base (Bitable) API:
      - Quản lý xác thực qua User Access Token hoặc Bot Tenant Access Token.
      - Kiến trúc Dual Transport: Đồng bộ (Sync) cho CLI/Scripts/Lark SDK và 
        Native Async (Bất đồng bộ) non-blocking cho FastAPI endpoints & lifecycle.
      - Tái sử dụng HTTP connection pool, tự động bóc tách và chuẩn hóa dữ liệu.
    """

    def __init__(
        self,
        app_token: Optional[str] = None,
        table_id: Optional[str] = None,
        user_access_token: Optional[str] = None,
        domain: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """Khởi tạo LarkBaseService với cấu hình từ tham số hoặc file .env."""
        self.app_token = (
            app_token
            or getattr(settings, "LARK_BASE_APP_TOKEN", "")
            or os.getenv("LARK_BASE_APP_TOKEN")
            or os.getenv("app_token")
            or ""
        ).strip().strip("\"'")

        self.table_id = (
            table_id
            or getattr(settings, "LARK_BASE_TABLE_ID", "")
            or os.getenv("LARK_BASE_TABLE_ID")
            or os.getenv("table_id")
            or ""
        ).strip().strip("\"'")

        self.user_access_token = (
            user_access_token
            or getattr(settings, "LARK_USER_ACCESS_TOKEN", "")
            or os.getenv("access_token_user")
            or os.getenv("LARK_USER_ACCESS_TOKEN")
            or ""
        ).strip().strip("\"'")

        raw_domain = (
            domain
            or getattr(settings, "LARK_DOMAIN", "")
            or os.getenv("lark_domain")
            or "https://open.larksuite.com"
        ).strip().rstrip("/")
        self.domain = raw_domain

        self.timeout = timeout
        self._tenant_token: Optional[str] = None
        self._tenant_token_expires_at: float = 0.0

        # Persistent HTTP clients (Connection Pooling)
        self._sync_client: Optional[httpx.Client] = None
        self._async_client: Optional[httpx.AsyncClient] = None

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
    def async_client(self) -> httpx.AsyncClient:
        """Trả về HTTP async client tái sử dụng connection pool cho FastAPI."""
        if self._async_client is None or self._async_client.is_closed:
            self._async_client = httpx.AsyncClient(timeout=self.timeout)
        return self._async_client

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

    def get_tenant_access_token(self, force_refresh: bool = False) -> str:
        """
        Lấy và tự động cache Bot Tenant Access Token từ Lark Cloud.
        Token có hiệu lực 2 giờ, tự động làm mới khi gần hết hạn.
        """
        now = time.time()
        if not force_refresh and self._tenant_token and (now < self._tenant_token_expires_at - 120):
            return self._tenant_token

        app_id = getattr(settings, "LARK_APP_ID", "") or os.getenv("LARK_APP_ID", "")
        app_secret = getattr(settings, "LARK_APP_SECRET", "") or os.getenv("LARK_APP_SECRET", "")
        if not app_id or not app_secret:
            logger.warning("Chưa cấu hình LARK_APP_ID hoặc LARK_APP_SECRET để lấy tenant_access_token.")
            return ""

        url = f"{self.domain}/open-apis/auth/v3/tenant_access_token/internal"
        try:
            resp = self.sync_client.post(
                url,
                json={"app_id": app_id, "app_secret": app_secret},
            )
            data = resp.json()
            if data.get("code") == 0 and data.get("tenant_access_token"):
                self._tenant_token = data.get("tenant_access_token")
                expire_sec = data.get("expire", 7200)
                self._tenant_token_expires_at = now + expire_sec
                return self._tenant_token
            else:
                logger.error(f"Lỗi khi lấy tenant_access_token: {data}")
                return ""
        except Exception as e:
            logger.error(f"Exception khi lấy tenant_access_token: {e}")
            return ""

    def _validate_config(self, use_tenant_token: bool = False) -> None:
        """Kiểm tra xem các thông số bắt buộc đã được cung cấp chưa."""
        missing = []
        if not use_tenant_token and not self.user_access_token:
            missing.append("user_access_token (hoặc access_token_user trong .env)")
        if not self.app_token:
            missing.append("app_token (hoặc LARK_BASE_APP_TOKEN trong .env)")
        if not self.table_id:
            missing.append("table_id (hoặc LARK_BASE_TABLE_ID trong .env)")

        if missing:
            err_msg = (
                f"Thiếu thông số bắt buộc để thao tác Lark Base: {', '.join(missing)}.\n"
                f"Vui lòng kiểm tra lại file .env hoặc truyền trực tiếp vào hàm!"
            )
            logger.error(err_msg)
            raise ValueError(err_msg)

    def _get_headers(self, use_tenant_token: bool = False) -> Dict[str, str]:
        """Tạo header xác thực với User Access Token hoặc Tenant Access Token."""
        self._validate_config(use_tenant_token=use_tenant_token)
        if use_tenant_token:
            token = self.get_tenant_access_token()
            if not token:
                raise PermissionError("Không thể lấy tenant_access_token của Bot để truy cập Lark Base.")
            return {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "HiLark-Base-Service/1.0",
            }

        return {
            "Authorization": f"Bearer {self.user_access_token}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "HiLark-Base-Reader/1.0",
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

    async def _arequest(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        use_tenant_token: bool = False,
        action_name: str = "Thao tác",
    ) -> Dict[str, Any]:
        """Thực thi HTTP request Bất đồng bộ Native (Async) qua httpx.AsyncClient."""
        headers = self._get_headers(use_tenant_token=use_tenant_token)
        resp = await self.async_client.request(
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

    def find_record_by_chat_id(self, chat_id: str, use_tenant_token: bool = True) -> Optional[LarkBaseRecord]:
        """Tìm kiếm bản ghi đầu tiên có ID Group trùng khớp với chat_id (Sync)."""
        if not chat_id:
            return None
        clean_chat_id = str(chat_id).strip()

        try:
            records = self.get_all_records(
                filter=f'CurrentValue.[{DEFAULT_COL_CHAT_ID}] = "{clean_chat_id}"',
                use_tenant_token=use_tenant_token,
            )
            if records:
                return records[0]
        except Exception as e:
            logger.debug(f"Filter trực tiếp theo cột '{DEFAULT_COL_CHAT_ID}' thất bại, chuyển sang quét toàn bộ: {e}")

        # Quét dự phòng toàn bảng nếu filter Lark Base không hỗ trợ
        try:
            all_records = self.get_all_records(use_tenant_token=use_tenant_token)
            for r in all_records:
                raw_val = r.clean_fields.get(DEFAULT_COL_CHAT_ID) or r.fields.get(DEFAULT_COL_CHAT_ID)
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
        data = self._request(
            method="POST",
            url=self._records_url,
            params={"user_id_type": user_id_type},
            json_data={"fields": fields},
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

        url = f"{self._records_url}/{record_id}"
        data = self._request(
            method="PUT",
            url=url,
            params={"user_id_type": user_id_type},
            json_data={"fields": fields},
            use_tenant_token=use_tenant_token,
            action_name="Cập nhật record",
        )
        return self._record_from_data(data.get("record", {}), fallback_id=record_id)

    def delete_record(self, record_id: str, use_tenant_token: bool = True) -> bool:
        """Xóa một bản ghi trong bảng Lark Base theo record_id (Sync)."""
        if not record_id:
            return False

        url = f"{self._records_url}/{record_id}"
        try:
            data = self._request(
                method="DELETE",
                url=url,
                use_tenant_token=use_tenant_token,
                action_name="Xóa record",
            )
            return bool(data.get("deleted", False))
        except Exception as e:
            logger.error(f"Lỗi khi xóa record {record_id}: {e}")
            return False

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

    def subscribe_events(self) -> bool:
        """Đăng ký nhận sự kiện thay đổi của bảng Base (Bitable) qua Drive Subscribe API."""
        try:
            t_token = self.get_tenant_access_token()
            if not t_token:
                logger.warning("Không lấy được tenant_access_token để subscribe sự kiện Base.")
                return False

            url = f"{self.domain}/open-apis/drive/v1/files/{self.app_token}/subscribe?file_type=bitable"
            headers = {
                "Authorization": f"Bearer {t_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            resp = self.sync_client.post(url, headers=headers, json={})
            if resp.status_code == 200 and resp.json().get("code") == 0:
                logger.info(f"✅ Đã đăng ký (subscribe) thành công sự kiện cho Base: {self.app_token}")
                return True
            else:
                logger.warning(f"⚠️ Subscribe Base trả về mã HTTP {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            logger.warning(f"Không thể gọi API subscribe Base: {e}")
            return False

    # =========================================================================
    # 2. NATIVE ASYNCHRONOUS CRUD METHODS (DÙNG CHO FASTAPI ROUTES & LIFECYCLE)
    # =========================================================================

    async def aget_records(
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
        """Lấy một trang bản ghi từ bảng Lark Base (Native Async)."""
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
        return await self._arequest("GET", self._records_url, params=params, use_tenant_token=use_tenant_token, action_name="Đọc records async")

    async def aget_all_records(
        self,
        max_records: Optional[int] = None,
        filter: Optional[str] = None,
        sort: Optional[str] = None,
        field_names: Optional[List[str]] = None,
        view_id: Optional[str] = None,
        page_size: int = 100,
        use_tenant_token: bool = False,
    ) -> List[LarkBaseRecord]:
        """Tự động duyệt phân trang để lấy toàn bộ bản ghi trong bảng (Native Async)."""
        all_records: List[LarkBaseRecord] = []
        page_token: Optional[str] = None

        while True:
            fetch_size = page_size
            if max_records is not None:
                remaining = max_records - len(all_records)
                if remaining <= 0:
                    break
                fetch_size = min(page_size, remaining)

            data = await self.aget_records(
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

    async def aget_fields(self, view_id: Optional[str] = None, use_tenant_token: bool = False) -> List[LarkBaseField]:
        """Đọc danh sách và thông tin schema của các cột (Fields) trong bảng (Native Async)."""
        params = {"view_id": view_id} if view_id else None
        data = await self._arequest("GET", self._fields_url, params=params, use_tenant_token=use_tenant_token, action_name="Đọc fields async")
        items = data.get("items", []) or []
        return [LarkBaseField.from_api_dict(item) for item in items]

    async def aread_all(
        self,
        max_records: Optional[int] = None,
        filter: Optional[str] = None,
        fetch_fields: bool = True,
        use_tenant_token: bool = False,
    ) -> LarkBaseQueryResult:
        """Đọc toàn diện bảng Base: lấy toàn bộ records kèm cấu trúc schema cột (Native Async)."""
        fields: List[LarkBaseField] = []
        if fetch_fields:
            try:
                fields = await self.aget_fields(use_tenant_token=use_tenant_token)
            except Exception as e:
                logger.warning(f"Không thể đọc danh sách field schema async: {e}")

        records = await self.aget_all_records(
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

    async def afind_record_by_chat_id(self, chat_id: str, use_tenant_token: bool = True) -> Optional[LarkBaseRecord]:
        """Tìm kiếm bản ghi đầu tiên có ID Group trùng khớp với chat_id (Native Async)."""
        if not chat_id:
            return None
        clean_chat_id = str(chat_id).strip()

        try:
            records = await self.aget_all_records(
                filter=f'CurrentValue.[{DEFAULT_COL_CHAT_ID}] = "{clean_chat_id}"',
                use_tenant_token=use_tenant_token,
            )
            if records:
                return records[0]
        except Exception as e:
            logger.debug(f"Filter trực tiếp async theo cột '{DEFAULT_COL_CHAT_ID}' thất bại: {e}")

        try:
            all_records = await self.aget_all_records(use_tenant_token=use_tenant_token)
            for r in all_records:
                raw_val = r.clean_fields.get(DEFAULT_COL_CHAT_ID) or r.fields.get(DEFAULT_COL_CHAT_ID)
                if str(raw_val or "").strip() == clean_chat_id:
                    return r
        except Exception as e:
            logger.error(f"Lỗi khi tìm async bản ghi theo chat_id '{clean_chat_id}': {e}")

        return None

    async def acreate_record(
        self,
        fields: Dict[str, Any],
        user_id_type: str = "open_id",
        use_tenant_token: bool = True,
    ) -> LarkBaseRecord:
        """Tạo mới một bản ghi trong bảng Lark Base (Native Async)."""
        data = await self._arequest(
            method="POST",
            url=self._records_url,
            params={"user_id_type": user_id_type},
            json_data={"fields": fields},
            use_tenant_token=use_tenant_token,
            action_name="Tạo record async",
        )
        return self._record_from_data(data.get("record", {}))

    async def aupdate_record(
        self,
        record_id: str,
        fields: Dict[str, Any],
        user_id_type: str = "open_id",
        use_tenant_token: bool = True,
    ) -> LarkBaseRecord:
        """Cập nhật một bản ghi trong bảng Lark Base (Native Async)."""
        if not record_id:
            raise ValueError("record_id không được để trống khi cập nhật.")

        url = f"{self._records_url}/{record_id}"
        data = await self._arequest(
            method="PUT",
            url=url,
            params={"user_id_type": user_id_type},
            json_data={"fields": fields},
            use_tenant_token=use_tenant_token,
            action_name="Cập nhật record async",
        )
        return self._record_from_data(data.get("record", {}), fallback_id=record_id)

    async def adelete_record(self, record_id: str, use_tenant_token: bool = True) -> bool:
        """Xóa một bản ghi trong bảng Lark Base theo record_id (Native Async)."""
        if not record_id:
            return False

        url = f"{self._records_url}/{record_id}"
        try:
            data = await self._arequest(
                method="DELETE",
                url=url,
                use_tenant_token=use_tenant_token,
                action_name="Xóa record async",
            )
            return bool(data.get("deleted", False))
        except Exception as e:
            logger.error(f"Lỗi khi xóa record async {record_id}: {e}")
            return False


# =============================================================================
# TOP-LEVEL CONVENIENCE FUNCTIONS
# =============================================================================

# Singleton instance mặc định khởi tạo từ file .env / settings
lark_base_service = LarkBaseService()


def find_lark_base_record_by_chat_id(chat_id: str) -> Optional[LarkBaseRecord]:
    """Hàm tiện ích tra cứu nhanh bản ghi theo chat_id."""
    return lark_base_service.find_record_by_chat_id(chat_id)


def create_lark_base_record(fields: Dict[str, Any]) -> LarkBaseRecord:
    """Hàm tiện ích tạo nhanh bản ghi trong Lark Base."""
    return lark_base_service.create_record(fields)


def update_lark_base_record(record_id: str, fields: Dict[str, Any]) -> LarkBaseRecord:
    """Hàm tiện ích cập nhật nhanh bản ghi trong Lark Base."""
    return lark_base_service.update_record(record_id, fields)


def read_lark_base_records(
    app_token: Optional[str] = None,
    table_id: Optional[str] = None,
    user_access_token: Optional[str] = None,
    clean: bool = True,
    max_records: Optional[int] = None,
    filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Hàm tiện ích nhanh nhất để đọc toàn bộ dữ liệu trong bảng Lark Base thành list of dicts (Sync)."""
    svc = LarkBaseService(
        app_token=app_token,
        table_id=table_id,
        user_access_token=user_access_token,
    )
    records = svc.get_all_records(max_records=max_records, filter=filter)
    return [r.to_dict(clean=clean) for r in records]


async def aread_lark_base_records(
    app_token: Optional[str] = None,
    table_id: Optional[str] = None,
    user_access_token: Optional[str] = None,
    clean: bool = True,
    max_records: Optional[int] = None,
    filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Hàm bất đồng bộ tương ứng của read_lark_base_records (Native Async)."""
    svc = LarkBaseService(
        app_token=app_token,
        table_id=table_id,
        user_access_token=user_access_token,
    )
    records = await svc.aget_all_records(max_records=max_records, filter=filter)
    return [r.to_dict(clean=clean) for r in records]


# =============================================================================
# STANDALONE BITABLE REAL-TIME LISTENER (WEBSOCKET)
# =============================================================================

def start_bitable_ws_listener(service: LarkBaseService) -> None:
    """
    Khởi động WebSocket Client ĐỘC LẬP dành riêng cho Lark Base (Bitable).
    Chỉ đăng ký và xử lý các sự kiện thay đổi dữ liệu của Base:
      - drive.file.bitable_record_changed_v1
      - drive.file.bitable_field_changed_v1
    TUYỆT ĐỐI KHÔNG can thiệp hoặc lắng nghe tin nhắn chat IM của Bot.
    """
    import lark_oapi as lark
    from lark_oapi.api.drive.v1 import (
        P2DriveFileBitableRecordChangedV1,
        P2DriveFileBitableFieldChangedV1,
    )

    app_id = getattr(settings, "LARK_APP_ID", "") or os.getenv("LARK_APP_ID", "")
    app_secret = getattr(settings, "LARK_APP_SECRET", "") or os.getenv("LARK_APP_SECRET", "")
    encrypt_key = getattr(settings, "LARK_ENCRYPT_KEY", "") or os.getenv("LARK_ENCRYPT_KEY", "")
    verification_token = getattr(settings, "LARK_VERIFICATION_TOKEN", "") or os.getenv("LARK_VERIFICATION_TOKEN", "")

    print("\n" + "=" * 70)
    print("⚡ HILARK - LẮNG NGHE SỰ KIỆN LARK BASE REAL-TIME (WEBSOCKET ĐỘC LẬP)")
    print("=" * 70)
    print(f"App ID     : {app_id}")
    print(f"Domain     : {service.domain}")
    print(f"Base Token : {service.app_token}")
    print(f"Table ID   : {service.table_id}")

    # Đọc trước schema các trường để hiển thị tên cột thay vì field_id khó hiểu
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

    # Build EventDispatcher CHỈ CHO BASE (Tuyệt đối không có IM message)
    dispatcher = (
        lark.EventDispatcherHandler.builder(encrypt_key, verification_token)
        .register_p2_drive_file_bitable_record_changed_v1(on_record_changed)
        .register_p2_drive_file_bitable_field_changed_v1(on_field_changed)
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
        help="Lắng nghe sự kiện thay đổi dữ liệu bảng theo thời gian thực (Lark WebSocket)",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Tự động quét và đồng bộ toàn bộ các nhóm chat của Bot vào bảng Lark Base",
    )

    args = parser.parse_args()

    if args.sync:
        service = LarkBaseService(app_token=args.app_token, table_id=args.table_id)
        print("\n" + "=" * 70)
        print("🔄 HILARK - TỰ ĐỘNG ĐỒNG BỘ NHÓM CHAT BOT VÀO LARK BASE")
        print("=" * 70)
        print(f"Base Token : {service.app_token}")
        print(f"Table ID   : {service.table_id}")
        res = service.sync_bot_chats()
        print(f"✔ Tổng số nhóm chat tìm thấy : {res.get('total_chats', 0)}")
        print(f"✔ Đã thêm mới vào Base       : {len(res.get('added', []))}")
        print(f"✔ Đã cập nhật vào dòng trống : {len(res.get('updated', []))}")
        for item in res.get("added", []) + res.get("updated", []):
            print(f"   • {item.get('name')}: {item.get('chat_id')} -> Record: {item.get('record_id')}")
        print("=" * 70 + "\n")
        return

    if args.listen:
        service = LarkBaseService(app_token=args.app_token, table_id=args.table_id)
        start_bitable_ws_listener(service)
        return

    # Khởi tạo service với các tham số từ CLI hoặc .env
    service = LarkBaseService(
        app_token=args.app_token,
        table_id=args.table_id,
        user_access_token=args.token,
    )

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
