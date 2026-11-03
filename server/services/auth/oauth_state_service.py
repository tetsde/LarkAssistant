"""
HiLark - OAuth State Service
============================
Vị trí: server/services/auth/oauth_state_service.py

Mục đích (GĐ4 kế hoạch Tenant Resolution & Token Fix):
    `state` của luồng OAuth không còn là một chuỗi tự do do frontend gửi lên. Nó là
    HÓA ĐƠN danh tính: mỗi lần bắt đầu ủy quyền, server ghi xuống
    `oauth_states {_id: state, tenant_key, app_id, purpose, created_at, expires_at, consumed_at}`
    rồi callback chỉ được đổi code bằng đúng (app_id, app_secret, tenant_key) đã ghi.

Vì sao phải làm:
    Trước đây `/auth/lark/callback` gọi `exchange_code_for_token(code=code)` với App
    mặc định trong `.env`. Khi một doanh nghiệp khác bấm link ủy quyền, code của họ bị
    đổi bằng credential của App khác và token được gán nhầm cho tenant có sẵn.

An toàn:
    - State ngẫu nhiên 256-bit, không tự chọn.
    - Dùng một lần: `find_one_and_update` với điều kiện `consumed_at: None` nên hai
      callback song song chỉ có một lần thành công.
    - Hết hạn sau 10 phút (kiểm tra `expires_at` + TTL index để Mongo tự dọn).
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from pymongo import ASCENDING, ReturnDocument

from database.db import get_oauth_states_collection

logger = logging.getLogger("hilark.oauth_state")

# State chỉ sống 10 phút: người dùng bấm link rồi ủy quyền, không để hóa đơn mở lâu.
STATE_TTL_SECONDS = 600


class OAuthStateError(ValueError):
    """State không tồn tại / đã dùng / đã hết hạn — callback phải bị từ chối (400)."""

    error_code = "oauth_state_invalid"

    def __init__(self, message: str, state: Optional[str] = None) -> None:
        self.state = state
        super().__init__(message)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OAuthStateService:
    """Store state OAuth trong MongoDB, chỉ định danh một tenant + một App."""

    def __init__(self) -> None:
        self._index_ready = False

    async def ensure_ttl_index(self) -> None:
        """
        Tạo chỉ mục một lần: TTL trên `created_at` dọn hóa đơn cũ, index trên
        `(tenant_key, app_id)` phục vụ debug. Failures chỉ warn — MongoDB có thể
        chưa sẵn sàng lúc startup và state vẫn tự kiểm tra `expires_at` trong code.
        """
        if self._index_ready:
            return
        try:
            col = get_oauth_states_collection()
            await col.create_index([("created_at", ASCENDING)], expireAfterSeconds=STATE_TTL_SECONDS)
            await col.create_index([("tenant_key", ASCENDING), ("app_id", ASCENDING)])
            self._index_ready = True
        except Exception as exc:  # pragma: no cover - phụ thuộc DB thật
            logger.warning("Không tạo được index cho collection 'oauth_states': %s", exc)

    async def create(
        self,
        tenant_key: str,
        app_id: str,
        purpose: str = "user_oauth",
        ttl_seconds: int = STATE_TTL_SECONDS,
        **extra: Any,
    ) -> str:
        """
        Phát hành một state cho (tenant_key, app_id).

        Raises:
            ValueError: thiếu tenant_key/app_id — không phát hành state vô danh.
        """
        if not tenant_key or not str(tenant_key).strip():
            raise ValueError("oauth_state_service.create() yêu cầu tenant_key.")
        if not app_id or not str(app_id).strip():
            raise ValueError("oauth_state_service.create() yêu cầu app_id của App đang ủy quyền.")

        await self.ensure_ttl_index()
        state = secrets.token_urlsafe(32)
        now = _utcnow()
        doc = {
            "_id": state,
            "tenant_key": str(tenant_key).strip(),
            "app_id": str(app_id).strip(),
            "purpose": purpose,
            "created_at": now,
            "expires_at": now + timedelta(seconds=int(ttl_seconds)),
            "consumed_at": None,
            **{k: v for k, v in extra.items() if v is not None},
        }
        col = get_oauth_states_collection()
        await col.insert_one(doc)
        logger.debug("🎫 Đã phát hành OAuth state cho tenant '%s' app '%s' (%s)", tenant_key, app_id, purpose)
        return state

    async def consume(self, state: Optional[str]) -> Dict[str, Any]:
        """
        Xác nhận và dùng một lần. Trả về document state (`tenant_key`, `app_id`, `purpose`).

        Dùng `find_one_and_update` thay vì `find_one` + `update_one` để hai callback
        song song trên cùng một state chỉ có một bên lấy được token.
        """
        if not state or not str(state).strip():
            raise OAuthStateError("Thiếu tham số `state` — không xác định được phiên ủy quyền.", state)

        await self.ensure_ttl_index()
        col = get_oauth_states_collection()
        now = _utcnow()
        doc = await col.find_one_and_update(
            {"_id": str(state).strip(), "consumed_at": None},
            {"$set": {"consumed_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            raise OAuthStateError(
                "OAuth state không hợp lệ hoặc đã được sử dụng. Hãy bắt đầu lại từ trang đăng nhập.",
                state,
            )

        expires_at = doc.get("expires_at")
        if isinstance(expires_at, datetime):
            # BSON chỉ lưu UTC mà không kèm tzinfo, nên Motor trả về datetime naive.
            # So naive với aware sẽ raise TypeError — tức mọi callback hợp lệ đều chết 500
            # ở bước kiểm hạn, nên chuẩn hóa về UTC có múi giờ trước khi so sánh.
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < now:
                raise OAuthStateError(
                    f"OAuth state đã hết hạn sau {STATE_TTL_SECONDS // 60} phút. Vui lòng ủy quyền lại.",
                    state,
                )

        tenant_key = doc.get("tenant_key")
        app_id = doc.get("app_id")
        if not tenant_key or not app_id:
            raise OAuthStateError(
                "OAuth state thiếu thông tin tenant/app — không thể xác định App đã ủy quyền.",
                state,
            )
        return doc

    async def peek(self, state: str) -> Optional[Dict[str, Any]]:
        """Đọc state mà không đánh dấu đã dùng (chỉ phục vụ log/debug)."""
        if not state:
            return None
        col = get_oauth_states_collection()
        try:
            return await col.find_one({"_id": str(state).strip()})
        except Exception as exc:  # pragma: no cover
            logger.debug("Không đọc được oauth state: %s", exc)
            return None


oauth_state_service = OAuthStateService()
"""Singleton store state OAuth."""

__all__ = [
    "OAuthStateError",
    "OAuthStateService",
    "oauth_state_service",
    "STATE_TTL_SECONDS",
]
