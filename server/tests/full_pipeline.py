#!/usr/bin/env python3
"""
HiLark Full Pipeline Test Lab
==============================
Vị trí: server/tests/full_pipeline.py

Luồng xử lý:
    Tin nhắn từ Lark (giả lập hoặc từ MongoDB)
      ↓
    LLM Extraction  →  Trích xuất Entities & Facts → Lưu MongoDB
      ↓
    Query Claims    →  Nạp facts mới nhất từ MongoDB
      ↓
    WeKnora Retrieve →  Lấy chunks văn bản từ Knowledge Base
      ↓
    Context Composer →  Ghép 2 nguồn thành 1 context hoàn chỉnh
      ↓
    Phản hồi (in context ra terminal / sẵn sàng truyền vào LLM)

Cách chạy:
    cd /Users/hoainam/Desktop/HiLark/server
    uv run python tests/full_pipeline.py                 # Interactive mode
    uv run python tests/full_pipeline.py --scenario      # Chạy kịch bản 5 turn mẫu
    uv run python tests/full_pipeline.py --single "Ngân sách dự án Alpha là bao nhiêu?"
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List, Optional

# ── Đảm bảo import được modules từ server ─────────────────────────────────────
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from database.db import (
    clear_mongo_stores_sync,
    get_all_entities_sync,
    get_all_facts_sync,
    save_extraction_to_mongo_sync,
)
from services.weknora import weknora_service
from utils.context_composer import ContextComposer
from utils.llm_extractor import extract

# ── ANSI Colors ────────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
PURPLE = "\033[95m"
CYAN   = "\033[96m"


# =============================================================================
# PRINT HELPERS
# =============================================================================

def banner(text: str, color: str = CYAN) -> None:
    line = "=" * 74
    print(f"\n{color}{BOLD}{line}")
    print(f"  {text}")
    print(f"{line}{RESET}")


def section(title: str, color: str = BLUE) -> None:
    print(f"\n{color}{BOLD}── {title} {'─' * max(0, 60 - len(title))}{RESET}")


def ok(msg: str) -> None:
    print(f"{GREEN}✔ {msg}{RESET}")


def warn(msg: str) -> None:
    print(f"{YELLOW}⚠ {msg}{RESET}")


def err(msg: str) -> None:
    print(f"{RED}✘ {msg}{RESET}")


def dim(msg: str) -> None:
    print(f"{DIM}{msg}{RESET}")


# =============================================================================
# STEP 1 — LLM EXTRACTION
# =============================================================================

def step_extract(
    message: str,
    step: int,
    session_entities: List[Dict[str, Any]],
    session_facts: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Trích xuất Entities & Facts từ tin nhắn qua LLM Extractor.
    Lưu kết quả vào MongoDB và trả về (entities, facts) mới nhất từ DB.
    """
    section("STEP 1 — LLM EXTRACTION", PURPLE)
    dim(f"   Đầu vào: \"{message}\"")
    dim(f"   Ngữ cảnh hiện tại: {len(session_entities)} entities | {len(session_facts)} facts")

    result = extract(
        query=message,
        workspace_id="default",
        source_message_id=f"pipe_{step:03d}",
        sender="LarkUser",
        existing_entities=session_entities,
        existing_facts=session_facts,
    )

    new_entities = result.get("entities") or result.get("memory", [])
    new_facts    = result.get("facts") or result.get("claims", [])
    superseded   = result.get("superseded_facts") or result.get("superseded_claims", [])

    # Lưu vào MongoDB
    save_extraction_to_mongo_sync(result)

    # Báo cáo nhanh
    print(f"   {CYAN}Entities mới:{RESET}   {len(new_entities)}")
    for e in new_entities:
        name = e.get("name") or e.get("canonical_name", "?")
        etype = e.get("type") or e.get("entity_type", "ENTITY")
        print(f"     • {BOLD}[{etype}]{RESET} {name}")

    print(f"   {CYAN}Facts mới:{RESET}      {len(new_facts)}")
    for f in new_facts:
        prop  = f.get("property") or f.get("predicate", "?")
        val   = f.get("value", "?")
        status = f.get("status", "current")
        color  = GREEN if status == "current" else YELLOW
        print(f"     • {color}[{status.upper()}]{RESET} {prop} = \"{val}\"")

    if superseded:
        print(f"   {YELLOW}Facts bị supersede:{RESET} {len(superseded)}")
        for f in superseded:
            prop = f.get("property") or f.get("predicate", "?")
            print(f"     • {DIM}[SUPERSEDED]{RESET} {prop} = \"{f.get('value')}\"")

    # Nạp lại từ MongoDB để đảm bảo đồng bộ
    latest_entities = get_all_entities_sync()
    latest_facts    = get_all_facts_sync()

    ok(f"Extraction xong. DB hiện có {len(latest_entities)} entities | {len(latest_facts)} facts.")
    return latest_entities, latest_facts


# =============================================================================
# STEP 2 — QUERY CLAIMS
# =============================================================================

def step_query_claims(
    query: str,
    all_facts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Lọc các claims relevant từ MongoDB dựa trên query.
    Đơn giản: trả về active claims (status = current).
    """
    section("STEP 2 — QUERY CLAIMS (từ MongoDB)", BLUE)

    active_claims = [f for f in all_facts if f.get("status", "current") == "current"]
    superseded_claims = [f for f in all_facts if f.get("status") == "superseded"]

    print(f"   Active claims:     {GREEN}{len(active_claims)}{RESET}")
    print(f"   Superseded claims: {DIM}{len(superseded_claims)}{RESET}")

    # Hiển thị active claims tóm tắt
    if active_claims:
        for c in active_claims[:10]:  # Giới hạn 10 để không tràn terminal
            prop     = c.get("property") or c.get("predicate", "?")
            val      = c.get("value", "?")
            ent_name = c.get("_entity_name") or c.get("entity_name") or c.get("entity_id", "?")
            print(f"     • {BOLD}{ent_name}{RESET}.{prop} = {GREEN}\"{val}\"{RESET}")
        if len(active_claims) > 10:
            dim(f"     ... và {len(active_claims) - 10} claims khác")

    ok(f"Query Claims xong. Trả về {len(active_claims)} active claims.")
    return active_claims


# =============================================================================
# STEP 3 — WEKNORA RETRIEVE
# =============================================================================

def step_weknora_retrieve(query: str, match_count: int = 5) -> List[Dict[str, Any]]:
    """
    Gọi WeKnora Knowledge Base để lấy các đoạn văn bản (chunks) liên quan đến query.
    """
    section("STEP 3 — WEKNORA RETRIEVE (Knowledge Base)", YELLOW)
    dim(f"   Query: \"{query}\"  |  match_count={match_count}")

    try:
        chunks = weknora_service.retrieve_sync(query=query, match_count=match_count)
    except Exception as e:
        warn(f"WeKnora retrieve lỗi: {e}")
        chunks = []

    if not chunks:
        warn("WeKnora không trả về kết quả nào (KB rỗng hoặc không match).")
        return []

    print(f"   Số chunks trả về: {CYAN}{len(chunks)}{RESET}")
    for i, chunk in enumerate(chunks, 1):
        doc  = chunk.get("knowledge_title") or chunk.get("document_name") or "Tài liệu"
        score = chunk.get("score", 0.0)
        snippet = str(chunk.get("content", ""))[:120].replace("\n", " ")
        print(f"     {i}. {BOLD}[{doc}]{RESET} score={score:.3f}")
        print(f"        {DIM}{snippet}...{RESET}")

    ok(f"WeKnora Retrieve xong. {len(chunks)} chunks tìm được.")
    return chunks


# =============================================================================
# STEP 4 — CONTEXT COMPOSER
# =============================================================================

def step_compose_context(
    query: str,
    chunks: List[Dict[str, Any]],
    claims: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Ghép chunks (WeKnora) + claims (MongoDB) thành 1 context hoàn chỉnh.
    """
    section("STEP 4 — CONTEXT COMPOSER", CYAN)

    composer = ContextComposer()

    # Chuẩn hóa chunks để composer nhận được (WeKnora dùng knowledge_title, composer dùng document_name)
    normalized_chunks = []
    for c in chunks:
        doc_name = (
            c.get("knowledge_title")
            or c.get("document_name")
            or "Tài liệu hệ thống"
        )
        normalized_chunks.append({
            "content": c.get("content", ""),
            "document_name": doc_name,
            "chunk_id": c.get("id") or c.get("chunk_id"),
            "score": c.get("score"),
        })

    result = composer.compose(
        retriever_data=normalized_chunks if normalized_chunks else None,
        claims_data=claims if claims else None,
        query=query,
        auto_align=True,
    )

    meta = result.get("metadata", {})
    print(f"   Chunks đưa vào:  {meta.get('num_chunks', 0)}")
    print(f"   Claims đưa vào:  {meta.get('num_claims', 0)}")
    print(f"     • Active:      {GREEN}{meta.get('num_active_claims', 0)}{RESET}")
    print(f"     • Superseded:  {DIM}{meta.get('num_superseded_claims', 0)}{RESET}")
    entities = meta.get("entities_covered", [])
    if entities:
        print(f"   Entities cover:  {PURPLE}{', '.join(entities)}{RESET}")

    ok("Context Composer xong.")
    return result


# =============================================================================
# PIPELINE ORCHESTRATOR
# =============================================================================

def run_pipeline(
    message: str,
    step: int,
    session_entities: List[Dict[str, Any]],
    session_facts: List[Dict[str, Any]],
    retrieve_count: int = 5,
    show_full_context: bool = False,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Chạy toàn bộ pipeline cho 1 tin nhắn.
    Trả về (session_entities, session_facts, composed_result)
    """
    banner(f"🔄 PIPELINE TURN #{step} — \"{message[:60]}{'...' if len(message) > 60 else ''}\"")

    # ── Step 1: LLM Extraction ─────────────────────────────────────────────────
    session_entities, session_facts = step_extract(
        message=message,
        step=step,
        session_entities=session_entities,
        session_facts=session_facts,
    )

    # ── Step 2: Query Claims ───────────────────────────────────────────────────
    active_claims = step_query_claims(query=message, all_facts=session_facts)

    # ── Step 3: WeKnora Retrieve ───────────────────────────────────────────────
    chunks = step_weknora_retrieve(query=message, match_count=retrieve_count)

    # ── Step 4: Context Composer ───────────────────────────────────────────────
    composed = step_compose_context(
        query=message,
        chunks=chunks,
        claims=active_claims,
    )

    # ── Kết quả cuối ──────────────────────────────────────────────────────────
    banner("📦 KẾT QUẢ PIPELINE — CONTEXT SẴN SÀNG", GREEN)

    if show_full_context:
        print(composed.get("context_text", ""))
    else:
        # Chỉ hiện 800 ký tự đầu
        ctx = composed.get("context_text", "")
        preview = ctx[:800]
        print(preview)
        if len(ctx) > 800:
            dim(f"... [còn {len(ctx) - 800} ký tự] — thêm --full để xem toàn bộ")

    print(f"\n{DIM}Context text length: {len(composed.get('context_text', ''))} chars{RESET}")

    return session_entities, session_facts, composed


# =============================================================================
# KỊCH BẢN 5 TURN MẪU
# =============================================================================

SCENARIO_TURNS = [
    "Team mình khởi động dự án Alpha, Nam làm Project Lead và Tuấn làm Tech Lead, hạn chót ngày 15/11.",
    "Dự án Alpha ký hợp đồng với khách hàng Vingroup, ngân sách được duyệt là 400 triệu.",
    "Khách hàng Vingroup tăng yêu cầu nên nâng ngân sách lên 600 triệu và lùi deadline sang 30/11.",
    "Tuấn đang phụ trách phát triển module Payment Gateway cho Alpha, dự kiến xong trước 20/11.",
    "Do Tuấn bận dự án khác nên chuyển module Payment Gateway sang cho Hoàng làm.",
]


def run_scenario(retrieve_count: int = 5, show_full_context: bool = False) -> None:
    banner("▶ BẮT ĐẦU KỊCH BẢN 5 MULTI-TURN PIPELINE", GREEN)

    print(f"{YELLOW}🧹 Làm mới MongoDB trước khi chạy kịch bản...{RESET}")
    clear_mongo_stores_sync()

    session_entities: List[Dict[str, Any]] = []
    session_facts: List[Dict[str, Any]] = []

    for i, message in enumerate(SCENARIO_TURNS, 1):
        session_entities, session_facts, _ = run_pipeline(
            message=message,
            step=i,
            session_entities=session_entities,
            session_facts=session_facts,
            retrieve_count=retrieve_count,
            show_full_context=show_full_context,
        )
        if i < len(SCENARIO_TURNS):
            time.sleep(0.5)

    banner("🎉 HOÀN THÀNH KỊCH BẢN 5 MULTI-TURN PIPELINE!", GREEN)
    ok(f"Tổng: {len(session_entities)} entities | {len(session_facts)} facts đã được lưu vào MongoDB.")


# =============================================================================
# INTERACTIVE MODE
# =============================================================================

def run_interactive(retrieve_count: int = 5, show_full_context: bool = False) -> None:
    banner("🚀 HILARK FULL PIPELINE — INTERACTIVE MODE")
    print(f"{DIM}Lệnh: 'scenario' | 'clear' | 'full' (toggle xem toàn bộ context) | 'exit'{RESET}\n")

    session_entities = get_all_entities_sync()
    session_facts    = get_all_facts_sync()

    if session_entities or session_facts:
        ok(f"Đã nạp từ MongoDB: {len(session_entities)} entities | {len(session_facts)} facts")
    else:
        dim("MongoDB đang rỗng. Sẵn sàng nhận tin nhắn đầu tiên!")

    step = 1

    while True:
        try:
            prompt = f"\n{BOLD}{GREEN}👉 Tin nhắn #{step}:{RESET} "
            user_input = input(prompt).strip()

            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q"):
                print(f"\n{CYAN}👋 Thoát pipeline. Tạm biệt!{RESET}\n")
                break

            if user_input.lower() in ("clear", "reset"):
                clear_mongo_stores_sync()
                session_entities, session_facts = [], []
                step = 1
                warn("Đã xóa sạch MongoDB và reset session!")
                continue

            if user_input.lower() == "scenario":
                run_scenario(retrieve_count=retrieve_count, show_full_context=show_full_context)
                session_entities = get_all_entities_sync()
                session_facts    = get_all_facts_sync()
                step = len(SCENARIO_TURNS) + 1
                continue

            if user_input.lower() == "full":
                show_full_context = not show_full_context
                state = "BẬT" if show_full_context else "TẮT"
                ok(f"Hiển thị toàn bộ context: {state}")
                continue

            session_entities, session_facts, _ = run_pipeline(
                message=user_input,
                step=step,
                session_entities=session_entities,
                session_facts=session_facts,
                retrieve_count=retrieve_count,
                show_full_context=show_full_context,
            )
            step += 1

        except (KeyboardInterrupt, EOFError):
            print(f"\n\n{CYAN}👋 Đã ngắt phiên. Tạm biệt!{RESET}\n")
            break
        except Exception as e:
            err(f"Lỗi không mong đợi: {e}")
            import traceback
            traceback.print_exc()


# =============================================================================
# ENTRY POINT
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="HiLark Full Pipeline Lab: Lark → LLM Extraction → Query Claims → WeKnora → Context Composer"
    )
    parser.add_argument(
        "--scenario",
        action="store_true",
        help="Chạy tự động kịch bản 5 multi-turn",
    )
    parser.add_argument(
        "--single",
        type=str,
        default=None,
        metavar="MESSAGE",
        help="Chạy pipeline cho 1 tin nhắn đơn lẻ rồi thoát",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Xóa sạch MongoDB trước khi chạy",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Hiển thị toàn bộ context text (mặc định chỉ hiện 800 ký tự đầu)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Số lượng chunks lấy từ WeKnora (mặc định: 5)",
    )
    args = parser.parse_args()

    if args.clear:
        clear_mongo_stores_sync()
        warn("Đã xóa sạch dữ liệu MongoDB!")

    if args.single:
        session_entities = get_all_entities_sync()
        session_facts    = get_all_facts_sync()
        run_pipeline(
            message=args.single,
            step=1,
            session_entities=session_entities,
            session_facts=session_facts,
            retrieve_count=args.count,
            show_full_context=args.full,
        )
        return

    if args.scenario:
        run_scenario(retrieve_count=args.count, show_full_context=args.full)
        return

    run_interactive(retrieve_count=args.count, show_full_context=args.full)


if __name__ == "__main__":
    main()
