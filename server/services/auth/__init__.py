"""
HiLark Auth Domain Package
==========================
Vị trí: server/services/auth/

Chứa toàn bộ các dịch vụ và tiện ích liên quan đến xác thực người dùng và quản lý Token Lark:
  - token_service: LarkTokenService (OAuth 2.0 / OIDC code exchange, single-use token rotation).
  - tenant_token_manager: TokenBroker theo `(tenant_key, app_id, kind)`, dùng qua token loop riêng.
  - tenant_refresh_sweeper: giữ token user của các tenant `ready` còn hạn (thay loop toàn cục cũ).
  - token_verifier: Tiện ích kiểm tra, decode JWT, ping xác thực Network và safe fallback (chuyển từ utils/lark_token.py).
"""

from services.auth.token_service import (
    PRIMARY_TOKEN_DOC_ID,
    VIETNAM_TZ,
    format_remaining_seconds,
    LarkTokenService,
    token_service,
)
from services.auth.tenant_refresh_sweeper import (
    TenantTokenSweeper,
    start_tenant_token_sweeper,
    sweeper as tenant_token_sweeper,
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
    "TenantTokenSweeper",
    "tenant_token_sweeper",
    "start_tenant_token_sweeper",
    "TokenCheckResult",
    "parse_jwt_expiration",
    "ping_user_access_token",
    "aping_user_access_token",
    "check_and_warn_token",
    "decode_jwt_token_payload",
]
