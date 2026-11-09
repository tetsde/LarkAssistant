"""
HiLark - Centralized AI Config & BYOK Manager
=============================================
Vị trí: server/services/ai/ai_config_manager.py

Nguồn chân lý duy nhất quản lý toàn bộ cấu hình AI & BYOK:
  1. Mã hóa / giải mã AES-256 Fernet (tương thích 100% ENCRYPTION_SECRET_KEY) & masking key.
  2. Cache cấu hình trong RAM với TTL 60 giây và cơ chế invalidation theo tenant / user.
  3. Truy vấn & phân giải cấu hình đa tầng Fail-Closed (bật BYOK nhưng thiếu/lỗi key -> raise BYOKConfigurationError).
  4. Lưu cấu hình thống nhất kèm dọn rác trường cũ (llm_base_url, llm_model) khi đổi provider hoặc xóa trên UI.
  5. Kiểm tra kết nối trực tiếp tới Google Gemini, OpenAI/ChatGPT, Anthropic, Custom và JEV System 1.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from cryptography.fernet import Fernet

import database.db as _db_module
from core.config import settings
from core.tenant_errors import BYOKConfigurationError
from database.db import get_user_settings_collection
from database.scoped_query import get_current_tenant_key
from models.memory import get_vietnam_now_iso
from models.user_settings import UserSettingsRecord
from services.ai.model_catalog import (
    DEFAULT_GEMINI_MODEL,
    get_default_model,
    normalize_provider,
)

logger = logging.getLogger("hilark.services.ai.config_manager")

_DEFAULT_ENCRYPTION_SECRET = "hilark-secret-key-32bytes-aes256!!"
_UNSET: Any = object()
_ORIG_GET_USER_SETTINGS_COLLECTION = get_user_settings_collection


def _derive_fernet_key(secret: str) -> bytes:
    """Sinh khóa Fernet 32-bytes an toàn từ chuỗi bí mật bằng SHA-256."""
    key_hash = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(key_hash)


async def _find_one_sorted(
    coll: Any,
    query: Dict[str, Any],
    sort: Optional[List[Tuple[str, int]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Thực thi `find_one` kèm `sort`; tự động fallback nếu collection giả trong unit test
    không hỗ trợ tham số `sort`.
    """
    if not sort:
        return await coll.find_one(query)
    try:
        return await coll.find_one(query, sort=sort)
    except TypeError:
        return await coll.find_one(query)


def _get_user_settings_coll() -> Any:
    """Lấy collection `user_settings`, tôn trọng patch trên cả module này lẫn `database.db`."""
    if get_user_settings_collection is not _ORIG_GET_USER_SETTINGS_COLLECTION:
        return get_user_settings_collection()
    return _db_module.get_user_settings_collection()


def _to_record(doc: Any) -> Optional[UserSettingsRecord]:
    """Chuyển document MongoDB (hoặc UserSettingsRecord) thành UserSettingsRecord."""
    if doc is None:
        return None
    if isinstance(doc, UserSettingsRecord):
        return doc
    return UserSettingsRecord(**doc)


class AIConfigManager:
    """Trình quản lý tập trung cấu hình AI, mã hóa BYOK, cache TTL và phân giải Fail-Closed."""

    def __init__(
        self,
        secret_key: Optional[str] = None,
        cache_ttl_seconds: float = 60.0,
    ) -> None:
        raw_secret = (
            secret_key
            or getattr(settings, "ENCRYPTION_SECRET_KEY", None)
            or _DEFAULT_ENCRYPTION_SECRET
        )
        self._fernet = Fernet(_derive_fernet_key(raw_secret))
        self._cache_ttl_seconds: float = float(cache_ttl_seconds)
        self._cache: Dict[
            Tuple[Optional[str], Optional[str]],
            Tuple[Optional[UserSettingsRecord], float],
        ] = {}
        self._exact_only_keys: Set[Tuple[Optional[str], Optional[str]]] = set()

    # --------------------------------------------------------------------------
    # 1. CRYPTO AES-256 FERNET & MASKING
    # --------------------------------------------------------------------------

    def encrypt_key(self, raw_key: str) -> str:
        """Mã hóa chuỗi API key thành token Fernet; trả về '' nếu rỗng."""
        if not raw_key or not raw_key.strip():
            return ""
        encrypted_bytes = self._fernet.encrypt(raw_key.strip().encode("utf-8"))
        return encrypted_bytes.decode("utf-8")

    def decrypt_key(self, cipher_text: str) -> str:
        """Giải mã an toàn cho caller non-BYOK (VD: Lark credentials); trả về '' nếu lỗi."""
        if not cipher_text or not cipher_text.strip():
            return ""
        try:
            decrypted_bytes = self._fernet.decrypt(cipher_text.strip().encode("utf-8"))
            return decrypted_bytes.decode("utf-8")
        except Exception as e:
            logger.error(f"Lỗi giải mã API key: {e}")
            return ""

    def decrypt_key_strict(
        self,
        cipher_text: Optional[str],
        *,
        tenant_key: Optional[str] = None,
        provider: Optional[str] = None,
        service_type: str = "llm",
    ) -> str:
        """
        Giải mã nghiêm ngặt (Fail-Closed) cho BYOK:
        thiếu cipher_text, lỗi giải mã hoặc kết quả rỗng -> raise BYOKConfigurationError.
        """
        service_label = (service_type or "llm").strip().lower()
        provider_label = (provider or "unknown").strip() or "unknown"
        tenant_label = (tenant_key or "").strip() or "chưa rõ"

        if not cipher_text or not cipher_text.strip():
            raise BYOKConfigurationError(
                f"BYOK cho dịch vụ {service_label.upper()} đã bật nhưng thiếu API key đã mã hóa "
                f"(tenant='{tenant_label}', provider='{provider_label}', service_type='{service_label}'). "
                "Vui lòng nhập lại API key trong phần cài đặt BYOK.",
                tenant_key=tenant_key,
                provider=provider,
                service_type=service_label,
            )

        try:
            decrypted_bytes = self._fernet.decrypt(cipher_text.strip().encode("utf-8"))
            decrypted = decrypted_bytes.decode("utf-8").strip()
        except Exception as e:
            logger.error(
                f"[BYOK] Lỗi giải mã key (tenant={tenant_label}, provider={provider_label}, "
                f"service_type={service_label}): {e}"
            )
            raise BYOKConfigurationError(
                f"Không thể giải mã API key BYOK cho dịch vụ {service_label.upper()} "
                f"(tenant='{tenant_label}', provider='{provider_label}', service_type='{service_label}'). "
                "Vui lòng cập nhật lại API key.",
                tenant_key=tenant_key,
                provider=provider,
                service_type=service_label,
            ) from e

        if not decrypted:
            raise BYOKConfigurationError(
                f"API key BYOK sau giải mã bị rỗng cho dịch vụ {service_label.upper()} "
                f"(tenant='{tenant_label}', provider='{provider_label}', service_type='{service_label}'). "
                "Vui lòng nhập lại API key hợp lệ.",
                tenant_key=tenant_key,
                provider=provider,
                service_type=service_label,
            )

        return decrypted

    @staticmethod
    def mask_key(raw_key: Optional[str]) -> str:
        """Che giấu phần giữa của API key (<= 10 ký tự giữ nguyên, dài hơn -> 6 đầu ... 4 cuối)."""
        if not raw_key:
            return ""
        s = raw_key.strip()
        if len(s) <= 10:
            return s
        return f"{s[:6]}...{s[-4:]}"

    mask_api_key = mask_key

    # --------------------------------------------------------------------------
    # 2. RAM CACHE TTL & INVALIDATION
    # --------------------------------------------------------------------------

    def _store_cache(
        self,
        cache_key: Tuple[Optional[str], Optional[str]],
        record: Optional[UserSettingsRecord],
        *,
        exact_only: bool = False,
    ) -> None:
        if self._cache_ttl_seconds <= 0:
            return
        self._cache[cache_key] = (record, time.monotonic() + self._cache_ttl_seconds)
        if exact_only:
            self._exact_only_keys.add(cache_key)
        else:
            self._exact_only_keys.discard(cache_key)

    def invalidate(
        self,
        tenant_key: Optional[str] = None,
        open_id: Optional[str] = None,
    ) -> int:
        """
        Xóa cache cấu hình AI theo `tenant_key` và/hoặc `open_id`.
        Trả về số entry đã xóa.
        """
        clean_tenant = (tenant_key or "").strip() or None
        clean_open_id = (open_id or "").strip() or None

        if clean_tenant is None and clean_open_id is None:
            removed = len(self._cache)
            self._cache.clear()
            self._exact_only_keys.clear()
            return removed

        if clean_tenant is not None:
            keys_to_delete = [
                k
                for k in list(self._cache.keys())
                if k[0] == clean_tenant
                or (clean_open_id is not None and k == (None, clean_open_id))
            ]
        else:
            keys_to_delete = [
                k for k in list(self._cache.keys()) if k[1] == clean_open_id
            ]

        for k in keys_to_delete:
            self._cache.pop(k, None)
            self._exact_only_keys.discard(k)

        return len(keys_to_delete)

    invalidate_cache = invalidate

    # --------------------------------------------------------------------------
    # 3. TRUY VẤN CẤU HÌNH (GET_USER_SETTINGS & RESOLVE_AI_CONFIG)
    # --------------------------------------------------------------------------

    async def get_user_settings(
        self,
        open_id: str,
        tenant_key: Optional[str] = None,
        bypass_cache: bool = False,
    ) -> Optional[UserSettingsRecord]:
        """Lấy cấu hình riêng của user; nếu có tenant_key thì khóa theo (open_id, tenant_key)."""
        clean_open_id = (open_id or "").strip()
        if not clean_open_id:
            return None
        clean_tenant = (tenant_key or "").strip() or None
        cache_key = (clean_tenant, clean_open_id)

        if not bypass_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                cached_record, expires_at = cached
                if expires_at > time.monotonic():
                    # Nếu entry này được lưu bởi resolve_ai_config qua fallback tenant (open_id khác),
                    # user này không có bản ghi riêng.
                    if cached_record is not None and cached_record.open_id != clean_open_id:
                        return None
                    return cached_record
                self._cache.pop(cache_key, None)
                self._exact_only_keys.discard(cache_key)

        coll = _get_user_settings_coll()
        if clean_tenant:
            doc = await coll.find_one({"open_id": clean_open_id, "tenant_key": clean_tenant})
        else:
            doc = await _find_one_sorted(
                coll,
                {"open_id": clean_open_id},
                sort=[("updated_at", -1)],
            )

        record = _to_record(doc)
        self._store_cache(cache_key, record, exact_only=(record is None and bool(clean_tenant)))
        return record

    async def resolve_ai_config(
        self,
        tenant_key: Optional[str] = None,
        open_id: Optional[str] = None,
        bypass_cache: bool = False,
    ) -> Optional[UserSettingsRecord]:
        """
        Phân giải cấu hình AI hiệu lực theo tenant/user:
          - Cả tenant_key lẫn open_id đều trống -> trả None (tuyệt đối không đọc document mồ côi).
          - Có cả 2 -> tìm exact (open_id, tenant_key) trước, sau đó fallback theo tenant_key mới nhất.
          - Chỉ có tenant_key -> tìm theo tenant_key mới nhất.
          - Chỉ có open_id -> tìm theo open_id mới nhất.
        """
        eff_tenant = ((tenant_key or "").strip() or (get_current_tenant_key() or "").strip()) or None
        clean_open_id = (open_id or "").strip() or None

        if eff_tenant is None and clean_open_id is None:
            return None

        cache_key = (eff_tenant, clean_open_id)
        exact_already_missed = False

        if not bypass_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                cached_record, expires_at = cached
                if expires_at > time.monotonic():
                    if cached_record is not None or cache_key not in self._exact_only_keys:
                        return cached_record
                    exact_already_missed = True
                else:
                    self._cache.pop(cache_key, None)
                    self._exact_only_keys.discard(cache_key)

        coll = _get_user_settings_coll()
        doc = None

        if eff_tenant and clean_open_id:
            if not exact_already_missed:
                doc = await coll.find_one({"open_id": clean_open_id, "tenant_key": eff_tenant})
            if not doc:
                doc = await _find_one_sorted(
                    coll,
                    {"tenant_key": eff_tenant},
                    sort=[("updated_at", -1)],
                )
        elif eff_tenant:
            doc = await _find_one_sorted(
                coll,
                {"tenant_key": eff_tenant},
                sort=[("updated_at", -1)],
            )
        else:
            doc = await _find_one_sorted(
                coll,
                {"open_id": clean_open_id},
                sort=[("updated_at", -1)],
            )

        record = _to_record(doc)
        self._store_cache(cache_key, record, exact_only=False)
        return record

    # --------------------------------------------------------------------------
    # 4. LƯU CẤU HÌNH THỐNG NHẤT & DỌN RÁC PROVIDER
    # --------------------------------------------------------------------------

    async def save_config(
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
        """Lưu hoặc cập nhật cấu hình AI/BYOK vào MongoDB và tự động làm mới cache."""
        clean_open_id = (open_id or "").strip()
        if not clean_open_id:
            raise ValueError("open_id không được để trống")

        clean_tenant = (tenant_key or "").strip() or None
        existing = await self.get_user_settings(
            clean_open_id,
            tenant_key=clean_tenant,
            bypass_cache=True,
        )

        # Validate digest_schedule_time dạng HH:MM (00:00..23:59)
        if digest_schedule_time is None:
            raw_digest_time = (existing.digest_schedule_time if existing else None) or "18:00"
        else:
            raw_digest_time = digest_schedule_time

        normalized_digest_time = str(raw_digest_time).strip()
        try:
            hour_str, minute_str = normalized_digest_time.split(":", 1)
            if not (hour_str.isdigit() and minute_str.isdigit()):
                raise ValueError
            hour_val, minute_val = int(hour_str), int(minute_str)
            if not (0 <= hour_val <= 23 and 0 <= minute_val <= 59):
                raise ValueError
            normalized_digest_time = f"{hour_val:02d}:{minute_val:02d}"
        except (AttributeError, TypeError, ValueError):
            raise ValueError("digest_schedule_time phải có định dạng HH:MM hợp lệ")

        eff_provider = normalize_provider(
            llm_provider if llm_provider is not None else (existing.llm_provider if existing else "google")
        )
        provider_changed = bool(
            existing and normalize_provider(existing.llm_provider) != eff_provider
        )

        # --- Xử lý LLM BYOK ---
        eff_byok = (
            existing.is_byok_enabled
            if (is_byok_enabled is None and existing)
            else bool(is_byok_enabled)
        )
        encrypted_key: Optional[str] = None
        masked_key: Optional[str] = None

        if eff_byok:
            if raw_llm_key and raw_llm_key.strip():
                encrypted_key = self.encrypt_key(raw_llm_key)
                masked_key = self.mask_key(raw_llm_key)
            elif not provider_changed and existing and existing.encrypted_llm_api_key:
                encrypted_key = existing.encrypted_llm_api_key
                masked_key = existing.masked_llm_api_key
            else:
                raise BYOKConfigurationError(
                    "Bạn đã bật BYOK LLM nhưng chưa nhập API Key cho nhà cung cấp đã chọn.",
                    tenant_key=clean_tenant,
                    provider=eff_provider,
                    service_type="llm",
                )

        # --- Xử lý JEV BYOK ---
        eff_jev_byok = (
            existing.is_jev_byok_enabled
            if (is_jev_byok_enabled is None and existing)
            else bool(is_jev_byok_enabled)
        )
        encrypted_jev_key: Optional[str] = None
        masked_jev_key: Optional[str] = None

        if eff_jev_byok:
            if raw_jev_key and raw_jev_key.strip():
                encrypted_jev_key = self.encrypt_key(raw_jev_key)
                masked_jev_key = self.mask_key(raw_jev_key)
            elif existing and existing.encrypted_jev_api_key:
                encrypted_jev_key = existing.encrypted_jev_api_key
                masked_jev_key = existing.masked_jev_api_key
            else:
                raise BYOKConfigurationError(
                    "Bạn đã bật BYOK JEV nhưng chưa nhập JEV API Key.",
                    tenant_key=clean_tenant,
                    provider="jev",
                    service_type="jev",
                )

        # --- Dọn rác llm_base_url khi đổi provider hoặc xóa trên UI ---
        if provider_changed:
            if llm_base_url is not _UNSET and llm_base_url is not None and str(llm_base_url).strip():
                eff_base_url: Optional[str] = str(llm_base_url).strip()
            else:
                eff_base_url = None
        else:
            if llm_base_url is _UNSET:
                eff_base_url = existing.llm_base_url if existing else None
            else:
                eff_base_url = (str(llm_base_url).strip() if llm_base_url is not None else "") or None

        # --- Dọn rác llm_model khi đổi provider hoặc reset trên UI ---
        if provider_changed:
            if llm_model is not _UNSET and llm_model is not None and str(llm_model).strip():
                eff_model: Optional[str] = str(llm_model).strip()
            else:
                eff_model = DEFAULT_GEMINI_MODEL if eff_provider == "google" else None
        else:
            if llm_model is _UNSET:
                eff_model = (
                    existing.llm_model
                    if existing
                    else (DEFAULT_GEMINI_MODEL if eff_provider == "google" else None)
                )
            else:
                cleaned_model = str(llm_model).strip() if llm_model is not None else ""
                if cleaned_model:
                    eff_model = cleaned_model
                else:
                    eff_model = DEFAULT_GEMINI_MODEL if eff_provider == "google" else None

        eff_tenant = clean_tenant or ((existing.tenant_key or "").strip() or None if existing else None)
        eff_user_name = (
            user_name.strip()
            if (user_name is not None and user_name.strip())
            else (existing.user_name if existing else None)
        )
        eff_timeout = (
            float(llm_timeout)
            if llm_timeout is not None
            else (existing.llm_timeout if existing else 60.0)
        )
        eff_hitl = (
            existing.hitl_mode_enabled
            if (hitl_mode_enabled is None and existing)
            else (True if hitl_mode_enabled is None else bool(hitl_mode_enabled))
        )
        eff_policy_interval = (
            int(policy_sync_interval_seconds)
            if policy_sync_interval_seconds is not None
            else (getattr(existing, "policy_sync_interval_seconds", 3600) if existing else 3600)
        )

        now_iso = get_vietnam_now_iso()
        record = UserSettingsRecord(
            open_id=clean_open_id,
            tenant_key=eff_tenant,
            user_name=eff_user_name,
            is_byok_enabled=eff_byok,
            llm_mode="byok" if eff_byok else "system",
            llm_provider=eff_provider,
            encrypted_llm_api_key=encrypted_key,
            masked_llm_api_key=masked_key,
            llm_base_url=eff_base_url,
            llm_model=eff_model,
            llm_timeout=eff_timeout,
            is_jev_byok_enabled=eff_jev_byok,
            jev_mode="byok" if eff_jev_byok else "system",
            encrypted_jev_api_key=encrypted_jev_key,
            masked_jev_api_key=masked_jev_key,
            digest_schedule_time=normalized_digest_time,
            hitl_mode_enabled=eff_hitl,
            policy_sync_interval_seconds=eff_policy_interval,
            created_at=existing.created_at if existing else now_iso,
            updated_at=now_iso,
        )

        coll = _get_user_settings_coll()
        user_query: Dict[str, Any] = {"open_id": clean_open_id}
        if record.tenant_key:
            user_query["tenant_key"] = record.tenant_key

        await coll.update_one(
            user_query,
            {"$set": record.to_dict()},
            upsert=True,
        )

        if record.tenant_key and policy_sync_interval_seconds is not None:
            try:
                await _db_module.get_tenants_collection().update_one(
                    {"tenant_key": record.tenant_key},
                    {"$set": {"policy_sync_interval_seconds": int(policy_sync_interval_seconds)}},
                )
            except Exception as t_up_err:
                logger.debug(f"Không thể cập nhật policy_sync_interval_seconds vào tenant: {t_up_err}")

        self.invalidate(tenant_key=record.tenant_key, open_id=record.open_id)
        logger.info(
            f"Đã lưu cấu hình AI cho open_id={record.open_id} (tenant={record.tenant_key}, "
            f"provider={record.llm_provider}, llm_byok={record.is_byok_enabled}, "
            f"jev_byok={record.is_jev_byok_enabled})"
        )
        return record

    save_user_settings = save_config

    # --------------------------------------------------------------------------
    # 5. PHÂN GIẢI FAIL-CLOSED (LLM CLIENT, LLM KEY, JEV KEY)
    # --------------------------------------------------------------------------

    async def resolve_llm_client(
        self,
        tenant_key: Optional[str] = None,
        open_id: Optional[str] = None,
        *,
        config_record: Optional[UserSettingsRecord] = None,
    ):
        """
        Phân giải `LLMClient` theo cấu hình tenant/user (Fail-Closed).
        Nếu bật BYOK nhưng thiếu hoặc lỗi giải mã key -> raise `BYOKConfigurationError`.
        """
        from services.ai.llm_client import LLMClient, llm_client

        eff_tenant = ((tenant_key or "").strip() or (get_current_tenant_key() or "").strip()) or None
        rec = (
            config_record
            if config_record is not None
            else await self.resolve_ai_config(tenant_key=eff_tenant, open_id=open_id)
        )

        if rec and rec.is_byok_enabled:
            provider_norm = normalize_provider(rec.llm_provider)
            rec_tenant = eff_tenant or rec.tenant_key
            user_key = self.decrypt_key_strict(
                rec.encrypted_llm_api_key,
                tenant_key=rec_tenant,
                provider=provider_norm,
                service_type="llm",
            )
            chosen_model = (rec.llm_model or "").strip() or get_default_model(provider_norm)
            clean_base_url = (rec.llm_base_url or "").strip() or None
            return LLMClient(
                api_key=user_key,
                provider=provider_norm,
                base_url=clean_base_url,
                timeout=rec.llm_timeout or 60.0,
                default_models=[chosen_model],
                model_name=chosen_model,
                is_byok=True,
                tenant_key=rec_tenant,
            )

        if getattr(llm_client, "is_byok", False):
            llm_client.is_byok = False
        return llm_client

    async def resolve_llm_key(
        self,
        tenant_key: Optional[str] = None,
        open_id: Optional[str] = None,
        *,
        config_record: Optional[UserSettingsRecord] = None,
    ) -> Tuple[str, bool]:
        """
        Phân giải `(api_key, is_byok)` cho LLM theo cơ chế Fail-Closed.
        Nếu bật BYOK nhưng thiếu hoặc giải mã lỗi -> raise `BYOKConfigurationError`.
        """
        eff_tenant = ((tenant_key or "").strip() or (get_current_tenant_key() or "").strip()) or None
        rec = (
            config_record
            if config_record is not None
            else await self.resolve_ai_config(tenant_key=eff_tenant, open_id=open_id)
        )

        if rec and rec.is_byok_enabled:
            provider_norm = normalize_provider(rec.llm_provider)
            rec_tenant = eff_tenant or rec.tenant_key
            user_key = self.decrypt_key_strict(
                rec.encrypted_llm_api_key,
                tenant_key=rec_tenant,
                provider=provider_norm,
                service_type="llm",
            )
            return user_key, True

        provider_norm = normalize_provider(rec.llm_provider if rec else "google")
        if provider_norm in ("openai", "chatgpt"):
            sys_key = (
                getattr(settings, "OPENAI_API_KEY", None)
                or os.getenv("OPENAI_API_KEY")
                or ""
            ).strip()
        elif provider_norm == "anthropic":
            sys_key = (
                getattr(settings, "ANTHROPIC_API_KEY", None)
                or os.getenv("ANTHROPIC_API_KEY")
                or ""
            ).strip()
        elif provider_norm == "custom":
            sys_key = ""
        else:
            sys_key = (
                getattr(settings, "GEMINI_API_KEY", None)
                or getattr(settings, "gemini_api", None)
                or os.getenv("GEMINI_API_KEY")
                or os.getenv("gemini_api")
                or ""
            ).strip()
        return sys_key, False

    async def resolve_jev_key(
        self,
        tenant_key: Optional[str] = None,
        open_id: Optional[str] = None,
        *,
        config_record: Optional[UserSettingsRecord] = None,
    ) -> Tuple[str, bool]:
        """
        Phân giải `(jev_api_key, is_byok)` cho JEV System 1 theo cơ chế Fail-Closed.
        Nếu bật JEV BYOK nhưng thiếu hoặc giải mã lỗi -> raise `BYOKConfigurationError`.
        """
        eff_tenant = ((tenant_key or "").strip() or (get_current_tenant_key() or "").strip()) or None
        rec = (
            config_record
            if config_record is not None
            else await self.resolve_ai_config(tenant_key=eff_tenant, open_id=open_id)
        )

        if rec and rec.is_jev_byok_enabled:
            rec_tenant = eff_tenant or rec.tenant_key
            jev_key = self.decrypt_key_strict(
                rec.encrypted_jev_api_key,
                tenant_key=rec_tenant,
                provider="jev",
                service_type="jev",
            )
            return jev_key, True

        sys_jev_key = (getattr(settings, "JEV_API_KEY", None) or "").strip()
        return sys_jev_key, False

    # --------------------------------------------------------------------------
    # 6. KIỂM TRA KẾT NỐI TRỰC TIẾP (LLM & JEV)
    # --------------------------------------------------------------------------

    async def test_llm_connection(
        self,
        raw_key: str,
        provider: str = "google",
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
    ) -> Tuple[bool, str, float]:
        """
        Kiểm tra trực tiếp kết nối với LLM/JEV Provider
        (`google`, `openai`/`chatgpt`, `anthropic`, `custom`, `jev`) thông qua engine chuẩn.
        Trả về: `(thành_công, thông_báo, độ_trễ_ms)`.
        """
        if not raw_key or not raw_key.strip():
            return False, "API Key không được để trống.", 0.0

        key = raw_key.strip()
        provider_norm = normalize_provider(provider)
        timeout_val = float(timeout) if timeout and float(timeout) > 0 else 30.0
        clean_base_url = (base_url or "").strip() or None
        clean_model = (model or "").strip() or None

        if provider_norm == "jev":
            from services.ai.jev_classifier import jev_service

            return await jev_service.ping_key(
                raw_key=key,
                base_url=clean_base_url,
                model=clean_model,
                timeout=timeout_val,
            )

        from services.ai.llm_client import LLMClient

        temp_client = LLMClient(
            api_key=key,
            provider=provider_norm,
            base_url=clean_base_url,
            model_name=clean_model,
            timeout=timeout_val,
            is_byok=True,
        )
        return await temp_client.ping(model=clean_model, timeout=timeout_val)


ai_config_manager = AIConfigManager()

__all__ = [
    "AIConfigManager",
    "ai_config_manager",
]
