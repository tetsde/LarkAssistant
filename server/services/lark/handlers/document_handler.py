"""
Document & Attachment Handler for Lark Bot
==========================================
Vị trí: server/services/bot_handlers/document_handler.py

Mục đích:
    - Xử lý các tệp đính kèm nhị phân (Word, PDF, Excel, PPTX, hình ảnh) qua gRPC AnyDoc.
    - Xử lý các liên kết Lark DocX và Wiki xuất hiện trong nội dung tin nhắn.
    - Trích xuất Claims & Entities vào MongoDB nhằm cập nhật tri thức động cho nhóm chat.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from models.lark import LarkMessage
from services.chat_service import process_document_to_claims as default_process_claims
from services.knowledge.doc_parser import doc_parser_service as default_doc_parser
from services.lark import lark_service as default_lark_service

logger = logging.getLogger("hilark.bot.document_handler")


def _resolve_dependencies():
    """Giải quyết dependencies linh hoạt: ưu tiên thuộc tính trong services.bot_service
    hoặc services.lark.bot_runner nếu đang bị patch bởi test suite (Backward Compatibility),
    ngược lại dùng default singletons.
    """
    bs = sys.modules.get("services.bot_service") or sys.modules.get("services.lark.bot_runner")
    doc_parser = getattr(bs, "doc_parser_service", default_doc_parser) if bs else default_doc_parser
    process_claims = getattr(bs, "process_document_to_claims", default_process_claims) if bs else default_process_claims
    from services.lark.runtime import get_current_lark_service
    fallback_lark = getattr(bs, "lark_service", default_lark_service) if bs else default_lark_service
    lark = get_current_lark_service(fallback_lark)
    return doc_parser, process_claims, lark


async def handle_document_or_links(msg: LarkMessage, is_owner: bool = False) -> bool:
    """
    Kiểm tra và xử lý tệp đính kèm hoặc liên kết tài liệu Lark trong tin nhắn.
    Trả về True nếu tin nhắn chứa tài liệu/liên kết và đã được thụ lý, ngược lại trả về False.
    """
    doc_parser, process_claims, lark = _resolve_dependencies()

    # 1. Xử lý tệp đính kèm hoặc hình ảnh (Binary Attachments - EDL-0010)
    if msg.message_type in ("file", "image"):
        file_key = msg.file_key or msg.image_key
        file_name = msg.file_name or ("image.png" if msg.message_type == "image" else "document")

        if not file_key:
            print(f"⚠️ [ATTACHMENT] Tin nhắn {msg.message_id} là {msg.message_type} nhưng không tìm thấy file_key/image_key.")
            return True

        # Kiểm tra Extension Gate
        if not doc_parser._docreader.is_supported_file(file_name) and not doc_parser.is_image_file(file_name, msg.message_type):
            print(f"Bỏ qua file '{file_name}' vì không thuộc định dạng được hỗ trợ.")
            if msg.chat_type == "p2p":
                await lark.areply_text(
                    msg.message_id,
                    f"Tệp \"{file_name}\" không thuộc định dạng tài liệu được hỗ trợ (chỉ hỗ trợ: Word, PDF, Excel, PPTX, TXT, MD, hình ảnh)."
                )
            return True

        print(f"Bắt đầu phân giải tệp: {file_name} (key: {file_key})...")

        doc_res = await doc_parser.parse_attachment(
            message_id=msg.message_id,
            file_key=file_key,
            file_name=file_name,
            resource_type=msg.message_type,
        )

        if not doc_res.success:
            print(f"Phân giải thất bại: {doc_res.error}")
            if msg.chat_type == "p2p":
                await lark.areply_text(
                    msg.message_id,
                    f"Không thể đọc nội dung tài liệu \"{file_name}\": {doc_res.error}"
                )
            return True

        # Trích xuất Claims & Entities vào MongoDB (Chế độ âm thầm - Silent Ingestion)
        claims_res = await process_claims(
            doc_result=doc_res,
            chat_id=msg.chat_id,
            sender=msg.sender_id,
            sender_id=msg.sender_id,
            message_id=msg.message_id,
            is_owner=is_owner,
            tenant_key=msg.tenant_key,
        )

        new_count = claims_res.get("new_claims_count", 0)
        superseded_count = claims_res.get("superseded_claims_count", 0)
        logger.info(
            f"✔ [SILENT INGESTION] Đã lưu {new_count} facts mới vào MongoDB từ '{file_name}' "
            f"(superseded={superseded_count}, is_owner={is_owner}). Không phát ngôn vào nhóm chat."
        )
        print(f"✔ Đã âm thầm lưu {new_count} facts mới từ '{file_name}' vào MongoDB (không phát ngôn vào nhóm).")

        # Tự động nạp tài liệu vào WeKnora Knowledge Base
        try:
            from services.knowledge.chat_scopes import scope_service, _get_active_weknora, _sanitize_filename
            effective_dataset_id, _ = await scope_service.get_kb_info_for_chat(msg.chat_id, tenant_key=msg.tenant_key)
            if effective_dataset_id:
                weknora_tenant_id = None
                if msg.tenant_key:
                    from database.db import get_tenant_config
                    t_cfg = await get_tenant_config(msg.tenant_key)
                    if t_cfg:
                        weknora_tenant_id = t_cfg.get("weknora_tenant_id")

                upload_name = file_name
                upload_bytes = getattr(doc_res, "raw_bytes", None) or (doc_res.markdown_content.encode("utf-8") if doc_res.markdown_content else None)
                mime = "text/markdown" if not getattr(doc_res, "raw_bytes", None) else ("application/pdf" if file_name.endswith(".pdf") else "application/octet-stream")
                if upload_bytes:
                    if not getattr(doc_res, "raw_bytes", None) and not upload_name.lower().endswith(".md"):
                        upload_name = f"{upload_name}.md"
                    await _get_active_weknora().upload_file(
                        file_name=_sanitize_filename(upload_name),
                        file_bytes=upload_bytes,
                        dataset_id=effective_dataset_id,
                        mime_type=mime,
                        tenant_id=weknora_tenant_id,
                    )
                    logger.info(f"✔ [DOC HANDLER] Đã tải nạp '{upload_name}' sang WeKnora KB {effective_dataset_id}")
        except Exception as weknora_up_err:
            logger.warning(f"Lỗi khi nạp file sang WeKnora trong document_handler: {weknora_up_err}")

        return True

    # 2. Xử lý liên kết Lark Cloud DocX / Wiki (Lark Doc Links - EDL-0010)
    if msg.message_type == "text" and msg.text:
        lark_links = doc_parser.extract_lark_links(msg.text)
        if lark_links:
            print(f"Tìm thấy {len(lark_links)} liên kết tài liệu Lark trong tin nhắn.")
            handled_any = False
            for link in lark_links:
                if link["type"] == "docx":
                    doc_res = await doc_parser.parse_lark_docx(link["token"])
                    doc_res_list = [doc_res] if doc_res else []
                elif link["type"] == "wiki":
                    doc_res = await doc_parser.parse_lark_wiki(link["token"])
                    doc_res_list = [doc_res] if doc_res else []
                elif link["type"] == "folder":
                    print(f"📁 [FOLDER LINK] Bắt đầu phân giải toàn bộ tài liệu trong thư mục Lark Drive {link['token']}...")
                    doc_res_list = await doc_parser.parse_lark_folder(link["token"])
                else:
                    continue

                for doc_res in doc_res_list:
                    if doc_res and doc_res.success:
                        claims_res = await process_claims(
                            doc_result=doc_res,
                            chat_id=msg.chat_id,
                            sender=msg.sender_id,
                            sender_id=msg.sender_id,
                            message_id=msg.message_id,
                            is_owner=is_owner,
                            tenant_key=msg.tenant_key,
                        )
                        new_count = claims_res.get("new_claims_count", 0)
                        superseded_count = claims_res.get("superseded_claims_count", 0)
                        logger.info(
                            f"✔ [SILENT INGESTION] Đã lưu {new_count} facts mới từ Lark Doc '{doc_res.doc_name}' "
                            f"(superseded={superseded_count}, is_owner={is_owner}). Không phát ngôn vào nhóm chat."
                        )
                        print(f"✔ Đã âm thầm lưu {new_count} facts từ Lark Doc '{doc_res.doc_name}' vào MongoDB (không phát ngôn vào nhóm).")

                        # Nạp tài liệu lên WeKnora Knowledge Base
                        try:
                            from services.knowledge.chat_scopes import scope_service, _get_active_weknora, _sanitize_filename
                            effective_dataset_id, _ = await scope_service.get_kb_info_for_chat(msg.chat_id, tenant_key=msg.tenant_key)
                            if effective_dataset_id and doc_res.markdown_content:
                                weknora_tenant_id = None
                                if msg.tenant_key:
                                    from database.db import get_tenant_config
                                    t_cfg = await get_tenant_config(msg.tenant_key)
                                    if t_cfg:
                                        weknora_tenant_id = t_cfg.get("weknora_tenant_id")

                                safe_name = _sanitize_filename(doc_res.doc_name or "lark_doc")
                                if not safe_name.lower().endswith(".md"):
                                    safe_name = f"{safe_name}.md"
                                await _get_active_weknora().upload_file(
                                    file_name=safe_name,
                                    file_bytes=doc_res.markdown_content.encode("utf-8"),
                                    dataset_id=effective_dataset_id,
                                    mime_type="text/markdown",
                                    tenant_id=weknora_tenant_id,
                                )
                                logger.info(f"✔ [DOC HANDLER] Đã tải nạp Lark Doc '{safe_name}' sang WeKnora KB {effective_dataset_id}")
                        except Exception as w_err:
                            logger.warning(f"Lỗi khi tải nạp Lark Doc sang WeKnora: {w_err}")

                        handled_any = True

            if handled_any:
                return True

    return False

