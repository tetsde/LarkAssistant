
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
from core.tenant_errors import TenantContextMissing, TenantResolutionError
from database.db import get_chat_scopes_collection
from database.scoped_query import inject_tenant_filter, get_current_tenant_key
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
    # Field IDs hiện tại của Base "Danh mục Dự án & Nhóm chat".
    # Giữ các ID cũ và tên cột để tương thích với các tenant/Base đã tạo trước đó.
    "chat_id": ["fld2e3jI7n", "fldMa7EqDd", "Chat ID", "ID Group", "chat_id"],
    "chat_name": ["fld83CoUi0", "fldQh1mqwW", "Text", "Tên dự án", "Dự án / Nhóm", "chat_name", "Tên nhóm"],
    "status": ["fldbk4Upv9", "Trạng thái hoạt động", "Trạng thái", "status"],
    "security_level": ["fldY4BvFLK", "Cấp độ bảo mật", "Mức độ bảo mật", "security_level", "confidentiality"],
    "forbidden_labels": ["fldsexGPII", "Nhãn cấm xem", "Forbidden Keywords", "forbidden_labels"],
    "allowed_labels": ["fldAYjcC5W", "Nhãn cho phép xem", "Allowed Labels", "allowed_labels"],
    "documents": ["fldLOaKxBH", "fldHpn8M87", "Danh mục tài liệu", "Documents", "documents", "Link tài liệu", "Tài liệu", "doc_links", "Doc Links"],
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

            from services.knowledge.doc_parser import DOCX_URL_PATTERN, WIKI_URL_PATTERN, FOLDER_URL_PATTERN
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

            for match in FOLDER_URL_PATTERN.finditer(combined_text):
                token = match.group(1)
                if token not in seen_tokens:
                    seen_tokens.add(token)
                    lark_links.append({
                        "type": "folder",
                        "token": token,
                        "url": match.group(0),
                        "title": title,
                    })

        elif isinstance(item, str):
            from services.knowledge.doc_parser import DOCX_URL_PATTERN, WIKI_URL_PATTERN, FOLDER_URL_PATTERN
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

            for match in FOLDER_URL_PATTERN.finditer(item):
                token = match.group(1)
                if token not in seen_tokens:
                    seen_tokens.add(token)
                    lark_links.append({
                        "type": "folder",
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

    async def get_scope_by_chat_id(
        self,
        chat_id: str,
        tenant_key: Optional[str] = None,
    ) -> Optional[ChatScopeRecord]:
        """Truy vấn bản ghi ChatScopeRecord trong MongoDB theo chat_id có cô lập theo tenant_key."""
        if not chat_id:
            return None
        try:
            coll = _get_active_scopes_col()
            query = inject_tenant_filter({"chat_id": chat_id}, tenant_key)
            doc = await coll.find_one(query)
            if not doc and tenant_key:
                # Fallback tự động sửa lỗi bản ghi cũ chưa gắn tenant_key
                doc = await coll.find_one({"chat_id": chat_id})
                if doc and not doc.get("tenant_key"):
                    await coll.update_one({"_id": doc["_id"]}, {"$set": {"tenant_key": tenant_key}})
            if doc:
                return ChatScopeRecord(**doc)
            return None
        except Exception as e:
            logger.error(f"Lỗi khi tìm chat scope cho chat_id={chat_id}: {e}", exc_info=True)
            return None

    async def get_kb_for_chat(self, chat_id: Optional[str], tenant_key: Optional[str] = None) -> str:
        """
        Tra cứu Knowledge Base ID (dataset_id) cho một nhóm chat.
        Nếu nhóm chưa cấu hình riêng, tự động tra cứu KB mặc định của tenant hoặc .env.
        """
        dataset_id, _ = await self.get_kb_info_for_chat(chat_id, tenant_key=tenant_key)
        return dataset_id

    async def get_kb_info_for_chat(self, chat_id: Optional[str], tenant_key: Optional[str] = None) -> Tuple[str, str]:
        """
        Trả về Tuple (dataset_id, dataset_name) của nhóm chat.
        """
        eff_tenant = tenant_key or get_current_tenant_key()

        if chat_id:
            scope = await self.get_scope_by_chat_id(chat_id, tenant_key=eff_tenant)
            if scope and scope.dataset_id:
                return scope.dataset_id, (scope.dataset_name or "Knowledge Base Nhóm")

        # Tra cứu KB mặc định của doanh nghiệp (Multi-Tenant)
        if eff_tenant:
            try:
                from database.db import get_tenant_config
                t_doc = await get_tenant_config(eff_tenant)
                if t_doc and t_doc.get("weknora_default_dataset_id"):
                    ent_title = t_doc.get("enterprise_name") or "Doanh Nghiệp"
                    return t_doc["weknora_default_dataset_id"], f"Knowledge Base {ent_title}"
            except Exception:
                pass

        # Fallback .env đã bỏ (Giai đoạn 2): thiếu tenant là lỗi ngữ cảnh, không phải
        # trường hợp "chạy bằng KB chung của hệ thống".
        if not eff_tenant:
            raise TenantContextMissing(
                "get_default_kb_for_chat() cần tenant_key để trả về Knowledge Base đúng doanh nghiệp."
            )
        # Tenant config không có dataset_id → warn; resolver sẽ chặn ở bước dùng thực tế.
        logger.warning(
            "⚠️ [ChatScope] Tenant '%s' chưa cấu hình weknora_default_dataset_id. "
            "Cần hoàn tất setup để gán dataset cho tenant.",
            eff_tenant,
        )
        return "", "Chưa cấu hình KB"

    async def get_wiki_kb_for_chat(self, chat_id: Optional[str], tenant_key: Optional[str] = None) -> str:
        """
        Tra cứu Wiki Knowledge Base ID cho một nhóm chat để lưu trữ digest & diễn biến dự án.
        Ưu tiên: Chat Scope riêng -> Wiki KB của tenant. Không có tầng `.env`.
        """
        eff_tenant = tenant_key or get_current_tenant_key()

        if chat_id:
            scope = await self.get_scope_by_chat_id(chat_id, tenant_key=eff_tenant)
            if scope and scope.wiki_dataset_id:
                return scope.wiki_dataset_id

        # Tra cứu Wiki KB của doanh nghiệp (Multi-Tenant)
        if eff_tenant:
            try:
                from database.db import get_tenant_config
                t_doc = await get_tenant_config(eff_tenant)
                if t_doc and t_doc.get("weknora_wiki_dataset_id"):
                    return t_doc["weknora_wiki_dataset_id"]
            except Exception:
                pass

        # Không có tầng `.env`: thiếu tenant là lỗi ngữ cảnh, thiếu wiki KB của tenant
        # là lỗi cấu hình và được báo bằng warning để caller thấy rõ nguyên nhân.
        if not eff_tenant:
            raise TenantContextMissing(
                "get_wiki_kb_for_chat() cần tenant_key để trả về Wiki KB đúng doanh nghiệp."
            )
        logger.warning(
            "⚠️ [ChatScope] Tenant '%s' chưa cấu hình weknora_wiki_dataset_id.",
            eff_tenant,
        )
        return ""

    async def set_chat_kb(
        self,
        chat_id: str,
        dataset_id: str,
        operator_open_id: str,
        operator_name: str = "",
        chat_name: str = "",
        project_tag: Optional[str] = None,
        tenant_key: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[ChatScopeRecord]]:
        """
        Thiết lập liên kết Nhóm chat với một Knowledge Base WeKnora (hỗ trợ tenant_key).
        Quy trình:
          1. Kiểm tra quyền Admin của người thực hiện (Chặn nhân viên phá hoại).
          2. Xác thực dataset_id với WeKnora API và lấy tên Knowledge Base.
          3. Lưu/Cập nhật vào MongoDB collection 'chat_scopes'.
        """
        if not chat_id or not dataset_id:
            return False, "❌ chat_id và dataset_id không được để trống.", None

        clean_dataset_id = dataset_id.strip()
        eff_tenant = tenant_key or get_current_tenant_key()

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
            query = inject_tenant_filter({"chat_id": chat_id}, eff_tenant)
            existing = await coll.find_one(query)

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
                tenant_key=eff_tenant or (existing.get("tenant_key") if existing else None),
                created_at=created_at,
                updated_at=now_iso,
            )

            await coll.update_one(
                query,
                {"$set": scope_rec.to_dict()},
                upsert=True,
            )

            log_msg = f"✔ Đã liên kết nhóm thành công với Knowledge Base '{dataset_name}' (ID: {clean_dataset_id})!"
            logger.info(f"[ChatScope] {log_msg} cho chat {chat_id} (tenant: {eff_tenant}) bởi {operator_open_id}")
            return True, log_msg, scope_rec
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
            eff_tenant = get_current_tenant_key()
            delete_query = inject_tenant_filter({"chat_id": chat_id}, eff_tenant)
            if eff_tenant and "tenant_key" not in delete_query:
                return False, "❌ Thiếu tenant context, không thể xóa ChatScope an toàn."
            res = await coll.delete_one(delete_query)
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

    async def list_all_scopes(self, tenant_key: Optional[str] = None) -> List[ChatScopeRecord]:
        """Lấy danh sách tất cả các nhóm chat đã được cấu hình KB riêng (hỗ trợ lọc theo tenant_key)."""
        eff_tenant = tenant_key or get_current_tenant_key()
        try:
            coll = _get_active_scopes_col()
            query = inject_tenant_filter({}, eff_tenant)
            cursor = coll.find(query).sort("updated_at", -1)
            docs = await cursor.to_list(length=100)
            return [ChatScopeRecord(**d) for d in docs]
        except Exception as e:
            logger.error(f"Lỗi khi lấy danh sách chat scopes: {e}", exc_info=True)
            return []

    async def ingest_documents_to_scope(
        self,
        chat_id: str,
        urls: List[str],
        operator_open_id: Optional[str] = None,
        operator_name: Optional[str] = None,
        extract_claims: bool = True,
    ) -> Dict[str, Any]:
        """
        Nạp tài liệu từ danh sách URLs (Lark DocX, Wiki, hoặc Drive Folder) vào nhóm chat.
        Hỗ trợ phân giải toàn bộ tài liệu bên trong thư mục Lark Drive và nạp vào WeKnora KB & Claims.

        Args:
            chat_id: ID nhóm chat Lark.
            urls: Danh sách đường dẫn liên kết (DocX, Wiki hoặc Thư mục Drive).
            operator_open_id: Lark open_id của người thực hiện.
            operator_name: Tên người thực hiện.
            extract_claims: Có tự động bóc tách Claims/Facts vào MongoDB hay không.

        Returns:
            Dict tóm tắt kết quả xử lý và danh sách tài liệu đã nạp.
        """
        if not chat_id:
            return {"success": False, "message": "chat_id không được để trống.", "processed_docs": []}

        if operator_open_id and not self.is_admin_user(operator_open_id):
            return {
                "success": False,
                "message": "⛔ [TỪ CHỐI] Bạn không có quyền quản trị để nạp tài liệu vào nhóm chat này.",
                "processed_docs": [],
            }

        scope = await self.get_scope_by_chat_id(chat_id)
        effective_dataset_id, _ = await self.get_kb_info_for_chat(chat_id)

        weknora_tenant_id = None
        eff_tk = (scope.tenant_key if scope else None) or get_current_tenant_key()
        if eff_tk:
            from database.db import get_tenant_config
            t_cfg = await get_tenant_config(eff_tk)
            if t_cfg:
                weknora_tenant_id = t_cfg.get("weknora_tenant_id")
                if not effective_dataset_id or effective_dataset_id == settings.WEKNORA_DATASET_ID:
                    effective_dataset_id = t_cfg.get("weknora_default_dataset_id") or effective_dataset_id

        from services.knowledge.doc_parser import doc_parser_service

        processed_docs: List[Dict[str, Any]] = []
        new_knowledge_ids: List[str] = []
        total_claims_count = 0

        existing_doc_map = {}
        if scope and scope.documents:
            for d in scope.documents:
                ft = d.get("file_token")
                kid = d.get("knowledge_id")
                if ft and kid:
                    existing_doc_map[ft] = d
                u = d.get("url")
                if u and kid:
                    existing_doc_map[u] = d

        for raw_url in urls:
            if not raw_url:
                continue
            links = doc_parser_service.extract_lark_links(raw_url)
            if not links:
                folders = doc_parser_service.extract_lark_folders(raw_url)
                if folders:
                    links = folders

            for link in links:
                ltype = link.get("type", "docx")
                token = link.get("token", "")
                url = link.get("url", "")

                if ltype == "folder":
                    logger.info(f"📁 [Scope Ingest] Phân giải thư mục Lark Drive {token} [tenant={eff_tk}]...")
                    folder_docs = await doc_parser_service.parse_lark_folder(token, tenant_key=eff_tk)
                    for doc_res in folder_docs:
                        if not doc_res.success:
                            continue
                        doc_token = doc_res.metadata.get("file_token") or doc_res.metadata.get("document_id") or ""
                        doc_key = f"lark_{doc_res.source_type}_{doc_token}" if doc_token else f"doc_{_sanitize_filename(doc_res.doc_name)}"

                        existing_doc = existing_doc_map.get(doc_key) or existing_doc_map.get(doc_res.metadata.get("url", ""))
                        k_id = existing_doc.get("knowledge_id") if existing_doc else None
                        doc_summary = existing_doc.get("summary") if existing_doc else None

                        if not k_id and doc_res.markdown_content:
                            safe_name = _sanitize_filename(doc_res.doc_name or "document")
                            if not safe_name.lower().endswith(".md"):
                                safe_name = f"{safe_name}.md"
                            doc_bytes = doc_res.markdown_content.encode("utf-8")
                            upload_res = await _get_active_weknora().upload_file(
                                file_name=safe_name,
                                file_bytes=doc_bytes,
                                dataset_id=effective_dataset_id,
                                mime_type="text/markdown",
                                tenant_id=weknora_tenant_id,
                            )
                            k_id = upload_res.get("knowledge_id", "")
                            doc_summary = upload_res.get("summary")

                        if k_id:
                            new_knowledge_ids.append(k_id)
                            doc_entry = {
                                "file_token": doc_key,
                                "name": doc_res.doc_name,
                                "size": len(doc_res.markdown_content.encode("utf-8")) if doc_res.markdown_content else 0,
                                "type": doc_res.source_type,
                                "url": doc_res.metadata.get("url") or url,
                                "folder_token": token,
                                "knowledge_id": k_id,
                                "summary": doc_summary,
                            }
                            processed_docs.append(doc_entry)
                            existing_doc_map[doc_key] = doc_entry

                        if extract_claims:
                            try:
                                from services.chat_service import process_document_to_claims
                                claims_res = await process_document_to_claims(
                                    doc_result=doc_res,
                                    chat_id=chat_id,
                                    sender=operator_name or "Admin",
                                    sender_id=operator_open_id,
                                    project_tag=scope.project_tag if scope else None,
                                    is_owner=True,
                                    tenant_key=eff_tk,
                                )
                                total_claims_count += claims_res.get("new_claims_count", 0)
                            except Exception as ce:
                                logger.warning(f"Không thể bóc tách claims từ {doc_res.doc_name}: {ce}")

                elif ltype in ("docx", "wiki"):
                    if ltype == "docx":
                        doc_res = await doc_parser_service.parse_lark_docx(token, tenant_key=eff_tk)
                    else:
                        doc_res = await doc_parser_service.parse_lark_wiki(token, tenant_key=eff_tk)

                    if doc_res and doc_res.success:
                        doc_key = f"lark_{ltype}_{token}"
                        existing_doc = existing_doc_map.get(doc_key) or existing_doc_map.get(url)
                        k_id = existing_doc.get("knowledge_id") if existing_doc else None
                        doc_summary = existing_doc.get("summary") if existing_doc else None

                        if not k_id and doc_res.markdown_content:
                            safe_name = _sanitize_filename(doc_res.doc_name or f"Lark_{ltype.upper()}_{token}")
                            if not safe_name.lower().endswith(".md"):
                                safe_name = f"{safe_name}.md"
                            doc_bytes = doc_res.markdown_content.encode("utf-8")
                            upload_res = await _get_active_weknora().upload_file(
                                file_name=safe_name,
                                file_bytes=doc_bytes,
                                dataset_id=effective_dataset_id,
                                mime_type="text/markdown",
                                tenant_id=weknora_tenant_id,
                            )
                            k_id = upload_res.get("knowledge_id", "")
                            doc_summary = upload_res.get("summary")

                        if k_id:
                            new_knowledge_ids.append(k_id)
                            doc_entry = {
                                "file_token": doc_key,
                                "name": doc_res.doc_name,
                                "size": len(doc_res.markdown_content.encode("utf-8")) if doc_res.markdown_content else 0,
                                "type": f"lark_{ltype}",
                                "url": url,
                                "knowledge_id": k_id,
                                "summary": doc_summary,
                            }
                            processed_docs.append(doc_entry)
                            existing_doc_map[doc_key] = doc_entry

                        if extract_claims:
                            try:
                                from services.chat_service import process_document_to_claims
                                claims_res = await process_document_to_claims(
                                    doc_result=doc_res,
                                    chat_id=chat_id,
                                    sender=operator_name or "Admin",
                                    sender_id=operator_open_id,
                                    project_tag=scope.project_tag if scope else None,
                                    is_owner=True,
                                    tenant_key=eff_tk,
                                )
                                total_claims_count += claims_res.get("new_claims_count", 0)
                            except Exception as ce:
                                logger.warning(f"Không thể bóc tách claims từ {doc_res.doc_name}: {ce}")

        # Cập nhật bản ghi ChatScope trong MongoDB
        now_iso = get_vietnam_now_iso()
        coll = _get_active_scopes_col()

        if scope:
            all_docs = list(scope.documents or [])
            seen_tokens = {d.get("file_token") for d in all_docs if d.get("file_token")}
            for pd in processed_docs:
                if pd.get("file_token") not in seen_tokens:
                    all_docs.append(pd)
                    seen_tokens.add(pd.get("file_token"))

            all_k_ids = list(dict.fromkeys((scope.knowledge_ids or []) + new_knowledge_ids))

            await coll.update_one(
                {"chat_id": chat_id},
                {
                    "$set": {
                        "documents": all_docs,
                        "knowledge_ids": all_k_ids,
                        "updated_at": now_iso,
                        "updated_by": operator_open_id or "api_upload",
                        "updated_by_name": operator_name or "Admin",
                    }
                },
            )
        else:
            new_scope = ChatScopeRecord(
                chat_id=chat_id,
                chat_name=f"Nhóm {chat_id}",
                dataset_id=effective_dataset_id,
                dataset_name="Knowledge Base Nhóm",
                documents=processed_docs,
                knowledge_ids=list(dict.fromkeys(new_knowledge_ids)),
                updated_by=operator_open_id or "api_upload",
                updated_by_name=operator_name or "Admin",
                created_at=now_iso,
                updated_at=now_iso,
            )
            await coll.update_one(
                {"chat_id": chat_id},
                {"$set": new_scope.to_dict()},
                upsert=True,
            )

        msg = f"✔ Đã xử lý {len(processed_docs)} tài liệu, bóc tách {total_claims_count} facts mới vào nhóm {chat_id}."
        logger.info(f"[ChatScope Ingest] {msg}")
        return {
            "success": True,
            "chat_id": chat_id,
            "dataset_id": effective_dataset_id,
            "total_docs_processed": len(processed_docs),
            "processed_docs": processed_docs,
            "new_claims_count": total_claims_count,
            "message": msg,
        }

    async def sync_group_from_base_record(
        self,
        record: Any,
        target_dataset_id: Optional[str] = None,
        tenant_key_override: Optional[str] = None,
        tenant_config_override: Optional[Dict[str, Any]] = None,
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

        # 5. Xác định Dataset ID, Wiki Dataset ID & Tenant Context
        # Base webhook có thể không gửi tenant_key trong header (đặc biệt với
        # Custom App). Khi đó caller phải truyền tenant đã resolve từ
        # bitable_app_token/table_id; không được phụ thuộc vào ContextVar của
        # task webhook.
        eff_tenant = tenant_key_override or get_current_tenant_key()
        tenant_cfg = tenant_config_override
        from database.db import get_tenant_config, get_tenants_collection
        if tenant_cfg and not eff_tenant:
            eff_tenant = tenant_cfg.get("tenant_key")
        if not tenant_cfg and eff_tenant:
            tenant_cfg = await get_tenant_config(eff_tenant)

        # Nếu chưa có tenant_cfg từ context, tra cứu theo chính scope đã có trong DB.
        # Không còn đo ván "singleton `lark_base_service.app_token` thuộc về tenant nào":
        # giá trị đó do request khác ghi vào và có thể là Base của doanh nghiệp khác.
        if not tenant_cfg and not eff_tenant:
            try:
                existing_s = await self.get_scope_by_chat_id(chat_id)
                if existing_s and existing_s.tenant_key:
                    eff_tenant = existing_s.tenant_key
                    tenant_cfg = await get_tenant_config(eff_tenant)
            except Exception as t_err:
                logger.debug(f"Không thể tra cứu tenant_cfg phụ: {t_err}")

        weknora_tenant_id = None
        if tenant_cfg:
            weknora_tenant_id = tenant_cfg.get("weknora_tenant_id")
            if not target_dataset_id:
                target_dataset_id = tenant_cfg.get("weknora_default_dataset_id") or tenant_cfg.get("weknora_wiki_dataset_id")

        if not weknora_tenant_id:
            logger.error(
                "❌ [ChatScope Sync] Thiếu weknora_tenant_id cho chat=%s, dataset=%s; "
                "WeKnora sẽ từ chối upload bằng TENANT_REQUIRED.",
                chat_id,
                target_dataset_id,
            )
        else:
            logger.info(
                "🔐 [ChatScope Sync] WeKnora routing: tenant_id=%s, dataset=%s, lark_tenant=%s",
                weknora_tenant_id,
                target_dataset_id,
                eff_tenant or "<chưa xác định>",
            )

        # Ưu tiên: cột trong bản ghi -> KB đã resolve của tenant -> rỗng.
        # Tầng `.env` bị bỏ vì nó đưa dataset của đơn vị khác vào một tenant chưa cấu hình.
        raw_kb_field = _extract_text_field(_get_base_field(raw_fields, "dataset_id") or _get_base_field(raw_fields, "knowledge_base_id"))
        effective_dataset_id = raw_kb_field or target_dataset_id or ""
        if "," in effective_dataset_id:
            effective_dataset_id = effective_dataset_id.split(",")[0].strip()

        raw_wiki = _extract_text_field(_get_base_field(raw_fields, "wiki_dataset_id"))
        wiki_dataset_id = raw_wiki or (tenant_cfg.get("weknora_wiki_dataset_id") if tenant_cfg else None) or ""

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
                            tenant_id=weknora_tenant_id,
                        )
                        k_id = upload_res.get("knowledge_id", "")
                        doc_summary = upload_res.get("summary")
                        if k_id:
                            logger.info(f"✔ [ChatScope Sync] WeKnora đã nạp file thành công: knowledge_id={k_id}")
                except Exception as e:
                    logger.error(f"❌ [ChatScope Sync] Lỗi khi xử lý file '{file_name}': {e}", exc_info=True)

            if k_id and not doc_summary:
                try:
                    doc_info = await _get_active_weknora().get_document_info(effective_dataset_id, k_id, tenant_id=weknora_tenant_id)
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

        # 6.2. Xử lý liên kết tài liệu đám mây Lark DocX, Wiki & Thư mục Drive
        for link_info in lark_links:
            link_type = link_info.get("type", "docx")
            token = link_info.get("token", "")
            url = link_info.get("url", "")
            title = link_info.get("title")

            if not token:
                continue

            # 6.2.1. Xử lý Thư mục Lark Drive (Drive Folder - đệ quy và deduplicate trước khi tải)
            if link_type == "folder":
                logger.info(f"📁 [ChatScope Sync] Bắt đầu duyệt danh mục thư mục Lark Drive ({token}) từ Base (tenant={eff_tenant})...")
                try:
                    from services.lark import lark_service
                    import mimetypes

                    async def _collect_folder_items(f_token: str, depth: int = 0) -> List[Dict[str, Any]]:
                        if not f_token or depth > 3:
                            return []
                        raw_items = await lark_service.alist_drive_folder_files(f_token, tenant_key=eff_tenant)
                        collected: List[Dict[str, Any]] = []
                        for it in raw_items:
                            itype = it.get("type", "").lower()
                            if itype == "folder":
                                sub_collected = await _collect_folder_items(it.get("token", ""), depth=depth + 1)
                                collected.extend(sub_collected)
                            else:
                                collected.append(it)
                        return collected

                    folder_items = await _collect_folder_items(token)
                    logger.info(f"📁 [ChatScope Sync] Thư mục {token} chứa {len(folder_items)} tệp (sau khi quét đệ quy).")

                    for item in folder_items:
                        itoken = item.get("token", "")
                        iname = item.get("name", "")
                        itype = item.get("type", "").lower()
                        iurl = item.get("url", "")
                        if not itoken:
                            continue

                        doc_key = f"lark_{itype}_{itoken}"
                        existing_doc = existing_doc_map.get(doc_key) or existing_doc_map.get(iurl)
                        k_id = existing_doc.get("knowledge_id") if existing_doc else None
                        doc_summary = existing_doc.get("summary") if existing_doc else None
                        doc_name = existing_doc.get("name") if existing_doc else None
                        doc_size = existing_doc.get("size", 0) if existing_doc else 0

                        # DEDUPLICATION: Nếu tài liệu đã được nạp vào WeKnora ở lần trước -> BỎ QUA NGAY
                        if not k_id:
                            try:
                                if itype == "docx":
                                    doc_res = await doc_parser_service.parse_lark_docx(document_id=itoken, title=iname, tenant_key=eff_tenant)
                                    if doc_res and doc_res.success and doc_res.markdown_content:
                                        safe_name = _sanitize_filename(doc_res.doc_name or iname or f"DocX_{itoken}")
                                        if not safe_name.lower().endswith(".md"):
                                            safe_name = f"{safe_name}.md"
                                        doc_bytes = doc_res.markdown_content.encode("utf-8")
                                        doc_name = safe_name
                                        doc_size = len(doc_bytes)
                                        upload_res = await _get_active_weknora().upload_file(
                                            file_name=doc_name,
                                            file_bytes=doc_bytes,
                                            dataset_id=effective_dataset_id,
                                            mime_type="text/markdown",
                                            tenant_id=weknora_tenant_id,
                                        )
                                        k_id = upload_res.get("knowledge_id", "")
                                        doc_summary = upload_res.get("summary")
                                        if k_id:
                                            logger.info(f"✔ [ChatScope Sync] Đã nạp Lark DocX '{doc_name}' vào KB {effective_dataset_id}")
                                elif itype == "wiki":
                                    doc_res = await doc_parser_service.parse_lark_wiki(wiki_token=itoken, tenant_key=eff_tenant)
                                    if doc_res and doc_res.success and doc_res.markdown_content:
                                        safe_name = _sanitize_filename(doc_res.doc_name or iname or f"Wiki_{itoken}")
                                        if not safe_name.lower().endswith(".md"):
                                            safe_name = f"{safe_name}.md"
                                        doc_bytes = doc_res.markdown_content.encode("utf-8")
                                        doc_name = safe_name
                                        doc_size = len(doc_bytes)
                                        upload_res = await _get_active_weknora().upload_file(
                                            file_name=doc_name,
                                            file_bytes=doc_bytes,
                                            dataset_id=effective_dataset_id,
                                            mime_type="text/markdown",
                                            tenant_id=weknora_tenant_id,
                                        )
                                        k_id = upload_res.get("knowledge_id", "")
                                        doc_summary = upload_res.get("summary")
                                        if k_id:
                                            logger.info(f"✔ [ChatScope Sync] Đã nạp Lark Wiki '{doc_name}' vào KB {effective_dataset_id}")
                                elif itype == "file":
                                    # Tệp ngoài (PDF, Word, Excel, CSV, MD...): Tải binary và bắn thẳng sang WeKnora
                                    # WeKnora tự động sử dụng container DocReader nội bộ của nó
                                    logger.info(f"📥 [ChatScope Sync] Đang tải tệp ngoài '{iname}' ({itoken}) từ Lark Drive...")
                                    file_bytes = await lark_service.adownload_drive_file(itoken, tenant_key=eff_tenant)
                                    if file_bytes:
                                        doc_name = iname or f"file_{itoken}"
                                        doc_size = len(file_bytes)
                                        guessed_mime, _ = mimetypes.guess_type(doc_name)
                                        mime_type = guessed_mime or "application/octet-stream"
                                        logger.info(f"📤 [ChatScope Sync] Đang nạp tệp ngoài '{doc_name}' ({doc_size} bytes, mime={mime_type}) sang WeKnora...")
                                        upload_res = await _get_active_weknora().upload_file(
                                            file_name=doc_name,
                                            file_bytes=file_bytes,
                                            dataset_id=effective_dataset_id,
                                            mime_type=mime_type,
                                            tenant_id=weknora_tenant_id,
                                        )
                                        k_id = upload_res.get("knowledge_id", "")
                                        doc_summary = upload_res.get("summary")
                                        if k_id:
                                            logger.info(f"✔ [ChatScope Sync] Đã nạp tệp ngoài '{doc_name}' thành công vào KB {effective_dataset_id}: k_id={k_id}")
                            except Exception as file_err:
                                logger.error(f"❌ [ChatScope Sync] Lỗi khi nạp file '{iname}' ({itoken}): {file_err}")

                        if k_id and not doc_summary:
                            try:
                                doc_info = await _get_active_weknora().get_document_info(effective_dataset_id, k_id, tenant_id=weknora_tenant_id)
                                if doc_info and doc_info.get("summary"):
                                    doc_summary = doc_info["summary"]
                            except Exception:
                                pass

                        if k_id:
                            synced_docs.append({
                                "file_token": doc_key,
                                "name": doc_name or iname or f"Lark_{itype.upper()}_{itoken}",
                                "size": doc_size,
                                "type": f"lark_{itype}",
                                "url": iurl or url,
                                "folder_token": token,
                                "knowledge_id": k_id,
                                "summary": doc_summary,
                            })
                            knowledge_ids.append(k_id)
                except Exception as e:
                    logger.error(f"❌ [ChatScope Sync] Lỗi khi xử lý Lark Folder link '{url}': {e}", exc_info=True)
                continue

            # 6.2.2. Xử lý tài liệu đơn lẻ DocX & Wiki
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
                        doc_res = await doc_parser_service.parse_lark_docx(document_id=token, title=title, tenant_key=eff_tenant)
                    elif link_type == "wiki":
                        doc_res = await doc_parser_service.parse_lark_wiki(wiki_token=token, tenant_key=eff_tenant)
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
                            tenant_id=weknora_tenant_id,
                        )
                        k_id = upload_res.get("knowledge_id", "")
                        doc_summary = upload_res.get("summary")
                        if k_id:
                            logger.info(f"✔ [ChatScope Sync] WeKnora đã nạp Lark Doc thành công: knowledge_id={k_id}")
                        elif not upload_res.get("success", False):
                            logger.error(
                                "❌ [ChatScope Sync] WeKnora từ chối nạp Lark Doc '%s': %s",
                                doc_name,
                                upload_res.get("error") or upload_res,
                            )
                    else:
                        err_msg = doc_res.error if doc_res else "Phân giải tài liệu không thành công"
                        logger.warning(f"⚠️ [ChatScope Sync] Không thể phân giải Lark {link_type} ({token}): {err_msg}")
                except Exception as e:
                    logger.error(f"❌ [ChatScope Sync] Lỗi khi xử lý Lark Doc link '{url}': {e}", exc_info=True)

            if k_id and not doc_summary:
                try:
                    doc_info = await _get_active_weknora().get_document_info(effective_dataset_id, k_id, tenant_id=weknora_tenant_id)
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

        resolved_tenant_key = eff_tenant or (tenant_cfg.get("tenant_key") if tenant_cfg else None)

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
            tenant_key=resolved_tenant_key,
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

    async def sync_all_groups_from_base(self, tenant_key: Optional[str] = None) -> List[ChatScopeRecord]:
        """
        Quét và đồng bộ toàn bộ bảng Lark Base của MỘT tenant sang MongoDB và WeKnora.

        Không còn ghi đè `app_token`/`table_id` lên singleton dùng chung: mỗi lần chạy
        tạo một `LarkBaseService` riêng từ `TenantResources` của tenant đang xử lý.
        """
        from database.db import get_current_tenant_key
        from services.lark.bitable import LarkBaseService
        from services.tenancy.tenant_resolver import tenant_resolver

        eff_tenant = tenant_key or get_current_tenant_key()
        if not eff_tenant:
            logger.warning("[ChatScope Sync] Bỏ qua quét toàn bảng Base: không có tenant_key nào.")
            return []
        try:
            resources = await tenant_resolver.resolve(eff_tenant)
        except TenantResolutionError as exc:
            logger.warning("[ChatScope Sync] Bỏ qua tenant '%s': %s", eff_tenant, exc)
            return []

        try:
            base_service = LarkBaseService.for_tenant(resources)
            records = await base_service.aget_all_records(use_tenant_token=True)
            results = []
            for r in records:
                rec = await self.sync_group_from_base_record(
                    r,
                    tenant_key_override=eff_tenant,
                    tenant_config_override=None,
                )
                if rec:
                    results.append(rec)
            logger.info(f"🎉 [ChatScope Sync] Đã quét và đồng bộ thành công {len(results)} nhóm từ Lark Base của tenant '{eff_tenant}'!")
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
            file_token = getattr(event, "file_token", "")
            action_list = getattr(event, "action_list", []) or []
            record_ids = [getattr(a, "record_id", "") for a in action_list if getattr(a, "record_id", "")]
            if not record_ids:
                return

            # Tra cứu tenant sở hữu file_token hoặc table_id này
            header = getattr(event_data, "header", None)
            tenant_key = getattr(header, "tenant_key", "") if header else ""
            app_id = getattr(header, "app_id", "") if header else ""

            tenant = None
            try:
                from database.db import get_tenants_collection
                t_col = get_tenants_collection()
                tenant = await t_col.find_one({"$or": [
                    {"bitable_app_token": file_token},
                    {"company_policy_table_id": table_id},
                    {"chat_scope_table_id": table_id},
                ]})
                if not tenant and tenant_key:
                    tenant = await t_col.find_one({"tenant_key": tenant_key})
                if not tenant and app_id:
                    tenant = await t_col.find_one({"app_id": app_id})
            except Exception as t_lookup_err:
                logger.debug(f"Không thể tra cứu tenant cho bitable change: {t_lookup_err}")

            is_policy_table = False
            if table_id and tenant and tenant.get("company_policy_table_id") == table_id:
                is_policy_table = True

            # Kiểm tra nếu sự kiện xuất phát từ Bảng Chính Sách Công Ty
            if is_policy_table:
                logger.info(f"🏛️ [Bitable Realtime Event] Phát hiện thay đổi trong Bảng Chính Sách ({table_id}) -> Kích hoạt Policy Sync!")
                from services.knowledge.policy_sync import policy_sync_service
                await policy_sync_service.sync_policies(
                    tenant_key=tenant.get("tenant_key") if tenant else None,
                    force=True,
                )
                return

            if not tenant:
                # Không xác định được chủ sở hữu Base thì dừng: đọc tiếp sẽ phải đoán,
                # mà đoán sai là ghi dữ liệu nhóm của doanh nghiệp này vào hệ thống của doanh nghiệp khác.
                logger.warning(
                    "⚠️ [Bitable Realtime Event] Không tìm thấy tenant sở hữu Base '%s' (table '%s') — bỏ qua sự kiện.",
                    file_token,
                    table_id,
                )
                return

            print(f"🔄 [Bitable Realtime Event] Phát hiện {len(record_ids)} bản ghi thay đổi trong Base '{file_token}' (table '{table_id}') của tenant '{tenant.get('tenant_key')}', tiến hành đồng bộ: {record_ids}")
            logger.info(f"🔄 [Bitable Realtime Event] Phát hiện {len(record_ids)} bản ghi thay đổi trong Base '{file_token}' (table '{table_id}') của tenant '{tenant.get('tenant_key')}', tiến hành đồng bộ: {record_ids}")
            from services.lark.bitable import LarkBaseService

            eff_tk = tenant.get("tenant_key") if tenant else tenant_key
            app_token = file_token or (tenant.get("bitable_app_token") if tenant else "")
            target_table_id = table_id or (tenant.get("chat_scope_table_id") if tenant else "")

            base_service = LarkBaseService(
                tenant_key=eff_tk,
                app_token=app_token,
                table_id=target_table_id,
            )

            target_ds_id = tenant.get("weknora_default_dataset_id") if tenant else None

            records = await base_service.aget_all_records(use_tenant_token=True)
            record_map = {r.record_id: r for r in records}

            for rid in record_ids:
                target_record = record_map.get(rid)
                if target_record:
                    await self.sync_group_from_base_record(
                        target_record,
                        target_dataset_id=target_ds_id,
                        tenant_key_override=eff_tk,
                        tenant_config_override=tenant,
                    )
                else:
                    logger.warning(
                        "⚠️ [Bitable Realtime Event] Không tìm thấy record %s trong bảng %s để đồng bộ.",
                        rid,
                        table_id,
                    )
        except Exception as e:
            logger.error(f"Lỗi khi xử lý sự kiện bitable_record_changed: {e}", exc_info=True)

    async def start_loop(self, interval_seconds: int = 30) -> None:
        """
        Vòng lặp chạy nền định kỳ đồng bộ Chat Scopes & Nhãn từ Lark Base cho các tenant 'ready'.
        Đảm bảo tính nhất quán (Eventual Consistency) ngay cả khi webhook bị trễ hoặc ngắt kết nối.
        """
        import asyncio
        logger.info(f"⏰ [ScopeSync Loop] Khởi động worker đồng bộ Chat Scopes định kỳ (Chu kỳ {interval_seconds}s).")
        # Chờ 15s sau khi server khởi động để hệ thống bootstrap ổn định
        await asyncio.sleep(15)
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                from database.db import get_tenants_collection
                t_col = get_tenants_collection()
                async for t_doc in t_col.find({"status": "ready"}, {"tenant_key": 1}):
                    tk = t_doc.get("tenant_key")
                    if tk:
                        try:
                            await self.sync_all_groups_from_base(tenant_key=tk)
                        except Exception as sync_err:
                            logger.debug(f"[ScopeSync Loop] Lỗi sync tenant {tk}: {sync_err}")
            except asyncio.CancelledError:
                logger.info("[ScopeSync Loop] Đã nhận tín hiệu dừng worker.")
                break
            except Exception as e:
                logger.warning(f"[ScopeSync Loop] Lỗi worker: {e}")
                await asyncio.sleep(15)


# Hai import bên dưới phải là import lười (bên trong hàm), không được đặt ở mức module:
# `services.lark.cleaner` kích hoạt `services/lark/__init__.py` -> `bot_runner` ->
# `chat_workflow` -> `from services.knowledge.chat_scopes import scope_service`, và
# `scope_service` chưa kịp tồn tại vì file này đang được thực thi tới dòng 1251.


def _extract_text_field(val: Any) -> str:
    """Trích xuất chuỗi văn bản sạch từ các kiểu dữ liệu của Lark Base."""
    from services.lark.cleaner import clean_field_value

    cleaned = clean_field_value(val)
    if cleaned is None:
        return ""
    if isinstance(cleaned, list):
        return ", ".join(str(x) for x in cleaned if x)
    return str(cleaned).strip()


def _extract_labels(*args: Any, **kwargs: Any):
    """Wrapper lười của `rule_engine.parse_labels` để không kéo theo `services.knowledge`."""
    from services.knowledge.rule_engine import parse_labels

    return parse_labels(*args, **kwargs)


# Singleton instance
scope_service = ScopeService()

__all__ = [
    "ScopeService",
    "scope_service",
]

