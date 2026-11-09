"""
HiLark - User Settings & BYOK Service (Thin Compatibility Facade)
=================================================================
Vị trí: server/services/user_settings_service.py

Facade tương thích ngược ủy quyền 100% logic mã hóa, kiểm tra kết nối,
lưu trữ/caching MongoDB và phân giải cấu hình AI (Fail-Closed BYOK)
sang `services.ai.ai_config_manager`.
"""

from __future__ import annotations

from typing import Optional, Tuple

from database.scoped_query import get_current_tenant_key
from models.user_settings import UserSettingsRecord
from services.ai.ai_config_manager import AIConfigManager, _UNSET, ai_config_manager


class UserSettingsService:
    """Thin facade ủy quyền quản trị cấu hình người dùng & BYOK sang AIConfigManager."""

    def __init__(self, secret_key: Optional[str] = None):
        if secret_key is not None:
            self._manager = AIConfigManager(secret_key=secret_key)
        else:
            self._manager = ai_config_manager

    def encrypt_key(self, raw_key: str) -> str:
        """Mã hóa chuỗi API key thành token mã hóa an toàn."""
        return self._manager.encrypt_key(raw_key)

    def decrypt_key(self, cipher_text: str) -> str:
        """Giải mã token mã hóa để lấy lại API key nguyên bản."""
        return self._manager.decrypt_key(cipher_text)

    def decrypt_key_strict(
        self,
        cipher_text: Optional[str],
        *,
        tenant_key: Optional[str] = None,
        provider: Optional[str] = None,
        service_type: str = "llm",
    ) -> str:
        """Giải mã token mã hóa ở chế độ Fail-Closed (ném BYOKConfigurationError khi rỗng/lỗi)."""
        return self._manager.decrypt_key_strict(
            cipher_text,
            tenant_key=tenant_key,
            provider=provider,
            service_type=service_type,
        )

    @staticmethod
    def mask_key(raw_key: Optional[str]) -> str:
        """Ẩn phần thân của key chỉ chừa đầu và đuôi (VD: AIzaSy...1234)."""
        return ai_config_manager.mask_key(raw_key)

    mask_api_key = mask_key

    def invalidate_cache(
        self,
        tenant_key: Optional[str] = None,
        open_id: Optional[str] = None,
    ) -> int:
        """Xóa cache cấu hình AI theo tenant_key và/hoặc open_id."""
        return self._manager.invalidate_cache(
            tenant_key=tenant_key,
            open_id=open_id,
        )

    invalidate = invalidate_cache

    async def test_llm_connection(
        self,
        raw_key: str,
        provider: str = "google",
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
    ) -> Tuple[bool, str, float]:
        """Kiểm tra trực tiếp kết nối với LLM/JEV Provider kèm timeout."""
        return await self._manager.test_llm_connection(
            raw_key=raw_key,
            provider=provider,
            base_url=base_url,
            model=model,
            timeout=timeout,
        )

    async def get_user_settings(
        self,
        open_id: str,
        tenant_key: Optional[str] = None,
        bypass_cache: bool = False,
    ) -> Optional[UserSettingsRecord]:
        """Lấy cấu hình theo user; nếu có tenant thì dùng khóa kép user + tenant."""
        return await self._manager.get_user_settings(
            open_id,
            tenant_key=tenant_key,
            bypass_cache=bypass_cache,
        )

    get_settings = get_user_settings

    async def save_user_settings(
        self,
        open_id: str,
        is_byok_enabled: Optional[bool] = None,
        raw_llm_key: Optional[str] = None,
        digest_schedule_time: Optional[str] = None,
        hitl_mode_enabled: Optional[bool] = None,
        user_name: Optional[str] = None,
        llm_provider: Optional[str] = None,
        llm_base_url: Optional[str] = _UNSET,
        llm_model: Optional[str] = _UNSET,
        llm_timeout: Optional[float] = None,
        policy_sync_interval_seconds: Optional[int] = None,
        tenant_key: Optional[str] = None,
        is_jev_byok_enabled: Optional[bool] = None,
        raw_jev_key: Optional[str] = None,
    ) -> UserSettingsRecord:
        """Lưu hoặc cập nhật cấu hình người dùng thông qua AIConfigManager."""
        return await self._manager.save_user_settings(
            open_id=open_id,
            is_byok_enabled=is_byok_enabled,
            raw_llm_key=raw_llm_key,
            digest_schedule_time=digest_schedule_time,
            hitl_mode_enabled=hitl_mode_enabled,
            user_name=user_name,
            llm_provider=llm_provider,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            llm_timeout=llm_timeout,
            policy_sync_interval_seconds=policy_sync_interval_seconds,
            tenant_key=tenant_key,
            is_jev_byok_enabled=is_jev_byok_enabled,
            raw_jev_key=raw_jev_key,
        )

    save_settings = save_user_settings

    async def resolve_effective_llm_key(
        self,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        request_api_key: Optional[str] = None,
        open_id: Optional[str] = None,
        tenant_key: Optional[str] = None,
    ) -> str:
        """
        Phân giải API key hiệu lực qua AIConfigManager.

        chat_id và request_api_key được giữ để tương thích ngược chữ ký hàm,
        nhưng không tham gia lựa chọn key.
        """
        eff_tenant = tenant_key or get_current_tenant_key()
        target_user = user_id or open_id

        if target_user:
            rec = await self.get_user_settings(target_user, tenant_key=eff_tenant)
            if rec is not None:
                key, _ = await self._manager.resolve_llm_key(
                    tenant_key=eff_tenant,
                    open_id=target_user,
                    config_record=rec,
                )
                return key

        key, _ = await self._manager.resolve_llm_key(
            tenant_key=eff_tenant,
            open_id=target_user,
        )
        return key

    async def resolve_effective_llm_client(
        self,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        open_id: Optional[str] = None,
        request_api_key: Optional[str] = None,
        tenant_key: Optional[str] = None,
    ):
        """
        Phân giải và khởi tạo LLMClient hoàn chỉnh qua AIConfigManager.

        chat_id và request_api_key được giữ để tương thích ngược chữ ký hàm,
        nhưng không tham gia lựa chọn client.
        """
        eff_tenant = tenant_key or get_current_tenant_key()
        target_user = user_id or open_id

        if target_user:
            rec = await self.get_user_settings(target_user, tenant_key=eff_tenant)
            if rec is not None:
                return await self._manager.resolve_llm_client(
                    tenant_key=eff_tenant,
                    open_id=target_user,
                    config_record=rec,
                )

        return await self._manager.resolve_llm_client(
            tenant_key=eff_tenant,
            open_id=target_user,
        )

    async def resolve_effective_jev_key(
        self,
        tenant_key: Optional[str] = None,
        open_id: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """Phân giải JEV API Key hiệu lực qua AIConfigManager."""
        return await self._manager.resolve_jev_key(
            tenant_key=tenant_key,
            open_id=open_id,
        )


user_settings_service = UserSettingsService()
user_settings_service.get_settings = user_settings_service.get_user_settings  # type: ignore
user_settings_service.save_settings = user_settings_service.save_user_settings  # type: ignore


async def resolve_effective_llm_key(
    open_id: Optional[str] = None,
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    request_api_key: Optional[str] = None,
    tenant_key: Optional[str] = None,
) -> Tuple[str, bool]:
    """
    Hàm phân giải khóa cấp module: trả về bộ (effective_key, is_byok).
    """
    eff_tenant = tenant_key or get_current_tenant_key()
    target_user = user_id or open_id

    if target_user:
        rec = await user_settings_service.get_user_settings(
            target_user, tenant_key=eff_tenant
        )
        if rec is not None:
            return await user_settings_service._manager.resolve_llm_key(
                tenant_key=eff_tenant,
                open_id=target_user,
                config_record=rec,
            )

    return await user_settings_service._manager.resolve_llm_key(
        tenant_key=eff_tenant,
        open_id=target_user,
    )


__all__ = [
    "UserSettingsService",
    "user_settings_service",
    "resolve_effective_llm_key",
]
