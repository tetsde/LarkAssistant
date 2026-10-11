import httpx
from fastapi import HTTPException
from core.config import settings

class JevService:
    def __init__(self):
        self.api_key = settings.JEV_API_KEY
        self.url = "https://api.typesafe.ai/v1/systemone"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def classify_message(self, message: str) -> dict:
        if not self.api_key:
            raise HTTPException(status_code=500, detail="Missing JEV API Key (jev_api) in .env")

        payload = {
            "state": message,
            "model": "jev-latest",
            "questions": {
                "message_action": {
                    "type": "choice",
                    "instructions": (
                        "Bạn là trợ lý AI (Gatekeeper) nghiêm khắc, lọc tin nhắn cho một vị "
                        "Giám đốc rất bận rộn. Bạn cần phân tích xem tin nhắn có chứa thông tin đáng để "
                        "GHI NHỚ (lưu trữ) hay không, và có cần phải TRẢ LỜI ngay lập tức hay không. "
                        "Hãy chọn 1 trong 4 nhãn phân loại phù hợp nhất bên dưới."
                    ),
                    "criteria": {
                        "IGNORE": "Tin nhắn rác, chào hỏi vô thưởng vô phạt, tán gẫu, không chứa thông tin quan trọng. (Không cần ghi nhớ, Không cần trả lời)",
                        "MEMORY_ONLY": "Tin nhắn mang tính chất báo cáo, thông báo tiến độ, tài liệu tham khảo. Cần lưu vào bộ nhớ để sau này tra cứu, nhưng không cần trả lời. (Cần ghi nhớ, Không cần trả lời)",
                        "REPLY_ONLY": "Tin nhắn hỏi đáp thông tin cơ bản, hỏi quy trình, cần cung cấp câu trả lời nhưng thông tin đó không mang giá trị lưu trữ lâu dài. (Không cần ghi nhớ, Cần trả lời)",
                        "MEMORY_AND_REPLY": "Tin nhắn cực kỳ quan trọng, sự cố khẩn cấp, xin ý kiến chốt deal, quyết định kinh doanh. Vừa cần lưu lại bằng chứng/quyết định, vừa cần sếp hoặc BOT trả lời ngay. (Cần ghi nhớ, Cần trả lời)"
                    }
                }
            }
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.url, headers=self.headers, json=payload, timeout=30.0)
                response.raise_for_status()
                data = response.json()
                
                # Trích xuất kết quả phân loại từ JEV (thường nằm ở data.answers.message_action)
                action_data = data.get("answers", {}).get("message_action")
                
                if not action_data:
                    return {"action": "IGNORE", "confidence": 0.0} 
                
                # Nếu API trả về chuỗi trực tiếp (fallback)
                if isinstance(action_data, str):
                    return {"action": action_data, "confidence": 0.0}
                    
                # Schema dạng dictionary của JEV
                choice = action_data.get("choice", "IGNORE")
                confidence = action_data.get("confidence", 0.0)
                probabilities = action_data.get("probabilities", {})
                prob_choice = probabilities.get(choice, 0.0)

                # --- BỘ LỌC ĐỘ TỰ TIN (FLEXIBLE THRESHOLDS VỚI NHÃN MỚI) ---
                if choice == "MEMORY_AND_REPLY":
                    if prob_choice > 0.95:
                        return {"action": "MEMORY_AND_REPLY", "confidence": prob_choice}
                    else:
                        # Không đủ > 0.95 thì hạ cấp xuống chỉ ghi nhớ thôi, khỏi rep
                        return {"action": "MEMORY_ONLY", "confidence": prob_choice}
                        
                elif choice == "MEMORY_ONLY":
                    if prob_choice > 0.7:
                        return {"action": "MEMORY_ONLY", "confidence": prob_choice}
                    else:
                        # Nhớ mà không chắc thì thôi dẹp luôn
                        return {"action": "IGNORE", "confidence": prob_choice}
                        
                elif choice == "REPLY_ONLY":
                    if prob_choice > 0.6:
                        return {"action": "REPLY_ONLY", "confidence": prob_choice}
                    else:
                        # Câu hỏi không rõ ràng, vứt
                        return {"action": "IGNORE", "confidence": prob_choice}
                        
                else: # choice == "IGNORE"
                    return {"action": "IGNORE", "confidence": prob_choice}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"JEV Classification Failed: {str(e)}")

jev_service = JevService()
