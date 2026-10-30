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
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from core.config import settings
from models.onboarding import (
    ProvisionBaseRequest,
    SaveSettingsRequest,
    TestKeyRequest,
)
from services.user_settings_service import user_settings_service

# Re-exported for backwards compatibility
__all__ = ["router", "TestKeyRequest", "SaveSettingsRequest", "ProvisionBaseRequest"]

logger = logging.getLogger("hilark.router.onboarding")
router = APIRouter(prefix="/onboarding", tags=["onboarding"])

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "onboarding_wizard.html"


@router.post("/api/provision-base")
async def provision_base_endpoint(req: ProvisionBaseRequest):
    """Tự động khởi tạo 100% Lark Base Quản trị Doanh nghiệp qua Lark OpenAPI."""
    try:
        from services.lark.base_provision_service import base_provision_service
        record = await base_provision_service.provision_enterprise_base(admin_open_id=req.admin_open_id)
        return {
            "success": True,
            "message": "Đã tự động khởi tạo Lark Base Quản trị thành công!",
            "data": record.to_dict(),
        }
    except Exception as e:
        logger.error(f"Lỗi khi auto-provision Lark Base: {e}", exc_info=True)
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
        )
        return {
            "success": True,
            "message": "Đã lưu cấu hình trợ lý thành công!",
            "data": record.to_dict(),
        }
    except Exception as e:
        logger.error(f"Lỗi khi lưu cấu hình onboarding: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/settings/{open_id}")
async def get_settings_endpoint(open_id: str):
    """Lấy thông tin cấu hình hiện hành để hiển thị trên Wizard."""
    from services.lark.base_provision_service import base_provision_service
    base_cfg = await base_provision_service.get_active_base_config()
    base_info = {
        "app_token": base_cfg.app_token,
        "app_url": base_cfg.app_url,
        "is_auto_provisioned": base_cfg.is_auto_provisioned,
    }

    record = await user_settings_service.get_user_settings(open_id)
    if not record:
        return {
            "success": True,
            "data": {
                "open_id": open_id,
                "is_byok_enabled": False,
                "llm_provider": "google",
                "masked_gemini_api_key": "",
                "llm_base_url": "",
                "llm_model": "gemini-2.0-flash",
                "llm_timeout": 60.0,
                "digest_schedule_time": "18:00",
                "hitl_mode_enabled": True,
                "base_info": base_info,
            },
        }
    data = record.to_dict()
    data["base_info"] = base_info
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
):
    """Render giao diện Screen Guide Wizard 4 bước mở trong Lark Applink Webview Modal."""
    effective_open_id = open_id or settings.LARK_USER_OPEN_ID or "ou_user_default"
    effective_user_name = user_name or settings.LARK_USER_NAME or "Lãnh đạo"

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
    )

    return HTMLResponse(content=rendered_html)
