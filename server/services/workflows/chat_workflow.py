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
import sys
import uuid
from typing import Any, Dict, List, Optional

from core.config import settings
from database.scoped_query import get_current_tenant_key, async_tenant_context
from database import (
    get_all_entities as get_mongo_entities,
    get_all_facts as get_mongo_facts,
    save_extraction_to_mongo,
)
from models import ChatRequest, DocParseResult
from services.workflows.draft_store import PendingDraft, draft_store
from services.ai.jev_classifier import jev_service
from services.ai.gemini_client import LLMClient, llm_client
from services.knowledge.chat_scopes import scope_service
from services.knowledge.weknora_client import weknora_service
from services.knowledge.context_composer import ContextComposer
from services.knowledge.rule_engine import rule_engine
from services.ai.text_filter import text_filter

logger = logging.getLogger("hilark.chat_service")


def _resolve_dep(name: str, default_val: Any) -> Any:
    shim = sys.modules.get("services.chat_service")
    if shim and hasattr(shim, name):
        val = getattr(shim, name)
        if val is not default_val:
            return val
    return default_val


def _get_lark_service():
    shim = sys.modules.get("services.chat_service")
    if shim and hasattr(shim, "lark_service"):
        return shim.lark_service
    from services.lark import lark_service
    return lark_service


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
5. TUYỆT ĐỐI CẤM ĐỊNH DẠNG MARKDOWN (.md) VÀ LỜI CHÀO MỞ ĐẦU:
   - KHÔNG dùng markdown (.md): CẤM in đậm (**), in nghiêng (*), gạch đầu dòng danh sách (*, -, +), tiêu đề (#, ##).
   - Toàn bộ câu trả lời là văn bản thuần túy (plain text).
   - KHÔNG mở đầu bằng các lời chào khách sáo ("Chào bạn,", "Xin chào,"). Đi thẳng vào câu trả lời.
6. BẢO TOÀN ĐỊNH DANH DỰ ÁN (TUYỆT ĐỐI CẤM NHẦM TÊN TÀI LIỆU THÀNH TÊN DỰ ÁN):
   - Đọc kỹ PHẦN 0: BỐI CẢNH DỰ ÁN để xác định đúng "Tên nhóm chat" hoặc "Dự án phụ trách". Đó là tên chính thức duy nhất của dự án (ví dụ: "Project Atlas").
   - TUYỆT ĐỐI CẤM lấy tên của các file tài liệu đính kèm (như "04_So_tay_chinh_sach_cong_ty.pdf", "Ngan_sach_du_an.xlsx", "Code_of_Conduct.docx") để gán nhầm làm tên dự án! Các file này chỉ là tài liệu tham khảo nội bộ.
7. BẢO TOÀN PHÂN CÔNG NHÂN SỰ DỰ ÁN (TUYỆT ĐỐI CẤM GÁN SAI HOẶC BỊA ĐẶT NGƯỜI QUẢN LÝ):
   - Khi được hỏi ai là Quản lý dự án (PM), Tech Lead hay người phụ trách, BẮT BUỘC phải tra cứu tài liệu/tri thức để nêu đúng tên người được phân công (ví dụ: Hoàng Minh Tuấn là Quản lý dự án).
   - Tuyệt đối không nhầm lẫn giữa Lãnh đạo cấp cao của công ty với Quản lý dự án cụ thể.
"""

GROUNDED_QA_USER_PERSONA_PROMPT = """Bạn là {responder_name} ({role}).
Bạn đang trực tiếp trả lời tin nhắn trên Lark cho thành viên/đồng nghiệp: {user_name}.
Tin nhắn gửi đi nhân danh tài khoản cá nhân của bạn (User Identity). Bạn là Lãnh đạo cấp cao / Chủ quản chung của doanh nghiệp, có phong cách điều hành quyết đoán, điềm tĩnh, tôn trọng và đồng hành cùng đội ngũ.

=== BỘ BỐI CẢNH TRI THỨC (KNOWLEDGE CONTEXT) ===
{context_text}

=== CÂU HỎI / TIN NHẮN TỪ {user_name} ===
{query}

=== CÁC NGUYÊN TẮC BẮT BUỘC KHI PHẢN HỒI (CHUẨN 10/10) ===
1. XƯNG HÔ, TONE OF VOICE & ĐỊNH DẠNG TIN NHẮN:
   - TUYỆT ĐỐI CẤM LỜI CHÀO KHÁCH SÁO: Không mở đầu bằng "Chào {user_name},", "Chào em,", "Hi {user_name},", "Xin chào,". Đi thẳng vào nội dung trả lời như đang chat tin nhắn trực tiếp ngoài đời.
   - CHỈ CẦN BIẾT ĐANG REPLY AI: Bạn đang trực tiếp reply tin nhắn của {user_name}. Tự xưng là "anh", gọi người hỏi là "em" hoặc gọi trực tiếp tên "{user_name}" một cách tự nhiên trong ngữ cảnh câu văn (Ví dụ: "{user_name} kiểm tra lại giúp anh...", "Phần này em cứ làm theo quy trình..."). Với nhóm chung thì xưng "mình", gọi "mọi người".
   - TUYỆT ĐỐI CẤM ĐỊNH DẠNG MARKDOWN (.md): KHÔNG dùng cú pháp markdown nào trong tin nhắn!
     * CẤM viết in đậm bằng **nội dung**
     * CẤM viết in nghiêng bằng *nội dung*
     * CẤM dùng các ký tự gạch đầu dòng danh sách (*, -, +)
     * CẤM dùng tiêu đề dấu thăng (#, ##, ###)
     * CẤM dùng bảng biểu, khối code
     * Toàn bộ tin nhắn PHẢI là văn bản thuần túy (plain text), ngắt câu và xuống dòng tự nhiên như người thật đang gõ chat bằng bàn phím trong ứng dụng Lark.
   - TUYỆT ĐỐI CẤM: Không bao giờ viết hoa chữ "Anh" ở giữa câu (chỉ viết hoa khi đứng ở đầu câu). Không dùng từ suồng sã như "Cả nhà", không dùng đại từ xa cách như "anh/chị", "chúng tôi".
   - TUYỆT ĐỐI KHÔNG xưng là AI, chatbot, hay trợ lý ảo. Không viết dạng bài luận. Trả lời ngắn gọn, dứt khoát (ưu tiên 2–4 câu).
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
   - NGUYÊN TẮC THẨM QUYỀN VỀ ĐỀ XUẤT NHÂN SỰ:
     * CHỈ đề cập hoặc phản hồi về Đề xuất nhân sự 💡 [PROPOSED] NẾU câu hỏi / tin nhắn của {user_name} TRỰC TIẾP hỏi hoặc đề cập đến đề xuất, nguyện vọng hoặc vai trò đó (Ví dụ: khi họ hỏi "anh duyệt đề xuất làm lead của em chưa?").
     * Khi đó, hãy giải thích rõ ràng và văn minh: "Đề xuất này của em anh đã ghi nhận nhưng cần cân nhắc thêm trước khi chốt nhé."
     * Nếu {user_name} đang hỏi về chủ đề khác (quy trình nhân sự, nghỉ phép, chính sách, tài liệu, kỹ thuật, việc khác), TUYỆT ĐỐI CẤM tự ý chêm đề xuất làm lead hay vai trò ngoài lề vào câu trả lời!
   - TUYỆT ĐỐI KHÔNG sinh thẻ trích dẫn nguồn lộ liễu (như [Cập nhật hội thoại: ...] hay [Tài liệu: ...]) trong câu trả lời.

7. NGUYÊN TẮC SUY LUẬN BỐI CẢNH DỰ ÁN & ĐỊNH DANH BẤT BIẾN (SCOPE & PROJECT IDENTITY):
   - Bạn đang trả lời trong một nhóm chat dự án cụ thể. Nếu thành viên hỏi các câu hỏi chung chung về dự án (ví dụ: "cho em xin thông tin dự án", "dự án này làm gì", "kế hoạch dự án ra sao", "mục tiêu dự án"), bạn MẶC ĐỊNH hiểu rằng thành viên đang hỏi về dự án của nhóm này (được nêu rõ tại mục "Tên nhóm chat" hoặc "Dự án phụ trách" trong PHẦN 0, ví dụ: "Project Atlas").
   - TUYỆT ĐỐI KHÔNG hỏi ngược lại người dùng những câu như: "em cần thông tin về dự án nào", "anh chưa rõ em hỏi dự án nào". Hãy chủ động cung cấp ngay bức tranh tổng quan/chi tiết của dự án thuộc nhóm này cho người hỏi!
   - NGUYÊN TẮC ĐỊNH DANH BẤT BIẾN (CẤM NHẦM TÊN FILE THÀNH TÊN DỰ ÁN): 
     * Tên dự án chính thức của nhóm là tên ghi trong PHẦN 0 (ví dụ: "Project Atlas").
     * TUYỆT ĐỐI CẤM lấy tên của các file tài liệu đính kèm (như "04_So_tay_chinh_sach_cong_ty.pdf", "Ngan_sach_du_an.xlsx", "Code_of_Conduct.docx") để nói làm tên dự án (Ví dụ: CẤM TUYỆT ĐỐI các câu như: "Dự án mình đang triển khai là 04 Sổ Tay Chính Sách Công Ty"). Các file này chỉ là văn bản chính sách/tham khảo nội bộ!

8. NGUYÊN TẮC PHÂN ĐỊNH RÕ RÀNG VAI TRÒ DỰ ÁN (TUYỆT ĐỐI CẤM TỰ NHẬN LÀM QUẢN LÝ DỰ ÁN / LEAD):
   - BẠN LÀ {responder_name} ({role}): Bạn là Lãnh đạo cấp cao / Chủ quản chung của doanh nghiệp, KHÔNG PHẢI là người phụ trách trực tiếp mọi vị trí chuyên môn cụ thể của từng dự án!
   - KHI THÀNH VIÊN HỎI: "ai làm quản lý", "ai là PM", "ai làm quản lý dự án", "ai phụ trách dự án", "ai lead", "ai phụ trách kỹ thuật":
     * BẮT BUỘC phải tra cứu BỘ BỐI CẢNH TRI THỨC để trả lời chính xác họ tên của nhân sự được phân công vị trí đó (Ví dụ: "Dự án này do anh Hoàng Minh Tuấn làm Quản lý dự án (PM)", "Về phần kỹ thuật do anh Nguyễn Văn Nam đảm nhiệm").
     * TUYỆT ĐỐI CẤM tự nhận mình "đang trực tiếp quản lý", "anh làm quản lý", "anh lead" khi trong tài liệu/tri thức đã ghi rõ người khác đảm nhận vai trò Quản lý dự án (PM) hoặc Người phụ trách!
     * Chỉ nói mình trực tiếp quản lý NẾU trong tài liệu ghi rõ đích danh {responder_name} là Quản lý dự án / PM của dự án đó.
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
    is_owner: bool = False,
    notify_realtime: bool = False,
    tenant_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Helper xử lý trích xuất Entities & Facts và lưu trực tiếp vào MongoDB có gắn scope & tenant_key."""
    eff_tenant = tenant_key or get_current_tenant_key()
    msg_id = f"msg_{uuid.uuid4().hex[:8]}"

    _get_entities = _resolve_dep("get_mongo_entities", get_mongo_entities)
    _get_facts = _resolve_dep("get_mongo_facts", get_mongo_facts)
    _save_extraction = _resolve_dep("save_extraction_to_mongo", save_extraction_to_mongo)

    try:
        existing_entities = await _get_entities(workspace_id=None, tenant_key=eff_tenant)
        existing_facts = await _get_facts(chat_id=chat_id, project_tag=project_tag, tenant_key=eff_tenant)
    except Exception as e:
        logger.error(f"Lỗi khi đọc từ MongoDB: {e}")
        existing_entities = []
        existing_facts = []

    from services.ai.llm_extractor import extract_async

    extraction_result = await extract_async(
        query=query_text,
        workspace_id="default",
        source_message_id=msg_id,
        sender=sender,
        asserted_by=asserted_by,
        existing_entities=existing_entities,
        existing_facts=existing_facts,
    )

    # Phân loại quyền lực tri thức:
    # Nếu không phải do Lãnh đạo phát ngôn -> chuyển toàn bộ facts sang proposed
    is_speaker_owner = is_owner or bool(asserted_by and asserted_by.get("role") == "owner")
    if not is_speaker_owner:
        facts_list = extraction_result.get("facts", []) if isinstance(extraction_result, dict) else getattr(extraction_result, "facts", [])
        for f in facts_list:
            if isinstance(f, dict):
                f["status"] = "proposed"
            elif hasattr(f, "status"):
                f.status = "proposed"

    mongo_saved = await _save_extraction(
        extraction_result,
        chat_id=chat_id,
        project_tag=project_tag,
        scope_type=scope_type,
        tenant_key=eff_tenant,
    )

    new_facts = mongo_saved.get("facts", [])
    if notify_realtime:
        try:
            from services.workflows.claim_workflow import claim_service
            await claim_service.notify_proposed_claims(
                facts=new_facts,
                chat_id=chat_id,
                entities=mongo_saved.get("entities", []),
                message_id=msg_id,
                source_text=query_text,
            )
        except Exception as e:
            logger.warning(f"Lỗi khi gửi thẻ duyệt Claim đề xuất tới lãnh đạo: {e}")

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


async def process_document_to_claims(
    doc_result: DocParseResult,
    chat_id: str,
    sender: str = "User",
    sender_id: Optional[str] = None,
    message_id: Optional[str] = None,
    project_tag: Optional[str] = None,
    scope_type: str = "chat",
    is_owner: bool = False,
    notify_realtime: bool = False,
) -> Dict[str, Any]:
    """
    Tiếp nhận tài liệu đã chuẩn hóa (DocParseResult từ AnyDoc gRPC hoặc Lark OpenAPI)
    và bóc tách thành các Entities & Claims lưu bền vững vào MongoDB (EDL-0010).

    Args:
        doc_result: Kết quả phân giải Markdown sạch từ doc_parser_service.
        chat_id: ID nhóm chat / cuộc hội thoại tiếp nhận tài liệu.
        sender: Tên người gửi / tải lên tài liệu.
        sender_id: ID người gửi (open_id / user_id).
        message_id: ID tin nhắn đính kèm tệp hoặc chứa liên kết.
        project_tag: Nhãn dự án (nếu có).
        scope_type: Loại scope ('chat' mặc định).

    Returns:
        Dict chứa thông tin thống kê: số entities, số claims mới, claims superseded.
    """
    if not doc_result or not doc_result.success:
        return {
            "success": False,
            "error": doc_result.error if doc_result else "DocParseResult rỗng",
            "new_claims_count": 0,
        }

    markdown_text = (doc_result.markdown_content or "").strip()
    if not markdown_text:
        return {
            "success": False,
            "error": f"Tài liệu '{doc_result.doc_name}' không chứa nội dung văn bản sau khi phân giải.",
            "new_claims_count": 0,
        }

    msg_id = message_id or f"doc_{uuid.uuid4().hex[:8]}"

    _get_entities = _resolve_dep("get_mongo_entities", get_mongo_entities)
    _get_facts = _resolve_dep("get_mongo_facts", get_mongo_facts)
    _save_extraction = _resolve_dep("save_extraction_to_mongo", save_extraction_to_mongo)

    try:
        existing_entities = await _get_entities()
        existing_facts = await _get_facts(chat_id=chat_id, project_tag=project_tag)
    except Exception as e:
        logger.error(f"Lỗi khi đọc từ MongoDB: {e}")
        existing_entities = []
        existing_facts = []

    from services.ai.llm_extractor import extract_async

    asserted_by = {
        "user_id": sender_id or "",
        "user_name": sender or "User",
        "channel": "document_upload",
        "source_type": doc_result.source_type,
        "doc_name": doc_result.doc_name,
    }

    extraction_result = await extract_async(
        query=markdown_text,
        workspace_id=chat_id or "default",
        source_message_id=msg_id,
        sender=sender,
        asserted_by=asserted_by,
        existing_entities=existing_entities,
        existing_facts=existing_facts,
    )

    # Đính kèm metadata nguồn tài liệu vào từng fact & phân loại quyền hạn:
    # Tài liệu từ thành viên -> status: proposed (gom duyệt cuối ngày trên Thẻ Digest).
    # Tài liệu do Lãnh đạo gửi (is_owner=True) -> status: current (hiệu lực ngay).
    facts_list = extraction_result.get("facts", []) if isinstance(extraction_result, dict) else getattr(extraction_result, "facts", [])
    for fact in facts_list:
        if isinstance(fact, dict):
            fact["source_doc"] = doc_result.doc_name
            fact["source_type"] = doc_result.source_type
            if not is_owner:
                fact["status"] = "proposed"
            if doc_result.metadata.get("document_id"):
                fact["document_id"] = doc_result.metadata["document_id"]
            elif doc_result.metadata.get("file_key"):
                fact["file_key"] = doc_result.metadata["file_key"]

    mongo_saved = await _save_extraction(
        extraction_result,
        chat_id=chat_id,
        project_tag=project_tag,
        scope_type=scope_type,
    )

    new_facts = mongo_saved.get("facts", [])
    superseded = mongo_saved.get("superseded_facts", [])
    entities = mongo_saved.get("entities", [])
    total_entities = mongo_saved.get("total_stored_entities", 0)
    total_facts = mongo_saved.get("total_stored_facts", 0)

    if notify_realtime:
        try:
            from services.workflows.claim_workflow import claim_service
            await claim_service.notify_proposed_claims(
                facts=new_facts,
                chat_id=chat_id,
                chat_title=doc_result.doc_name,
                entities=entities,
                message_id=msg_id,
                source_text=f"Trích xuất từ tài liệu {doc_result.doc_name}",
            )
        except Exception as e:
            logger.warning(f"Lỗi khi gửi thẻ duyệt Claim đề xuất từ tài liệu tới lãnh đạo: {e}")

    logger.info(
        f"✔ [DOC CLAIMS PIPELINE] Tiếp thu thành công tài liệu '{doc_result.doc_name}': "
        f"+{len(new_facts)} facts/claims mới, {len(superseded)} facts bị thay thế."
    )

    return {
        "success": True,
        "doc_name": doc_result.doc_name,
        "source_type": doc_result.source_type,
        "message_id": msg_id,
        "entities": entities,
        "facts": new_facts,
        "superseded_facts": superseded,
        "new_claims_count": len(new_facts),
        "superseded_claims_count": len(superseded),
        "total_stored_entities": total_entities,
        "total_stored_facts": total_facts,
        "saved_to_mongodb": True,
        # Backward compatibility aliases
        "memory": entities,
        "claims": new_facts,
        "superseded_claims": superseded,
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
    tenant_key: Optional[str] = None,
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
    eff_tenant = tenant_key or get_current_tenant_key()
    _jev = _resolve_dep("jev_service", jev_service)
    _weknora = _resolve_dep("weknora_service", weknora_service)
    _scope = _resolve_dep("scope_service", scope_service)
    _draft_store = _resolve_dep("draft_store", draft_store)
    _lark = _resolve_dep("lark_service", _get_lark_service())
    _Composer = _resolve_dep("ContextComposer", ContextComposer)
    _process_memory = _resolve_dep("process_memory_extraction", process_memory_extraction)
    _generate_answer = _resolve_dep("generate_grounded_answer", generate_grounded_answer)
    _get_facts = _resolve_dep("get_mongo_facts", get_mongo_facts)
    _get_entities = _resolve_dep("get_mongo_entities", get_mongo_entities)

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
            from services.workflows.digest_workflow import digest_service
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
            scope_record = await _scope.get_scope_by_chat_id(chat_id, tenant_key=eff_tenant)
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
            forbidden_res = await _jev.check_forbidden_query(
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
                        await _lark.send_bot_dm_to_owner(alert_text)
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
        jev_result = await _jev.classify_message(clean_query)
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
        extraction_data = await _process_memory(
            query_text=clean_query,
            sender=sender,
            asserted_by=asserted_by,
            chat_id=chat_id,
            project_tag=proj_context_name,
            scope_type="chat" if chat_id else "global",
            is_owner=is_owner,
            tenant_key=eff_tenant,
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
        facts_coro = _get_facts(
            chat_id=chat_id,
            project_tag=proj_context_name,
            tenant_key=eff_tenant,
        )
        entities_coro = _get_entities(workspace_id=None, tenant_key=eff_tenant)
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

    # ── [DOMAIN SEPARATION GATE & CHAT SCOPE CURRENT-ONLY CLAIMS] ──
    # 1. Nếu câu hỏi là Chính sách toàn công ty (COMPANY_POLICY), cấm hoàn toàn nạp Project Claims
    if jev_domain == "COMPANY_POLICY":
        logger.info(f"🏛️ [Domain Separation] Câu hỏi Chính sách công ty -> Cấm nạp Project Claims ({len(all_facts)} facts bị loại bỏ).")
        active_claims = [f for f in all_facts if f.get("scope_type") == "global" and f.get("is_policy")]
    else:
        # 2. Với câu hỏi Dự án: CHỈ nạp các facts hiện hành đã được phê duyệt chính thức (status == 'current').
        # Tuyệt đối cấm nạp PROPOSED vào Chat Q&A để chống nói leo và rò rỉ đề xuất chưa duyệt.
        # Đồng thời kiểm soát nghiêm ngặt Chat Scope: Chỉ nạp facts của đúng chat_id / project_tag / global.
        active_claims = [
            f for f in all_facts
            if f.get("status", "current") == "current"
            and (
                f.get("scope_type") == "global"
                or (chat_id and f.get("chat_id") == chat_id)
                or (proj_context_name and f.get("project_tag") == proj_context_name)
                or (not f.get("chat_id") and not f.get("project_tag"))
            )
        ]

    # 2. Truy xuất các đoạn văn bản (chunks) từ WeKnora Knowledge Base theo phân quyền nhóm chat & Two-Tier Routing
    chunks = []
    try:
        if not scope_record and chat_id:
            scope_record = await _scope.get_scope_by_chat_id(chat_id, tenant_key=eff_tenant)

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
            if not any(kw in proj_context_name.lower() for kw in ("knowledge base", "lark base", "mặc định", "default")):
                retrieval_query = f"{clean_query} {proj_context_name}"

        # ── [RAG TWO-TIER PIGGYBACK ROUTING] ──
        # Pessimistic Threshold: Chỉ khi confidence >= 0.85 mới định tuyến đơn kho, còn lại fallback HYBRID song song
        policy_keywords = [
            "chính sách", "quy định", "nội quy", "sổ tay", "nghỉ phép", "bảo hiểm",
            "chế độ", "phúc lợi", "thưởng tết", "lương tháng 13", "quy tắc ứng xử",
            "code of conduct", "policy", "handbook", "văn hóa công ty"
        ]
        is_explicit_policy_query = (
            jev_domain == "COMPANY_POLICY"
            or any(kw in clean_query.lower() for kw in policy_keywords)
        )

        if jev_domain == "COMPANY_POLICY" and global_policy_kbs:
            logger.info(
                f"🏛️ [RAG Routing] Định tuyến đơn kho -> Global Policy KBs ({global_policy_kbs}) | Confidence: {jev_domain_conf:.2f}"
            )
            chunks = await _weknora.retrieve(
                query=clean_query,
                knowledge_base_ids=global_policy_kbs,
                knowledge_ids=None,
                match_count=retrieve_count,
            )
        elif jev_domain == "PROJECT" and project_dataset_id:
            logger.info(
                f"📁 [RAG Routing] Định tuyến đơn kho -> Project Scoped KB ({project_dataset_id}) | Confidence: {jev_domain_conf:.2f}"
            )
            chunks = await _weknora.retrieve(
                query=retrieval_query,
                knowledge_base_ids=[project_dataset_id],
                knowledge_ids=target_knowledge_ids,
                match_count=retrieve_count,
            )
            # Fallback an toàn: Nếu tìm theo target_knowledge_ids trả về 0 chunks (do stale ID), quét dataset và để Strict Isolation lọc theo tên file
            if not chunks and target_knowledge_ids:
                logger.info(f"🔄 [RAG Fallback] Retrieve theo target_knowledge_ids trả về 0 -> Fallback quét project dataset {project_dataset_id}...")
                chunks = await _weknora.retrieve(
                    query=retrieval_query,
                    knowledge_base_ids=[project_dataset_id],
                    knowledge_ids=None,
                    match_count=retrieve_count,
                )
        else:
            # HYBRID MODE hoặc Phân vân (Confidence < 0.85): Truy vấn song song cả kho dự án và kho chính sách
            if project_dataset_id and global_policy_kbs:
                logger.info(
                    f"🔀 [RAG Routing] Kích hoạt HYBRID parallel search (Project: {project_dataset_id}, Policy KBs: {global_policy_kbs})"
                )
                tasks = [
                    _weknora.retrieve(
                        query=retrieval_query,
                        knowledge_base_ids=[project_dataset_id],
                        knowledge_ids=target_knowledge_ids,
                        match_count=retrieve_count,
                    ),
                    _weknora.retrieve(
                        query=clean_query,
                        knowledge_base_ids=global_policy_kbs,
                        knowledge_ids=None,
                        match_count=retrieve_count,
                    ),
                ]
                res_proj, res_policy = await asyncio.gather(*tasks, return_exceptions=True)
                chunks_proj = res_proj if isinstance(res_proj, list) else []
                # Fallback kho dự án nếu target_knowledge_ids bị 0 chunks
                if not chunks_proj and target_knowledge_ids:
                    logger.info(f"🔄 [RAG Fallback Hybrid] Kho dự án trả về 0 với target_knowledge_ids -> Quét project dataset...")
                    fb_res = await _weknora.retrieve(
                        query=retrieval_query,
                        knowledge_base_ids=[project_dataset_id],
                        knowledge_ids=None,
                        match_count=retrieve_count,
                    )
                    chunks_proj = fb_res if isinstance(fb_res, list) else []
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
                chunks = await _weknora.retrieve(
                    query=retrieval_query,
                    knowledge_base_ids=[project_dataset_id],
                    knowledge_ids=target_knowledge_ids,
                    match_count=retrieve_count,
                )
                if not chunks and target_knowledge_ids:
                    chunks = await _weknora.retrieve(
                        query=retrieval_query,
                        knowledge_base_ids=[project_dataset_id],
                        knowledge_ids=None,
                        match_count=retrieve_count,
                    )
            elif global_policy_kbs:
                chunks = await _weknora.retrieve(
                    query=clean_query,
                    knowledge_base_ids=global_policy_kbs,
                    knowledge_ids=None,
                    match_count=retrieve_count,
                )
    except Exception as e:
        logger.warning(f"Lỗi WeKnora retrieve: {e}")

    # ── [CHỐT CHẶN BẢO MẬT: STRICT DOCUMENT SCOPE & DATA ISOLATION] ──
    # Nhóm chat chỉ được phép nhìn thấy tài liệu được cấu hình cho chính nhóm đó trên Lark Base!
    # Lọc bỏ 100% các chunks từ tài liệu khác / dự án khác lọt vào từ dataset dùng chung.
    allowed_doc_names = set()
    if scope_record:
        if hasattr(scope_record, "get_document_names"):
            for dn in scope_record.get_document_names():
                if dn and str(dn).strip():
                    allowed_doc_names.add(str(dn).strip().lower())
        if scope_record.documents:
            for d in scope_record.documents:
                if isinstance(d, dict) and d.get("name"):
                    allowed_doc_names.add(str(d["name"]).strip().lower())
                elif isinstance(d, str) and d.strip():
                    allowed_doc_names.add(d.strip().lower())

    allowed_kids = set(str(kid).strip() for kid in (target_knowledge_ids or []) if str(kid).strip())

    # Chuẩn hóa chunks cho ContextComposer và Rule Engine
    normalized_chunks = []
    for c in chunks:
        doc_name = (
            c.get("knowledge_title")
            or c.get("document_name")
            or "Tài liệu hệ thống"
        )
        chunk_kid = str(c.get("knowledge_id") or "").strip()
        kb_id = str(c.get("knowledge_base_id") or "")
        is_policy_doc = (
            kb_id == str(settings.WEKNORA_POLICY_DATASET_ID)
            or any(
                kw in doc_name.lower()
                for kw in ["so_tay", "chinh_sach", "quy_che", "quy_tac", "employee_handbook", "code_of_conduct", "policy", "handbook"]
            )
        )

        # STRICT ISOLATION FILTER:
        # Nếu đây là tài liệu dự án và nhóm có cấu hình tài liệu cụ thể:
        if not is_policy_doc and (allowed_kids or allowed_doc_names):
            if chunk_kid and allowed_kids:
                kid_match = chunk_kid in allowed_kids
                name_match = any(
                    (ad in doc_name.lower() or doc_name.lower() in ad)
                    for ad in allowed_doc_names
                ) if allowed_doc_names else False

                if not kid_match and not name_match:
                    cid = c.get("id") or c.get("chunk_id") or "unknown"
                    logger.warning(
                        f"🚫 [DOCUMENT ISOLATION DROP] Chunk '{cid}' từ '{doc_name}' (kid={chunk_kid}) "
                        f"bị loại bỏ vì không thuộc phạm vi tài liệu được cấu hình của nhóm '{scope_record.chat_name if scope_record else chat_id}'."
                    )
                    continue
            elif allowed_doc_names and not chunk_kid:
                name_match = any(
                    (ad in doc_name.lower() or doc_name.lower() in ad)
                    for ad in allowed_doc_names
                )
                if not name_match:
                    cid = c.get("id") or c.get("chunk_id") or "unknown"
                    logger.warning(
                        f"🚫 [DOCUMENT ISOLATION DROP] Chunk '{cid}' từ '{doc_name}' "
                        f"bị loại bỏ vì không khớp danh mục tài liệu của nhóm."
                    )
                    continue

        normalized_chunks.append({
            "content": c.get("content", ""),
            "document_name": doc_name,
            "chunk_id": c.get("id") or c.get("chunk_id"),
            "score": c.get("score"),
            "is_policy_doc": is_policy_doc,
            "knowledge_base_id": kb_id,
            "knowledge_id": chunk_kid,
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
    # Hợp nhất: Nếu câu hỏi hỏi về chính sách toàn công ty thì nạp policy_chunks
    # Nếu câu hỏi là về dự án, ưu tiên 100% clean_proj_chunks để tránh nhiễm bẩn tài liệu văn hóa / review code
    if is_explicit_policy_query:
        clean_chunks = [c for c in policy_chunks if len(str(c.get("content", "")).strip()) >= 3] + clean_proj_chunks
    elif clean_proj_chunks:
        clean_chunks = clean_proj_chunks
    else:
        clean_chunks = clean_proj_chunks or [c for c in policy_chunks if len(str(c.get("content", "")).strip()) >= 3]

    # ── [RAG GATE RELEVANCE FILTERING] ──
    # Lọc ngữ nghĩa thông minh qua JEV (1 Call duy nhất) trên các chunks đã được khử trùng
    if clean_chunks and len(clean_chunks) > 1:
        try:
            proj_ctx = proj_context_name or (scope_record.dataset_name if scope_record else None) or (scope_record.chat_name if scope_record else None)
            clean_chunks = await _jev.filter_chunks_relevance(
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

    composer = _Composer()
    composed = composer.compose(
        retriever_data=clean_chunks if clean_chunks else None,
        claims_data=clean_claims if clean_claims else None,
        query=clean_query,
        entity_map=entity_map,
        auto_align=True,
        scope_context=scope_ctx_data,
    )

    # 4. Sinh câu trả lời Grounded QA từ Gemini (có hỗ trợ xưng hô đích danh & BYOK Key Resolver)
    effective_api_key = None
    try:
        from services.user_settings_service import user_settings_service
        effective_api_key = await user_settings_service.resolve_effective_llm_key(user_id=sender, chat_id=chat_id)
    except Exception as key_err:
        logger.debug(f"Không thể resolve BYOK key: {key_err}")

    target_user = user_name or (sender if sender and sender not in ("User", "api", "system") else None)
    answer = await _generate_answer(
        query=clean_query,
        context_text=composed.get("context_text", ""),
        user_name=target_user,
        responder_name=responder_name,
        role=role,
        api_key=effective_api_key,
    )

    # Fallback WeKnora chat nếu LLM answer trống
    if not answer:
        try:
            fallback = await _weknora.get_chat_response(ChatRequest(query=clean_query))
            if isinstance(fallback, dict) and "answer" in fallback:
                answer = fallback["answer"]
        except Exception as e:
            logger.warning(f"Fallback WeKnora chat thất bại: {e}")

    # Làm sạch đầu ra
    answer = text_filter.clean_output(answer) if answer else "Hệ thống chưa tìm thấy thông tin phù hợp trong cơ sở tri thức để trả lời câu hỏi của bạn."

    # TH5: DRAFT_PENDING_APPROVAL - Soạn nháp chờ duyệt (Câu hỏi có dữ liệu nhưng có rủi ro)
    if jev_action in ("DRAFT_PENDING_APPROVAL", "MEMORY_AND_DRAFT"):
        dm_notice = None

        owner_open_id = getattr(_lark, "owner_open_id", None)
        if not owner_open_id and hasattr(_lark, "get_current_user"):
            try:
                curr_user = _lark.get_current_user()
                if isinstance(curr_user, dict):
                    owner_open_id = curr_user.get("open_id") or curr_user.get("user_id")
            except Exception:
                pass
        if not owner_open_id:
            raise RuntimeError("Thiếu LARK_USER_OPEN_ID để lưu draft chờ duyệt.")

        await _draft_store.create(
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
            from services.lark.card_builder import build_draft_card

            sec_lvl = "Tuyệt mật" if is_confidential_group else (scope_record.security_level if scope_record else "Tiêu chuẩn")
            chat_title = scope_record.chat_name if scope_record else (chat_id or "Nhóm thảo luận")
            reason_text = (
                "Nhóm thuộc mức độ bảo mật cao. Toàn bộ câu trả lời cần được duyệt trước khi gửi vào nhóm."
                if is_confidential_group
                else "Câu hỏi có dữ liệu trong kho tri thức nhưng thuộc nhóm cần thẩm định trước khi trả lời."
            )

            draft_card_payload = build_draft_card(
                draft_id=message_id or "",
                chat_title=chat_title,
                user_name=user_name or "bạn",
                query=clean_query,
                draft_answer=answer,
                reason=reason_text,
                is_confidential=is_confidential_group,
                security_level=sec_lvl,
            )

            try:
                dm_notice = await _lark.send_bot_dm_to_owner(draft_card_payload)
                logger.info(f"Đã lưu bản nháp vào cơ sở dữ liệu và gửi thẻ phê duyệt tới lãnh đạo (Message ID: {message_id})")
            except Exception as e:
                logger.error(f"Lỗi gửi bản nháp cho lãnh đạo: {e}")
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
            lark_reply_result = await _lark.areply_text(
                message_id=message_id,
                text=answer,
                as_user=True,
            )
            if isinstance(lark_reply_result, dict) and lark_reply_result.get("success"):
                reply_data = lark_reply_result.get("data")
                bot_msg_id = getattr(reply_data, "message_id", None) if reply_data else None
                if not bot_msg_id and isinstance(reply_data, dict):
                    bot_msg_id = reply_data.get("message_id")
                if bot_msg_id:
                    try:
                        from database.db import save_bot_reply_to_staging
                        await save_bot_reply_to_staging(message_id, bot_msg_id)
                    except Exception as stg_err:
                        logger.debug(f"Không thể lưu bot_reply_message_id vào staging: {stg_err}")
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
    process_document = staticmethod(process_document_to_claims)


chat_service = ChatService()


def __getattr__(name: str):
    if name == "lark_service":
        return _get_lark_service()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "ChatService",
    "chat_service",
    "process_chat_pipeline",
    "process_document_to_claims",
    "process_memory_extraction",
    "generate_grounded_answer",
    "GLOBAL_LLM_SEMAPHORE",
    "ContextComposer",
    "draft_store",
    "jev_service",
    "lark_service",
    "weknora_service",
    "rule_engine",
    "scope_service",
    "llm_client",
]

