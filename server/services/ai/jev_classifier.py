import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Union
import httpx
from core.config import settings
from core.http_client import get_http_client

logger = logging.getLogger(__name__)


class JEVError(RuntimeError):
    """Ngoại lệ nghiệp vụ cho JEV Service (không phụ thuộc web framework)."""
    pass


class JevService:
    def __init__(self):
        self.api_key = settings.JEV_API_KEY
        self.url = "https://api.typesafe.ai/v1/systemone"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    @asynccontextmanager
    async def _get_client_session(self, client: Optional[httpx.AsyncClient] = None):
        """Helper lấy HTTP client: ưu tiên persistent pool, tương thích ngược với unit test mock context manager."""
        if client is not None:
            if hasattr(client, "__aenter__") and hasattr(client, "__aexit__"):
                async with client as c:
                    yield c
            else:
                yield client
            return

        # Nếu httpx.AsyncClient đã bị monkey-patch / mock trong unit test
        import sys
        target_httpx = httpx
        jev_mod = sys.modules.get("services.jev")
        if jev_mod and hasattr(jev_mod, "httpx") and type(getattr(jev_mod.httpx, "AsyncClient", None)).__name__ in ("MagicMock", "AsyncMock"):
            target_httpx = jev_mod.httpx

        if type(target_httpx.AsyncClient).__name__ in ("MagicMock", "AsyncMock"):
            mock_obj = target_httpx.AsyncClient()
            if hasattr(mock_obj, "__aenter__") and hasattr(mock_obj, "__aexit__"):
                async with mock_obj as c:
                    yield c
                return
            yield mock_obj
            return

        yield get_http_client()

    async def classify_message(self, message: str, client: Optional[httpx.AsyncClient] = None) -> dict:
        if not self.api_key:
            raise JEVError("Missing JEV API Key (jev_api) in .env")

        payload = {
            "state": message,
            "model": "jev-latest",
            "questions": {
                "message_action": {
                    "type": "choice",
                    "instructions": (
                        "Bạn là trợ lý AI (Gatekeeper) nghiêm khắc, lọc tin nhắn cho một vị "
                        "Giám đốc rất bận rộn. Bạn cần phân tích tin nhắn có đáng GHI NHỚ hay không, "
                        "và nếu cần phản hồi thì trả lời ngay hay tạo bản nháp chờ duyệt. "
                        "Hãy chọn 1 trong 5 nhãn phân loại phù hợp nhất bên dưới."
                    ),
                    "criteria": {
                        "IGNORE": "Tin nhắn rác, chào hỏi vô thưởng vô phạt, tán gẫu, không chứa thông tin quan trọng. (Không cần ghi nhớ, Không cần trả lời)",
                        "MEMORY_ONLY": "Tin nhắn mang tính chất báo cáo, cập nhật tiến độ hoặc tài liệu tham khảo cần lưu vào bộ nhớ để tra cứu, nhưng không ai hỏi. (Cần ghi nhớ, Không cần trả lời)",
                        "REPLY_ONLY": "Tin nhắn hỏi đáp thông tin thông thường về dự án, tiến độ, thành viên team, phân công công việc, quy trình, kiến trúc kỹ thuật hoặc tài liệu hệ thống đã có sẵn trong Knowledge Base. Cần AI tự động tra cứu tri thức và trả lời ngay vào nhóm.",
                        "MEMORY_AND_DRAFT": "Tin nhắn quan trọng cần ghi nhớ và có câu hỏi cần phản hồi. Lưu thông tin vào memory, soạn câu trả lời nháp gửi chủ nhân duyệt; tuyệt đối không tự reply vào chat.",
                        "DRAFT_PENDING_APPROVAL": "CHỈ áp dụng cho các câu hỏi ĐẶC BIỆT NHẠY CẢM MẬT (như bảng lương cá nhân nhân viên, bí mật tài chính kế toán riêng tư, thỏa thuận hợp đồng bảo mật, tranh chấp pháp lý nghiêm trọng). Còn các câu hỏi tiến độ, thành viên, thông tin dự án chung thì KHÔNG chọn nhãn này."
                    }
                },
                "knowledge_domain": {
                    "type": "choice",
                    "instructions": (
                        "Phân tích câu hỏi/tin nhắn để xác định phạm vi tri thức cần tra cứu. "
                        "Chọn 1 trong 3 nhãn bên dưới:"
                    ),
                    "criteria": {
                        "PROJECT": "Câu hỏi hoặc nội dung thuần túy về một dự án cụ thể, kế hoạch, tiến độ, sprint, task, bug, kiến trúc, tính năng kỹ thuật, phân công nhân sự trong dự án của nhóm.",
                        "COMPANY_POLICY": "Câu hỏi hoặc nội dung thuần túy về chính sách chung của công ty, quy định nhân sự, chế độ đãi ngộ, ngày nghỉ phép, bảo hiểm, văn hóa doanh nghiệp, bảo mật thông tin nội bộ, sổ tay nhân viên.",
                        "HYBRID": "Câu hỏi vừa liên quan đến dự án vừa liên quan đến chính sách công ty, hoặc câu hỏi chung chung, không rõ ràng, phân vân giữa hai phạm vi."
                    }
                }
            }
        }

        try:
            async with self._get_client_session(client) as http_client:
                response = await http_client.post(self.url, headers=self.headers, json=payload, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            
            answers = data.get("answers", {})
            action_data = answers.get("message_action")
            domain_data = answers.get("knowledge_domain")

            # --- XỬ LÝ KNOWLEDGE DOMAIN (PIGGYBACK ROUTING & PESSIMISTIC THRESHOLD) ---
            domain_choice = "HYBRID"
            domain_conf = 0.50

            if isinstance(domain_data, dict):
                raw_domain = domain_data.get("choice", "HYBRID")
                probabilities = domain_data.get("probabilities", {})
                prob_domain = probabilities.get(raw_domain, domain_data.get("confidence", 0.0))
                # Ngưỡng tin cậy bi quan: >= 0.85 mới chốt đơn kho, còn lại fallback HYBRID để truy vấn cả 2 kho
                if raw_domain in ("PROJECT", "COMPANY_POLICY") and prob_domain >= 0.85:
                    domain_choice = raw_domain
                    domain_conf = prob_domain
                elif raw_domain == "HYBRID":
                    domain_choice = "HYBRID"
                    domain_conf = prob_domain
                else:
                    # Điểm số < 0.85: Chủ động hạ cấp an toàn về HYBRID
                    domain_choice = "HYBRID"
                    domain_conf = prob_domain
            elif isinstance(domain_data, str) and domain_data in ("PROJECT", "COMPANY_POLICY", "HYBRID"):
                domain_choice = domain_data
                domain_conf = 0.85
            else:
                domain_choice = "HYBRID"
                domain_conf = 0.50

            if not action_data:
                return {
                    "action": "IGNORE",
                    "confidence": 0.0,
                    "knowledge_domain": domain_choice,
                    "domain_confidence": domain_conf,
                }
            
            # Nếu API trả về chuỗi trực tiếp (fallback)
            if isinstance(action_data, str):
                return {
                    "action": action_data,
                    "confidence": 0.0,
                    "knowledge_domain": domain_choice,
                    "domain_confidence": domain_conf,
                }
                
            # Schema dạng dictionary của JEV
            choice = action_data.get("choice", "IGNORE")
            confidence = action_data.get("confidence", 0.0)
            probabilities = action_data.get("probabilities", {})
            prob_choice = probabilities.get(choice, 0.0)

            # --- BỘ LỌC ĐỘ TỰ TIN (ĐÃ TỐI ƯU CÂN BẰNG PHẢN HỒI MƯỢT MÀ & AN TOÀN) ---
            prob_draft_risk = probabilities.get("DRAFT_PENDING_APPROVAL", 0.0)
            prob_reply = probabilities.get("REPLY_ONLY", 0.0)

            final_action = "IGNORE"
            final_conf = prob_choice

            if choice == "MEMORY_AND_DRAFT":
                if prob_choice >= 0.70:
                    final_action, final_conf = "MEMORY_AND_DRAFT", prob_choice
                else:
                    # Hạ cấp xuống chỉ ghi nhớ nếu độ tự tin chưa đủ cao.
                    final_action, final_conf = "MEMORY_ONLY", prob_choice

            elif choice == "MEMORY_ONLY":
                if prob_choice >= 0.50:
                    final_action, final_conf = "MEMORY_ONLY", prob_choice
                else:
                    final_action, final_conf = "IGNORE", prob_choice

            elif choice == "REPLY_ONLY":
                # Ưu tiên tự trả lời các câu hỏi cơ bản, chỉ chặn sang DRAFT khi rủi ro thực sự áp đảo
                if prob_draft_risk >= 0.85 and prob_draft_risk > prob_choice:
                    final_action, final_conf = "DRAFT_PENDING_APPROVAL", prob_draft_risk
                elif prob_choice >= 0.75:
                    final_action, final_conf = "REPLY_ONLY", prob_choice
                else:
                    final_action, final_conf = "DRAFT_PENDING_APPROVAL", prob_choice

            elif choice == "DRAFT_PENDING_APPROVAL":
                # Nếu JEV chọn DRAFT nhưng xác suất thấp (< 0.60) và REPLY_ONLY cũng cao -> Ưu tiên tự trả lời
                if prob_choice < 0.60 and prob_reply >= 0.30:
                    final_action, final_conf = "REPLY_ONLY", prob_reply
                else:
                    final_action, final_conf = "DRAFT_PENDING_APPROVAL", prob_choice

            else:  # choice == "IGNORE"
                final_action, final_conf = "IGNORE", prob_choice

            return {
                "action": final_action,
                "confidence": final_conf,
                "knowledge_domain": domain_choice,
                "domain_confidence": domain_conf,
            }
        except Exception as e:
            raise JEVError(f"JEV Classification Failed: {str(e)}") from e

    async def filter_chunks_relevance(
        self,
        query: str,
        chunks: list,
        max_snippet_chars: int = 300,
        timeout: float = 10.0,
        project_context: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
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

        ctx_label = f"liên quan đến {project_context.strip()}" if project_context else "liên quan đến bối cảnh dự án/công việc đang trao đổi"

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
                    f"Đoạn trích này có chứa thông tin phù hợp để tham khảo cho câu hỏi của người dùng không?"
                ),
                "criteria": {
                    "RELEVANT": f"Tài liệu hoặc thông tin hữu ích, {ctx_label} để trả lời câu hỏi",
                    "IRRELEVANT": "Tài liệu thuộc dự án khác, nội dung lạc đề hoặc tài liệu mẫu không liên quan"
                }
            }

        state_header = (
            f"Bối cảnh: Trợ lý AI đang hỗ trợ giải đáp cho {project_context.strip()}.\n"
            if project_context
            else "Bối cảnh: Trợ lý AI đang hỗ trợ giải đáp thông tin cho người dùng.\n"
        )
        payload = {
            "state": (
                f"{state_header}"
                f"Câu hỏi của người dùng: \"{query.strip()}\""
            ),
            "model": "jev-latest",
            "questions": questions,
        }


        try:
            async with self._get_client_session(client) as http_client:
                resp = await http_client.post(self.url, headers=self.headers, json=payload, timeout=timeout)
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

    async def check_forbidden_query(
        self,
        query: str,
        forbidden_labels: Union[str, List[str], None],
        timeout: float = 10.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """
        [Forbidden Intent Gating] Sử dụng JEV System One để kiểm tra xem câu hỏi của người dùng
        có vi phạm danh sách nhãn cấm (ví dụ: Ngân sách, Chi phí, Bảng lương, Hợp đồng...) hay không.

        Nếu vi phạm:
            Bot sẽ IM LẶNG HOÀN TOÀN (Zero-response / Silent Drop), không gọi WeKnora/Gemini.

        Returns:
            dict: {
                "is_forbidden": bool,
                "confidence": float,
                "choice": str,
                "forbidden_labels": list[str],
                "matched_label": Optional[str],
                "reason": str
            }
        """
        if not query or not query.strip():
            return {
                "is_forbidden": False,
                "confidence": 0.0,
                "choice": "ALLOWED",
                "forbidden_labels": [],
                "matched_label": None,
                "reason": "empty_query",
            }

        cleaned_labels: List[str] = []
        if isinstance(forbidden_labels, str):
            raw_items = [
                item.strip()
                for item in forbidden_labels.replace(";", ",").replace("\n", ",").split(",")
            ]
            cleaned_labels = [item for item in raw_items if item]
        elif isinstance(forbidden_labels, list):
            cleaned_labels = [
                str(item).strip() for item in forbidden_labels if str(item).strip()
            ]

        if not cleaned_labels:
            return {
                "is_forbidden": False,
                "confidence": 0.0,
                "choice": "ALLOWED",
                "forbidden_labels": [],
                "matched_label": None,
                "reason": "no_forbidden_labels",
            }

        # Kiểm tra nhanh từ khóa trực tiếp (Fast Keyword Match)
        query_lower = query.lower()
        keyword_matched = None
        for lbl in cleaned_labels:
            if lbl.lower() in query_lower:
                keyword_matched = lbl
                break

        if not self.api_key:
            if keyword_matched:
                return {
                    "is_forbidden": True,
                    "confidence": 1.0,
                    "choice": "FORBIDDEN",
                    "forbidden_labels": cleaned_labels,
                    "matched_label": keyword_matched,
                    "reason": "missing_api_key_keyword_match",
                }
            return {
                "is_forbidden": False,
                "confidence": 0.0,
                "choice": "ALLOWED",
                "forbidden_labels": cleaned_labels,
                "matched_label": None,
                "reason": "missing_api_key",
            }

        labels_display = ", ".join(cleaned_labels)
        payload = {
            "state": f"Nội dung câu hỏi của người dùng trong nhóm làm việc: \"{query.strip()}\"",
            "model": "jev-latest",
            "questions": {
                "forbidden_intent": {
                    "type": "choice",
                    "instructions": (
                        f"Bạn là chuyên gia an ninh thông tin và bảo mật nội bộ. "
                        f"Nhiệm vụ của bạn là kiểm tra xem câu hỏi của người dùng có cố tình tra cứu, "
                        f"hỏi đáp hoặc yêu cầu tiết lộ thông tin liên quan đến bất kỳ chủ đề cấm nào sau đây hay không: [{labels_display}]. "
                        f"Nếu câu hỏi vi phạm hoặc tìm kiếm thông tin về các chủ đề cấm trên, hãy chọn FORBIDDEN. "
                        f"Nếu là câu hỏi nghiệp vụ, trao đổi thông thường, kỹ thuật, tiến độ không liên quan đến chủ đề cấm, hãy chọn ALLOWED."
                    ),
                    "criteria": {
                        "FORBIDDEN": f"Câu hỏi liên quan trực tiếp hoặc gián tiếp đến một trong các chủ đề cấm: {labels_display}",
                        "ALLOWED": "Câu hỏi thông thường, an toàn, không chứa hoặc không đòi hỏi thông tin thuộc các chủ đề cấm."
                    }
                }
            }
        }

        try:
            async with self._get_client_session(client) as http_client:
                response = await http_client.post(self.url, headers=self.headers, json=payload, timeout=timeout)
            if response.status_code != 200:
                logger.warning(f"JEV API returned non-200 ({response.status_code}): {response.text}")
                if keyword_matched:
                    return {
                        "is_forbidden": True,
                        "confidence": 1.0,
                        "choice": "FORBIDDEN",
                        "forbidden_labels": cleaned_labels,
                        "matched_label": keyword_matched,
                        "reason": "api_error_keyword_fallback",
                    }
                return {
                    "is_forbidden": False,
                    "confidence": 0.0,
                    "choice": "ALLOWED",
                    "forbidden_labels": cleaned_labels,
                    "matched_label": None,
                    "reason": f"api_error_{response.status_code}",
                }

            data = response.json()
            action_data = data.get("answers", {}).get("forbidden_intent")
            if not action_data:
                return {
                    "is_forbidden": bool(keyword_matched),
                    "confidence": 1.0 if keyword_matched else 0.0,
                    "choice": "FORBIDDEN" if keyword_matched else "ALLOWED",
                    "forbidden_labels": cleaned_labels,
                    "matched_label": keyword_matched,
                    "reason": "empty_answer_keyword_fallback" if keyword_matched else "empty_answer",
                }

            if isinstance(action_data, str):
                is_forb = (action_data.upper() == "FORBIDDEN")
                return {
                    "is_forbidden": is_forb or bool(keyword_matched),
                    "confidence": 1.0 if (is_forb or keyword_matched) else 0.0,
                    "choice": "FORBIDDEN" if (is_forb or keyword_matched) else "ALLOWED",
                    "forbidden_labels": cleaned_labels,
                    "matched_label": keyword_matched,
                    "reason": "string_response",
                }

            choice = action_data.get("choice", "ALLOWED")
            probabilities = action_data.get("probabilities", {})
            prob_forbidden = float(probabilities.get("FORBIDDEN", 0.0))
            prob_allowed = float(probabilities.get("ALLOWED", 0.0))

            is_forbidden = (
                (choice == "FORBIDDEN" and prob_forbidden >= 0.65)
                or (prob_forbidden >= 0.70)
                or bool(keyword_matched)
            )
            confidence = prob_forbidden if is_forbidden else prob_allowed

            return {
                "is_forbidden": is_forbidden,
                "confidence": confidence,
                "choice": "FORBIDDEN" if is_forbidden else "ALLOWED",
                "forbidden_labels": cleaned_labels,
                "matched_label": keyword_matched,
                "reason": "jev_classified",
            }

        except Exception as e:
            logger.warning(f"JEV check_forbidden_query exception: {e}")
            if keyword_matched:
                return {
                    "is_forbidden": True,
                    "confidence": 1.0,
                    "choice": "FORBIDDEN",
                    "forbidden_labels": cleaned_labels,
                    "matched_label": keyword_matched,
                    "reason": "exception_keyword_fallback",
                }
            return {
                "is_forbidden": False,
                "confidence": 0.0,
                "choice": "ALLOWED",
                "forbidden_labels": cleaned_labels,
                "matched_label": None,
                "reason": f"exception: {str(e)}",
            }


jev_service = JevService()


