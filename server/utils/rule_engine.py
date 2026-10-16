"""
HiLark Unified Rule Engine (Security & Dynamic Label Sanitizer)
=============================================================
Vị trí: server/utils/rule_engine.py

Mục đích:
    Bộ lọc bảo mật và chuẩn hóa tri thức tập trung (Unified Rule Engine) kết nối trực tiếp
    với bộ nhãn cấm (forbidden_labels) từ Lark Base (Chat Scope Record).
    
    Được thiết kế dùng chung làm chốt chặn bảo vệ cuối cùng trước khi đưa dữ liệu vào
    ContextComposer cho cả:
      1. WeKnora Chunks (Tài liệu tĩnh / Kiến thức KB sau khi JEV rerank)
      2. MongoDB Claims (Mệnh đề / Tri thức động từ bộ nhớ phân cấp)

Cơ chế lọc đa tầng (Multi-tier Dynamic Resolution):
    Tầng 1: Canonical Property Mapping
      - Tự động ánh xạ các nhãn cấm chuẩn ("Ngân sách", "Lương", "Tài chính", ...)
        sang các canonical properties: budget, cost, price, salary, compensation...
    Tầng 2: Dynamic Literal Substring Scan (Cho bất kỳ nhãn mới nào từ Lark Base)
      - Bất kỳ khi nào Sếp tạo thêm nhãn cấm mới trên Lark Base (ví dụ: "Thầu phụ",
        "Đối tác VIP", "Kế hoạch Q4", "NDA"), Rule Engine tự động quét so khớp chuỗi
        (cả có dấu và không dấu, chặn word boundary chuẩn tiếng Việt) vào:
          + Claim: property, value, source_snippet
          + Chunk: content, document_name
        -> Loại bỏ ngay lập tức mà KHÔNG cần sửa code.
    Tầng 3: Data Quality & Validity Filter
      - Lọc bỏ chunks rỗng hoặc quá ngắn, claims thiếu property hoặc value rỗng.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("HiLark.RuleEngine")


# =============================================================================
# 1. HELPER FUNCTIONS: NORMALIZATION & ACCENT STRIPPING
# =============================================================================

def remove_vietnamese_accents(text: str) -> str:
    """
    Chuyển đổi văn bản tiếng Việt có dấu thành không dấu an toàn.
    Hỗ trợ cả đ/Đ và các ký tự tổ hợp Unicode (NFD/NFKD).
    """
    if not text or not isinstance(text, str):
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return without_accents.replace("đ", "d").replace("Đ", "D")


def parse_labels(raw_labels: Any) -> List[str]:
    """
    Chuẩn hóa đầu vào nhãn từ Lark Base hoặc Scope Record:
      - None / Rỗng -> []
      - String ("Ngân sách, Lương; Thầu phụ") -> ["Ngân sách", "Lương", "Thầu phụ"]
      - List các string hoặc List các dict (Lark Base Multi-select field: [{"text": "..."}])
    """
    if not raw_labels:
        return []
    
    extracted: List[str] = []
    if isinstance(raw_labels, str):
        parts = raw_labels.replace(";", ",").replace("\n", ",").split(",")
        extracted = [p.strip() for p in parts if p.strip()]
    elif isinstance(raw_labels, list):
        for item in raw_labels:
            if isinstance(item, str):
                if item.strip():
                    extracted.append(item.strip())
            elif isinstance(item, dict):
                val = item.get("text") or item.get("name") or item.get("value") or ""
                if str(val).strip():
                    extracted.append(str(val).strip())
    
    # Loại bỏ trùng lặp giữ nguyên thứ tự
    seen = set()
    cleaned = []
    for lb in extracted:
        low = lb.lower()
        if low not in seen:
            seen.add(low)
            cleaned.append(lb)
    return cleaned


# =============================================================================
# 2. CANONICAL PROPERTIES MAPPING
# =============================================================================

CANONICAL_FORBIDDEN_PROPERTIES: Dict[str, Set[str]] = {
    # Ngân sách & Tiền bạc
    "ngân sách": {"budget", "cost", "price", "fee", "expense", "financial", "fund"},
    "ngan sach": {"budget", "cost", "price", "fee", "expense", "financial", "fund"},
    "chi phí": {"budget", "cost", "price", "fee", "expense"},
    "chi phi": {"budget", "cost", "price", "fee", "expense"},
    "giá": {"price", "cost", "budget", "pricing"},
    "gia": {"price", "cost", "budget", "pricing"},
    "tài chính": {"budget", "financial", "finance", "revenue", "profit", "cashflow"},
    "tai chinh": {"budget", "financial", "finance", "revenue", "profit", "cashflow"},
    
    # Lương & Thu nhập nhân sự
    "lương": {"salary", "compensation", "income", "payroll", "wage"},
    "luong": {"salary", "compensation", "income", "payroll", "wage"},
    "thu nhập": {"salary", "compensation", "income", "revenue"},
    "thu nhap": {"salary", "compensation", "income", "revenue"},
    "thù lao": {"salary", "compensation", "fee"},
    "thu lao": {"salary", "compensation", "fee"},
    
    # Hợp đồng & Pháp lý
    "hợp đồng": {"contract", "agreement", "deal", "nda", "sign"},
    "hop dong": {"contract", "agreement", "deal", "nda", "sign"},
    "thỏa thuận": {"agreement", "contract", "nda"},
    "thoa thuan": {"agreement", "contract", "nda"},
    "đấu thầu": {"bid", "bidding", "tender"},
    "dau thau": {"bid", "bidding", "tender"},
    
    # Doanh số & Lợi nhuận
    "doanh thu": {"revenue", "sales", "income"},
    "doanh so": {"sales", "revenue"},
    "doanh số": {"sales", "revenue"},
    "lợi nhuận": {"profit", "margin"},
    "loi nhuan": {"profit", "margin"},
}


# =============================================================================
# 3. RESULT DATA STRUCTURES
# =============================================================================

@dataclass
class SanitizeResult:
    """Kết quả sau khi lọc bảo mật qua Rule Engine."""
    clean_chunks: List[Dict[str, Any]] = field(default_factory=list)
    clean_claims: List[Dict[str, Any]] = field(default_factory=list)
    dropped_chunks: List[Dict[str, Any]] = field(default_factory=list)
    dropped_claims: List[Dict[str, Any]] = field(default_factory=list)
    forbidden_labels: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def __iter__(self):
        """Hỗ trợ tuple unpacking trực tiếp: clean_chunks, clean_claims = rule_engine.sanitize(...)"""
        return iter((self.clean_chunks, self.clean_claims))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clean_chunks_count": len(self.clean_chunks),
            "clean_claims_count": len(self.clean_claims),
            "dropped_chunks_count": len(self.dropped_chunks),
            "dropped_claims_count": len(self.dropped_claims),
            "forbidden_labels": self.forbidden_labels,
            "stats": self.stats,
        }


# =============================================================================
# 4. UNIFIED RULE ENGINE CLASS
# =============================================================================

class UnifiedRuleEngine:
    """
    Unified Rule Engine cho HiLark.
    Xử lý kiểm tra và loại bỏ các tri thức vi phạm nhãn bảo mật từ Lark Base.
    """

    def __init__(self, canonical_map: Optional[Dict[str, Set[str]]] = None):
        self.canonical_map = canonical_map or CANONICAL_FORBIDDEN_PROPERTIES

    def _build_matchers(self, forbidden_labels: List[str]) -> Tuple[Set[str], List[re.Pattern], List[re.Pattern]]:
        """
        Xây dựng bộ so khớp bảo mật gồm:
          1. blocked_properties: Tập các thuộc tính canonical bị cấm (e.g. 'budget', 'salary')
          2. accented_regexes: Regex bắt chính xác có dấu trên văn bản gốc
          3. unaccented_regexes: Regex bắt không dấu (cho trường hợp người chat/tài liệu viết không dấu)
        """
        blocked_properties: Set[str] = set()
        accented_regexes: List[re.Pattern] = []
        unaccented_regexes: List[re.Pattern] = []

        for label in forbidden_labels:
            clean_lbl = label.strip()
            if not clean_lbl:
                continue

            lbl_lower = clean_lbl.lower()
            lbl_unaccent = remove_vietnamese_accents(lbl_lower)

            # Tầng 1: Thu nạp các canonical properties bị cấm (khớp chính xác hoặc biên từ)
            for key, props in self.canonical_map.items():
                is_key_matched = (
                    key == lbl_lower
                    or key == lbl_unaccent
                    or bool(re.search(rf"(?<!\w){re.escape(key)}(?!\w)", lbl_lower))
                    or bool(re.search(rf"(?<!\w){re.escape(key)}(?!\w)", lbl_unaccent))
                )
                if is_key_matched:
                    blocked_properties.update(props)

            # Đưa chính tên nhãn (nếu viết dạng slug/thuộc tính như 'thau_phu') vào blocked_properties
            slug_prop = lbl_unaccent.replace(" ", "_")
            blocked_properties.add(slug_prop)
            blocked_properties.add(lbl_lower)
            blocked_properties.add(lbl_unaccent)

            # Tầng 2: Xây dựng Regex quét chuỗi con với Word Boundary tiếng Việt
            # Regex bảo vệ biên từ Unicode: (?<!\w) từ (?!\w)
            try:
                # 2.1 Accented pattern (tìm từ có dấu trong văn bản gốc)
                pattern_acc = re.compile(rf"(?<!\w){re.escape(lbl_lower)}(?!\w)", re.IGNORECASE)
                accented_regexes.append(pattern_acc)

                # 2.2 Unaccented pattern:
                # Chỉ áp dụng cho nhãn từ 2 từ trở lên hoặc nhãn thuần ASCII để tránh false-positive
                # (Ví dụ: tránh nhãn 'lương' unaccented thành 'luong' vô tình khớp chữ 'số lượng' unaccented)
                words = lbl_lower.split()
                if len(words) > 1 or lbl_lower.isascii():
                    pattern_unacc = re.compile(rf"(?<!\w){re.escape(lbl_unaccent)}(?!\w)", re.IGNORECASE)
                    unaccented_regexes.append(pattern_unacc)
            except Exception as e:
                logger.warning(f"Lỗi khi compile regex cho nhãn cấm '{label}': {e}")

        return blocked_properties, accented_regexes, unaccented_regexes

    def is_text_violating(
        self,
        text: str,
        accented_regexes: List[re.Pattern],
        unaccented_regexes: List[re.Pattern],
    ) -> Tuple[bool, Optional[str]]:
        """
        Kiểm tra xem một đoạn văn bản (text) có chứa nhãn cấm hay không.
        Trả về (is_violating, matched_pattern_str).
        """
        if not text or not isinstance(text, str):
            return False, None

        # 1. So khớp trên text gốc
        text_lower = text.lower()
        for pat in accented_regexes:
            match = pat.search(text_lower)
            if match:
                return True, match.group(0)

        # 2. So khớp trên text không dấu (cho nhãn nhiều từ hoặc ASCII)
        if unaccented_regexes:
            text_unaccent = remove_vietnamese_accents(text_lower)
            for pat in unaccented_regexes:
                match = pat.search(text_unaccent)
                if match:
                    return True, match.group(0)

        return False, None

    def is_claim_violating(
        self,
        claim_dict: Dict[str, Any],
        blocked_properties: Set[str],
        accented_regexes: List[re.Pattern],
        unaccented_regexes: List[re.Pattern],
    ) -> Tuple[bool, Optional[str]]:
        """
        Kiểm tra xem một Claim/Fact có vi phạm nhãn cấm hay không.
        Kiểm tra qua:
          - property (theo canonical & slug match an toàn bằng token intersection)
          - value (chuỗi con cấm)
          - source_snippet (chuỗi trích dẫn gốc)
        """
        # 1. Kiểm tra Property bằng token intersection (tránh nhầm lẫn 'fee' trong 'feedback' hay 'gia' trong 'giai_doan')
        prop = str(claim_dict.get("property") or claim_dict.get("predicate", "")).strip().lower()
        prop_unaccent = remove_vietnamese_accents(prop)
        if prop in blocked_properties or prop_unaccent in blocked_properties:
            return True, f"property='{prop}' thuộc nhóm bị cấm"

        prop_tokens = set(re.split(r"[\s_.-]+", prop)) | set(re.split(r"[\s_.-]+", prop_unaccent))
        intersect = (prop_tokens & blocked_properties) - {""}
        if intersect:
            return True, f"property='{prop}' chứa từ khóa cấm '{list(intersect)[0]}'"

        # 2. Kiểm tra Value
        val_str = str(claim_dict.get("value", "")).strip()
        if val_str:
            is_vio, matched = self.is_text_violating(val_str, accented_regexes, unaccented_regexes)
            if is_vio:
                return True, f"value chứa từ khóa cấm '{matched}'"

        # 3. Kiểm tra Source Snippet
        snippet = str(claim_dict.get("source_snippet") or claim_dict.get("snippet", "")).strip()
        if snippet:
            is_vio, matched = self.is_text_violating(snippet, accented_regexes, unaccented_regexes)
            if is_vio:
                return True, f"source_snippet chứa từ khóa cấm '{matched}'"

        return False, None

    def is_chunk_violating(
        self,
        chunk_dict: Dict[str, Any],
        accented_regexes: List[re.Pattern],
        unaccented_regexes: List[re.Pattern],
    ) -> Tuple[bool, Optional[str]]:
        """
        Kiểm tra xem một WeKnora Chunk có vi phạm nhãn cấm hay không.
        Kiểm tra qua content và doc_name/knowledge_title.
        """
        # 1. Kiểm tra content
        content = str(chunk_dict.get("content") or chunk_dict.get("text", "")).strip()
        if content:
            is_vio, matched = self.is_text_violating(content, accented_regexes, unaccented_regexes)
            if is_vio:
                return True, f"content chứa từ khóa cấm '{matched}'"

        # 2. Kiểm tra document_name
        doc_name = str(
            chunk_dict.get("document_name")
            or chunk_dict.get("doc_name")
            or chunk_dict.get("knowledge_title", "")
        ).strip()
        if doc_name:
            is_vio, matched = self.is_text_violating(doc_name, accented_regexes, unaccented_regexes)
            if is_vio:
                return True, f"document_name='{doc_name}' chứa từ khóa cấm '{matched}'"

        return False, None

    def sanitize(
        self,
        chunks: Optional[List[Union[Dict[str, Any], Any]]] = None,
        claims: Optional[List[Union[Dict[str, Any], Any]]] = None,
        forbidden_labels: Optional[Union[List[str], str]] = None,
        allowed_labels: Optional[Union[List[str], str]] = None,
        query: Optional[str] = None,
        project_context: Optional[str] = None,
    ) -> SanitizeResult:
        """
        Lọc toàn diện cả Chunks và Claims dựa trên nhãn cấm (forbidden_labels) từ Lark Base.
        
        Trả về SanitizeResult chứa:
          - clean_chunks: Các chunk an toàn
          - clean_claims: Các claim an toàn
          - dropped_chunks: Các chunk bị loại bỏ kèm lý do
          - dropped_claims: Các claim bị loại bỏ kèm lý do
          - stats: Thống kê số lượng
        """
        labels = parse_labels(forbidden_labels)
        raw_chunks = chunks or []
        raw_claims = claims or []

        # Nếu không có nhãn cấm nào, chỉ cần validate chất lượng cơ bản
        if not labels:
            clean_chunks = []
            for c in raw_chunks:
                c_dict = c if isinstance(c, dict) else (c.to_dict() if hasattr(c, "to_dict") else vars(c))
                content = str(c_dict.get("content") or c_dict.get("text", "")).strip()
                if len(content) >= 3:
                    clean_chunks.append(c_dict)

            clean_claims = []
            for cl in raw_claims:
                cl_dict = cl if isinstance(cl, dict) else (cl.to_dict() if hasattr(cl, "to_dict") else vars(cl))
                prop = str(cl_dict.get("property") or cl_dict.get("predicate", "")).strip()
                if prop:
                    clean_claims.append(cl_dict)

            return SanitizeResult(
                clean_chunks=clean_chunks,
                clean_claims=clean_claims,
                dropped_chunks=[],
                dropped_claims=[],
                forbidden_labels=[],
                stats={
                    "total_chunks": len(raw_chunks),
                    "passed_chunks": len(clean_chunks),
                    "dropped_chunks": 0,
                    "total_claims": len(raw_claims),
                    "passed_claims": len(clean_claims),
                    "dropped_claims": 0,
                },
            )

        # Xây dựng bộ matcher từ danh sách nhãn cấm
        blocked_properties, accented_regexes, unaccented_regexes = self._build_matchers(labels)

        # ── 1. LỌC CLAIMS (MONGODB FACTS) ──
        clean_claims: List[Dict[str, Any]] = []
        dropped_claims: List[Dict[str, Any]] = []

        for cl in raw_claims:
            cl_dict = cl if isinstance(cl, dict) else (cl.to_dict() if hasattr(cl, "to_dict") else vars(cl))
            prop = str(cl_dict.get("property") or cl_dict.get("predicate", "")).strip()
            if not prop:
                continue

            is_vio, reason = self.is_claim_violating(
                cl_dict,
                blocked_properties,
                accented_regexes,
                unaccented_regexes,
            )

            if is_vio:
                claim_id = cl_dict.get("id") or cl_dict.get("_id") or "unknown"
                logger.warning(
                    f"🛡️ [RULE ENGINE - CLAIM DROP] Claim '{claim_id}' (prop='{prop}') bị loại bỏ. Lý do: {reason}"
                )
                dropped_item = dict(cl_dict)
                dropped_item["_drop_reason"] = reason
                dropped_claims.append(dropped_item)
            else:
                clean_claims.append(cl_dict)

        # ── 2. LỌC CHUNKS (WEKNORA KB) ──
        clean_chunks: List[Dict[str, Any]] = []
        dropped_chunks: List[Dict[str, Any]] = []

        for c in raw_chunks:
            c_dict = c if isinstance(c, dict) else (c.to_dict() if hasattr(c, "to_dict") else vars(c))
            content = str(c_dict.get("content") or c_dict.get("text", "")).strip()
            if len(content) < 3:
                continue

            is_vio, reason = self.is_chunk_violating(
                c_dict,
                accented_regexes,
                unaccented_regexes,
            )

            if is_vio:
                cid = c_dict.get("chunk_id") or c_dict.get("id") or "unknown"
                doc = c_dict.get("document_name") or c_dict.get("doc_name") or "tài liệu"
                logger.warning(
                    f"🛡️ [RULE ENGINE - CHUNK DROP] Chunk '{cid}' từ '{doc}' bị loại bỏ. Lý do: {reason}"
                )
                dropped_item = dict(c_dict)
                dropped_item["_drop_reason"] = reason
                dropped_chunks.append(dropped_item)
            else:
                clean_chunks.append(c_dict)

        result = SanitizeResult(
            clean_chunks=clean_chunks,
            clean_claims=clean_claims,
            dropped_chunks=dropped_chunks,
            dropped_claims=dropped_claims,
            forbidden_labels=labels,
            stats={
                "total_chunks": len(raw_chunks),
                "passed_chunks": len(clean_chunks),
                "dropped_chunks": len(dropped_chunks),
                "total_claims": len(raw_claims),
                "passed_claims": len(clean_claims),
                "dropped_claims": len(dropped_claims),
            },
        )

        logger.info(
            f"🛡️ [RULE ENGINE] Đã khử nhiễm ngữ cảnh với {len(labels)} nhãn cấm: "
            f"Chunks ({len(clean_chunks)}/{len(raw_chunks)} giữ lại), "
            f"Claims ({len(clean_claims)}/{len(raw_claims)} giữ lại)."
        )
        return result


# Singleton instance cho toàn hệ thống
rule_engine = UnifiedRuleEngine()


def sanitize(
    chunks: Optional[List[Union[Dict[str, Any], Any]]] = None,
    claims: Optional[List[Union[Dict[str, Any], Any]]] = None,
    forbidden_labels: Optional[Union[List[str], str]] = None,
    allowed_labels: Optional[Union[List[str], str]] = None,
    query: Optional[str] = None,
    project_context: Optional[str] = None,
) -> SanitizeResult:
    """Convenience module-level function để sanitize trực tiếp."""
    return rule_engine.sanitize(
        chunks=chunks,
        claims=claims,
        forbidden_labels=forbidden_labels,
        allowed_labels=allowed_labels,
        query=query,
        project_context=project_context,
    )
