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

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Union


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
    status: str = "current"  # current, superseded, conflicted, uncertain
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    entity_type: Optional[str] = None
    replaces: Optional[str] = None
    source_snippet: Optional[str] = None
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
        }


# =============================================================================
# CONTEXT COMPOSER CLASS
# =============================================================================

class ContextComposer:
    """
    Công cụ hợp nhất dữ liệu từ WeKnora Retriever và MongoDB Claims
    thành prompt context chuẩn cho LLM Grounded Generation.
    """

    DEFAULT_CONFLICT_RULES = """NGUYÊN TẮC GIẢI QUYẾT XUNG ĐỘT (CONFLICT RESOLUTION):
1. ĐỘ ƯU TIÊN CAO NHẤT: Thông tin [CURRENT] từ Mệnh đề cập nhật (Phần 2) LUÔN CÓ ĐỘ ƯU TIÊN CAO HƠN thông tin trong Tài liệu văn bản (Phần 1) vì đây là các quyết định, phê duyệt và trao đổi thời gian thực mới nhất.
2. NÊU RÕ BIẾN ĐỘNG LỊCH SỬ: Nếu phát hiện mâu thuẫn giữa Tài liệu và Mệnh đề (ví dụ: tài liệu ghi giá trị A nhưng mệnh đề đã cập nhật giá trị B), hãy giải thích rõ: "Theo tài liệu gốc là A, tuy nhiên theo cập nhật thảo luận mới nhất đã được điều chỉnh thành B".
3. TRÍCH DẪN RÕ RÀNG: Ghi rõ căn cứ từ tài liệu nào hoặc từ tin nhắn cập nhật của ai nếu có."""

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
                    item.get("document_name")
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
                        entities_lookup[eid] = {"name": ename, "type": etype}

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
                            entities_lookup[eid] = ent

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
            if not self.include_superseded and status == "superseded":
                continue

            eid = str(f.get("entity_id") or "")
            ename = f.get("_entity_name")
            etype = f.get("_entity_type")

            if not ename and eid and eid in entities_lookup:
                ent_obj = entities_lookup[eid]
                ename = ent_obj.get("name") or ent_obj.get("canonical_name")
                etype = ent_obj.get("type")

            src = f.get("source")
            snippet = None
            if isinstance(src, dict):
                snippet = src.get("snippet") or src.get("text")
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
                    created_at=f.get("created_at") or f.get("updated_at"),
                )
            )

        # Sắp xếp: CURRENT và UNCERTAIN ưu tiên trước SUPERSEDED
        def claim_sort_key(c: NormalizedClaim):
            status_priority = {"current": 0, "uncertain": 1, "conflicted": 2, "superseded": 3}
            return (status_priority.get(c.status, 4), c.entity_name or "")

        claims.sort(key=claim_sort_key)
        return claims[: self.max_claims]

    # -------------------------------------------------------------------------
    # 2. ĐÓNG GÓI NỘI DUNG (FORMATTING & RENDERING)
    # -------------------------------------------------------------------------

    def format_retriever_section(self, chunks: List[RetrievedChunk]) -> str:
        """Định dạng phân vùng tài liệu từ WeKnora."""
        if not chunks:
            return "(Không có dữ liệu tài liệu trích xuất từ WeKnora)"

        lines: List[str] = []
        for idx, c in enumerate(chunks, 1):
            chunk_tag = f" [Chunk ID: {c.chunk_id}]" if c.chunk_id else ""
            score_tag = f" (Score: {c.score:.2f})" if c.score is not None else ""
            lines.append(f"--- [Tài liệu {idx}]: {c.doc_name}{chunk_tag}{score_tag} ---")
            lines.append(c.content.strip())
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

            # 1. Thuộc tính hiện hành (Active / Current)
            active = [c for c in ent_claims if c.status in ("current", "uncertain", "conflicted")]
            if active:
                for c in active:
                    st_badge = f"[{c.status.upper()}]"
                    rep_note = f" (Thay thế cho: {c.replaces})" if c.replaces else ""
                    src_note = f" | Nguồn: \"{c.source_snippet}\"" if c.source_snippet else ""
                    lines.append(f"  • {st_badge} {c.property} = \"{c.value}\"{rep_note}{src_note}")

            # 2. Thuộc tính lịch sử (Superseded)
            superseded = [c for c in ent_claims if c.status == "superseded"]
            if superseded and self.include_superseded:
                for c in superseded:
                    src_note = f" | Từng nói: \"{c.source_snippet}\"" if c.source_snippet else ""
                    lines.append(f"  • [LỊCH SỬ/SUPERSEDED] {c.property} = \"{c.value}\" (Đã bị thay thế){src_note}")

            lines.append("")

        return "\n".join(lines).strip()

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
    ) -> Dict[str, Any]:
        """
        Đóng gói toàn diện WeKnora Retriever + Claims Data thành 1 Context hoàn chỉnh.

        Trả về:
          - context_text: Đoạn văn bản Context hoàn chỉnh có phân vùng rõ ràng.
          - sections: Dict chứa riêng từng section (documents, claims, rules).
          - metadata: Thống kê số lượng chunks, số lượng claims, danh sách citations.
        """
        # 1. Chuẩn hóa dữ liệu
        chunks = self.normalize_retriever_data(retriever_data)
        claims = self.normalize_claims_data(claims_data, entity_map=entity_map)

        # 2. Xây dựng từng section
        docs_text = self.format_retriever_section(chunks)
        claims_text = self.format_claims_section(claims)

        # 3. Tạo context text
        context_parts: List[str] = [
            "=== BỘ BỐI CẢNH TRI THỨC TỔNG HỢP (HIERARCHICAL KNOWLEDGE CONTEXT) ===",
            "",
            "--- PHẦN 1: TÀI LIỆU DỰ ÁN & VĂN BẢN (WEKNORA RETRIEVER) ---",
            docs_text,
            "",
            "--- PHẦN 2: THỰC TẾ CẬP NHẬT & MỆNH ĐỀ ĐỘNG (MONGODB CLAIMS) ---",
            claims_text,
            "",
            "--- PHẦN 3: NGUYÊN TẮC XỬ LÝ DỮ LIỆU ---",
            self.conflict_rules,
        ]

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
        chunks = self.normalize_retriever_data(retriever_data)
        claims = self.normalize_claims_data(claims_data, entity_map=entity_map)

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
    include_superseded: bool = True,
    max_chunks: int = 8,
    max_claims: int = 25,
) -> Dict[str, Any]:
    """
    Hàm tiện ích nhanh (Functional API) để đóng gói context.

    Ví dụ:
        ctx = compose_context(retriever_chunks, claims_list, query="Ngân sách?")
        print(ctx["prompt_ready"])
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
    )
