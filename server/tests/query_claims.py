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

import httpx

# Đảm bảo import được modules từ server
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

try:
    from models.memory import Entity, Fact, FactStatus, build_entity_tree
    from utils.text_filter import text_filter
except ImportError:
    # Fallback nếu chạy độc lập
    Entity = None
    Fact = None
    FactStatus = None
    text_filter = None


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


DEFAULT_DATA_SOURCE = "MONGODB"
DEFAULT_SESSION_FILE = os.path.join(SERVER_ROOT, "tests", "interactive_session_output.json")


class ClaimQuerier:
    """
    Công cụ truy vấn Mệnh đề / Facts từ bộ nhớ phân cấp.
    Mặc định truy vấn TRỰC TIẾP từ MongoDB (Database: LarkAssistant, Collections: memories, claims).
    """

    def __init__(self, data_source: Optional[Union[str, Dict[str, Any]]] = None):
        self.data_source = data_source or DEFAULT_DATA_SOURCE
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
        """Mặc định sử dụng nguồn MongoDB."""
        return DEFAULT_DATA_SOURCE

    def reload(self) -> None:
        """Nạp lại dữ liệu và xây dựng lại indexes từ MongoDB."""
        self.entities = []
        self.facts = []
        self.history_steps = []

        if isinstance(self.data_source, dict):
            self._load_from_dict(self.data_source)
        elif self.data_source == "MONGODB":
            self._load_from_mongodb()
        elif isinstance(self.data_source, str):
            if os.path.exists(self.data_source):
                try:
                    with open(self.data_source, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self._load_from_dict(data)
                except Exception as e:
                    print(f"{C_RED}Lỗi khi đọc file {self.data_source}: {e}{C_RESET}")
            else:
                self._load_from_mongodb()
        else:
            self._load_from_mongodb()

        self._build_indexes()

    def _load_from_mongodb(self) -> None:
        """Nạp trực tiếp từ MongoDB (collections memories & claims)."""
        try:
            from database.db import get_all_entities_sync, get_all_facts_sync
            raw_entities = get_all_entities_sync(workspace_id=None)
            raw_facts = get_all_facts_sync()
            if build_entity_tree:
                self.entities = build_entity_tree(raw_entities, raw_facts)
            else:
                self.entities = raw_entities
            self.facts = raw_facts
        except Exception as e:
            print(f"{C_RED}Lỗi khi nạp dữ liệu từ MongoDB: {e}{C_RESET}")



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
        """Nạp từ MongoDB (Single Source of Truth)."""
        self._load_from_mongodb()

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
    # 5. HỎI ĐÁP QUA SERVER CHAT ENDPOINT (/api/chat)
    # =========================================================================

    DEFAULT_SERVER_CHAT_URL = "http://localhost:8000/api/chat"

    def call_server_chat(
        self,
        query: str,
        server_url: Optional[str] = None,
        channel: str = "tests_cli",
        timeout: float = 90.0,
    ) -> Dict[str, Any]:
        """
        Gửi câu hỏi / tin nhắn trực tiếp qua endpoint /api/chat của server HiLark FastAPI.
        Bao gồm toàn bộ quy trình: JEV Routing -> WeKnora RAG -> LLM Extractor -> text_filter.
        """
        url = server_url or self.DEFAULT_SERVER_CHAT_URL
        payload = {
            "query": query,
            "channel": channel,
            "agent_enabled": True,
            "agent_id": "builtin-quick-answer",
        }

        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    # Tự động nạp lại dữ liệu nếu có thực thể hoặc facts mới được ghi nhận vào MongoDB
                    if data.get("extraction"):
                        self.reload()
                    return data
                elif resp.status_code == 400:
                    err_detail = resp.json().get("detail", resp.text)
                    return {"status": "error", "error": f"Bad Request (400): {err_detail}"}
                else:
                    return {"status": "error", "error": f"HTTP {resp.status_code}: {resp.text}"}
        except httpx.ConnectError:
            return {
                "status": "error",
                "error": f"Không thể kết nối tới server tại {url}. Vui lòng đảm bảo server đang chạy (lệnh: uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload).",
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "error": f"Timeout khi gọi server sau {timeout}s.",
            }
        except Exception as e:
            return {"status": "error", "error": f"Lỗi kết nối server: {str(e)}"}

    def ask(
        self,
        question: str,
        server_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Truy vấn trực tiếp qua Server Chat API (/api/chat).
        Đảm bảo câu trả lời luôn đầy đủ từ WeKnora RAG + JEV Routing + đồng bộ Claims vào MongoDB.
        """
        if not question or not question.strip():
            return {"answer": "Vui lòng nhập câu hỏi.", "status": "empty"}

        resp = self.call_server_chat(question, server_url=server_url)
        if resp.get("status") == "error":
            return {
                "answer": f"Lỗi gọi server: {resp.get('error')}",
                "status": "error",
                "raw_response": resp,
            }

        weknora = resp.get("weknora_response") or {}
        ans = weknora.get("answer") or resp.get("message") or ""
        return {
            "answer": ans,
            "status": resp.get("status"),
            "jev_action": resp.get("jev_action"),
            "jev_confidence": resp.get("jev_confidence"),
            "citations": weknora.get("citations", []),
            "extraction": resp.get("extraction"),
            "raw_response": resp,
        }

    def ask_claims(
        self,
        question: str,
        server_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Truy vấn qua Server Chat API (/api/chat) làm engine trả lời chính,
        kết hợp tìm kiếm & đối chiếu các Claims / Facts hiện có từ MongoDB.
        """
        resp = self.ask(question, server_url=server_url)

        # Tìm các facts liên quan trong MongoDB dựa trên keywords
        supporting_facts: List[Dict[str, Any]] = []
        seen_ids = set()
        tokens = [w.strip() for w in re.split(r"[\s,;?.!]+", question) if len(w.strip()) >= 3]
        for token in tokens:
            for fact in self.search_claims(token):
                fid = fact.get("id") or fact.get("_id")
                if fid and fid not in seen_ids:
                    seen_ids.add(fid)
                    supporting_facts.append(fact)
                    if len(supporting_facts) >= 10:
                        break
            if len(supporting_facts) >= 10:
                break

        # Nếu không có fact nào từ token, tìm theo các entities hiện có
        if not supporting_facts:
            for ent in self.entities:
                ename = ent.get("name") or ent.get("canonical_name") or ""
                if ename and ename.lower() in question.lower():
                    eid = ent.get("id") or ent.get("_id")
                    for fact in self.active_facts_by_entity_id.get(eid, [])[:5]:
                        fid = fact.get("id") or fact.get("_id")
                        if fid and fid not in seen_ids:
                            seen_ids.add(fid)
                            item = dict(fact)
                            item["_entity_name"] = ename
                            supporting_facts.append(item)

        resp["supporting_facts_detail"] = supporting_facts
        resp["history_changes"] = []
        return resp


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


def format_server_response(resp: Dict[str, Any]) -> str:
    """Định dạng kết quả trả về từ endpoint /api/chat hiển thị đẹp mắt trên terminal."""
    if resp.get("status") == "error":
        return f"\n{C_RED}❌ LỖI GỌI SERVER:{C_RESET} {resp.get('error')}\n"

    lines = []
    status = resp.get("status")
    jev_act = resp.get("jev_action", "N/A")
    jev_conf = resp.get("jev_confidence", 0.0)

    # 1. Header & JEV routing info
    jev_color = C_GREEN if jev_act in ("REPLY_ONLY", "MEMORY_AND_REPLY") else C_YELLOW
    lines.append(f"\n{C_CYAN}{C_BOLD}📡 KẾT QUẢ TỪ SERVER (/api/chat):{C_RESET}")
    lines.append(f"   • Phân loại JEV: {jev_color}{C_BOLD}{jev_act}{C_RESET} (Độ tin cậy: {jev_conf:.0%}) | Trạng thái: {C_BOLD}{status}{C_RESET}")

    # 2. Câu trả lời chính (đã được text_filter làm sạch tag <kb.../>)
    weknora = resp.get("weknora_response") or {}
    answer = weknora.get("answer") or resp.get("message") or ""
    if answer:
        lines.append(f"\n{C_PURPLE}{C_BOLD}🤖 TRẢ LỜI:{C_RESET}\n{answer}")

    # 3. Tài liệu trích dẫn (Citations)
    citations = weknora.get("citations") or []
    if citations:
        lines.append(f"\n   {C_BLUE}{C_BOLD}📚 TÀI LIỆU TRÍCH DẪN (CITATIONS):{C_RESET}")
        for idx, c in enumerate(citations, 1):
            doc = c.get("doc", "Tài liệu")
            chunk = c.get("chunk_id", "")
            chunk_display = f" (Chunk: {chunk[:16]}...)" if chunk else ""
            lines.append(f"      {idx}. {C_CYAN}{doc}{C_RESET}{C_DIM}{chunk_display}{C_RESET}")

    # 4. Trích xuất Entities & Facts mới (nếu có)
    extraction = resp.get("extraction")
    if extraction and isinstance(extraction, dict):
        ents = extraction.get("entities", [])
        facts = extraction.get("facts", [])
        superseded = extraction.get("superseded_facts", [])
        if ents or facts:
            lines.append(f"\n   {C_YELLOW}{C_BOLD}💾 TRÍCH XUẤT VÀO BỘ NHỚ (MONGODB):{C_RESET}")
            if ents:
                ent_names = [e.get("name") or e.get("canonical_name", "") for e in ents]
                lines.append(f"      • Entities ({len(ents)}): {', '.join(ent_names)}")
            if facts:
                lines.append(f"      • Facts mới ({len(facts)}):")
                for f in facts:
                    prop = f.get("property") or f.get("predicate", "info")
                    val = f.get("value")
                    lines.append(f"        - {prop} = \"{val}\" (ID: {f.get('id')})")
            if superseded:
                lines.append(f"      • Facts cũ bị thay thế: {len(superseded)} fact")

    lines.append("")
    return "\n".join(lines)


# =============================================================================
# CLI CONVERSATIONAL AGENT (HỎI ĐÁP BẰNG LLM DỰA TRÊN CLAIMS)
# =============================================================================

def interactive_cli(server_url: str = "http://localhost:8000/api/chat", default_mode: str = "SERVER"):
    """
    Giao diện Hỏi - Đáp & Test Server Chat:
      - Chế độ SERVER: Gọi trực tiếp endpoint /api/chat của server HiLark.
      - Chế độ CLAIMS: LLM đọc Claims/Facts từ MongoDB làm Ground Truth để trả lời.
    """
    querier = ClaimQuerier()
    mode = default_mode.upper()

    print(f"\n{C_CYAN}{C_BOLD}" + "=" * 78)
    print("   🤖 HILARK MEMORY & CHAT TEST CONSOLE (ENDPOINT /api/chat)")
    print("   Hỗ trợ cả: Test Live Server Chat API & Truy vấn Phân cấp Claims")
    print("=" * 78 + C_RESET)
    print(f"{C_GREEN}Nguồn dữ liệu: MongoDB (Database: LarkAssistant | collections: memories, claims){C_RESET}")
    print(f"Tổng số Entities: {C_BOLD}{len(querier.entities)}{C_RESET} | Tổng số Facts: {C_BOLD}{len(querier.facts_by_id)}{C_RESET}")
    print(f"Server Endpoint: {C_YELLOW}{C_BOLD}{server_url}{C_RESET}")
    print(f"Chế độ hiện tại: {C_PURPLE}{C_BOLD}[{mode}]{C_RESET} (Gõ câu hỏi để gọi { 'Server Chat API' if mode == 'SERVER' else 'Grounded Claims QA' })")
    print(f"{C_DIM}Lệnh hỗ trợ: /mode (đổi chế độ) | /chat <câu> | /ask <câu> | /entities | /timeline | /reload | /exit{C_RESET}\n")

    while True:
        try:
            mode_badge = f"{C_PURPLE}[{mode}]{C_RESET}"
            prompt_str = f"{mode_badge} {C_BOLD}{C_GREEN}👉 Nhập:{C_RESET} "
            user_input = input(prompt_str).strip()

            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q", "/exit", "/quit"):
                print(f"\n{C_CYAN}👋 Tạm biệt!{C_RESET}\n")
                break

            # Lệnh làm mới dữ liệu
            if user_input.lower() in ("/reload", "/r", "reload"):
                querier.reload()
                print(f"\n{C_GREEN}✅ Đã nạp lại dữ liệu Claims từ MongoDB (LarkAssistant){C_RESET}")
                print(f"Tổng Entities: {len(querier.entities)} | Tổng Facts: {len(querier.facts_by_id)}\n")
                continue

            # Lệnh xem danh sách entities
            if user_input.lower() in ("/entities", "/list", "/all", "entities", "list"):
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
                    print(querier.format_timeline("HiLark", parts[0]))
                else:
                    print(f"{C_YELLOW}Cú pháp: /timeline <tên_entity> <thuộc_tính> (vd: /timeline HiLark budget){C_RESET}")
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

            # Lệnh chuyển đổi chế độ (Toggle Mode)
            if user_input.lower() in ("/mode", "/switch", "/m", "mode", "m", "switch"):
                mode = "CLAIMS" if mode == "SERVER" else "SERVER"
                if querier.data_source == "MONGODB":
                    querier.reload()
                mode_desc = (
                    "Server Chat API (/api/chat)"
                    if mode == "SERVER"
                    else f"Server Chat API + Đối chiếu Claims MongoDB ({len(querier.entities)} Entities, {len(querier.facts_by_id)} Facts)"
                )
                print(f"\n{C_GREEN}🔄 Đã chuyển chế độ mặc định sang:{C_RESET} {C_BOLD}{C_PURPLE}[{mode}]{C_RESET} — {mode_desc}\n")
                continue

            # Lệnh đổi URL server
            if user_input.startswith("/server "):
                new_url = user_input.split(" ", 1)[1].strip()
                if new_url:
                    server_url = new_url
                    print(f"\n{C_GREEN}✔ Đã cập nhật URL server:{C_RESET} {server_url}\n")
                continue

            # Lệnh kiểm tra kết nối server
            if user_input.lower() in ("/url", "/ping", "/status", "ping", "status"):
                print(f"\n{C_CYAN}Đang kiểm tra kết nối tới server: {server_url}...{C_RESET}")
                try:
                    root_url = server_url.replace("/api/chat", "/")
                    with httpx.Client(timeout=3.0) as cl:
                        r = cl.get(root_url)
                        print(f"{C_GREEN}✔ Server đang hoạt động tốt (HTTP {r.status_code})!{C_RESET}\n")
                except Exception as e:
                    print(f"{C_RED}❌ Không thể kết nối tới server: {e}{C_RESET}\n")
                continue

            # Lệnh ép buộc gọi Server Chat API: /chat <câu hỏi>
            if user_input.startswith("/chat ") or user_input.startswith("/c "):
                query = user_input.split(" ", 1)[1].strip()
                print(f"{C_DIM}⏳ Đang gửi tới Server Chat API ({server_url})...{C_RESET}")
                resp = querier.call_server_chat(query, server_url=server_url)
                print(format_server_response(resp))
                continue

            # Lệnh ép buộc gọi Grounded Claims QA: /ask <câu hỏi>
            if user_input.startswith("/ask ") or user_input.startswith("/a "):
                query = user_input.split(" ", 1)[1].strip()
                print(f"{C_DIM}⏳ Đang gửi qua Server Chat API ({server_url}) & đối chiếu Claims...{C_RESET}")
                resp = querier.ask_claims(query, server_url=server_url)
                print(format_server_response(resp.get("raw_response", {})))
                detailed_facts = resp.get("supporting_facts_detail") or []
                if detailed_facts:
                    print(f"   {C_BLUE}{C_BOLD}📋 CĂN CỨ MỆNH ĐỀ ĐỐI CHIẾU TỪ MONGODB ({len(detailed_facts)} facts):{C_RESET}")
                    for idx, f in enumerate(detailed_facts, 1):
                        st = f.get("status", "current")
                        st_col = C_GREEN if st == "current" else C_RED
                        prop = f.get("property") or f.get("predicate")
                        val = f.get("value")
                        fid = f.get("id") or f.get("_id")
                        ent_name = f.get("_entity_name") or ""
                        ent_str = f"[{ent_name}] " if ent_name else ""
                        rep = f.get("replaces") or f.get("supersedes")
                        rep_text = f" {C_YELLOW}⟵ [thay thế {rep}]{C_RESET}" if rep else ""

                        print(f"      {idx}. {st_col}[{st.upper()}]{C_RESET} {ent_str}{C_BOLD}{prop}{C_RESET} = \"{val}\"{rep_text} (ID: {C_DIM}{fid}{C_RESET})")
                        src = f.get("source")
                        snippet = src.get("snippet") if isinstance(src, dict) else src
                        if snippet:
                            print(f"         {C_DIM}Nguồn tin nhắn: \"{snippet}\"{C_RESET}")
                    print("")
                continue

            # Lệnh trợ giúp
            if user_input.lower() in ("/help", "/h", "help", "?"):
                print(f"""
{C_BOLD}CÁC LỆNH HỖ TRỢ:{C_RESET}
  • {C_GREEN}<nhập câu hỏi>{C_RESET}        : Tự động xử lý theo chế độ hiện tại ({C_PURPLE}[{mode}]{C_RESET})
  • {C_CYAN}/mode{C_RESET} hoặc {C_CYAN}mode{C_RESET} / {C_CYAN}m{C_RESET}  : Chuyển đổi giữa [SERVER] (/api/chat) và [CLAIMS] (/api/chat + Claims MongoDB)
  • {C_CYAN}/chat <nội dung>{C_RESET}   : Luôn gửi qua Server Chat API (/api/chat)
  • {C_CYAN}/ask <câu hỏi>{C_RESET}     : Gửi qua Server Chat API và đối chiếu Claims MongoDB
  • {C_CYAN}/server <url>{C_RESET}      : Đổi URL server (mặc định: {server_url})
  • {C_CYAN}/entities{C_RESET}          : Xem toàn bộ thực thể và số lượng claims
  • {C_CYAN}/entity <tên>{C_RESET}     : Xem chi tiết 1 thực thể (vd: /entity HiLark)
  • {C_CYAN}/timeline <ent> <prop>{C_RESET}: Xem lịch sử biến động thuộc tính (vd: /timeline HiLark budget)
  • {C_CYAN}/search <từ_khóa>{C_RESET}   : Tìm kiếm facts theo từ khóa (vd: /search 30/11)
  • {C_CYAN}/reload{C_RESET}            : Nạp lại dữ liệu Claims từ MongoDB
  • {C_CYAN}/exit{C_RESET}              : Thoát chương trình
""")
                continue

            # =================================================================
            # XỬ LÝ THEO CHẾ ĐỘ HIỆN TẠI (MẶC ĐỊNH LÀ SERVER: /api/chat)
            # =================================================================
            if mode == "SERVER":
                print(f"{C_DIM}⏳ Đang gửi tin nhắn qua Server Chat API ({server_url})...{C_RESET}")
                resp = querier.call_server_chat(user_input, server_url=server_url)
                print(format_server_response(resp))
            else:
                print(f"{C_DIM}⏳ Đang gửi qua Server Chat API ({server_url}) & đối chiếu Claims MongoDB...{C_RESET}")
                resp = querier.ask_claims(user_input, server_url=server_url)

                print(format_server_response(resp.get("raw_response", {})))

                detailed_facts = resp.get("supporting_facts_detail") or []
                if detailed_facts:
                    print(f"   {C_BLUE}{C_BOLD}📋 CĂN CỨ MỆNH ĐỀ ĐỐI CHIẾU TỪ MONGODB ({len(detailed_facts)} facts):{C_RESET}")
                    for idx, f in enumerate(detailed_facts, 1):
                        st = f.get("status", "current")
                        st_col = C_GREEN if st == "current" else C_RED
                        prop = f.get("property") or f.get("predicate")
                        val = f.get("value")
                        fid = f.get("id") or f.get("_id")
                        ent_name = f.get("_entity_name") or ""
                        ent_str = f"[{ent_name}] " if ent_name else ""
                        rep = f.get("replaces") or f.get("supersedes")
                        rep_text = f" {C_YELLOW}⟵ [thay thế {rep}]{C_RESET}" if rep else ""

                        print(f"      {idx}. {st_col}[{st.upper()}]{C_RESET} {ent_str}{C_BOLD}{prop}{C_RESET} = \"{val}\"{rep_text} (ID: {C_DIM}{fid}{C_RESET})")
                        src = f.get("source")
                        snippet = src.get("snippet") if isinstance(src, dict) else src
                        if snippet:
                            print(f"         {C_DIM}Nguồn tin nhắn: \"{snippet}\"{C_RESET}")
                    print("")
                continue

        except (KeyboardInterrupt, EOFError):
            print(f"\n\n{C_CYAN}👋 Đã ngắt phiên. Tạm biệt!{C_RESET}\n")
            break
        except Exception as e:
            print(f"\n{C_RED}❌ Lỗi: {e}{C_RESET}\n")



def run_demo():
    """Hàm chạy demo tự động kiểm tra các chức năng chính của ClaimQuerier."""
    querier = ClaimQuerier()
    print(f"\n{C_BOLD}{C_GREEN}=== CHẠY DEMO TRUY VẤN CLAIM / FACT ==={C_RESET}\n")

    # 1. Tra cứu HiLark
    print(querier.format_entity_card("HiLark"))

    # 2. Timeline Budget
    print(querier.format_timeline("HiLark", "budget"))

    # 3. Timeline Scope
    print(querier.format_timeline("HiLark", "scope"))

    # 4. Tìm kiếm từ khóa
    print(f"{C_BOLD}Tìm kiếm 'Nguyên':{C_RESET}")
    for res in querier.search_claims("Nguyên"):
        print(f"  • {res.get('property')} = {res.get('value')} (Status: {res.get('status')})")

    # 5. Lấy giá trị trực tiếp
    current_budget = querier.get_property_value("HiLark", "budget")
    print(f"\n{C_BOLD}Giá trị budget hiện tại của HiLark:{C_RESET} {C_GREEN}{current_budget}{C_RESET}")
    print(f"{C_BOLD}Thuộc tính hiện tại của HiLark:{C_RESET} {querier.get_active_summary('HiLark')}\n")


def main():
    parser = argparse.ArgumentParser(description="HiLark Memory & Chat Query Tool (Mặc định Server Chat API)")
    parser.add_argument("query", nargs="?", default=None, help="Câu hỏi trực tiếp (mặc định trả lời qua Server Chat API)")
    parser.add_argument("--ask", "-a", type=str, help="Đặt câu hỏi tự nhiên cho AI (mặc định Server Chat API)")
    parser.add_argument("--claims", action="store_true", help="Ưu tiên dùng engine Claims QA thuần thay vì Server Chat API")
    parser.add_argument("--chat", "-c", type=str, help="Gửi câu hỏi / tin nhắn qua Server Chat API (/api/chat)")
    parser.add_argument("--entity", "-e", type=str, help="Tên thực thể cần tra cứu")
    parser.add_argument("--property", "-p", type=str, help="Tên thuộc tính cần lấy giá trị")
    parser.add_argument("--timeline", "-t", type=str, help="Vẽ timeline lịch sử của thuộc tính")
    parser.add_argument("--search", "-s", type=str, help="Tìm kiếm claim theo từ khóa")
    parser.add_argument("--server-url", type=str, default="http://localhost:8000/api/chat", help="URL của server chat endpoint")
    parser.add_argument("--demo", action="store_true", help="Chạy demo kiểm thử các chức năng")
    parser.add_argument("--file", "-f", type=str, help="Đường dẫn file JSON bộ nhớ tùy chỉnh")

    args = parser.parse_args()
    querier = ClaimQuerier(data_source=args.file)

    if args.demo:
        run_demo()
        return

    # Nếu người dùng truyền câu hỏi trực tiếp hoặc qua --chat hoặc --ask
    target_query = args.chat or args.ask or args.query
    if target_query:
        if args.claims:
            resp = querier.ask_claims(target_query, server_url=args.server_url)
            print(format_server_response(resp.get("raw_response", {})))
            detailed_facts = resp.get("supporting_facts_detail") or []
            if detailed_facts:
                print(f"   {C_BLUE}{C_BOLD}📋 CĂN CỨ MỆNH ĐỀ ĐỐI CHIẾU TỪ MONGODB ({len(detailed_facts)} facts):{C_RESET}")
                for idx, f in enumerate(detailed_facts, 1):
                    prop = f.get("property") or f.get("predicate")
                    val = f.get("value")
                    print(f"      {idx}. {prop} = \"{val}\" (ID: {f.get('id')})")
        else:
            resp = querier.call_server_chat(target_query, server_url=args.server_url)
            print(format_server_response(resp))
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

    # Mặc định mở giao diện tương tác (mặc định kết nối tới Live Server)
    interactive_cli(server_url=args.server_url, default_mode="SERVER")



if __name__ == "__main__":
    main()
