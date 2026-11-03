"""
HiLark - Tenant State Machine & Invalidation Hub
================================================
Vị trí: server/services/tenancy/tenant_state.py

Mục đích (GĐ5 của kế hoạch Tenant Resolution & Token Fix):
    1. Là CHỖ DUY NHẤT đổi trạng thái vòng đời tenant trên collection `tenants`.
       Trước đây mỗi luồng (setup, lifecycle event, router) tự viết `$set` theo cách
       riêng nên trạng thái có thể nhảy ngược (ready -> active -> provisioning) và
       cache/resolver không được báo.
    2. Khi trạng thái đổi, luôn báo cho `tenant_resolver` và `token_broker` bỏ dữ liệu
       cũ — đây là cách duy nhất để cache RAM 60s không phục vụ cấu hình/token của
       trạng thái đã chết.

Trạng thái hợp lệ (field `status` đã tồn tại, không đổi schema):
    provisioning          -> ready | provisioning_failed | uninstalled
    provisioning_failed  -> provisioning | ready | uninstalled
    ready                 -> provisioning | inactive | uninstalled
    active                -> ready | inactive | uninstalled   (tenant cũ chưa provision xong)
    inactive              -> ready | active | uninstalled     (start lại)
    uninstalled           -> provisioning                     (cài đặt lại từ đầu)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Optional, Set, Tuple

from database.db import get_tenants_collection
from models.memory import get_vietnam_now_iso

logger = logging.getLogger("hilark.tenant_state")

PROVISIONING = "provisioning"
PROVISIONING_FAILED = "provisioning_failed"
READY = "ready"
ACTIVE = "active"
INACTIVE = "inactive"
UNINSTALLED = "uninstalled"

ALL_STATUSES: Set[str] = {
    PROVISIONING,
    PROVISIONING_FAILED,
    READY,
    ACTIVE,
    INACTIVE,
    UNINSTALLED,
}

ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    PROVISIONING: {READY, PROVISIONING_FAILED, UNINSTALLED},
    PROVISIONING_FAILED: {PROVISIONING, READY, UNINSTALLED},
    # ready -> provisioning là luồng "Thử lại/cài lại" của một tenant đã bàn giao.
    READY: {INACTIVE, UNINSTALLED, ACTIVE, PROVISIONING},
    ACTIVE: {READY, INACTIVE, UNINSTALLED, PROVISIONING},
    INACTIVE: {READY, ACTIVE, UNINSTALLED, PROVISIONING},
    # Uninstalled vẫn cho phép install lại để một tenant cũ có thể quay lại hệ thống.
    UNINSTALLED: {PROVISIONING, ACTIVE},
}

# Trạng thái được phục vụ dữ liệu thật (resolver chỉ cho qua status này).
SERVING_STATUSES: Set[str] = {READY}


class InvalidTenantTransition(ValueError):
    """Chuyển trạng thái không được phép — dấu hiệu hai luồng đang tự viết `status`."""

    def __init__(self, tenant_key: str, from_status: Optional[str], to_status: str) -> None:
        self.tenant_key = tenant_key
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Chuyển trạng thái tenant '{tenant_key}' từ {from_status!r} sang {to_status!r} "
            f"không được phép. Cho phép: {sorted(ALLOWED_TRANSITIONS.get(from_status or '', set()))}"
        )


class TenantStateService:
    """Machine trạng thái tenant + điểm invalidation tập trung."""

    def __init__(self, collection_factory=None) -> None:
        # Late-binding: nếu tham số mặc định là `get_tenants_collection` (bind lúc định
        # nghĩa class), test thay tên ở mức module sẽ không ảnh hưởng tới singleton đã
        # tạo trước đó, và state machine sẽ ghi thẳng vào DB thật.
        self._collection_factory = collection_factory or (lambda: get_tenants_collection())

    # -------------------------------------------------------------------------
    # Đọc
    # -------------------------------------------------------------------------

    async def get_status(self, tenant_key: str) -> Optional[Dict[str, Any]]:
        """Trả về document tenant hiện tại (không che giấu việc tenant chưa tồn tại)."""
        if not tenant_key:
            return None
        col = self._collection_factory()
        found = col.find_one({"tenant_key": tenant_key})
        if hasattr(found, "__await__"):
            found = await found
        return found

    # -------------------------------------------------------------------------
    # Ghi
    # -------------------------------------------------------------------------

    async def transition(
        self,
        tenant_key: str,
        to_status: str,
        *,
        upsert: bool = True,
        invalidate: bool = True,
        **extra_fields: Any,
    ) -> Dict[str, Any]:
        """
        Đổi trạng thái theo bảng ALLOWED_TRANSITIONS rồi báo cache bỏ dữ liệu cũ.

        Returns:
            dict gồm `tenant_key`, `from_status`, `to_status`, `changed` (bool).
        Raises:
            ValueError: tenant_key rỗng hoặc `to_status` không thuộc bảng trạng thái.
            InvalidTenantTransition: chuyển đổi ngược/ngoài bảng (caller phải sửa luồng,
                không được âm thầm ghi đè).
        """
        if not tenant_key or not str(tenant_key).strip():
            raise ValueError("transition() yêu cầu tenant_key tường minh.")
        tenant_key = str(tenant_key).strip()
        if to_status not in ALL_STATUSES:
            raise ValueError(
                f"Trạng thái không biết: {to_status!r}. Hợp lệ: {sorted(ALL_STATUSES)}"
            )

        current = await self.get_status(tenant_key)
        from_status = current.get("status") if isinstance(current, dict) else None

        if from_status and from_status != to_status:
            if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
                raise InvalidTenantTransition(tenant_key, from_status, to_status)

        if from_status == to_status and not extra_fields:
            return {
                "tenant_key": tenant_key,
                "from_status": from_status,
                "to_status": to_status,
                "changed": False,
            }

        payload: Dict[str, Any] = {
            "tenant_key": tenant_key,
            "status": to_status,
            "updated_at": get_vietnam_now_iso(),
            **{k: v for k, v in extra_fields.items() if v is not None},
        }
        if to_status == READY:
            payload["ready_at"] = payload["updated_at"]
        if to_status == UNINSTALLED:
            payload["uninstalled_at"] = payload["updated_at"]

        col = self._collection_factory()
        op = col.update_one(
            {"tenant_key": tenant_key},
            {"$set": payload, "$setOnInsert": {"created_at": payload["updated_at"]}},
            upsert=upsert,
        )
        if hasattr(op, "__await__"):
            await op

        if invalidate:
            await self._invalidate(tenant_key)

        logger.info(
            "🧬 [TENANT STATE] '%s': %s -> %s%s",
            tenant_key,
            from_status or "<new>",
            to_status,
            f" (fields={sorted(extra_fields)})" if extra_fields else "",
        )
        return {
            "tenant_key": tenant_key,
            "from_status": from_status,
            "to_status": to_status,
            "changed": True,
        }

    async def mark_ready(self, tenant_key: str, **extra_fields: Any) -> Dict[str, Any]:
        """Điểm hẹn duy nhất: provisioning hoàn tất, tenant bắt đầu được phục vụ."""
        return await self.transition(tenant_key, READY, **extra_fields)

    async def mark_provisioning(self, tenant_key: str, **extra_fields: Any) -> Dict[str, Any]:
        return await self.transition(tenant_key, PROVISIONING, **extra_fields)

    async def mark_provisioning_failed(self, tenant_key: str, error: str, **extra_fields: Any) -> Dict[str, Any]:
        """
        Setup thất bại: ghi `provisioning_failed` + lý do để UI hiện nút "Thử lại".
        Dùng upsert=False: nếu tenant chưa có document thì không có gì để đánh dấu hỏng,
        thay vì chèn một document cô lập chỉ chứa trạng thái lỗi.
        """
        return await self.transition(
            tenant_key,
            PROVISIONING_FAILED,
            upsert=False,
            provisioning_error=str(error or "")[:1000],
            **extra_fields,
        )

    async def mark_inactive(self, tenant_key: str, **extra_fields: Any) -> Dict[str, Any]:
        """Doanh nghiệp tắt app (stop_by_tenant): ngừng phục vụ nhưng giữ dữ liệu."""
        return await self.transition(tenant_key, INACTIVE, **extra_fields)

    async def mark_active(self, tenant_key: str, **extra_fields: Any) -> Dict[str, Any]:
        """Doanh nghiệp bật lại app; ready/inactive -> ready, tenant cũ -> active."""
        current = await self.get_status(tenant_key)
        status = current.get("status") if isinstance(current, dict) else None
        if status in {READY, INACTIVE, ACTIVE}:
            return await self.transition(tenant_key, READY, **extra_fields)
        return await self.transition(tenant_key, ACTIVE, **extra_fields)

    async def mark_uninstalled(self, tenant_key: str, **extra_fields: Any) -> Dict[str, Any]:
        """upsert=False: uninstalled chỉ áp dụng cho tenant đã tồn tại trong DB."""
        return await self.transition(tenant_key, UNINSTALLED, upsert=False, **extra_fields)

    # -------------------------------------------------------------------------
    # Invalidation (cũng dùng cho register_app / link_tenant)
    # -------------------------------------------------------------------------

    async def _invalidate(self, tenant_key: str) -> None:
        await self.invalidate_caches(tenant_key)

    async def invalidate_caches(self, tenant_key: Optional[str] = None) -> Tuple[int, int]:
        """
        Báo resolver (RAM 60s) và token broker bỏ cấu hình/token đang giữ cho tenant.

        Không được ném exception ở đây: invalidation hỏng chỉ làm dữ liệu cũ sống thêm
        60s, trong khi trạng thái đã ghi xuống DB là sự thật phải được giữ.
        """
        resolver_missed = 0
        broker_missed = 0
        try:
            from services.tenancy.tenant_resolver import tenant_resolver

            resolver_missed = tenant_resolver.invalidate(tenant_key)
        except Exception as exc:  # pragma: no cover - phụ thuộc module
            logger.warning("Không invalidate được tenant_resolver cho '%s': %s", tenant_key, exc)

        try:
            if tenant_key:
                from services.auth.tenant_token_manager import token_broker

                await token_broker.invalidate(tenant_key)
        except Exception as exc:  # pragma: no cover - phụ thuộc token loop
            logger.warning("Không invalidate được token_broker cho '%s': %s", tenant_key, exc)

        return resolver_missed, broker_missed


tenant_state = TenantStateService()
"""Singleton machine trạng thái tenant."""

__all__ = [
    "ALL_STATUSES",
    "ALLOWED_TRANSITIONS",
    "SERVING_STATUSES",
    "InvalidTenantTransition",
    "TenantStateService",
    "tenant_state",
    "PROVISIONING",
    "PROVISIONING_FAILED",
    "READY",
    "ACTIVE",
    "INACTIVE",
    "UNINSTALLED",
]
