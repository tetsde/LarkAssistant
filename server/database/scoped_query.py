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
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Dict, List, Optional, Union
from motor.motor_asyncio import AsyncIOMotorCollection

from core.config import settings

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

