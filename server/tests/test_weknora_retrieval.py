#!/usr/bin/env python3
"""
Kiểm tra riêng biệt endpoint WeKnora Retrieval
Vị trí: server/tests/test_weknora_retrieval.py
Sử dụng:
    uv run python tests/test_weknora_retrieval.py
    uv run python tests/test_weknora_retrieval.py "Câu hỏi khác..."
"""

import os
import sys
import json
import asyncio
from typing import List, Dict, Any

SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from core.config import settings
from services.weknora import weknora_service

# ANSI Colors
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_banner(text: str, color: str = CYAN):
    print(f"\n{color}{BOLD}{'=' * 75}{RESET}")
    print(f"{color}{BOLD}  {text}{RESET}")
    print(f"{color}{BOLD}{'=' * 75}{RESET}\n")


def test_weknora_retrieval(query: str, match_count: int = 5):
    print_banner(f"🔍 TEST WEKNORA RETRIEVAL ENDPOINT — \"{query}\"")

    # 1. Cấu hình hiện tại
    print(f"{BOLD}1. THÔNG SỐ CẤU HÌNH HỆ THỐNG:{RESET}")
    print(f"   • WeKnora Base URL   : {CYAN}{settings.BASE_URL}{RESET}")
    print(f"   • API Key đã cấu hình: {GREEN}{bool(settings.WEKNORA_API_KEY)}{RESET}")
    print(f"   • WEKNORA_DATASET_ID : {YELLOW}{settings.WEKNORA_DATASET_ID or '(Trống)'}{RESET}")

    kb_ids = weknora_service.get_configured_kb_ids()
    print(f"   • Target Knowledge Bases: {CYAN}{kb_ids}{RESET}")

    # 2. Kiểm tra các Knowledge Base và Documents trên Server
    print(f"\n{BOLD}2. DANH SÁCH KNOWLEDGE BASES TRÊN WEKNORA:{RESET}")
    try:
        import httpx
        with httpx.Client(timeout=10.0) as client:
            res = client.get(f"{settings.BASE_URL}/knowledge-bases", headers=weknora_service.headers)
            if res.status_code == 200:
                kbs = res.json().get("data", [])
                for kb in kbs:
                    print(f"   📦 [{kb.get('id')}] {BOLD}{kb.get('name')}{RESET} (chunks: {kb.get('chunk_count', 0)})")
                    # Lấy danh sách tài liệu
                    r_docs = client.get(f"{settings.BASE_URL}/knowledge-bases/{kb.get('id')}/knowledge", headers=weknora_service.headers)
                    if r_docs.status_code == 200:
                        docs = r_docs.json().get("data", [])
                        for d in docs:
                            print(f"      📄 doc_id={d.get('id')} | title={CYAN}{d.get('title')}{RESET} | status={d.get('parse_status')}")
            else:
                print(f"   {RED}Không thể lấy danh sách KBs (HTTP {res.status_code}): {res.text}{RESET}")
    except Exception as e:
        print(f"   {RED}Lỗi kết nối WeKnora: {e}{RESET}")

    # 3. Gọi endpoint /knowledge-search qua weknora_service.retrieve_sync
    print(f"\n{BOLD}3. THỰC HIỆN TRUY VẤN RETRIEVE (POST /knowledge-search):{RESET}")
    print(f"   Query: {YELLOW}\"{query}\"{RESET}")
    print(f"   Match Count: {match_count}")

    chunks = weknora_service.retrieve_sync(query=query, match_count=match_count)

    print(f"\n{BOLD}4. KẾT QUẢ TRẢ VỀ TỪ WEKNORA:{RESET}")
    if not chunks:
        print(f"   {RED}❌ Không có chunk nào được trả về!{RESET}")
        return

    print(f"   {GREEN}✔ Tìm thấy {len(chunks)} chunks liên quan:{RESET}\n")

    for i, c in enumerate(chunks, 1):
        title = c.get("knowledge_title") or c.get("document_name") or "Không tên"
        score = c.get("score", 0.0)
        chunk_id = c.get("id") or "N/A"
        kb_id = c.get("knowledge_base_id") or "N/A"
        content = c.get("content", "").strip()

        print(f"{CYAN}{'─' * 70}{RESET}")
        print(f"{BOLD}Chunk #{i} | {GREEN}{title}{RESET} | Score: {YELLOW}{score:.4f}{RESET} | KB: {kb_id}")
        print(f"{DIM}Chunk ID: {chunk_id}{RESET}")
        print(f"\n{content}\n")

    print(f"{CYAN}{'─' * 70}{RESET}")
    print(f"{GREEN}{BOLD}🎉 Hoàn tất kiểm tra Retrieval thành công!{RESET}\n")


if __name__ == "__main__":
    test_query = sys.argv[1] if len(sys.argv) > 1 else "Thông tin tổng quan dự án Hilark"
    test_weknora_retrieval(test_query)
