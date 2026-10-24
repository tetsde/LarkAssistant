"""
HiLark Chat Service - Unified Pipeline & Grounded QA Engine
===========================================================
Vị trí: server/services/chat_service.py

Chịu trách nhiệm toàn bộ logic nghiệp vụ hội thoại:
  1. Kiểm duyệt & làm sạch nội dung (text_filter).
  2. Phân loại định tuyến hành động thông minh qua JEV Classifier (IGNORE, MEMORY_ONLY, REPLY_ONLY, MEMORY_AND_DRAFT).
  3. Bóc tách và cập nhật tri thức động vào MongoDB (Entities & Facts).
  4. Truy xuất tri thức tài liệu từ WeKnora theo phân quyền nhóm chat (Chat Scope).
  5. Lọc ngữ nghĩa thông minh qua RAG Gate Relevance Filter.
  6. Hợp nhất bối cảnh đa nguồn với ContextComposer.
  7. Sinh câu trả lời Grounded QA bằng Gemini LLM (hỗ trợ Persona điều hành).
  8. Quản lý bản nháp (Draft Approval) hoặc phản hồi trực tiếp tới Lark.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional

from core.config import settings
from database import (
    get_all_entities as get_mongo_entities,
    get_all_facts as get_mongo_facts,
    save_extraction_to_mongo,
)
from models import ChatRequest
from services.draft_store import PendingDraft, draft_store
from services.jev import jev_service
from services.lark import lark_service
from services.llm_client import LLMClient, llm_client
from services.scope_service import scope_service
from services.weknora import weknora_service
from utils.context_composer import ContextComposer
from utils.rule_engine import rule_engine
from utils.text_filter import text_filter

logger = logging.getLogger("hilark.chat_service")

# Giới hạn số lượng tác vụ gọi LLM đồng thời trên toàn server
GLOBAL_LLM_SEMAPHORE = asyncio.Semaphore(getattr(settings, "MAX_CONCURRENT_CHAT_PIPELINES", 3))


# =============================================================================
# SYSTEM PROMPTS CHO GROUNDED QA
# =============================================================================

GROUNDED_QA_SYSTEM_PROMPT = """Bạn là Trợ lý Doanh nghiệp AI thông minh, chuyên nghiệp, chính xác và trung thực.

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
   - Trích dẫn rõ ràng nguồn thông tin nếu có (ví dụ: [Tài liệu: ...] hoặc [Cập nhật hội thoại: ...]).
4. ĐÚNG TRỌNG TÂM, GỌN GÀNG & ĐỦ Ý (GIỚI HẠN MAX 4096 TOKENS):
   - Hệ thống cấp cho bạn giới hạn phản hồi tối đa là 4096 tokens (max output tokens = 4096).
   - Bạn PHẢI trả lời cô đọng, dứt khoát, đi thẳng vào đúng trọng tâm câu hỏi dựa trên dữ liệu tri thức truy vấn được.
   - TUYỆT ĐỐI KHÔNG viết dông dài lan man, không lặp lại câu hỏi khiến câu trả lời bị đứt đoạn hay cụt câu giữa chừng.
   - BẮT BUỘC hoàn thành trọn vẹn toàn bộ các câu và đoạn văn, đảm bảo có phần kết thúc mạch lạc, hoàn chỉnh.
5. BẢO TOÀN ĐỊNH DANH DỰ ÁN (TUYỆT ĐỐI CẤM NHẦM TÊN TÀI LIỆU THÀNH TÊN DỰ ÁN):
   - Đọc kỹ PHẦN 0: BỐI CẢNH DỰ ÁN để xác định đúng "Tên nhóm chat" hoặc "Dự án phụ trách". Đó là tên chính thức duy nhất của dự án (ví dụ: "Project Atlas").
   - TUYỆT ĐỐI CẤM lấy tên của các file tài liệu đính kèm (như "04_So_tay_chinh_sach_cong_ty.pdf", "Ngan_sach_du_an.xlsx", "Code_of_Conduct.docx") để gán nhầm làm tên dự án! Các file này chỉ là tài liệu tham khảo nội bộ.
"""

GROUNDED_QA_USER_PERSONA_PROMPT = """Bạn là {responder_name} ({role}).
Bạn đang trực tiếp trả lời tin nhắn trên Lark cho thành viên/đồng nghiệp: {user_name}.
Tin nhắn gửi đi nhân danh tài khoản cá nhân của bạn (User Identity). Bạn là một người quản lý/nhà điều hành thực tế, dày dặn kinh nghiệm, quyết đoán nhưng văn minh, điềm tĩnh, tôn trọng và đồng hành cùng đội ngũ.

=== BỘ BỐI CẢNH TRI THỨC (KNOWLEDGE CONTEXT) ===
{context_text}

=== CÂU HỎI / TIN NHẮN TỪ {user_name} ===
{query}

=== CÁC NGUYÊN TẮC BẮT BUỘC KHI PHẢN HỒI (CHUẨN 10/10) ===
1. XƯNG HÔ VÀ TONE OF VOICE:
   - Với cá nhân {user_name}: Tự xưng là "anh", gọi người hỏi là "em" hoặc gọi trực tiếp tên "{user_name}" (Ví dụ: "Chào {user_name},...", "{user_name} giúp anh...").
   - Với tập thể/nhóm chat: Dùng "mình" khi nói về định hướng chung, gọi người nhận là "mọi người".
   - TUYỆT ĐỐI CẤM: Không bao giờ viết hoa chữ "Anh" ở giữa câu (chỉ viết hoa khi đứng ở đầu câu). Không dùng từ suồng sã như "Cả nhà", không dùng đại từ xa cách như "anh/chị", "chúng tôi".
   - TUYỆT ĐỐI KHÔNG xưng là AI, chatbot, hay trợ lý ảo. Không viết dạng bài luận hay dùng quá nhiều gạch đầu dòng hoa mỹ. Hãy trả lời tự nhiên như người thật đang nhắn tin trong app Lark (ưu tiên 2–4 câu ngắn gọn, dứt khoát).
   - Làm mềm câu tự nhiên: Dùng các từ đệm như "nhờ em...", "em cứ...", và kết thúc câu bằng "nhé", "sớm nhé", "có vướng gì báo anh hỗ trợ".

2. NÓI NHƯ KIẾN THỨC CỦA CHÍNH MÌNH (KHÔNG LỘ NGUỒN TÀI LIỆU):
   - Tuyệt đối KHÔNG nói: "Theo tài liệu WeKnora...", "Theo cơ sở tri thức...", "Theo văn bản được cung cấp...".
   - Hãy nói tự nhiên dưới góc nhìn người điều hành: "Về vấn đề này, hiện tại...", "Theo kế hoạch bên mình...", "Quy trình hiện tại là...".

3. NGUYÊN TẮC ƯU TIÊN SỰ THẬT CẬP NHẬT (Fact Override):
   - "PHẦN 2: THỰC TẾ CẬP NHẬT & MỆNH ĐỀ ĐỘNG (MONGODB CLAIMS)" chứa các thông tin cập nhật thời gian thực từ hội thoại trao đổi.
   - Nếu có mâu thuẫn giữa "PHẦN 1: TÀI LIỆU (WEKNORA)" và "PHẦN 2: CLAIMS", thông tin có trạng thái [CURRENT] trong Claims LUÔN ĐƯỢC ƯU TIÊN TUYỆT ĐỐI.
   - Khi có thay đổi (deadline, ngân sách, nhân sự phụ trách), hãy giải thích ngắn gọn, tự nhiên như chính bạn đã nắm việc thay đổi đó (Ví dụ: "Dự án này trước đây do Nam phụ trách, nhưng tuần trước mình đã chuyển giao cho Nguyên lead rồi em nhé").

4. XỬ LÝ KHI BỐI CẢNH THIẾU THÔNG TIN / CHƯA RÕ:
   - Tuyệt đối KHÔNG bịa đặt số liệu hay chính sách không có trong bối cảnh.
   - Đồng thời, KHÔNG trả lời kiểu máy móc ("Hệ thống chưa tìm thấy dữ liệu...").
   - Hãy trả lời thực tế như một người sếp:
     * "Phần này anh chưa nắm được số liệu/cập nhật mới nhất. Để anh kiểm tra lại với bên phụ trách rồi nhắn em sau nhé."
     * Hoặc: "Vụ này em chủ động đối soát trước với bộ phận liên quan giúp anh, có gì báo lại anh nhé."

5. CÂU MẪU THAM CHIẾU GIỌNG ĐIỆU (BENCHMARK 10/10):
   - "Phần số liệu trong báo cáo chưa khớp với dữ liệu nguồn. Em kiểm tra lại công thức và đối chiếu với bảng gốc trước khi gửi bản mới nhé. Nếu chưa rõ chỗ nào, cứ trao đổi với anh để xử lý sớm."
   - "Cảm ơn mọi người đã hoàn thành đợt triển khai đúng hạn. Kết quả lần này cho thấy sự phối hợp giữa các bộ phận đã tốt hơn. Mình tiếp tục giữ cách làm này và ghi lại những điểm cần cải thiện cho đợt sau nhé."
   - "Bản thử nghiệm đã chạy được rồi, cảm ơn mọi người. Hôm nay mình tập trung sửa ba lỗi ảnh hưởng trực tiếp đến người dùng; các phần còn lại để vòng sau. Có vướng mắc thì báo ngay trong nhóm nhé."
   - "Minh phụ trách tổng hợp số liệu bán hàng của ba khu vực giúp anh, gồm doanh thu, tỷ lệ hoàn đơn và các biến động đáng chú ý. Gửi bản đầu tiên trước 15 giờ thứ Năm; nếu thiếu dữ liệu, báo anh sớm nhé."

6. NGUYÊN TẮC BẢO TOÀN DANH TÍNH & THẨM QUYỀN (QUAN TRỌNG NHẤT):
   - NGƯỜI HỎI LÀ {user_name}: Bạn đang nói chuyện trực tiếp với {user_name}. TUYỆT ĐỐI KHÔNG nhầm lẫn hay gán ghép vai trò, nhiệm vụ, kỹ năng hay lộ trình của nhân sự khác (như Trí, Nguyên...) vào {user_name}.
   - NGUYÊN TẮC THẨM QUYỀN: Nếu bối cảnh có mục 💡 [ĐỀ XUẤT NHÂN SỰ / CHỜ DUYỆT], đây CHỈ LÀ ĐỀ XUẤT CÁ NHÂN từ nhân sự (nguyện vọng xin làm lead, xin chuyển đổi vai trò), CHƯA PHẢI QUYẾT ĐỊNH CỦA BẠN. Hãy trả lời rõ ràng: "Đề xuất này của em anh đã ghi nhận nhưng cần cân nhắc thêm trước khi chốt nhé".
   - TUYỆT ĐỐI KHÔNG sinh thẻ trích dẫn nguồn lộ liễu (như [Cập nhật hội thoại: ...] hay [Tài liệu: ...]) trong câu trả lời.

7. NGUYÊN TẮC SUY LUẬN BỐI CẢNH DỰ ÁN & ĐỊNH DANH BẤT BIẾN (SCOPE & PROJECT IDENTITY):
   - Bạn đang trả lời trong một nhóm chat dự án cụ thể. Nếu thành viên hỏi các câu hỏi chung chung về dự án (ví dụ: "cho em xin thông tin dự án", "dự án này làm gì", "kế hoạch dự án ra sao", "mục tiêu dự án"), bạn MẶC ĐỊNH hiểu rằng thành viên đang hỏi về dự án của nhóm này (được nêu rõ tại mục "Tên nhóm chat" hoặc "Dự án phụ trách" trong PHẦN 0, ví dụ: "Project Atlas").
   - TUYỆT ĐỐI KHÔNG hỏi ngược lại người dùng những câu như: "em cần thông tin về dự án nào", "anh chưa rõ em hỏi dự án nào". Hãy chủ động cung cấp ngay bức tranh tổng quan/chi tiết của dự án thuộc nhóm này cho người hỏi!
   - NGUYÊN TẮC ĐỊNH DANH BẤT BIẾN (CẤM NHẦM TÊN FILE THÀNH TÊN DỰ ÁN): 
     * Tên dự án chính thức của nhóm là tên ghi trong PHẦN 0 (ví dụ: "Project Atlas").
     * TUYỆT ĐỐI CẤM lấy tên của các file tài liệu đính kèm (như "04_So_tay_chinh_sach_cong_ty.pdf", "Ngan_sach_du_an.xlsx", "Code_of_Conduct.docx") để nói làm tên dự án (Ví dụ: CẤM TUYỆT ĐỐI các câu như: "Dự án mình đang triển khai là 04 Sổ Tay Chính Sách Công Ty"). Các file này chỉ là văn bản chính sách/tham khảo nội bộ!
"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def process_memory_extraction(
    query_text: str,
    sender: str = "User",
    asserted_by: Optional[Dict[str, Any]] = None,
    chat_id: Optional[str] = None,
    project_tag: Optional[str] = None,
    scope_type: str = "chat",
) -> Dict[str, Any]:
    """Helper xử lý trích xuất Entities & Facts và lưu trực tiếp vào MongoDB có gắn scope."""
    msg_id = f"msg_{uuid.uuid4().hex[:8]}"

    try:
        existing_entities = await get_mongo_entities()
        existing_facts = await get_mongo_facts(chat_id=chat_id, project_tag=project_tag)
    except Exception as e:
        logger.error(f"Lỗi khi đọc từ MongoDB: {e}")
        existing_entities = []
        existing_facts = []

    from utils.llm_extractor import extract_async

    extraction_result = await extract_async(
        query=query_text,
        workspace_id="default",
        source_message_id=msg_id,
        sender=sender,
        asserted_by=asserted_by,
        existing_entities=existing_entities,
        existing_facts=existing_facts,
    )

    mongo_saved = await save_extraction_to_mongo(
        extraction_result,
        chat_id=chat_id,
        project_tag=project_tag,
        scope_type=scope_type,
    )

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
    responder_name: Optional[str] = None,
    role: Optional[str] = None,
    max_output_tokens: int = 4096,
) -> str:
    """Sinh câu trả lời Grounded QA dựa trên context hợp nhất (hỗ trợ đích danh user, max 4096 tokens)."""
    key = api_key or getattr(settings, "GEMINI_API_KEY", "") or getattr(settings, "gemini_api", "")
    if not key:
        logger.warning("Không tìm thấy GEMINI_API_KEY trong cấu hình. Bỏ qua LLM Grounded QA.")
        return ""

    effective_role = role or getattr(settings, "LARK_USER_ROLE", "") or "CEO / Founder / CTO"
    effective_responder = responder_name or getattr(settings, "LARK_USER_NAME", "") or ""

    if user_name:
        prompt = GROUNDED_QA_USER_PERSONA_PROMPT.format(
            context_text=context_text,
            query=query,
            user_name=user_name,
            responder_name=effective_responder or "Sếp",
            role=effective_role,
        )
    else:
        prompt = GROUNDED_QA_SYSTEM_PROMPT.format(
            context_text=context_text,
            query=query,
        )

    client = LLMClient(api_key=api_key) if api_key else llm_client
    try:
        async with GLOBAL_LLM_SEMAPHORE:
            ans = await client.generate_text_async(
                prompt=prompt,
                model_name=model_name,
                max_output_tokens=max_output_tokens,
            )
        return ans.strip()
    except Exception as e:
        logger.warning(f"Lỗi khi gọi LLM generate_text_async: {e}")
        return ""


# =============================================================================
# CORE CHAT PIPELINE
# =============================================================================

async def process_chat_pipeline(
    query: str,
    sender: str = "User",
    channel: str = "api",
    message_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    reply_to_lark: bool = False,
    retrieve_count: int = 5,
    user_name: Optional[str] = None,
    responder_name: Optional[str] = None,
    role: Optional[str] = None,
    is_owner: bool = False,
) -> Dict[str, Any]:
    """
    Quy trình xử lý hội thoại toàn diện (Unified Chat Pipeline):
      1. text_filter: Làm sạch ký tự lạ, validate độ dài tin nhắn.
      2. JEV Service: Phân loại định tuyến hành động (IGNORE, MEMORY_ONLY, REPLY_ONLY, MEMORY_AND_DRAFT).
      3. Thực thi hành động:
         - IGNORE: Bỏ qua (tin nhắn rác, chào hỏi xã giao).
         - MEMORY_ONLY: Trích xuất thực thể & mệnh đề -> Lưu MongoDB.
         - REPLY_ONLY: Tra cứu WeKnora Chunks + MongoDB Claims -> ContextComposer -> Gemini Grounded QA -> Reply Lark.
         - MEMORY_AND_DRAFT: Lưu memory -> tra cứu context -> soạn draft, chờ chủ nhân duyệt trước khi reply.
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

    # ── Tự động lưu Staging nếu có chat_id và message_id (Tránh ghi đúp nếu đã qua bot_service) ──
    if chat_id and message_id and channel != "lark_group":
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

    # ── Tra cứu Cấu hình & Phân quyền Nhóm từ Lark Base / MongoDB ──
    scope_record = None
    if chat_id:
        try:
            scope_record = await scope_service.get_scope_by_chat_id(chat_id)
        except Exception as e:
            logger.warning(f"Lỗi khi tra cứu scope_record cho chat_id={chat_id}: {e}")

    proj_context_name = None
    if scope_record:
        proj_context_name = (
            scope_record.get_project_name()
            if hasattr(scope_record, "get_project_name")
            else (scope_record.project_tag or scope_record.chat_name or "")
        )

    # ── [CHỐT CHẶN 1: KIỂM TRA TRẠNG THÁI NHÓM] (Active vs Inactive) ──
    if scope_record and not scope_record.is_active:
        logger.info(
            f"🛑 [GROUP INACTIVE] Nhóm '{scope_record.chat_name}' ({chat_id}) đang ở trạng thái '{scope_record.status}'. Bỏ qua hoàn toàn tin nhắn."
        )
        return {
            "status": "group_inactive",
            "jev_action": "IGNORE",
            "jev_confidence": 1.0,
            "query": clean_query,
            "answer": None,
            "message": f"Nhóm chat đang ở trạng thái '{scope_record.status}'. Bot tạm dừng phản hồi.",
        }

    # ── [CHỐT CHẶN 2: KIỂM TRA NHÃN CẤM XEM BẰNG JEV] (Forbidden Intent Gating) ──
    if scope_record and scope_record.forbidden_labels:
        try:
            forbidden_res = await jev_service.check_forbidden_query(
                query=clean_query,
                forbidden_labels=scope_record.forbidden_labels,
            )
            if forbidden_res.get("is_forbidden"):
                matched_label = forbidden_res.get("matched_label") or "Chủ đề bảo mật bị cấm"
                conf = forbidden_res.get("confidence", 1.0)
                logger.warning(
                    f"⛔ [FORBIDDEN DROP] Thành viên '{user_name}' ({sender}) trong nhóm '{scope_record.chat_name}' "
                    f"hỏi vào chủ đề cấm '{matched_label}' (Độ tin cậy: {conf:.2f}). Kích hoạt Zero-response."
                )
                print(
                    f"⛔ [FORBIDDEN DROP] Thành viên '{user_name}' hỏi vào chủ đề cấm '{matched_label}'. "
                    f"Bot IM LẶNG HOÀN TOÀN (Zero-response)."
                )

                # Cảnh báo âm thầm tới DM của Chủ nhân nếu tin nhắn xuất phát từ group
                if channel == "lark_group":
                    alert_text = (
                        f"⚠️ [CẢNH BÁO BẢO MẬT: TRUY CẬP TRÁI PHÉP]\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"👥 Nhóm chat : {scope_record.chat_name} ({chat_id})\n"
                        f"👤 Thành viên: {user_name or 'N/A'} ({sender or 'N/A'})\n"
                        f"💬 Câu hỏi   : \"{clean_query}\"\n"
                        f"🚫 Nhãn cấm  : {matched_label}\n"
                        f"🛡️ Phản hồi  : Bot đã IM LẶNG HOÀN TOÀN, không phát ngôn vào nhóm và không gọi WeKnora.\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    )
                    try:
                        await lark_service.send_bot_dm_to_owner(alert_text)
                    except Exception as e:
                        logger.debug(f"Không thể gửi alert DM cho chủ nhân: {e}")

                return {
                    "status": "forbidden_query",
                    "jev_action": "IGNORE",
                    "jev_confidence": conf,
                    "query": clean_query,
                    "answer": None,
                    "message": f"Câu hỏi vi phạm nhãn cấm xem '{matched_label}'. Đã kích hoạt cơ chế Zero-response.",
                    "forbidden_check": forbidden_res,
                }
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra forbidden_query qua JEV: {e}")

    # ── Bước 2: JEV Routing - Phân loại xem tin nhắn có đáng xử lý hay không ──
    jev_domain = "HYBRID"
    jev_domain_conf = 0.50
    try:
        jev_result = await jev_service.classify_message(clean_query)
        jev_action = jev_result.get("action", "IGNORE")
        jev_confidence = jev_result.get("confidence", 0.0)
        jev_domain = jev_result.get("knowledge_domain", "HYBRID")
        jev_domain_conf = jev_result.get("domain_confidence", 0.50)
    except Exception as e:
        logger.error(f"Lỗi phân loại JEV: {e}")
        # [SAFETY] Khi JEV API lỗi/timeout, TUYỆT ĐỐI không tự ý phát ngôn vào nhóm.
        jev_action = "DRAFT_PENDING_APPROVAL" if ("?" in clean_query or len(clean_query.split()) >= 4) else "IGNORE"
        jev_confidence = 0.0
        jev_domain = "HYBRID"
        jev_domain_conf = 0.50

    # ── [OWNER ANTI-LOOP SHIELD] ──
    # Nếu tin nhắn do CHÍNH CHỦ NHÂN phát ngôn trong GROUP:
    # Tuyệt đối không sinh phản hồi để triệt tiêu 100% loop!
    if is_owner and channel == "lark_group":
        if jev_action in ("MEMORY_ONLY", "MEMORY_AND_DRAFT"):
            logger.info(f"👑 [OWNER SHIELD] Chủ nhân phát ngôn có tri thức: Ép JEV {jev_action} -> MEMORY_ONLY (Chỉ ghi nhớ, cấm reply).")
            print(f"👑 [OWNER SHIELD] Chủ nhân phát ngôn: Ép {jev_action} -> MEMORY_ONLY (Chỉ bóc tách & lưu tri thức, không reply).")
            jev_action = "MEMORY_ONLY"
        else:
            logger.info(f"👑 [OWNER SHIELD] Chủ nhân tán gẫu/hỏi đáp: Ép JEV {jev_action} -> IGNORE (Bỏ qua, không reply chống loop).")
            print(f"👑 [OWNER SHIELD] Chủ nhân phát ngôn: Ép {jev_action} -> IGNORE (Bỏ qua, không reply chống loop).")
            jev_action = "IGNORE"

    # TH1: IGNORE - Tin rác, chào hỏi vô thưởng vô phạt
    if jev_action == "IGNORE":
        return {
            "status": "ignored",
            "jev_action": jev_action,
            "jev_confidence": jev_confidence,
            "knowledge_domain": jev_domain,
            "domain_confidence": jev_domain_conf,
            "query": clean_query,
            "answer": None,
            "message": "Tin nhắn rác hoặc tán gẫu không quan trọng. Không lưu, không trả lời.",
        }

    # Xác định thẩm quyền người phát ngôn
    speaker_role = "owner" if is_owner else "member"
    asserted_by = {
        "user_id": sender or "",
        "user_name": user_name or sender or "Thành viên",
        "role": speaker_role,
    }

    # Bước 3: Lưu memory cho các intent cần ghi nhớ theo scope nhóm
    extraction_data = None
    if jev_action in ("MEMORY_ONLY", "MEMORY_AND_DRAFT"):
        extraction_data = await process_memory_extraction(
            query_text=clean_query,
            sender=sender,
            asserted_by=asserted_by,
            chat_id=chat_id,
            project_tag=proj_context_name,
            scope_type="chat" if chat_id else "global",
        )

    # TH2: MEMORY_ONLY - Đã trích xuất xong, không cần tạo câu trả lời
    if jev_action == "MEMORY_ONLY":
        return {
            "status": "memorized",
            "jev_action": jev_action,
            "jev_confidence": jev_confidence,
            "knowledge_domain": jev_domain,
            "domain_confidence": jev_domain_conf,
            "query": clean_query,
            "extraction": extraction_data,
            "answer": None,
            "message": "Thông tin quan trọng đã được trích xuất và lưu vào MongoDB. Không cần phản hồi.",
        }

    # REPLY_ONLY và MEMORY_AND_DRAFT đều cần tạo nội dung từ context.
    # 1. Lấy active claims (gồm cả Current và Proposed) và Entities từ MongoDB theo scope nhóm
    all_facts = []
    entity_map: Dict[str, Any] = {}
    try:
        facts_coro = get_mongo_facts(
            chat_id=chat_id,
            project_tag=proj_context_name,
        )
        entities_coro = get_mongo_entities(workspace_id=None)
        facts_res, entities_res = await asyncio.gather(facts_coro, entities_coro, return_exceptions=True)

        if isinstance(facts_res, list):
            all_facts = facts_res
        elif isinstance(facts_res, Exception):
            logger.warning(f"Lỗi khi đọc facts từ MongoDB: {facts_res}")

        if isinstance(entities_res, list):
            entity_map = {str(e.get("id")): e for e in entities_res if isinstance(e, dict) and e.get("id")}
        elif isinstance(entities_res, Exception):
            logger.warning(f"Lỗi khi đọc entities từ MongoDB: {entities_res}")
    except Exception as e:
        logger.warning(f"Lỗi khi đọc tri thức động từ MongoDB: {e}")

    active_claims = [f for f in all_facts if f.get("status", "current") in ("current", "proposed")]

    # 2. Truy xuất các đoạn văn bản (chunks) từ WeKnora Knowledge Base theo phân quyền nhóm chat & Two-Tier Routing
    chunks = []
    try:
        if not scope_record and chat_id:
            scope_record = await scope_service.get_scope_by_chat_id(chat_id)

        # 1. Kho dự án chuyên biệt của nhóm chat (chứa tài liệu dự án theo phân quyền)
        project_dataset_id = scope_record.dataset_id if scope_record else (settings.WEKNORA_DATASET_ID or None)

        # 2. Kho Chính Sách & Quy Định Toàn Công Ty (Sổ tay nhân viên, Code of Conduct, Policies...)
        policy_dataset_id = settings.WEKNORA_POLICY_DATASET_ID or None

        # 3. Kho Wiki / Digest Hội thoại (nếu có cấu hình)
        wiki_dataset_id = (
            (scope_record.wiki_dataset_id if (scope_record and scope_record.wiki_dataset_id) else None)
            or settings.WEKNORA_WIKI_DATASET_ID
            or None
        )

        # Tập hợp các kho tri thức quy chế / chính sách toàn công ty (Policy KB luôn là cốt lõi)
        global_policy_kbs = [kb for kb in [policy_dataset_id, wiki_dataset_id] if kb]
        global_policy_kbs = list(dict.fromkeys(global_policy_kbs))

        target_knowledge_ids = (
            scope_record.knowledge_ids if (scope_record and scope_record.knowledge_ids) else None
        )

        # Context-Driven Query Expansion cho câu hỏi dự án
        retrieval_query = clean_query
        if proj_context_name and proj_context_name.lower() not in clean_query.lower():
            retrieval_query = f"{clean_query} {proj_context_name}"

        # ── [RAG TWO-TIER PIGGYBACK ROUTING] ──
        # Pessimistic Threshold: Chỉ khi confidence >= 0.85 mới định tuyến đơn kho, còn lại fallback HYBRID song song
        if jev_domain == "COMPANY_POLICY" and global_policy_kbs:
            logger.info(
                f"🏛️ [RAG Routing] Định tuyến đơn kho -> Global Policy KBs ({global_policy_kbs}) | Confidence: {jev_domain_conf:.2f}"
            )
            chunks = await weknora_service.retrieve(
                query=clean_query,
                knowledge_base_ids=global_policy_kbs,
                knowledge_ids=None,
                match_count=retrieve_count,
            )
        elif jev_domain == "PROJECT" and project_dataset_id:
            logger.info(
                f"📁 [RAG Routing] Định tuyến đơn kho -> Project Scoped KB ({project_dataset_id}) | Confidence: {jev_domain_conf:.2f}"
            )
            chunks = await weknora_service.retrieve(
                query=retrieval_query,
                knowledge_base_ids=[project_dataset_id],
                knowledge_ids=target_knowledge_ids,
                match_count=retrieve_count,
            )
        else:
            # HYBRID MODE hoặc Phân vân (Confidence < 0.85): Truy vấn song song cả kho dự án và kho chính sách
            if project_dataset_id and global_policy_kbs:
                logger.info(
                    f"🔀 [RAG Routing] Kích hoạt HYBRID parallel search (Project: {project_dataset_id}, Policy KBs: {global_policy_kbs})"
                )
                tasks = [
                    weknora_service.retrieve(
                        query=retrieval_query,
                        knowledge_base_ids=[project_dataset_id],
                        knowledge_ids=target_knowledge_ids,
                        match_count=retrieve_count,
                    ),
                    weknora_service.retrieve(
                        query=clean_query,
                        knowledge_base_ids=global_policy_kbs,
                        knowledge_ids=None,
                        match_count=retrieve_count,
                    ),
                ]
                res_proj, res_policy = await asyncio.gather(*tasks, return_exceptions=True)
                chunks_proj = res_proj if isinstance(res_proj, list) else []
                chunks_policy = res_policy if isinstance(res_policy, list) else []

                # Hợp nhất và lọc trùng chunks theo id/content, sắp xếp theo score cao nhất
                merged_chunks = []
                seen_chunk_ids = set()
                for c in sorted(chunks_proj + chunks_policy, key=lambda x: x.get("score") or 0.0, reverse=True):
                    cid = c.get("id") or c.get("chunk_id") or c.get("content", "")[:50]
                    if cid not in seen_chunk_ids:
                        seen_chunk_ids.add(cid)
                        merged_chunks.append(c)
                chunks = merged_chunks[:retrieve_count]
            elif project_dataset_id:
                chunks = await weknora_service.retrieve(
                    query=retrieval_query,
                    knowledge_base_ids=[project_dataset_id],
                    knowledge_ids=target_knowledge_ids,
                    match_count=retrieve_count,
                )
            elif global_policy_kbs:
                chunks = await weknora_service.retrieve(
                    query=clean_query,
                    knowledge_base_ids=global_policy_kbs,
                    knowledge_ids=None,
                    match_count=retrieve_count,
                )
    except Exception as e:
        logger.warning(f"Lỗi WeKnora retrieve: {e}")

    # Chuẩn hóa chunks cho ContextComposer và Rule Engine
    normalized_chunks = []
    for c in chunks:
        doc_name = (
            c.get("knowledge_title")
            or c.get("document_name")
            or "Tài liệu hệ thống"
        )
        kb_id = str(c.get("knowledge_base_id") or "")
        is_policy_doc = (
            kb_id == str(settings.WEKNORA_POLICY_DATASET_ID)
            or any(
                kw in doc_name.lower()
                for kw in ["so_tay", "chinh_sach", "quy_che", "quy_tac", "employee_handbook", "code_of_conduct", "policy", "handbook"]
            )
        )
        normalized_chunks.append({
            "content": c.get("content", ""),
            "document_name": doc_name,
            "chunk_id": c.get("id") or c.get("chunk_id"),
            "score": c.get("score"),
            "is_policy_doc": is_policy_doc,
            "knowledge_base_id": kb_id,
        })

    # ── [CHỐT CHẶN BẢO MẬT: UNIFIED RULE ENGINE] ──
    # Với các chunks dự án: Lọc nghiêm ngặt theo forbidden_labels của nhóm.
    # Với các chunks chính sách toàn công ty (Policy KB): Miễn trừ nhãn cấm dự án (như ngân sách/chi phí dự án)
    # để bảo đảm nhân viên luôn tra cứu được quyền lợi nghỉ phép, quy tắc ứng xử, chế độ công ty.
    forbidden_labels = scope_record.forbidden_labels if scope_record else []
    proj_chunks_to_filter = [c for c in normalized_chunks if not c.get("is_policy_doc")]
    policy_chunks = [c for c in normalized_chunks if c.get("is_policy_doc")]

    clean_proj_chunks, clean_claims = rule_engine.sanitize(
        chunks=proj_chunks_to_filter,
        claims=active_claims,
        forbidden_labels=forbidden_labels,
        query=clean_query,
    )
    # Hợp nhất: policy chunks hợp lệ + project chunks đã được làm sạch
    clean_chunks = [c for c in policy_chunks if len(str(c.get("content", "")).strip()) >= 3] + clean_proj_chunks

    # ── [RAG GATE RELEVANCE FILTERING] ──
    # Lọc ngữ nghĩa thông minh qua JEV (1 Call duy nhất) trên các chunks đã được khử trùng
    if clean_chunks and len(clean_chunks) > 1:
        try:
            proj_ctx = proj_context_name or (scope_record.dataset_name if scope_record else None) or (scope_record.chat_name if scope_record else None)
            clean_chunks = await jev_service.filter_chunks_relevance(
                clean_query,
                clean_chunks,
                project_context=proj_ctx,
            )
        except Exception as e:
            logger.warning(f"Lỗi khi lọc chunks qua JEV: {e}")

    # [SAFETY - RAG GATE] Nếu REPLY_ONLY nhưng không có chunks KB nào đủ cơ sở tri thức
    # -> Downgrade bắt buộc sang DRAFT_PENDING_APPROVAL để người dùng tự kiểm tra & duyệt
    if jev_action == "REPLY_ONLY" and not clean_chunks and not clean_claims:
        logger.warning(
            f"[RAG GATE] REPLY_ONLY nhưng KB rỗng (0 chunks, 0 claims) "
            f"-> Downgrade sang DRAFT_PENDING_APPROVAL. Query: '{clean_query}'"
        )
        jev_action = "DRAFT_PENDING_APPROVAL"

    # ── [CHỐT CHẶN BẢO MẬT: MỨC ĐỘ BẢO MẬT TUYỆT MẬT (ZERO AUTO-REPLY)] ──
    # Nếu nhóm ở mức độ "Tuyệt mật" (Strict Confidential), CẤM hoàn toàn bot tự động reply vào nhóm.
    # 100% câu hỏi trả lời bắt buộc chuyển thành DRAFT_PENDING_APPROVAL gửi về DM của Sếp duyệt!
    is_confidential_group = bool(scope_record and scope_record.is_confidential)
    if is_confidential_group and jev_action == "REPLY_ONLY":
        logger.warning(
            f"🔒 [SECURITY LEVEL - TUYỆT MẬT] Nhóm '{scope_record.chat_name}' ({chat_id}) được thiết lập 'Tuyệt mật'. "
            f"Kích hoạt Zero Auto-reply: Ép chuyển REPLY_ONLY sang DRAFT_PENDING_APPROVAL."
        )
        jev_action = "DRAFT_PENDING_APPROVAL"

    # 3. Hợp nhất ngữ cảnh với ContextComposer
    scope_ctx_data = None
    if scope_record:
        documents = (
            scope_record.documents
            if scope_record.documents
            else (scope_record.get_document_names() if hasattr(scope_record, "get_document_names") else [])
        )
        proj_name = proj_context_name or (
            scope_record.get_project_name()
            if hasattr(scope_record, "get_project_name")
            else (scope_record.chat_name or "Dự án nội bộ")
        )
        scope_ctx_data = {
            "chat_name": scope_record.chat_name,
            "project_name": proj_name,
            "documents": documents,
        }

    composer = ContextComposer()
    composed = composer.compose(
        retriever_data=clean_chunks if clean_chunks else None,
        claims_data=clean_claims if clean_claims else None,
        query=clean_query,
        entity_map=entity_map,
        auto_align=True,
        scope_context=scope_ctx_data,
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
    if jev_action in ("DRAFT_PENDING_APPROVAL", "MEMORY_AND_DRAFT"):
        dm_notice = None

        owner_open_id = lark_service.owner_open_id
        if not owner_open_id:
            raise RuntimeError("Thiếu LARK_USER_OPEN_ID để lưu draft chờ duyệt.")

        await draft_store.create(
            PendingDraft(
                owner_id=owner_open_id,
                message_id=message_id or "",
                chat_id=chat_id or "",
                query=clean_query,
                draft_answer=answer,
                user_name=user_name or "bạn",
                responder_name=responder_name,
            )
        )

        if reply_to_lark:
            header_title = "DỰ ÁN TUYỆT MẬT" if is_confidential_group else "CÂU HỎI CÓ RỦI RO"
            reason_text = (
                "Nhóm thuộc mức độ TUYỆT MẬT (Chính sách: 100% câu trả lời phải được Sếp duyệt trước khi gửi vào nhóm)."
                if is_confidential_group
                else "Câu hỏi có dữ liệu trong Knowledge Base nhưng thuộc nhóm rủi ro/nhạy cảm."
            )
            chat_title = scope_record.chat_name if scope_record else (chat_id or "Nhóm chat")
            draft_card_text = (
                f"📝 [SOẠN NHÁP CHỜ DUYỆT - {header_title}]\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👥 Nhóm chat : {chat_title}\n"
                f"🛡️ Bảo mật   : {'TUYỆT MẬT (Khóa auto-reply)' if is_confidential_group else (scope_record.security_level if scope_record else 'Tiêu chuẩn')}\n"
                f"👤 Người hỏi : {user_name or 'bạn'}\n"
                f"💬 Câu hỏi   : \"{clean_query}\"\n\n"
                f"💡 Bản nháp AI soạn sẵn:\n"
                f"\"{answer}\"\n\n"
                f"⚠️ Lý do: {reason_text}\n"
                f"👉 Hành động chờ duyệt: Nhắn lại [Gửi] / [Sửa: <nội dung>] / [Bỏ]\n"
                f"🆔 Message ID gốc: {message_id or 'N/A'}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            try:
                dm_notice = await lark_service.send_bot_dm_to_owner(draft_card_text)
                logger.info(f"Đã lưu draft vào MongoDB và gửi thông báo duyệt (Message ID: {message_id})")
            except Exception as e:
                logger.error(f"Lỗi gửi bản nháp cho chủ nhân: {e}")
                dm_notice = {"error": str(e)}

        return {
            "status": "memory_and_draft_pending_approval" if jev_action == "MEMORY_AND_DRAFT" else "draft_pending_approval",
            "jev_action": jev_action,
            "jev_confidence": jev_confidence,
            "knowledge_domain": jev_domain,
            "domain_confidence": jev_domain_conf,
            "query": clean_query,
            "draft_answer": answer,
            "answer": answer,
            "actions": ["Gửi", "Sửa", "Bỏ"],
            "user_name": user_name,
            "responder_name": responder_name,
            "extraction": extraction_data,
            "composed_context": composed,
            "lark_response": dm_notice,
            "message": "Draft đã được lưu với trạng thái pending; chưa gửi câu trả lời vào nhóm.",
        }

    # Chỉ REPLY_ONLY mới được gửi thẳng vào nhóm
    lark_reply_result = None
    if reply_to_lark and message_id:
        try:
            lark_reply_result = await lark_service.areply_text(
                message_id=message_id,
                text=answer,
                as_user=True,
            )
        except Exception as e:
            logger.error(f"Lỗi khi gửi reply tới Lark: {e}")
            lark_reply_result = {"error": str(e), "success": False}

    return {
        "status": "auto_replied",
        "jev_action": jev_action,
        "jev_confidence": jev_confidence,
        "knowledge_domain": jev_domain,
        "domain_confidence": jev_domain_conf,
        "query": clean_query,
        "answer": answer,
        "user_name": user_name,
        "responder_name": responder_name,
        "extraction": extraction_data,
        "composed_context": composed,
        "lark_response": lark_reply_result,
        "message": "Đã tạo câu trả lời tự động.",
    }


class ChatService:
    """Class wrapper cho ChatService."""
    process_pipeline = staticmethod(process_chat_pipeline)
    extract_memory = staticmethod(process_memory_extraction)
    generate_answer = staticmethod(generate_grounded_answer)


chat_service = ChatService()
