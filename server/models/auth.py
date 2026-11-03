"""
HiLark - Authentication Models
==============================
Vị trí: server/models/auth.py

Data structures cho token management và caching trong multi-tenant architecture.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class TokenType(str, Enum):
    """Loại token hỗ trợ bởi TenantTokenManager."""
    USER = "user"
    TENANT = "tenant"
    APP = "app"
    # Alias để code cũ (và test) vẫn dùng được tên "bot"; thực chất là tenant_access_token.
    BOT = "tenant"


class TokenCacheEntry(BaseModel):
    """
    Entry trong per-tenant token cache.
    
    Attributes:
        token: Access token string (encrypted hoặc plain tùy implementation)
        expires_at: Unix timestamp (seconds) khi token hết hạn
        tenant_key: Tenant key sở hữu token này
        token_type: Loại token (user/bot)
    """
    token: str = Field(..., description="Access token string")
    expires_at: float = Field(..., description="Unix timestamp (seconds) khi token hết hạn")
    tenant_key: str = Field(..., description="Tenant key sở hữu token")
    token_type: TokenType = Field(..., description="Loại token (user/tenant/app)")
    # app_id là một chiều của khoá cache. Thiếu nó, tenant đổi App mới vẫn nhận token
    # của App cũ (lỗi cô lập đa tenant).
    app_id: Optional[str] = Field(default=None, description="App sở hữu token này")

    def is_expired(self, buffer_seconds: float = 300.0) -> bool:
        """
        Kiểm tra token đã hết hạn hay sắp hết hạn.
        
        Args:
            buffer_seconds: Số giây buffer trước expiry (default: 5 phút)
        
        Returns:
            True nếu token đã hết hạn hoặc còn < buffer_seconds
        """
        import time
        return time.time() >= (self.expires_at - buffer_seconds)

    model_config = ConfigDict(use_enum_values=True)
