"""Tenant-aware registry for customer-owned Lark Custom Apps."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database.db import get_lark_apps_collection
from services.user_settings_service import user_settings_service

logger = logging.getLogger("hilark.lark_app_service")


async def _invalidate_tenant_caches(tenant_key: Optional[str]) -> None:
    """
    Credential của App vừa thay đổi -> resolver và token broker không được giữ bản cũ.

    Nếu bỏ bước này, một lần `register_app` thay secret vẫn có thể bị token/request cũ
    phục vụ trong 60s (RAM cache của resolver) hoặc tới hết hạn (token đã cache).
    """
    if not tenant_key:
        return
    try:
        from services.tenancy.tenant_state import tenant_state

        await tenant_state.invalidate_caches(str(tenant_key))
    except Exception as exc:  # pragma: no cover - cache không được làm hỏng luồng ghi DB
        logger.warning("Không invalidate được cache cho tenant '%s': %s", tenant_key, exc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LarkAppService:
    """Lưu credential App theo registration/tenant, không ghi đè settings global."""

    async def register_app(
        self,
        app_id: str,
        app_secret: str = "",
        verification_token: str = "",
        encrypt_key: str = "",
        *,
        require_webhook_secrets: bool = True,
        custom_mongo_url: Optional[str] = None,
        tenant_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        app_id = (app_id or "").strip()
        app_secret = (app_secret or "").strip()
        verif_clean = (verification_token or "").strip()
        encrypt_clean = (encrypt_key or "").strip()
        if not app_id.startswith("cli_"):
            raise ValueError("App ID không hợp lệ.")

        col = get_lark_apps_collection()
        existing = await col.find_one({"app_id": app_id})

        encrypted_secret = existing.get("encrypted_app_secret", "") if existing else ""
        masked_secret = existing.get("masked_app_secret", "") if existing else ""
        if app_secret:
            encrypted_secret = user_settings_service.encrypt_key(app_secret)
            masked_secret = user_settings_service.mask_key(app_secret)
        elif require_webhook_secrets or not encrypted_secret:
            raise ValueError("App Secret không được để trống.")

        if require_webhook_secrets:
            if not verif_clean:
                raise ValueError("Verification Token bắt buộc để định tuyến và xác thực webhook của App.")
            if not encrypt_clean:
                raise ValueError("Encrypt Key bắt buộc để giải mã webhook của App.")

        encrypted_verif = (
            user_settings_service.encrypt_key(verif_clean)
            if verif_clean
            else (existing.get("encrypted_verification_token", "") if existing else "")
        )
        encrypted_encrypt = (
            user_settings_service.encrypt_key(encrypt_clean)
            if encrypt_clean
            else (existing.get("encrypted_encrypt_key", "") if existing else "")
        )

        clean_mongo = (
            custom_mongo_url.strip() or None
            if custom_mongo_url is not None
            else (existing.get("custom_mongo_url") if existing else None)
        )
        clean_tenant = (tenant_key or "").strip() or (existing.get("tenant_key") if existing else None)

        registration_id = existing.get("registration_id") if existing else uuid.uuid4().hex
        now = _now()
        doc = {
            "registration_id": registration_id,
            "app_id": app_id,
            "encrypted_app_secret": encrypted_secret,
            "masked_app_secret": masked_secret,
            "encrypted_verification_token": encrypted_verif,
            "encrypted_encrypt_key": encrypted_encrypt,
            "custom_mongo_url": clean_mongo,
            "status": existing.get("status", "pending") if existing else "pending",
            "tenant_key": clean_tenant,
            "updated_at": now,
            "created_at": existing.get("created_at", now) if existing else now,
        }
        await col.update_one({"app_id": app_id}, {"$set": doc}, upsert=True)
        await _invalidate_tenant_caches(doc.get("tenant_key"))
        from services.lark.runtime import invalidate_lark_service
        invalidate_lark_service(app_id)
        return {
            "registration_id": registration_id,
            "app_id": app_id,
            "status": doc["status"],
            "tenant_key": clean_tenant,
            "custom_mongo_url": clean_mongo,
        }

    async def get_registration(self, registration_id: str) -> Optional[Dict[str, Any]]:
        if not isinstance(registration_id, str) or not registration_id.strip():
            return None
        doc = await get_lark_apps_collection().find_one({"registration_id": registration_id})
        return self._decrypt(doc) if doc else None

    async def get_by_app_id(self, app_id: str) -> Optional[Dict[str, Any]]:
        if not isinstance(app_id, str) or not app_id.strip():
            return None
        doc = await get_lark_apps_collection().find_one({"app_id": app_id})
        return self._decrypt(doc) if doc else None

    async def get_by_tenant_key(self, tenant_key: str) -> Optional[Dict[str, Any]]:
        """Lấy Custom App đã liên kết với tenant để gửi/nhận đúng app identity."""
        if not isinstance(tenant_key, str) or not tenant_key.strip():
            return None
        doc = await get_lark_apps_collection().find_one(
            {"tenant_key": tenant_key, "status": {"$ne": "revoked"}},
            sort=[("updated_at", -1)],
        )
        return self._decrypt(doc) if doc else None

    async def list_registrations(self) -> list[Dict[str, Any]]:
        """Lấy danh sách App đã đăng ký để giải mã webhook encrypted payload."""
        cursor = get_lark_apps_collection().find({})
        docs = await cursor.to_list(length=1000)
        return [self._decrypt(doc) for doc in docs]

    async def link_tenant(self, registration_id: str, tenant_key: str, admin_open_id: str = "") -> Optional[Dict[str, Any]]:
        if not registration_id or not tenant_key:
            return None
        await get_lark_apps_collection().update_one(
            {"registration_id": registration_id},
            {"$set": {"tenant_key": tenant_key, "admin_open_id": admin_open_id, "status": "active", "updated_at": _now()}},
        )
        # Tenant vừa được gắn vào một App cụ thể: mọi phân giải token/config cũ của nó
        # (có thể đang trỏ sang App khác) phải bị loại ngay.
        await _invalidate_tenant_caches(tenant_key)
        reg = await self.get_registration(registration_id)
        if reg and reg.get("app_id"):
            from services.lark.runtime import invalidate_lark_service
            invalidate_lark_service(reg["app_id"])
        return reg

    @staticmethod
    def _decrypt(doc: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(doc)
        result.pop("_id", None)
        result["app_secret"] = user_settings_service.decrypt_key(result.get("encrypted_app_secret", ""))
        result["verification_token"] = user_settings_service.decrypt_key(result.get("encrypted_verification_token", ""))
        result["encrypt_key"] = user_settings_service.decrypt_key(result.get("encrypted_encrypt_key", ""))
        return result


lark_app_service = LarkAppService()
