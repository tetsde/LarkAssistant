from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from models.chat import ChatRequest
from services.weknora import WeKnoraService
from services.jev import jev_service
from utils.text_filter import text_filter

from utils.memory import save_memory

router = APIRouter(prefix="/api/chat", tags=["chat"])
weknora_service = WeKnoraService()

@router.post("")
async def chat(request: ChatRequest):
    # Bước 1: Lọc rác và validate input (chặn query tán gẫu/spam)
    try:
        request.query = text_filter.validate_and_clean(request.query)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Bước 2: JEV Routing - Phân loại xem tin nhắn có đáng xử lý hay không
    jev_result = await jev_service.classify_message(request.query)
    jev_action = jev_result["action"]
    jev_confidence = jev_result["confidence"]

    # Xử lý theo quyết định của JEV
    if jev_action == "IGNORE":
        return {
            "status": "ignored",
            "jev_action": jev_action,
            "message": "Tin nhắn rác hoặc không quan trọng. Không lưu, không trả lời."
        }
        
    if jev_action == "MEMORY_ONLY":
        claim_id = save_memory(request.query, jev_action, jev_confidence, sender=request.channel)
        try:
            await weknora_service.save_to_kb(request.query)
        except Exception as e:
            print(f"Lỗi khi lưu vào KB: {e}")
            
        return {
            "status": "memorized",
            "jev_action": jev_action,
            "claim_id": claim_id,
            "message": "Thông tin quan trọng đã được hệ thống ghi nhớ âm thầm. Không cần phản hồi."
        }

    # Đối với REPLY_ONLY và MEMORY_AND_REPLY, ta cần gọi qua WeKnora để tạo câu trả lời
    response_data = await weknora_service.get_chat_response(request)
    
    claim_id = None
    if jev_action == "MEMORY_AND_REPLY":
        claim_id = save_memory(request.query, jev_action, jev_confidence, sender=request.channel)
        try:
            await weknora_service.save_to_kb(request.query)
        except Exception as e:
            print(f"Lỗi khi lưu vào KB: {e}")

    
    return {
        "status": "auto_replied" if jev_action == "REPLY_ONLY" else "escalated_and_memorized",
        "jev_action": jev_action,
        "claim_id": claim_id,
        "weknora_response": response_data,
        "message": "Đã tạo câu trả lời tự động." if jev_action == "REPLY_ONLY" else "Đã ghi nhớ vào DB và trả lời khẩn!"
    }

class MemoryRequest(BaseModel):
    text: str

@router.post("/memory")
async def add_memory(request: MemoryRequest):
    """
    Endpoint riêng biệt để chủ động lưu thông tin vào Knowledge Base.
    """
    try:
        result = await weknora_service.save_to_kb(request.text)
        return {
            "status": "success",
            "message": "Đã lưu vào Knowledge Base",
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

