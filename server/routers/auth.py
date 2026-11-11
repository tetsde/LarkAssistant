"""
HiLark Authentication Router
============================
Vị trí: server/routers/auth.py

Mục đích:
    Cung cấp các endpoint phục vụ luồng OAuth 2.0 / OIDC của Lark:
      - GET  /auth/lark/login     : Giao diện / Chuyển hướng sang trang ủy quyền Lark.
      - GET  /auth/lark/callback  : Endpoint callback nhận `code`, đổi lấy access_token + refresh_token.
      - POST /auth/lark/exchange  : Đổi `code` lấy token qua REST API (cho Postman/cURL).
      - GET  /auth/lark/status    : Kiểm tra trạng thái sống còn của Token hiện tại.
      - POST /auth/lark/refresh   : Kích hoạt làm mới (refresh) token thủ công.
"""

from __future__ import annotations

import html
import json
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from core.config import settings
from services.auth.token_service import mask_token_preview
from services.auth_service import token_service

logger = logging.getLogger("hilark.router.auth")
router = APIRouter(prefix="/auth/lark", tags=["auth"])


class ExchangeCodeRequest(BaseModel):
    code: str
    redirect_uri: Optional[str] = None
    tenant_key: Optional[str] = None


def _oauth_error_page(status_code: int, title: str, message: str) -> HTMLResponse:
    """Trang lỗi chung cho luồng ủy quyền: không âm thầm đổi App khi thiếu thông tin."""
    safe_message = (message or "").replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(
        status_code=status_code,
        content=f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8"><title>{title}</title>
    <style>body {{ font-family: -apple-system, sans-serif; background: #0f172a; color: #fff; padding: 40px; text-align: center; }}</style>
</head>
<body>
    <h1 style="color: #ef4444;">⚠️ {title}</h1>
    <p style="color: #cbd5e1; margin: 20px auto; max-width: 640px;">{safe_message}</p>
    <a href="/auth/lark/login" style="color: #818cf8;">Quay lại màn hình đăng nhập</a>
</body></html>""",
    )


# =============================================================================
# 1. GET /auth/lark/login
# =============================================================================

@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    redirect: bool = Query(False, description="Nếu True sẽ tự động chuyển hướng sang Lark"),
    redirect_uri: Optional[str] = Query(None, description="Tùy chỉnh redirect_uri"),
    source: Optional[str] = Query(None, description="Nguồn gọi: wizard, popup..."),
    tenant_key: Optional[str] = Query(None, description="Doanh nghiệp đang cần uỷ quyền (bắt buộc)"),
):
    """
    Tạo link ủy quyền OAuth2 của Lark CHO MỘT TENANT CỤ THỂ.

    Bắt buộc `tenant_key`: URL ủy quyền và `state` phải nói rõ code sẽ được đổi bằng App
    nào. Bản cũ sinh link bằng `settings.LARK_APP_ID` và state tự do, nên một doanh nghiệp
    có thể bị gán token lấy từ App của doanh nghiệp khác.
    Có thể hiển thị trang giao diện bấm nút hoặc chuyển hướng trực tiếp.
    """
    from database.db import get_current_tenant_key
    from services.auth.oauth_state_service import oauth_state_service
    from services.tenancy.tenant_resolver import tenant_resolver
    from core.tenant_errors import TenantResolutionError

    eff_tenant = (tenant_key or "").strip() or get_current_tenant_key()
    if not eff_tenant:
        return _oauth_error_page(
            status_code=400,
            title="Thiếu thông tin doanh nghiệp",
            message=(
                "/auth/lark/login cần `tenant_key` để biết ủy quyền này cho doanh nghiệp nào "
                "và dùng App nào. Không còn mặc định App trong .env."
            ),
        )

    try:
        credentials = await tenant_resolver.resolve_credentials(eff_tenant)
    except TenantResolutionError as err:
        return _oauth_error_page(
            status_code=err.http_status,
            title="Không tìm thấy App của doanh nghiệp",
            message=str(err),
        )

    # Tự động suy luận redirect_uri từ domain hiện tại nếu người dùng không truyền vào
    effective_redirect_uri = redirect_uri or settings.LARK_OAUTH_REDIRECT_URI
    if not effective_redirect_uri:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        base_url = f"{proto}://{host}".rstrip("/") if host else str(request.base_url).rstrip("/")
        effective_redirect_uri = f"{base_url}/auth/lark/callback"

    # State do server sinh và lưu xuống `oauth_states` kèm (tenant_key, app_id).
    state_val = await oauth_state_service.create(
        tenant_key=eff_tenant,
        app_id=credentials.app_id,
        purpose="wizard" if source == "wizard" else "user_oauth",
        redirect_uri=effective_redirect_uri,
    )
    auth_url = token_service.get_authorize_url(
        redirect_uri=effective_redirect_uri,
        state=state_val,
        app_id=credentials.app_id,
    )

    if redirect:
        return RedirectResponse(url=auth_url)

    html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HiLark — Kết nối Tài khoản Lark & Lấy Refresh Token</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Inter', -apple-system, sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
            color: #f8fafc;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }}
        .card {{
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 20px;
            padding: 40px;
            max-width: 580px;
            width: 100%;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }}
        .badge {{
            display: inline-block;
            background: rgba(99, 102, 241, 0.2);
            color: #818cf8;
            font-size: 12px;
            font-weight: 600;
            padding: 4px 12px;
            border-radius: 9999px;
            margin-bottom: 16px;
            border: 1px solid rgba(99, 102, 241, 0.3);
        }}
        h1 {{ font-size: 24px; font-weight: 700; margin-bottom: 12px; color: #fff; }}
        p.subtitle {{ color: #94a3b8; font-size: 14px; line-height: 1.6; margin-bottom: 24px; }}
        .steps {{
            background: rgba(15, 23, 42, 0.6);
            border-radius: 12px;
            padding: 16px 20px;
            margin-bottom: 24px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }}
        .step-item {{
            display: flex;
            align-items: flex-start;
            margin-bottom: 12px;
            font-size: 13px;
            color: #cbd5e1;
        }}
        .step-item:last-child {{ margin-bottom: 0; }}
        .step-num {{
            background: #4f46e5;
            color: #fff;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 700;
            margin-right: 12px;
            flex-shrink: 0;
            margin-top: 2px;
        }}
        .code-box {{
            background: #0f172a;
            color: #38bdf8;
            padding: 6px 10px;
            border-radius: 6px;
            font-family: monospace;
            font-size: 12px;
            word-break: break-all;
            margin-top: 4px;
            display: block;
        }}
        .btn {{
            display: block;
            width: 100%;
            background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
            color: #fff;
            text-align: center;
            text-decoration: none;
            padding: 14px 20px;
            border-radius: 12px;
            font-weight: 600;
            font-size: 15px;
            box-shadow: 0 10px 15px -3px rgba(79, 70, 229, 0.4);
            transition: all 0.2s ease;
        }}
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 15px 25px -5px rgba(79, 70, 229, 0.5);
            background: linear-gradient(135deg, #4338ca 0%, #6d28d9 100%);
        }}
    </style>
</head>
<body>
    <div class="card">
        <span class="badge">OAuth 2.0 Token Manager</span>
        <h1>Kết nối Tài khoản Lark</h1>
        <p class="subtitle">Ủy quyền 1 lần duy nhất để HiLark lấy <strong>Refresh Token</strong> và kích hoạt cơ chế tự động xoay vòng vĩnh viễn.</p>

        <div class="steps">
            <div class="step-item">
                <div class="step-num">1</div>
                <div>Ủy quyền cho tenant <span class="code-box">{eff_tenant}</span> — App ID: <span class="code-box">{credentials.app_id}</span></div>
            </div>
            <div class="step-item">
                <div class="step-num">2</div>
                <div>Đảm bảo đã đăng ký Redirect URL này trong <em>Security Settings &gt; Redirect URLs</em>:
                    <span class="code-box">{effective_redirect_uri}</span>
                </div>
            </div>
            <div class="step-item">
                <div class="step-num">3</div>
                <div>Đảm bảo quyền <strong>offline_access</strong> đã được bật trên Lark Console.</div>
            </div>
        </div>

        <a href="{auth_url}" class="btn">🚀 Bấm vào đây để Đăng nhập &amp; Cấp quyền</a>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)


# =============================================================================
# 2. GET /auth/lark/callback (ENDPOINT NHẬN CODE & LẤY REFRESH TOKEN)
# =============================================================================

@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    request: Request,
    code: Optional[str] = Query(None, description="Mã authorization code do Lark trả về"),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    format: Optional[str] = Query(None),
    accept: Optional[str] = Header(None),
):
    """
    Endpoint tiếp nhận redirect từ Lark sau khi người dùng chấp thuận ủy quyền.
    Tự động đổi `code` lấy `access_token` và `refresh_token`, lưu vào MongoDB.
    """
    # 1. Xử lý trường hợp Lark trả về lỗi hoặc user từ chối
    if error:
        err_msg = error_description or error
        logger.warning(f"Lark OAuth Callback báo lỗi: {error} - {err_msg}")
        if format == "json" or (accept and "application/json" in accept):
            return JSONResponse(status_code=400, content={"success": False, "error": error, "description": err_msg})
        
        return HTMLResponse(
            status_code=400,
            content=f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8"><title>Ủy quyền Thất bại</title>
    <style>body {{ font-family: sans-serif; background: #0f172a; color: #fff; padding: 40px; text-align: center; }}</style>
</head>
<body>
    <h1 style="color: #ef4444;">❌ Ủy quyền Thất bại</h1>
    <p style="color: #94a3b8; margin: 20px 0;">Mã lỗi: {error} - {err_msg}</p>
    <a href="/auth/lark/login" style="color: #818cf8;">Thử lại</a>
</body></html>"""
        )

    if not code:
        raise HTTPException(status_code=400, detail="Thiếu tham số `code` trong callback URL!")

    # 2. Mọi luồng OAuth (setup / wizard / user_oauth) ĐỀU đi qua oauth_state_service.consume(state)
    # dùng một lần — không còn nhánh đoán prefix `setup_` cho phép bypass state store.
    from services.auth.oauth_state_service import OAuthStateError, oauth_state_service
    from services.tenancy.tenant_resolver import tenant_resolver
    from core.tenant_errors import TenantResolutionError

    wants_json = format == "json" or (accept and "application/json" in accept)

    try:
        state_doc = await oauth_state_service.consume(state)
    except OAuthStateError as state_err:
        logger.warning("Callback OAuth bị từ chối: %s", state_err)
        if wants_json:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": state_err.error_code, "description": str(state_err)},
            )
        return _oauth_error_page(400, "Phiên ủy quyền không hợp lệ", str(state_err))

    state_tenant = state_doc["tenant_key"]
    state_app_id = state_doc["app_id"]
    state_purpose = state_doc.get("purpose") or ""

    if state_purpose == "setup":
        import asyncio
        from services.setup.one_click_setup_service import one_click_setup_service

        eff_task_id = await one_click_setup_service.resume_task_from_state(state_doc)
        if not eff_task_id:
            if wants_json:
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": "oauth_state_invalid",
                        "description": "Phiên One-Click Setup thiếu task_id hợp lệ.",
                    },
                )
            return _oauth_error_page(
                400,
                "Phiên cài đặt không hợp lệ",
                "OAuth state của setup thiếu task_id hợp lệ. Vui lòng bắt đầu lại từ /setup.",
            )
        logger.info("[ONE_CLICK_SETUP] callback_received task_id=%s", eff_task_id)
        asyncio.create_task(
            one_click_setup_service.run_setup_pipeline(task_id=eff_task_id, code=code, state=state)
        )
        return RedirectResponse(url=f"/setup?task_id={eff_task_id}")

    try:
        credentials = await tenant_resolver.resolve_credentials(state_tenant)
    except TenantResolutionError as cred_err:
        if wants_json:
            return JSONResponse(
                status_code=cred_err.http_status,
                content={"success": False, "error": cred_err.error_code, "description": str(cred_err)},
            )
        return _oauth_error_page(cred_err.http_status, "App của tenant không còn hợp lệ", str(cred_err))

    if credentials.app_id != state_app_id:
        # State được phát hành cho App A nhưng tenant giờ đã trỏ sang App B: phải ủy quyền
        # lại bằng App mới, không được đổi code của App B bằng link của App A.
        return _oauth_error_page(
            400,
            "App đã thay đổi sau khi bắt đầu ủy quyền",
            f"State phát hành cho App '{state_app_id}' nhưng tenant '{state_tenant}' hiện trỏ "
            f"sang App '{credentials.app_id}'. Vui lòng ủy quyền lại.",
        )

    try:
        result = await token_service.exchange_code_for_token(
            code=code,
            app_id=credentials.app_id,
            app_secret=credentials.app_secret,
            expected_tenant_key=state_tenant,
        )
    except TenantResolutionError as e:
        logger.error("Lỗi tenant khi đổi token trong callback: %s", e, exc_info=True)
        status = getattr(e, "http_status", 400)
        if wants_json:
            return JSONResponse(
                status_code=status,
                content={"success": False, "error": getattr(e, "error_code", "token_exchange_failed"), "description": str(e)},
            )
        return _oauth_error_page(status, "Đổi Token Thất Bại", str(e))
    except Exception as e:
        logger.error(f"Lỗi khi đổi token trong callback: {e}", exc_info=True)
        if format == "json" or (accept and "application/json" in accept):
            return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
        
        return HTMLResponse(
            status_code=500,
            content=f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8"><title>Lỗi Đổi Token</title>
    <style>body {{ font-family: sans-serif; background: #0f172a; color: #fff; padding: 40px; text-align: center; }}</style>
</head>
<body>
    <h1 style="color: #ef4444;">⚠️ Đổi Token Thất Bại</h1>
    <p style="color: #cbd5e1; margin: 20px 0;">{str(e)}</p>
    <a href="/auth/lark/login" style="color: #818cf8;">Quay lại màn hình đăng nhập</a>
</body></html>"""
        )

    # Cổng Onboarding Gate (Phase 4): nếu tenant đang tạm dừng ở `awaiting_user_oauth`,
    # kích hoạt tự động provisioning -> READY & gửi thẻ bàn giao.
    try:
        from services.tenancy.tenant_state import AWAITING_USER_OAUTH, tenant_state

        tenant_doc = await tenant_state.get_status(state_tenant)
        if isinstance(tenant_doc, dict) and tenant_doc.get("status") == AWAITING_USER_OAUTH:
            from services.lark.handlers.tenant_lifecycle_handler import (
                provision_tenant_and_send_handover,
            )

            eff_admin = (
                (result.get("open_id") or "").strip()
                or (tenant_doc.get("admin_open_id") or "").strip()
                or None
            )
            await provision_tenant_and_send_handover(
                tenant_key=state_tenant,
                app_id=credentials.app_id,
                admin_open_id=eff_admin,
                raw_event_type="oauth_callback",
            )
    except Exception as prov_resume_err:
        logger.warning(
            "[AUTH_CALLBACK] oauth_provision_resume_failed tenant=%s err=%s",
            state_tenant,
            prov_resume_err,
        )

    # Nếu caller yêu cầu JSON
    if format == "json" or (accept and "application/json" in accept):
        return JSONResponse(content=result)

    user_name = result.get("user_name", "User")
    open_id = result.get("open_id", "")
    access_token = result.get("access_token", "")
    refresh_token = result.get("refresh_token", "")
    expires_at = result.get("expires_at_readable", "")
    refresh_expires_at = result.get("refresh_expires_at_readable", "")

    safe_user_name = html.escape(str(user_name or "User"))
    safe_open_id = html.escape(str(open_id or ""))
    safe_expires_at = html.escape(str(expires_at or ""))
    safe_refresh_expires_at = html.escape(str(refresh_expires_at or ""))
    js_user_name = json.dumps(str(user_name or "User"), ensure_ascii=False).replace("<", "\\u003c")
    js_open_id = json.dumps(str(open_id or ""), ensure_ascii=False).replace("<", "\\u003c")
    masked_refresh_token = html.escape(mask_token_preview(refresh_token) or "Đã lưu an toàn")
    masked_access_token = html.escape(mask_token_preview(access_token) or "Đã lưu an toàn")

    # 2.5 Nếu request đến từ Screen Guide Wizard (purpose của state, hoặc param source=wizard)
    is_wizard_source = bool(state_purpose == "wizard" or request.query_params.get("source") == "wizard")
    if is_wizard_source:
        return HTMLResponse(
            content=f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HiLark — Ủy Quyền Thành Công</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
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
            background: rgba(30, 41, 59, 0.85);
            border: 1px solid rgba(16, 185, 129, 0.4);
            border-radius: 20px;
            padding: 32px 24px;
            max-width: 420px;
            width: 100%;
            backdrop-filter: blur(20px);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
        }}
        .btn {{
            display: inline-block;
            margin-top: 18px;
            background: #10b981;
            color: #fff;
            padding: 10px 20px;
            border-radius: 10px;
            font-weight: 700;
            text-decoration: none;
            cursor: pointer;
            border: none;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div style="font-size: 48px; margin-bottom: 12px;">🎉</div>
        <h2 style="color: #34d399; margin-bottom: 8px;">Ủy Quyền Thành Công!</h2>
        <p style="color: #94a3b8; font-size: 14px; line-height: 1.5;">
            Đã kết nối tài khoản đại diện <strong>{safe_user_name}</strong>.<br/>
            Cửa sổ này sẽ tự đóng lại để quay về Trình thiết lập...
        </p>
        <button onclick="finishAuth()" class="btn">Quay lại Wizard</button>
    </div>
    <script>
        function finishAuth() {{
            if (window.opener) {{
                try {{
                    window.opener.postMessage({{
                        type: 'LARK_AUTH_SUCCESS',
                        user_name: {js_user_name},
                        open_id: {js_open_id}
                    }}, '*');
                }} catch (e) {{}}
                window.close();
            }} else {{
                window.location.href = '/onboarding/wizard?step=4&auth=success';
            }}
        }}
        setTimeout(finishAuth, 1200);
    </script>
</body>
</html>"""
        )

    # 3. Trả về giao diện HTML đã che giấu token nguyên văn (chỉ hiển thị preview & trạng thái)

    html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HiLark — Kết nối Thành công &amp; Đã Lưu Token</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Inter', -apple-system, sans-serif;
            background: linear-gradient(135deg, #090d16 0%, #111827 100%);
            color: #f8fafc;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }}
        .card {{
            background: rgba(30, 41, 59, 0.85);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 20px;
            padding: 36px;
            max-width: 640px;
            width: 100%;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.6);
        }}
        .success-icon {{
            width: 56px;
            height: 56px;
            background: rgba(34, 197, 94, 0.15);
            border: 1px solid rgba(34, 197, 94, 0.3);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 28px;
            margin-bottom: 20px;
        }}
        h1 {{ font-size: 22px; font-weight: 700; color: #fff; margin-bottom: 8px; }}
        p.subtitle {{ color: #94a3b8; font-size: 14px; margin-bottom: 24px; }}

        .section-title {{
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #818cf8;
            margin-bottom: 8px;
        }}
        .token-group {{
            margin-bottom: 20px;
        }}
        .input-wrapper {{
            display: flex;
            background: #0f172a;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            overflow: hidden;
        }}
        .token-input {{
            flex: 1;
            background: transparent;
            border: none;
            padding: 12px 14px;
            color: #38bdf8;
            font-family: monospace;
            font-size: 13px;
            outline: none;
        }}
        .meta-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 24px;
        }}
        .meta-item {{
            background: rgba(15, 23, 42, 0.5);
            padding: 12px 14px;
            border-radius: 10px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }}
        .meta-label {{ font-size: 11px; color: #64748b; margin-bottom: 4px; }}
        .meta-val {{ font-size: 13px; font-weight: 600; color: #f1f5f9; }}

        .alert-box {{
            background: rgba(56, 189, 248, 0.1);
            border: 1px solid rgba(56, 189, 248, 0.2);
            border-radius: 10px;
            padding: 14px;
            font-size: 13px;
            color: #bae6fd;
            line-height: 1.5;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="success-icon">🎉</div>
        <h1>Kết nối Thành công &amp; Đã Lưu Token</h1>
        <p class="subtitle">Tài khoản của Sếp đã được liên kết với HiLark Assistant. Hệ thống đã kích hoạt cơ chế tự động xoay vòng và mã hóa an toàn.</p>

        <div class="meta-grid">
            <div class="meta-item">
                <div class="meta-label">Người dùng</div>
                <div class="meta-val">{safe_user_name}</div>
            </div>
            <div class="meta-item">
                <div class="meta-label">Open ID</div>
                <div class="meta-val">{safe_open_id}</div>
            </div>
            <div class="meta-item">
                <div class="meta-label">Hết hạn Access Token (~2 giờ)</div>
                <div class="meta-val">{safe_expires_at}</div>
            </div>
            <div class="meta-item">
                <div class="meta-label">Hết hạn Refresh Token (~30 ngày)</div>
                <div class="meta-val">{safe_refresh_expires_at}</div>
            </div>
        </div>

        <div class="token-group">
            <div class="section-title">Refresh Token (đã che giấu để bảo mật):</div>
            <div class="input-wrapper">
                <input type="text" id="refreshTokenPreview" class="token-input" value="{masked_refresh_token}" readonly>
            </div>
        </div>

        <div class="token-group">
            <div class="section-title">User Access Token (đã che giấu để bảo mật):</div>
            <div class="input-wrapper">
                <input type="text" id="accessTokenPreview" class="token-input" value="{masked_access_token}" readonly>
            </div>
        </div>

        <div class="alert-box">
            🛡️ <strong>Hệ thống đã tự động lưu &amp; mã hóa:</strong> Cặp token đã được mã hóa AES-256 Fernet vào MongoDB collection <code>lark_auth</code>. Hệ thống không hiển thị token nguyên văn trên trình duyệt để tránh lộ bí mật xác thực.
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)


# =============================================================================
# 3. POST /auth/lark/exchange (REST API ĐỔI CODE)
# =============================================================================

@router.post("/exchange")
async def exchange_code(payload: ExchangeCodeRequest):
    """
    Endpoint API đổi Authorization Code lấy Token bằng POST JSON.

    Phải nói rõ tenant (`tenant_key` trong body hoặc ContextVar của request): đổi code
    bằng App mặc định trong .env là cách token bị gán nhầm cho doanh nghiệp khác.
    """
    from database.db import get_current_tenant_key
    from services.tenancy.tenant_resolver import tenant_resolver
    from core.tenant_errors import TenantResolutionError, TokenUnavailable

    eff_tenant = (payload.tenant_key or "").strip() or get_current_tenant_key()
    if not eff_tenant:
        raise HTTPException(
            status_code=400,
            detail="Thiếu `tenant_key`: /auth/lark/exchange cần biết code thuộc doanh nghiệp nào.",
        )
    try:
        credentials = await tenant_resolver.resolve_credentials(eff_tenant)
    except (TenantResolutionError, TokenUnavailable):
        # Nhả lỗi có kiểu lên handler cấp app: HTTPException(detail=str(err)) giữ đúng
        # mã trạng thái nhưng làm mất `error_code` và `tenant_key` trong body.
        raise

    try:
        result = await token_service.exchange_code_for_token(
            code=payload.code,
            redirect_uri=payload.redirect_uri,
            app_id=credentials.app_id,
            app_secret=credentials.app_secret,
            expected_tenant_key=eff_tenant,
        )
        return result
    except (TenantResolutionError, TokenUnavailable):
        # 409 (tenant chưa ready/thiếu config), 401 (cần uỷ quyền lại), 503 (Lark từ chối
        # cấp token) — phân biệt rõ thay vì gộp tất cả vào 400.
        raise
    except Exception as e:
        logger.error(f"Lỗi exchange code qua API: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# 4. GET /auth/lark/status (KIỂM TRA SỨC KHỎE TOKEN)
# =============================================================================

@router.get("/status")
async def token_status(
    tenant_key: Optional[str] = Query(None, description="Mã doanh nghiệp (tenant_key) cần kiểm tra"),
):
    """Tra cứu trạng thái sống còn của Token trong MongoDB theo đúng tenant."""
    from core.tenant_errors import TenantContextMissing
    from database.db import get_current_tenant_key

    eff_tenant = (tenant_key or "").strip() or get_current_tenant_key()
    if not eff_tenant:
        raise TenantContextMissing("Thiếu `tenant_key`: GET /auth/lark/status yêu cầu tenant_key.")
    return await token_service.get_token_status(tenant_key=eff_tenant)


# =============================================================================
# 5. POST /auth/lark/refresh (KÍCH HOẠT REFRESH THỦ CÔNG)
# =============================================================================

@router.post("/refresh")
async def manual_refresh(
    tenant_key: Optional[str] = Query(None, description="Mã doanh nghiệp (tenant_key) cần làm mới token"),
):
    """Chủ động kích hoạt xoay vòng Token ngay lập tức cho đúng tenant."""
    from core.tenant_errors import TenantContextMissing, TenantResolutionError, TokenUnavailable
    from database.db import get_current_tenant_key

    eff_tenant = (tenant_key or "").strip() or get_current_tenant_key()
    if not eff_tenant:
        raise TenantContextMissing("Thiếu `tenant_key`: POST /auth/lark/refresh yêu cầu tenant_key.")
    try:
        return await token_service.refresh_user_token(force=True, tenant_key=eff_tenant)
    except (TenantResolutionError, TokenUnavailable):
        raise
    except Exception as e:
        logger.error(f"Lỗi khi gọi manual refresh: {e}")
        raise HTTPException(status_code=400, detail=str(e))
