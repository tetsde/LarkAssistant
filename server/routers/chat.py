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
    load_stored_claims,
    apply_and_save_extraction,
    clear_stores,
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

    # Helper xử lý trích xuất Memory & Claims khi JEV yêu cầu ghi nhớ
    async def process_memory_extraction(query_text: str, sender: str) -> Dict[str, Any]:
        msg_id = f"msg_{uuid.uuid4().hex[:8]}"
        existing_entities = load_stored_entities()
        existing_claims = load_stored_claims()

        extraction_result = await extract_async(
            query=query_text,
            workspace_id="default",
            source_message_id=msg_id,
            sender=sender,
            existing_entities=existing_entities,
            existing_claims=existing_claims,
        )
        saved = apply_and_save_extraction(extraction_result)
        return {
            "message_id": msg_id,
            "memory": saved.get("memory", []),
            "claims": saved.get("claims", []),
            "superseded_claims": saved.get("superseded_claims", []),
            "total_stored_entities": saved.get("total_stored_entities", 0),
            "total_stored_claims": saved.get("total_stored_claims", 0),
        }

    # TH2: MEMORY_ONLY - Chỉ ghi nhớ tri thức vào Memory & Claims (không trả lời)
    if jev_action == "MEMORY_ONLY":
        extraction_data = await process_memory_extraction(
            query_text=request.query,
            sender=request.channel or "User",
        )

        try:
            await weknora_service.save_to_kb(request.query)
        except Exception as e:
            print(f"Lỗi khi lưu vào WeKnora KB: {e}")

        return {
            "status": "memorized",
            "jev_action": jev_action,
            "jev_confidence": jev_confidence,
            "extraction": extraction_data,
            "message": "Thông tin quan trọng đã được hệ thống trích xuất Thực thể & Mệnh đề thành công. Không cần phản hồi."
        }

    # TH3: REPLY_ONLY hoặc MEMORY_AND_REPLY - Cần gọi WeKnora tạo câu trả lời
    response_data = await weknora_service.get_chat_response(request)

    extraction_data = None
    if jev_action == "MEMORY_AND_REPLY":
        extraction_data = await process_memory_extraction(
            query_text=request.query,
            sender=request.channel or "User",
        )
        try:
            await weknora_service.save_to_kb(request.query)
        except Exception as e:
            print(f"Lỗi khi lưu vào WeKnora KB: {e}")

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
    Endpoint chủ động lưu thông tin vào Knowledge Base và trích xuất Memory & Claims.
    """
    try:
        existing_entities = load_stored_entities()
        existing_claims = load_stored_claims()
        msg_id = f"msg_{uuid.uuid4().hex[:8]}"

        extraction_result = await extract_async(
            query=request.text,
            workspace_id="default",
            source_message_id=msg_id,
            sender="API",
            existing_entities=existing_entities,
            existing_claims=existing_claims,
        )
        saved = apply_and_save_extraction(extraction_result)

        weknora_result = None
        try:
            weknora_result = await weknora_service.save_to_kb(request.text)
        except Exception as e:
            print(f"Lỗi khi lưu vào KB: {e}")

        return {
            "status": "success",
            "message": "Đã trích xuất và lưu vào Knowledge Base",
            "extraction": saved,
            "weknora_data": weknora_result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory/store")
async def get_memory_store():
    """Xem toàn bộ các thực thể (entities) và mệnh đề (claims) đang được lưu trữ."""
    entities = load_stored_entities()
    claims = load_stored_claims()
    return {
        "total_entities": len(entities),
        "total_claims": len(claims),
        "entities": entities,
        "claims": claims,
    }


@router.delete("/memory/store")
async def reset_memory_store():
    """Xóa sạch toàn bộ kho thực thể và mệnh đề."""
    clear_stores()
    return {"status": "success", "message": "Đã xóa sạch bộ nhớ entities và claims!"}


