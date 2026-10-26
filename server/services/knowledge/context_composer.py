"""
HiLark Context Composer Utility
===============================
Vị trí: server/utils/context_composer.py

Mục đích:
    Đóng gói (compose) dữ liệu đa nguồn gồm:
      1. Chunks văn bản từ WeKnora Retriever (Knowledge Base / tài liệu tĩnh như PDF, Word, quy trình)
      2. Mệnh đề & Thực thể từ MongoDB Claims Store (Tri thức động / cập nhật thực tế từ tin nhắn chat)
    thành một khối Ngữ cảnh hoàn chỉnh (Unified Hierarchical Context) kèm theo:
      - Phân cấp thông tin rõ ràng giữa Tài liệu văn bản và Mệnh đề thực tế
      - Lần vết chuỗi thay thế (Lineage / Superseded facts)
      - Quy tắc giải quyết xung đột (Conflict Resolution Rules) giúp LLM không bị mâu thuẫn thông tin
      - Chuẩn hóa trích dẫn nguồn (Citations metadata)

Sử dụng:
    from utils.context_composer import ContextComposer, compose_context

    composer = ContextComposer()
    result = composer.compose(
        retriever_data=retriever_chunks,
        claims_data=claims_list,
    )
    prompt_context = result["context_text"]
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Union

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class RetrievedChunk:
    """Đại diện cho 1 đoạn văn bản được WeKnora Retriever truy xuất từ tài liệu."""
    content: str
    doc_name: str = "Tài liệu hệ thống"
    chunk_id: Optional[str] = None
    score: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "content": self.content,
            "doc_name": self.doc_name,
        }
        if self.chunk_id:
            res["chunk_id"] = self.chunk_id
        if self.score is not None:
            res["score"] = self.score
        if self.metadata:
            res["metadata"] = self.metadata
        return res


@dataclass
class NormalizedClaim:
    """Đại diện cho 1 mệnh đề / fact được trích xuất từ bộ nhớ phân cấp."""
    id: str
    property: str
    value: Any
    status: str = "current"  # current, proposed, superseded, conflicted, uncertain
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    entity_type: Optional[str] = None
    replaces: Optional[str] = None
    source_snippet: Optional[str] = None
    asserted_by: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "property": self.property,
            "value": self.value,
            "status": self.status,
            "entity_name": self.entity_name or "Chung",
            "replaces": self.replaces,
            "source_snippet": self.source_snippet,
            "asserted_by": self.asserted_by,
        }


# =============================================================================
# CONTEXT COMPOSER CLASS
# =============================================================================

class ContextComposer:
    """
    Công cụ hợp nhất dữ liệu từ WeKnora Retriever và MongoDB Claims
    thành prompt context chuẩn cho LLM Grounded Generation.
    """

    DEFAULT_CONFLICT_RULES = """NGUYÊN TẮC GIẢI QUYẾT XUNG ĐỘT & THẨM QUYỀN TRI THỨC (AUTHORITY & CONFLICT RESOLUTION):
1. THẨM QUYỀN TỐI CAO TỪ CEO / BAN ĐIỀU HÀNH: Các mệnh đề có tiền tố ⭐ [QUYẾT ĐỊNH CHÍNH THỨC TỪ CEO / BAN ĐIỀU HÀNH] hoặc [CURRENT] do Sếp/Owner chốt là chân lý thực tế cao nhất, có hiệu lực tuyệt đối và cao hơn mọi tài liệu văn bản tĩnh.
2. PHÂN BIỆT RẠCH RÒI ĐỀ XUẤT VÀ QUYẾT ĐỊNH: Các mệnh đề có tiền tố 💡 [ĐỀ XUẤT NHÂN SỰ / CHỜ DUYỆT (PROPOSED)] chỉ là ý kiến, nguyện vọng hoặc câu hỏi xin phép của nhân viên, TUYỆT ĐỐI CHƯA PHẢI QUYẾT ĐỊNH. CHỈ đề cập hoặc phản hồi về đề xuất này nếu câu hỏi của người dùng trực tiếp liên quan hoặc hỏi về đề xuất/nguyện vọng đó. Khi đó giải thích rõ: "Đây mới là đề xuất của bạn [X], hiện chưa được Sếp duyệt chính thức". TUYỆT ĐỐI KHÔNG tự ý chêm đề xuất vào câu trả lời nếu người dùng đang hỏi chuyện khác.
3. KHÔNG GÁN GHÉP NHẦM LẪN NHÂN SỰ: Mỗi nhân sự có lộ trình và nhiệm vụ riêng. Người hỏi hỏi về ai thì chỉ trả lời đúng về người đó, tuyệt đối không lấy thông tin, vai trò hay lộ trình của nhân sự khác gán cho người hỏi.
4. NÊU RÕ BIẾN ĐỘNG LỊCH SỬ: Nếu phát hiện mâu thuẫn giữa Tài liệu và Mệnh đề (ví dụ: tài liệu ghi giá trị A nhưng mệnh đề đã cập nhật giá trị B), hãy giải thích rõ: "Theo tài liệu gốc là A, tuy nhiên theo cập nhật thảo luận mới nhất đã được điều chỉnh thành B"."""

    def __init__(
        self,
        max_chunks: int = 8,
        max_claims: int = 25,
        include_superseded: bool = True,
        conflict_rules: Optional[str] = None,
    ):
        self.max_chunks = max_chunks
        self.max_claims = max_claims
        self.include_superseded = include_superseded
        self.conflict_rules = conflict_rules or self.DEFAULT_CONFLICT_RULES

    # -------------------------------------------------------------------------
    # 1. BỘ CHUẨN HOÁ DỮ LIỆU ĐẦU VÀO (NORMALIZERS)
    # -------------------------------------------------------------------------

    def normalize_retriever_data(
        self,
        retriever_data: Any,
    ) -> List[RetrievedChunk]:
        """
        Chuẩn hóa mọi dạng dữ liệu trả về từ WeKnora Retriever:
          - List of dicts (chunks)
          - Dict response dạng Dify/WeKnora: {"records": [...]} hoặc {"data": [...]}
          - List of strings
          - Response kèm citations từ get_chat_response
        """
        chunks: List[RetrievedChunk] = []
        if not retriever_data:
            return chunks

        raw_items: List[Any] = []
        if isinstance(retriever_data, dict):
            if "records" in retriever_data and isinstance(retriever_data["records"], list):
                raw_items = retriever_data["records"]
            elif "data" in retriever_data and isinstance(retriever_data["data"], list):
                raw_items = retriever_data["data"]
            elif "chunks" in retriever_data and isinstance(retriever_data["chunks"], list):
                raw_items = retriever_data["chunks"]
            elif "citations" in retriever_data and isinstance(retriever_data["citations"], list):
                # Format get_chat_response citations
                raw_items = retriever_data["citations"]
            elif "answer" in retriever_data:
                # Nếu chỉ có text answer/content
                raw_items = [retriever_data]
            else:
                raw_items = [retriever_data]
        elif isinstance(retriever_data, list):
            raw_items = retriever_data
        elif isinstance(retriever_data, str):
            raw_items = [{"content": retriever_data}]

        for item in raw_items:
            if not item:
                continue

            if isinstance(item, RetrievedChunk):
                chunks.append(item)
                continue

            if isinstance(item, str):
                text = item.strip()
                if text:
                    chunks.append(RetrievedChunk(content=text))
                continue


            if isinstance(item, dict):
                content = (
                    item.get("content")
                    or item.get("text")
                    or item.get("snippet")
                    or item.get("chunk_content")
                    or item.get("answer")
                    or ""
                )
                doc_obj = item.get("document")
                nested_doc = doc_obj.get("name") if isinstance(doc_obj, dict) else None
                doc = (
                    item.get("knowledge_title")
                    or item.get("document_name")
                    or item.get("doc_name")
                    or item.get("doc")
                    or item.get("title")
                    or nested_doc
                    or "Tài liệu hệ thống"
                )

                cid = item.get("chunk_id") or item.get("segment_id") or item.get("id")
                score = item.get("score")

                if content:
                    chunks.append(
                        RetrievedChunk(
                            content=str(content).strip(),
                            doc_name=str(doc).strip(),
                            chunk_id=str(cid) if cid else None,
                            score=float(score) if score is not None else None,
                            metadata=item.get("metadata") or {},
                        )
                    )

        # De-duplicate chunks theo content trùng lặp
        seen_texts: Set[str] = set()
        unique_chunks: List[RetrievedChunk] = []
        for c in chunks:
            norm_text = re.sub(r"\s+", " ", c.content.strip().lower())
            if norm_text and norm_text not in seen_texts:
                seen_texts.add(norm_text)
                unique_chunks.append(c)

        return unique_chunks[: self.max_chunks]

    def normalize_claims_data(
        self,
        claims_data: Any,
        entity_map: Optional[Dict[str, Any]] = None,
    ) -> List[NormalizedClaim]:
        """
        Chuẩn hóa mọi dạng dữ liệu Claims / Facts:
          - List of Fact dicts / models
          - Parent-Child entity trees (kết quả từ build_entity_tree)
          - Dict facts map
        """
        claims: List[NormalizedClaim] = []
        if not claims_data:
            return claims

        raw_facts: List[Dict[str, Any]] = []
        entities_lookup: Dict[str, Dict[str, Any]] = dict(entity_map or {})

        # Tự động nạp entities từ MongoDB nếu chưa có entity_map
        if not entities_lookup:
            try:
                from database.db import get_all_entities_sync
                raw_entities = get_all_entities_sync(workspace_id=None)
                if raw_entities:
                    for ent in raw_entities:
                        if isinstance(ent, dict):
                            eid_key = str(ent.get("id") or ent.get("_id") or "")
                            if eid_key:
                                entities_lookup[eid_key] = ent
            except Exception as e:
                logger.debug(f"Không thể tự động tải entities từ MongoDB: {e}")

        # 1. Bóc tách dữ liệu
        if isinstance(claims_data, list):
            for elem in claims_data:
                if not elem:
                    continue
                # Nếu là Entity Tree Node có active_facts & history_facts
                if isinstance(elem, dict) and ("active_facts" in elem or "history_facts" in elem):
                    eid = elem.get("id") or elem.get("_id")
                    ename = elem.get("name") or elem.get("canonical_name") or "Chung"
                    etype = elem.get("type") or "unknown"
                    if eid:
                        entities_lookup[str(eid)] = {"name": ename, "type": etype}

                    for f in elem.get("active_facts", []):
                        if isinstance(f, dict):
                            item = dict(f)
                            item.setdefault("entity_id", eid)
                            item.setdefault("_entity_name", ename)
                            item.setdefault("_entity_type", etype)
                            raw_facts.append(item)

                    if self.include_superseded:
                        for f in elem.get("history_facts", []):
                            if isinstance(f, dict):
                                item = dict(f)
                                item.setdefault("entity_id", eid)
                                item.setdefault("_entity_name", ename)
                                item.setdefault("_entity_type", etype)
                                raw_facts.append(item)
                elif hasattr(elem, "to_dict"):
                    raw_facts.append(elem.to_dict())
                elif isinstance(elem, dict):
                    raw_facts.append(dict(elem))
        elif isinstance(claims_data, dict):
            # Có thể là {"facts": [...], "entities": [...]}
            if "facts" in claims_data and isinstance(claims_data["facts"], list):
                raw_facts = list(claims_data["facts"])
            elif "claims" in claims_data and isinstance(claims_data["claims"], list):
                raw_facts = list(claims_data["claims"])
            else:
                raw_facts = [claims_data]

            if "entities" in claims_data and isinstance(claims_data["entities"], list):
                for ent in claims_data["entities"]:
                    if isinstance(ent, dict):
                        eid = ent.get("id") or ent.get("_id")
                        if eid:
                            entities_lookup[str(eid)] = ent

        # 2. Chuẩn hóa từng Fact
        seen_fact_ids: Set[str] = set()
        for f in raw_facts:
            fid = str(f.get("id") or f.get("_id") or f.get("fact_id") or "")
            if fid and fid in seen_fact_ids:
                continue
            if fid:
                seen_fact_ids.add(fid)

            prop = str(f.get("property") or f.get("predicate") or "info").strip()
            val = f.get("value")
            if val is None or val == "":
                continue

            status = str(f.get("status") or "current").lower()
            if status in ("accepted", "active", "approved"):
                status = "current"
            if not self.include_superseded and status == "superseded":
                continue

            eid = str(f.get("entity_id") or "")
            ename = f.get("_entity_name")
            etype = f.get("_entity_type")

            if not ename and eid and eid in entities_lookup:
                ent_obj = entities_lookup[eid]
                ename = ent_obj.get("name") or ent_obj.get("canonical_name")
                etype = ent_obj.get("type")

            # Fallback nếu vẫn chưa có ename: lấy từ project_tag hoặc entity_name
            if not ename:
                ename = f.get("project_tag") or f.get("entity_name")

            src = f.get("source") or f.get("source_doc")
            snippet = None
            if isinstance(src, dict):
                snippet = src.get("snippet") or src.get("text") or src.get("source_doc")
            elif isinstance(src, str):
                snippet = src

            claims.append(
                NormalizedClaim(
                    id=fid,
                    property=prop,
                    value=val,
                    status=status,
                    entity_id=eid if eid else None,
                    entity_name=ename or "Hệ thống",
                    entity_type=etype,
                    replaces=f.get("replaces") or f.get("supersedes"),
                    source_snippet=snippet,
                    asserted_by=f.get("asserted_by"),
                    created_at=f.get("created_at") or f.get("updated_at"),
                )
            )

        # Sắp xếp: CURRENT và PROPOSED ưu tiên trước SUPERSEDED
        def claim_sort_key(c: NormalizedClaim):
            status_priority = {"current": 0, "proposed": 1, "uncertain": 2, "conflicted": 3, "superseded": 4}
            return (status_priority.get(c.status, 5), c.entity_name or "")

        claims.sort(key=claim_sort_key)
        return claims[: self.max_claims]

    # -------------------------------------------------------------------------
    # 2. ĐÓNG GÓI NỘI DUNG (FORMATTING & RENDERING)
    # -------------------------------------------------------------------------

    def format_retriever_section(self, chunks: List[RetrievedChunk], max_chunk_chars: int = 16000) -> str:
        """Định dạng phân vùng tài liệu từ WeKnora."""
        if not chunks:
            return "(Không có dữ liệu tài liệu trích xuất từ WeKnora)"

        lines: List[str] = []
        for idx, c in enumerate(chunks, 1):
            chunk_tag = f" [Chunk ID: {c.chunk_id}]" if c.chunk_id else ""
            score_tag = f" (Score: {c.score:.2f})" if c.score is not None else ""
            lines.append(f"--- [Tài liệu {idx}]: {c.doc_name}{chunk_tag}{score_tag} ---")
            raw_content = c.content.strip()
            if len(raw_content) > max_chunk_chars:
                lines.append(raw_content[:max_chunk_chars] + f"\n...(đoạn trích lược bớt {len(raw_content) - max_chunk_chars} ký tự để tối ưu bối cảnh)...")
            else:
                lines.append(raw_content)
            lines.append("")

        return "\n".join(lines).strip()

    def format_claims_section(self, claims: List[NormalizedClaim]) -> str:
        """Định dạng phân vùng Mệnh đề / Facts từ MongoDB phân cấp theo Thực thể."""
        if not claims:
            return "(Không có mệnh đề hoặc cập nhật thực tế từ bộ nhớ)"

        # Nhóm claims theo Entity
        grouped: Dict[str, List[NormalizedClaim]] = {}
        for c in claims:
            ent_key = c.entity_name or "Hệ thống / Chung"
            grouped.setdefault(ent_key, []).append(c)

        lines: List[str] = []
        for ent_name, ent_claims in grouped.items():
            lines.append(f"📦 THỰC THỂ: {ent_name.upper()}")

            # 1. Thuộc tính hiện hành / Quyết định chính thức (Active / Current)
            active = [c for c in ent_claims if c.status in ("current", "uncertain", "conflicted")]
            if active:
                for c in active:
                    asserted = c.asserted_by or {}
                    speaker_role = asserted.get("role") if isinstance(asserted, dict) else getattr(asserted, "role", "member")
                    speaker_name = asserted.get("user_name") if isinstance(asserted, dict) else getattr(asserted, "user_name", "")

                    if speaker_role == "owner":
                        st_badge = "⭐ [QUYẾT ĐỊNH CHÍNH THỨC TỪ CEO / BAN ĐIỀU HÀNH]"
                    else:
                        st_badge = f"[{c.status.upper()}]"

                    rep_note = f" (Thay thế cho: {c.replaces})" if c.replaces else ""
                    speaker_note = f" (Chốt bởi: {speaker_name})" if speaker_name and speaker_role == "owner" else ""
                    src_note = f" | Nguồn: \"{c.source_snippet}\"" if c.source_snippet else ""
                    lines.append(f"  • {st_badge} {c.property} = \"{c.value}\"{speaker_note}{rep_note}{src_note}")

            # 2. Đề xuất nhân sự / Chờ duyệt (Proposed)
            proposed = [c for c in ent_claims if c.status == "proposed"]
            if proposed:
                for c in proposed:
                    asserted = c.asserted_by or {}
                    speaker_name = asserted.get("user_name") if isinstance(asserted, dict) else getattr(asserted, "user_name", "Nhân sự")
                    src_note = f" | Lời đề xuất: \"{c.source_snippet}\"" if c.source_snippet else ""
                    lines.append(
                        f"  • 💡 [ĐỀ XUẤT NHÂN SỰ / CHỜ DUYỆT (PROPOSED)] {c.property} = \"{c.value}\" "
                        f"(Đề xuất bởi: {speaker_name} - CHƯA ĐƯỢC DUYỆT CHÍNH THỨC){src_note}"
                    )

            # 3. Thuộc tính lịch sử (Superseded)
            superseded = [c for c in ent_claims if c.status == "superseded"]
            if superseded and self.include_superseded:
                for c in superseded:
                    src_note = f" | Từng nói: \"{c.source_snippet}\"" if c.source_snippet else ""
                    lines.append(f"  • [LỊCH SỬ/SUPERSEDED] {c.property} = \"{c.value}\" (Đã bị thay thế){src_note}")

            lines.append("")

        return "\n".join(lines).strip()

    def align_claims_with_retriever(
        self,
        chunks: Optional[List[RetrievedChunk]] = None,
        claims: Optional[List[NormalizedClaim]] = None,
        query: Optional[str] = None,
        entity_map: Optional[Dict[str, Any]] = None,
    ) -> List[NormalizedClaim]:
        """
        Contextual Claim Gate (EDL-0008):
        Lọc và chỉ nạp các Mệnh đề (Claims) thực sự liên quan đến Trọng tâm Câu hỏi của người dùng:
          1. Cô lập Proposed Claims: Mệnh đề trạng thái PROPOSED chỉ được xem xét khi câu hỏi
             thực sự có ý định hỏi/nhắc đến đề xuất, nguyện vọng hoặc vai trò nhân sự.
          2. Property & Value Match: So khớp theo thuộc tính nghiệp vụ hoặc giá trị trong câu hỏi.
          3. Triệt tiêu Safe Scoped Fallback: Nếu không có claim nào khớp với câu hỏi, trả về [] (rỗng).
             Tuyệt đối không tự ý nạp toàn bộ claims của nhóm vào prompt.
          4. Chỉ cho phép nạp Key Facts hiện hành (CURRENT) nếu là câu hỏi tổng quan dự án.
        """
        if not claims:
            return []
        
        query_text = (query or "").lower().strip()
        if not query_text:
            return []

        # Tự động nạp entity_map nếu chưa có
        if not entity_map:
            try:
                from database.db import get_all_entities_sync
                raw_entities = get_all_entities_sync(workspace_id=None)
                if raw_entities:
                    entity_map = {str(e.get("id")): e for e in raw_entities if isinstance(e, dict) and e.get("id")}
            except Exception:
                entity_map = {}

        # Từ điển ánh xạ từ đồng nghĩa cho các thuộc tính nghiệp vụ
        PROPERTY_SYNONYMS: Dict[str, Set[str]] = {
            "lead": {"lead", "trưởng", "phụ trách", "chỉ huy", "quản lý"},
            "owner": {"owner", "chủ", "phụ trách", "nắm", "quản lý", "lead", "chịu trách nhiệm"},
            "role": {"role", "vai trò", "vị trí", "chức vụ", "làm gì", "công việc"},
            "assignee": {"assignee", "người làm", "giao cho", "phụ trách", "ai làm", "ai nhận", "giao ai"},
            "scope": {"scope", "phạm vi", "kế hoạch", "mục tiêu", "nội dung", "thay đổi", "giảm", "tăng", "bỏ", "thêm", "tính năng"},
            "deadline": {"deadline", "hạn chót", "thời hạn", "ngày nào", "khi nào", "tiến độ", "hạn", "bao giờ"},
            "budget": {"ngân sách", "chi phí", "tiền", "budget", "kinh phí", "giá"},
            "status": {"trạng thái", "tình hình", "tiến độ", "ra sao", "thế nào"},
        }

        # Nhận diện ý định hỏi về Đề xuất / Nguyện vọng nhân sự (Proposal Intent)
        PROPOSAL_INTENT_KEYWORDS = {
            "đề xuất", "nguyện vọng", "xin làm", "xin nhận", "ý kiến", "chốt chưa",
            "duyệt chưa", "được không", "ai làm lead", "ai là lead", "ai lead",
            "vai trò của em", "đề xuất của em", "đề xuất của", "cho em làm", "cho em xin",
        }
        is_asking_about_proposal = any(kw in query_text for kw in PROPOSAL_INTENT_KEYWORDS)

        # Nhận diện câu hỏi tổng quan dự án (General Project Overview Query)
        GENERAL_PROJECT_QUERY_KEYWORDS = {
            "thông tin dự án", "tổng quan dự án", "dự án này làm gì", "kế hoạch dự án",
            "mục tiêu dự án", "dự án thế nào", "dự án ra sao", "tình hình dự án", "tiến độ dự án",
        }
        is_general_project_query = any(kw in query_text for kw in GENERAL_PROJECT_QUERY_KEYWORDS)

        # Trích xuất các token có nghĩa từ câu hỏi (bỏ stopwords)
        QUERY_STOPWORDS = {
            "là", "gì", "thế", "nào", "cho", "của", "và", "như", "các", "có", "không",
            "nhé", "được", "ạ", "ơi", "với", "trong", "đến", "này", "đó", "hỏi", "về",
            "ai", "sao", "thì", "đã", "đang", "sẽ", "phải", "muốn", "xin", "bạn", "mình",
            "làm", "dự", "án", "em", "anh", "chị", "giúp", "báo"
        }
        query_tokens = [w for w in re.findall(r"\w+", query_text) if len(w) >= 2 and w not in QUERY_STOPWORDS]

        # Xây dựng từ khóa Entity riêng biệt (Distinct Entities) có mặt trong câu hỏi
        GENERIC_ENTITY_WORDS = {
            "dự án", "project", "hệ thống", "công ty", "nhóm", "team", "lead", "sếp", "ông", "bạn", "mình",
            "dự án này", "dự án của chúng ta", "ai", "bên mình", "chúng tôi", "người", "nhân sự", "phạm vi"
        }
        query_mentioned_entities: Set[str] = set()
        for eid, ent in (entity_map or {}).items():
            ename = (ent.get("name") or ent.get("canonical_name") or "").lower().strip()
            if ename and len(ename) >= 2 and ename not in GENERIC_ENTITY_WORDS and re.search(rf"(?<!\w){re.escape(ename)}(?!\w)", query_text):
                query_mentioned_entities.add(str(eid))
                query_mentioned_entities.add(ename)
            for a in ent.get("aliases", []):
                if a and isinstance(a, str) and len(a.strip()) >= 2:
                    alias_clean = a.lower().strip()
                    if alias_clean not in GENERIC_ENTITY_WORDS and re.search(rf"(?<!\w){re.escape(alias_clean)}(?!\w)", query_text):
                        query_mentioned_entities.add(str(eid))
                        query_mentioned_entities.add(alias_clean)

        matched_claims: List[NormalizedClaim] = []
        matched_ids: Set[str] = set()

        for claim in claims:
            cid = claim.id or f"{claim.property}_{claim.value}"
            if cid in matched_ids:
                continue

            c_status = (claim.status or "current").lower().strip()
            c_name = (claim.entity_name or "").lower().strip()
            c_eid = str(claim.entity_id or "")
            c_prop = (claim.property or "").lower().strip()
            c_val_str = str(claim.value or "").lower().strip()
            c_snippet = (claim.source_snippet or "").lower().strip()

            # --- NGUYÊN TẮC CÔ LẬP PROPOSED CLAIMS ---
            # Nếu là đề xuất cá nhân (proposed), CẤM đưa vào trừ khi câu hỏi đích danh hỏi về đề xuất/vai trò đó
            if c_status == "proposed" and not is_asking_about_proposal:
                continue

            is_matched = False

            # --- CHIỀU 1: SO KHỚP THUỘC TÍNH NGHIỆP VỤ (Property Match) ---
            if c_prop and len(c_prop) >= 2:
                synonyms = PROPERTY_SYNONYMS.get(c_prop, {c_prop})
                if any(re.search(rf"(?<!\w){re.escape(syn)}(?!\w)", query_text) for syn in synonyms):
                    # Nếu câu hỏi có nhắc Entity khác hẳn Entity của claim này -> không match
                    if not query_mentioned_entities or (c_eid in query_mentioned_entities or c_name in query_mentioned_entities):
                        is_matched = True

            # --- CHIỀU 2: SO KHỚP GIÁ TRỊ CỤ THỂ (Value Match) ---
            if not is_matched and c_val_str and len(c_val_str) >= 2:
                # Giá trị ngắn (tên người, số liệu) xuất hiện trong câu hỏi
                if len(c_val_str) <= 30:
                    if re.search(rf"(?<!\w){re.escape(c_val_str)}(?!\w)", query_text):
                        is_matched = True
                else:
                    if c_val_str in query_text:
                        is_matched = True

            # --- CHIỀU 3: SO KHỚP Ý ĐỊNH ĐỀ XUẤT CỤ THỂ (Khi is_asking_about_proposal == True) ---
            if not is_matched and is_asking_about_proposal and c_status == "proposed":
                # Trùng khớp người đề xuất hoặc thuộc tính đề xuất
                if claim.asserted_by and isinstance(claim.asserted_by, dict):
                    speaker = (claim.asserted_by.get("user_name") or "").lower().strip()
                    if speaker and len(speaker) >= 2 and re.search(rf"(?<!\w){re.escape(speaker)}(?!\w)", query_text):
                        is_matched = True
                if c_snippet and query_tokens:
                    snippet_tokens = {w for w in re.findall(r"\w+", c_snippet.lower()) if len(w) >= 2 and w not in QUERY_STOPWORDS}
                    if set(query_tokens).intersection(snippet_tokens):
                        is_matched = True

            if is_matched:
                matched_claims.append(claim)
                matched_ids.add(cid)

        # --- NGUYÊN TẮC TRIỆT TIÊU FALLBACK MÙ QUÁNG ---
        # Chỉ khi là câu hỏi tổng quan dự án mới lấy Key Facts (status, scope, deadline) ở trạng thái CURRENT
        if not matched_claims:
            if is_general_project_query:
                overview_claims = [
                    c for c in claims
                    if c.status == "current" and (c.property or "").lower() in ("status", "deadline", "scope")
                ]
                logger.debug(f"[Contextual Claim Gate] Bổ sung {len(overview_claims)} Key Facts cho câu hỏi tổng quan dự án.")
                return overview_claims[:3]
            # Mặc định: Trả về rỗng [] để bảo vệ độ sạch của context!
            logger.debug("[Contextual Claim Gate] Không có claim liên quan trực tiếp đến query. Trả về [].")
            return []

        return matched_claims[: self.max_claims]

    # -------------------------------------------------------------------------
    # 3. PHƯƠNG THỨC CHÍNH: COMPOSE
    # -------------------------------------------------------------------------

    def compose(
        self,
        retriever_data: Any = None,
        claims_data: Any = None,
        query: Optional[str] = None,
        entity_map: Optional[Dict[str, Any]] = None,
        extra_system_instruction: Optional[str] = None,
        auto_align: bool = True,
        scope_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Đóng gói toàn diện WeKnora Retriever + Claims Data thành 1 Context hoàn chỉnh.

        Tham số:
          - retriever_data: Dữ liệu chunks từ WeKnora Retriever
          - claims_data: Dữ liệu facts/claims từ MongoDB
          - query: Câu hỏi người dùng (dùng để neo ngữ cảnh bổ sung)
          - entity_map: Bảng tra cứu thực thể và aliases
          - auto_align: Tự động so khớp chéo thực thể (Cách 1) loại bỏ claims không liên quan
          - scope_context: Bối cảnh nhóm chat & danh mục file docs từ Lark Base / MongoDB
        """
        # Tự động nạp entity_map nếu chưa được cung cấp
        if not entity_map:
            try:
                from database.db import get_all_entities_sync
                raw_entities = get_all_entities_sync(workspace_id=None)
                if raw_entities:
                    entity_map = {str(e.get("id")): e for e in raw_entities if isinstance(e, dict) and e.get("id")}
            except Exception:
                entity_map = {}

        # 1. Chuẩn hóa dữ liệu
        chunks = self.normalize_retriever_data(retriever_data)
        claims = self.normalize_claims_data(claims_data, entity_map=entity_map)

        # 2. Tự động so khớp chéo Thực thể (Entity Alignment) nếu bật auto_align và có query
        if auto_align and claims and query:
            claims = self.align_claims_with_retriever(
                chunks=chunks,
                claims=claims,
                query=query,
                entity_map=entity_map,
            )

        # 3. Xây dựng từng section
        docs_text = self.format_retriever_section(chunks)
        claims_text = self.format_claims_section(claims)

        scope_lines: List[str] = []
        if scope_context:
            chat_name = scope_context.get("chat_name") or ""
            project_name = scope_context.get("project_name") or ""
            doc_list = scope_context.get("documents") or []

            scope_lines.append("--- PHẦN 0: BỐI CẢNH DỰ ÁN & BẢN ĐỒ TÀI LIỆU (DOCUMENT MANIFEST) ---")
            if chat_name:
                scope_lines.append(f"• Tên nhóm chat       : {chat_name}")
            if project_name:
                scope_lines.append(f"• Dự án phụ trách     : {project_name}")
            if doc_list:
                scope_lines.append("• Bản đồ tài liệu & Vai trò văn bản (Document Manifest):")
                for d in doc_list:
                    if isinstance(d, dict):
                        d_name = d.get("name") or "Tài liệu"
                        d_summary = d.get("summary")
                        if d_summary and str(d_summary).strip():
                            scope_lines.append(f"  - 📄 [{d_name}]: {str(d_summary).strip()}")
                        else:
                            scope_lines.append(f"  - 📄 [{d_name}] (Tài liệu tham khảo nội bộ)")
                    elif isinstance(d, str) and d.strip():
                        scope_lines.append(f"  - 📄 [{d.strip()}] (Tài liệu tham khảo nội bộ)")
            canonical_proj = project_name or chat_name or "Dự án hiện tại"
            scope_lines.append("• Chỉ dẫn định danh dự án & suy luận bối cảnh ngầm định:")
            scope_lines.append(
                f"  1. TÊN CHÍNH THỨC CỦA DỰ ÁN LÀ: '{canonical_proj}'. "
                f"Mọi câu hỏi chung về 'dự án', 'dự án này là gì', 'thông tin dự án', 'kế hoạch' từ thành viên trong nhóm này "
                f"MẶC ĐỊNH 100% là đang hỏi về dự án '{canonical_proj}'. "
                f"TUYỆT ĐỐI KHÔNG hỏi ngược lại người dùng 'em hỏi dự án nào'!\n"
                f"  2. NGUYÊN TẮC BẢO VỆ TÊN DỰ ÁN (TUYỆT ĐỐI CẤM NHẦM VỚI TÊN TÀI LIỆU): "
                f"Các tài liệu trong 'Bản đồ tài liệu' (như Sổ tay chính sách, Code of Conduct, Bảng dự toán...) "
                f"chỉ là văn bản tham chiếu nội bộ. Tuyệt đối không lấy tên file làm tên dự án."
            )

        # 4. Tạo context text
        context_parts: List[str] = [
            "=== BỘ BỐI CẢNH TRI THỨC TỔNG HỢP (HIERARCHICAL KNOWLEDGE CONTEXT) ===",
            "",
        ]

        if scope_lines:
            context_parts.extend(["\n".join(scope_lines), ""])

        context_parts.extend([
            "--- PHẦN 1: TÀI LIỆU DỰ ÁN & VĂN BẢN (WEKNORA RETRIEVER) ---",
            docs_text,
            "",
            "--- PHẦN 2: THỰC TẾ CẬP NHẬT & MỆNH ĐỀ ĐỘNG (MONGODB CLAIMS) ---",
            claims_text,
            "",
            "--- PHẦN 3: NGUYÊN TẮC XỬ LÝ DỮ LIỆU ---",
            self.conflict_rules,
        ])

        if extra_system_instruction:
            context_parts.extend(["", "--- CHỈ DẪN BỔ SUNG ---", extra_system_instruction.strip()])

        context_text = "\n".join(context_parts).strip()

        # 4. Metadata & Citations
        citations = []
        for c in chunks:
            citations.append({
                "doc": c.doc_name,
                "chunk_id": c.chunk_id,
                "score": c.score,
            })

        entities_covered = sorted(list({c.entity_name for c in claims if c.entity_name}))

        return {
            "context_text": context_text,
            "sections": {
                "documents": docs_text,
                "claims": claims_text,
                "rules": self.conflict_rules,
            },
            "metadata": {
                "num_chunks": len(chunks),
                "num_claims": len(claims),
                "num_active_claims": len([c for c in claims if c.status == "current"]),
                "num_proposed_claims": len([c for c in claims if c.status == "proposed"]),
                "num_superseded_claims": len([c for c in claims if c.status == "superseded"]),
                "citations": citations,
                "entities_covered": entities_covered,
                "has_documents": bool(chunks),
                "has_claims": bool(claims),
            },
        }

    def compose_xml(
        self,
        retriever_data: Any = None,
        claims_data: Any = None,
        query: Optional[str] = None,
        entity_map: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Đóng gói ngữ cảnh dưới dạng XML Tags (rất phù hợp với Claude / Gemini / GPT)."""
        if not entity_map:
            try:
                from database.db import get_all_entities_sync
                raw_entities = get_all_entities_sync(workspace_id=None)
                if raw_entities:
                    entity_map = {str(e.get("id")): e for e in raw_entities if isinstance(e, dict) and e.get("id")}
            except Exception:
                entity_map = {}

        chunks = self.normalize_retriever_data(retriever_data)
        claims = self.normalize_claims_data(claims_data, entity_map=entity_map)
        if claims and (chunks or query):
            claims = self.align_claims_with_retriever(
                chunks=chunks,
                claims=claims,
                query=query,
                entity_map=entity_map,
            )

        xml_parts: List[str] = ["<knowledge_context>"]

        # Documents
        xml_parts.append("  <retrieved_documents>")
        if chunks:
            for idx, c in enumerate(chunks, 1):
                cid_attr = f' id="{c.chunk_id}"' if c.chunk_id else ""
                xml_parts.append(f'    <document index="{idx}" name="{c.doc_name}"{cid_attr}>')
                xml_parts.append(f"      {c.content.strip()}")
                xml_parts.append("    </document>")
        else:
            xml_parts.append("    <empty>Không có tài liệu</empty>")
        xml_parts.append("  </retrieved_documents>")

        # Claims
        xml_parts.append("  <dynamic_claims>")
        if claims:
            for c in claims:
                rep_attr = f' replaces="{c.replaces}"' if c.replaces else ""
                src_attr = f' source="{c.source_snippet}"' if c.source_snippet else ""
                xml_parts.append(
                    f'    <claim id="{c.id}" entity="{c.entity_name}" property="{c.property}" status="{c.status}"{rep_attr}{src_attr}>'
                    f"{c.value}"
                    f"</claim>"
                )
        else:
            xml_parts.append("    <empty>Không có mệnh đề</empty>")
        xml_parts.append("  </dynamic_claims>")

        # Rules
        xml_parts.append("  <conflict_resolution_rules>")
        xml_parts.append(f"    {self.conflict_rules.strip()}")
        xml_parts.append("  </conflict_resolution_rules>")

        if query:
            xml_parts.append(f"  <user_query>{query.strip()}</user_query>")

        xml_parts.append("</knowledge_context>")
        return "\n".join(xml_parts)


# =============================================================================
# HELPER FUNCTIONS & SINGLETON
# =============================================================================

context_composer = ContextComposer()


def compose_context(
    retriever_data: Any = None,
    claims_data: Any = None,
    query: Optional[str] = None,
    entity_map: Optional[Dict[str, Any]] = None,
    scope_context: Optional[Dict[str, Any]] = None,
    include_superseded: bool = True,
    max_chunks: int = 8,
    max_claims: int = 25,
) -> Dict[str, Any]:
    """
    Hàm tiện ích nhanh (Functional API) để đóng gói context.

    Ví dụ:
        ctx = compose_context(retriever_chunks, claims_list, query="Ngân sách?")
        print(ctx["context_text"])
    """
    composer = ContextComposer(
        max_chunks=max_chunks,
        max_claims=max_claims,
        include_superseded=include_superseded,
    )
    return composer.compose(
        retriever_data=retriever_data,
        claims_data=claims_data,
        query=query,
        entity_map=entity_map,
        scope_context=scope_context,
    )
