#!/usr/bin/env python3
"""
Interactive Multi-Message Test Console cho LLM Extractor (Memory & Claim)
========================================================================
Vị trí: server/tests/test_interactive.py
Cách chạy:
    cd /Users/hoainam/Desktop/HiLark/server
    .venv/bin/python tests/test_interactive.py

Chức năng:
    - Nhận tin nhắn tuần tự liên tục từ người dùng (Multi-message session).
    - Tự động duy trì và tích lũy trạng thái:
        + Nhánh 1 (Memory Entities): Tích lũy và cập nhật thực thể chuẩn.
        + Nhánh 2 (Claims): Tự động phát hiện thay thế (superseded), mơ hồ (uncertain) hay mâu thuẫn (conflicted).
    - Lưu kết quả phiên test vào file: server/tests/interactive_session_output.json
"""

import json
import os
import sys
from datetime import datetime

# Đảm bảo import được modules từ server
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from utils.llm_extractor import extract
from models.memory import build_hierarchical_memory

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

OUTPUT_JSON_PATH = os.path.join(SERVER_ROOT, "tests", "interactive_session_output.json")


def print_banner():
    print(f"\n{C_CYAN}{C_BOLD}" + "=" * 76)
    print("      🚀 HILARk LLM EXTRACTOR - INTERACTIVE MULTI-MESSAGE TEST")
    print("   Nhận tin nhắn tuần tự -> Bóc tách Thực thể (Entities) & Facts (Parent-Child)")
    print("=" * 76 + C_RESET)
    print(f"{C_DIM}Lệnh hỗ trợ: Gõ 'clear' để làm mới bộ nhớ | Gõ 'exit' hoặc 'quit' để thoát.{C_RESET}\n")


def display_turn_result(turn_num: int, query: str, memory_list: list, new_claims: list, superseded_claims: list):
    print(f"\n{C_BOLD}{C_BLUE}--- [KẾT QUẢ TIN NHẮN #{turn_num}] ---{C_RESET}")
    print(f"{C_DIM}Nội dung: \"{query}\"{C_RESET}\n")

    # 1. Hiển thị Entities
    print(f"{C_PURPLE}{C_BOLD}📦 THỰC THỂ (ENTITIES) - {len(memory_list)} thực thể:{C_RESET}")
    if not memory_list:
        print(f"   {C_DIM}(Không có thực thể mới){C_RESET}")
    else:
        for idx, m in enumerate(memory_list, 1):
            name = m.get("canonical_name") or m.get("name", "Unknown")
            etype = m.get("entity_type") or m.get("type", "UNKNOWN")
            aliases_str = ", ".join(m.get("aliases", [])) if m.get("aliases") else "(Không có)"
            print(f"   {C_CYAN}{idx}. [{etype.upper()}]{C_RESET} {C_BOLD}{name}{C_RESET}")
            print(f"      • ID:      {C_DIM}{m.get('_id') or m.get('id')}{C_RESET}")
            print(f"      • Aliases: {C_YELLOW}{aliases_str}{C_RESET}")
            if m.get("description"):
                print(f"      • Mô tả:   {m.get('description')}")

    # 2. Hiển thị Facts (Claims)
    print(f"\n{C_CYAN}{C_BOLD}📋 FACTS (THÔNG TIN MỚI) - {len(new_claims)} fact(s):{C_RESET}")
    if not new_claims:
        print(f"   {C_DIM}(Không có fact nào được trích xuất){C_RESET}")
    else:
        for idx, c in enumerate(new_claims, 1):
            status = c.get("status", "current")
            if status == "current":
                st_color = C_GREEN
            elif status == "uncertain":
                st_color = C_YELLOW
            elif status == "conflicted":
                st_color = C_RED
            else:
                st_color = C_DIM

            prop = c.get("predicate") or c.get("property", "info")
            val = c.get("value")
            replaces_id = c.get("supersedes") or c.get("replaces")
            print(f"   {idx}. {st_color}[{status.upper()}]{C_RESET} {C_BOLD}{prop}{C_RESET} = {C_GREEN}\"{val}\"{C_RESET}")
            print(f"      • Fact ID:   {C_DIM}{c.get('_id') or c.get('id')}{C_RESET}  |  Entity ID: {C_PURPLE}{c.get('entity_id')}{C_RESET}")
            
            # Highlight nếu thay thế fact cũ
            if replaces_id:
                print(f"      • {C_YELLOW}🔄 REPLACES (Thay thế cho fact cũ): {replaces_id}{C_RESET}")

    # 3. Hiển thị Fact cũ bị Replaced / Superseded
    if superseded_claims:
        print(f"\n{C_RED}{C_BOLD}⚠️ CÁC FACTS CŨ VỪA BỊ THAY THẾ [SUPERSEDED] ({len(superseded_claims)} fact):{C_RESET}")
        for old in superseded_claims:
            prop = old.get("predicate") or old.get("property", "info")
            print(f"   • {C_RED}[SUPERSEDED]{C_RESET} ID: {C_DIM}{old.get('_id') or old.get('id')}{C_RESET} | {prop} = \"{old.get('value')}\"")

    print(f"\n{C_DIM}" + "-" * 76 + C_RESET)


def display_session_summary(session_entities: list, session_claims: list):
    hierarchical = build_hierarchical_memory(session_entities, session_claims)
    current_claims = [c for c in session_claims if c.get("status") == "current"]
    superseded_claims = [c for c in session_claims if c.get("status") == "superseded"]

    print(f"{C_BOLD}📊 BỘ NHỚ PHÂN CẤP HIỆN TẠI (PARENT - CHILD):{C_RESET}")
    print(f"   • Tổng số Entities: {C_BOLD}{len(hierarchical)}{C_RESET}")
    for ent in hierarchical:
        n_active = len(ent.get("active_facts", []))
        n_hist = len(ent.get("history_facts", []))
        print(f"     🔹 {C_CYAN}[{ent.get('type').upper()}]{C_RESET} {C_BOLD}{ent.get('name')}{C_RESET} "
              f"({C_GREEN}{n_active} active facts{C_RESET}" + 
              (f", {C_RED}{n_hist} history facts{C_RESET}" if n_hist else "") + ")")
        for f in ent.get("active_facts", []):
            print(f"        • {C_BOLD}{f.get('property')}{C_RESET}: {C_GREEN}\"{f.get('value')}\"{C_RESET}")
    print(f"{C_DIM}Đã lưu bộ nhớ phân cấp Parent-Child vào: {OUTPUT_JSON_PATH}{C_RESET}\n")


def save_session_to_json(history: list, session_entities: list, session_claims: list):
    """Lưu toàn bộ phiên theo cấu trúc phân cấp Parent-Child trực quan."""
    hierarchical_entities = build_hierarchical_memory(session_entities, session_claims)

    clean_history = []
    for step_item in history:
        clean_step = {
            "step": step_item.get("step"),
            "message": step_item.get("message"),
            "timestamp": step_item.get("timestamp"),
            "new_entities": [
                {
                    "id": e.get("_id") or e.get("id"),
                    "name": e.get("canonical_name") or e.get("name"),
                    "type": e.get("entity_type") or e.get("type"),
                    "aliases": e.get("aliases", []),
                    "description": e.get("description", ""),
                }
                for e in step_item.get("extracted_memory", [])
            ],
            "new_facts": [
                {
                    "id": c.get("_id") or c.get("id"),
                    "entity_id": c.get("entity_id"),
                    "property": c.get("predicate") or c.get("property"),
                    "value": c.get("value"),
                    "status": c.get("status"),
                    "replaces": c.get("supersedes") or c.get("replaces"),
                    "source": c.get("source", {}).get("snippet") if isinstance(c.get("source"), dict) else c.get("source"),
                }
                for c in step_item.get("extracted_claims", [])
            ],
            "replaced_facts": [
                {
                    "id": s.get("_id") or s.get("id"),
                    "entity_id": s.get("entity_id"),
                    "property": s.get("predicate") or s.get("property"),
                    "value": s.get("value"),
                    "status": "superseded",
                }
                for s in step_item.get("superseded_claims", [])
            ]
        }
        clean_history.append(clean_step)

    payload = {
        "updated_at": datetime.now().isoformat(),
        "total_messages": len(history),
        "total_entities": len(hierarchical_entities),
        "entities": hierarchical_entities,
        "history": clean_history,
    }
    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main():
    print_banner()

    session_entities = []
    session_claims = []
    history = []
    step = 1

    while True:
        try:
            prompt_str = f"{C_BOLD}{C_GREEN}👉 Nhập tin nhắn #{step}:{C_RESET} "
            user_input = input(prompt_str).strip()

            if not user_input:
                continue

            # Xử lý lệnh thoát
            if user_input.lower() in ("exit", "quit", "q"):
                print(f"\n{C_CYAN}👋 Đã kết thúc phiên test. Tạm biệt!{C_RESET}\n")
                break

            # Xử lý lệnh làm mới bộ nhớ
            if user_input.lower() in ("clear", "reset", "cls"):
                session_entities = []
                session_claims = []
                history = []
                step = 1
                if os.path.exists(OUTPUT_JSON_PATH):
                    try:
                        os.remove(OUTPUT_JSON_PATH)
                    except Exception:
                        pass
                print(f"\n{C_YELLOW}🧹 Đã xóa sạch bộ nhớ phiên test (Reset)!{C_RESET}\n")
                continue

            print(f"{C_DIM}⏳ Đang gửi tin nhắn qua LLM Extractor...{C_RESET}")

            # Gọi LLM Extractor với đầy đủ context tích lũy từ các tin nhắn trước
            result = extract(
                query=user_input,
                workspace_id="default_ws",
                source_message_id=f"msg_{step:03d}",
                sender="User",
                existing_entities=session_entities,
                existing_claims=session_claims,
            )

            new_memories = result.get("memory", [])
            new_claims = result.get("claims", [])
            superseded_claims = result.get("superseded_claims", [])

            # 1. Cập nhật session_entities (Upsert theo _id)
            for m in new_memories:
                m_id = m.get("_id")
                idx = next((i for i, e in enumerate(session_entities) if e.get("_id") == m_id), None)
                if idx is not None:
                    session_entities[idx] = m
                else:
                    session_entities.append(m)

            # 2. Cập nhật các claims cũ bị superseded trong session_claims
            superseded_ids = {c.get("_id") for c in superseded_claims if c.get("_id")}
            for c in session_claims:
                if c.get("_id") in superseded_ids:
                    c["status"] = "superseded"
                    c["updated_at"] = datetime.now().isoformat()

            # 3. Thêm các claims mới vào session_claims
            session_claims.extend(new_claims)

            # 4. Ghi nhận lịch sử
            history.append({
                "step": step,
                "message": user_input,
                "timestamp": datetime.now().isoformat(),
                "extracted_memory": new_memories,
                "extracted_claims": new_claims,
                "superseded_claims": superseded_claims,
            })

            # 5. Lưu ra file JSON
            save_session_to_json(history, session_entities, session_claims)

            # 6. In kết quả trực quan
            display_turn_result(step, user_input, new_memories, new_claims, superseded_claims)
            display_session_summary(session_entities, session_claims)

            step += 1

        except (KeyboardInterrupt, EOFError):
            print(f"\n\n{C_CYAN}👋 Đã ngắt phiên test. Hẹn gặp lại!{C_RESET}\n")
            break
        except Exception as e:
            print(f"\n{C_RED}❌ Đã xảy ra lỗi: {str(e)}{C_RESET}\n")


if __name__ == "__main__":
    main()
