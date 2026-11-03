"""
HiLark Context Composer Utility
===============================
Vị trí: server/services/knowledge/context_composer.py

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
    from services.knowledge.context_composer import ContextComposer, compose_context

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
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Union

from database.scoped_query import get_current_tenant_key

logger = logging.getLogger(__name__)


def _remove_accents(input_str: str) -> str:
    """Loại bỏ dấu tiếng Việt để so khớp từ khóa linh hoạt."""
    if not input_str:
        return ""
    nfkd = unicodedata.normalize("NFKD", input_str)
    res = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return res.replace("đ", "d").replace("Đ", "d").lower()


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
    chat_id: Optional[str] = None
    project_tag: Optional[str] = None
    tenant_key: Optional[str] = None

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
            "chat_id": self.chat_id,
            "project_tag": self.project_tag,
            "tenant_key": self.tenant_key,
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
        tenant_key: Optional[str] = None,
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
                raw_entities = get_all_entities_sync(workspace_id=None, tenant_key=tenant_key)
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
            snippet = f.get("source_snippet")
            if not snippet:
                if isinstance(src, dict):
                    snippet = src.get("snippet") or src.get("text") or src.get("source_doc")
                elif isinstance(src, str):
                    snippet = src
                elif f.get("source_doc"):
                    snippet = f.get("source_doc")

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
                    chat_id=f.get("chat_id"),
                    project_tag=f.get("project_tag"),
                    tenant_key=f.get("tenant_key"),
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
                    src_note = f" | Nguồn: \"{c.source_snippet}\"" if c.source_snippet else ""
                    if c.property in ("role", "lead", "assignee", "owner"):
                        badge = "💡 [ĐỀ XUẤT NHÂN SỰ / CHỜ DUYỆT (PROPOSED)]"
                        desc = f"(Đề xuất bởi: {speaker_name} - CHƯA ĐƯỢC DUYỆT CHÍNH THỨC)"
                    else:
                        badge = "💡 [ĐIỀU CHỈNH / ĐỀ XUẤT TỪ BIÊN BẢN / CHỜ DUYỆT (PROPOSED)]"
                        desc = f"(Ghi nhận từ thảo luận / cuộc họp - CHƯA PHÊ DUYỆT CHÍNH THỨC)"
                    lines.append(
                        f"  • {badge} {c.property} = \"{c.value}\" {desc}{src_note}"
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
        scope_context: Optional[Dict[str, Any]] = None,
        tenant_key: Optional[str] = None,
    ) -> List[NormalizedClaim]:
        """
        Lọc và căn chỉnh Claims phù hợp với câu hỏi và phạm vi nhóm chat:
        1. Chat Scope Hard Isolation: Khóa chặt theo chat_id và project_tag.
        2. Relevance Matching: So khớp đa chiều theo thuộc tính, giá trị, thực thể, trích dẫn, người nói.
        3. Clean Guard: Tự động loại bỏ claims không liên quan khi người dùng hỏi chuyện ngoài lề / HR.
        """
        if not claims:
            return []

        eff_tenant = tenant_key or get_current_tenant_key()

        query_text = (query or "").lower().strip()
        query_no_acc = _remove_accents(query_text)

        # ── 1. PHẠM VI NHÓM CHAT (CHAT SCOPE HARD ISOLATION) ──
        target_chat_id = str(scope_context.get("chat_id") or "").strip() if scope_context else ""
        target_proj = (
            str(scope_context.get("project_name") or scope_context.get("project_tag") or "").lower().strip()
            if scope_context else ""
        )

        # ── 2. XÂY DỰNG BẢN ĐỒ THỰC THỂ (ENTITY MAP) ──
        if not entity_map:
            try:
                from database.db import get_all_entities_sync
                raw_entities = get_all_entities_sync(workspace_id=None, tenant_key=eff_tenant)
                if raw_entities:
                    entity_map = {str(e.get("id")): e for e in raw_entities if isinstance(e, dict) and e.get("id")}
            except Exception:
                entity_map = {}

        # Thu thập từ khóa thực thể (entity name & aliases)
        entity_keywords_map: Dict[str, Set[str]] = {}
        matched_entity_ids: Set[str] = set()

        # Tổng hợp anchor text từ chunks văn bản trích xuất
        chunks_text = " ".join(c.content.lower() for c in (chunks or []) if c.content)
        chunks_no_acc = _remove_accents(chunks_text)

        for eid, ent in (entity_map or {}).items():
            kws: Set[str] = set()
            ename = (ent.get("name") or ent.get("canonical_name") or "").lower().strip()
            if ename and len(ename) >= 2:
                kws.add(ename)
            for a in ent.get("aliases", []):
                if a and isinstance(a, str) and len(a.strip()) >= 2:
                    kws.add(a.lower().strip())
            if kws:
                entity_keywords_map[str(eid)] = kws
                # Nếu chunks hoặc query có nhắc đến alias/tên thực thể
                for kw in kws:
                    kw_no_acc = _remove_accents(kw)
                    if (
                        (chunks_text and (kw in chunks_text or kw_no_acc in chunks_no_acc))
                        or (query_text and (kw in query_text or kw_no_acc in query_no_acc))
                    ):
                        matched_entity_ids.add(str(eid))
                        break

        # Ánh xạ thuộc tính chuẩn sang từ khóa tiếng Việt thông dụng
        PROPERTY_SYNONYMS: Dict[str, Set[str]] = {
            "deadline": {"deadline", "hạn chót", "thời hạn", "ngày nào", "ngày mấy", "khi nào", "tiến độ", "hạn", "bao giờ", "bắt đầu", "khởi động", "ngày bắt đầu", "thời gian", "lịch", "lịch trình", "dự kiến", "kết thúc", "start_date", "due_date"},
            "budget": {"ngân sách", "chi phí", "tiền", "budget", "kinh phí", "giá", "vốn", "tiền bạc"},
            "scope": {"scope", "phạm vi", "kế hoạch", "mục tiêu", "nội dung", "tính năng", "chức năng", "thay đổi", "giảm", "tăng", "bỏ", "thêm"},
            "assignee": {"assignee", "người làm", "giao cho", "phụ trách", "ai làm", "ai nhận", "trưởng", "ai phụ trách"},
            "owner": {"owner", "chủ", "phụ trách", "nắm", "quản lý", "chịu trách nhiệm"},
            "status": {"trạng thái", "tình hình", "tiến độ", "ra sao", "thế nào", "tình hình thế nào"},
            "role": {"role", "vai trò", "vị trí", "chức vụ", "làm gì", "công việc"},
            "lead": {"lead", "trưởng", "phụ trách", "chỉ huy", "quản lý"},
            "salary": {"lương", "salary", "thu nhập", "thù lao", "chi trả", "thanh toán", "bảng lương", "ngày trả lương", "pay", "payment"},
            "salary_payment_date": {"lương", "salary", "thu nhập", "thù lao", "chi trả", "thanh toán", "ngày 25", "ngày trả lương", "payment"},
        }

        matched_claims: List[NormalizedClaim] = []
        scoped_claims: List[NormalizedClaim] = []
        matched_ids: Set[str] = set()


        for claim in claims:
            cid = claim.id or f"{claim.property}_{claim.value}"
            if cid in matched_ids:
                continue

            c_status = (claim.status or "current").lower().strip()
            c_eid = str(claim.entity_id or "")
            c_prop = (claim.property or "").lower().strip()
            c_val = str(claim.value or "").lower().strip()
            c_name = (claim.entity_name or "").lower().strip()
            c_proj = (claim.project_tag or "").lower().strip()
            c_snippet = (claim.source_snippet or "").lower().strip()

            # Speaker info
            c_speaker = ""
            if claim.asserted_by and isinstance(claim.asserted_by, dict):
                c_speaker = str(claim.asserted_by.get("user_name") or "").lower().strip()

            # ── 1.1 Khóa theo chat_id nếu claim có chat_id riêng và khác target_chat_id ──
            if target_chat_id and claim.chat_id and claim.chat_id != target_chat_id:
                continue

            # ── 1.2 Khóa theo project_tag / project_name ──
            # Khi claim đã có đúng chat_id, chat scope là nguồn xác định mạnh
            # hơn entity name. Một tài liệu của dự án có thể chứa nhiều entity
            # như OMNISHOP, OnePay hoặc nhân sự; không được coi các entity đó
            # là project khác rồi loại claim hợp lệ.
            same_target_chat = bool(target_chat_id and claim.chat_id == target_chat_id)
            if target_proj and (c_proj or c_name) and not same_target_chat:
                scope_str = (c_proj or c_name).lower()
                if scope_str not in ("global", "chung", "hệ thống", "dự án", ""):
                    if target_proj not in scope_str and scope_str not in target_proj:
                        continue

            # Claim đã vượt qua lớp cô lập scope. Relevance chỉ dùng để xếp hạng,
            # không được tự động loại claim hợp lệ khỏi context.
            scoped_claims.append(claim)

            # ── 2. RELEVANCE MATCHING ──
            is_matched = False

            # Chiều 1: So khớp Thuộc tính nghiệp vụ
            synonyms = set(PROPERTY_SYNONYMS.get(c_prop, set()))
            synonyms.add(c_prop)
            if "_" in c_prop:
                synonyms.add(c_prop.replace("_", " "))
                synonyms.update(c_prop.split("_"))
            if any(
                (query_text and (syn in query_text or _remove_accents(syn) in query_no_acc))
                or (chunks_text and (syn in chunks_text or _remove_accents(syn) in chunks_no_acc))
                for syn in synonyms if syn and len(syn) >= 2
            ):
                is_matched = True

            # Chiều 2: So khớp Giá trị cụ thể
            if not is_matched and c_val and len(c_val) >= 2:
                if c_val in query_text or _remove_accents(c_val) in query_no_acc:
                    is_matched = True

            # Chiều 3: So khớp Thực thể liên quan (qua entity_id hoặc tên thực thể)
            if not is_matched and c_eid and c_eid in matched_entity_ids:
                is_matched = True
            elif not is_matched and c_name and len(c_name) >= 3 and c_name not in ("chung", "hệ thống", "dự án", "global"):
                if (
                    (query_text and (c_name in query_text or _remove_accents(c_name) in query_no_acc))
                    or (chunks_text and (c_name in chunks_text or _remove_accents(c_name) in chunks_no_acc))
                ):
                    is_matched = True

            if is_matched:
                matched_claims.append(claim)
                matched_ids.add(cid)

        # ── 3. SOFT FALLBACK: giữ claim cùng scope nhưng không match keyword ──
        if not matched_claims:
            is_general_status_query = any(
                w in query_no_acc for w in ("tinh hinh", "tien do", "the nao", "ra sao", "thong tin", "tong quan", "ke hoach")
            )
            if is_general_status_query or target_chat_id or target_proj:
                # Chỉ fallback sang claim hiện hành. Proposed vẫn tuân thủ cơ chế duyệt.
                overview_claims = [
                    c for c in scoped_claims
                    if c.status == "current"
                ]
                if overview_claims:
                    return overview_claims[: self.max_claims]
            # Mặc định: Trả về rỗng [] để bảo vệ độ sạch của context khi hỏi HR / ngoài lề
            return []

        # Match liên quan lên trước, các claim current cùng scope theo sau.
        ranked_claims = list(matched_claims)
        ranked_ids = {c.id for c in matched_claims}
        ranked_claims.extend(
            c for c in scoped_claims
            if c.status == "current" and c.id not in ranked_ids
        )
        return ranked_claims[: self.max_claims]

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
        tenant_key: Optional[str] = None,
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
          - tenant_key: Mã doanh nghiệp để bảo đảm cách ly 100% dữ liệu đa khách thuê
        """
        eff_tenant = tenant_key or get_current_tenant_key()

        # Tự động nạp entity_map nếu chưa được cung cấp
        if not entity_map:
            try:
                from database.db import get_all_entities_sync
                raw_entities = get_all_entities_sync(workspace_id=None, tenant_key=eff_tenant)
                if raw_entities:
                    entity_map = {str(e.get("id")): e for e in raw_entities if isinstance(e, dict) and e.get("id")}
            except Exception:
                entity_map = {}

        # 1. Chuẩn hóa dữ liệu
        chunks = self.normalize_retriever_data(retriever_data)
        claims = self.normalize_claims_data(claims_data, entity_map=entity_map, tenant_key=eff_tenant)

        # 1.1. Lọc bảo vệ nghiêm ngặt đa doanh nghiệp (Defense-in-depth Cross-Tenant Isolation):
        # Nếu có tenant_key, loại bỏ mọi claim KHÔNG thuộc đúng tenant này.
        # ⚠️ Strict mode: không có escape hatch "not c.tenant_key" nữa.
        # Claim legacy không có tenant_key sẽ bị loại bỏ để tránh rò rỉ cross-tenant.
        # Xem: docs/project-memory/DECISIONS.md — B3 fix (2026-11-03)
        if eff_tenant:
            claims = [c for c in claims if c.tenant_key == eff_tenant]

        # 2. Tự động so khớp chéo Thực thể (Entity Alignment) nếu bật auto_align và có (chunks or query)
        if auto_align and claims and (chunks or query):
            claims = self.align_claims_with_retriever(
                chunks=chunks,
                claims=claims,
                query=query,
                entity_map=entity_map,
                scope_context=scope_context,
                tenant_key=eff_tenant,
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
