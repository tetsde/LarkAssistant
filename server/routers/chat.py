import logging
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from core.config import settings
from models import ChatRequest, MemoryRequest, UserChatRequest, ApproveDraftRequest
from services.weknora import WeKnoraService, weknora_service
from services.jev import jev_service
from services.lark import lark_service
from services.draft_store import PendingDraft, draft_store
from utils.text_filter import text_filter
from utils.context_composer import ContextComposer
from utils.llm_extractor import extract_async, GeminiClient
from database import (
    check_mongo_connection,
    get_all_entities as get_mongo_entities,
    get_all_facts as get_mongo_facts,
    save_extraction_to_mongo,
    clear_mongo_stores,
)

logger = logging.getLogger("hilark.chat")
router = APIRouter(prefix="/api/chat", tags=["chat"])


GROUNDED_QA_SYSTEM_PROMPT = """Bạn là Trợ lý Doanh nghiệp HiLark (HiLark AI Assistant) chuyên nghiệp, thông minh, chính xác và trung thực.

Nhiệm vụ của bạn là trả lời câu hỏi của người dùng DỰA HOÀN TOÀN TRÊN BỘ BỐI CẢNH TRI THỨC dưới đây.

=== BỘ BỐI CẢNH TRI THỨC (KNOWLEDGE CONTEXT) ===
{context_text}

=== CÂU HỎI CỦA NGƯỜI DÙNG ===
{query}

=== QUY TẮC BẮT BUỘC KHI TRẢ LỜI ===
1. NGUYÊN TẮC ƯU TIÊN SỰ THẬT (Fact Override):
   - "PHẦN 2: THỰC TẾ CẬP NHẬT & MỆNH ĐỀ ĐỘNG (MONGODB CLAIMS)" chứa các thông tin cập nhật thời gian thực từ hội thoại trao đổi.
   - Nếu có mâu thuẫn giữa "PHẦN 1: TÀI LIỆU DỰ ÁN & VĂN BẢN (WEKNORA)" và "PHẦN 2: CLAIMS", thông tin có trạng thái [CURRENT] trong Claims LUÔN ĐƯỢC ƯU TIÊN TUYỆT ĐỐI.
   - Khi phát hiện thông tin đã thay đổi (ví dụ: chuyển giao người phụ trách, ngân sách thay đổi, deadline điều chỉnh), bạn PHẢI nêu rõ sự thay đổi và quá trình biến động để người dùng nắm bắt (Ví dụ: "Theo tài liệu ban đầu là Nam làm Project Lead, tuy nhiên theo cập nhật mới nhất đã chuyển giao cho Nguyên đảm nhiệm").
2. TRUNG THỰC & GROUNDED:
   - Tuyệt đối không suy diễn hoặc bịa đặt thông tin không có trong bối cảnh.
   - Nếu bối cảnh không có dữ liệu để trả lời câu hỏi, hãy lịch sự thông báo rõ rằng hệ thống chưa ghi nhận thông tin này.
3. TRÍCH DẪN NGUỒN:
   - Trích dẫn rõ ràng nguồn thông tin nếu có (ví dụ: [Tài liệu: du_an_mau_hilark.pdf] hoặc [Cập nhật hội thoại: ...]).
4. ĐÚNG TRỌNG TÂM, GỌN GÀNG & ĐỦ Ý (GIỚI HẠN MAX 4096 TOKENS):
   - Hệ thống cấp cho bạn giới hạn phản hồi tối đa là 4096 tokens (max output tokens = 4096).
   - Bạn PHẢI trả lời cô đọng, dứt khoát, đi thẳng vào đúng trọng tâm câu hỏi dựa trên dữ liệu tri thức truy vấn được.
   - TUYỆT ĐỐI KHÔNG viết dông dài lan man, không lặp lại câu hỏi khiến câu trả lời bị đứt đoạn hay cụt câu giữa chừng.
   - BẮT BUỘC hoàn thành trọn vẹn toàn bộ các câu và đoạn văn, đảm bảo có phần kết thúc mạch lạc, hoàn chỉnh.
"""

GROUNDED_QA_USER_PERSONA_PROMPT = """Bạn là {responder_name} ({role}) của dự án HiLark.
Bạn đang trực tiếp phản hồi ĐÍCH DANH cho thành viên/đồng nghiệp: {user_name}.

Nhiệm vụ của bạn là giải đáp câu hỏi của {user_name} một cách tự nhiên, chân thành, thân thiện nhưng chuẩn xác và chuyên nghiệp, DỰA HOÀN TOÀN TRÊN BỘ BỐI CẢNH TRI THỨC dưới đây.

=== BỘ BỐI CẢNH TRI THỨC (KNOWLEDGE CONTEXT) ===
{context_text}

=== CÂU HỎI TỪ {user_name} ===
{query}

=== QUY TẮC BẮT BUỘC KHI TRẢ LỜI ===
1. XƯNG HÔ VÀ PHONG CÁCH ĐÍCH DANH (BẮT BUỘC):
   - BẮT BUỘC chào hỏi và xưng hô ĐÍCH DANH với {user_name} ở đầu câu trả lời (Ví dụ: "Chào {user_name}, về câu hỏi của bạn/em...", "Chào {user_name}, dự án HiLark...").
   - Trả lời bằng giọng văn của con người thật ({responder_name}), tự nhiên, ấm áp, uy tín.
   - TUYỆT ĐỐI KHÔNG xưng "Tôi là trợ lý ảo/AI/bot". Hãy trả lời tự nhiên như bạn đang nhắn tin trao đổi trực tiếp trong nhóm.
2. NGUYÊN TẮC ƯU TIÊN SỰ THẬT (Fact Override):
   - "PHẦN 2: THỰC TẾ CẬP NHẬT & MỆNH ĐỀ ĐỘNG (MONGODB CLAIMS)" chứa các thông tin cập nhật thời gian thực từ hội thoại trao đổi.
   - Nếu có mâu thuẫn giữa "PHẦN 1: TÀI LIỆU DỰ ÁN & VĂN BẢN (WEKNORA)" và "PHẦN 2: CLAIMS", thông tin có trạng thái [CURRENT] trong Claims LUÔN ĐƯỢC ƯU TIÊN TUYỆT ĐỐI.
   - Khi phát hiện thông tin đã thay đổi (deadline điều chỉnh, ngân sách, phân công nhân sự), bạn PHẢI giải thích rõ để {user_name} nắm được tình hình.
3. TRUNG THỰC & GROUNDED:
   - Tuyệt đối không bịa đặt thông tin không có trong bối cảnh.
   - Nếu bối cảnh chưa có thông tin, hãy thành thật trả lời {user_name} rằng mình chưa ghi nhận thông tin này và sẽ kiểm tra lại sau.
4. ĐÚNG TRỌNG TÂM, GỌN GÀNG & ĐỦ Ý (GIỚI HẠN MAX 4096 TOKENS):
   - Hệ thống cấp cho bạn giới hạn phản hồi tối đa là 4096 tokens (max output tokens = 4096).
   - Trả lời bằng tiếng Việt gãy gọn, cô đọng, đi thẳng vào đúng trọng tâm thắc mắc của {user_name}.
   - TUYỆT ĐỐI KHÔNG viết dông dài lan man dẫn đến việc câu trả lời bị đứt đoạn, cụt câu giữa chừng.
   - BẮT BUỘC hoàn thành trọn vẹn toàn bộ các câu văn, đảm bảo có lời chào kết thúc tự nhiên, mạch lạc.
"""


async def process_memory_extraction(query_text: str, sender: str = "User") -> Dict[str, Any]:
    """Helper xử lý trích xuất Entities & Facts và lưu trực tiếp vào MongoDB."""
    msg_id = f"msg_{uuid.uuid4().hex[:8]}"

    try:
        existing_entities = await get_mongo_entities()
        existing_facts = await get_mongo_facts()
    except Exception as e:
        logger.error(f"Lỗi khi đọc từ MongoDB: {e}")
        existing_entities = []
        existing_facts = []

    extraction_result = await extract_async(
        query=query_text,
        workspace_id="default",
        source_message_id=msg_id,
        sender=sender,
        existing_entities=existing_entities,
        existing_facts=existing_facts,
    )

    mongo_saved = await save_extraction_to_mongo(extraction_result)

    total_entities = mongo_saved.get("total_stored_entities", 0)
    total_facts = mongo_saved.get("total_stored_facts", 0)

    return {
        "message_id": msg_id,
        "entities": mongo_saved.get("entities", []),
        "facts": mongo_saved.get("facts", []),
        "superseded_facts": mongo_saved.get("superseded_facts", []),
        "total_stored_entities": total_entities,
        "total_stored_facts": total_facts,
        "saved_to_mongodb": True,
        # Backward compatibility
        "memory": mongo_saved.get("entities", []),
        "claims": mongo_saved.get("facts", []),
        "superseded_claims": mongo_saved.get("superseded_facts", []),
        "total_stored_claims": total_facts,
    }


async def generate_grounded_answer(
    query: str,
    context_text: str,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    user_name: Optional[str] = None,
    responder_name: Optional[str] = "Tống Phước Hoài Nam",
    role: Optional[str] = "Project Lead",
    max_output_tokens: int = 4096,
) -> str:
    """Sinh câu trả lời Grounded QA dựa trên context hợp nhất (hỗ trợ đích danh user, max 4096 tokens)."""
    key = api_key or getattr(settings, "GEMINI_API_KEY", "") or getattr(settings, "gemini_api", "")
    if not key:
        logger.warning("Không tìm thấy GEMINI_API_KEY trong cấu hình. Bỏ qua LLM Grounded QA.")
        return ""

    if user_name:
        prompt = GROUNDED_QA_USER_PERSONA_PROMPT.format(
            context_text=context_text,
            query=query,
            user_name=user_name,
            responder_name=responder_name or "Tống Phước Hoài Nam",
            role=role or "Project Lead",
        )
    else:
        prompt = GROUNDED_QA_SYSTEM_PROMPT.format(
            context_text=context_text,
            query=query,
        )

    client = GeminiClient(api_key=key)
    try:
        ans = await client.generate_text_async(
            prompt=prompt,
            model_name=model_name,
            max_output_tokens=max_output_tokens,
        )
        return ans.strip()
    except Exception as e:
        logger.warning(f"Lỗi khi gọi Gemini generate_text_async: {e}")
        return ""


async def process_chat_pipeline(
    query: str,
    sender: str = "User",
    channel: str = "api",
    message_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    reply_to_lark: bool = False,
    retrieve_count: int = 5,
    user_name: Optional[str] = None,
    responder_name: Optional[str] = "Tống Phước Hoài Nam",
    role: Optional[str] = "Project Lead",
) -> Dict[str, Any]:
    """
    Quy trình xử lý hội thoại toàn diện (Unified Chat Pipeline):
      1. text_filter: Làm sạch ký tự lạ, validate độ dài tin nhắn.
      2. JEV Service: Phân loại định tuyến hành động (IGNORE, MEMORY_ONLY, REPLY_ONLY, MEMORY_AND_REPLY).
      3. Thực thi hành động:
         - IGNORE: Bỏ qua (tin nhắn rác, chào hỏi xã giao).
         - MEMORY_ONLY: Trích xuất thực thể & mệnh đề -> Lưu MongoDB + WeKnora KB (im lặng ghi nhớ).
         - REPLY_ONLY: Tra cứu WeKnora Chunks + MongoDB Claims -> ContextComposer -> Gemini Grounded QA -> Reply Lark.
         - MEMORY_AND_REPLY: Lưu trích xuất trước -> Tra cứu tổng hợp -> ContextComposer -> Gemini Grounded QA -> Reply Lark.
    """
    # ── Bước 1: Dọn dẹp ký tự và validate độ dài ──
    try:
        clean_query = text_filter.validate_and_clean(query)
    except ValueError as e:
        logger.warning(f"text_filter từ chối tin nhắn: {e} (nội dung: '{query}')")
        return {
            "status": "invalid_input",
            "jev_action": "IGNORE",
            "jev_confidence": 0.0,
            "query": query,
            "answer": None,
            "message": str(e),
        }

    # ── Tự động lưu Staging nếu có chat_id và message_id (Hỗ trợ Daily Digest) ──
    if chat_id and message_id:
        try:
            from services.digest_service import digest_service
            await digest_service.add_staging_message(
                message_id=message_id,
                chat_id=chat_id,
                text=clean_query,
                speaker_name=user_name or "Thành viên",
                speaker_id=sender or "",
                chat_name=chat_id,
            )
        except Exception as e:
            logger.warning(f"Lỗi khi lưu Staging từ process_chat_pipeline: {e}")

    # ── Bước 2: JEV Routing - Phân loại xem tin nhắn có đáng xử lý hay không ──
    try:
        jev_result = await jev_service.classify_message(clean_query)
        jev_action = jev_result.get("action", "IGNORE")
        jev_confidence = jev_result.get("confidence", 0.0)
    except Exception as e:
        logger.error(f"Lỗi phân loại JEV: {e}")
        # [SAFETY] Khi JEV API lỗi/timeout, TUYỆT ĐỐI không tự ý phát ngôn vào nhóm.
        # Chuyển sang DRAFT_PENDING_APPROVAL để người dùng tự quyết định câu trả lời.
        jev_action = "DRAFT_PENDING_APPROVAL" if ("?" in clean_query or len(clean_query.split()) >= 4) else "IGNORE"
        jev_confidence = 0.0

    # TH1: IGNORE - Tin rác, chào hỏi vô thưởng vô phạt
    if jev_action == "IGNORE":
        return {
            "status": "ignored",
            "jev_action": jev_action,
            "jev_confidence": jev_confidence,
            "query": clean_query,
            "answer": None,
            "message": "Tin nhắn rác hoặc tán gẫu không quan trọng. Không lưu, không trả lời.",
        }

    # Bước 3: Nếu JEV yêu cầu lưu bộ nhớ (MEMORY_ONLY hoặc MEMORY_AND_REPLY)
    extraction_data = None
    if jev_action in ("MEMORY_ONLY", "MEMORY_AND_REPLY"):
        extraction_data = await process_memory_extraction(
            query_text=clean_query,
            sender=sender,
        )
        try:
            await weknora_service.save_to_kb(clean_query)
        except Exception as e:
            logger.warning(f"Lỗi khi lưu vào WeKnora KB: {e}")

    # TH2: MEMORY_ONLY - Đã trích xuất xong, không cần tạo câu trả lời
    if jev_action == "MEMORY_ONLY":
        return {
            "status": "memorized",
            "jev_action": jev_action,
            "jev_confidence": jev_confidence,
            "query": clean_query,
            "extraction": extraction_data,
            "answer": None,
            "message": "Thông tin quan trọng đã được hệ thống trích xuất Thực thể & Mệnh đề thành công. Không cần phản hồi.",
        }

    # TH3 & TH4: REPLY_ONLY hoặc MEMORY_AND_REPLY - Cần tạo câu trả lời Grounded QA
    # 1. Lấy active claims từ MongoDB
    all_facts = []
    try:
        all_facts = await get_mongo_facts()
    except Exception as e:
        logger.warning(f"Lỗi khi đọc facts từ MongoDB: {e}")
    active_claims = [f for f in all_facts if f.get("status", "current") == "current"]

    # 2. Truy xuất các đoạn văn bản (chunks) từ WeKnora Knowledge Base theo phân quyền nhóm chat
    chunks = []
    try:
        from services.scope_service import scope_service
        target_kb = await scope_service.get_kb_for_chat(chat_id) if chat_id else None
        target_kbs = [target_kb] if target_kb else None
        chunks = await weknora_service.retrieve(
            query=clean_query,
            knowledge_base_ids=target_kbs,
            match_count=retrieve_count,
        )
    except Exception as e:
        logger.warning(f"Lỗi WeKnora retrieve: {e}")

    # [RAG GATE 2-TIER FILTERING] Kết hợp cả 2 tầng lọc thông minh:
    # --- TẦNG 1: Lọc thô nhanh theo Project / Entity Heuristics (0ms) ---
    if chunks and len(chunks) > 1:
        q_lower = clean_query.lower()
        if "hilark" in q_lower or "hi lark" in q_lower:
            filtered_coarse = [
                c for c in chunks
                if "kiaca" not in (c.get("knowledge_title") or c.get("document_name") or "").lower()
            ]
            if filtered_coarse:
                chunks = filtered_coarse

    # --- TẦNG 2: JEV Batch Relevance Gate (Lọc ngữ nghĩa thông minh ~300ms, 1 Call duy nhất) ---
    if chunks and len(chunks) > 1:
        try:
            chunks = await jev_service.filter_chunks_relevance(clean_query, chunks)
        except Exception as e:
            logger.warning(f"Lỗi khi lọc chunks qua JEV: {e}")

    # Chuẩn hóa chunks cho ContextComposer
    normalized_chunks = []
    for c in chunks:
        doc_name = (
            c.get("knowledge_title")
            or c.get("document_name")
            or "Tài liệu hệ thống"
        )
        normalized_chunks.append({
            "content": c.get("content", ""),
            "document_name": doc_name,
            "chunk_id": c.get("id") or c.get("chunk_id"),
            "score": c.get("score"),
        })

    # [SAFETY - RAG GATE] Nếu REPLY_ONLY nhưng không có chunks KB nào đủ cơ sở tri thức
    # -> Downgrade bắt buộc sang DRAFT_PENDING_APPROVAL để người dùng tự kiểm tra & duyệt
    # Đề bài: "Tự trả lời: Câu hỏi quy trình có SẴN câu trả lời chuẩn"
    # => Không có KB = không có câu trả lời chuẩn = không được tự ý phát ngôn
    if jev_action == "REPLY_ONLY" and not normalized_chunks and not active_claims:
        logger.warning(
            f"[RAG GATE] REPLY_ONLY nhưng KB rỗng (0 chunks, 0 claims) "
            f"-> Downgrade sang DRAFT_PENDING_APPROVAL. Query: '{clean_query}'"
        )
        jev_action = "DRAFT_PENDING_APPROVAL"

    # 3. Hợp nhất ngữ cảnh với ContextComposer
    composer = ContextComposer()
    composed = composer.compose(
        retriever_data=normalized_chunks if normalized_chunks else None,
        claims_data=active_claims if active_claims else None,
        query=clean_query,
        auto_align=True,
    )

    # 4. Sinh câu trả lời Grounded QA từ Gemini (có hỗ trợ xưng hô đích danh)
    answer = await generate_grounded_answer(
        query=clean_query,
        context_text=composed.get("context_text", ""),
        user_name=user_name,
        responder_name=responder_name,
        role=role,
    )

    # Fallback WeKnora chat nếu LLM answer trống
    if not answer:
        try:
            fallback = await weknora_service.get_chat_response(ChatRequest(query=clean_query))
            if isinstance(fallback, dict) and "answer" in fallback:
                answer = fallback["answer"]
        except Exception as e:
            logger.warning(f"Fallback WeKnora chat thất bại: {e}")

    # Làm sạch đầu ra
    answer = text_filter.clean_output(answer) if answer else "Hệ thống chưa tìm thấy thông tin phù hợp trong cơ sở tri thức để trả lời câu hỏi của bạn."

    # TH5: DRAFT_PENDING_APPROVAL - Soạn nháp chờ duyệt (Câu hỏi có dữ liệu nhưng có rủi ro)
    if jev_action == "DRAFT_PENDING_APPROVAL":
        # Bot KHÔNG gửi trả lời vào nhóm chat!
        # Bot gửi riêng 1-1 cho sếp (chủ nhân token) để sếp chọn: [Gửi / Sửa / Bỏ]
        dm_notice = None

        # 1. Lưu bản nháp vào DraftStore để phục vụ lệnh duyệt qua chat [Gửi / Sửa / Bỏ]
        owner_open_id = lark_service.known_user_open_id
        if lark_service._current_user_profile and lark_service._current_user_profile.get("open_id"):
            owner_open_id = lark_service._current_user_profile.get("open_id")

        draft_store.set_draft(
            owner_id=owner_open_id,
            draft=PendingDraft(
                message_id=message_id or "",
                chat_id=chat_id or "",
                query=clean_query,
                draft_answer=answer,
                user_name=user_name,
                responder_name=responder_name,
            ),
        )

        if reply_to_lark:
            draft_card_text = (
                "📝 [SOẠN NHÁP CHỜ DUYỆT - CÂU HỎI CÓ RỦI RO]\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Người hỏi : {user_name}\n"
                f"💬 Câu hỏi   : \"{clean_query}\"\n\n"
                f"💡 Bản nháp AI soạn sẵn:\n"
                f"\"{answer}\"\n\n"
                f"⚠️ Lý do: Câu hỏi có dữ liệu trong Knowledge Base nhưng thuộc nhóm rủi ro/nhạy cảm.\n"
                f"👉 Hành động chờ duyệt: Nhắn lại [Gửi] / [Sửa: <nội dung>] / [Bỏ]\n"
                f"🆔 Message ID gốc: {message_id or 'N/A'}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            try:
                dm_notice = await lark_service.send_bot_dm_to_owner(draft_card_text)
                logger.info(f"✔ Đã lưu vào DraftStore & gửi bản nháp chờ duyệt vào DM riêng của chủ nhân (Message ID: {message_id})")
            except Exception as e:
                logger.error(f"Lỗi gửi bản nháp cho chủ nhân: {e}")
                dm_notice = {"error": str(e)}

        return {
            "status": "draft_pending_approval",
            "jev_action": jev_action,
            "jev_confidence": jev_confidence,
            "query": clean_query,
            "draft_answer": answer,
            "answer": answer,
            "actions": ["Gửi", "Sửa", "Bỏ"],
            "user_name": user_name,
            "responder_name": responder_name,
            "extraction": extraction_data,
            "composed_context": composed,
            "lark_response": dm_notice,
            "message": "AI đã soạn câu trả lời nháp thành công. Đang chờ người dùng bấm Gửi / Sửa / Bỏ (Đã gửi vào DM riêng của bạn, chưa phát ngôn vào nhóm).",
        }

    # TH3 & TH4: REPLY_ONLY hoặc MEMORY_AND_REPLY - Gửi reply trực tiếp vào nhóm nhân danh User
    lark_reply_result = None
    if reply_to_lark and message_id:
        try:
            lark_reply_result = await lark_service.areply_text(
                message_id=message_id,
                text=answer,
                as_user=True,  # Trả lời nhân danh User (không có logo bot)
            )
        except Exception as e:
            logger.error(f"Lỗi khi gửi reply tới Lark: {e}")
            lark_reply_result = {"error": str(e), "success": False}

    return {
        "status": "auto_replied" if jev_action == "REPLY_ONLY" else "escalated_and_memorized",
        "jev_action": jev_action,
        "jev_confidence": jev_confidence,
        "query": clean_query,
        "answer": answer,
        "user_name": user_name,
        "responder_name": responder_name,
        "extraction": extraction_data,
        "composed_context": composed,
        "lark_response": lark_reply_result,
        "message": "Đã tạo câu trả lời tự động." if jev_action == "REPLY_ONLY" else "Đã trích xuất Thực thể & Mệnh đề vào bộ nhớ và tạo câu trả lời khẩn!",
    }


@router.post("")
async def chat(request: ChatRequest):
    result = await process_chat_pipeline(
        query=request.query,
        sender=request.sender_id or request.channel or "User",
        channel=request.channel,
        message_id=request.message_id,
        chat_id=request.chat_id,
        reply_to_lark=request.reply_to_lark,
        user_name=request.user_name,
        responder_name=request.responder_name or "Tống Phước Hoài Nam",
        role=request.role or "Project Lead",
    )

    if result.get("status") == "invalid_input":
        raise HTTPException(status_code=400, detail=result.get("message", "Tin nhắn không hợp lệ"))

    return result


@router.post("/user", summary="Chat trả lời dựa trên đích danh User")
async def chat_as_user(request: UserChatRequest):
    """
    Endpoint chat trả lời ĐÍCH DANH người dùng:
      - Xưng hô và chào hỏi đích danh người hỏi (user_name, VD: 'Hoài Phước').
      - Đóng vai là người trả lời (responder_name, mặc định: 'Tống Phước Hoài Nam').
      - Đi qua text_filter và JEV routing.
      - Hợp nhất tài liệu WeKnora và mệnh đề MongoDB Claims.
      - Tùy chọn gửi tin nhắn phản hồi về Lark qua message_id (reply_to_lark=True).
    """
    result = await process_chat_pipeline(
        query=request.query,
        sender=request.sender_id or request.user_name,
        channel=request.channel,
        message_id=request.message_id,
        chat_id=request.chat_id,
        reply_to_lark=request.reply_to_lark,
        retrieve_count=request.retrieve_count,
        user_name=request.user_name,
        responder_name=request.responder_name,
        role=request.role,
    )

    if result.get("status") == "invalid_input":
        raise HTTPException(status_code=400, detail=result.get("message", "Tin nhắn không hợp lệ"))

    return result



@router.post("/memory")
async def add_memory(request: MemoryRequest):
    """
    Endpoint chủ động lưu thông tin vào Knowledge Base và trích xuất Entities & Facts vào MongoDB.
    """
    try:
        try:
            existing_entities = await get_mongo_entities()
            existing_facts = await get_mongo_facts()
        except Exception as e:
            logger.warning(f"Lỗi đọc MongoDB: {e}")
            existing_entities = []
            existing_facts = []

        msg_id = f"msg_{uuid.uuid4().hex[:8]}"

        extraction_result = await extract_async(
            query=request.text,
            workspace_id="default",
            source_message_id=msg_id,
            sender="API",
            existing_entities=existing_entities,
            existing_facts=existing_facts,
        )

        mongo_saved = await save_extraction_to_mongo(extraction_result)

        weknora_result = None
        try:
            weknora_result = await weknora_service.save_to_kb(request.text)
        except Exception as e:
            logger.warning(f"Lỗi khi lưu vào KB: {e}")

        return {
            "status": "success",
            "message": "Đã trích xuất và lưu vào Knowledge Base & MongoDB",
            "extraction": mongo_saved,
            "saved_to_mongodb": True,
            "weknora_data": weknora_result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory/store")
async def get_memory_store():
    """Xem toàn bộ các thực thể (entities) và sự thật (facts) từ MongoDB."""
    entities = await get_mongo_entities()
    facts = await get_mongo_facts()

    return {
        "storage_source": "mongodb",
        "total_entities": len(entities),
        "total_facts": len(facts),
        "entities": entities,
        "facts": facts,
        # Backward compatibility
        "total_claims": len(facts),
        "claims": facts,
    }


@router.delete("/memory/store")
async def reset_memory_store():
    """Xóa sạch toàn bộ kho thực thể và facts trên MongoDB."""
    try:
        await clear_mongo_stores()
    except Exception as e:
        logger.error(f"Lỗi khi xóa MongoDB: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "success", "message": "Đã xóa sạch bộ nhớ entities và facts trên MongoDB!"}


@router.get("/mongodb/status")
async def get_mongodb_status():
    """Kiểm tra trạng thái kết nối tới MongoDB."""
    return await check_mongo_connection()


@router.post("/approve-draft")
async def approve_draft(request: ApproveDraftRequest):
    """
    Endpoint cho phép người dùng/sếp bấm Gửi / Sửa / Bỏ đối với bản nháp:
      - 'send': Gửi nguyên bản nháp vào nhóm nhân danh User.
      - 'edit': Gửi nội dung đã chỉnh sửa vào nhóm nhân danh User.
      - 'discard': Hủy bỏ bản nháp, không gửi vào nhóm.
    """
    if request.action == "discard":
        logger.info(f"Người dùng đã BỎ bản nháp cho message_id={request.message_id}")
        return {
            "status": "discarded",
            "message_id": request.message_id,
            "message": "Đã hủy bỏ bản nháp thành công. Không có tin nhắn nào được gửi vào nhóm.",
        }

    if request.action in ("send", "edit"):
        if not request.content:
            raise HTTPException(status_code=400, detail="Cần cung cấp 'content' để gửi vào nhóm")

        clean_text = text_filter.clean_output(request.content)
        try:
            resp = await lark_service.areply_text(
                message_id=request.message_id,
                text=clean_text,
                as_user=True,  # 100% danh tính User
            )
            return {
                "status": "sent" if request.action == "send" else "edited_and_sent",
                "message_id": request.message_id,
                "sent_content": clean_text,
                "lark_response": resp,
                "message": "Đã duyệt và gửi tin nhắn vào nhóm thành công dưới danh tính của bạn!",
            }
        except Exception as e:
            logger.error(f"Lỗi khi gửi duyệt bản nháp: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=400, detail="Hành động không hợp lệ. Chọn 'send', 'edit', hoặc 'discard'.")




