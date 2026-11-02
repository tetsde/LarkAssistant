"""
HiLark - Onboarding Screen Guide Router
=======================================
Vị trí: server/routers/onboarding.py

Cung cấp:
  1. GET  /onboarding/wizard       : Giao diện Stepper Wizard 4 bước bằng HTML/CSS/JS (Apple Native SF Pro).
  2. POST /onboarding/api/test-key : Endpoint AJAX kiểm tra tính sống còn và latency của Gemini Key.
  3. POST /onboarding/api/save     : Lưu toàn bộ cấu hình vào MongoDB collection 'user_settings'.
  4. GET  /onboarding/api/settings/{open_id} : Lấy cấu hình hiện tại để điền sẵn vào Wizard.
  5. GET  /onboarding/api/auth-status        : Tra cứu nhanh tình trạng xác thực Lark OAuth.
  6. POST /onboarding/api/provision-base     : Tự động khởi tạo 100% Lark Base Doanh nghiệp.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient

from core.config import settings
from database.db import get_system_config_collection
from models.onboarding import (
    ProvisionBaseRequest,
    ProvisionWeKnoraRequest,
    SaveBotConfigRequest,
    SaveSettingsRequest,
    TestBotCredentialsRequest,
    TestKeyRequest,
    TestMongoRequest,
)
from services.user_settings_service import user_settings_service

# Re-exported for backwards compatibility
__all__ = [
    "router",
    "TestKeyRequest",
    "SaveSettingsRequest",
    "ProvisionBaseRequest",
    "ProvisionWeKnoraRequest",
    "TestBotCredentialsRequest",
    "SaveBotConfigRequest",
    "TestMongoRequest",
]

logger = logging.getLogger("hilark.router.onboarding")
router = APIRouter(prefix="/onboarding", tags=["onboarding"])

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "onboarding_wizard.html"


@router.post("/api/test-bot")
async def test_bot_credentials_endpoint(req: TestBotCredentialsRequest):
    """Kiểm tra trực tiếp cặp App ID & App Secret với Lark Open Platform."""
    app_id_clean = req.app_id.strip()
    app_secret_clean = req.app_secret.strip()

    if not app_id_clean:
        return {"success": False, "message": "App ID không được để trống."}
    if not app_id_clean.startswith("cli_"):
        return {
            "success": False,
            "message": "Định dạng App ID không hợp lệ. Mã ứng dụng Lark bắt buộc phải bắt đầu bằng tiền tố 'cli_' (Ví dụ: cli_aa4770ba50789e2c).",
        }
    if len(app_id_clean) < 10:
        return {"success": False, "message": "App ID quá ngắn (tối thiểu 10 ký tự)."}
    if not app_secret_clean or len(app_secret_clean) < 8:
        return {"success": False, "message": "App Secret không được để trống và phải có độ dài hợp lệ."}

    start_time = time.time()
    try:
        domain = getattr(settings, "LARK_DOMAIN", "https://open.larksuite.com")
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{domain}/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id_clean, "app_secret": app_secret_clean},
            )
            latency = round((time.time() - start_time) * 1000, 1)
            data = resp.json()

            if data.get("code") == 0:
                return {
                    "success": True,
                    "message": f"Xác thực Lark Bot thành công ({latency}ms). Cặp App ID & App Secret hoàn toàn hợp lệ!",
                    "latency_ms": latency,
                    "app_id": app_id_clean,
                }
            else:
                err_code = data.get("code")
                err_msg = data.get("msg") or data.get("message") or f"Mã lỗi Lark: {err_code}"
                return {
                    "success": False,
                    "message": f"Lark từ chối thông tin xác thực (Mã {err_code}): {err_msg}. Vui lòng kiểm tra lại App ID và App Secret trên Developer Console.",
                    "latency_ms": latency,
                }
    except Exception as e:
        latency = round((time.time() - start_time) * 1000, 1)
        logger.error(f"Lỗi kiểm tra Lark credentials: {e}")
        return {
            "success": False,
            "message": f"Không thể kết nối đến máy chủ Lark: {str(e)}",
            "latency_ms": latency,
        }


@router.post("/api/test-mongo")
async def test_mongo_connection_endpoint(req: TestMongoRequest):
    """Kiểm tra độ sống và đo độ trễ của kết nối MongoDB (Custom MongoDB URL)."""
    mongo_url = req.mongo_url.strip() if req.mongo_url else ""
    if not mongo_url:
        return {"success": False, "message": "URI MongoDB không được để trống."}

    if not (mongo_url.startswith("mongodb://") or mongo_url.startswith("mongodb+srv://")):
        return {
            "success": False,
            "message": "URI MongoDB không đúng định dạng. Phải bắt đầu bằng 'mongodb://' hoặc 'mongodb+srv://'.",
        }

    start_time = time.time()
    test_client = None
    try:
        test_client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=4000)
        # Ping cơ sở dữ liệu
        await test_client.admin.command("ping")
        latency = round((time.time() - start_time) * 1000, 1)
        return {
            "success": True,
            "message": f"Kết nối MongoDB thành công ({latency}ms). Cơ sở dữ liệu hoạt động bình thường!",
            "latency_ms": latency,
        }
    except Exception as e:
        latency = round((time.time() - start_time) * 1000, 1)
        logger.warning(f"Lỗi kết nối test MongoDB: {e}")
        return {
            "success": False,
            "message": f"Không thể kết nối tới MongoDB: {str(e)}",
            "latency_ms": latency,
        }
    finally:
        if test_client:
            try:
                test_client.close()
            except Exception:
                pass


@router.post("/api/save-bot-config")
async def save_bot_config_endpoint(req: SaveBotConfigRequest):
    """Lưu cấu hình Bot credentials và tùy chọn MongoDB vào hệ thống."""
    app_id_clean = req.app_id.strip() if req.app_id else ""
    if not app_id_clean or not app_id_clean.startswith("cli_"):
        raise HTTPException(
            status_code=400,
            detail="App ID không hợp lệ. Phải bắt đầu bằng tiền tố 'cli_'.",
        )

    try:
        coll = get_system_config_collection()
        doc: Dict[str, Any] = {
            "config_key": "bot_credentials",
            "app_id": app_id_clean,
            "custom_mongo_url": req.custom_mongo_url.strip() if req.custom_mongo_url else None,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+07:00"),
        }
        if req.app_secret and req.app_secret.strip():
            doc["encrypted_app_secret"] = user_settings_service.encrypt_key(req.app_secret.strip())
            doc["masked_app_secret"] = user_settings_service.mask_key(req.app_secret.strip())

        await coll.update_one(
            {"config_key": "bot_credentials"},
            {"$set": doc},
            upsert=True,
        )

        # Cập nhật runtime settings
        settings.LARK_APP_ID = app_id_clean
        if req.app_secret and req.app_secret.strip():
            settings.LARK_APP_SECRET = req.app_secret.strip()
        if req.custom_mongo_url and req.custom_mongo_url.strip():
            settings.MONGO_URL = req.custom_mongo_url.strip()

        # Cập nhật LarkService singleton nếu có
        try:
            from services.lark import lark_service
            old_app_id = getattr(lark_service, "app_id", "")
            old_secret = getattr(lark_service, "app_secret", "")

            lark_service.app_id = app_id_clean
            if req.app_secret and req.app_secret.strip():
                lark_service.app_secret = req.app_secret.strip()
            lark_service._init_client(
                app_id=app_id_clean,
                app_secret=settings.LARK_APP_SECRET,
            )
            # Chỉ tái kết nối WebSocket ngầm nếu App ID hoặc Secret thật sự thay đổi và có đủ cặp credentials
            current_secret = getattr(settings, "LARK_APP_SECRET", "")
            if (old_app_id != app_id_clean or old_secret != current_secret) and app_id_clean and current_secret:
                # Dọn thread cũ nếu cần trước khi kết nối mới
                if hasattr(lark_service, "_ws_thread"):
                    lark_service._ws_thread = None
                lark_service.start_ws_client(background=True)
        except Exception as e:
            logger.debug(f"Không thể reinit LarkService runtime: {e}")

        return {
            "success": True,
            "message": "Đã lưu cấu hình Lark Bot & Hạ tầng thành công!",
            "data": {
                "app_id": app_id_clean,
                "custom_mongo_url": req.custom_mongo_url,
            },
        }
    except Exception as e:
        logger.error(f"Lỗi khi lưu bot config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/bot-config")
async def get_bot_config_endpoint():
    """Lấy cấu hình hiện tại của Lark Bot & MongoDB để hiển thị trên Wizard."""
    current_app_id = getattr(settings, "LARK_APP_ID", "") or ""
    current_secret = getattr(settings, "LARK_APP_SECRET", "") or ""
    current_mongo = getattr(settings, "MONGO_URL", "") or "mongodb://localhost:27017"
    masked_secret = user_settings_service.mask_key(current_secret) if current_secret else ""
    has_credentials = bool(current_app_id and current_secret)
    custom_mongo_url = None

    try:
        coll = get_system_config_collection()
        doc = await coll.find_one({"config_key": "bot_credentials"})
        if doc:
            if doc.get("app_id"):
                current_app_id = doc["app_id"]
            if doc.get("masked_app_secret"):
                masked_secret = doc["masked_app_secret"]
            if doc.get("custom_mongo_url"):
                custom_mongo_url = doc["custom_mongo_url"]
            has_credentials = bool(current_app_id and (masked_secret or current_secret))
    except Exception as e:
        logger.debug(f"Chưa lấy được bot config từ MongoDB: {e}")

    return {
        "success": True,
        "data": {
            "app_id": current_app_id,
            "masked_app_secret": masked_secret,
            "has_credentials": has_credentials,
            "custom_mongo_url": custom_mongo_url,
            "default_mongo_url": current_mongo,
        },
    }


@router.post("/api/provision-base")
async def provision_base_endpoint(req: ProvisionBaseRequest):
    """Tự động khởi tạo 100% Lark Base Quản trị Doanh nghiệp qua Lark OpenAPI."""
    try:
        from services.lark.base_provision_service import base_provision_service
        if req.admin_open_id and req.admin_open_id.strip():
            clean_admin = req.admin_open_id.strip()
            settings.LARK_USER_OPEN_ID = clean_admin
            try:
                from services.lark import lark_service
                lark_service.known_user_open_id = clean_admin
                if getattr(lark_service, "config", None):
                    lark_service.config.user_open_id = clean_admin
            except Exception:
                pass
        record = await base_provision_service.provision_enterprise_base(
            admin_open_id=req.admin_open_id,
            tenant_key=req.tenant_key,
        )
        return {
            "success": True,
            "message": "Đã tự động khởi tạo Lark Base Quản trị thành công!",
            "data": record.to_dict(),
        }
    except Exception as e:
        logger.error(f"Lỗi khi auto-provision Lark Base: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/provision-weknora")
async def provision_weknora_endpoint(req: ProvisionWeKnoraRequest):
    """Tự động khởi tạo không gian tri thức WeKnora và tài khoản Admin đa doanh nghiệp."""
    try:
        from services.knowledge.weknora_provision_service import weknora_provision_service
        tenant_key = req.tenant_key or "default"
        record = await weknora_provision_service.provision_tenant_weknora(
            tenant_key=tenant_key,
            enterprise_name=req.enterprise_name or f"Enterprise {tenant_key}",
            admin_email=req.admin_email,
            admin_open_id=req.admin_open_id,
        )
        screen_data = weknora_provision_service.build_screen_guide_data(record)
        return {
            "success": True,
            "message": "Đã khởi tạo không gian tri thức WeKnora thành công!",
            "data": screen_data,
        }
    except Exception as e:
        logger.error(f"Lỗi khi provision WeKnora: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/test-key")
async def test_key_endpoint(req: TestKeyRequest):
    """Kiểm tra trực tiếp độ sống và độ trễ của LLM API Key qua AJAX."""
    provider_norm = (req.provider or "google").strip().lower()
    if provider_norm == "google" and not req.base_url:
        ok, msg, latency = await user_settings_service.test_gemini_key(req.api_key)
    else:
        ok, msg, latency = await user_settings_service.test_llm_connection(
            raw_key=req.api_key,
            provider=provider_norm,
            base_url=req.base_url,
            model=req.model_name,
            timeout=req.timeout or 30.0,
        )
    return {
        "success": ok,
        "message": msg,
        "latency_ms": latency,
    }


@router.post("/api/save")
async def save_settings_endpoint(req: SaveSettingsRequest):
    """Lưu cấu hình sau khi người dùng hoàn thành 4 bước trên Screen Guide."""
    try:
        record = await user_settings_service.save_user_settings(
            open_id=req.open_id,
            is_byok_enabled=req.is_byok_enabled,
            raw_gemini_key=req.raw_gemini_key,
            digest_schedule_time=req.digest_schedule_time,
            hitl_mode_enabled=req.hitl_mode_enabled,
            user_name=req.user_name,
            llm_provider=req.llm_provider or "google",
            llm_base_url=req.llm_base_url,
            llm_model=req.llm_model,
            llm_timeout=req.llm_timeout or 60.0,
            tenant_key=req.tenant_key,
        )

        clean_open_id = req.open_id.strip() if req.open_id else ""
        if clean_open_id:
            # 1. Cập nhật settings runtime & lark_service singleton
            settings.LARK_USER_OPEN_ID = clean_open_id
            try:
                from services.lark import lark_service
                lark_service.known_user_open_id = clean_open_id
                if getattr(lark_service, "config", None):
                    lark_service.config.user_open_id = clean_open_id
            except Exception as le:
                logger.debug(f"Không thể cập nhật LarkService known_user_open_id: {le}")

            # 2. Cập nhật admin_open_id vào tenants collection nếu có tenant_key
            eff_tenant = req.tenant_key or getattr(record, "tenant_key", None)
            if eff_tenant:
                try:
                    from database.db import upsert_tenant_config
                    await upsert_tenant_config({
                        "tenant_key": eff_tenant,
                        "admin_open_id": clean_open_id,
                    })
                except Exception as te:
                    logger.debug(f"Không thể cập nhật admin_open_id vào tenant '{eff_tenant}': {te}")

            # 3. Lưu cấu hình admin vào system_config để duy trì sau khởi động lại
            try:
                coll = get_system_config_collection()
                await coll.update_one(
                    {"config_key": "lark_admin_config"},
                    {"$set": {
                        "config_key": "lark_admin_config",
                        "admin_open_id": clean_open_id,
                        "user_name": req.user_name or getattr(record, "user_name", "") or "Lãnh đạo",
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+07:00"),
                    }},
                    upsert=True,
                )
            except Exception as se:
                logger.debug(f"Không thể lưu lark_admin_config vào system_config: {se}")

        if req.custom_mongo_url and req.custom_mongo_url.strip():
            try:
                coll = get_system_config_collection()
                bot_doc: Dict[str, Any] = {
                    "config_key": "bot_credentials",
                    "custom_mongo_url": req.custom_mongo_url.strip(),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+07:00"),
                }
                await coll.update_one({"config_key": "bot_credentials"}, {"$set": bot_doc}, upsert=True)
                settings.MONGO_URL = req.custom_mongo_url.strip()
            except Exception as bot_err:
                logger.debug(f"Không thể cập nhật custom_mongo_url trong save_settings: {bot_err}")
        return {
            "success": True,
            "message": "Đã lưu cấu hình trợ lý thành công!",
            "data": record.to_dict(),
        }
    except Exception as e:
        logger.error(f"Lỗi khi lưu cấu hình onboarding: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/settings/{open_id}")
async def get_settings_endpoint(
    open_id: str,
    tenant_key: Optional[str] = Query(None, description="Mã định danh tenant ISV"),
):
    """Lấy thông tin cấu hình hiện hành để hiển thị trên Wizard."""
    effective_tenant_key = tenant_key
    if not effective_tenant_key:
        try:
            from database.db import get_tenants_collection
            t_col = get_tenants_collection()
            found_tenant = await t_col.find_one({"admin_open_id": open_id})
            if found_tenant:
                effective_tenant_key = found_tenant.get("tenant_key")
        except Exception as e:
            logger.debug(f"Không tìm thấy tenant cho open_id {open_id}: {e}")

    from services.lark.base_provision_service import base_provision_service
    base_cfg = await base_provision_service.get_active_base_config(tenant_key=effective_tenant_key)
    base_info = {
        "app_token": base_cfg.app_token,
        "app_url": base_cfg.app_url,
        "is_auto_provisioned": base_cfg.is_auto_provisioned,
    }

    weknora_info = None
    if effective_tenant_key:
        try:
            from database.db import get_tenant_config
            from services.knowledge.weknora_provision_service import weknora_provision_service
            from models.tenant import TenantConfigRecord
            t_cfg = await get_tenant_config(effective_tenant_key)
            if t_cfg:
                rec = TenantConfigRecord.from_dict(t_cfg) if isinstance(t_cfg, dict) else t_cfg
                weknora_info = weknora_provision_service.build_screen_guide_data(rec)
        except Exception as e:
            logger.debug(f"Không thể lấy WeKnora info cho tenant {effective_tenant_key}: {e}")

    record = await user_settings_service.get_user_settings(open_id, tenant_key=effective_tenant_key)
    if not record:
        return {
            "success": True,
            "data": {
                "open_id": open_id,
                "is_byok_enabled": False,
                "llm_provider": "google",
                "masked_gemini_api_key": "",
                "llm_base_url": "",
                "llm_model": "gemini-2.5-flash",
                "llm_timeout": 60.0,
                "digest_schedule_time": "18:00",
                "hitl_mode_enabled": True,
                "base_info": base_info,
                "weknora_info": weknora_info,
                "tenant_key": effective_tenant_key,
            },
        }
    data = record.to_dict()
    data["base_info"] = base_info
    data["weknora_info"] = weknora_info
    data["tenant_key"] = effective_tenant_key
    return {
        "success": True,
        "data": data,
    }


@router.get("/api/auth-status")
async def get_onboarding_auth_status():
    """Tra cứu nhanh tình trạng xác thực Lark OAuth cho Wizard UI."""
    try:
        from services.auth_service import token_service
        status = await token_service.get_token_status()
        return {
            "success": True,
            "data": status,
        }
    except Exception as e:
        logger.error(f"Lỗi khi lấy auth status trong onboarding router: {e}")
        return {
            "success": False,
            "error": str(e),
            "data": {"has_token": False, "is_valid": False},
        }


@router.get("/wizard", response_class=HTMLResponse)
async def onboarding_wizard_page(
    request: Request,
    open_id: Optional[str] = Query(None, description="Lark Open ID của người dùng"),
    user_name: Optional[str] = Query(None, description="Tên người dùng"),
    tenant_key: Optional[str] = Query(None, description="Mã tenant ISV nếu có"),
):
    """Render giao diện Screen Guide Wizard 4 bước mở trong Lark Applink Webview Modal."""
    effective_open_id = open_id or settings.LARK_USER_OPEN_ID or "ou_user_default"
    effective_user_name = user_name or settings.LARK_USER_NAME or "Lãnh đạo"
    effective_tenant_key = tenant_key or ""

    if not TEMPLATE_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Template file không tồn tại: {TEMPLATE_PATH}",
        )

    template_content = TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered_html = (
        template_content
        .replace("{{effective_open_id}}", effective_open_id)
        .replace("{{effective_user_name}}", effective_user_name)
        .replace("{{effective_tenant_key}}", effective_tenant_key)
    )

    return HTMLResponse(content=rendered_html)
