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
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from core.config import settings
from database.db import get_chat_scopes_collection
from models.chat_scope import ChatScopeRecord
from models.memory import get_vietnam_now_iso
import sys

logger = logging.getLogger(__name__)


def _get_active_weknora():
    shim = sys.modules.get("services.auth_service") or sys.modules.get("services.scope_service")
    if shim and hasattr(shim, "weknora_service"):
        return shim.weknora_service
    from services.knowledge.weknora_client import weknora_service
    return weknora_service


def _get_active_scopes_col():
    shim = sys.modules.get("services.auth_service") or sys.modules.get("services.scope_service")
    if shim and hasattr(shim, "get_chat_scopes_collection"):
        fn = getattr(shim, "get_chat_scopes_collection")
        if fn is not get_chat_scopes_collection:
            return fn()
    return get_chat_scopes_collection()

# Ánh xạ tên trường và Field ID của Lark Base (Bitable)
BASE_FIELD_MAP: Dict[str, List[str]] = {
    "chat_id": ["fldMa7EqDd", "ID Group", "chat_id"],
    "chat_name": ["fldQh1mqwW", "Dự án / Nhóm", "chat_name"],
    "status": ["fldbk4Upv9", "Trạng thái", "status"],
    "security_level": ["fldY4BvFLK", "Mức độ bảo mật", "security_level", "confidentiality"],
    "forbidden_labels": ["fldsexGPII", "Nhãn cấm xem", "forbidden_labels"],
    "allowed_labels": ["fldAYjcC5W", "Nhãn cho phép xem", "allowed_labels"],
    "documents": ["fldHpn8M87", "Documents", "documents", "Link tài liệu", "Tài liệu", "doc_links", "Doc Links"],
    "dataset_id": ["fldKBId", "Knowledge Base ID", "dataset_id"],
    "wiki_dataset_id": ["fldWikiKB", "Wiki KB", "wiki_dataset_id", "wiki_kb_id"],
    "project_tag": ["fldProjTag", "Mã dự án", "Project Tag", "project_tag"],
}


def _get_base_field(raw_fields: Dict[str, Any], key: str) -> Any:
    """Tra cứu giá trị trường từ raw_fields theo danh sách tên/ID tương thích."""
    for candidate in BASE_FIELD_MAP.get(key, []):
        if candidate in raw_fields:
            return raw_fields[candidate]
    return raw_fields.get(key)


def _sanitize_filename(name: str) -> str:
    """Loại bỏ các ký tự không hợp lệ trong tên tệp để an toàn khi lưu trữ."""
    safe = re.sub(r'[\\/*?:"<>|]', '_', name).strip()
    return safe or "lark_document"


def _extract_document_items(docs_val: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Trích xuất và phân loại tất cả các tài liệu từ trường 'Documents' của Lark Base.
    Hỗ trợ cả 2 dạng:
      1. Tệp đính kèm nhị phân (Attachment: PDF, docx, xlsx... có file_token/attachmentToken)
      2. Liên kết đám mây Lark DocX / Wiki (Link URL dạng string, dict {'link': ..., 'text': ...}, hoặc list)

    Returns:
      Tuple[attachments, lark_links]:
        - attachments: [{'file_token': ..., 'name': ..., 'type': ..., 'size': ...}]
        - lark_links: [{'type': 'docx'|'wiki', 'token': ..., 'url': ..., 'title': ...}]
    """
    attachments: List[Dict[str, Any]] = []
    lark_links: List[Dict[str, Any]] = []
    seen_tokens: Set[str] = set()

    if not docs_val:
        return attachments, lark_links

    raw_items = docs_val if isinstance(docs_val, list) else [docs_val]

    for item in raw_items:
        if not item:
            continue

        if isinstance(item, dict):
            # 1. Kiểm tra nếu là Attachment tệp đính kèm từ Lark Base
            ft = item.get("file_token") or item.get("attachmentToken") or item.get("id")
            if ft and ("name" in item or "mimeType" in item or (item.get("type") not in ("url", "link") and "size" in item)):
                attachments.append(item)
                continue

            # 2. Kiểm tra nếu là trường Hyperlink / Link dict: {'link': '...', 'text': '...'}
            url = item.get("link") or item.get("url") or ""
            text = item.get("text") or ""
            title = text if text and not text.startswith("http") else None
            combined_text = f"{url} {text}".strip()

            from services.knowledge.doc_parser import DOCX_URL_PATTERN, WIKI_URL_PATTERN
            for match in DOCX_URL_PATTERN.finditer(combined_text):
                token = match.group(1)
                if token not in seen_tokens:
                    seen_tokens.add(token)
                    lark_links.append({
                        "type": "docx",
                        "token": token,
                        "url": match.group(0),
                        "title": title,
                    })

            for match in WIKI_URL_PATTERN.finditer(combined_text):
                token = match.group(1)
                if token not in seen_tokens:
                    seen_tokens.add(token)
                    lark_links.append({
                        "type": "wiki",
                        "token": token,
                        "url": match.group(0),
                        "title": title,
                    })

        elif isinstance(item, str):
            from services.knowledge.doc_parser import DOCX_URL_PATTERN, WIKI_URL_PATTERN
            for match in DOCX_URL_PATTERN.finditer(item):
                token = match.group(1)
                if token not in seen_tokens:
                    seen_tokens.add(token)
                    lark_links.append({
                        "type": "docx",
                        "token": token,
                        "url": match.group(0),
                        "title": None,
                    })

            for match in WIKI_URL_PATTERN.finditer(item):
                token = match.group(1)
                if token not in seen_tokens:
                    seen_tokens.add(token)
                    lark_links.append({
                        "type": "wiki",
                        "token": token,
                        "url": match.group(0),
                        "title": None,
                    })

    return attachments, lark_links


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
        from services.lark import lark_service
        if lark_service.owner_open_id:
            admins.add(lark_service.owner_open_id.strip())
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
            coll = _get_active_scopes_col()
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

    async def get_wiki_kb_for_chat(self, chat_id: Optional[str]) -> str:
        """
        Tra cứu Wiki Knowledge Base ID cho một nhóm chat để lưu trữ digest & diễn biến dự án.
        Nếu nhóm chưa cấu hình riêng wiki_dataset_id, tự động fallback về WEKNORA_WIKI_DATASET_ID hoặc WEKNORA_DATASET_ID.
        """
        if chat_id:
            scope = await self.get_scope_by_chat_id(chat_id)
            if scope and scope.wiki_dataset_id:
                return scope.wiki_dataset_id

        default_wiki_id = settings.WEKNORA_WIKI_DATASET_ID or settings.WEKNORA_DATASET_ID or ""
        if "," in default_wiki_id:
            default_wiki_id = default_wiki_id.split(",")[0].strip()
        return default_wiki_id

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
        kb_info = await _get_active_weknora().get_kb_info(clean_dataset_id)
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
            coll = _get_active_scopes_col()
            existing = await coll.find_one({"chat_id": chat_id})

            created_at = existing.get("created_at", now_iso) if existing else now_iso
            security_level = existing.get("security_level", "Nội bộ") if existing else "Nội bộ"
            wiki_dataset_id = existing.get("wiki_dataset_id", "") if existing else ""

            scope_rec = ChatScopeRecord(
                chat_id=chat_id,
                chat_name=chat_name or (existing.get("chat_name", "") if existing else ""),
                dataset_id=clean_dataset_id,
                dataset_name=dataset_name,
                wiki_dataset_id=wiki_dataset_id,
                project_tag=project_tag or (existing.get("project_tag") if existing else None),
                security_level=security_level,
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
            coll = _get_active_scopes_col()
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
            coll = _get_active_scopes_col()
            cursor = coll.find().sort("updated_at", -1)
            docs = await cursor.to_list(length=100)
            return [ChatScopeRecord(**d) for d in docs]
        except Exception as e:
            logger.error(f"Lỗi khi lấy danh sách chat scopes: {e}", exc_info=True)
            return []

    async def sync_group_from_base_record(
        self,
        record: Any,
        target_dataset_id: Optional[str] = None,
    ) -> Optional[ChatScopeRecord]:
        """
        Đồng bộ 1 bản ghi cấu hình nhóm từ Lark Base sang MongoDB & WeKnora:
          1. Đọc chat_id, chat_name, status, forbidden_labels, allowed_labels, documents.
          2. Duyệt qua documents: nếu file chưa có knowledge_id trên WeKnora, tải file bằng
             Lark Drive Media API và upload sang WeKnora lấy knowledge_id.
          3. Cập nhật bản ghi ChatScopeRecord trong MongoDB collection 'chat_scopes'.
        """
        if not record:
            return None

        if hasattr(record, "fields"):
            raw_fields = record.fields or {}
            rec_id = getattr(record, "record_id", "")
        else:
            raw_fields = record.get("fields", record)
            rec_id = record.get("record_id", "")

        # 1. Trích xuất chat_id
        chat_id = _extract_text_field(_get_base_field(raw_fields, "chat_id"))
        if not chat_id:
            logger.debug(f"[ChatScope Sync] Bản ghi {rec_id} không có ID Group, bỏ qua.")
            return None

        # 2. Trích xuất tên nhóm / dự án
        chat_name = _extract_text_field(_get_base_field(raw_fields, "chat_name")) or f"Nhóm {chat_id}"
        raw_project_tag = _extract_text_field(_get_base_field(raw_fields, "project_tag"))

        # 3. Trích xuất trạng thái & mức độ bảo mật
        status = _extract_text_field(_get_base_field(raw_fields, "status")) or "Hoạt động"
        raw_sec = _extract_text_field(_get_base_field(raw_fields, "security_level")) or "Nội bộ"
        security_level = "Tuyệt mật" if raw_sec.strip().lower() in ("tuyệt mật", "tuyet mat", "confidential", "secret", "strict") else "Nội bộ"

        # 4. Trích xuất nhãn cấm xem & nhãn được phép xem
        forbidden_labels = _extract_labels(_get_base_field(raw_fields, "forbidden_labels"))
        allowed_labels = _extract_labels(_get_base_field(raw_fields, "allowed_labels"))

        # 5. Xác định Dataset ID & Wiki Dataset ID
        effective_dataset_id = target_dataset_id or settings.WEKNORA_DATASET_ID or ""
        if "," in effective_dataset_id:
            effective_dataset_id = effective_dataset_id.split(",")[0].strip()

        raw_wiki = _extract_text_field(_get_base_field(raw_fields, "wiki_dataset_id"))
        wiki_dataset_id = raw_wiki or settings.WEKNORA_WIKI_DATASET_ID or ""

        # 6. Đọc tài liệu đính kèm & liên kết Lark Docs từ trường Documents
        docs_val = _get_base_field(raw_fields, "documents")
        attachments, lark_links = _extract_document_items(docs_val)

        existing_scope = await self.get_scope_by_chat_id(chat_id)
        existing_doc_map = {}
        if existing_scope and existing_scope.documents:
            for d in existing_scope.documents:
                ft = d.get("file_token")
                kid = d.get("knowledge_id")
                if ft and kid:
                    existing_doc_map[ft] = d
                u = d.get("url")
                if u and kid:
                    existing_doc_map[u] = d

        synced_docs: List[Dict[str, Any]] = []
        knowledge_ids: List[str] = []

        from services.lark.bitable import lark_base_service
        from services.knowledge.doc_parser import doc_parser_service

        # 6.1. Xử lý tệp đính kèm nhị phân (PDF, Word, Excel...)
        for d in attachments:
            file_token = d.get("file_token") or d.get("attachmentToken") or d.get("id") or ""
            file_name = d.get("name") or "document.pdf"
            mime_type = d.get("type") or d.get("mimeType") or "application/pdf"
            file_size = d.get("size") or 0

            if not file_token:
                continue

            existing_doc = existing_doc_map.get(file_token)
            k_id = existing_doc.get("knowledge_id") if existing_doc else None
            doc_summary = existing_doc.get("summary") if existing_doc else None

            if not k_id:
                try:
                    logger.info(f"📥 [ChatScope Sync] Đang tải file '{file_name}' ({file_token}) từ Lark Base...")
                    file_bytes = await lark_base_service.adownload_attachment(file_token, use_tenant_token=True)
                    if file_bytes:
                        logger.info(f"📤 [ChatScope Sync] Đang nạp '{file_name}' ({len(file_bytes)} bytes) sang WeKnora KB {effective_dataset_id}...")
                        upload_res = await _get_active_weknora().upload_file(
                            file_name=file_name,
                            file_bytes=file_bytes,
                            dataset_id=effective_dataset_id,
                            mime_type=mime_type,
                        )
                        k_id = upload_res.get("knowledge_id", "")
                        doc_summary = upload_res.get("summary")
                        if k_id:
                            logger.info(f"✔ [ChatScope Sync] WeKnora đã nạp file thành công: knowledge_id={k_id}")
                except Exception as e:
                    logger.error(f"❌ [ChatScope Sync] Lỗi khi xử lý file '{file_name}': {e}", exc_info=True)

            if k_id and not doc_summary:
                try:
                    doc_info = await _get_active_weknora().get_document_info(effective_dataset_id, k_id)
                    if doc_info and doc_info.get("summary"):
                        doc_summary = doc_info["summary"]
                except Exception as e:
                    logger.debug(f"Chưa lấy được summary từ WeKnora cho file {file_name}: {e}")

            if k_id:
                synced_docs.append({
                    "file_token": file_token,
                    "name": file_name,
                    "size": file_size,
                    "type": mime_type,
                    "knowledge_id": k_id,
                    "summary": doc_summary,
                })
                knowledge_ids.append(k_id)

        # 6.2. Xử lý liên kết tài liệu đám mây Lark DocX & Wiki
        for link_info in lark_links:
            link_type = link_info.get("type", "docx")
            token = link_info.get("token", "")
            url = link_info.get("url", "")
            title = link_info.get("title")

            if not token:
                continue

            doc_key = f"lark_{link_type}_{token}"
            existing_doc = existing_doc_map.get(doc_key) or existing_doc_map.get(url)
            k_id = existing_doc.get("knowledge_id") if existing_doc else None
            doc_summary = existing_doc.get("summary") if existing_doc else None
            doc_name = existing_doc.get("name") if existing_doc else None
            doc_size = existing_doc.get("size", 0) if existing_doc else 0

            if not k_id:
                try:
                    logger.info(f"📥 [ChatScope Sync] Đang phân giải liên kết Lark {link_type.upper()} ({token}) từ Base...")
                    if link_type == "docx":
                        doc_res = await doc_parser_service.parse_lark_docx(document_id=token, title=title)
                    elif link_type == "wiki":
                        doc_res = await doc_parser_service.parse_lark_wiki(wiki_token=token)
                    else:
                        doc_res = None

                    if doc_res and doc_res.success and doc_res.markdown_content:
                        raw_name = doc_res.doc_name or title or f"Lark_{link_type.upper()}_{token}"
                        safe_name = _sanitize_filename(raw_name)
                        if not safe_name.lower().endswith(".md"):
                            safe_name = f"{safe_name}.md"

                        doc_bytes = doc_res.markdown_content.encode("utf-8")
                        doc_name = safe_name
                        doc_size = len(doc_bytes)

                        logger.info(f"📤 [ChatScope Sync] Đang nạp Lark Doc '{doc_name}' ({doc_size} bytes) sang WeKnora KB {effective_dataset_id}...")
                        upload_res = await _get_active_weknora().upload_file(
                            file_name=doc_name,
                            file_bytes=doc_bytes,
                            dataset_id=effective_dataset_id,
                            mime_type="text/markdown",
                        )
                        k_id = upload_res.get("knowledge_id", "")
                        doc_summary = upload_res.get("summary")
                        if k_id:
                            logger.info(f"✔ [ChatScope Sync] WeKnora đã nạp Lark Doc thành công: knowledge_id={k_id}")
                    else:
                        err_msg = doc_res.error if doc_res else "Phân giải tài liệu không thành công"
                        logger.warning(f"⚠️ [ChatScope Sync] Không thể phân giải Lark {link_type} ({token}): {err_msg}")
                except Exception as e:
                    logger.error(f"❌ [ChatScope Sync] Lỗi khi xử lý Lark Doc link '{url}': {e}", exc_info=True)

            if k_id and not doc_summary:
                try:
                    doc_info = await _get_active_weknora().get_document_info(effective_dataset_id, k_id)
                    if doc_info and doc_info.get("summary"):
                        doc_summary = doc_info["summary"]
                except Exception as e:
                    logger.debug(f"Chưa lấy được summary từ WeKnora cho Lark Doc {doc_name}: {e}")

            if k_id:
                synced_docs.append({
                    "file_token": doc_key,
                    "name": doc_name or f"Lark_{link_type.upper()}_{token}.md",
                    "size": doc_size,
                    "type": f"lark_{link_type}",
                    "url": url,
                    "knowledge_id": k_id,
                    "summary": doc_summary,
                })
                knowledge_ids.append(k_id)

        # 7. Lưu hoặc cập nhật ChatScopeRecord trong MongoDB
        now_iso = get_vietnam_now_iso()
        coll = _get_active_scopes_col()
        created_at = existing_scope.created_at if existing_scope else now_iso
        effective_project_tag = raw_project_tag or (existing_scope.project_tag if existing_scope else None)

        scope_rec = ChatScopeRecord(
            chat_id=chat_id,
            chat_name=chat_name,
            dataset_id=effective_dataset_id,
            dataset_name=existing_scope.dataset_name if existing_scope else "Lark Base Knowledge Base",
            wiki_dataset_id=wiki_dataset_id,
            project_tag=effective_project_tag,
            status=status,
            security_level=security_level,
            forbidden_labels=forbidden_labels,
            allowed_labels=allowed_labels,
            documents=synced_docs,
            knowledge_ids=list(dict.fromkeys(knowledge_ids)),
            record_id=rec_id,
            updated_by="larkbase_sync",
            updated_by_name="Lark Base Auto-Sync",
            created_at=created_at,
            updated_at=now_iso,
        )

        await coll.update_one(
            {"chat_id": chat_id},
            {"$set": scope_rec.to_dict()},
            upsert=True,
        )

        logger.info(
            f"✔ [ChatScope Sync] Đồng bộ thành công nhóm '{chat_name}' ({chat_id}): "
            f"Trạng thái='{status}', {len(scope_rec.knowledge_ids)} files WeKnora, "
            f"Nhãn cấm={forbidden_labels}"
        )
        return scope_rec

    async def sync_all_groups_from_base(self) -> List[ChatScopeRecord]:
        """Quét và đồng bộ toàn bộ bảng Lark Base sang MongoDB và WeKnora."""
        try:
            from services.lark.bitable import lark_base_service
            if not lark_base_service.app_token:
                logger.debug("[ChatScope Sync] LARK_BASE_APP_TOKEN chưa được cấu hình, bỏ qua sync toàn bảng.")
                return []

            records = await lark_base_service.aget_all_records(use_tenant_token=True)
            results = []
            for r in records:
                rec = await self.sync_group_from_base_record(r)
                if rec:
                    results.append(rec)
            logger.info(f"🎉 [ChatScope Sync] Đã quét và đồng bộ thành công {len(results)} nhóm từ Lark Base!")
            return results
        except Exception as e:
            logger.error(f"Lỗi khi đồng bộ toàn bộ Lark Base: {e}", exc_info=True)
            return []

    async def handle_bitable_record_changed_event(self, event_data: Any) -> None:
        """
        Lắng nghe sự kiện Bitable thay đổi (drive.file.bitable_record_changed_v1)
        tự động cập nhật MongoDB & tải file PDF mới vào WeKnora theo thời gian thực.
        Hỗ trợ phân luồng:
          - Bảng Quản lý nhóm (tblK5UANXj0FxHuQ) -> Cập nhật Chat Scopes
          - Bảng Chính sách (tblZphzEZPLQAy24) -> Kích hoạt Policy Sync
        """
        try:
            event = getattr(event_data, "event", None)
            if not event:
                return

            table_id = getattr(event, "table_id", "")
            action_list = getattr(event, "action_list", []) or []
            record_ids = [getattr(a, "record_id", "") for a in action_list if getattr(a, "record_id", "")]
            if not record_ids:
                return

            # Kiểm tra nếu sự kiện xuất phát từ Bảng Chính Sách Công Ty
            if table_id and table_id == settings.LARK_BASE_POLICY_TABLE_ID:
                logger.info(f"🏛️ [Bitable Realtime Event] Phát hiện thay đổi trong Bảng Chính Sách ({table_id}) -> Kích hoạt Policy Sync!")
                from services.knowledge.policy_sync import policy_sync_service
                await policy_sync_service.sync_policies()
                return

            logger.info(f"🔄 [Bitable Realtime Event] Phát hiện {len(record_ids)} bản ghi thay đổi, tiến hành đồng bộ: {record_ids}")
            from services.lark.bitable import lark_base_service
            records = await lark_base_service.aget_all_records(use_tenant_token=True)
            record_map = {r.record_id: r for r in records}

            for rid in record_ids:
                target_record = record_map.get(rid)
                if target_record:
                    await self.sync_group_from_base_record(target_record)
        except Exception as e:
            logger.error(f"Lỗi khi xử lý sự kiện bitable_record_changed: {e}", exc_info=True)


from services.lark.cleaner import clean_field_value
from services.knowledge.rule_engine import parse_labels


def _extract_text_field(val: Any) -> str:
    """Trích xuất chuỗi văn bản sạch từ các kiểu dữ liệu của Lark Base."""
    cleaned = clean_field_value(val)
    if cleaned is None:
        return ""
    if isinstance(cleaned, list):
        return ", ".join(str(x) for x in cleaned if x)
    return str(cleaned).strip()


_extract_labels = parse_labels


# Singleton instance
scope_service = ScopeService()

__all__ = [
    "ScopeService",
    "scope_service",
]

