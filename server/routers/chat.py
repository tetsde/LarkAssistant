import logging
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from core.config import settings
from models import ChatRequest, MemoryRequest, UserChatRequest
from services.weknora import WeKnoraService, weknora_service
from services.jev import jev_service
from services.lark import lark_service
from utils.text_filter import text_filter
from utils.context_composer import ContextComposer
from utils.llm_extractor import (
    extract_async,
    load_stored_entities,
    load_stored_facts,
    load_stored_claims,
    apply_and_save_extraction,
    clear_stores,
    GeminiClient,
)
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
4. PHONG CÁCH TRÌNH BÀY:
   - Trả lời bằng tiếng Việt chuyên nghiệp, súc tích, dễ đọc. Sử dụng bullet points hoặc bảng tóm tắt khi trình bày nhiều mục thông tin.
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
4. NGẮN GỌN, DỄ ĐỌC:
   - Trả lời bằng tiếng Việt gãy gọn, đúng trọng tâm câu hỏi.
"""


async def process_memory_extraction(query_text: str, sender: str = "User") -> Dict[str, Any]:
    """Helper xử lý trích xuất Entities & Facts khi JEV yêu cầu ghi nhớ."""
    msg_id = f"msg_{uuid.uuid4().hex[:8]}"

    try:
        existing_entities = await get_mongo_entities()
        existing_facts = await get_mongo_facts()
        if not existing_entities:
            existing_entities = load_stored_entities()
        if not existing_facts:
            existing_facts = load_stored_facts()
    except Exception:
        existing_entities = load_stored_entities()
        existing_facts = load_stored_facts()

    extraction_result = await extract_async(
        query=query_text,
        workspace_id="default",
        source_message_id=msg_id,
        sender=sender,
        existing_entities=existing_entities,
        existing_facts=existing_facts,
    )

    # Lưu vào JSON file trước để đảm bảo sạch dữ liệu
    saved = apply_and_save_extraction(extraction_result)

    mongo_saved = None
    try:
        mongo_saved = await save_extraction_to_mongo(extraction_result)
    except Exception as e:
        logger.error(f"Lỗi khi lưu vào MongoDB: {e}")

    total_entities = mongo_saved.get("total_stored_entities", saved.get("total_stored_entities", 0)) if mongo_saved else saved.get("total_stored_entities", 0)
    total_facts = mongo_saved.get("total_stored_facts", saved.get("total_stored_facts", 0)) if mongo_saved else saved.get("total_stored_facts", 0)

    return {
        "message_id": msg_id,
        "entities": saved.get("entities", []),
        "facts": saved.get("facts", []),
        "superseded_facts": saved.get("superseded_facts", []),
        "total_stored_entities": total_entities,
        "total_stored_facts": total_facts,
        "saved_to_mongodb": bool(mongo_saved),
        # Backward compatibility
        "memory": saved.get("memory", []),
        "claims": saved.get("claims", []),
        "superseded_claims": saved.get("superseded_claims", []),
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
) -> str:
    """Sinh câu trả lời Grounded QA dựa trên context hợp nhất (hỗ trợ đích danh user)."""
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
        ans = await client.generate_text_async(prompt=prompt, model_name=model_name)
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

    # ── Bước 2: JEV Routing - Phân loại xem tin nhắn có đáng xử lý hay không ──
    try:
        jev_result = await jev_service.classify_message(clean_query)
        jev_action = jev_result.get("action", "IGNORE")
        jev_confidence = jev_result.get("confidence", 0.0)
    except Exception as e:
        logger.error(f"Lỗi phân loại JEV: {e}")
        jev_action = "REPLY_ONLY" if ("?" in clean_query or len(clean_query.split()) >= 4) else "IGNORE"
        jev_confidence = 0.5

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
    if not all_facts:
        all_facts = load_stored_facts()
    active_claims = [f for f in all_facts if f.get("status", "current") == "current"]

    # 2. Truy xuất các đoạn văn bản (chunks) từ WeKnora Knowledge Base
    chunks = []
    try:
        chunks = await weknora_service.retrieve(query=clean_query, match_count=retrieve_count)
    except Exception as e:
        logger.warning(f"Lỗi WeKnora retrieve: {e}")

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

    # 5. Gửi reply về Lark nếu có yêu cầu (nhân danh User)
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
    Endpoint chủ động lưu thông tin vào Knowledge Base và trích xuất Entities & Facts.
    """
    try:
        try:
            existing_entities = await get_mongo_entities()
            existing_facts = await get_mongo_facts()
            if not existing_entities:
                existing_entities = load_stored_entities()
            if not existing_facts:
                existing_facts = load_stored_facts()
        except Exception:
            existing_entities = load_stored_entities()
            existing_facts = load_stored_facts()

        msg_id = f"msg_{uuid.uuid4().hex[:8]}"

        extraction_result = await extract_async(
            query=request.text,
            workspace_id="default",
            source_message_id=msg_id,
            sender="API",
            existing_entities=existing_entities,
            existing_facts=existing_facts,
        )

        mongo_saved = None
        try:
            mongo_saved = await save_extraction_to_mongo(extraction_result)
        except Exception as e:
            print(f"Lỗi khi lưu vào MongoDB: {e}")

        saved = apply_and_save_extraction(extraction_result)

        weknora_result = None
        try:
            weknora_result = await weknora_service.save_to_kb(request.text)
        except Exception as e:
            print(f"Lỗi khi lưu vào KB: {e}")

        return {
            "status": "success",
            "message": "Đã trích xuất và lưu vào Knowledge Base & MongoDB",
            "extraction": saved,
            "saved_to_mongodb": bool(mongo_saved),
            "weknora_data": weknora_result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory/store")
async def get_memory_store():
    """Xem toàn bộ các thực thể (entities) và sự thật (facts) đang được lưu trữ."""
    mongo_entities = []
    mongo_facts = []
    try:
        mongo_entities = await get_mongo_entities()
        mongo_facts = await get_mongo_facts()
    except Exception as e:
        print(f"Lỗi khi đọc từ MongoDB: {e}")

    entities = mongo_entities if mongo_entities else load_stored_entities()
    facts = mongo_facts if mongo_facts else load_stored_facts()

    return {
        "storage_source": "mongodb" if (mongo_entities or mongo_facts) else "json_file",
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
    """Xóa sạch toàn bộ kho thực thể và facts (cả MongoDB và file)."""
    try:
        await clear_mongo_stores()
    except Exception as e:
        print(f"Lỗi khi xóa MongoDB: {e}")
    clear_stores()
    return {"status": "success", "message": "Đã xóa sạch bộ nhớ entities và facts (MongoDB & JSON File)!"}


@router.get("/mongodb/status")
async def get_mongodb_status():
    """Kiểm tra trạng thái kết nối tới MongoDB."""
    return await check_mongo_connection()



