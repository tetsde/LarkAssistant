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
                        "GHI NHỚ (lưu trữ) hay không, và có cần phải TRẢ LỜI ngay lập tức hay SOẠN NHÁP CHỜ DUYỆT hay không. "
                        "Hãy chọn 1 trong 5 nhãn phân loại phù hợp nhất bên dưới."
                    ),
                    "criteria": {
                        "IGNORE": "Tin nhắn rác, chào hỏi vô thưởng vô phạt, tán gẫu, không chứa thông tin quan trọng. (Không cần ghi nhớ, Không cần trả lời)",
                        "MEMORY_ONLY": "Tin nhắn mang tính chất báo cáo, cập nhật tiến độ hoặc tài liệu tham khảo cần lưu vào bộ nhớ để tra cứu, nhưng không ai hỏi. (Cần ghi nhớ, Không cần trả lời)",
                        "REPLY_ONLY": "Tin nhắn hỏi đáp thông tin thông thường về dự án, tiến độ, thành viên team, phân công công việc, quy trình, kiến trúc kỹ thuật hoặc tài liệu hệ thống đã có sẵn trong Knowledge Base. Cần AI tự động tra cứu tri thức và trả lời ngay vào nhóm.",
                        "MEMORY_AND_REPLY": "Tin nhắn sự cố khẩn cấp, thay đổi quan trọng kèm câu hỏi cần phản hồi ngay. (Cần ghi nhớ, Cần trả lời)",
                        "DRAFT_PENDING_APPROVAL": "CHỈ áp dụng cho các câu hỏi ĐẶC BIỆT NHẠY CẢM MẬT (như bảng lương cá nhân nhân viên, bí mật tài chính kế toán riêng tư, thỏa thuận hợp đồng bảo mật, tranh chấp pháp lý nghiêm trọng). Còn các câu hỏi tiến độ, thành viên, thông tin dự án chung thì KHÔNG chọn nhãn này."
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

                # --- BỘ LỌC ĐỘ TỰ TIN (ĐÃ TỐI ƯU CÂN BẰNG PHẢN HỒI MƯỢT MÀ & AN TOÀN) ---
                prob_draft_risk = probabilities.get("DRAFT_PENDING_APPROVAL", 0.0)
                prob_reply = probabilities.get("REPLY_ONLY", 0.0)

                if choice == "MEMORY_AND_REPLY":
                    if prob_choice >= 0.70:
                        return {"action": "MEMORY_AND_REPLY", "confidence": prob_choice}
                    else:
                        # Hạ cấp xuống chỉ ghi nhớ nếu độ tự tin trả lời chưa đủ cao
                        return {"action": "MEMORY_ONLY", "confidence": prob_choice}

                elif choice == "MEMORY_ONLY":
                    if prob_choice >= 0.50:
                        return {"action": "MEMORY_ONLY", "confidence": prob_choice}
                    else:
                        return {"action": "IGNORE", "confidence": prob_choice}

                elif choice == "REPLY_ONLY":
                    # Ưu tiên tự trả lời các câu hỏi cơ bản, chỉ chặn sang DRAFT khi rủi ro thực sự áp đảo
                    if prob_draft_risk >= 0.65 and prob_draft_risk > prob_choice:
                        return {"action": "DRAFT_PENDING_APPROVAL", "confidence": prob_draft_risk}
                    elif prob_choice >= 0.35:
                        return {"action": "REPLY_ONLY", "confidence": prob_choice}
                    else:
                        return {"action": "DRAFT_PENDING_APPROVAL", "confidence": prob_choice}

                elif choice == "DRAFT_PENDING_APPROVAL":
                    # Nếu JEV chọn DRAFT nhưng xác suất thấp (< 0.60) và REPLY_ONLY cũng cao -> Ưu tiên tự trả lời
                    if prob_choice < 0.60 and prob_reply >= 0.30:
                        return {"action": "REPLY_ONLY", "confidence": prob_reply}
                    return {"action": "DRAFT_PENDING_APPROVAL", "confidence": prob_choice}

                else:  # choice == "IGNORE"
                    return {"action": "IGNORE", "confidence": prob_choice}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"JEV Classification Failed: {str(e)}")

    async def filter_chunks_relevance(
        self,
        query: str,
        chunks: list,
        max_snippet_chars: int = 300,
        timeout: float = 10.0,
    ) -> list:
        """
        [RAG Gate Tier 2] Lọc mức độ liên quan ngữ nghĩa của các Chunks bằng JEV:
          - Gửi 1 API batch duy nhất gồm nhiều câu hỏi (mỗi chunk là 1 question trong payload).
          - Tránh quá tải token bằng cách chỉ gửi tiêu đề tài liệu + snippet ngắn (~300 ký tự).
          - Giữ lại các chunks có nhãn RELEVANT (loại bỏ hoàn toàn tài liệu rác, lạc đề).
          - Graceful Fallback: Nếu JEV lỗi, timeout hoặc lọc rỗng, giữ lại chunks ban đầu để không crash RAG.
        """
        if not chunks or len(chunks) <= 1:
            return chunks

        if not self.api_key:
            return chunks

        # Chuẩn bị questions cho tối đa 5 chunks hàng đầu
        candidate_chunks = chunks[:5]
        questions = {}

        for idx, c in enumerate(candidate_chunks, 1):
            doc_title = (
                c.get("knowledge_title")
                or c.get("document_name")
                or c.get("title")
                or f"Tài liệu {idx}"
            )
            raw_content = c.get("matched_content") or c.get("content") or ""
            snippet = raw_content[:max_snippet_chars].strip().replace("\n", " ")
            questions[f"chunk_{idx}"] = {
                "type": "choice",
                "instructions": (
                    f"Đoạn trích {idx} từ tài liệu '{doc_title}': \"{snippet}...\". "
                    f"Đoạn trích này có thuộc bối cảnh dự án phù hợp để tham khảo cho câu hỏi của người dùng không?"
                ),
                "criteria": {
                    "RELEVANT": "Tài liệu hoặc bối cảnh liên quan đến dự án đang hỗ trợ (HiLark Assistant)",
                    "IRRELEVANT": "Tài liệu thuộc dự án khác (như Kiaca...) hoặc tài liệu mẫu không liên quan"
                }
            }

        payload = {
            "state": (
                f"Bối cảnh: Trợ lý AI đang hỗ trợ giải đáp cho dự án HiLark Assistant.\n"
                f"Câu hỏi của người dùng: \"{query.strip()}\""
            ),
            "model": "jev-latest",
            "questions": questions,
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(self.url, headers=self.headers, json=payload)
                if resp.status_code != 200:
                    return chunks

                data = resp.json()
                answers = data.get("answers", {})

                relevant_chunks = []
                for idx, c in enumerate(candidate_chunks, 1):
                    ans = answers.get(f"chunk_{idx}")
                    if isinstance(ans, dict):
                        choice = ans.get("choice", "")
                        probs = ans.get("probabilities", {})
                        rel_score = float(probs.get("RELEVANT", 0.0))
                        c["jev_score"] = rel_score
                        is_relevant = (choice == "RELEVANT") or (rel_score >= 0.5)
                        if is_relevant:
                            relevant_chunks.append(c)

                # [RERANK] Tái sắp xếp các chunk giữ lại theo điểm JEV giảm dần (chunk sát nhất lên đầu)
                if relevant_chunks:
                    relevant_chunks.sort(key=lambda x: x.get("jev_score", 0.0), reverse=True)
                    return relevant_chunks

                # An toàn: nếu JEV lọc quá tay làm mất hết chunks, fallback giữ lại chunks ban đầu
                return chunks
        except Exception:
            return chunks


jev_service = JevService()

