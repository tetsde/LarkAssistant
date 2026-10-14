"""
HiLark Scope Service - Phân Quyền Dữ Liệu & Quản Lý Ánh Xạ Nhóm Chat <-> WeKnora KB
=====================================================================================
Vị trí: server/services/scope_service.py

Cung cấp:
  1. Tra cứu KB tương ứng của nhóm chat (Chat Scoping).
  2. Kiểm tra quyền hạn của người thực hiện (Admin Whitelist).
  3. Lệnh liên kết nhóm chat với Knowledge Base kèm xác thực tên KB từ WeKnora.
  4. Quản lý lưu trữ trong MongoDB collection 'chat_scopes'.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from core.config import settings
from database.db import get_chat_scopes_collection
from models.chat_scope import ChatScopeRecord
from models.memory import get_vietnam_now_iso
from services.weknora import weknora_service

logger = logging.getLogger(__name__)


class ScopeService:
    def __init__(self):
        pass

    def get_admin_open_ids(self) -> List[str]:
        """Lấy danh sách các Open ID có quyền Admin quản trị hệ thống."""
        admins = set()
        if settings.LARK_USER_OPEN_ID:
            admins.add(settings.LARK_USER_OPEN_ID.strip())
        if settings.DIGEST_APPROVER_ID:
            admins.add(settings.DIGEST_APPROVER_ID.strip())
        extra_admins = os.getenv("admin_open_ids", "")
        if extra_admins:
            for aid in extra_admins.split(","):
                if aid.strip():
                    admins.add(aid.strip())
        return list(admins)

    def is_admin_user(self, open_id: str) -> bool:
        """Kiểm tra xem một user có quyền Admin thay đổi cấu hình KB hay không."""
        if not open_id:
            return False
        return open_id.strip() in self.get_admin_open_ids()

    async def get_scope_by_chat_id(self, chat_id: str) -> Optional[ChatScopeRecord]:
        """Truy vấn bản ghi ChatScopeRecord trong MongoDB theo chat_id."""
        if not chat_id:
            return None
        try:
            coll = get_chat_scopes_collection()
            doc = await coll.find_one({"chat_id": chat_id})
            if doc:
                return ChatScopeRecord(**doc)
            return None
        except Exception as e:
            logger.error(f"Lỗi khi tìm chat scope cho chat_id={chat_id}: {e}", exc_info=True)
            return None

    async def get_kb_for_chat(self, chat_id: Optional[str]) -> str:
        """
        Tra cứu Knowledge Base ID (dataset_id) cho một nhóm chat.
        Nếu nhóm chưa cấu hình riêng, tự động fallback về WEKNORA_DATASET_ID mặc định trong .env.
        """
        dataset_id, _ = await self.get_kb_info_for_chat(chat_id)
        return dataset_id

    async def get_kb_info_for_chat(self, chat_id: Optional[str]) -> Tuple[str, str]:
        """
        Trả về Tuple (dataset_id, dataset_name) của nhóm chat.
        """
        if chat_id:
            scope = await self.get_scope_by_chat_id(chat_id)
            if scope and scope.dataset_id:
                return scope.dataset_id, (scope.dataset_name or "Knowledge Base Nhóm")

        # Fallback về KB mặc định
        default_id = settings.WEKNORA_DATASET_ID or ""
        if "," in default_id:
            default_id = default_id.split(",")[0].strip()
        return default_id, "Knowledge Base Mặc Định"

    async def set_chat_kb(
        self,
        chat_id: str,
        dataset_id: str,
        operator_open_id: str,
        operator_name: str = "",
        chat_name: str = "",
        project_tag: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[ChatScopeRecord]]:
        """
        Thiết lập liên kết Nhóm chat với một Knowledge Base WeKnora.
        Quy trình:
          1. Kiểm tra quyền Admin của người thực hiện (Chặn nhân viên phá hoại).
          2. Xác thực dataset_id với WeKnora API và lấy tên Knowledge Base.
          3. Lưu/Cập nhật vào MongoDB collection 'chat_scopes'.
        """
        if not chat_id or not dataset_id:
            return False, "❌ chat_id và dataset_id không được để trống.", None

        clean_dataset_id = dataset_id.strip()

        # 1. Kiểm tra quyền Admin
        if not self.is_admin_user(operator_open_id):
            logger.warning(
                f"⛔ CẢNH BÁO BẢO MẬT: Người dùng {operator_open_id} cố tình chạy set-kb trong chat {chat_id} nhưng không có quyền."
            )
            return (
                False,
                "⛔ [TỪ CHỐI] Bạn không có quyền quản trị! Chỉ Admin hoặc Chủ nhóm mới được phép thay đổi Knowledge Base của nhóm chat này.",
                None,
            )

        # 2. Xác thực dataset_id trên WeKnora và lấy tên KB
        kb_info = await weknora_service.get_kb_info(clean_dataset_id)
        if not kb_info:
            logger.warning(f"❌ Không tìm thấy Knowledge Base ID={clean_dataset_id} trên WeKnora.")
            return (
                False,
                f"❌ Knowledge Base ID '{clean_dataset_id}' không tồn tại hoặc không hợp lệ trên WeKnora.",
                None,
            )

        dataset_name = kb_info.get("name") or "Knowledge Base"

        # 3. Lưu/Cập nhật vào MongoDB
        try:
            now_iso = get_vietnam_now_iso()
            coll = get_chat_scopes_collection()
            existing = await coll.find_one({"chat_id": chat_id})

            created_at = existing.get("created_at", now_iso) if existing else now_iso

            scope_rec = ChatScopeRecord(
                chat_id=chat_id,
                chat_name=chat_name or (existing.get("chat_name", "") if existing else ""),
                dataset_id=clean_dataset_id,
                dataset_name=dataset_name,
                project_tag=project_tag or (existing.get("project_tag") if existing else None),
                updated_by=operator_open_id,
                updated_by_name=operator_name or "Admin",
                created_at=created_at,
                updated_at=now_iso,
            )

            await coll.update_one(
                {"chat_id": chat_id},
                {"$set": scope_rec.to_dict()},
                upsert=True,
            )

            log_msg = f"✔ Đã liên kết nhóm thành công với Knowledge Base '{dataset_name}' (ID: {clean_dataset_id})!"
            logger.info(f"[ChatScope] {log_msg} cho chat {chat_id} bởi {operator_open_id}")
            return True, log_msg, scope_rec

        except Exception as e:
            logger.error(f"Lỗi khi lưu ChatScope vào MongoDB: {e}", exc_info=True)
            return False, f"❌ Lỗi hệ thống khi lưu cấu hình vào cơ sở dữ liệu: {e}", None

    async def reset_chat_kb(
        self,
        chat_id: str,
        operator_open_id: str,
    ) -> Tuple[bool, str]:
        """
        Gỡ bỏ Knowledge Base riêng của nhóm chat, đưa nhóm về dùng KB mặc định.
        """
        if not chat_id:
            return False, "❌ chat_id không hợp lệ."

        if not self.is_admin_user(operator_open_id):
            return (
                False,
                "⛔ [TỪ CHỐI] Bạn không có quyền quản trị! Chỉ Admin mới được phép gỡ bỏ Knowledge Base của nhóm.",
            )

        try:
            coll = get_chat_scopes_collection()
            res = await coll.delete_one({"chat_id": chat_id})
            if res.deleted_count > 0:
                return (
                    True,
                    "✔ Đã gỡ bỏ Knowledge Base riêng của nhóm. Nhóm sẽ quay về sử dụng Knowledge Base mặc định của hệ thống.",
                )
            else:
                return (
                    True,
                    "ℹ️ Nhóm chat này hiện chưa được cấu hình Knowledge Base riêng (đang dùng KB mặc định sẵn rồi).",
                )
        except Exception as e:
            logger.error(f"Lỗi khi xóa ChatScope cho chat {chat_id}: {e}", exc_info=True)
            return False, f"❌ Lỗi khi gỡ bỏ Knowledge Base: {e}"

    async def list_all_scopes(self) -> List[ChatScopeRecord]:
        """Lấy danh sách tất cả các nhóm chat đã được cấu hình KB riêng."""
        try:
            coll = get_chat_scopes_collection()
            cursor = coll.find().sort("updated_at", -1)
            docs = await cursor.to_list(length=100)
            return [ChatScopeRecord(**d) for d in docs]
        except Exception as e:
            logger.error(f"Lỗi khi lấy danh sách chat scopes: {e}", exc_info=True)
            return []


# Singleton instance
scope_service = ScopeService()

__all__ = [
    "ScopeService",
    "scope_service",
]
