"""Runtime registry for tenant-owned Lark Custom App clients."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict, Optional

from services.auth.token_service import token_service


_current_service: ContextVar[Any] = ContextVar("current_lark_service", default=None)
_services: Dict[str, Any] = {}


def get_current_lark_service(default: Any = None) -> Any:
    return _current_service.get() or default


def set_current_lark_service(service: Any):
    return _current_service.set(service)


def reset_current_lark_service(token: Any) -> None:
    _current_service.reset(token)


async def get_or_create_lark_service(app_record: Dict[str, Any]) -> Any:
    """Create one isolated SDK/dispatcher per registered Custom App."""
    app_id = app_record.get("app_id", "")
    if not app_id:
        raise ValueError("Custom App record thiếu app_id")

    service = _services.get(app_id)
    if service is None:
        # Local import avoids the package-level Lark singleton circular import.
        from services.lark import LarkService
        from services.lark.bot_runner import handle_lark_incoming_message

        access_token: Optional[str] = await token_service.get_valid_user_token(
            tenant_key=app_record.get("tenant_key"),
            app_id=app_id,
        )
        service = LarkService(
            app_id=app_id,
            app_secret=app_record.get("app_secret", ""),
            verification_token=app_record.get("verification_token", ""),
            encrypt_key=app_record.get("encrypt_key", ""),
            user_access_token=access_token or "",
            user_open_id=app_record.get("admin_open_id", ""),
        )
        service.register_handler(handle_lark_incoming_message)
        _services[app_id] = service
    else:
        access_token = await token_service.get_valid_user_token(
            tenant_key=app_record.get("tenant_key"),
            app_id=app_id,
        )
        if access_token:
            service.user_access_token = access_token
            service._last_token_check = None

    return service
