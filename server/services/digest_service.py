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

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

import httpx

from core.config import settings
from database.db import get_staging_collection, get_daily_digests_collection
from models.digest import (
    CommitmentItem,
    DailyDigestRecord,
    DecisionItem,
    SourceReference,
    StagingMessage,
    StatusCategory,
    StatusChangeItem,
)
from models.memory import get_vietnam_now_iso
from services.weknora import weknora_service
from utils.digest import build_lark_message_link, get_current_digest_date

logger = logging.getLogger("hilark.digest")
logger.setLevel(logging.INFO)


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
        self.fallback_models = [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
        ]

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
            coll = get_staging_collection()
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
            coll = get_staging_collection()
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
        """Gọi Gemini API qua danh sách model fallback với thinkingBudget: 0."""
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY chưa được cấu hình trong settings.")

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 4096,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

        last_error = None
        async with httpx.AsyncClient(timeout=60.0) as client:
            for model in self.fallback_models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
                try:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                return parts[0].get("text", "")
                    elif resp.status_code in (400, 404):
                        last_error = f"Model {model} không khả dụng (status {resp.status_code})"
                        continue
                    else:
                        resp.raise_for_status()
                except Exception as e:
                    last_error = e
                    continue

        raise RuntimeError(f"Không thể gọi Gemini API: {last_error}")

    async def extract_digest_from_messages(
        self,
        messages: List[StagingMessage],
        chat_id: str,
        chat_name: str = "",
        date: Optional[str] = None,
        project_tag: Optional[str] = None,
    ) -> DailyDigestRecord:
        """Dùng LLM đọc danh sách tin nhắn và trích xuất thành đối tượng DailyDigestRecord."""
        target_date = date or get_current_digest_date()
        digest_id = f"digest_{target_date.replace('-', '')}_{chat_id}"

        if not messages:
            return DailyDigestRecord(
                id=digest_id,
                date=target_date,
                chat_id=chat_id,
                chat_name=chat_name,
                project_tag=project_tag,
                overview_summary="Không có tin nhắn trao đổi nào trong ngày.",
            )

        # Định dạng danh sách tin nhắn nạp vào LLM kèm message_id và timestamp
        formatted_msgs = []
        for idx, m in enumerate(messages, 1):
            formatted_msgs.append(
                f"[{idx}] (message_id: {m.message_id}) [{m.timestamp}] {m.speaker_name}: {m.text}"
            )
        msgs_block = "\n".join(formatted_msgs)

        user_prompt = f"""\
HỘI THOẠI TRONG NGÀY ({target_date}) - NHÓM: {chat_name or chat_id}:
\"\"\"
{msgs_block}
\"\"\"

Hãy trích xuất:
1. Quyết định (Decisions)
2. Cam kết (Commitments: ai hứa gì, hạn nào)
3. Thay đổi trạng thái (Status Changes: tiến độ, mốc, blocker)
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
            decisions=decisions,
            commitments=commitments,
            status_changes=status_changes,
            message_count=len(messages),
        )

    # -------------------------------------------------------------------------
    # 3. LƯU MONGODB & ĐỒNG BỘ WEKNORA
    # -------------------------------------------------------------------------

    async def save_digest_to_mongo(self, digest: DailyDigestRecord) -> None:
        """Lưu hoặc cập nhật bản DailyDigestRecord vào MongoDB và đánh dấu staging đã xử lý."""
        try:
            coll = get_daily_digests_collection()
            await coll.update_one(
                {"id": digest.id},
                {"$set": digest.to_dict()},
                upsert=True,
            )

            # Đánh dấu các tin nhắn staging liên quan trong ngày là đã xử lý
            stg_coll = get_staging_collection()
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
        target_kb = dataset_id or digest.weknora_kb_id or settings.WEKNORA_DATASET_ID
        if target_kb and "," in target_kb:
            target_kb = target_kb.split(",")[0].strip()

        if not target_kb:
            logger.warning("Không tìm thấy dataset_id để đồng bộ sang WeKnora.")
            digest.sync_status = "failed"
            return False

        md_content = digest.to_weknora_markdown()
        doc_name = f"Daily_Digest_{digest.date}_{digest.chat_name or digest.chat_id}"

        try:
            resp = await weknora_service.save_to_kb(text=md_content, dataset_id=target_kb, name=doc_name)
            doc_id = ""
            if isinstance(resp, dict):
                doc_id = resp.get("data", {}).get("id") or resp.get("id") or ""

            digest.weknora_kb_id = target_kb
            digest.weknora_doc_id = str(doc_id)
            digest.sync_status = "synced"
            digest.updated_at = get_vietnam_now_iso()

            # Cập nhật lại trạng thái vào MongoDB
            coll = get_daily_digests_collection()
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
            coll = get_daily_digests_collection()
            doc = await coll.find_one({"id": digest_id})
            if doc:
                return DailyDigestRecord(**doc)
            return None
        except Exception as e:
            logger.error(f"Lỗi khi tìm DailyDigest {digest_id}: {e}", exc_info=True)
            return None

    async def sync_digest_by_id(
        self,
        digest_id: str,
        dataset_id: Optional[str] = None,
    ) -> bool:
        """
        Lôi bản ghi DailyDigest từ MongoDB theo digest_id và đồng bộ đẩy lên WeKnora.
        """
        digest = await self.get_digest_by_id(digest_id)
        if not digest:
            logger.warning(f"Không tìm thấy digest {digest_id} trong MongoDB để đồng bộ.")
            return False

        return await self.sync_digest_to_weknora(digest, dataset_id=dataset_id)

    async def sync_pending_digests(
        self,
        limit: int = 20,
        dataset_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Quét các bản ghi DailyDigest trong MongoDB có sync_status != 'synced'
        (ví dụ: 'pending', 'failed') để tự động đẩy bù / retry sang WeKnora.
        """
        try:
            coll = get_daily_digests_collection()
            cursor = coll.find(
                {"sync_status": {"$in": ["pending", "failed", None]}}
            ).limit(limit)
            docs = await cursor.to_list(length=limit)

            synced_count = 0
            failed_count = 0
            synced_ids = []

            for d in docs:
                digest = DailyDigestRecord(**d)
                ok = await self.sync_digest_to_weknora(digest, dataset_id=dataset_id)
                if ok:
                    synced_count += 1
                    synced_ids.append(digest.id)
                else:
                    failed_count += 1

            return {
                "total_found": len(docs),
                "synced_count": synced_count,
                "failed_count": failed_count,
                "synced_ids": synced_ids,
            }
        except Exception as e:
            logger.error(f"Lỗi khi quét sync pending digests: {e}", exc_info=True)
            return {
                "total_found": 0,
                "synced_count": 0,
                "failed_count": 0,
                "error": str(e),
            }


    async def process_and_sync_daily_digest(
        self,
        chat_id: str,
        chat_name: str = "",
        date: Optional[str] = None,
        project_tag: Optional[str] = None,
        weknora_kb_id: Optional[str] = None,
    ) -> DailyDigestRecord:
        """
        Flow tự động trọn gói cuối ngày:
          1. Lấy tin nhắn staging trong ngày từ MongoDB
          2. Trích xuất LLM (Quyết định, Cam kết, Thay đổi trạng thái + truy vết)
          3. Lưu bản ghi vào MongoDB
          4. Đẩy bản Markdown lên WeKnora
        """
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

        # Lưu vào MongoDB
        await self.save_digest_to_mongo(digest)

        # Đồng bộ sang WeKnora
        await self.sync_digest_to_weknora(digest, dataset_id=weknora_kb_id)

        return digest


# Singleton instance
digest_service = DigestService()

__all__ = [
    "DigestService",
    "digest_service",
]
