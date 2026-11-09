"""
HiLark - Tenant Error -> Friendly Chat Reply
============================================
Vị trí: server/services/lark/tenant_error_reply.py

Mục đích (GĐ5 của kế hoạch Tenant Resolution & Token Fix):
    Khi pipeline từ chối phục vụ vì lý do thuộc về doanh nghiệp (chưa cài đặt xong,
    thiếu cấu hình, chưa uỷ quyền), người dùng trong chat phải nhận được một câu trả
    lời ngắn và hành động được — thay vì im lặng hoặc nhận câu trả lời của doanh
    nghiệp khác.

Hợp đồng:
    - Chỉ lỗi có kiểu (`TenantResolutionError`, `TokenUnavailable`) mới được dịch
      sang tin nhắn. Lỗi hệ thống khác giữ nguyên hành vi cũ (chỉ log) để không bộc
      lộ chi tiết nội bộ cho người dùng.
    - Gửi bằng danh tính Bot (`as_user=False`), vì chính user token có thể là nguyên
      nhân lỗi. Nếu Bot token cũng không lấy được thì chỉ log, không ném tiếp: tin
      nhắn giải thích không được phép làm hỏng luồng xử lý event.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional

from core.tenant_errors import (
    AppCredentialMissing,
    BYOKConfigurationError,
    TenantConfigIncomplete,
    TenantNotReady,
    TenantResolutionError,
    TokenUnavailable,
    UserTokenMissing,
)

logger = logging.getLogger("hilark.tenant_error_reply")

SETUP_INCOMPLETE_REPLY = (
    "Doanh nghiệp chưa hoàn tất cài đặt HiLark. "
    "Quản trị viên vui lòng mở trang Setup để thử lại."
)
USER_REAUTH_REPLY = (
    "Cần uỷ quyền lại tài khoản Lark. "
    "Quản trị viên vui lòng mở trang Setup và hoàn tất bước uỷ quyền."
)
BYOK_CONFIG_ERROR_REPLY = (
    "Cấu hình AI Key (BYOK) của doanh nghiệp chưa hợp lệ hoặc đã hết hạn. "
    "Quản trị viên vui lòng mở trang Setup để kiểm tra lại."
)

# Những lỗi mà người dùng trong chat có thể làm gì đó được.
REPLYABLE_ERRORS = (
    TenantNotReady,
    TenantConfigIncomplete,
    AppCredentialMissing,
    UserTokenMissing,
    BYOKConfigurationError,
)


def reply_text_for_error(exc: BaseException) -> Optional[str]:
    """
    Ánh xạ exception -> lời nhắn cho người dùng; `None` nghĩa là chỉ log.

    Thứ tự quan trọng: `UserTokenMissing` là subclass của `TokenUnavailable` nhưng
    mang thông điệp khác (cần uỷ quyền lại), nên phải kiểm tra trước.
    `BYOKConfigurationError` cũng mang thông điệp riêng về cấu hình AI Key (BYOK),
    nên phải kiểm tra trước nhóm `REPLYABLE_ERRORS` chung.
    """
    if isinstance(exc, UserTokenMissing):
        return USER_REAUTH_REPLY
    if isinstance(exc, BYOKConfigurationError):
        return BYOK_CONFIG_ERROR_REPLY
    if isinstance(exc, REPLYABLE_ERRORS):
        return SETUP_INCOMPLETE_REPLY
    return None


def _resolve_lark_service():
    """Dùng đúng instance Lark của bot đang chạy (giống member_message_handler)."""
    from services.lark import lark_service as default_lark_service
    from services.lark.runtime import get_current_lark_service

    bs = sys.modules.get("services.bot_service") or sys.modules.get("services.lark.bot_runner")
    fallback = getattr(bs, "lark_service", default_lark_service) if bs else default_lark_service
    return get_current_lark_service(fallback)


async def reply_tenant_error(
    exc: BaseException,
    message_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    tenant_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Trả lời trong chat theo loại lỗi tenant. Không bao giờ ném exception.

    Returns:
        dict kết quả gửi (`sent`, `text`, `reason`) để caller log/test được.
    """
    text = reply_text_for_error(exc)
    error_code = getattr(exc, "error_code", type(exc).__name__)
    if not text:
        logger.info(
            "[TENANT ERROR] Không trả lời chat (error_code=%s tenant=%s): %s",
            error_code,
            tenant_key,
            exc,
        )
        return {"sent": False, "reason": "not_replyable", "error_code": error_code}

    if not message_id and not chat_id:
        logger.warning(
            "[TENANT ERROR] Bỏ qua trả lời chat vì không có message_id/chat_id "
            "(error_code=%s tenant=%s)",
            error_code,
            tenant_key,
        )
        return {"sent": False, "reason": "no_destination", "error_code": error_code}

    try:
        lark_service = _resolve_lark_service()
        if message_id:
            result = await lark_service.areply_text(
                message_id=message_id, text=text, as_user=False, tenant_key=tenant_key
            )
        else:
            result = await lark_service.asend_text(
                receive_id=chat_id, text=text, receive_id_type="chat_id",
                as_user=False, tenant_key=tenant_key,
            )
    except Exception as send_exc:
        # Bot token cũng hỏng: chỉ log, đúng tinh thần "không làm hỏng luồng event".
        logger.warning(
            "[TENANT ERROR] Không gửi được lời nhắn (error_code=%s tenant=%s): %s",
            error_code,
            tenant_key,
            send_exc,
        )
        return {"sent": False, "reason": "send_failed", "error_code": error_code, "detail": str(send_exc)}

    sent = bool(result.get("success"))
    log_line = logger.info if sent else logger.warning
    log_line(
        "[TENANT ERROR] replied=%s error_code=%s tenant=%s result=%s",
        sent,
        error_code,
        tenant_key,
        {k: result.get(k) for k in ("code", "msg", "skipped") if result.get(k) is not None},
    )
    return {"sent": sent, "text": text, "error_code": error_code, "result": result}


async def notify_tenant_error(
    exc: BaseException,
    message_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    tenant_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Điểm vào cho dispatcher/handler: chỉ xử lý khi lỗi thuộc họ tenant/token.

    Trả về `{"sent": False, "reason": "ignored"}` với exception thông thường để
    hành vi cũ (log rồi bỏ) không thay đổi.
    """
    if not isinstance(exc, (TenantResolutionError, TokenUnavailable)):
        return {"sent": False, "reason": "ignored"}
    return await reply_tenant_error(
        exc, message_id=message_id, chat_id=chat_id, tenant_key=tenant_key
    )


__all__ = [
    "SETUP_INCOMPLETE_REPLY",
    "USER_REAUTH_REPLY",
    "BYOK_CONFIG_ERROR_REPLY",
    "REPLYABLE_ERRORS",
    "reply_text_for_error",
    "reply_tenant_error",
    "notify_tenant_error",
]
