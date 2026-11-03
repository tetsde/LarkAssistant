"""
HiLark - One-Click Setup Router
===============================
Vị trí: server/routers/setup.py

Cung cấp các endpoints phục vụ luồng One-Click Setup 7 bước:
  - GET  /setup                : Landing Page giao diện Apple Minimalist.
  - GET  /setup/install        : Khởi tạo luồng cài đặt & chuyển hướng sang Lark OAuth.
  - GET  /setup/callback       : Nhận authorization code từ Lark & kích hoạt pipeline ngầm.
  - GET  /setup/api/status/{id}: Polling API kiểm tra tiến độ 7 bước theo thời gian thực.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from core.config import settings
from models.onboarding import RegisterLarkAppRequest
from services.auth_service import token_service
from services.lark_app_service import lark_app_service
from services.setup.one_click_setup_service import one_click_setup_service

logger = logging.getLogger("hilark.router.setup")
router = APIRouter(prefix="/setup", tags=["setup"])

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "setup_one_click.html"


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def setup_landing_page(
    request: Request,
    task_id: Optional[str] = Query(None, description="Mã tiến trình nếu đang theo dõi"),
):
    """
    Hiển thị giao diện One-Click Setup.
    Nếu có task_id, trang sẽ tự động kích hoạt polling tiến độ 7 bước.
    """
    if not TEMPLATE_PATH.exists():
        raise HTTPException(status_code=500, detail="Không tìm thấy template setup_one_click.html")

    html_content = TEMPLATE_PATH.read_text(encoding="utf-8")

    # Thay thế biến động vào template
    app_id = getattr(settings, "LARK_APP_ID", "")
    base_url = str(request.base_url).rstrip("/")
    initial_task_id = task_id or ""
    initial_view = "progress" if task_id else "guide"

    html_content = (
        html_content
        .replace("{{APP_ID}}", app_id)
        .replace("{{BASE_URL}}", base_url)
        .replace("{{TASK_ID}}", initial_task_id)
        .replace("{{INITIAL_VIEW}}", initial_view)
        .replace("{{TENANT_KEY}}", "")
        .replace("{{OPEN_ID}}", "")
        .replace("{{effective_open_id}}", "")
        .replace("{{effective_user_name}}", "")
        .replace("{{effective_tenant_key}}", "")
    )

    return HTMLResponse(content=html_content)


@router.get("/install")
async def start_install_redirect(
    request: Request,
    registration_id: Optional[str] = Query(None, description="Mã đăng ký Custom App theo tenant/setup"),
    redirect_uri: Optional[str] = Query(None, description="Tùy chọn redirect_uri được truyền trực tiếp từ client"),
):
    """
    Khởi tạo phiên cài đặt mới và chuyển hướng sang Lark OAuth.
    Tự động nhận diện host/proxy (ngrok/https) để tạo redirect_uri chính xác khớp với Lark Console.
    """
    app_record = await lark_app_service.get_registration(registration_id) if registration_id else None
    # GĐ2/GĐ4: không vay App credential từ `.env` nữa. Phiên cài đặt phải gắn với một
    # registration đã lưu trong DB, nếu không thì URL ủy quyền sẽ trỏ vào App của
    # người khác và toàn bộ pipeline setup đổi code bằng secret sai.
    if not app_record:
        raise HTTPException(
            status_code=400,
            detail="Cần đăng ký Custom App (register-app) trước khi bắt đầu OAuth user.",
        )
    app_id = app_record.get("app_id") or ""
    app_secret = app_record.get("app_secret") or ""
    if not app_id or not app_secret:
        raise HTTPException(
            status_code=400,
            detail="Cần xác thực và lưu App ID/App Secret trước khi bắt đầu OAuth user.",
        )

    task_id = one_click_setup_service.create_task(app_registration_id=registration_id)

    configured_redirect_uri = getattr(settings, "LARK_OAUTH_REDIRECT_URI", "")
    if redirect_uri:
        final_redirect_uri = redirect_uri
    elif configured_redirect_uri:
        final_redirect_uri = configured_redirect_uri
    else:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        base_url = f"{proto}://{host}".rstrip("/") if host else str(request.base_url).rstrip("/")
        final_redirect_uri = f"{base_url}/setup/callback"

    auth_state = f"setup_{task_id}"
    await one_click_setup_service.persist_task(task_id, oauth_state=auth_state)
    auth_url = token_service.get_authorize_url(
        redirect_uri=final_redirect_uri,
        state=auth_state,
        app_id=app_id,
    )
    logger.info(f"🚀 [ONE-CLICK SETUP] Khởi tạo task '{task_id}', redirect_uri='{final_redirect_uri}', auth_url='{auth_url}'")
    return RedirectResponse(url=auth_url)


@router.post("/api/register-app")
async def register_custom_app(req: RegisterLarkAppRequest):
    """Đăng ký Custom App theo setup session, không mutate settings global."""
    try:
        record = await lark_app_service.register_app(
            app_id=req.app_id,
            app_secret=req.app_secret,
            verification_token=req.verification_token or "",
            encrypt_key=req.encrypt_key or "",
        )
        return {"success": True, "data": record}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Không thể đăng ký Custom App: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Không thể lưu Custom App credential.")


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback_endpoint(
    request: Request,
    code: Optional[str] = Query(None, description="Authorization code từ Lark"),
    state: Optional[str] = Query(None, description="Task ID của phiên cài đặt"),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
):
    """
    Nhận callback từ Lark sau khi Admin cấp quyền.
    Kích hoạt pipeline 7 bước chạy nền và hiển thị màn hình tiến độ cho Admin.
    """
    if error:
        err_msg = error_description or error
        logger.warning(f"Lark OAuth bị từ chối: {error} - {err_msg}")
        return HTMLResponse(
            status_code=400,
            content=f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HiLark — Cài Đặt Thất Bại</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #090d16;
            color: #f8fafc;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            padding: 24px;
            text-align: center;
        }}
        .card {{
            background: rgba(30, 41, 59, 0.7);
            border: 1px solid rgba(239, 68, 68, 0.3);
            border-radius: 20px;
            padding: 40px;
            max-width: 440px;
            backdrop-filter: blur(20px);
        }}
        h2 {{ color: #f87171; margin-bottom: 12px; }}
        p {{ color: #94a3b8; font-size: 14px; line-height: 1.6; }}
        a {{
            display: inline-block;
            margin-top: 20px;
            padding: 10px 24px;
            background: #3b82f6;
            color: #fff;
            text-decoration: none;
            border-radius: 10px;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h2>Cài đặt Chưa Thành Công</h2>
        <p>Lark đã phản hồi lỗi ủy quyền: {err_msg}</p>
        <a href="/setup">Thử cài đặt lại</a>
    </div>
</body>
</html>""",
        )

    if not code:
        raise HTTPException(status_code=400, detail="Thiếu tham số 'code' trong callback!")

    if state and state.startswith("setup_"):
        task_id = await one_click_setup_service.claim_oauth_state(state)
        if not task_id:
            raise HTTPException(status_code=400, detail="OAuth state không hợp lệ hoặc đã được sử dụng.")
    else:
        task_id = state or one_click_setup_service.create_task()

    # Kích hoạt pipeline 7 bước chạy nền (asyncio task)
    asyncio.create_task(one_click_setup_service.run_setup_pipeline(task_id=task_id, code=code, state=state))

    # Chuyển hướng về trang /setup?task_id=... để hiển thị tiến độ
    return RedirectResponse(url=f"/setup?task_id={task_id}")


@router.get("/api/status/{task_id}")
async def get_setup_status_endpoint(task_id: str):
    """API Polling để Web UI truy vấn tiến độ 7 bước."""
    status = await one_click_setup_service.load_task_status(task_id)
    if not status:
        return JSONResponse(status_code=404, content={"success": False, "message": "Không tìm thấy task_id"})
    return JSONResponse(content={"success": True, "data": status})

