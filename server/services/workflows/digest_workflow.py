"""
HiLark - Daily Digest Service
==============================
Vị trí: server/services/digest_service.py

Xử lý toàn bộ logic nghiệp vụ:
  1. Tiếp nhận và lưu tin nhắn vào vùng đệm MongoDB Staging trong ngày.
  2. Tổng hợp định kỳ / cuối ngày bằng LLM (Gemini) để bóc tách 3 nhóm tri thức:
     - Quyết định (Decisions)
     - Cam kết (Commitments: ai hứa gì, hạn nào)
     - Thay đổi trạng thái (Status Changes: tiến độ, mốc, blocker)
     - Gắn thông tin truy vết: link tin gốc (Lark applink), người nói, thời điểm
  3. Lưu bản ghi DailyDigestRecord vào MongoDB.
  4. Đồng bộ đẩy bản Markdown sang kho tri thức WeKnora để phục vụ RAG.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
import sys
import uuid
from typing import Any, Dict, List, Optional

import httpx

from core.config import settings
from services.ai.gemini_client import LLMClient, llm_client
from database.db import (
    get_staging_collection,
    get_daily_digests_collection,
    get_master_daily_digests_collection,
)
from models.digest import (
    CommitmentItem,
    DailyDigestRecord,
    DecisionItem,
    MasterDailyDigestRecord,
    SourceReference,
    StagingMessage,
    StatusCategory,
    StatusChangeItem,
)
from models.memory import get_vietnam_now_iso
from services.knowledge.weknora_client import weknora_service
from services.workflows.digest_formatters import build_lark_message_link, get_current_digest_date

logger = logging.getLogger("hilark.digest")
logger.setLevel(logging.INFO)


def _get_staging_coll():
    shim = sys.modules.get("services.digest_service")
    if shim and hasattr(shim, "get_staging_collection"):
        return shim.get_staging_collection()
    return get_staging_collection()


def _get_daily_digests_coll():
    shim = sys.modules.get("services.digest_service")
    if shim and hasattr(shim, "get_daily_digests_collection"):
        return shim.get_daily_digests_collection()
    return get_daily_digests_collection()


def _get_master_daily_digests_coll():
    shim = sys.modules.get("services.digest_service")
    if shim and hasattr(shim, "get_master_daily_digests_collection"):
        return shim.get_master_daily_digests_collection()
    return get_master_daily_digests_collection()


def _get_weknora_service():
    shim = sys.modules.get("services.digest_service")
    if shim and hasattr(shim, "weknora_service"):
        return shim.weknora_service
    return weknora_service


EXTRACTION_SYSTEM_PROMPT = """\
Bạn là chuyên gia phân tích hội thoại doanh nghiệp và trích xuất tri thức (Enterprise Knowledge Extraction Specialist).
Nhiệm vụ của bạn là đọc các tin nhắn trao đổi trong ngày từ Lark của nhóm làm việc và trích xuất thành 3 DANH MỤC TRI THỨC CỐT LÕI:

1. QUYẾT ĐỊNH (Decisions):
   - Các phương án kỹ thuật, chính sách, quy chế, hoặc thỏa thuận đã được chốt/thống nhất.
   - Bỏ qua các ý kiến đang tranh luận dở dang chưa chốt.

2. CAM KẾT (Commitments & Promises):
   - Ai hứa làm gì, hạn chót (deadline) khi nào, hứa với ai.
   - Ví dụ: "Nam hứa tối thứ 5 nộp báo cáo", "Tuấn cam kết fix bug thanh toán trước 17h".

3. THAY ĐỔI TRẠNG THÁI (Status Changes):
   - category: 
     * "progress": Tiến độ công việc (VD: Đã test xong 80%).
     * "milestone": Đạt được cột mốc hoặc dời mốc quan trọng (VD: Hoàn thành đợt deploy Sprint 2).
     * "blocker": Điểm nghẽn, vướng mắc, rủi ro làm đình trệ công việc (VD: Bị nghẽn do chờ API ngân hàng, thiếu server).

QUY TẮC BẮT BUỘC VỀ TRUY VẾT (PROVENANCE):
- Mỗi mục trích xuất (quyết định, cam kết, thay đổi trạng thái) BẮT BUỘC PHẢI CÓ nguồn tin:
  * message_id: ID tin nhắn phát sinh (lấy từ dữ liệu input).
  * speaker_name: Tên người nói.
  * timestamp: Thời điểm phát ngôn.
  * quote: Trích dẫn câu nói gốc chứa ngữ cảnh.

ĐỊNH DẠNG ĐẦU RA BẮT BUỘC:
Trả về DUY NHẤT một JSON Object hợp lệ (không kèm markdown ```json bọc ngoài):
{
  "overview_summary": "1-2 câu tóm tắt toàn cảnh ngày hôm nay",
  "decisions": [
    {
      "id": "dec_01",
      "title": "Tên ngắn gọn quyết định",
      "content": "Nội dung chi tiết quyết định",
      "scope": "Phạm vi áp dụng (nếu có)",
      "message_id": "om_xxx",
      "speaker_name": "Tên người chốt",
      "timestamp": "HH:mm DD/MM/YYYY",
      "quote": "Trích dẫn câu chốt gốc"
    }
  ],
  "commitments": [
    {
      "id": "cmt_01",
      "promiser_name": "Tên người hứa",
      "task": "Nội dung việc cam kết làm",
      "deadline": "Hạn chót cụ thể",
      "recipient_name": "Hứa với ai (nếu rõ)",
      "message_id": "om_xxx",
      "speaker_name": "Tên người hứa",
      "timestamp": "HH:mm DD/MM/YYYY",
      "quote": "Trích dẫn câu hứa gốc"
    }
  ],
  "status_changes": [
    {
      "id": "stc_01",
      "category": "progress / milestone / blocker",
      "target_object": "Đối tượng/Tính năng/Module",
      "summary": "Tóm tắt thay đổi",
      "previous_state": "Trạng thái trước đó (nếu có)",
      "new_state": "Trạng thái mới",
      "blocker_reason": "Lý do nghẽn và ai cần tháo gỡ (nếu category là blocker)",
      "message_id": "om_xxx",
      "speaker_name": "Tên người báo cáo",
      "timestamp": "HH:mm DD/MM/YYYY",
      "quote": "Trích dẫn câu báo cáo gốc"
    }
  ]
}
"""


class DigestService:
    """Service điều phối toàn bộ chu trình Staging -> Digest Extraction -> WeKnora Sync."""

    def __init__(self, gemini_api_key: Optional[str] = None):
        self.api_key = gemini_api_key or settings.GEMINI_API_KEY or settings.gemini_api
        self.llm_client = LLMClient(api_key=self.api_key)
        self.fallback_models = self.llm_client.default_models

    # -------------------------------------------------------------------------
    # 1. QUẢN LÝ VÙNG ĐỆM STAGING (MONGODB)
    # -------------------------------------------------------------------------

    async def add_staging_message(
        self,
        message_id: str,
        chat_id: str,
        text: str,
        speaker_name: str = "",
        speaker_id: str = "",
        chat_name: str = "",
        timestamp: Optional[str] = None,
        project_tag: Optional[str] = None,
    ) -> StagingMessage:
        """Lưu một tin nhắn hợp lệ vào vùng đệm Staging của MongoDB trong ngày."""
        staging_item = StagingMessage(
            id=f"stg_{uuid.uuid4().hex[:12]}",
            message_id=message_id,
            chat_id=chat_id,
            chat_name=chat_name,
            speaker_name=speaker_name or "Thành viên",
            speaker_id=speaker_id,
            text=text.strip(),
            timestamp=timestamp or get_vietnam_now_iso(),
            message_link=build_lark_message_link(message_id),
            project_tag=project_tag,
            processed=False,
        )

        try:
            coll = _get_staging_coll()
            await coll.update_one(
                {"message_id": message_id},
                {"$set": staging_item.to_dict()},
                upsert=True,
            )
            logger.info(f"Đã lưu staging tin nhắn: {message_id} ({chat_id})")
        except Exception as e:
            logger.error(f"Lỗi khi lưu staging vào MongoDB: {e}", exc_info=True)

        return staging_item

    async def get_staging_messages(
        self,
        chat_id: str,
        date: Optional[str] = None,
        unprocessed_only: bool = False,
    ) -> List[StagingMessage]:
        """Lấy danh sách tin nhắn staging của một cuộc trò chuyện trong ngày."""
        target_date = date or get_current_digest_date()
        query: Dict[str, Any] = {
            "chat_id": chat_id,
            "timestamp": {"$regex": f"^{target_date}"},
        }
        if unprocessed_only:
            query["processed"] = False

        try:
            coll = _get_staging_coll()
            cursor = coll.find(query).sort("timestamp", 1)
            docs = await cursor.to_list(length=1000)
            return [StagingMessage(**d) for d in docs]
        except Exception as e:
            logger.error(f"Lỗi truy vấn staging messages: {e}", exc_info=True)
            return []

    # -------------------------------------------------------------------------
    # 2. TRÍCH XUẤT THÔNG MINH BẰNG LLM
    # -------------------------------------------------------------------------

    async def _call_gemini(self, prompt: str) -> str:
        """Gọi Gemini API thông qua unified llm_client với thinkingBudget: 0."""
        return await self.llm_client.generate_text_async(
            prompt=prompt,
            temperature=0.1,
            max_output_tokens=4096,
            thinking_budget=0,
        )


    async def get_claims_for_digest(
        self,
        chat_id: str,
        date: Optional[str] = None,
        project_tag: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Truy vấn các Claims / Mệnh đề trong MongoDB collection 'claims' liên quan đến nhóm:
          - Lọc theo chat_id hoặc project_tag.
          - Lấy cả các trạng thái 'current', 'proposed', 'conflicted', 'superseded'.
        """
        from database.db import get_claims_collection
        try:
            coll = get_claims_collection()
            scope_or: List[Dict[str, Any]] = [{"chat_id": chat_id}]
            if project_tag:
                scope_or.append({"project_tag": project_tag})
            query = {"$or": scope_or}

            cursor = coll.find(query).sort("updated_at", -1)
            raw_claims = await cursor.to_list(length=200)

            clean_claims = []
            for doc in raw_claims:
                c = dict(doc)
                c.pop("_id", None)
                clean_claims.append(c)

            return clean_claims
        except Exception as e:
            logger.error(f"Lỗi khi truy vấn claims cho digest {chat_id}: {e}", exc_info=True)
            return []

    async def get_previous_digest(
        self,
        chat_id: str,
        before_date: Optional[str] = None,
    ) -> Optional[DailyDigestRecord]:
        """
        Truy vấn bản ghi DailyDigestRecord gần nhất trước ngày `before_date` cho một nhóm chat.
        Mục đích: Lấy overview_summary của ngày K-1 làm ngữ cảnh bối cảnh liên tục cho ngày K.
        """
        target_date = before_date or get_current_digest_date()
        try:
            coll = _get_daily_digests_coll()
            res = coll.find_one(
                {
                    "chat_id": chat_id,
                    "date": {"$lt": target_date},
                },
                sort=[("date", -1)],
            )
            doc = await res if inspect.isawaitable(res) else None
            if doc and isinstance(doc, dict):
                return DailyDigestRecord(**doc)
            return None
        except Exception as e:
            logger.debug(f"Không thể tìm previous digest cho {chat_id} trước {target_date}: {e}")
            return None

    async def get_previous_master_digest(
        self,
        before_date: Optional[str] = None,
    ) -> Optional[MasterDailyDigestRecord]:
        """
        Truy vấn bản ghi MasterDailyDigestRecord gần nhất trước ngày `before_date`.
        """
        target_date = before_date or get_current_digest_date()
        try:
            coll = _get_master_daily_digests_coll()
            res = coll.find_one(
                {"date": {"$lt": target_date}},
                sort=[("date", -1)],
            )
            doc = await res if inspect.isawaitable(res) else None
            if doc and isinstance(doc, dict):
                return MasterDailyDigestRecord(**doc)
            return None
        except Exception as e:
            logger.debug(f"Không thể tìm previous master digest trước {target_date}: {e}")
            return None

    async def extract_digest_from_messages(
        self,
        messages: List[StagingMessage],
        chat_id: str,
        chat_name: str = "",
        date: Optional[str] = None,
        project_tag: Optional[str] = None,
        claims: Optional[List[Dict[str, Any]]] = None,
        previous_overview_summary: Optional[str] = None,
        previous_digest_date: Optional[str] = None,
    ) -> DailyDigestRecord:
        """Dùng LLM đọc danh sách tin nhắn và Claims để trích xuất thành đối tượng DailyDigestRecord."""
        target_date = date or get_current_digest_date()
        digest_id = f"digest_{target_date.replace('-', '')}_{chat_id}"

        # Tự động nạp overview_summary của ngày trước (K-1) nếu chưa được chỉ định
        if previous_overview_summary is None:
            prev_digest = await self.get_previous_digest(chat_id=chat_id, before_date=target_date)
            if prev_digest and prev_digest.overview_summary:
                previous_overview_summary = prev_digest.overview_summary.strip()
                previous_digest_date = prev_digest.date

        # Nếu claims chưa được truyền vào, tự động lấy từ MongoDB
        if claims is None:
            claims = await self.get_claims_for_digest(chat_id=chat_id, date=target_date, project_tag=project_tag)

        if not messages and not claims:
            fallback_summary = (
                f"Tiếp nối bối cảnh ngày trước: {previous_overview_summary}. Hôm nay không có trao đổi mới."
                if previous_overview_summary
                else "Không có tin nhắn trao đổi hay cập nhật tri thức nào trong ngày."
            )
            return DailyDigestRecord(
                id=digest_id,
                date=target_date,
                chat_id=chat_id,
                chat_name=chat_name,
                project_tag=project_tag,
                overview_summary=fallback_summary,
                previous_overview_summary=previous_overview_summary,
                previous_digest_date=previous_digest_date,
                claims=[],
            )

        # Định dạng danh sách tin nhắn nạp vào LLM kèm message_id và timestamp
        formatted_msgs = []
        for idx, m in enumerate(messages, 1):
            formatted_msgs.append(
                f"[{idx}] (message_id: {m.message_id}) [{m.timestamp}] {m.speaker_name}: {m.text}"
            )
        msgs_block = "\n".join(formatted_msgs) if formatted_msgs else "(Không có tin nhắn hội thoại trực tiếp)"

        # Định dạng danh sách Claims đã ghi nhận trong MongoDB nạp vào LLM
        claims_block = ""
        if claims:
            formatted_claims = []
            for idx, c in enumerate(claims, 1):
                st = (c.get("status") or "current").upper()
                prop = c.get("property") or ""
                val = c.get("value") or ""
                eid = c.get("entity_id") or ""
                asserted = c.get("asserted_by") or {}
                spk = asserted.get("user_name") or asserted.get("user_id") or "Thành viên"
                formatted_claims.append(f"[{idx}] Entity='{eid}' | [{st}] {prop} = {val} (khẳng định bởi: {spk})")
            claims_block = "\n\nDANH SÁCH MỆNH ĐỀ & SỰ THẬT ĐÃ BÓC TÁCH TRONG NGÀY (MONGODB CLAIMS):\n\"\"\"\n" + "\n".join(formatted_claims) + "\n\"\"\""

        # Định dạng bối cảnh từ ngày trước (K-1)
        prev_summary_block = ""
        if previous_overview_summary:
            p_date = f" ({previous_digest_date})" if previous_digest_date else ""
            prev_summary_block = f"""\
BỐI CẢNH TỔNG QUAN TỪ NGÀY TRƯỚC{p_date} (PREVIOUS OVERVIEW SUMMARY):
\"\"\"
{previous_overview_summary}
\"\"\"

"""

        user_prompt = f"""\
{prev_summary_block}HỘI THOẠI TRONG NGÀY ({target_date}) - NHÓM: {chat_name or chat_id} (Dự án: {project_tag or 'Nội bộ'}):
\"\"\"
{msgs_block}
\"\"\"{claims_block}

Hãy phân tích kết hợp bối cảnh ngày trước (nếu có), tin nhắn hội thoại và danh sách Claims đã bóc tách ở trên để trích xuất:
1. overview_summary: 1-2 câu tóm tắt liên kết liền mạch diễn biến ngày hôm nay (tiếp nối bối cảnh ngày trước và cập nhật tình hình mới nhất hôm nay).
2. Quyết định (Decisions): Các phương án, chính sách đã được chốt/thống nhất trong ngày hôm nay.
3. Cam kết (Commitments: ai hứa gì, hạn nào, với ai).
4. Thay đổi trạng thái (Status Changes: tiến độ, mốc, blocker).
5. ĐẶC BIỆT LƯU Ý: Không bỏ sót các Đề xuất mới từ thành viên (Proposed Claims) hoặc các mâu thuẫn tranh luận dở dang chưa duyệt.
Đảm bảo mỗi mục đều gán đúng message_id, speaker_name, timestamp từ tin nhắn gốc!
"""

        full_prompt = f"{EXTRACTION_SYSTEM_PROMPT}\n\n{user_prompt}"
        raw_response = await self._call_gemini(full_prompt)

        # Làm sạch JSON bọc trong markdown ```json ... ```
        clean_json = raw_response.strip()
        if clean_json.startswith("```"):
            clean_json = re.sub(r"^```(?:json)?\s*", "", clean_json)
            clean_json = re.sub(r"\s*```$", "", clean_json)

        parsed_data: Dict[str, Any] = {}
        try:
            parsed_data = json.loads(clean_json)
        except Exception as e:
            logger.error(f"Lỗi parse JSON từ LLM extraction: {e}\nRaw: {raw_response[:300]}")
            # Fallback nếu parse lỗi
            parsed_data = {"overview_summary": "Tổng hợp trao đổi trong ngày."}

        # Ánh xạ Decisions
        decisions: List[DecisionItem] = []
        for d in parsed_data.get("decisions", []):
            msg_id = d.get("message_id") or (messages[0].message_id if messages else "")
            src = SourceReference.create(
                message_id=msg_id,
                speaker_name=d.get("speaker_name", "Thành viên"),
                timestamp=d.get("timestamp", target_date),
                quote=d.get("quote", ""),
            )
            decisions.append(
                DecisionItem(
                    id=d.get("id") or f"dec_{uuid.uuid4().hex[:6]}",
                    title=d.get("title", "Quyết định"),
                    content=d.get("content", ""),
                    scope=d.get("scope"),
                    source=src,
                )
            )

        # Ánh xạ Commitments
        commitments: List[CommitmentItem] = []
        for c in parsed_data.get("commitments", []):
            msg_id = c.get("message_id") or (messages[0].message_id if messages else "")
            src = SourceReference.create(
                message_id=msg_id,
                speaker_name=c.get("speaker_name", c.get("promiser_name", "Thành viên")),
                timestamp=c.get("timestamp", target_date),
                quote=c.get("quote", ""),
            )
            commitments.append(
                CommitmentItem(
                    id=c.get("id") or f"cmt_{uuid.uuid4().hex[:6]}",
                    promiser_name=c.get("promiser_name", "Thành viên"),
                    task=c.get("task", ""),
                    deadline=c.get("deadline", "Chưa xác định"),
                    recipient_name=c.get("recipient_name"),
                    source=src,
                )
            )

        # Ánh xạ Status Changes
        status_changes: List[StatusChangeItem] = []
        for s in parsed_data.get("status_changes", []):
            msg_id = s.get("message_id") or (messages[0].message_id if messages else "")
            cat_str = str(s.get("category", "progress")).lower()
            cat = (
                StatusCategory.BLOCKER
                if "blocker" in cat_str
                else (StatusCategory.MILESTONE if "milestone" in cat_str else StatusCategory.PROGRESS)
            )
            src = SourceReference.create(
                message_id=msg_id,
                speaker_name=s.get("speaker_name", "Thành viên"),
                timestamp=s.get("timestamp", target_date),
                quote=s.get("quote", ""),
            )
            status_changes.append(
                StatusChangeItem(
                    id=s.get("id") or f"stc_{uuid.uuid4().hex[:6]}",
                    category=cat,
                    target_object=s.get("target_object", "Module"),
                    summary=s.get("summary", ""),
                    previous_state=s.get("previous_state"),
                    new_state=s.get("new_state", "Cập nhật"),
                    blocker_reason=s.get("blocker_reason"),
                    source=src,
                )
            )

        return DailyDigestRecord(
            id=digest_id,
            date=target_date,
            chat_id=chat_id,
            chat_name=chat_name,
            project_tag=project_tag,
            overview_summary=parsed_data.get("overview_summary", ""),
            previous_overview_summary=previous_overview_summary,
            previous_digest_date=previous_digest_date,
            decisions=decisions,
            commitments=commitments,
            status_changes=status_changes,
            claims=claims or [],
            message_count=len(messages),
        )

    # -------------------------------------------------------------------------
    # 3. LƯU MONGODB & ĐỒNG BỘ WEKNORA
    # -------------------------------------------------------------------------

    async def save_digest_to_mongo(self, digest: DailyDigestRecord) -> None:
        """Lưu hoặc cập nhật bản DailyDigestRecord vào MongoDB và đánh dấu staging đã xử lý."""
        try:
            coll = _get_daily_digests_coll()
            await coll.update_one(
                {"id": digest.id},
                {"$set": digest.to_dict()},
                upsert=True,
            )

            # Đánh dấu các tin nhắn staging liên quan trong ngày là đã xử lý
            stg_coll = _get_staging_coll()
            await stg_coll.update_many(
                {
                    "chat_id": digest.chat_id,
                    "timestamp": {"$regex": f"^{digest.date}"},
                },
                {"$set": {"processed": True}},
            )
            logger.info(f"Đã lưu DailyDigest vào MongoDB: {digest.id}")
        except Exception as e:
            logger.error(f"Lỗi khi lưu DailyDigest vào MongoDB: {e}", exc_info=True)

    async def sync_digest_to_weknora(
        self,
        digest: DailyDigestRecord,
        dataset_id: Optional[str] = None,
    ) -> bool:
        """
        Đẩy bản Markdown của DailyDigestRecord lên WeKnora làm tri thức tìm kiếm RAG.
        Cập nhật trạng thái sync_status = 'synced' và weknora_doc_id.
        """
        from services.knowledge.chat_scopes import scope_service

        scoped_wiki_kb = await scope_service.get_wiki_kb_for_chat(digest.chat_id)
        target_kb = dataset_id or digest.weknora_kb_id or scoped_wiki_kb or settings.WEKNORA_WIKI_DATASET_ID or settings.WEKNORA_DATASET_ID
        if target_kb and "," in target_kb:
            target_kb = target_kb.split(",")[0].strip()

        if not target_kb:
            logger.warning("Không tìm thấy wiki_dataset_id để đồng bộ sang WeKnora.")
            digest.sync_status = "failed"
            return False

        md_content = digest.to_weknora_markdown()
        doc_name = f"Wiki_Digest_{digest.date}_{digest.chat_name or digest.chat_id}"

        try:
            resp = await _get_weknora_service().save_to_kb(text=md_content, dataset_id=target_kb, name=doc_name)
            doc_id = ""
            if isinstance(resp, dict):
                doc_id = resp.get("data", {}).get("id") or resp.get("id") or ""

            digest.weknora_kb_id = target_kb
            digest.weknora_doc_id = str(doc_id)
            digest.sync_status = "synced"
            digest.updated_at = get_vietnam_now_iso()

            # Cập nhật lại trạng thái vào MongoDB
            coll = _get_daily_digests_coll()
            await coll.update_one(
                {"id": digest.id},
                {
                    "$set": {
                        "sync_status": "synced",
                        "weknora_kb_id": target_kb,
                        "weknora_doc_id": digest.weknora_doc_id,
                        "updated_at": digest.updated_at,
                    }
                },
            )
            logger.info(f"Đồng bộ DailyDigest lên WeKnora thành công! doc_id={doc_id}")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi đồng bộ DailyDigest lên WeKnora: {e}", exc_info=True)
            digest.sync_status = "failed"
            return False

    async def get_digest_by_id(self, digest_id: str) -> Optional[DailyDigestRecord]:
        """Truy vấn 1 bản ghi DailyDigestRecord từ MongoDB theo ID."""
        try:
            coll = _get_daily_digests_coll()
            doc = await coll.find_one({"id": digest_id})
            if doc:
                return DailyDigestRecord(**doc)
            return None
        except Exception as e:
            logger.error(f"Lỗi khi tìm DailyDigest {digest_id}: {e}", exc_info=True)
            return None



    async def send_approval_request(
        self,
        digest: DailyDigestRecord,
        approver_open_id: Optional[str] = None,
    ) -> bool:
        """
        Gửi tin nhắn thông báo kèm tóm tắt nội dung Daily Digest tới người duyệt qua Lark DM.
        Người duyệt nhận tin nhắn và có thể duyệt bằng lệnh 'Duyệt digest' hoặc 'OK digest'.
        """
        from services.lark import lark_service

        target_approver = (
            approver_open_id
            or settings.DIGEST_APPROVER_ID
            or lark_service.owner_open_id
        )

        summary_lines = [
            "📋 [YÊU CẦU DUYỆT DAILY DIGEST]",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📅 Ngày ghi nhận : {digest.date}",
            f"💬 Nhóm chat     : {digest.chat_name or digest.chat_id}",
            f"🎯 Dự án         : {digest.project_tag or 'Nội bộ'}",
            f"🆔 Mã Digest     : {digest.id}",
            f"✉ Số tin nhắn   : {digest.message_count} | 🧠 Số Claims: {len(digest.claims)}",
            "",
            "🔍 TỔNG QUAN HÔM NAY:",
            f"{digest.overview_summary or 'Chưa có tóm tắt tổng quan.'}",
            "",
            "📊 THỐNG KÊ CHI TIẾT:",
            f"• Quyết định (Decisions) : {len(digest.decisions)} mục",
            f"• Cam kết (Commitments)  : {len(digest.commitments)} mục",
            f"• Trạng thái/Blocker     : {len(digest.status_changes)} mục",
            f"• Mệnh đề/Claims         : {len(digest.claims)} mục",
        ]

        # 0. Đề xuất mới từ thành viên (Proposed Claims)
        proposed_claims = [c for c in digest.claims if (c.get("status") or "").lower() == "proposed"]
        if proposed_claims:
            summary_lines.append("\n💡 ĐỀ XUẤT MỚI TỪ THÀNH VIÊN (PROPOSED CLAIMS):")
            for p in proposed_claims[:3]:
                prop = p.get("property") or "đề xuất"
                val = p.get("value") or ""
                asserted = p.get("asserted_by") or {}
                spk = asserted.get("user_name") or asserted.get("user_id") or "Thành viên"
                summary_lines.append(f"  - {spk} đề xuất: {prop} = {val}")

        if digest.decisions:
            summary_lines.append("\n👉 Quyết định nổi bật:")
            for d in digest.decisions[:3]:
                summary_lines.append(f"  - {d.title} (bởi {d.source.speaker_name})")

        if digest.commitments:
            summary_lines.append("\n👉 Cam kết deadline:")
            for c in digest.commitments[:3]:
                summary_lines.append(f"  - {c.promiser_name}: {c.task} (hạn {c.deadline})")

        blockers = [s for s in digest.status_changes if s.category == StatusCategory.BLOCKER]
        if blockers:
            summary_lines.append("\n🚨 Điểm nghẽn (Blocker):")
            for b in blockers[:3]:
                summary_lines.append(f"  - {b.target_object}: {b.summary}")

        summary_lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "👉 HƯỚNG DẪN DUYỆT ĐẨY LÊN WEKNORA:",
            "• Nhắn 'Duyệt digest' hoặc 'OK digest' để ĐỒNG Ý nạp vào KB.",
            "• Nhắn 'Hủy digest' hoặc 'Bỏ digest' để TỪ CHỐI.",
            "• Nhắn 'Xem digest' để đọc toàn bộ văn bản Markdown chi tiết.",
        ])

        msg_text = "\n".join(summary_lines)

        try:
            if target_approver:
                res = await lark_service.send_bot_dm_to_owner(msg_text, target_open_id=target_approver)
                if not res.get("success"):
                    logger.error(
                        f"❌ [DIGEST APPROVAL] Thất bại khi gửi tin duyệt tới approver: "
                        f"code={res.get('code')}, msg={res.get('msg') or res.get('error')}"
                    )
                    return False
                logger.info(f"✔ [DIGEST APPROVAL] Đã gửi tin nhắn xin duyệt thành công tới approver: {target_approver}")
                return True
            logger.warning("⚠️ [DIGEST APPROVAL] Không có target_approver (chưa cấu hình open_id)")
            return False
        except Exception as e:
            logger.error(f"❌ [DIGEST APPROVAL] Lỗi ngoại lệ khi gửi tin duyệt: {e}", exc_info=True)
            return False

    async def get_latest_pending_approval_digest(self) -> Optional[DailyDigestRecord]:
        """Lấy bản ghi DailyDigest gần nhất đang ở trạng thái chờ duyệt."""
        try:
            coll = _get_daily_digests_coll()
            doc = await coll.find_one(
                {"sync_status": "pending_approval"},
                sort=[("created_at", -1)],
            )
            if doc:
                return DailyDigestRecord(**doc)
            return None
        except Exception as e:
            logger.error(f"Lỗi khi tìm digest pending approval: {e}", exc_info=True)
            return None

    async def approve_and_sync_digest(
        self,
        digest_id: Optional[str] = None,
        dataset_id: Optional[str] = None,
    ) -> tuple[bool, str, Optional[DailyDigestRecord]]:
        """
        Người duyệt đồng ý -> Lấy digest từ MongoDB và đẩy chính thức lên WeKnora KB.
        """
        if digest_id:
            digest = await self.get_digest_by_id(digest_id)
        else:
            digest = await self.get_latest_pending_approval_digest()

        if not digest:
            return False, "Không tìm thấy bản ghi Daily Digest nào đang chờ duyệt.", None

        if digest.sync_status == "synced":
            return True, f"Digest {digest.id} đã được đồng bộ lên WeKnora trước đó.", digest

        success = await self.sync_digest_to_weknora(digest, dataset_id=dataset_id)
        if success:
            try:
                from database.db import promote_proposed_claims_for_chat
                promoted = await promote_proposed_claims_for_chat(
                    chat_id=digest.chat_id,
                    approver_info={"user_name": "Lãnh đạo", "role": "owner"},
                )
                if promoted > 0:
                    logger.info(f"✔ [Digest Approval] Đã tự động thăng hạng {promoted} claims của nhóm {digest.chat_id} thành CURRENT.")
            except Exception as e:
                logger.warning(f"Lỗi khi auto-promote claims theo digest: {e}")
            return True, f"Đã duyệt và nạp thành công Daily Digest ({digest.id}) vào WeKnora KB!", digest
        else:
            return False, f"Duyệt thành công nhưng lỗi khi đẩy lên WeKnora API.", digest

    async def reject_digest(
        self,
        digest_id: Optional[str] = None,
    ) -> tuple[bool, str, Optional[DailyDigestRecord]]:
        """
        Người duyệt từ chối -> Đánh dấu rejected, không đẩy lên WeKnora.
        """
        if digest_id:
            digest = await self.get_digest_by_id(digest_id)
        else:
            digest = await self.get_latest_pending_approval_digest()

        if not digest:
            return False, "Không tìm thấy bản ghi Daily Digest nào đang chờ duyệt.", None

        digest.sync_status = "rejected"
        digest.updated_at = get_vietnam_now_iso()

        coll = _get_daily_digests_coll()
        await coll.update_one(
            {"id": digest.id},
            {"$set": {"sync_status": "rejected", "updated_at": digest.updated_at}},
        )
        return True, f"Đã từ chối bản Daily Digest ({digest.id}). Dữ liệu không được nạp vào KB.", digest

    async def get_active_chat_ids_today(self, date: Optional[str] = None) -> List[str]:
        """Lấy danh sách các nhóm chat có tin nhắn staging trong ngày hôm nay."""
        target_date = date or get_current_digest_date()
        try:
            coll = _get_staging_coll()
            cursor = coll.distinct("chat_id", {"timestamp": {"$regex": f"^{target_date}"}})
            chat_ids = await cursor
            return [str(c) for c in chat_ids if c]
        except Exception as e:
            logger.error(f"Lỗi khi lấy active chat_ids: {e}", exc_info=True)
            return []

    async def _generate_executive_overview(
        self,
        group_digests: List[DailyDigestRecord],
        target_date: str,
        previous_executive_summary: Optional[str] = None,
        previous_master_date: Optional[str] = None,
    ) -> str:
        """Dùng LLM tổng hợp bức tranh toàn cảnh cấp điều hành từ tóm tắt của các nhóm."""
        if not group_digests:
            return "Hôm nay không có hoạt động trao đổi đáng chú ý nào trên các nhóm dự án."

        if previous_executive_summary is None:
            prev_master = await self.get_previous_master_digest(before_date=target_date)
            if prev_master and prev_master.executive_summary:
                previous_executive_summary = prev_master.executive_summary.strip()
                previous_master_date = prev_master.date

        lines = []
        for gd in group_digests:
            grp_name = gd.chat_name or gd.project_tag or gd.chat_id
            summary = gd.overview_summary or "Có trao đổi thông tin"
            dec_cnt = len(gd.decisions)
            cmt_cnt = len(gd.commitments)
            blockers = [s.summary for s in gd.status_changes if s.category == StatusCategory.BLOCKER]
            blocker_str = f", {len(blockers)} blocker: {'; '.join(blockers)}" if blockers else ""
            lines.append(f"- Nhóm '{grp_name}': {summary} ({dec_cnt} quyết định, {cmt_cnt} cam kết{blocker_str})")

        prev_exec_block = ""
        if previous_executive_summary:
            p_date = f" ({previous_master_date})" if previous_master_date else ""
            prev_exec_block = f"Bối cảnh điều hành ngày hôm trước{p_date}:\n\"{previous_executive_summary}\"\n\n"

        prompt = f"""Bạn là Giám đốc Điều hành (COO / Project Director). Hãy viết 1 đoạn văn ngắn (2-3 câu, tối đa 80 từ) tóm tắt bức tranh toàn cảnh cấp điều hành cho ngày {target_date} dựa trên bối cảnh ngày trước (nếu có) và báo cáo từ các nhóm sau:
{prev_exec_block}Báo cáo các nhóm hôm nay:
{chr(10).join(lines)}

Yêu cầu:
- Nêu bật tiến độ chung, các cam kết/mốc quan trọng và các điểm nghẽn (blocker) cần ban lãnh đạo chú ý (nếu có), đảm bảo mạch tiếp nối tự nhiên từ ngày hôm trước.
- Ngắn gọn, súc tích, mang tính chỉ đạo điều hành, không liệt kê máy móc.
- Trả về văn bản thuần túy không dấu ngoặc kép hay markdown header."""
        try:
            res = await self._call_gemini(prompt)
            clean_res = res.strip()
            if clean_res.startswith("```"):
                clean_res = re.sub(r"^```[a-zA-Z]*\s*", "", clean_res)
                clean_res = re.sub(r"\s*```$", "", clean_res)
            return clean_res.strip()
        except Exception as e:
            logger.warning(f"Lỗi khi gọi LLM sinh executive overview: {e}")
            return f"Tổng hợp trao đổi và tiến độ công việc trên {len(group_digests)} nhóm dự án ngày {target_date}."

    async def save_master_digest_to_mongo(self, master_digest: MasterDailyDigestRecord) -> None:
        """Lưu hoặc cập nhật bản MasterDailyDigestRecord vào MongoDB."""
        try:
            coll = _get_master_daily_digests_coll()
            await coll.update_one(
                {"id": master_digest.id},
                {"$set": master_digest.to_dict()},
                upsert=True,
            )
            logger.info(f"Đã lưu MasterDailyDigest vào MongoDB: {master_digest.id}")
        except Exception as e:
            logger.error(f"Lỗi khi lưu MasterDailyDigest vào MongoDB: {e}", exc_info=True)

    async def get_master_digest_by_id(self, master_digest_id: str) -> Optional[MasterDailyDigestRecord]:
        """Truy vấn 1 bản ghi MasterDailyDigestRecord từ MongoDB theo ID."""
        try:
            coll = _get_master_daily_digests_coll()
            doc = await coll.find_one({"id": master_digest_id})
            if doc:
                return MasterDailyDigestRecord(**doc)
            return None
        except Exception as e:
            logger.error(f"Lỗi khi tìm MasterDailyDigest {master_digest_id}: {e}", exc_info=True)
            return None

    async def get_latest_pending_master_digest(self) -> Optional[MasterDailyDigestRecord]:
        """Lấy bản ghi MasterDailyDigest gần nhất đang ở trạng thái chờ duyệt."""
        try:
            coll = _get_master_daily_digests_coll()
            doc = await coll.find_one(
                {"status": "pending_approval"},
                sort=[("created_at", -1)],
            )
            if doc:
                return MasterDailyDigestRecord(**doc)
            return None
        except Exception as e:
            logger.error(f"Lỗi khi tìm master digest pending approval: {e}", exc_info=True)
            return None

    async def send_master_approval_request(
        self,
        master_digest: MasterDailyDigestRecord,
        approver_open_id: Optional[str] = None,
    ) -> bool:
        """Gửi Thẻ tin nhắn tương tác Master Daily Digest tới Chủ nhân để duyệt."""
        from services.lark import lark_service
        from services.lark.card_builder import build_digest_approval_card
        from services.claim_service import claim_service

        target_approver = (
            approver_open_id
            or settings.DIGEST_APPROVER_ID
            or lark_service.owner_open_id
        )

        pending_claims = []
        try:
            pending_claims = await claim_service.get_pending_claims_for_date(
                date_str=getattr(master_digest, "date", None)
            )
        except Exception as e:
            logger.warning(f"Không thể lấy danh sách thông tin đề xuất trong ngày cho digest: {e}")

        card_payload = build_digest_approval_card(master_digest, pending_claims=pending_claims)
        try:
            if target_approver:
                res = await lark_service.send_bot_card_to_owner(card_payload, target_open_id=target_approver)
                if not res.get("success"):
                    logger.error(
                        f"Thất bại khi gửi thẻ duyệt Master Digest: {res.get('msg') or res.get('error')}"
                    )
                    return False
                logger.info(f"Đã gửi thẻ duyệt Master Digest tới {target_approver}")
                return True
            logger.warning("Không tìm thấy target_approver!")
            return False
        except Exception as e:
            logger.error(f"Lỗi gửi thẻ duyệt Master Digest: {e}", exc_info=True)
            return False

    async def generate_master_daily_digest(
        self,
        date: Optional[str] = None,
        require_approval: Optional[bool] = None,
    ) -> MasterDailyDigestRecord:
        """
        Tổng hợp báo cáo ngày cấp điều hành (Master Daily Digest):
          1. Lấy tất cả active chat_ids trong ngày từ staging.
          2. Bóc tách DailyDigestRecord cho từng nhóm chat (Quyết định, Cam kết, Trạng thái/Blocker).
          3. Lưu từng DailyDigestRecord vào MongoDB (đánh dấu staging đã xử lý).
          4. Dùng LLM tổng hợp bức tranh toàn cảnh cấp điều hành (Executive Summary) từ tất cả các nhóm.
          5. Tạo bản ghi MasterDailyDigestRecord, lưu vào MongoDB collection 'master_daily_digests'.
          6. Nếu require_approval=True: Gửi DUY NHẤT 1 tin nhắn DM tới Chủ nhân kèm hướng dẫn duyệt.
          7. Nếu require_approval=False: Tự động duyệt và phân phối đẩy từng group digest vào đúng KB WeKnora tương ứng.
        """
        target_date = date or get_current_digest_date()
        chat_ids = await self.get_active_chat_ids_today(target_date)
        logger.info(f"🏛️ [MASTER DIGEST] Bắt đầu tổng hợp Master Digest cho ngày {target_date} ({len(chat_ids)} nhóm)")

        from services.knowledge.chat_scopes import scope_service

        group_digests: List[DailyDigestRecord] = []
        total_msgs = 0

        for cid in chat_ids:
            try:
                messages = await self.get_staging_messages(chat_id=cid, date=target_date)
                if not messages:
                    continue
                total_msgs += len(messages)
                scope = await scope_service.get_scope_by_chat_id(cid)
                cname = scope.chat_name if scope else (messages[0].chat_name if messages else cid)
                ptag = scope.project_tag if scope else None

                digest = await self.extract_digest_from_messages(
                    messages=messages,
                    chat_id=cid,
                    chat_name=cname,
                    date=target_date,
                    project_tag=ptag,
                )
                scoped_wiki_kb = await scope_service.get_wiki_kb_for_chat(cid)
                digest.weknora_kb_id = scoped_wiki_kb
                digest.sync_status = "pending_approval"
                # Lưu từng digest vào MongoDB và đánh dấu staging đã xử lý
                await self.save_digest_to_mongo(digest)
                group_digests.append(digest)
            except Exception as e:
                logger.error(f"Lỗi khi tổng hợp digest cho nhóm {cid}: {e}", exc_info=True)

        # Lấy thông tin master digest liền trước (nếu có)
        prev_master = await self.get_previous_master_digest(before_date=target_date)
        prev_exec_summary = prev_master.executive_summary.strip() if prev_master and prev_master.executive_summary else None
        prev_master_date = prev_master.date if prev_master else None

        exec_summary = await self._generate_executive_overview(
            group_digests=group_digests,
            target_date=target_date,
            previous_executive_summary=prev_exec_summary,
            previous_master_date=prev_master_date,
        )
        master_id = f"master_digest_{target_date.replace('-', '')}"

        needs_approval = (
            require_approval
            if require_approval is not None
            else settings.DIGEST_REQUIRE_APPROVAL
        )

        master_digest = MasterDailyDigestRecord(
            id=master_id,
            date=target_date,
            executive_summary=exec_summary,
            previous_executive_summary=prev_exec_summary,
            previous_master_date=prev_master_date,
            group_digests=group_digests,
            total_messages=total_msgs,
            total_groups=len(group_digests),
            status="pending_approval" if needs_approval else "approved",
        )

        # Lưu Master Digest vào MongoDB
        await self.save_master_digest_to_mongo(master_digest)

        if needs_approval:
            sent_ok = await self.send_master_approval_request(master_digest)
            if sent_ok:
                print(f"✔ [MASTER DIGEST APPROVAL] Đã gửi báo cáo Master Digest ngày {target_date} tới Chủ nhân thành công!")
            else:
                print(f"⚠️ [MASTER DIGEST APPROVAL] Đã lưu Master Digest nhưng không thể gửi DM cho Chủ nhân.")
        else:
            await self.approve_and_sync_master_digest(master_digest.id)

        return master_digest

    async def approve_and_sync_master_digest(
        self,
        master_digest_id: Optional[str] = None,
        approver_open_id: Optional[str] = None,
    ) -> tuple[bool, str, Optional[MasterDailyDigestRecord]]:
        """
        Phê duyệt Master Daily Digest:
          1. Lấy bản ghi MasterDailyDigestRecord từ MongoDB.
          2. Lặp qua từng group digest trong group_digests:
             - Đẩy bản markdown của nhóm vào đúng Knowledge Base WeKnora của nhóm đó.
          3. Cập nhật status='synced', approved_by, approved_at trong MongoDB.
        """
        coll = _get_master_daily_digests_coll()
        if master_digest_id:
            doc = await coll.find_one({"id": master_digest_id})
        else:
            doc = await coll.find_one(
                {"status": "pending_approval"},
                sort=[("created_at", -1)],
            )

        if not doc:
            return False, "Không tìm thấy bản ghi Master Daily Digest nào đang chờ duyệt.", None

        master_digest = MasterDailyDigestRecord(**doc)

        synced_count = 0
        failed_count = 0
        for gd in master_digest.group_digests:
            ok = await self.sync_digest_to_weknora(gd)
            if ok:
                synced_count += 1
            else:
                failed_count += 1

        now_iso = get_vietnam_now_iso()
        master_digest.status = "synced"
        master_digest.approved_by = approver_open_id or settings.DIGEST_APPROVER_ID
        master_digest.approved_at = now_iso
        master_digest.updated_at = now_iso

        await coll.update_one(
            {"id": master_digest.id},
            {"$set": master_digest.to_dict()},
        )

        # [TIER 3: DAILY MASTER DIGEST AUTO-PROMOTE]
        # Thăng hạng toàn bộ PROPOSED claims trong ngày của các nhóm được duyệt thành CURRENT
        try:
            from database.db import promote_proposed_claims_for_chat
            approver_info = {
                "user_id": master_digest.approved_by,
                "user_name": "Lãnh đạo",
                "role": "owner",
            }
            total_promoted = 0
            for gd in master_digest.group_digests:
                if gd.chat_id:
                    cnt = await promote_proposed_claims_for_chat(gd.chat_id, approver_info=approver_info)
                    total_promoted += cnt
            if total_promoted > 0:
                print(f"🎉 [TIER 3 MASTER DIGEST APPROVAL] Đã tự động thăng hạng {total_promoted} claims tồn đọng thành CURRENT.")
        except Exception as e:
            logger.warning(f"Lỗi auto-promote claims khi duyệt Master Digest: {e}")

        msg = f"Đã duyệt và đồng bộ thành công Master Daily Digest ngày {master_digest.date} ({synced_count}/{len(master_digest.group_digests)} nhóm đã nạp vào WeKnora)."
        if failed_count > 0:
            msg += f" (Có {failed_count} nhóm đồng bộ WeKnora thất bại do thiếu dataset_id hoặc lỗi mạng)."

        return True, msg, master_digest

    async def reject_master_digest(
        self,
        master_digest_id: Optional[str] = None,
    ) -> tuple[bool, str, Optional[MasterDailyDigestRecord]]:
        """Từ chối Master Daily Digest."""
        coll = _get_master_daily_digests_coll()
        if master_digest_id:
            doc = await coll.find_one({"id": master_digest_id})
        else:
            doc = await coll.find_one(
                {"status": "pending_approval"},
                sort=[("created_at", -1)],
            )

        if not doc:
            return False, "Không tìm thấy bản ghi Master Daily Digest nào đang chờ duyệt.", None

        master_digest = MasterDailyDigestRecord(**doc)
        now_iso = get_vietnam_now_iso()
        master_digest.status = "rejected"
        master_digest.updated_at = now_iso

        await coll.update_one(
            {"id": master_digest.id},
            {"$set": {"status": "rejected", "updated_at": now_iso}},
        )
        return True, f"Đã từ chối Master Daily Digest ({master_digest.id}). Dữ liệu không được nạp vào WeKnora.", master_digest

    async def run_scheduled_daily_digests(
        self,
        date: Optional[str] = None,
        require_approval: Optional[bool] = None,
    ) -> MasterDailyDigestRecord:
        """
        Chạy tổng hợp tự động cho tất cả các nhóm chat hoạt động trong ngày:
        Tạo 1 bản Master Executive Daily Digest duy nhất gom toàn bộ nhóm chat.
        """
        return await self.generate_master_daily_digest(
            date=date,
            require_approval=require_approval,
        )

    async def process_and_sync_daily_digest(
        self,
        chat_id: str,
        chat_name: str = "",
        date: Optional[str] = None,
        project_tag: Optional[str] = None,
        weknora_kb_id: Optional[str] = None,
        require_approval: Optional[bool] = None,
    ) -> DailyDigestRecord:
        """
        Flow tự động trọn gói:
          1. Lấy tin nhắn staging trong ngày từ MongoDB
          2. Trích xuất LLM (Quyết định, Cam kết, Thay đổi trạng thái + truy vết)
          3. Lưu bản ghi vào MongoDB
          4. Nếu require_approval == True (hoặc cấu hình .env bật require_approval):
             - Lưu với trạng thái 'pending_approval'
             - Gửi tin nhắn xin duyệt tới Người duyệt (Lark DM)
             - CHỜ NGƯỜI DUYỆT OK mới update lên WeKnora
          5. Nếu require_approval == False:
             - Tự động đẩy thẳng lên WeKnora ngay
        """
        needs_approval = (
            require_approval
            if require_approval is not None
            else settings.DIGEST_REQUIRE_APPROVAL
        )

        target_date = date or get_current_digest_date()
        messages = await self.get_staging_messages(chat_id=chat_id, date=target_date)

        logger.info(f"Bắt đầu tổng hợp DailyDigest cho nhóm {chat_id} ngày {target_date} ({len(messages)} tin nhắn)")
        digest = await self.extract_digest_from_messages(
            messages=messages,
            chat_id=chat_id,
            chat_name=chat_name,
            date=target_date,
            project_tag=project_tag,
        )

        from services.knowledge.chat_scopes import scope_service

        scoped_wiki_kb = await scope_service.get_wiki_kb_for_chat(chat_id)
        digest.weknora_kb_id = weknora_kb_id or scoped_wiki_kb

        if needs_approval:
            digest.sync_status = "pending_approval"
            await self.save_digest_to_mongo(digest)
            sent_ok = await self.send_approval_request(digest)
            if sent_ok:
                print(f"✔ [DIGEST APPROVAL] Đã gửi tin nhắn xin duyệt Daily Digest ({digest.id}) tới approver thành công!")
                logger.info(f"✔ Đã lưu DailyDigest {digest.id} và gửi tin nhắn chờ duyệt tới approver thành công.")
            else:
                print(f"❌ [DIGEST APPROVAL] Đã lưu DailyDigest {digest.id} vào MongoDB nhưng KHÔNG THỂ gửi tin nhắn duyệt qua Lark (Lỗi API/Quota 429)!")
                logger.warning(
                    f"⚠️ [DIGEST APPROVAL] Đã lưu DailyDigest {digest.id} vào MongoDB nhưng KHÔNG THỂ gửi tin nhắn duyệt qua Lark "
                    f"(Vui lòng kiểm tra API quota hoặc cấu hình Lark Bot)!"
                )
        else:
            await self.save_digest_to_mongo(digest)
            await self.sync_digest_to_weknora(digest, dataset_id=weknora_kb_id)

        return digest



# Singleton instance
digest_service = DigestService()

__all__ = [
    "DigestService",
    "digest_service",
]
