"""
HiLark Auth Domain Package
==========================
Vị trí: server/services/auth/

Chứa toàn bộ các dịch vụ và tiện ích liên quan đến xác thực người dùng và quản lý Token Lark:
  - token_service: LarkTokenService (OAuth 2.0 / OIDC code exchange, single-use token rotation, auto-refresh loop).
  - token_verifier: Tiện ích kiểm tra, decode JWT, ping xác thực Network và safe fallback (chuyển từ utils/lark_token.py).
"""

from services.auth.token_service import (
    PRIMARY_TOKEN_DOC_ID,
    VIETNAM_TZ,
    format_remaining_seconds,
    LarkTokenService,
    token_service,
    start_token_refresh_loop,
)
from services.auth.token_verifier import (
    TokenCheckResult,
    parse_jwt_expiration,
    ping_user_access_token,
    aping_user_access_token,
    check_and_warn_token,
    decode_jwt_token_payload,
)

__all__ = [
    "PRIMARY_TOKEN_DOC_ID",
    "VIETNAM_TZ",
    "format_remaining_seconds",
    "LarkTokenService",
    "token_service",
    "start_token_refresh_loop",
    "TokenCheckResult",
    "parse_jwt_expiration",
    "ping_user_access_token",
    "aping_user_access_token",
    "check_and_warn_token",
    "decode_jwt_token_payload",
]
