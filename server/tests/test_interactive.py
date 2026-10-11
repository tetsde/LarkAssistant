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
    print("   Nhận tin nhắn tuần tự -> Bóc tách Thực thể (Memory) & Mệnh đề (Claim)")
    print("=" * 76 + C_RESET)
    print(f"{C_DIM}Lệnh hỗ trợ: Gõ 'clear' để làm mới bộ nhớ | Gõ 'exit' hoặc 'quit' để thoát.{C_RESET}\n")


def display_turn_result(turn_num: int, query: str, memory_list: list, new_claims: list, superseded_claims: list):
    print(f"\n{C_BOLD}{C_BLUE}--- [KẾT QUẢ TIN NHẮN #{turn_num}] ---{C_RESET}")
    print(f"{C_DIM}Nội dung: \"{query}\"{C_RESET}\n")

    # 1. Hiển thị Memory (Entities)
    print(f"{C_PURPLE}{C_BOLD}📦 NHÁNH 1: THỰC THỂ (MEMORY ENTITIES) - {len(memory_list)} thực thể:{C_RESET}")
    if not memory_list:
        print(f"   {C_DIM}(Không có thực thể mới){C_RESET}")
    else:
        for idx, m in enumerate(memory_list, 1):
            aliases_str = ", ".join(m.get("aliases", [])) if m.get("aliases") else "(Không có)"
            print(f"   {C_CYAN}{idx}. [{m.get('entity_type', 'UNKNOWN').upper()}]{C_RESET} {C_BOLD}{m.get('canonical_name')}{C_RESET}")
            print(f"      • ID:      {C_DIM}{m.get('_id')}{C_RESET}")
            print(f"      • Aliases: {C_YELLOW}{aliases_str}{C_RESET}")
            if m.get("description"):
                print(f"      • Mô tả:   {m.get('description')}")
            if m.get("attributes"):
                print(f"      • Thuộc tính: {m.get('attributes')}")

    # 2. Hiển thị Claims mới
    print(f"\n{C_CYAN}{C_BOLD}📋 NHÁNH 2: MỆNH ĐỀ MỚI TRÍCH XUẤT (CLAIMS) - {len(new_claims)} claim(s):{C_RESET}")
    if not new_claims:
        print(f"   {C_DIM}(Không có claim nào được trích xuất){C_RESET}")
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

            conf = c.get("confidence")
            conf_str = f" (độ tin cậy: {conf:.2f})" if conf is not None else ""
            print(f"   {idx}. {st_color}[{status.upper()}]{C_RESET} {C_BOLD}{c.get('predicate')}{C_RESET} = {C_GREEN}\"{c.get('value')}\"{C_RESET}{conf_str}")
            print(f"      • Claim ID:  {C_DIM}{c.get('_id')}{C_RESET}  |  Entity ID: {C_PURPLE}{c.get('entity_id')}{C_RESET}")
            
            # Highlight nếu thay thế claim cũ
            if c.get("supersedes"):
                print(f"      • {C_YELLOW}🔄 THAY THẾ CHO CLAIM CŨ: {c.get('supersedes')}{C_RESET}")

    # 3. Hiển thị Claim cũ bị Superseded (nếu có)
    if superseded_claims:
        print(f"\n{C_RED}{C_BOLD}⚠️ CÁC CLAIM CŨ VỪA BỊ CHUYỂN THÀNH [SUPERSEDED] ({len(superseded_claims)} claim):{C_RESET}")
        for old in superseded_claims:
            print(f"   • {C_RED}[SUPERSEDED]{C_RESET} ID: {C_DIM}{old.get('_id')}{C_RESET} | {old.get('predicate')} = \"{old.get('value')}\"")

    print(f"\n{C_DIM}" + "-" * 76 + C_RESET)


def display_session_summary(session_entities: list, session_claims: list):
    current_claims = [c for c in session_claims if c.get("status") == "current"]
    superseded_claims = [c for c in session_claims if c.get("status") == "superseded"]
    uncertain_claims = [c for c in session_claims if c.get("status") == "uncertain"]
    conflicted_claims = [c for c in session_claims if c.get("status") == "conflicted"]

    print(f"{C_BOLD}📊 TỔNG THỂ BỘ NHỚ HIỆN TẠI TRONG PHIÊN:{C_RESET}")
    print(f"   • Tổng số thực thể (Memory): {C_BOLD}{len(session_entities)}{C_RESET}")
    print(f"   • Tổng số claims: {C_BOLD}{len(session_claims)}{C_RESET} "
          f"({C_GREEN}Current: {len(current_claims)}{C_RESET} | "
          f"{C_RED}Superseded: {len(superseded_claims)}{C_RESET} | "
          f"{C_YELLOW}Uncertain: {len(uncertain_claims)}{C_RESET} | "
          f"{C_RED}Conflicted: {len(conflicted_claims)}{C_RESET})")
    print(f"{C_DIM}Đã lưu bản sao trạng thái vào: {OUTPUT_JSON_PATH}{C_RESET}\n")


def save_session_to_json(history: list, session_entities: list, session_claims: list):
    payload = {
        "updated_at": datetime.now().isoformat(),
        "total_messages": len(history),
        "history": history,
        "current_memory_entities": session_entities,
        "current_claims": session_claims,
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
