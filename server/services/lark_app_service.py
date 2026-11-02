"""Tenant-aware registry for customer-owned Lark Custom Apps."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database.db import get_lark_apps_collection
from services.user_settings_service import user_settings_service


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LarkAppService:
    """Lưu credential App theo registration/tenant, không ghi đè settings global."""

    async def register_app(
        self,
        app_id: str,
        app_secret: str,
        verification_token: str = "",
        encrypt_key: str = "",
    ) -> Dict[str, Any]:
        app_id = (app_id or "").strip()
        app_secret = (app_secret or "").strip()
        if not app_id.startswith("cli_"):
            raise ValueError("App ID không hợp lệ.")
        if not app_secret:
            raise ValueError("App Secret không được để trống.")
        if not (verification_token or "").strip():
            raise ValueError("Verification Token bắt buộc để định tuyến và xác thực webhook của App.")
        if not (encrypt_key or "").strip():
            raise ValueError("Encrypt Key bắt buộc để giải mã webhook của App.")

        col = get_lark_apps_collection()
        existing = await col.find_one({"app_id": app_id})
        registration_id = existing.get("registration_id") if existing else uuid.uuid4().hex
        now = _now()
        doc = {
            "registration_id": registration_id,
            "app_id": app_id,
            "encrypted_app_secret": user_settings_service.encrypt_key(app_secret),
            "encrypted_verification_token": user_settings_service.encrypt_key(verification_token),
            "encrypted_encrypt_key": user_settings_service.encrypt_key(encrypt_key),
            "status": existing.get("status", "pending") if existing else "pending",
            "tenant_key": existing.get("tenant_key") if existing else None,
            "updated_at": now,
            "created_at": existing.get("created_at", now) if existing else now,
        }
        await col.update_one({"app_id": app_id}, {"$set": doc}, upsert=True)
        return {"registration_id": registration_id, "app_id": app_id, "status": doc["status"]}

    async def get_registration(self, registration_id: str) -> Optional[Dict[str, Any]]:
        if not registration_id:
            return None
        doc = await get_lark_apps_collection().find_one({"registration_id": registration_id})
        return self._decrypt(doc) if doc else None

    async def get_by_app_id(self, app_id: str) -> Optional[Dict[str, Any]]:
        if not app_id:
            return None
        doc = await get_lark_apps_collection().find_one({"app_id": app_id})
        return self._decrypt(doc) if doc else None

    async def get_by_tenant_key(self, tenant_key: str) -> Optional[Dict[str, Any]]:
        """Lấy Custom App đã liên kết với tenant để gửi/nhận đúng app identity."""
        if not tenant_key:
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
        return await self.get_registration(registration_id)

    @staticmethod
    def _decrypt(doc: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(doc)
        result.pop("_id", None)
        result["app_secret"] = user_settings_service.decrypt_key(result.get("encrypted_app_secret", ""))
        result["verification_token"] = user_settings_service.decrypt_key(result.get("encrypted_verification_token", ""))
        result["encrypt_key"] = user_settings_service.decrypt_key(result.get("encrypted_encrypt_key", ""))
        return result


lark_app_service = LarkAppService()
