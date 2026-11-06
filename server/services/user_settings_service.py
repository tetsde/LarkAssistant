"""
HiLark - User Settings & BYOK Service
=====================================
Vị trí: server/services/user_settings_service.py

Chịu trách nhiệm:
  1. Mã hóa & giải mã an toàn AES-256 cho khóa API cá nhân (Fernet key derivation).
  2. Ping test độ sống còn và đo độ trễ (latency) của Gemini API Key.
  3. Quản lý lưu trữ/truy vấn cấu hình người dùng (MongoDB collection 'user_settings').
  4. Thuật toán giải quyết Key 3 tầng (Key Resolution Hierarchy):
       User BYOK -> Project/Scope BYOK -> System Default Key
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from typing import Any, Dict, Optional, Tuple

import httpx
from cryptography.fernet import Fernet

from core.config import settings
from database.db import get_user_settings_collection
from database.scoped_query import get_current_tenant_key
from models.memory import get_vietnam_now_iso
from models.user_settings import UserSettingsRecord

logger = logging.getLogger("hilark.services.user_settings")


def _derive_fernet_key(secret: str) -> bytes:
    """Sinh khóa Fernet 32-bytes an toàn từ chuỗi bí mật bằng SHA-256."""
    key_hash = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(key_hash)


class UserSettingsService:
    """Quản trị cấu hình người dùng, bảo mật API Key và phân giải BYOK."""

    def __init__(self, secret_key: Optional[str] = None):
        raw_secret = secret_key or getattr(settings, "ENCRYPTION_SECRET_KEY", "hilark-secret-key-32bytes-aes256!!")
        self._fernet = Fernet(_derive_fernet_key(raw_secret))

    def encrypt_key(self, raw_key: str) -> str:
        """Mã hóa chuỗi API key thành token mã hóa an toàn."""
        if not raw_key or not raw_key.strip():
            return ""
        encrypted_bytes = self._fernet.encrypt(raw_key.strip().encode("utf-8"))
        return encrypted_bytes.decode("utf-8")

    def decrypt_key(self, cipher_text: str) -> str:
        """Giải mã token mã hóa để lấy lại API key nguyên bản."""
        if not cipher_text or not cipher_text.strip():
            return ""
        try:
            decrypted_bytes = self._fernet.decrypt(cipher_text.strip().encode("utf-8"))
            return decrypted_bytes.decode("utf-8")
        except Exception as e:
            logger.error(f"Lỗi giải mã API key: {e}")
            return ""

    @staticmethod
    def mask_key(raw_key: Optional[str]) -> str:
        """Ẩn phần thân của key chỉ chừa đầu và đuôi (VD: AIzaSy••••••••1234)."""
        if not raw_key:
            return ""
        s = raw_key.strip()
        if len(s) <= 10:
            return s
        return f"{s[:6]}...{s[-4:]}"

    mask_api_key = mask_key

    async def test_llm_connection(
        self,
        raw_key: str,
        provider: str = "google",
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
    ) -> Tuple[bool, str, float]:
        """
        Kiểm tra trực tiếp kết nối với LLM Provider (Google, ChatGPT/OpenAI, Anthropic, Custom) kèm timeout.
        Trả về: (thành_công, thông_báo, độ_trễ_ms)
        """
        if not raw_key or not raw_key.strip():
            return False, "API Key không được để trống.", 0.0

        key = raw_key.strip()
        provider_norm = (provider or "google").strip().lower()
        timeout_val = float(timeout) if timeout and float(timeout) > 0 else 30.0

        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=timeout_val) as client:
                if provider_norm == "google":
                    model_target = model or "gemini-flash-latest"
                    b_url = (base_url or "https://generativelanguage.googleapis.com").rstrip("/")
                    test_url = f"{b_url}/v1beta/models/{model_target}:generateContent?key={key}"
                    payload = {
                        "contents": [{"parts": [{"text": "ping"}]}],
                        "generationConfig": {"maxOutputTokens": 5, "thinkingConfig": {"thinkingBudget": 0}},
                    }
                    res = await client.post(test_url, json=payload)
                elif provider_norm in ("openai", "chatgpt"):
                    model_target = model or "gpt-4o-mini"
                    b_url = (base_url or "https://api.openai.com/v1").rstrip("/")
                    test_url = f"{b_url}/chat/completions"
                    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                    payload = {
                        "model": model_target,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 5,
                    }
                    res = await client.post(test_url, headers=headers, json=payload)
                elif provider_norm == "anthropic":
                    model_target = model or "claude-3-5-sonnet-20241022"
                    b_url = (base_url or "https://api.anthropic.com/v1").rstrip("/")
                    if not b_url.endswith("/v1"):
                        b_url = f"{b_url}/v1"
                    test_url = f"{b_url}/messages"
                    headers = {
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    }
                    payload = {
                        "model": model_target,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 5,
                    }
                    res = await client.post(test_url, headers=headers, json=payload)
                else:  # "custom" / other OpenAI-compatible
                    model_target = model or "gpt-3.5-turbo"
                    b_url = (base_url or "https://api.openai.com/v1").rstrip("/")
                    if not b_url.endswith("/chat/completions"):
                        test_url = f"{b_url}/chat/completions"
                    else:
                        test_url = b_url
                    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                    payload = {
                        "model": model_target,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 5,
                    }
                    res = await client.post(test_url, headers=headers, json=payload)

                latency_ms = round((time.time() - start_time) * 1000, 2)
                if res.status_code == 200:
                    provider_display = {
                        "google": "Google Gemini",
                        "openai": "ChatGPT / OpenAI",
                        "chatgpt": "ChatGPT / OpenAI",
                        "anthropic": "Anthropic Claude",
                        "custom": "Custom Provider",
                    }.get(provider_norm, provider_norm.upper())
                    return True, f"Kết nối {provider_display} thành công (độ trễ {latency_ms} ms)", latency_ms

                try:
                    err_json = res.json()
                    err_msg = (
                        err_json.get("error", {}).get("message")
                        if isinstance(err_json.get("error"), dict)
                        else str(err_json.get("error") or res.text)
                    )
                except Exception:
                    err_msg = res.text

                return False, f"Provider từ chối ({res.status_code}): {err_msg[:120]}", latency_ms

        except httpx.TimeoutException:
            return False, f"Kết nối đến {provider_norm.upper()} quá thời gian chờ (Timeout {timeout_val}s).", 0.0
        except Exception as e:
            return False, f"Lỗi kết nối kiểm tra: {str(e)}", 0.0

    async def test_gemini_key(self, raw_key: str) -> Tuple[bool, str, float]:
        """Tương thích ngược kiểm tra Gemini API Key."""
        return await self.test_llm_connection(raw_key=raw_key, provider="google")

    async def get_user_settings(self, open_id: str, tenant_key: Optional[str] = None) -> Optional[UserSettingsRecord]:
        """Lấy cấu hình theo user; nếu có tenant thì dùng khóa kép user + tenant."""
        if not open_id:
            return None
        coll = get_user_settings_collection()
        query = {"open_id": open_id}
        if tenant_key:
            query["tenant_key"] = tenant_key
        doc = await coll.find_one(query)
        if not doc:
            return None
        return UserSettingsRecord(**doc)

    async def save_user_settings(
        self,
        open_id: str,
        is_byok_enabled: bool = False,
        raw_gemini_key: Optional[str] = None,
        digest_schedule_time: str = "18:00",
        hitl_mode_enabled: bool = True,
        user_name: Optional[str] = None,
        llm_provider: str = "google",
        llm_base_url: Optional[str] = None,
        llm_model: Optional[str] = None,
        llm_timeout: float = 60.0,
        policy_sync_interval_seconds: Optional[int] = None,
        tenant_key: Optional[str] = None,
    ) -> UserSettingsRecord:
        """Lưu hoặc cập nhật cấu hình người dùng vào MongoDB."""
        normalized_digest_time = (digest_schedule_time or "18:00").strip()
        try:
            hour, minute = normalized_digest_time.split(":", 1)
            if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
                raise ValueError
            normalized_digest_time = f"{int(hour):02d}:{int(minute):02d}"
        except (TypeError, ValueError):
            raise ValueError("digest_schedule_time phải có định dạng HH:MM hợp lệ")

        coll = get_user_settings_collection()
        existing = await self.get_user_settings(open_id, tenant_key=tenant_key)

        encrypted_key = None
        masked_key = None

        if is_byok_enabled and raw_gemini_key and raw_gemini_key.strip():
            encrypted_key = self.encrypt_key(raw_gemini_key)
            masked_key = self.mask_key(raw_gemini_key)
        elif is_byok_enabled and existing and existing.encrypted_gemini_api_key:
            # Giữ nguyên key cũ nếu không truyền key mới
            encrypted_key = existing.encrypted_gemini_api_key
            masked_key = existing.masked_gemini_api_key

        now_iso = get_vietnam_now_iso()
        record = UserSettingsRecord(
            open_id=open_id,
            tenant_key=tenant_key or (existing.tenant_key if existing else None),
            user_name=user_name or (existing.user_name if existing else None),
            is_byok_enabled=is_byok_enabled,
            llm_provider=llm_provider or (existing.llm_provider if existing else "google"),
            encrypted_gemini_api_key=encrypted_key,
            masked_gemini_api_key=masked_key,
            llm_base_url=llm_base_url or (existing.llm_base_url if existing else None),
            llm_model=llm_model or (existing.llm_model if existing else None),
            llm_timeout=llm_timeout if llm_timeout is not None else (existing.llm_timeout if existing else 60.0),
            digest_schedule_time=normalized_digest_time,
            hitl_mode_enabled=hitl_mode_enabled,
            policy_sync_interval_seconds=int(policy_sync_interval_seconds) if policy_sync_interval_seconds is not None else (getattr(existing, "policy_sync_interval_seconds", 3600) if existing else 3600),
            created_at=existing.created_at if existing else now_iso,
            updated_at=now_iso,
        )

        user_query = {"open_id": open_id}
        if record.tenant_key:
            user_query["tenant_key"] = record.tenant_key
        await coll.update_one(
            user_query,
            {"$set": record.to_dict()},
            upsert=True,
        )
        if record.tenant_key and policy_sync_interval_seconds is not None:
            try:
                from database.db import get_tenants_collection
                await get_tenants_collection().update_one(
                    {"tenant_key": record.tenant_key},
                    {"$set": {"policy_sync_interval_seconds": int(policy_sync_interval_seconds)}},
                )
            except Exception as t_up_err:
                logger.debug(f"Không thể cập nhật policy_sync_interval_seconds vào tenant: {t_up_err}")
        logger.info(f"Đã lưu cấu hình người dùng cho open_id={open_id} (BYOK={is_byok_enabled})")
        return record

    async def resolve_effective_llm_key(
        self,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        request_api_key: Optional[str] = None,
        open_id: Optional[str] = None,
        tenant_key: Optional[str] = None,
    ) -> str:
        """
        Phân giải API key theo thứ tự:
          1. User BYOK nếu được bật và giải mã thành công.
          2. System Default từ settings/.env.

        chat_id và request_api_key được giữ để tương thích ngược,
        nhưng không tham gia lựa chọn key.
        """
        eff_tenant = tenant_key or get_current_tenant_key()
        target_user = user_id or open_id

        if target_user:
            user_settings = await self.get_user_settings(
                target_user, tenant_key=eff_tenant
            )
            if (
                user_settings
                and user_settings.is_byok_enabled
                and user_settings.encrypted_gemini_api_key
            ):
                decrypted = self.decrypt_key(
                    user_settings.encrypted_gemini_api_key
                )
                if decrypted:
                    logger.info(
                        f"[BYOK] Sử dụng User BYOK: {target_user} "
                        f"(tenant={eff_tenant})"
                    )
                    return decrypted

        return settings.GEMINI_API_KEY or settings.gemini_api or ""

    async def resolve_effective_llm_client(
        self,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        open_id: Optional[str] = None,
        request_api_key: Optional[str] = None,
        tenant_key: Optional[str] = None,
    ):
        """
        Phân giải và khởi tạo LLMClient hoàn chỉnh theo cấu hình cá nhân hóa của User hoặc Hệ thống:
          - Nếu User bật BYOK: Áp dụng nhà cung cấp (provider), model, base_url, timeout và key giải mã.
          - Nếu không: Sử dụng LLMClient mặc định của hệ thống.
        """
        from services.ai.gemini_client import LLMClient, llm_client

        eff_tenant = tenant_key or get_current_tenant_key()

        target_user = user_id or open_id
        if target_user:
            settings_rec = await self.get_user_settings(target_user, tenant_key=eff_tenant)
            if settings_rec and settings_rec.is_byok_enabled and settings_rec.encrypted_gemini_api_key:
                user_api_key = self.decrypt_key(settings_rec.encrypted_gemini_api_key)
                if user_api_key:
                    default_models = [settings_rec.llm_model] if settings_rec.llm_model else None
                    logger.info(
                        f"🤖 [BYOK CLIENT] Sử dụng cấu hình LLM riêng của User {target_user} (tenant={eff_tenant}): "
                        f"provider={settings_rec.llm_provider}, model={settings_rec.llm_model or 'default'}"
                    )
                    return LLMClient(
                        api_key=user_api_key,
                        provider=settings_rec.llm_provider or "google",
                        base_url=settings_rec.llm_base_url,
                        timeout=settings_rec.llm_timeout or 60.0,
                        default_models=default_models,
                    )

        # Không sử dụng Project BYOK hoặc Request Override.
        # Nếu User BYOK không hợp lệ, dùng client mặc định của hệ thống.
        return llm_client


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
    key = await user_settings_service.resolve_effective_llm_key(
        user_id=user_id,
        chat_id=chat_id,
        request_api_key=request_api_key,
        open_id=open_id,
        tenant_key=tenant_key,
    )
    sys_key = settings.GEMINI_API_KEY or settings.gemini_api or ""
    is_byok = bool(key and key != sys_key)
    return key, is_byok


__all__ = [
    "UserSettingsService",
    "user_settings_service",
    "resolve_effective_llm_key",
]
