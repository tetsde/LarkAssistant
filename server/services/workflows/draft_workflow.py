"""Approval and Lark delivery operations for persisted reply drafts."""

from __future__ import annotations

import asyncio
import inspect
import logging
import sys
from typing import Any, Dict, Optional, Set, Tuple

from services.workflows.draft_store import PendingDraft, draft_store

logger = logging.getLogger(__name__)


def _get_draft_store():
    shim = sys.modules.get("services.draft_service")
    if shim and hasattr(shim, "draft_store"):
        return shim.draft_store
    return draft_store


def _get_lark_service():
    from services.lark import lark_service
    from services.lark.runtime import get_current_lark_service

    shim = sys.modules.get("services.draft_service")
    if shim and hasattr(shim, "lark_service") and shim.lark_service is not lark_service:
        return shim.lark_service
    return get_current_lark_service(lark_service)


class DraftService:
    def __init__(self, store=None):
        self._has_custom_store = store is not None
        self.store = store or _get_draft_store()
        self._bg_tasks: Set[asyncio.Task] = set()

    def _active_store(self):
        if not getattr(self, "_has_custom_store", False):
            self.store = _get_draft_store()
        return self.store

    async def send_latest(
        self,
        owner_id: str,
        approved_content: Optional[str] = None,
        tenant_key: Optional[str] = None,
        background: bool = False,
        draft_id: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[PendingDraft], Optional[Dict[str, Any]]]:
        # Tự động refresh store nếu đang dùng singleton mặc định và bị mock patch
        store = self._active_store()
        draft = None
        if draft_id and hasattr(store, "claim_draft"):
            draft = await store.claim_draft(owner_id, draft_id=draft_id, tenant_key=tenant_key)
        if not draft:
            draft = await store.claim_latest_pending(owner_id, tenant_key=tenant_key)
        if not draft:
            return False, "Không có bản nháp nào đang chờ duyệt.", None, None
        content = approved_content or draft.approved_content or draft.draft_answer

        if background:
            # Chạy nền ngay trên event loop chính, khôi phục đầy đủ ContextVar tenant & runtime service
            from database.scoped_query import async_tenant_context
            from services.lark.runtime import (
                get_current_lark_service,
                reset_current_lark_service,
                set_current_lark_service,
            )

            captured_tenant = tenant_key or getattr(draft, "tenant_key", None)
            captured_service = get_current_lark_service(None)

            async def _run_bg_send() -> None:
                async with async_tenant_context(captured_tenant):
                    svc = captured_service
                    if svc is None and captured_tenant:
                        try:
                            from services.lark_app_service import lark_app_service
                            from services.lark.runtime import get_or_create_lark_service

                            app_record = await lark_app_service.get_by_tenant_key(captured_tenant)
                            if app_record:
                                svc = await get_or_create_lark_service(app_record)
                        except Exception as exc:
                            logger.warning(
                                "[DRAFT] bg_resolve_runtime_failed tenant=%s error=%s",
                                captured_tenant,
                                exc,
                            )
                    tok = set_current_lark_service(svc) if svc is not None else None
                    try:
                        await self._send_claimed(draft, content)
                    except Exception:
                        logger.exception(
                            "[DRAFT] bg_send_failed draft_id=%s tenant=%s",
                            getattr(draft, "id", None),
                            captured_tenant,
                        )
                    finally:
                        if tok is not None:
                            reset_current_lark_service(tok)

            task = asyncio.create_task(_run_bg_send())
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
            draft.status = "sent"
            draft.approved_content = content
            return True, "sent", draft, {"success": True}

        return await self._send_claimed(draft, content)

    async def discard_latest(self, owner_id: str, tenant_key: Optional[str] = None) -> Optional[PendingDraft]:
        return await self._active_store().discard_latest_pending(owner_id, tenant_key=tenant_key)

    async def get_latest_pending(self, owner_id: str, tenant_key: Optional[str] = None) -> Optional[PendingDraft]:
        return await self._active_store().get_latest_pending(owner_id, tenant_key=tenant_key)

    async def update_content(self, draft_id: str, new_draft_answer: str) -> bool:
        return await self._active_store().update_draft_content(draft_id, new_draft_answer)

    async def _send_claimed(
        self,
        draft: PendingDraft,
        content: str,
    ) -> Tuple[bool, str, PendingDraft, Optional[Dict[str, Any]]]:
        lark = _get_lark_service()

        try:
            response = await lark.areply_text(
                message_id=draft.message_id,
                text=content,
                as_user=True,
                tenant_key=draft.tenant_key,  # ✅ FIX: truyền đúng tenant để lấy đúng token
            )
        except Exception as exc:
            err_str = str(exc)
            if "UserTokenMissing" in type(exc).__name__ or "user_token_missing" in err_str:
                await self._notify_user_reauth_dm(lark, draft, reason=err_str)
            error = await self._restore_pending(draft, err_str, content)
            return False, error, draft, None

        if not isinstance(response, dict) or not response.get("success"):
            error = "Lark không xác nhận đã gửi tin nhắn."
            if isinstance(response, dict):
                error = response.get("msg") or response.get("error") or error
                err_code = str(response.get("error_code") or response.get("error") or "").strip()
                lark_code = response.get("code")
                if err_code in ("user_token_missing", "token_expired", "token_unavailable") or lark_code in (
                    99991663, 99991668, 99991677, 20005, 99991665
                ):
                    await self._notify_user_reauth_dm(lark, draft, reason=error)
            state_error = await self._restore_pending(draft, error, content)
            return False, state_error, draft, response if isinstance(response, dict) else None

        reply_data = response.get("data") if isinstance(response, dict) else None
        bot_msg_id = getattr(reply_data, "message_id", None) if reply_data else None
        if not bot_msg_id and isinstance(reply_data, dict):
            bot_msg_id = reply_data.get("message_id")

        if bot_msg_id and draft.message_id:
            try:
                from database.db import save_bot_reply_to_staging
                await save_bot_reply_to_staging(draft.message_id, bot_msg_id)
            except Exception as stg_err:
                logger.debug(f"Không thể lưu bot_reply_message_id vào staging: {stg_err}")

        if not await self.store.mark_sent(draft.id, content, bot_reply_message_id=bot_msg_id):
            return False, "Lark đã nhận tin nhưng không lưu được trạng thái sent vào MongoDB.", draft, response

        draft.status = "sent"
        draft.approved_content = content
        draft.bot_reply_message_id = bot_msg_id
        return True, "sent", draft, response

    async def _notify_user_reauth_dm(
        self,
        lark: Any,
        draft: PendingDraft,
        reason: Optional[str] = None,
    ) -> None:
        """Gửi thẻ nhắc ủy quyền lại tới DM của Lãnh đạo khi gửi nháp nhân danh User thất bại do thiếu/hết hạn token."""
        try:
            owner_id = (getattr(draft, "owner_id", "") or "").strip()
            if not owner_id or owner_id == "ou_admin_fallback":
                return
            dm_fn = getattr(lark, "send_bot_dm_to_owner", None)
            if not callable(dm_fn):
                return
            from services.lark.card_builder import build_user_reauth_card

            eff_tenant = getattr(draft, "tenant_key", None)
            card = build_user_reauth_card(tenant_key=eff_tenant, reason=reason)
            res = dm_fn(card, target_open_id=owner_id, tenant_key=eff_tenant)
            if inspect.isawaitable(res):
                await res
        except Exception as exc:
            logger.warning(
                "[DRAFT] send_reauth_dm_failed draft_id=%s tenant=%s error=%s",
                getattr(draft, "id", None),
                getattr(draft, "tenant_key", None) or "-",
                exc,
            )

    async def _restore_pending(self, draft: PendingDraft, error: str, content: str) -> str:
        try:
            restored = await self.store.mark_pending(draft.id, error, content)
        except Exception as exc:
            logger.exception("Could not restore draft %s to pending", draft.id)
            return f"{error}; MongoDB cũng không lưu được trạng thái pending: {exc}"
        if not restored:
            return f"{error}; MongoDB không xác nhận trạng thái pending cho draft này."
        return error


draft_service = DraftService()

__all__ = ["DraftService", "draft_service"]
