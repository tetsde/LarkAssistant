#!/usr/bin/env python3
"""
Interactive Multi-Message Test Console cho LLM Extractor (Entity & Fact)
========================================================================
Vị trí: server/tests/test_interactive.py
Cách chạy:
    cd /Users/hoainam/Desktop/HiLark/server
    .venv/bin/python tests/test_interactive.py

Chức năng:
    - Nhận tin nhắn tuần tự liên tục từ người dùng (Multi-message session).
    - Tự động duy trì và tích lũy trạng thái:
        + Nhánh 1 (Entities): Tích lũy và cập nhật thực thể kinh doanh (Parent).
        + Nhánh 2 (Facts): Tự động phát hiện thay thế (replaces/superseded), mơ hồ (uncertain) hay mâu thuẫn (conflicted).
    - Lưu kết quả phiên test vào file: server/tests/interactive_session_output.json theo cây Parent-Child.
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
from models.memory import build_entity_tree

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
    print("      🚀 HILARK LLM EXTRACTOR - INTERACTIVE TEST CONSOLE")
    print("   Nhận tin nhắn tuần tự -> Bóc tách Entities & Facts (Parent - Child)")
    print("=" * 76 + C_RESET)
    print(f"{C_DIM}Lệnh hỗ trợ: Gõ 'clear' để làm mới bộ nhớ | Gõ 'exit' hoặc 'quit' để thoát.{C_RESET}\n")


def display_turn_result(turn_num: int, query: str, entity_list: list, new_facts: list, superseded_facts: list):
    print(f"\n{C_BOLD}{C_BLUE}--- [KẾT QUẢ TIN NHẮN #{turn_num}] ---{C_RESET}")
    print(f"{C_DIM}Nội dung: \"{query}\"{C_RESET}\n")

    # 1. Hiển thị Entities
    print(f"{C_PURPLE}{C_BOLD}📦 THỰC THỂ (ENTITIES) - {len(entity_list)} thực thể:{C_RESET}")
    if not entity_list:
        print(f"   {C_DIM}(Không có thực thể mới){C_RESET}")
    else:
        for idx, ent in enumerate(entity_list, 1):
            name = ent.get("name") or ent.get("canonical_name", "Unknown")
            etype = ent.get("type") or ent.get("entity_type", "UNKNOWN")
            aliases_str = ", ".join(ent.get("aliases", [])) if ent.get("aliases") else "(Không có)"
            print(f"   {C_CYAN}{idx}. [{etype.upper()}]{C_RESET} {C_BOLD}{name}{C_RESET}")
            print(f"      • ID:      {C_DIM}{ent.get('id') or ent.get('_id')}{C_RESET}")
            print(f"      • Aliases: {C_YELLOW}{aliases_str}{C_RESET}")
            if ent.get("description"):
                print(f"      • Mô tả:   {ent.get('description')}")

    # 2. Hiển thị Facts
    print(f"\n{C_CYAN}{C_BOLD}📋 FACTS (THÔNG TIN MỚI) - {len(new_facts)} fact(s):{C_RESET}")
    if not new_facts:
        print(f"   {C_DIM}(Không có fact nào được trích xuất){C_RESET}")
    else:
        for idx, fact in enumerate(new_facts, 1):
            status = fact.get("status", "current")
            if status == "current":
                st_color = C_GREEN
            elif status == "uncertain":
                st_color = C_YELLOW
            elif status == "conflicted":
                st_color = C_RED
            else:
                st_color = C_DIM

            prop = fact.get("property") or fact.get("predicate", "info")
            val = fact.get("value")
            replaces_id = fact.get("replaces") or fact.get("supersedes")
            print(f"   {idx}. {st_color}[{status.upper()}]{C_RESET} {C_BOLD}{prop}{C_RESET} = {C_GREEN}\"{val}\"{C_RESET}")
            print(f"      • Fact ID:   {C_DIM}{fact.get('id') or fact.get('_id')}{C_RESET}  |  Entity ID: {C_PURPLE}{fact.get('entity_id')}{C_RESET}")
            
            if replaces_id:
                print(f"      • {C_YELLOW}🔄 REPLACES (Thay thế fact cũ): {replaces_id}{C_RESET}")

    # 3. Hiển thị Fact cũ bị Replaced / Superseded
    if superseded_facts:
        print(f"\n{C_RED}{C_BOLD}⚠️ CÁC FACTS CŨ VỪA BỊ THAY THẾ [SUPERSEDED] ({len(superseded_facts)} fact):{C_RESET}")
        for old in superseded_facts:
            prop = old.get("property") or old.get("predicate", "info")
            print(f"   • {C_RED}[SUPERSEDED]{C_RESET} ID: {C_DIM}{old.get('id') or old.get('_id')}{C_RESET} | {prop} = \"{old.get('value')}\"")

    print(f"\n{C_DIM}" + "-" * 76 + C_RESET)


def display_session_summary(session_entities: list, session_facts: list):
    tree = build_entity_tree(session_entities, session_facts)

    print(f"{C_BOLD}📊 BỘ NHỚ PHÂN CẤP HIỆN TẠI (PARENT - CHILD):{C_RESET}")
    print(f"   • Tổng số Entities: {C_BOLD}{len(tree)}{C_RESET}")
    for ent in tree:
        n_active = len(ent.get("active_facts", []))
        n_hist = len(ent.get("history_facts", []))
        ent_type = ent.get("type") or ent.get("entity_type", "ENTITY")
        ent_name = ent.get("name") or ent.get("canonical_name", "Unknown")
        print(f"     🔹 {C_CYAN}[{ent_type.upper()}]{C_RESET} {C_BOLD}{ent_name}{C_RESET} "
              f"({C_GREEN}{n_active} active facts{C_RESET}" + 
              (f", {C_RED}{n_hist} history facts{C_RESET}" if n_hist else "") + ")")
        for f in ent.get("active_facts", []):
            prop = f.get("property") or f.get("predicate", "info")
            print(f"        • {C_BOLD}{prop}{C_RESET}: {C_GREEN}\"{f.get('value')}\"{C_RESET}")
    print(f"{C_DIM}Đã lưu bộ nhớ phân cấp Parent-Child vào: {OUTPUT_JSON_PATH}{C_RESET}\n")


def save_session_to_json(history: list, session_entities: list, session_facts: list):
    """Lưu toàn bộ phiên theo cấu trúc phân cấp Parent-Child trực quan."""
    entity_tree = build_entity_tree(session_entities, session_facts)

    clean_history = []
    for step_item in history:
        clean_step = {
            "step": step_item.get("step"),
            "message": step_item.get("message"),
            "timestamp": step_item.get("timestamp"),
            "new_entities": [
                {
                    "id": e.get("id") or e.get("_id"),
                    "name": e.get("name") or e.get("canonical_name"),
                    "type": e.get("type") or e.get("entity_type"),
                    "aliases": e.get("aliases", []),
                    "description": e.get("description", ""),
                }
                for e in (step_item.get("extracted_entities") or step_item.get("extracted_memory", []))
            ],
            "new_facts": [
                {
                    "id": f.get("id") or f.get("_id"),
                    "entity_id": f.get("entity_id"),
                    "property": f.get("property") or f.get("predicate"),
                    "value": f.get("value"),
                    "status": f.get("status"),
                    "replaces": f.get("replaces") or f.get("supersedes"),
                    "source": f.get("source", {}).get("snippet") if isinstance(f.get("source"), dict) else f.get("source"),
                }
                for f in (step_item.get("extracted_facts") or step_item.get("extracted_claims", []))
            ],
            "replaced_facts": [
                {
                    "id": s.get("id") or s.get("_id"),
                    "entity_id": s.get("entity_id"),
                    "property": s.get("property") or s.get("predicate"),
                    "value": s.get("value"),
                    "status": "superseded",
                }
                for s in (step_item.get("superseded_facts") or step_item.get("superseded_claims", []))
            ]
        }
        clean_history.append(clean_step)

    payload = {
        "updated_at": datetime.now().isoformat(),
        "total_messages": len(history),
        "total_entities": len(entity_tree),
        "entities": entity_tree,
        "history": clean_history,
    }
    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main():
    print_banner()

    session_entities = []
    session_facts = []
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
                session_facts = []
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
                existing_facts=session_facts,
            )

            new_entities = result.get("entities") or result.get("memory", [])
            new_facts = result.get("facts") or result.get("claims", [])
            superseded_facts = result.get("superseded_facts") or result.get("superseded_claims", [])

            # 1. Cập nhật session_entities (Upsert theo id)
            for ent in new_entities:
                ent_id = ent.get("id") or ent.get("_id")
                idx = next((i for i, e in enumerate(session_entities) if (e.get("id") or e.get("_id")) == ent_id), None)
                if idx is not None:
                    session_entities[idx] = ent
                else:
                    session_entities.append(ent)

            # 2. Cập nhật các facts cũ bị superseded trong session_facts
            superseded_ids = {f.get("id") or f.get("_id") for f in superseded_facts if (f.get("id") or f.get("_id"))}
            for f in session_facts:
                if (f.get("id") or f.get("_id")) in superseded_ids:
                    f["status"] = "superseded"
                    f["updated_at"] = datetime.now().isoformat()

            # 3. Thêm các facts mới vào session_facts
            session_facts.extend(new_facts)

            # 4. Ghi nhận lịch sử
            history.append({
                "step": step,
                "message": user_input,
                "timestamp": datetime.now().isoformat(),
                "extracted_entities": new_entities,
                "extracted_facts": new_facts,
                "superseded_facts": superseded_facts,
            })

            # 5. Lưu ra file JSON theo cấu trúc Parent-Child
            save_session_to_json(history, session_entities, session_facts)

            # 6. In kết quả trực quan
            display_turn_result(step, user_input, new_entities, new_facts, superseded_facts)
            display_session_summary(session_entities, session_facts)

            step += 1

        except (KeyboardInterrupt, EOFError):
            print(f"\n\n{C_CYAN}👋 Đã ngắt phiên test. Hẹn gặp lại!{C_RESET}\n")
            break
        except Exception as e:
            print(f"\n{C_RED}❌ Đã xảy ra lỗi: {str(e)}{C_RESET}\n")


if __name__ == "__main__":
    main()
