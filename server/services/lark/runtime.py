"""Runtime registry for tenant-owned Lark Custom App clients."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, Dict, Optional

from services.auth.token_service import token_service

logger = logging.getLogger("hilark.lark")


_current_service: ContextVar[Any] = ContextVar("current_lark_service", default=None)
_services: Dict[str, Any] = {}


def get_current_lark_service(default: Any = None) -> Any:
    return _current_service.get() or default


def set_current_lark_service(service: Any):
    return _current_service.set(service)


def reset_current_lark_service(token: Any) -> None:
    _current_service.reset(token)


def get_lark_service_for_tenant(tenant_key: str) -> Optional[Any]:
    """
    Trả về LarkService đã được đăng ký cho tenant_key chỉ định.
    Tra cứu theo app_id đã được gắn với tenant_key trong _services cache.

    Returns None nếu không tìm thấy (caller cần fallback về default service).
    """
    if not tenant_key:
        return None
    for svc in _services.values():
        svc_app_id = getattr(svc, "app_id", None)
        if not svc_app_id:
            continue
        # Tìm trong _services theo app_id, sau đó kiểm tra tenant_key của service
        # bằng cách tra DB sync (chỉ dùng cache nếu có)
        svc_tenant = getattr(svc, "_tenant_key_hint", None)
        if svc_tenant and svc_tenant == tenant_key:
            return svc
    # Fallback: tra DB đồng bộ để tìm app_id → service
    try:
        from database.db import get_sync_db
        from core.config import get_settings
        settings = get_settings()
        db = get_sync_db()
        app_col = getattr(settings, "MONGO_LARK_APPS_COLLECTION", "lark_app_credentials")
        rec = db[app_col].find_one(
            {"tenant_key": tenant_key, "status": {"$ne": "revoked"}},
            {"app_id": 1},
        )
        if rec:
            app_id = rec.get("app_id")
            if app_id and app_id in _services:
                # Cache hint để lần sau không cần tra DB
                svc = _services[app_id]
                object.__setattr__(svc, "_tenant_key_hint", tenant_key) if hasattr(type(svc), "__slots__") else setattr(svc, "_tenant_key_hint", tenant_key)
                return svc
    except Exception as e:
        logger.debug("[LARK_RUNTIME] lookup_failed tenant=%s error=%s", tenant_key, e)
    return None


def invalidate_lark_service(app_id: Optional[str] = None) -> None:
    """Xóa cache LarkService trong RAM khi App credentials được cập nhật."""
    if app_id:
        _services.pop(app_id, None)
        logger.info("[LARK_RUNTIME] cache_invalidated app_id=%s", app_id)
    else:
        _services.clear()
        logger.info("[LARK_RUNTIME] cache_cleared")


async def get_or_create_lark_service(app_record: Dict[str, Any]) -> Any:
    """Create one isolated SDK/dispatcher per registered Custom App."""
    app_id = app_record.get("app_id", "")
    if not app_id:
        raise ValueError("Custom App record thiếu app_id")

    service = _services.get(app_id)

    # Tự động nhận diện nếu người dùng vừa cập nhật lại Khóa (Secret, Encrypt Key, Verification Token)
    # trên UI Setup/Onboarding -> Buộc tái tạo mới LarkService ngay, không dùng bản cũ trong RAM.
    if service is not None:
        rec_secret = app_record.get("app_secret", "")
        rec_verif = app_record.get("verification_token", "")
        rec_encrypt = app_record.get("encrypt_key", "")
        if (
            service.app_secret != rec_secret
            or service.verification_token != rec_verif
            or service.encrypt_key != rec_encrypt
        ):
            logger.info("[LARK_RUNTIME] client_rebuilt app_id=%s reason=credentials_changed", app_id)
            service = None
            _services.pop(app_id, None)

    if service is None:
        # Local import avoids the package-level Lark singleton circular import.
        from services.lark import LarkService
        from services.lark.bot_runner import handle_lark_incoming_message
        from services.auth.tenant_token_manager import tenant_token_manager

        tenant_key = app_record.get("tenant_key")
        access_token: Optional[str] = None
        if tenant_key:
            try:
                access_token = await tenant_token_manager.get_token(
                    tenant_key=tenant_key,
                    token_type="user"
                )
            except Exception as e:
                logger.warning("[LARK_RUNTIME] user_token_unavailable tenant=%s error=%s", tenant_key, e)
        
        service = LarkService(
            app_id=app_id,
            app_secret=app_record.get("app_secret", ""),
            verification_token=app_record.get("verification_token", ""),
            encrypt_key=app_record.get("encrypt_key", ""),
            user_access_token=access_token or "",
            user_open_id=app_record.get("admin_open_id", ""),
        )
        service.register_handler(handle_lark_incoming_message)
        from services.knowledge.chat_scopes import scope_service
        service.register_bitable_record_handler(scope_service.handle_bitable_record_changed_event)
        _services[app_id] = service
    else:
        from services.knowledge.chat_scopes import scope_service
        if scope_service.handle_bitable_record_changed_event not in service._bitable_record_handlers:
            service.register_bitable_record_handler(scope_service.handle_bitable_record_changed_event)
        from services.auth.tenant_token_manager import tenant_token_manager
        
        tenant_key = app_record.get("tenant_key")
        access_token = None
        if tenant_key:
            try:
                access_token = await tenant_token_manager.get_token(
                    tenant_key=tenant_key,
                    token_type="user"
                )
            except Exception as e:
                logger.warning("[LARK_RUNTIME] user_token_unavailable tenant=%s error=%s", tenant_key, e)
        
        if access_token:
            service.user_access_token = access_token
            service._last_token_check = None

    return service
