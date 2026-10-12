import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from models import ChatRequest, MemoryRequest
from services.weknora import WeKnoraService
from services.jev import jev_service
from utils.text_filter import text_filter
from utils.llm_extractor import (
    extract_async,
    load_stored_entities,
    load_stored_facts,
    load_stored_claims,
    apply_and_save_extraction,
    clear_stores,
)
from database import (
    check_mongo_connection,
    get_all_entities as get_mongo_entities,
    get_all_facts as get_mongo_facts,
    save_extraction_to_mongo,
    clear_mongo_stores,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])
weknora_service = WeKnoraService()


@router.post("")
async def chat(request: ChatRequest):
    # Bước 1: Dọn dẹp ký tự và validate độ dài (không chặn theo từ khóa)
    try:
        request.query = text_filter.validate_and_clean(request.query)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Bước 2: JEV Routing - Phân loại xem tin nhắn có đáng xử lý hay không
    jev_result = await jev_service.classify_message(request.query)
    jev_action = jev_result["action"]
    jev_confidence = jev_result["confidence"]

    # TH1: IGNORE - Tin rác, chào hỏi vô thưởng vô phạt
    if jev_action == "IGNORE":
        return {
            "status": "ignored",
            "jev_action": jev_action,
            "jev_confidence": jev_confidence,
            "message": "Tin nhắn rác hoặc tán gẫu không quan trọng. Không lưu, không trả lời."
        }

    # Helper xử lý trích xuất Entities & Facts khi JEV yêu cầu ghi nhớ
    async def process_memory_extraction(query_text: str, sender: str) -> Dict[str, Any]:
        msg_id = f"msg_{uuid.uuid4().hex[:8]}"
        
        # Ưu tiên lấy từ MongoDB nếu có, fallback sang file JSON
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

        # Dual-save: Lưu cả MongoDB và file JSON
        mongo_saved = None
        try:
            mongo_saved = await save_extraction_to_mongo(extraction_result)
        except Exception as e:
            print(f"Lỗi khi lưu vào MongoDB: {e}")

        saved = apply_and_save_extraction(extraction_result)

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

    # Bước 3: Nếu JEV yêu cầu lưu bộ nhớ (MEMORY_ONLY hoặc MEMORY_AND_REPLY) -> Chạy Utils Extractor ĐẦU TIÊN
    extraction_data = None
    if jev_action in ("MEMORY_ONLY", "MEMORY_AND_REPLY"):
        extraction_data = await process_memory_extraction(
            query_text=request.query,
            sender=request.channel or "User",
        )
        try:
            await weknora_service.save_to_kb(request.query)
        except Exception as e:
            print(f"Lỗi khi lưu vào WeKnora KB: {e}")

    # TH2: MEMORY_ONLY - Đã trích xuất xong, không cần tạo câu trả lời
    if jev_action == "MEMORY_ONLY":
        return {
            "status": "memorized",
            "jev_action": jev_action,
            "jev_confidence": jev_confidence,
            "extraction": extraction_data,
            "message": "Thông tin quan trọng đã được hệ thống trích xuất Thực thể & Mệnh đề thành công. Không cần phản hồi."
        }

    # TH3: REPLY_ONLY hoặc MEMORY_AND_REPLY - Cần gọi WeKnora tạo câu trả lời
    response_data = await weknora_service.get_chat_response(request)
    if isinstance(response_data, dict) and "answer" in response_data:
        response_data["answer"] = text_filter.clean_output(response_data["answer"])

    return {
        "status": "auto_replied" if jev_action == "REPLY_ONLY" else "escalated_and_memorized",
        "jev_action": jev_action,
        "jev_confidence": jev_confidence,
        "extraction": extraction_data,
        "weknora_response": response_data,
        "message": "Đã tạo câu trả lời tự động." if jev_action == "REPLY_ONLY" else "Đã trích xuất Thực thể & Mệnh đề vào bộ nhớ và tạo câu trả lời khẩn!"
    }


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



