"""
HiLark - Tenant Resource Resolver
=================================
Vị trí: server/services/tenancy/tenant_resolver.py

Nơi DUY NHẤT trả lời câu hỏi "tenant này có cấu hình gì".

Trước đây câu hỏi này được trả lời ở nhiều nơi khác nhau, mỗi nơi theo một thứ tự riêng:
`bitable._resolve_app_credentials_sync`, `base_provision_service.get_active_base_config`,
và các dòng `... or settings.X` trong workflow. Hai tầng cuối của mọi chuỗi từng là
"App bất kỳ mới nhất trong DB" rồi `.env` — nghĩa là khi dữ liệu của tenant thiếu,
hệ thống lặng lẽ chạy bằng dữ liệu của tenant khác.

Hợp đồng của tầng này:
  1. thiếu `tenant_key`           -> TenantContextMissing
  2. không có document `tenants`  -> TenantNotFound
  3. `status != "ready"`          -> TenantNotReady
  4. không có credential của chính tenant -> TenantConfigIncomplete(["app_credentials"])
  5. `tenants.app_id` != credential.app_id -> TenantConfigIncomplete(["app_id_mismatch"])
  6. thiếu field bắt buộc         -> TenantConfigIncomplete(missing)

Không có nhánh `.env`. `app_id` và `app_secret` luôn lấy từ CÙNG MỘT document credential.

Cache in-memory theo tenant_key (TTL ngắn) vì dữ liệu này gần như bất biến; query Atlas
mỗi tin nhắn sẽ cộng thêm độ trễ không cần thiết. Cache được xoá khi tenant đổi trạng
thái hoặc credential đổi (xem `invalidate`).

Lịch sử:
  - 2026-11-02: Giai đoạn 2 của kế hoạch sửa Tenant Resolution & Token Flow.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from core.tenant_errors import (
    TenantConfigIncomplete,
    TenantContextMissing,
    TenantNotReady,
    TenantNotFound,
)

logger = logging.getLogger("hilark.tenant_resolver")

CACHE_TTL_SECONDS = 60.0

# Field bắt buộc trên document `tenants` để một tenant thực sự phục vụ được.
REQUIRED_TENANT_FIELDS: Tuple[str, ...] = (
    "app_id",
    "weknora_tenant_id",
    "weknora_policy_dataset_id",
    "weknora_wiki_dataset_id",
    "weknora_default_dataset_id",
    "bitable_app_token",
    "chat_scope_table_id",
    "company_policy_table_id",
)


@dataclass(frozen=True)
class TenantResources:
    """Tập giá trị đã kiểm tra của MỘT tenant. Frozen để không sửa chéo request."""

    tenant_key: str
    app_id: str
    app_secret: str
    verification_token: str
    encrypt_key: str
    base_app_token: str
    chat_scope_table_id: str
    company_policy_table_id: str
    weknora_tenant_id: str
    weknora_policy_dataset_id: str
    weknora_wiki_dataset_id: str
    weknora_default_dataset_id: str
    enterprise_name: str = ""
    bitable_app_url: str = ""


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


@dataclass(frozen=True)
class AppCredentials:
    """
    Chỉ credential của App, KHÔNG đòi hỏi tenant đã `ready`.

    Tách riêng vì tầng token cần trả lời cả tenant chưa hoàn tất cài đặt: muốn gửi
    thông báo "doanh nghiệp chưa cài đặt HiLark" thì phải lấy được bot token, mà lúc
    đó cấu hình Base/WeKnora của tenant còn thiếu.
    """

    tenant_key: str
    app_id: str
    app_secret: str
    verification_token: str = ""
    encrypt_key: str = ""


class TenantResourceResolver:
    """Resolver có cache ngắn hạn; mọi lỗi là exception có kiểu, không có giá trị thay thế."""

    def __init__(self, ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._cache: Dict[str, Tuple[TenantResources, float]] = {}

    # -------------------------------------------------------------------------
    # LOOKUPS
    # -------------------------------------------------------------------------

    async def _fetch_tenant_doc(self, tenant_key: str) -> Optional[Dict[str, Any]]:
        from database.db import get_tenants_collection

        return await get_tenants_collection().find_one({"tenant_key": tenant_key})

    async def _fetch_credential(self, tenant_key: str) -> Optional[Dict[str, Any]]:
        from database.db import get_lark_apps_collection

        apps_col = get_lark_apps_collection()
        return await apps_col.find_one(
            {"tenant_key": tenant_key, "status": {"$ne": "revoked"}},
            sort=[("updated_at", -1)],
        )

    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    async def resolve_credentials(self, tenant_key: Optional[str]) -> AppCredentials:
        """
        Lấy (app_id, app_secret) của CHÍNH tenant_key đó.

        Đây là lối vào duy nhất cho tầng token. Không có nhánh "App mới nhất trong DB"
        và không đọc `.env`: thiếu credential là raise, không mượn App của tenant khác.
        """
        if not tenant_key or not str(tenant_key).strip():
            raise TenantContextMissing("resolve_credentials() yêu cầu tenant_key.")
        tenant_key = str(tenant_key).strip()

        credential = await self._fetch_credential(tenant_key)
        if not credential or not _is_filled(credential.get("app_id")):
            raise TenantConfigIncomplete(tenant_key, ["app_credentials"])

        from services.user_settings_service import user_settings_service

        app_secret = user_settings_service.decrypt_key(credential.get("encrypted_app_secret", ""))
        if not app_secret:
            raise TenantConfigIncomplete(tenant_key, ["app_secret"])

        return AppCredentials(
            tenant_key=tenant_key,
            app_id=str(credential["app_id"]).strip(),
            app_secret=app_secret,
            verification_token=user_settings_service.decrypt_key(
                credential.get("encrypted_verification_token", "")
            ),
            encrypt_key=user_settings_service.decrypt_key(credential.get("encrypted_encrypt_key", "")),
        )

    def resolve_credentials_sync(self, tenant_key: Optional[str]) -> AppCredentials:
        from core import token_loop

        return token_loop.submit(self.resolve_credentials(tenant_key), timeout=10.0)

    async def resolve(self, tenant_key: Optional[str]) -> TenantResources:
        """
        Trả về `TenantResources` của tenant, hoặc raise. Không bao giờ trả dữ liệu
        của tenant khác và không bao giờ đọc `.env`.
        """
        if not tenant_key or not str(tenant_key).strip():
            raise TenantContextMissing("tenant_resolver.resolve() yêu cầu tenant_key.")
        tenant_key = str(tenant_key).strip()

        cached = self._cache.get(tenant_key)
        if cached and cached[1] > time.time():
            return cached[0]

        tenant_doc = await self._fetch_tenant_doc(tenant_key)
        if not tenant_doc:
            raise TenantNotFound(tenant_key)

        status = tenant_doc.get("status")
        if status != "ready":
            raise TenantNotReady(tenant_key, status=status if status is not None else None)

        credential = await self._fetch_credential(tenant_key)
        missing: List[str] = []
        if not credential or not _is_filled(credential.get("app_id")):
            missing.append("app_credentials")

        app_id = (credential or {}).get("app_id") or ""
        tenant_app_id = tenant_doc.get("app_id") or ""
        if app_id and tenant_app_id and app_id != tenant_app_id:
            missing.append("app_id_mismatch")

        for field in REQUIRED_TENANT_FIELDS:
            if not _is_filled(tenant_doc.get(field)):
                missing.append(field)

        if missing:
            raise TenantConfigIncomplete(tenant_key, missing)

        from services.user_settings_service import user_settings_service

        app_secret = user_settings_service.decrypt_key(credential.get("encrypted_app_secret", ""))
        if not app_secret:
            raise TenantConfigIncomplete(tenant_key, ["app_secret"])

        resources = TenantResources(
            tenant_key=tenant_key,
            app_id=app_id,
            app_secret=app_secret,
            verification_token=user_settings_service.decrypt_key(
                credential.get("encrypted_verification_token", "")
            ),
            encrypt_key=user_settings_service.decrypt_key(credential.get("encrypted_encrypt_key", "")),
            base_app_token=str(tenant_doc.get("bitable_app_token") or "").strip().strip("\"'"),
            chat_scope_table_id=str(tenant_doc.get("chat_scope_table_id") or "").strip(),
            company_policy_table_id=str(tenant_doc.get("company_policy_table_id") or "").strip(),
            weknora_tenant_id=str(tenant_doc.get("weknora_tenant_id") or "").strip(),
            weknora_policy_dataset_id=str(tenant_doc.get("weknora_policy_dataset_id") or "").strip(),
            weknora_wiki_dataset_id=str(tenant_doc.get("weknora_wiki_dataset_id") or "").strip(),
            weknora_default_dataset_id=str(tenant_doc.get("weknora_default_dataset_id") or "").strip(),
            enterprise_name=str(tenant_doc.get("enterprise_name") or ""),
            bitable_app_url=str(tenant_doc.get("bitable_app_url") or ""),
        )
        self._cache[tenant_key] = (resources, time.time() + self._ttl)
        return resources

    def resolve_sync(self, tenant_key: Optional[str]) -> TenantResources:
        """Cho caller sync; coroutine được chạy trên token loop duy nhất."""
        from core import token_loop

        return token_loop.submit(self.resolve(tenant_key), timeout=10.0)

    async def resolve_current(self) -> TenantResources:
        """Resolve theo tenant của ngữ cảnh request hiện tại (ContextVar)."""
        from database.db import get_current_tenant_key

        return await self.resolve(get_current_tenant_key())

    def invalidate(self, tenant_key: Optional[str] = None) -> int:
        """
        Xoá cache. Gọi khi: app_uninstalled, app_status_change(stop), đăng ký lại
        credential, link_tenant, hoặc provisioning -> ready. `tenant_key=None` = xoá hết.
        """
        if tenant_key is None:
            count = len(self._cache)
            self._cache.clear()
            return count
        removed = 0
        key = str(tenant_key).strip()
        if self._cache.pop(key, None) is not None:
            removed += 1
        logger.debug("Resolver cache xoá %s entry cho tenant '%s'", removed, key)
        return removed

    def stats(self) -> Dict[str, Any]:
        now = time.time()
        return {
            "cached_tenants": len(self._cache),
            "fresh_tenants": sum(1 for _, exp in self._cache.values() if exp > now),
            "ttl_seconds": self._ttl,
            "required_fields": list(REQUIRED_TENANT_FIELDS),
        }


tenant_resolver = TenantResourceResolver()
"""Singleton resolver — điểm vào duy nhất cho cấu hình tenant."""


async def resolve_tenant(tenant_key: Optional[str]) -> TenantResources:
    """Hàm tiện ích ngắn gọn cho các call site."""
    return await tenant_resolver.resolve(tenant_key)


def resolve_tenant_sync(tenant_key: Optional[str]) -> TenantResources:
    return tenant_resolver.resolve_sync(tenant_key)
