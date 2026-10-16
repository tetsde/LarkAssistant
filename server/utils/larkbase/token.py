"""
HiLark - Lark Base Token Utilities
===================================
Vị trí: server/utils/larkbase/token.py

Mục đích:
    Các tiện ích giải mã và kiểm tra hạn sử dụng, scopes của Lark Access Token
    mà không phụ thuộc vào thư viện ngoài.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

VIETNAM_TZ = timezone(timedelta(hours=7))

from utils.lark_token import decode_jwt_token_payload

def inspect_bitable_token(token: str) -> Dict[str, Any]:
    """
    Kiểm tra chi tiết thông tin token Lark Bitable:
      - Trạng thái hết hạn (expired/valid)
      - Thời gian hết hạn (theo giờ Việt Nam)
      - Danh sách quyền (scopes) và kiểm tra có quyền Bitable (bitable:app) hay không
    """
    if not token:
        return {"status": "missing", "is_valid": False, "message": "Chưa có Token."}

    payload = decode_jwt_token_payload(token)
    if not payload:
        return {
            "status": "opaque_or_invalid",
            "is_valid": True,
            "message": "Token không phải JWT định dạng chuẩn hoặc là Opaque Token.",
        }

    exp = payload.get("exp")
    iat = payload.get("iat")
    scopes = payload.get("scope", "")
    now = time.time()

    is_expired = False
    remaining_sec = None
    if exp:
        remaining_sec = int(exp - now)
        is_expired = remaining_sec <= 0

    exp_dt_str = ""
    if exp:
        exp_dt = datetime.fromtimestamp(exp, tz=VIETNAM_TZ)
        exp_dt_str = exp_dt.strftime("%Y-%m-%d %H:%M:%S")

    has_bitable_scope = "bitable:app" in scopes

    return {
        "status": "expired" if is_expired else "valid",
        "is_valid": not is_expired,
        "is_expired": is_expired,
        "expires_at": exp_dt_str,
        "remaining_seconds": remaining_sec,
        "scopes": scopes,
        "has_bitable_scope": has_bitable_scope,
        "app_id": payload.get("client_id", ""),
        "user_type": payload.get("user_type", ""),
    }
