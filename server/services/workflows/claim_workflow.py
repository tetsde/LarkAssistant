"""
Claim Approval and Real-Time Notification Workflow for HiLark
==============================================================
Vị trí: server/services/workflows/claim_workflow.py

Mục đích:
    - Quản lý quy trình phê duyệt thông tin đề xuất (Claims / Facts) từ thành viên.
    - Gửi Thẻ tin nhắn tương tác (Lark Interactive Card) về hộp thư riêng của Lãnh đạo khi có fact proposed.
    - Cung cấp các thao tác: Duyệt thông tin (chuyển sang current), Từ chối (superseded), và Sửa giá trị.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, List, Optional, Tuple

from database.db import (
    get_claims_collection,
    get_latest_proposed_claim,
    get_pending_proposed_claims,
    promote_all_proposed_claims,
    promote_claims_by_ids,
    reject_claims_by_ids,
    update_claim_value,
)
from services.lark.card_builder import build_claim_approval_card

logger = logging.getLogger("hilark.workflows.claim")


def _get_lark_service():
    shim = sys.modules.get("services.claim_service") or sys.modules.get("services.bot_service")
    if shim and hasattr(shim, "lark_service"):
        return shim.lark_service
    from services.lark import lark_service
    return lark_service


class ClaimService:
    def __init__(self, lark=None):
        self._lark = lark

    def _resolve_lark(self):
        return self._lark or _get_lark_service()

    async def get_latest_proposed(self, chat_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Lấy thông tin đề xuất ở trạng thái proposed gần nhất."""
        return await get_latest_proposed_claim(chat_id=chat_id)

    async def get_claim_by_id(self, claim_id: str) -> Optional[Dict[str, Any]]:
        """Tìm claim theo ID trong MongoDB."""
        col = get_claims_collection()
        return await col.find_one({"id": claim_id})

    async def approve_claim(
        self,
        claim_id: Optional[str] = None,
        approver_info: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Duyệt một claim proposed chuyển thành current.
        Nếu không truyền claim_id, tự động lấy claim proposed gần nhất.
        """
        if claim_id:
            target_claim = await self.get_claim_by_id(claim_id)
        else:
            target_claim = await self.get_latest_proposed()

        if not target_claim:
            return False, "Không tìm thấy thông tin đề xuất nào đang chờ duyệt.", None

        cid = target_claim.get("id") or target_claim.get("_id")
        modified = await promote_claims_by_ids([cid], approver_info=approver_info)
        if modified > 0:
            target_claim["status"] = "current"
            return True, "Đã duyệt thông tin đề xuất thành công.", target_claim
        return False, "Không thể cập nhật trạng thái thông tin vào cơ sở dữ liệu.", target_claim

    async def reject_claim(
        self,
        claim_id: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Từ chối một claim proposed, chuyển trạng thái sang superseded.
        Nếu không truyền claim_id, tự động lấy claim proposed gần nhất.
        """
        if claim_id:
            target_claim = await self.get_claim_by_id(claim_id)
        else:
            target_claim = await self.get_latest_proposed()

        if not target_claim:
            return False, "Không tìm thấy thông tin đề xuất nào đang chờ duyệt.", None

        cid = target_claim.get("id") or target_claim.get("_id")
        modified = await reject_claims_by_ids([cid])
        if modified > 0:
            target_claim["status"] = "superseded"
            return True, "Đã từ chối thông tin đề xuất.", target_claim
        return False, "Không thể cập nhật trạng thái từ chối vào cơ sở dữ liệu.", target_claim

    async def edit_and_approve_claim(
        self,
        new_value: str,
        claim_id: Optional[str] = None,
        approver_info: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Cập nhật giá trị mới cho claim và đồng thời phê duyệt thành current.
        Nếu không truyền claim_id, tự động lấy claim proposed gần nhất.
        """
        if claim_id:
            target_claim = await self.get_claim_by_id(claim_id)
        else:
            target_claim = await self.get_latest_proposed()

        if not target_claim:
            return False, "Không tìm thấy thông tin đề xuất nào đang chờ duyệt để sửa.", None

        cid = target_claim.get("id") or target_claim.get("_id")
        success = await update_claim_value(cid, new_value, approver_info=approver_info)
        if success:
            target_claim["value"] = new_value
            target_claim["status"] = "current"
            return True, "Đã cập nhật và duyệt thông tin thành công.", target_claim
        return False, "Không thể cập nhật giá trị mới vào cơ sở dữ liệu.", target_claim

    async def get_pending_claims_for_date(
        self,
        date_str: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Lấy danh sách các claims đề xuất đang chờ duyệt trong ngày."""
        return await get_pending_proposed_claims(date_str=date_str, chat_id=chat_id)

    async def approve_all_pending_claims_for_date(
        self,
        date_str: Optional[str] = None,
        chat_id: Optional[str] = None,
        approver_info: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, str]:
        """
        Duyệt toàn bộ các claims đề xuất trong ngày thành current (duyệt hàng loạt).
        """
        count = await promote_all_proposed_claims(
            date_str=date_str,
            chat_id=chat_id,
            approver_info=approver_info,
        )
        if count > 0:
            return count, f"Đã phê duyệt thành công toàn bộ {count} thông tin đề xuất."
        return 0, "Không có thông tin đề xuất nào cần duyệt."

    async def notify_proposed_claims(
        self,
        facts: List[Dict[str, Any]],
        chat_id: Optional[str] = None,
        chat_title: Optional[str] = None,
        entities: Optional[List[Dict[str, Any]]] = None,
        message_id: Optional[str] = None,
        source_text: Optional[str] = None,
    ) -> int:
        """
        Gửi Thẻ tin nhắn tương tác tới Lãnh đạo cho từng fact có status == 'proposed'.
        Trả về số lượng thẻ đã gửi thành công.
        """
        if not facts:
            return 0

        lark = self._resolve_lark()
        sent_count = 0

        entity_lookup = {}
        if entities:
            for ent in entities:
                if isinstance(ent, dict) and ent.get("id"):
                    entity_lookup[str(ent["id"])] = ent.get("name") or ent.get("id")

        for f in facts:
            f_dict = f if isinstance(f, dict) else (f.to_dict() if hasattr(f, "to_dict") else vars(f))
            status_val = str(f_dict.get("status", "")).strip().lower()
            if status_val != "proposed":
                continue

            cid = str(f_dict.get("id") or f_dict.get("_id") or "")
            if not cid:
                continue

            prop = str(f_dict.get("property") or f_dict.get("predicate") or "")
            val = str(f_dict.get("value") or "")
            src = str(f_dict.get("source") or source_text or "")
            ent_id = str(f_dict.get("entity_id") or "")
            ent_name = entity_lookup.get(ent_id) or ent_id or "Dự án"

            asserted = f_dict.get("asserted_by") or {}
            speaker = (
                asserted.get("user_name")
                or asserted.get("user_id")
                or "Thành viên"
            )

            group_title = chat_title or chat_id or "Nhóm dự án"

            card_payload = build_claim_approval_card(
                claim_id=cid,
                chat_title=group_title,
                speaker_name=speaker,
                entity_name=ent_name,
                property_name=prop,
                value=val,
                source_text=src,
                message_id=message_id,
            )

            try:
                await lark.send_bot_card_to_owner(card_payload)
                sent_count += 1
                logger.info(f"Đã gửi Thẻ phê duyệt Claim đề xuất (ID: {cid}) tới lãnh đạo.")
            except Exception as e:
                logger.error(f"Lỗi khi gửi Thẻ Claim tới lãnh đạo: {e}")

        return sent_count


claim_service = ClaimService()

__all__ = ["ClaimService", "claim_service"]
