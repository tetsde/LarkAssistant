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
from services.doc_parser_service import doc_parser_service as default_doc_parser
from services.lark import lark_service as default_lark_service

logger = logging.getLogger("hilark.bot.document_handler")


def _resolve_dependencies():
    """Giải quyết dependencies linh hoạt: ưu tiên thuộc tính trong services.bot_service
    nếu đang bị patch bởi test suite (Backward Compatibility), ngược lại dùng default singletons.
    """
    bs = sys.modules.get("services.bot_service")
    doc_parser = getattr(bs, "doc_parser_service", default_doc_parser) if bs else default_doc_parser
    process_claims = getattr(bs, "process_document_to_claims", default_process_claims) if bs else default_process_claims
    lark = getattr(bs, "lark_service", default_lark_service) if bs else default_lark_service
    return doc_parser, process_claims, lark


async def handle_document_or_links(msg: LarkMessage) -> bool:
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
        if not doc_parser._docreader.is_supported_file(file_name):
            print(f"🚫 [ATTACHMENT GATE] Bỏ qua file '{file_name}' vì không thuộc định dạng được hỗ trợ.")
            if msg.chat_type == "p2p":
                await lark.areply_text(
                    msg.message_id,
                    f"⚠️ Tệp \"{file_name}\" không thuộc định dạng tài liệu được hỗ trợ (chỉ hỗ trợ: Word, PDF, Excel, PPTX, TXT, MD, hình ảnh)."
                )
            return True

        print(f"📄 [ATTACHMENT DETECTED] Bắt đầu phân giải tệp: {file_name} (key: {file_key})...")
        await lark.areply_text(
            msg.message_id,
            f"📄 Trợ lý đang đọc và trích xuất thông tin từ tài liệu \"{file_name}\"..."
        )

        doc_res = await doc_parser.parse_attachment(
            message_id=msg.message_id,
            file_key=file_key,
            file_name=file_name,
            resource_type=msg.message_type,
        )

        if not doc_res.success:
            print(f"❌ [ATTACHMENT FAILED] Phân giải thất bại: {doc_res.error}")
            await lark.areply_text(
                msg.message_id,
                f"⚠️ Không thể đọc nội dung tài liệu \"{file_name}\": {doc_res.error}"
            )
            return True

        # Trích xuất Claims & Entities vào MongoDB
        claims_res = await process_claims(
            doc_result=doc_res,
            chat_id=msg.chat_id,
            sender=msg.sender_id,
            sender_id=msg.sender_id,
            message_id=msg.message_id,
        )

        new_count = claims_res.get("new_claims_count", 0)
        superseded_count = claims_res.get("superseded_claims_count", 0)
        print(f"✅ [ATTACHMENT SUCCESS] Đã lưu {new_count} facts mới vào MongoDB từ {file_name}.")

        reply_msg = f"✅ Đã tiếp thu tri thức từ \"{file_name}\": Ghi nhận {new_count} sự thật mới vào bộ nhớ nhóm."
        if superseded_count > 0:
            reply_msg += f" (Đã cập nhật thay thế {superseded_count} thông tin cũ)."
        await lark.areply_text(msg.message_id, reply_msg)
        return True

    # 2. Xử lý liên kết Lark Cloud DocX / Wiki (Lark Doc Links - EDL-0010)
    if msg.message_type == "text" and msg.text:
        lark_links = doc_parser.extract_lark_links(msg.text)
        if lark_links:
            print(f"🔗 [LARK LINKS DETECTED] Tìm thấy {len(lark_links)} liên kết tài liệu Lark trong tin nhắn.")
            handled_any = False
            for link in lark_links:
                if link["type"] == "docx":
                    doc_res = await doc_parser.parse_lark_docx(link["token"])
                elif link["type"] == "wiki":
                    doc_res = await doc_parser.parse_lark_wiki(link["token"])
                else:
                    continue

                if doc_res.success:
                    claims_res = await process_claims(
                        doc_result=doc_res,
                        chat_id=msg.chat_id,
                        sender=msg.sender_id,
                        sender_id=msg.sender_id,
                        message_id=msg.message_id,
                    )
                    new_count = claims_res.get("new_claims_count", 0)
                    superseded_count = claims_res.get("superseded_claims_count", 0)
                    confirm_link_text = f"✅ Đã tiếp thu tri thức từ {doc_res.doc_name}: Ghi nhận {new_count} sự thật mới vào bộ nhớ."
                    if superseded_count > 0:
                        confirm_link_text += f" (Đã cập nhật thay thế {superseded_count} thông tin cũ)."
                    await lark.areply_text(msg.message_id, confirm_link_text)
                    handled_any = True

            if handled_any:
                return True

    return False
