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

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from core.config import settings
from services.auth_service import token_service

logger = logging.getLogger("hilark.router.auth")
router = APIRouter(prefix="/auth/lark", tags=["auth"])


class ExchangeCodeRequest(BaseModel):
    code: str
    redirect_uri: Optional[str] = None


# =============================================================================
# 1. GET /auth/lark/login
# =============================================================================

@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    redirect: bool = Query(False, description="Nếu True sẽ tự động chuyển hướng sang Lark"),
    redirect_uri: Optional[str] = Query(None, description="Tùy chỉnh redirect_uri"),
):
    """
    Tạo link ủy quyền OAuth2 của Lark.
    Có thể hiển thị trang giao diện bấm nút hoặc chuyển hướng trực tiếp.
    """
    # Tự động suy luận redirect_uri từ domain hiện tại nếu người dùng không truyền vào
    effective_redirect_uri = redirect_uri or settings.LARK_OAUTH_REDIRECT_URI
    if not effective_redirect_uri:
        base_url = str(request.base_url).rstrip("/")
        effective_redirect_uri = f"{base_url}/auth/lark/callback"

    auth_url = token_service.get_authorize_url(redirect_uri=effective_redirect_uri)

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
                <div>App ID hiện tại: <span class="code-box">{settings.LARK_APP_ID}</span></div>
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

    # 2. Tiến hành đổi code lấy cặp token
    try:
        result = await token_service.exchange_code_for_token(code=code)
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

    # Nếu caller yêu cầu JSON
    if format == "json" or (accept and "application/json" in accept):
        return JSONResponse(content=result)

    # 3. Trả về giao diện HTML hoàn chỉnh, rực rỡ với Refresh Token cho Sếp
    user_name = result.get("user_name", "User")
    open_id = result.get("open_id", "")
    access_token = result.get("access_token", "")
    refresh_token = result.get("refresh_token", "")
    expires_at = result.get("expires_at_readable", "")
    refresh_expires_at = result.get("refresh_expires_at_readable", "")

    html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HiLark — Kết nối Thành công &amp; Refresh Token</title>
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
        .copy-btn {{
            background: rgba(99, 102, 241, 0.2);
            color: #818cf8;
            border: none;
            padding: 0 16px;
            font-weight: 600;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s;
            border-left: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .copy-btn:hover {{
            background: #4f46e5;
            color: #fff;
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
        <p class="subtitle">Tài khoản của Sếp đã được liên kết với HiLark Assistant. Hệ thống đã kích hoạt cơ chế tự động xoay vòng vĩnh viễn.</p>

        <div class="meta-grid">
            <div class="meta-item">
                <div class="meta-label">Người dùng</div>
                <div class="meta-val">{user_name}</div>
            </div>
            <div class="meta-item">
                <div class="meta-label">Open ID</div>
                <div class="meta-val">{open_id}</div>
            </div>
            <div class="meta-item">
                <div class="meta-label">Hết hạn Access Token (~2 giờ)</div>
                <div class="meta-val">{expires_at}</div>
            </div>
            <div class="meta-item">
                <div class="meta-label">Hết hạn Refresh Token (~30 ngày)</div>
                <div class="meta-val">{refresh_expires_at}</div>
            </div>
        </div>

        <div class="token-group">
            <div class="section-title">🔑 Refresh Token của bạn (Dùng để duy trì và xoay vòng):</div>
            <div class="input-wrapper">
                <input type="text" id="refreshTokenInput" class="token-input" value="{refresh_token}" readonly>
                <button class="copy-btn" onclick="copyToken('refreshTokenInput', this)">📋 Copy</button>
            </div>
        </div>

        <div class="token-group">
            <div class="section-title">⚡ User Access Token hiện tại (Tự động refresh trước khi hết hạn):</div>
            <div class="input-wrapper">
                <input type="text" id="accessTokenInput" class="token-input" value="{access_token}" readonly>
                <button class="copy-btn" onclick="copyToken('accessTokenInput', this)">📋 Copy</button>
            </div>
        </div>

        <div class="alert-box">
            🛡️ <strong>Hệ thống đã tự động lưu:</strong> Toàn bộ cặp token này đã được lưu nguyên tử vào MongoDB collection <code>lark_auth</code> và nạp vào bộ nhớ RAM. Sếp không cần copy paste vào <code>.env</code> hay restart server nữa!
        </div>
    </div>

    <script>
        function copyToken(elementId, btn) {{
            var copyText = document.getElementById(elementId);
            copyText.select();
            copyText.setSelectionRange(0, 99999);
            navigator.clipboard.writeText(copyText.value).then(function() {{
                var originalText = btn.innerText;
                btn.innerText = '✅ Đã Copy!';
                setTimeout(function() {{ btn.innerText = originalText; }}, 2000);
            }});
        }}
    </script>
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
    Hữu ích khi test qua cURL, Postman hoặc frontend client riêng.
    """
    try:
        result = await token_service.exchange_code_for_token(
            code=payload.code,
            redirect_uri=payload.redirect_uri,
        )
        return result
    except Exception as e:
        logger.error(f"Lỗi exchange code qua API: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# 4. GET /auth/lark/status (KIỂM TRA SỨC KHỎE TOKEN)
# =============================================================================

@router.get("/status")
async def token_status():
    """Tra cứu trạng thái sống còn của Token trong MongoDB & RAM."""
    return await token_service.get_token_status()


# =============================================================================
# 5. POST /auth/lark/refresh (KÍCH HOẠT REFRESH THỦ CÔNG)
# =============================================================================

@router.post("/refresh")
async def manual_refresh():
    """Chủ động kích hoạt xoay vòng Token ngay lập tức để kiểm chứng logic."""
    try:
        return await token_service.refresh_user_token(force=True)
    except Exception as e:
        logger.error(f"Lỗi khi gọi manual refresh: {e}")
        raise HTTPException(status_code=400, detail=str(e))
