"""
HiLark Database Multi-Tenant Scoped Query Engine (EDL-0020)
============================================================
Vị trí: server/database/scoped_query.py

Chịu trách nhiệm:
  1. Quản lý Tenant Context theo từng luồng bất đồng bộ (ContextVar Isolation).
  2. Tự động tiêm bộ lọc tenant_key vào mọi câu truy vấn find, count, update, delete.
  3. Tự động gắn nhãn tenant_key vào mọi bản ghi mới khi insert_one, insert_many.
  4. Lớp bọc an toàn TenantScopedCollection bảo vệ toàn diện dữ liệu, loại trừ rủi ro rò rỉ dữ liệu chéo giữa các công ty.
  5. Bảo lưu chế độ Single-Tenant / Backward Compatibility khi không có tenant_key.
"""

from __future__ import annotations

import contextvars
import inspect
import logging
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Dict, List, Optional, Union
from motor.motor_asyncio import AsyncIOMotorCollection

from core.config import settings

logger = logging.getLogger("hilark.database.scoped_query")

# Biến ngữ cảnh tenant hiện tại cho async task
_current_tenant_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_tenant_var", default=None
)


def get_current_tenant_key() -> Optional[str]:
    """Lấy tenant_key đang hoạt động trong ngữ cảnh hiện tại."""
    return _current_tenant_var.get()


def set_current_tenant_key(tenant_key: Optional[str]) -> None:
    """Thiết lập tenant_key thủ công cho ngữ cảnh hiện tại."""
    _current_tenant_var.set(tenant_key)


@contextmanager
def tenant_context(tenant_key: Optional[str]):
    """Context manager đồng bộ thiết lập tạm thời tenant_key và khôi phục khi thoát."""
    token = _current_tenant_var.set(tenant_key)
    try:
        yield
    finally:
        _current_tenant_var.reset(token)


@asynccontextmanager
async def async_tenant_context(tenant_key: Optional[str]):
    """Context manager bất đồng bộ thiết lập tạm thời tenant_key và khôi phục khi thoát."""
    token = _current_tenant_var.set(tenant_key)
    try:
        yield
    finally:
        _current_tenant_var.reset(token)


def inject_tenant_filter(
    filter_dict: Optional[Dict[str, Any]] = None,
    tenant_key: Optional[str] = None,
    allow_legacy_unscoped: bool = False,
) -> Dict[str, Any]:
    """
    Tiêm điều kiện tenant_key vào bộ lọc truy vấn MongoDB:
      - Ưu tiên tenant_key được truyền vào trực tiếp.
      - Nếu không có, lấy từ ngữ cảnh hiện tại qua get_current_tenant_key().
      - Nếu có tenant_key: Đính kèm {"tenant_key": effective_tenant}.
      - Nếu allow_legacy_unscoped=True và có tenant_key: Cho phép tìm cả tài liệu của tenant_key lẫn tài liệu cũ không có tenant_key ($in: [None, "", tenant_key]).
      - Nếu không có tenant_key (chạy Single-Tenant test): Trả về filter_dict ban đầu mà không ép buộc.
    """
    res = dict(filter_dict or {})
    effective_tenant = tenant_key or get_current_tenant_key()

    if effective_tenant and effective_tenant.strip():
        eff = effective_tenant.strip()
        if allow_legacy_unscoped:
            res["tenant_key"] = {"$in": [None, "", eff]}
        else:
            res["tenant_key"] = eff

    return res


class TenantScopedCollection:
    """
    Lớp bọc bảo vệ an toàn cho Motor Collection:
    Tự động áp dụng tenant_key cho mọi thao tác đọc/ghi dữ liệu.
    """

    def __init__(self, raw_collection: AsyncIOMotorCollection, tenant_key: Optional[str] = None):
        self._raw_col = raw_collection
        self._tenant_key = tenant_key

    @property
    def effective_tenant(self) -> Optional[str]:
        return self._tenant_key or get_current_tenant_key()

    def find(self, filter: Optional[Dict[str, Any]] = None, *args, **kwargs):
        scoped_filter = inject_tenant_filter(filter, self.effective_tenant)
        return self._raw_col.find(scoped_filter, *args, **kwargs)

    async def find_one(self, filter: Optional[Dict[str, Any]] = None, *args, **kwargs):
        scoped_filter = inject_tenant_filter(filter, self.effective_tenant)
        return await self._raw_col.find_one(scoped_filter, *args, **kwargs)

    async def insert_one(self, document: Dict[str, Any], *args, **kwargs):
        doc = dict(document)
        eff = self.effective_tenant
        if eff and not doc.get("tenant_key"):
            doc["tenant_key"] = eff
        return await self._raw_col.insert_one(doc, *args, **kwargs)

    async def insert_many(self, documents: List[Dict[str, Any]], *args, **kwargs):
        docs: List[Dict[str, Any]] = []
        eff = self.effective_tenant
        for d in documents:
            doc = dict(d)
            if eff and not doc.get("tenant_key"):
                doc["tenant_key"] = eff
            docs.append(doc)
        return await self._raw_col.insert_many(docs, *args, **kwargs)

    async def update_one(self, filter: Dict[str, Any], update: Dict[str, Any], *args, **kwargs):
        scoped_filter = inject_tenant_filter(filter, self.effective_tenant)
        return await self._raw_col.update_one(scoped_filter, update, *args, **kwargs)

    async def update_many(self, filter: Dict[str, Any], update: Dict[str, Any], *args, **kwargs):
        scoped_filter = inject_tenant_filter(filter, self.effective_tenant)
        return await self._raw_col.update_many(scoped_filter, update, *args, **kwargs)

    async def delete_one(self, filter: Dict[str, Any], *args, **kwargs):
        scoped_filter = inject_tenant_filter(filter, self.effective_tenant)
        return await self._raw_col.delete_one(scoped_filter, *args, **kwargs)

    async def delete_many(self, filter: Dict[str, Any], *args, **kwargs):
        scoped_filter = inject_tenant_filter(filter, self.effective_tenant)
        return await self._raw_col.delete_many(scoped_filter, *args, **kwargs)

    async def count_documents(self, filter: Optional[Dict[str, Any]] = None, *args, **kwargs):
        scoped_filter = inject_tenant_filter(filter, self.effective_tenant)
        return await self._raw_col.count_documents(scoped_filter, *args, **kwargs)

    def __getattr__(self, item: str):
        """Ủy quyền mọi thuộc tính hoặc method khác cho raw collection gốc."""
        return getattr(self._raw_col, item)


def get_scoped_collection(
    raw_collection: AsyncIOMotorCollection,
    tenant_key: Optional[str] = None,
) -> TenantScopedCollection:
    """Hàm tiện ích tạo nhanh TenantScopedCollection."""
    return TenantScopedCollection(raw_collection, tenant_key)


async def resolve_tenant_by_admin_open_id(
    open_id: Optional[str],
    *,
    app_id: Optional[str] = None,
    tenants_collection: Any = None,
) -> Optional[str]:
    """
    Tra cứu `tenant_key` theo `admin_open_id` một cách fail-closed.

    - Luôn lọc thêm `app_id` khi caller đã xác định được runtime App.
    - Nếu khớp duy nhất 1 tenant có `tenant_key` hợp lệ -> trả về `tenant_key`.
    - Nếu khớp >= 2 tenant (trùng `admin_open_id` đa doanh nghiệp) -> log cảnh báo và
      trả về `None` (fail-closed, tuyệt đối không chọn ngẫu nhiên một tenant).
    """
    clean_open_id = str(open_id or "").strip()
    if not clean_open_id or clean_open_id in ("ou_default_admin", "ou_admin_fallback"):
        return None

    query: Dict[str, Any] = {"admin_open_id": clean_open_id}
    clean_app_id = str(app_id or "").strip()
    if clean_app_id:
        query["app_id"] = clean_app_id

    try:
        if tenants_collection is None:
            from database.db import get_tenants_collection

            tenants_collection = get_tenants_collection()

        docs: Optional[List[Dict[str, Any]]] = None
        find_fn = getattr(tenants_collection, "find", None)
        if callable(find_fn):
            cursor = find_fn(query)
            if inspect.isawaitable(cursor):
                awaited = await cursor
                if isinstance(awaited, list):
                    docs = awaited[:2]
            elif isinstance(cursor, list):
                docs = cursor[:2]
            elif cursor is not None:
                limit_fn = getattr(cursor, "limit", None)
                limited = limit_fn(2) if callable(limit_fn) else cursor
                to_list_fn = getattr(limited, "to_list", None)
                if callable(to_list_fn):
                    res_list = to_list_fn(2)
                    if inspect.isawaitable(res_list):
                        awaited = await res_list
                        if isinstance(awaited, list):
                            docs = awaited[:2]
                    elif isinstance(res_list, list):
                        docs = res_list[:2]

        if docs is None:
            # Tương thích mock collection tối giản trong test chỉ stub `find_one`
            find_one_fn = getattr(tenants_collection, "find_one", None)
            if not callable(find_one_fn):
                return None
            found = find_one_fn(query)
            if inspect.isawaitable(found):
                found = await found
            docs = [found] if isinstance(found, dict) else []

        valid_tenants: List[str] = []
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            tk = str(doc.get("tenant_key") or "").strip()
            if tk:
                valid_tenants.append(tk)

        if len(valid_tenants) == 1:
            return valid_tenants[0]
        if len(valid_tenants) >= 2:
            logger.warning(
                "[TENANCY] admin_open_id_collision open_id=%s app_id=%s matched_count=%d action=fail_closed",
                clean_open_id,
                clean_app_id or "-",
                len(valid_tenants),
            )
            return None
        return None
    except Exception as exc:
        logger.debug(
            "[TENANCY] resolve_tenant_by_admin_open_id_failed open_id=%s app_id=%s error=%s",
            clean_open_id,
            clean_app_id or "-",
            exc,
        )
        return None

