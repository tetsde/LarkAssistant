#!/usr/bin/env python3
"""
HiLark Memory & Claim Query Module
===================================
Vị trí: server/tests/query_claims.py

Mục đích:
    Module chuyên trách truy vấn, tra cứu và phân tích các Mệnh đề (Claims / Facts)
    đã được trích xuất và lưu trữ trong bộ nhớ phân cấp (Hierarchical Memory) của HiLark.

Các tính năng chính:
    1. Tra cứu theo Thực thể (Entity): Lấy thông tin tổng hợp, active facts & history facts.
    2. Tra cứu theo Thuộc tính (Property): Lấy giá trị hiện tại hoặc toàn bộ lịch sử (Lineage / Timeline).
    3. Lần vết chuỗi thay thế (Fact Lineage / Audit Trail):
       Biết rõ fact nào thay thế fact nào, từ tin nhắn nào, ai nói, ngữ cảnh ra sao.
    4. Tìm kiếm tự do theo từ khóa (Keyword Search).
    5. Hỏi đáp thông minh (Ask AI grounded in Facts): Sử dụng Gemini để trả lời câu hỏi
       dựa CHÍNH XÁC trên các claims được trích xuất (có trích dẫn nguồn).
    6. Interactive Console & CLI Tool: Hỗ trợ cả import làm thư viện lẫn chạy trực tiếp terminal.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

# Đảm bảo import được modules từ server
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

try:
    from models.memory import Entity, Fact, FactStatus, build_entity_tree
    from utils.llm_extractor import GeminiClient
except ImportError:
    # Fallback nếu chạy độc lập
    Entity = None
    Fact = None
    FactStatus = None
    GeminiClient = None


# ANSI Color codes cho terminal
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_RED = "\033[91m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_BLUE = "\033[94m"
C_PURPLE = "\033[95m"
C_CYAN = "\033[96m"
C_DIM = "\033[2m"


DEFAULT_SESSION_FILE = os.path.join(SERVER_ROOT, "tests", "interactive_session_output.json")
DATA_DIR = os.path.join(SERVER_ROOT, "utils", "data")
ENTITY_STORE_PATH = os.path.join(DATA_DIR, "entity_store.json")
FACT_STORE_PATH = os.path.join(DATA_DIR, "fact_store.json")


class ClaimQuerier:
    """
    Công cụ truy vấn Mệnh đề / Facts từ bộ nhớ phân cấp.
    Hỗ trợ nạp từ interactive_session_output.json, entity/fact store hoặc object truyền vào.
    """

    def __init__(self, data_source: Optional[Union[str, Dict[str, Any]]] = None):
        self.data_source = data_source or self._discover_data_source()
        self.entities: List[Dict[str, Any]] = []
        self.facts: List[Dict[str, Any]] = []
        self.history_steps: List[Dict[str, Any]] = []
        
        # Indexes phục vụ tra cứu O(1)
        self.entities_by_id: Dict[str, Dict[str, Any]] = {}
        self.entities_by_name: Dict[str, Dict[str, Any]] = {}
        self.alias_to_entity_id: Dict[str, str] = {}
        self.facts_by_id: Dict[str, Dict[str, Any]] = {}
        self.active_facts_by_entity_id: Dict[str, List[Dict[str, Any]]] = {}
        self.history_facts_by_entity_id: Dict[str, List[Dict[str, Any]]] = {}

        self.reload()

    def _discover_data_source(self) -> str:
        """Tự động tìm kiếm file dữ liệu sẵn có."""
        if os.path.exists(DEFAULT_SESSION_FILE):
            return DEFAULT_SESSION_FILE
        if os.path.exists(ENTITY_STORE_PATH) and os.path.exists(FACT_STORE_PATH):
            return "STORE_FILES"
        return DEFAULT_SESSION_FILE

    def reload(self) -> None:
        """Nạp lại dữ liệu và xây dựng lại indexes."""
        self.entities = []
        self.facts = []
        self.history_steps = []

        if isinstance(self.data_source, dict):
            self._load_from_dict(self.data_source)
        elif isinstance(self.data_source, str):
            if self.data_source == "STORE_FILES":
                self._load_from_stores()
            elif os.path.exists(self.data_source):
                try:
                    with open(self.data_source, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self._load_from_dict(data)
                except Exception as e:
                    print(f"{C_RED}Lỗi khi đọc file {self.data_source}: {e}{C_RESET}")
        
        self._build_indexes()

    def _load_from_dict(self, data: Dict[str, Any]) -> None:
        """Nạp từ cấu trúc JSON session."""
        self.entities = data.get("entities", [])
        self.history_steps = data.get("history", [])

        # Thu thập toàn bộ facts từ entities tree
        all_facts = []
        for ent in self.entities:
            for f in ent.get("active_facts", []):
                all_facts.append(f)
            for f in ent.get("history_facts", []):
                all_facts.append(f)
        
        # Nếu có list facts riêng
        if "facts" in data and isinstance(data["facts"], list):
            for f in data["facts"]:
                if f not in all_facts:
                    all_facts.append(f)

        self.facts = all_facts

    def _load_from_stores(self) -> None:
        """Nạp từ entity_store.json và fact_store.json."""
        raw_entities = []
        raw_facts = []
        if os.path.exists(ENTITY_STORE_PATH):
            with open(ENTITY_STORE_PATH, "r", encoding="utf-8") as f:
                raw_entities = json.load(f)
        if os.path.exists(FACT_STORE_PATH):
            with open(FACT_STORE_PATH, "r", encoding="utf-8") as f:
                raw_facts = json.load(f)

        if build_entity_tree:
            self.entities = build_entity_tree(raw_entities, raw_facts)
        else:
            self.entities = raw_entities
        self.facts = raw_facts

    def _build_indexes(self) -> None:
        """Xây dựng chỉ mục nhanh."""
        self.entities_by_id.clear()
        self.entities_by_name.clear()
        self.alias_to_entity_id.clear()
        self.facts_by_id.clear()
        self.active_facts_by_entity_id.clear()
        self.history_facts_by_entity_id.clear()

        for ent in self.entities:
            ent_id = ent.get("id") or ent.get("_id")
            if not ent_id:
                continue
            self.entities_by_id[ent_id] = ent
            
            name = (ent.get("name") or ent.get("canonical_name") or "").strip()
            if name:
                self.entities_by_name[name.lower()] = ent

            aliases = ent.get("aliases") or []
            for alias in aliases:
                if alias:
                    self.alias_to_entity_id[alias.lower().strip()] = ent_id

            # Facts của entity
            active = ent.get("active_facts", [])
            history = ent.get("history_facts", [])
            self.active_facts_by_entity_id[ent_id] = list(active)
            self.history_facts_by_entity_id[ent_id] = list(history)

            for f in active:
                fid = f.get("id") or f.get("_id")
                if fid:
                    self.facts_by_id[fid] = f
            for f in history:
                fid = f.get("id") or f.get("_id")
                if fid:
                    self.facts_by_id[fid] = f

        # Bổ sung facts độc lập nếu có
        for f in self.facts:
            fid = f.get("id") or f.get("_id")
            if fid and fid not in self.facts_by_id:
                self.facts_by_id[fid] = f
                eid = f.get("entity_id")
                if eid:
                    if f.get("status") == "superseded":
                        self.history_facts_by_entity_id.setdefault(eid, []).append(f)
                    else:
                        self.active_facts_by_entity_id.setdefault(eid, []).append(f)

    # =========================================================================
    # 1. TRUY VẤN THỰC THỂ (ENTITY QUERY)
    # =========================================================================

    def find_entity(self, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Tìm thực thể theo ID, tên chính xác, tên không phân biệt hoa thường, alias hoặc tên gần đúng.
        """
        if not identifier:
            return None
        target = identifier.strip().lower()

        # 1. Theo ID trực tiếp
        if identifier in self.entities_by_id:
            return self.entities_by_id[identifier]

        # 2. Theo tên chính xác
        if target in self.entities_by_name:
            return self.entities_by_name[target]

        # 3. Theo Alias
        if target in self.alias_to_entity_id:
            eid = self.alias_to_entity_id[target]
            return self.entities_by_id.get(eid)

        # 4. Tìm kiếm gần đúng / Chứa cụm từ
        for name, ent in self.entities_by_name.items():
            if target in name or name in target:
                return ent

        for alias, eid in self.alias_to_entity_id.items():
            if target in alias or alias in target:
                return self.entities_by_id.get(eid)

        return None

    def list_entities(self) -> List[Dict[str, Any]]:
        """Trả về toàn bộ danh sách thực thể có trong bộ nhớ."""
        return list(self.entities)

    # =========================================================================
    # 2. TRUY VẤN MỆNH ĐỀ / FACTS (CLAIM QUERY)
    # =========================================================================

    def get_claims(
        self,
        entity_name_or_id: str,
        status: Optional[str] = "current"
    ) -> List[Dict[str, Any]]:
        """
        Lấy danh sách Claims/Facts của một thực thể.
        status:
            - "current": Chỉ lấy facts còn hiệu lực (active).
            - "superseded": Chỉ lấy facts đã bị thay thế (lịch sử).
            - "all": Lấy toàn bộ facts cả mới lẫn cũ.
        """
        ent = self.find_entity(entity_name_or_id)
        if not ent:
            return []
        eid = ent.get("id") or ent.get("_id")
        active = self.active_facts_by_entity_id.get(eid, [])
        history = self.history_facts_by_entity_id.get(eid, [])

        if status == "current":
            return list(active)
        elif status == "superseded":
            return list(history)
        elif status in ("all", None):
            return list(active) + list(history)
        else:
            return [f for f in (active + history) if f.get("status") == status]

    def get_property(
        self,
        entity_name_or_id: str,
        property_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Lấy Fact hiện tại (active) của một thuộc tính cụ thể trên thực thể.
        Ví dụ: get_property("Atlas", "budget") -> Fact {property: budget, value: 500tr}
        """
        ent = self.find_entity(entity_name_or_id)
        if not ent:
            return None
        eid = ent.get("id") or ent.get("_id")
        active = self.active_facts_by_entity_id.get(eid, [])

        p_target = property_name.strip().lower()
        for f in active:
            prop = (f.get("property") or f.get("predicate") or "").strip().lower()
            if prop == p_target:
                return f
        return None

    def get_property_value(
        self,
        entity_name_or_id: str,
        property_name: str
    ) -> Optional[str]:
        """Lấy giá trị chuỗi hiện tại của thuộc tính."""
        fact = self.get_property(entity_name_or_id, property_name)
        if fact:
            return fact.get("value")
        return None

    def get_active_summary(self, entity_name_or_id: str) -> Dict[str, Any]:
        """
        Trả về dictionary tổng hợp tất cả các thuộc tính còn hiệu lực của thực thể.
        Ví dụ: {"budget": "500tr", "deadline": "20/10", "assignee": "Nguyên"}
        """
        ent = self.find_entity(entity_name_or_id)
        if not ent:
            return {}
        eid = ent.get("id") or ent.get("_id")
        active = self.active_facts_by_entity_id.get(eid, [])
        
        summary = {}
        for f in active:
            prop = f.get("property") or f.get("predicate") or "info"
            summary[prop] = f.get("value")
        return summary

    # =========================================================================
    # 3. LẦN VẾT LỊCH SỬ THAY ĐỔI (LINEAGE / TIMELINE)
    # =========================================================================

    def get_property_timeline(
        self,
        entity_name_or_id: str,
        property_name: str
    ) -> List[Dict[str, Any]]:
        """
        Lấy toàn bộ dòng thời gian biến động của một thuộc tính từ quá khứ đến hiện tại.
        Trả về danh sách các facts được sắp xếp từ cũ nhất đến mới nhất.
        """
        ent = self.find_entity(entity_name_or_id)
        if not ent:
            return []
        eid = ent.get("id") or ent.get("_id")

        p_target = property_name.strip().lower()
        all_entity_facts = (
            self.active_facts_by_entity_id.get(eid, []) +
            self.history_facts_by_entity_id.get(eid, [])
        )

        matched_facts = [
            f for f in all_entity_facts
            if (f.get("property") or f.get("predicate") or "").strip().lower() == p_target
        ]

        if not matched_facts:
            return []

        # Xây dựng đồ thị thay thế: replaces_map[old_id] = new_fact
        replaces_map = {}
        has_predecessor = set()
        for f in matched_facts:
            rep_id = f.get("replaces") or f.get("supersedes")
            if rep_id:
                replaces_map[rep_id] = f
                has_predecessor.add(f.get("id") or f.get("_id"))

        # Tìm các root nodes (các fact không thay thế fact nào khác)
        roots = [
            f for f in matched_facts
            if not (f.get("replaces") or f.get("supersedes"))
        ]

        timeline = []
        if roots:
            curr = roots[0]
            timeline.append(curr)
            curr_id = curr.get("id") or curr.get("_id")
            while curr_id in replaces_map:
                curr = replaces_map[curr_id]
                timeline.append(curr)
                curr_id = curr.get("id") or curr.get("_id")
        else:
            # Sắp xếp theo created_at nếu không lần được con trỏ
            timeline = sorted(
                matched_facts,
                key=lambda x: str(x.get("created_at") or "")
            )

        return timeline

    def trace_fact_chain(self, fact_id: str) -> List[Dict[str, Any]]:
        """
        Lần ngược lại chuỗi thay thế bắt đầu từ fact_id chỉ định về quá khứ.
        """
        chain = []
        curr_id = fact_id
        visited = set()

        while curr_id and curr_id not in visited:
            visited.add(curr_id)
            fact = self.facts_by_id.get(curr_id)
            if not fact:
                break
            chain.append(fact)
            curr_id = fact.get("replaces") or fact.get("supersedes")

        return chain

    # =========================================================================
    # 4. TÌM KIẾM TỰ DO (KEYWORD SEARCH)
    # =========================================================================

    def search_claims(
        self,
        keyword: str,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Tìm kiếm Claims theo từ khóa bất kỳ (tìm trong property, value, snippet, sender).
        """
        if not keyword:
            return []
        kw = keyword.strip().lower()

        results = []
        for f in self.facts_by_id.values():
            if status and f.get("status") != status:
                continue

            prop = str(f.get("property") or f.get("predicate") or "").lower()
            val = str(f.get("value") or "").lower()
            
            src = f.get("source") or {}
            snippet = ""
            if isinstance(src, dict):
                snippet = str(src.get("snippet") or "").lower()
            elif isinstance(src, str):
                snippet = src.lower()

            # Lấy tên thực thể cha để tìm kiếm kèm
            eid = f.get("entity_id")
            ent_name = ""
            if eid and eid in self.entities_by_id:
                ent_name = str(self.entities_by_id[eid].get("name") or "").lower()

            if (kw in prop) or (kw in val) or (kw in snippet) or (kw in ent_name):
                # Gắn kèm thông tin tên entity để tiện hiển thị
                item = dict(f)
                item["_entity_name"] = self.entities_by_id.get(eid, {}).get("name", "Unknown")
                results.append(item)

        return results

    # =========================================================================
    # 5. HỎI ĐÁP THÔNG MINH CÓ CĂN CỨ (GROUNDED ASK AI)
    # =========================================================================

    def ask(self, question: str) -> Dict[str, Any]:
        """
        Trả lời câu hỏi tự nhiên bằng LLM (Gemini) dựa HOÀN TOÀN trên các facts/claims đã bóc tách.
        Cung cấp câu trả lời chính xác, kèm danh sách các facts làm căn cứ chứng minh.
        """
        if not question or not question.strip():
            return {"answer": "Vui lòng nhập câu hỏi.", "supporting_facts": []}

        # 1. Chuẩn bị ngữ cảnh từ bộ nhớ phân cấp
        context_lines = []
        context_lines.append("=== DANH SÁCH THỰC THỂ VÀ THUỘC TÍNH HIỆN TẠI (GROUND TRUTH) ===")
        for ent in self.entities:
            name = ent.get("name") or ent.get("canonical_name")
            etype = ent.get("type") or "unknown"
            eid = ent.get("id") or ent.get("_id")
            active = self.active_facts_by_entity_id.get(eid, [])
            history = self.history_facts_by_entity_id.get(eid, [])

            context_lines.append(f"\n[THỰC THỂ: {name} (Loại: {etype}, ID: {eid})]")
            if ent.get("aliases"):
                context_lines.append(f"  - Tên gọi khác (Aliases): {', '.join(ent.get('aliases'))}")
            if ent.get("description"):
                context_lines.append(f"  - Mô tả: {ent.get('description')}")

            context_lines.append("  * CÁC THUỘC TÍNH HIỆN TẠI (CURRENT/ACTIVE FACTS):")
            if not active:
                context_lines.append("    (Không có thuộc tính active)")
            for f in active:
                fid = f.get("id") or f.get("_id")
                prop = f.get("property") or f.get("predicate")
                val = f.get("value")
                src = f.get("source")
                snippet = src.get("snippet") if isinstance(src, dict) else src
                rep = f.get("replaces") or f.get("supersedes")
                rep_info = f" [Thay thế fact cũ: {rep}]" if rep else ""
                context_lines.append(f"    - Fact ID {fid}: {prop} = \"{val}\"{rep_info} (Nguồn: \"{snippet}\")")

            if history:
                context_lines.append("  * LỊCH SỬ THUỘC TÍNH ĐÃ BỊ THAY THẾ (SUPERSEDED FACTS):")
                for f in history:
                    fid = f.get("id") or f.get("_id")
                    prop = f.get("property") or f.get("predicate")
                    val = f.get("value")
                    context_lines.append(f"    - Fact ID {fid} [SUPERSEDED]: {prop} từng là \"{val}\"")

        grounding_context = "\n".join(context_lines)

        prompt = f"""Bạn là Trợ lý Truy vấn Bộ nhớ HiLark AI.
Dưới đây là BỘ NHỚ THỰC TẾ (GROUND TRUTH) gồm các Thực thể và Mệnh đề (Facts/Claims) đã được bóc tách từ các cuộc hội thoại trước đó.

{grounding_context}

NGƯỜI DÙNG HỎI:
"{question}"

YÊU CẦU TRẢ LỜI:
1. Trả lời trực tiếp, chính xác, ngắn gọn dựa HOÀN TOÀN trên các facts ở trên.
2. Nêu rõ giá trị HIỆN TẠI (current) và nếu có thay đổi trong quá khứ thì giải thích rõ (ví dụ: trước đó là X, nay đã đổi thành Y).
3. KHÔNG bịa đặt thông tin không có trong Ground Truth.
4. Trả về kết quả dưới định dạng JSON có cấu trúc sau:
{{
  "answer": "Câu trả lời đầy đủ, thân thiện bằng tiếng Việt",
  "supporting_fact_ids": ["fact_xxx", "fact_yyy"],
  "entity_name": "Tên thực thể liên quan chính",
  "current_values": {{"thuộc_tính": "giá_trị"}},
  "history_changes": ["Từng là A nhưng đã đổi thành B"]
}}
Chỉ trả về duy nhất chuỗi JSON hợp lệ, không bọc markdown thừa.
"""

        try:
            client = GeminiClient()
            response_text = client.generate(prompt)
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
                cleaned = re.sub(r"\n?```$", "", cleaned)
            result_json = json.loads(cleaned)

            # Đính kèm chi tiết đầy đủ của các Facts làm căn cứ
            supporting_ids = result_json.get("supporting_fact_ids") or []
            detailed_facts = []
            for fid in supporting_ids:
                f_obj = self.facts_by_id.get(fid)
                if f_obj:
                    detailed_facts.append(f_obj)
            result_json["supporting_facts_detail"] = detailed_facts

            return result_json
        except Exception as e:
            # Fallback nếu LLM gặp sự cố
            return {
                "answer": f"Lỗi khi gọi AI: {str(e)}. Bạn có thể dùng lệnh /entity hoặc /search để xem trực tiếp.",
                "supporting_fact_ids": [],
                "supporting_facts_detail": [],
            }

    # =========================================================================
    # 6. FORMATTERS CHO TERMINAL / CLI
    # =========================================================================

    def format_entity_card(self, entity_name_or_id: str) -> str:
        """Tạo thẻ hiển thị trực quan thông tin Entity và các Claims."""
        ent = self.find_entity(entity_name_or_id)
        if not ent:
            return f"{C_RED}❌ Không tìm thấy thực thể: '{entity_name_or_id}'{C_RESET}"

        eid = ent.get("id") or ent.get("_id")
        name = ent.get("name") or ent.get("canonical_name")
        etype = ent.get("type") or "unknown"
        aliases = ent.get("aliases") or []
        desc = ent.get("description") or "(Không có mô tả)"

        active = self.active_facts_by_entity_id.get(eid, [])
        history = self.history_facts_by_entity_id.get(eid, [])

        lines = []
        lines.append(f"\n{C_CYAN}{C_BOLD}╔═══════════════════════════════════════════════════════════════════════╗{C_RESET}")
        lines.append(f"{C_CYAN}{C_BOLD}║ THỰC THỂ: {name.upper():<30} [{etype.upper():<10}]         ║{C_RESET}")
        lines.append(f"{C_CYAN}{C_BOLD}╚═══════════════════════════════════════════════════════════════════════╝{C_RESET}")
        lines.append(f"  • {C_BOLD}Entity ID:{C_RESET} {C_DIM}{eid}{C_RESET}")
        lines.append(f"  • {C_BOLD}Aliases:{C_RESET}   {C_YELLOW}{', '.join(aliases) if aliases else '(Không có)'}{C_RESET}")
        lines.append(f"  • {C_BOLD}Mô tả:{C_RESET}     {desc}")

        lines.append(f"\n  {C_GREEN}{C_BOLD}🟢 CÁC THUỘC TÍNH HIỆN TẠI (ACTIVE FACTS - {len(active)} facts):{C_RESET}")
        if not active:
            lines.append(f"     {C_DIM}(Chưa có thuộc tính nào đang active){C_RESET}")
        for idx, f in enumerate(active, 1):
            fid = f.get("id") or f.get("_id")
            prop = f.get("property") or f.get("predicate") or "info"
            val = f.get("value")
            rep = f.get("replaces") or f.get("supersedes")
            src = f.get("source")
            snippet = src.get("snippet") if isinstance(src, dict) else src

            rep_str = f" {C_YELLOW}⟵ [replaces: {rep}]{C_RESET}" if rep else ""
            lines.append(f"     {idx}. {C_BOLD}{prop:<12}{C_RESET} = {C_GREEN}\"{val}\"{C_RESET}{rep_str}")
            lines.append(f"        {C_DIM}• Fact ID: {fid} | Nguồn: \"{snippet}\"{C_RESET}")

        if history:
            lines.append(f"\n  {C_RED}{C_BOLD}🔴 LỊCH SỬ ĐÃ BỊ THAY THẾ (SUPERSEDED FACTS - {len(history)} facts):{C_RESET}")
            for idx, f in enumerate(history, 1):
                fid = f.get("id") or f.get("_id")
                prop = f.get("property") or f.get("predicate") or "info"
                val = f.get("value")
                src = f.get("source")
                snippet = src.get("snippet") if isinstance(src, dict) else src
                lines.append(f"     {idx}. {C_DIM}[SUPERSEDED]{C_RESET} {prop:<12} = {C_RED}\"{val}\"{C_RESET}")
                lines.append(f"        {C_DIM}• Fact ID: {fid} | Từng nói: \"{snippet}\"{C_RESET}")

        lines.append("")
        return "\n".join(lines)

    def format_timeline(self, entity_name_or_id: str, property_name: str) -> str:
        """Vẽ biểu đồ timeline biến động giá trị thuộc tính qua các bước."""
        timeline = self.get_property_timeline(entity_name_or_id, property_name)
        if not timeline:
            return f"{C_YELLOW}⚠️ Không tìm thấy biến động nào cho thuộc tính '{property_name}' trên '{entity_name_or_id}'.{C_RESET}"

        ent = self.find_entity(entity_name_or_id)
        ent_name = ent.get("name") if ent else entity_name_or_id

        lines = []
        lines.append(f"\n{C_BOLD}{C_BLUE}📊 DÒNG THỜI GIAN BIẾN ĐỘNG (PROPERTY LINEAGE):{C_RESET}")
        lines.append(f"   Thực thể: {C_CYAN}{C_BOLD}{ent_name}{C_RESET} | Thuộc tính: {C_PURPLE}{C_BOLD}{property_name}{C_RESET}\n")

        for i, f in enumerate(timeline):
            is_latest = (i == len(timeline) - 1)
            status = f.get("status", "current")
            fid = f.get("id") or f.get("_id")
            val = f.get("value")
            src = f.get("source")
            snippet = src.get("snippet") if isinstance(src, dict) else src

            if is_latest and status == "current":
                node_sym = f"{C_GREEN}● [HIỆN TẠI / CURRENT]{C_RESET}"
                val_color = C_GREEN
            else:
                node_sym = f"{C_RED}○ [ĐÃ CŨ / SUPERSEDED]{C_RESET}"
                val_color = C_DIM

            lines.append(f"   Step {i+1}: {node_sym}")
            lines.append(f"           Giá trị: {val_color}{C_BOLD}\"{val}\"{C_RESET}")
            lines.append(f"           Fact ID: {C_DIM}{fid}{C_RESET}")
            if snippet:
                lines.append(f"           Trích dẫn: {C_DIM}\"{snippet}\"{C_RESET}")

            if not is_latest:
                rep_by = timeline[i+1].get("id") or timeline[i+1].get("_id")
                lines.append(f"           {C_YELLOW}│   ▼ (Bị thay thế bởi Fact {rep_by}){C_RESET}")

        lines.append("")
        return "\n".join(lines)


# =============================================================================
# CLI CONVERSATIONAL AGENT (HỎI ĐÁP BẰNG LLM DỰA TRÊN CLAIMS)
# =============================================================================

def interactive_cli():
    """Giao diện Hỏi - Đáp tự nhiên: LLM đọc Claims/Facts làm Ground Truth để trả lời."""
    querier = ClaimQuerier()

    print(f"\n{C_CYAN}{C_BOLD}" + "=" * 76)
    print("   🤖 HILARK MEMORY QA - TRỢ LÝ TRUY VẤN DỰA TRÊN MỆNH ĐỀ (CLAIMS)")
    print("   LLM suy luận & trả lời HOÀN TOÀN dựa trên các Claims/Facts đã trích xuất")
    print("=" * 76 + C_RESET)
    print(f"{C_DIM}Nguồn dữ liệu: {querier.data_source}{C_RESET}")
    print(f"Tổng số Entities: {C_BOLD}{len(querier.entities)}{C_RESET} | Tổng số Facts: {C_BOLD}{len(querier.facts_by_id)}{C_RESET}\n")
    print(f"{C_DIM}Gõ câu hỏi tự nhiên để LLM trả lời (vd: 'Ngân sách Atlas bao nhiêu?', 'Ai đang lead?')")
    print(f"Lệnh nhanh: /entities | /entity <tên> | /timeline <tên> <thuộc_tính> | /search <từ> | /reload | /exit{C_RESET}\n")

    while True:
        try:
            prompt_str = f"{C_BOLD}{C_GREEN}👉 Câu hỏi của bạn:{C_RESET} "
            user_input = input(prompt_str).strip()

            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q", "/exit", "/quit"):
                print(f"\n{C_CYAN}👋 Tạm biệt!{C_RESET}\n")
                break

            # Lệnh làm mới dữ liệu
            if user_input.lower() in ("/reload", "/r", "reload"):
                querier.reload()
                print(f"\n{C_GREEN}✅ Đã nạp lại dữ liệu Claims từ: {querier.data_source}{C_RESET}")
                print(f"Tổng Entities: {len(querier.entities)} | Tổng Facts: {len(querier.facts_by_id)}\n")
                continue

            # Lệnh xem danh sách entities
            if user_input.lower() in ("/entities", "/list", "/all"):
                ents = querier.list_entities()
                print(f"\n{C_BOLD}📦 DANH SÁCH {len(ents)} THỰC THỂ TRONG BỘ NHỚ:{C_RESET}")
                for idx, e in enumerate(ents, 1):
                    n_act = len(e.get("active_facts", []))
                    n_his = len(e.get("history_facts", []))
                    name = e.get("name") or e.get("canonical_name")
                    etype = e.get("type", "unknown")
                    aliases = ", ".join(e.get("aliases", []))
                    print(f"   {idx}. {C_CYAN}[{etype.upper()}]{C_RESET} {C_BOLD}{name}{C_RESET} "
                          f"({C_GREEN}{n_act} active facts{C_RESET}, {C_RED}{n_his} superseded{C_RESET})")
                    if aliases:
                        print(f"      {C_DIM}Aliases: {aliases}{C_RESET}")
                print("")
                continue

            # Lệnh xem entity card
            if user_input.startswith("/entity ") or user_input.startswith("/e "):
                name = user_input.split(" ", 1)[1].strip()
                print(querier.format_entity_card(name))
                continue

            # Lệnh xem timeline
            if user_input.startswith("/timeline ") or user_input.startswith("/t "):
                parts = user_input.split(" ", 2)[1:]
                if len(parts) == 2:
                    print(querier.format_timeline(parts[0], parts[1]))
                elif len(parts) == 1:
                    # Mặc định lấy entity Atlas nếu không ghi
                    print(querier.format_timeline("Atlas", parts[0]))
                else:
                    print(f"{C_YELLOW}Cú pháp: /timeline <tên_entity> <thuộc_tính> (vd: /timeline Atlas budget){C_RESET}")
                continue

            # Lệnh tìm kiếm từ khóa
            if user_input.startswith("/search ") or user_input.startswith("/s "):
                kw = user_input.split(" ", 1)[1].strip()
                results = querier.search_claims(kw)
                print(f"\n{C_BOLD}🔎 KẾT QUẢ TÌM KIẾM CHO '{kw}' ({len(results)} facts):{C_RESET}")
                if not results:
                    print(f"   {C_DIM}(Không tìm thấy fact nào phù hợp){C_RESET}\n")
                else:
                    for idx, f in enumerate(results, 1):
                        status_col = C_GREEN if f.get("status") == "current" else C_RED
                        prop = f.get("property") or f.get("predicate")
                        val = f.get("value")
                        ent_name = f.get("_entity_name", "Unknown")
                        print(f"   {idx}. {status_col}[{f.get('status', '').upper()}]{C_RESET} "
                              f"[{ent_name}] {C_BOLD}{prop}{C_RESET} = \"{val}\" (ID: {f.get('id')})")
                    print("")
                continue

            # Lệnh trợ giúp
            if user_input.lower() in ("/help", "/h", "help"):
                print(f"""
{C_BOLD}CÁC LỆNH HỖ TRỢ:{C_RESET}
  • {C_GREEN}<câu hỏi tự nhiên>{C_RESET} : LLM dùng Claims làm Ground Truth để trả lời (vd: "Atlas ngân sách bao nhiêu?")
  • {C_CYAN}/entities{C_RESET}           : Xem toàn bộ thực thể và số lượng claims
  • {C_CYAN}/entity <tên>{C_RESET}      : Xem chi tiết 1 thực thể (vd: /entity Atlas)
  • {C_CYAN}/timeline <ent> <prop>{C_RESET}: Xem lịch sử biến động thuộc tính (vd: /timeline Atlas budget)
  • {C_CYAN}/search <từ_khóa>{C_RESET}    : Tìm kiếm facts theo từ khóa (vd: /search 500tr)
  • {C_CYAN}/reload{C_RESET}             : Nạp lại file JSON sau khi test thêm tin nhắn mới
  • {C_CYAN}/exit{C_RESET}               : Thoát chương trình
""")
                continue

            # =================================================================
            # MẶC ĐỊNH: GỌI LLM DỰA VÀO CÁC CLAIMS ĐỂ TRẢ LỜI CÂU HỎI
            # =================================================================
            print(f"{C_DIM}⏳ LLM đang truy vấn căn cứ từ các Claims...{C_RESET}")
            resp = querier.ask(user_input)

            print(f"\n{C_PURPLE}{C_BOLD}🤖 TRẢ LỜI:{C_RESET} {C_BOLD}{resp.get('answer')}{C_RESET}")

            # Hiển thị biến động lịch sử nếu có
            if resp.get("history_changes"):
                print(f"\n   {C_YELLOW}📜 Lịch sử biến động: {', '.join(resp.get('history_changes'))}{C_RESET}")

            # Hiển thị chi tiết căn cứ Claims (Proof / Ground Truth)
            detailed_facts = resp.get("supporting_facts_detail") or []
            if detailed_facts:
                print(f"\n   {C_BLUE}{C_BOLD}📋 CĂN CỨ MỆNH ĐỀ (SUPPORTING CLAIMS):{C_RESET}")
                for idx, f in enumerate(detailed_facts, 1):
                    st = f.get("status", "current")
                    st_col = C_GREEN if st == "current" else C_RED
                    prop = f.get("property") or f.get("predicate")
                    val = f.get("value")
                    fid = f.get("id") or f.get("_id")
                    src = f.get("source")
                    snippet = src.get("snippet") if isinstance(src, dict) else src
                    rep = f.get("replaces") or f.get("supersedes")
                    rep_text = f" {C_YELLOW}⟵ [thay thế {rep}]{C_RESET}" if rep else ""

                    print(f"      {idx}. {st_col}[{st.upper()}]{C_RESET} {C_BOLD}{prop}{C_RESET} = \"{val}\"{rep_text} (ID: {C_DIM}{fid}{C_RESET})")
                    if snippet:
                        print(f"         {C_DIM}Nguồn tin nhắn: \"{snippet}\"{C_RESET}")
            print("")

        except (KeyboardInterrupt, EOFError):
            print(f"\n\n{C_CYAN}👋 Đã ngắt phiên. Tạm biệt!{C_RESET}\n")
            break
        except Exception as e:
            print(f"\n{C_RED}❌ Lỗi: {e}{C_RESET}\n")



def run_demo():
    """Hàm chạy demo tự động kiểm tra các chức năng chính của ClaimQuerier."""
    querier = ClaimQuerier()
    print(f"\n{C_BOLD}{C_GREEN}=== CHẠY DEMO TRUY VẤN CLAIM / FACT ==={C_RESET}\n")

    # 1. Tra cứu Atlas
    print(querier.format_entity_card("Atlas"))

    # 2. Timeline Budget
    print(querier.format_timeline("Atlas", "budget"))

    # 3. Timeline Assignee
    print(querier.format_timeline("Atlas", "assignee"))

    # 4. Tìm kiếm từ khóa
    print(f"{C_BOLD}Tìm kiếm 'Nguyên':{C_RESET}")
    for res in querier.search_claims("Nguyên"):
        print(f"  • {res.get('property')} = {res.get('value')} (Status: {res.get('status')})")

    # 5. Lấy giá trị trực tiếp
    current_budget = querier.get_property_value("Atlas", "budget")
    print(f"\n{C_BOLD}Giá trị budget hiện tại của Atlas:{C_RESET} {C_GREEN}{current_budget}{C_RESET}")
    print(f"{C_BOLD}Thuộc tính hiện tại của Atlas:{C_RESET} {querier.get_active_summary('Atlas')}\n")


def main():
    parser = argparse.ArgumentParser(description="HiLark Claim & Fact Query Tool")
    parser.add_argument("--entity", "-e", type=str, help="Tên thực thể cần tra cứu")
    parser.add_argument("--property", "-p", type=str, help="Tên thuộc tính cần lấy giá trị")
    parser.add_argument("--timeline", "-t", type=str, help="Vẽ timeline lịch sử của thuộc tính")
    parser.add_argument("--search", "-s", type=str, help="Tìm kiếm claim theo từ khóa")
    parser.add_argument("--ask", "-a", type=str, help="Đặt câu hỏi tự nhiên cho AI dựa trên Claims")
    parser.add_argument("--demo", action="store_true", help="Chạy demo kiểm thử các chức năng")
    parser.add_argument("--file", "-f", type=str, help="Đường dẫn file JSON bộ nhớ tùy chỉnh")

    args = parser.parse_args()
    querier = ClaimQuerier(data_source=args.file)

    if args.demo:
        run_demo()
        return

    if args.entity and args.timeline:
        print(querier.format_timeline(args.entity, args.timeline))
        return

    if args.entity and args.property:
        val = querier.get_property_value(args.entity, args.property)
        print(f"{args.property}: {val}")
        return

    if args.entity:
        print(querier.format_entity_card(args.entity))
        return

    if args.search:
        results = querier.search_claims(args.search)
        print(f"Tìm thấy {len(results)} kết quả:")
        for r in results:
            print(f"[{r.get('status')}] {r.get('property')} = {r.get('value')}")
        return

    if args.ask:
        resp = querier.ask(args.ask)
        print(resp.get("answer"))
        return

    # Mặc định mở giao diện tương tác
    interactive_cli()


if __name__ == "__main__":
    main()
