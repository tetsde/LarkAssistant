#!/usr/bin/env python3
"""
Interactive Multi-Message Test Console cho LLM Extractor (MongoDB Edition)
==========================================================================
Vị trí: server/tests/test_interactive.py
Cách chạy:
    cd /Users/hoainam/Desktop/HiLark/server
    .venv/bin/python tests/test_interactive.py             # Chế độ nhập tương tác trực tiếp
    .venv/bin/python tests/test_interactive.py --scenario  # Chạy tự động kịch bản 5 tin nhắn

Chức năng:
    - Nhận tin nhắn tuần tự (Multi-turn chat).
    - Tự động duy trì và tích lũy trạng thái:
        + Nhánh 1 (Entities): Tích lũy và cập nhật thực thể kinh doanh (Parent).
        + Nhánh 2 (Facts): Tự động phát hiện thay thế (replaces/superseded), mơ hồ hay mâu thuẫn.
    - Lưu TRỰC TIẾP vào MongoDB (Database: LarkAssistant, Collections: memories, claims).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List

# Đảm bảo import được modules từ server
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from models.memory import build_entity_tree
from utils.llm_extractor import extract
from database.db import (
    get_all_entities_sync,
    get_all_facts_sync,
    save_extraction_to_mongo_sync,
    clear_mongo_stores_sync,
    get_sync_memories_collection,
    get_sync_claims_collection,
)

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


def print_banner():
    print(f"\n{C_CYAN}{C_BOLD}" + "=" * 78)
    print("      🚀 HILARK LLM EXTRACTOR - INTERACTIVE TEST CONSOLE (MONGODB)")
    print("   Nhận tin nhắn tuần tự -> Bóc tách Entities & Facts -> Lưu trữ MongoDB")
    print("   Database: LarkAssistant | Collections: memories (entities), claims (facts)")
    print("=" * 78 + C_RESET)
    print(f"{C_DIM}Lệnh hỗ trợ: 'scenario' (chạy 5 turn mẫu) | 'clear' (xóa DB) | 'exit' (thoát){C_RESET}\n")


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

    print(f"\n{C_DIM}" + "-" * 78 + C_RESET)


def display_session_summary(session_entities: list, session_facts: list):
    tree = build_entity_tree(session_entities, session_facts)

    print(f"{C_BOLD}📊 BỘ NHỚ PHÂN CẤP TRONG MONGODB (PARENT - CHILD):{C_RESET}")
    print(f"   • Tổng số Entities trong DB: {C_BOLD}{len(tree)}{C_RESET}")
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
        for f in ent.get("history_facts", []):
            prop = f.get("property") or f.get("predicate", "info")
            print(f"        • {C_DIM}[SUPERSEDED] {prop}: \"{f.get('value')}\"{C_RESET}")

    mem_count = get_sync_memories_collection().count_documents({})
    claim_count = get_sync_claims_collection().count_documents({})
    print(f"\n{C_DIM}💾 Trạng thái MongoDB: collections.memories={mem_count} docs | collections.claims={claim_count} docs{C_RESET}\n")


def process_message_turn(
    step: int,
    user_input: str,
    session_entities: List[Dict[str, Any]],
    session_facts: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Xử lý 1 lượt tin nhắn: Trích xuất -> Lưu MongoDB -> Trả về entities & facts mới nhất.
    """
    print(f"{C_DIM}⏳ Đang gửi tin nhắn qua LLM Extractor (context {len(session_entities)} entities, {len(session_facts)} facts)...{C_RESET}")

    result = extract(
        query=user_input,
        workspace_id="default",
        source_message_id=f"msg_{step:03d}",
        sender="User",
        existing_entities=session_entities,
        existing_facts=session_facts,
    )

    new_entities = result.get("entities") or result.get("memory", [])
    new_facts = result.get("facts") or result.get("claims", [])
    superseded_facts = result.get("superseded_facts") or result.get("superseded_claims", [])

    # Lưu trực tiếp vào MongoDB
    save_extraction_to_mongo_sync(result)

    # Nạp lại dữ liệu đồng bộ chính xác nhất từ MongoDB
    latest_entities = get_all_entities_sync()
    latest_facts = get_all_facts_sync()

    # In kết quả lượt này
    display_turn_result(step, user_input, new_entities, new_facts, superseded_facts)
    display_session_summary(latest_entities, latest_facts)

    return latest_entities, latest_facts


def run_5_turn_scenario():
    """
    Chạy tự động kịch bản 5 tin nhắn đa lượt (Multi-turn chat) thực tế:
      Turn 1: Khởi tạo Dự án & Phân công Nhân sự
      Turn 2: Bổ sung Khách hàng & Ngân sách dự án
      Turn 3: Biến động thuộc tính (Khách hàng tăng ngân sách & dời deadline)
      Turn 4: Tạo Feature/Module mới thuộc dự án & người làm
      Turn 5: Thay đổi người phụ trách Module (Superseded assignee)
    """
    print(f"\n{C_BOLD}{C_GREEN}══════════════════════════════════════════════════════════════════════════════{C_RESET}")
    print(f"{C_BOLD}{C_GREEN}  ▶ BẮT ĐẦU CHẠY KỊCH BẢN 5 MULTI-TURN CHAT (LƯU TRỰC TIẾP VÀO MONGODB)        {C_RESET}")
    print(f"{C_BOLD}{C_GREEN}══════════════════════════════════════════════════════════════════════════════{C_RESET}\n")

    scenario_turns = [
        (
            1,
            "Team mình khởi động dự án Alpha, Nam làm Project Lead và Tuấn làm Tech Lead, hạn chót ngày 15/11.",
            "Khởi tạo dự án Alpha, 2 nhân sự Nam (Project Lead) & Tuấn (Tech Lead), deadline 15/11."
        ),
        (
            2,
            "Dự án Alpha này ký hợp đồng với khách hàng Vingroup, ngân sách được duyệt là 400 triệu.",
            "Bổ sung thuộc tính khách hàng Vingroup & ngân sách ban đầu 400 triệu cho Alpha."
        ),
        (
            3,
            "Khách hàng Vingroup vừa bổ sung thêm yêu cầu nên tăng ngân sách lên 600 triệu và lùi deadline sang 30/11.",
            "Biến động: Ngân sách tăng 400M -> 600M (replaces) & Deadline đổi 15/11 -> 30/11 (replaces)."
        ),
        (
            4,
            "Tuấn đang phụ trách phát triển module Payment Gateway cho dự án Alpha, dự kiến xong trước 20/11.",
            "Tạo thực thể mới Payment Gateway thuộc Alpha do Tuấn phụ trách, deadline 20/11."
        ),
        (
            5,
            "Do Tuấn bận dự án khác nên chuyển module Payment Gateway sang cho Hoàng làm.",
            "Biến động: Phụ trách Payment Gateway đổi từ Tuấn -> Hoàng (replaces assignee)."
        ),
    ]

    # Làm sạch DB trước khi chạy kịch bản để có số liệu chuẩn xác
    print(f"{C_YELLOW}🧹 Đang làm mới database MongoDB (LarkAssistant) để chạy kịch bản...{C_RESET}")
    clear_mongo_stores_sync()
    session_entities = []
    session_facts = []

    for step, message, goal in scenario_turns:
        print(f"\n{C_BOLD}{C_YELLOW}=============================================================================={C_RESET}")
        print(f"{C_BOLD}{C_YELLOW} 👉 TURN #{step}: {C_CYAN}\"{message}\"{C_RESET}")
        print(f"{C_DIM}    Mục tiêu: {goal}{C_RESET}")
        print(f"{C_BOLD}{C_YELLOW}=============================================================================={C_RESET}")

        session_entities, session_facts = process_message_turn(
            step=step,
            user_input=message,
            session_entities=session_entities,
            session_facts=session_facts,
        )

        time.sleep(1)

    print(f"\n{C_BOLD}{C_GREEN}══════════════════════════════════════════════════════════════════════════════{C_RESET}")
    print(f"{C_BOLD}{C_GREEN}  🎉 HOÀN THÀNH KỊCH BẢN 5 MULTI-TURN CHAT!                                      {C_RESET}")
    print(f"{C_BOLD}{C_GREEN}  Toàn bộ Entities & Facts/Claims đã được lưu an toàn trong MongoDB.            {C_RESET}")
    print(f"{C_BOLD}{C_GREEN}══════════════════════════════════════════════════════════════════════════════{C_RESET}\n")


def main():
    parser = argparse.ArgumentParser(description="HiLark LLM Extractor Interactive Console (MongoDB)")
    parser.add_argument("--scenario", action="store_true", help="Chạy tự động kịch bản 5 multi-turn chat")
    parser.add_argument("--clear", action="store_true", help="Xóa sạch database MongoDB trước khi bắt đầu")
    args = parser.parse_args()

    if args.clear:
        clear_mongo_stores_sync()
        print(f"{C_YELLOW}🧹 Đã xóa sạch dữ liệu trong MongoDB!{C_RESET}")

    if args.scenario:
        run_5_turn_scenario()
        return

    print_banner()

    # Nạp dữ liệu hiện có trong MongoDB
    session_entities = get_all_entities_sync()
    session_facts = get_all_facts_sync()
    if session_entities or session_facts:
        print(f"{C_GREEN}✔ Đã nạp từ MongoDB: {len(session_entities)} Entities | {len(session_facts)} Facts{C_RESET}\n")
    else:
        print(f"{C_DIM}Database MongoDB hiện đang rỗng. Sẵn sàng nhận tin nhắn đầu tiên!{C_RESET}\n")

    step = 1

    while True:
        try:
            prompt_str = f"{C_BOLD}{C_GREEN}👉 Nhập tin nhắn #{step}:{C_RESET} "
            user_input = input(prompt_str).strip()

            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q"):
                print(f"\n{C_CYAN}👋 Đã kết thúc phiên test. Tạm biệt!{C_RESET}\n")
                break

            if user_input.lower() in ("clear", "reset", "cls"):
                clear_mongo_stores_sync()
                session_entities = []
                session_facts = []
                step = 1
                print(f"\n{C_YELLOW}🧹 Đã xóa sạch bộ nhớ trong MongoDB (Reset)!{C_RESET}\n")
                continue

            if user_input.lower() in ("scenario", "test5"):
                run_5_turn_scenario()
                session_entities = get_all_entities_sync()
                session_facts = get_all_facts_sync()
                step = 6
                continue

            session_entities, session_facts = process_message_turn(
                step=step,
                user_input=user_input,
                session_entities=session_entities,
                session_facts=session_facts,
            )
            step += 1

        except (KeyboardInterrupt, EOFError):
            print(f"\n\n{C_CYAN}👋 Đã ngắt phiên test. Hẹn gặp lại!{C_RESET}\n")
            break
        except Exception as e:
            print(f"\n{C_RED}❌ Đã xảy ra lỗi: {str(e)}{C_RESET}\n")


if __name__ == "__main__":
    main()
