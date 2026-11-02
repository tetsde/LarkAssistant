"""
Owner DM Interaction Handler for Lark Bot (DM 1-1)
==================================================
Vị trí: server/services/lark/handlers/owner_command_handler.py

Mục đích:
    - Điều phối tương tác giữa Trợ lý HiLark và Lãnh đạo / Quản trị viên trong hội thoại riêng DM 1-1.
    - 100% hướng tương tác qua Thẻ tương tác (Interactive Card Hub) với các nút bấm 1-Click.
    - Tuyệt đối không sử dụng câu lệnh dòng lệnh (slash commands hoặc text commands).
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from models.lark import LarkMessage
from database.db import get_tenant_config, get_tenants_collection, get_chat_scopes_collection
from services.digest_service import digest_service
from services.draft_service import draft_service
from services.lark import lark_service as default_lark_service
from services.lark.card_builder import (
    build_owner_control_hub_card,
    build_onboarding_welcome_card,
)

logger = logging.getLogger("hilark.bot.owner_command_handler")


def _resolve_lark_service():
    from services.lark.runtime import get_current_lark_service
    bs = sys.modules.get("services.bot_service") or sys.modules.get("services.lark.bot_runner")
    fallback = getattr(bs, "lark_service", default_lark_service) if bs else default_lark_service
    return get_current_lark_service(fallback)


async def handle_owner_dm_command(msg: LarkMessage) -> bool:
    """
    Xử lý tương tác trong DM 1-1 với Lãnh đạo / Quản trị viên.
    Hoàn toàn sử dụng Thẻ tương tác (Interactive Card) với nút bấm 1-Click.
    Không xử lý bằng câu lệnh văn bản.
    """
    lark_service = _resolve_lark_service()

    # 1. Xác định tenant_key của người gửi
    tenant_key = getattr(msg, "tenant_key", None)
    if not tenant_key:
        try:
            t_col = get_tenants_collection()
            found_t = await t_col.find_one({"admin_open_id": msg.sender_id})
            if found_t:
                tenant_key = found_t.get("tenant_key")
        except Exception as e:
            logger.debug(f"Không thể tìm tenant cho admin {msg.sender_id}: {e}")

    # 2. Lấy cấu hình doanh nghiệp (nếu có)
    tenant_cfg = None
    if tenant_key:
        tenant_cfg = await get_tenant_config(tenant_key)

    # 3. Đếm số nhóm chat đang hoạt động
    active_chat_count = 0
    if tenant_key:
        try:
            c_col = get_chat_scopes_collection()
            active_chat_count = await c_col.count_documents({"tenant_key": tenant_key})
        except Exception as e:
            logger.debug(f"Không thể đếm nhóm chat: {e}")

    # 4. Kiểm tra báo cáo ngày hoặc bản nháp đang chờ duyệt (nếu có)
    latest_master = None
    try:
        latest_master = await digest_service.get_latest_pending_master_digest()
    except Exception as e:
        logger.debug(f"Lỗi kiểm tra master digest: {e}")

    latest_draft = None
    try:
        latest_draft = await draft_service.get_latest_pending(msg.sender_id)
    except Exception as e:
        logger.debug(f"Lỗi kiểm tra pending draft: {e}")

    user_name = getattr(msg, "user_name", "") or getattr(msg, "sender_name", "") or ""

    # 5. Xây dựng Thẻ Điều Hành Tương Tác (Executive Control Hub Card)
    if tenant_cfg:
        card = build_owner_control_hub_card(
            tenant_config=tenant_cfg,
            user_name=user_name,
            open_id=msg.sender_id,
            pending_digest=latest_master,
            pending_draft=latest_draft,
            active_chat_count=active_chat_count,
        )
    else:
        # Trường hợp workspace chưa cấu hình hoặc chế độ Single-Tenant chưa gắn tenant record
        card = build_onboarding_welcome_card(
            open_id=msg.sender_id,
            user_name=user_name,
            tenant_key=tenant_key,
        )

    # 6. Gửi thẻ điều hành qua DM cho chủ nhân
    await lark_service.send_bot_card_to_owner(
        card,
        target_open_id=msg.sender_id,
        tenant_key=tenant_key,
    )
    return True
