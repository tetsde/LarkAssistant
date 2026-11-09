"""
HiLark - Tenant & Token Errors
==============================
Vị trí: server/core/tenant_errors.py

Exception có kiểu cho nguyên tắc "tra cứu có hợp đồng": thiếu dữ liệu là raise,
không có giá trị thay thế. Mọi tầng (resolver, token broker, router, dispatcher)
dùng chung các lớp lỗi này để phân biệt "tenant chưa sẵn sàng" với "lỗi hệ thống".

Lịch sử:
  - 2026-11-02: Giai đoạn 1 của kế hoạch sửa Tenant Resolution & Token Flow.
"""

from __future__ import annotations

from typing import Iterable, List, Optional


class TenantResolutionError(Exception):
    """Lỗi nền cho toàn bộ cơ chế phân giải tenant."""

    error_code: str = "tenant_resolution_error"
    http_status: int = 500

    def __init__(self, message: str, tenant_key: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.tenant_key = tenant_key


class TenantContextMissing(TenantResolutionError):
    """Request/event không có tenant_key. Đây là lỗi lập trình, không phải thiếu dữ liệu."""

    error_code = "tenant_context_missing"
    http_status = 400

    def __init__(self, detail: str = "") -> None:
        msg = "Không có tenant_key trong ngữ cảnh hiện tại."
        super().__init__(f"{msg} {detail}".strip())


class TenantNotFound(TenantResolutionError):
    """tenant_key hợp lệ nhưng không có document `tenants` tương ứng."""

    error_code = "tenant_not_found"
    http_status = 409

    def __init__(self, tenant_key: str) -> None:
        super().__init__(
            f"Doanh nghiệp '{tenant_key}' chưa được ghi nhận trong hệ thống.",
            tenant_key=tenant_key,
        )


class TenantNotReady(TenantResolutionError):
    """Tenant tồn tại nhưng status != 'ready'; từ chối phục vụ cho tới khi setup xong."""

    error_code = "tenant_not_ready"
    http_status = 409

    def __init__(self, tenant_key: str, status: Optional[str] = None) -> None:
        self.status = status
        super().__init__(
            f"Doanh nghiệp '{tenant_key}' chưa hoàn tất cài đặt (trạng thái: {status or 'chưa rõ'}).",
            tenant_key=tenant_key,
        )


class TenantConfigIncomplete(TenantResolutionError):
    """Tenant đã 'ready' nhưng dữ liệu bắt buộc vẫn thiếu — vi phạm hợp đồng provisioning."""

    error_code = "tenant_config_incomplete"
    http_status = 409

    def __init__(self, tenant_key: str, missing_fields: Iterable[str]) -> None:
        self.missing_fields: List[str] = list(missing_fields)
        super().__init__(
            f"Doanh nghiệp '{tenant_key}' thiếu cấu hình bắt buộc: {', '.join(self.missing_fields) or 'không rõ'}.",
            tenant_key=tenant_key,
        )


class TokenUnavailable(Exception):
    """Không lấy được token từ Lark. Mang mã lỗi Lark nếu có, để log phân tích được."""

    error_code = "token_unavailable"
    http_status = 503

    def __init__(
        self,
        message: str,
        tenant_key: Optional[str] = None,
        kind: Optional[str] = None,
        lark_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.tenant_key = tenant_key
        self.kind = kind
        self.lark_code = lark_code


class UserTokenMissing(TokenUnavailable):
    """Tenant chưa (hoặc không còn) user access token hợp lệ; cần uỷ quyền lại."""

    error_code = "user_token_missing"
    http_status = 401

    def __init__(self, tenant_key: str, app_id: Optional[str] = None) -> None:
        self.app_id = app_id
        super().__init__(
            f"Chưa có user token cho doanh nghiệp '{tenant_key}'. "
            "Quản trị viên cần uỷ quyền lại tài khoản Lark.",
            tenant_key=tenant_key,
            kind="user",
        )


class AppCredentialMissing(TenantResolutionError):
    """Không có document credential cho chính tenant_key đó (không mượn App khác)."""

    error_code = "app_credential_missing"
    http_status = 409

    def __init__(self, tenant_key: str) -> None:
        super().__init__(
            f"Doanh nghiệp '{tenant_key}' chưa có credential App (lark_app_credentials) "
            "hoặc credential đã bị thu hồi.",
            tenant_key=tenant_key,
        )


class BYOKConfigurationError(TenantResolutionError):
    """Cấu hình BYOK không hợp lệ hoặc thiếu API key khi đã kích hoạt chế độ BYOK."""

    error_code: str = "byok_config_error"
    http_status: int = 400

    def __init__(
        self,
        message: str,
        tenant_key: Optional[str] = None,
        provider: Optional[str] = None,
        service_type: str = "llm",
    ) -> None:
        super().__init__(message, tenant_key=tenant_key)
        self.provider = provider
        self.service_type = service_type
