#!/usr/bin/env python3
"""
Kiểm thử Kịch bản Claims từ Tài liệu Kế hoạch Dự án HiLark (du_an_mau_hilark.pdf)
================================================================================
Vị trí: server/tests/test_pdf_claims.py

Mục tiêu:
    Mô phỏng vòng đời dự án từ Hồ sơ Kế hoạch gốc (Charter trong du_an_mau_hilark.pdf)
    đến các cuộc thảo luận chat thực tế gây ra biến động (Claims/Facts Timeline):
    1. Kịch bản 1: Chuyển giao trách nhiệm Module (Linh -> Nguyên).
    2. Kịch bản 2: Bổ sung phạm vi & Tăng ngân sách (650 triệu -> 800 triệu do Cowi).
    3. Kịch bản 3: Biến động lịch trình Mốc M4 (15/11 -> cuối tháng 11 -> 25/11/2026).

Cách chạy:
    cd /Users/hoainam/Desktop/HiLark/server
    python tests/test_pdf_claims.py           # Chạy truy vấn kiểm thử trên DB hiện tại
    python tests/test_pdf_claims.py --run-all # Chạy toàn bộ luồng nạp tin nhắn và kiểm thử
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List

SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from tests.query_claims import ClaimQuerier

# ANSI Colors
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_RED = "\033[91m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_BLUE = "\033[94m"
C_PURPLE = "\033[95m"
C_CYAN = "\033[96m"
C_DIM = "\033[2m"


PDF_SCENARIO_QUESTIONS = [
    {
        "id": "SCENARIO_1",
        "title": "KỊCH BẢN 1: Chuyển giao Phân hệ Tích hợp Đa kênh (Linh ➔ Nguyên)",
        "charter_fact": "PDF Charter: Linh phụ trách Module Tích hợp Đa kênh (Lark Suite Integration).",
        "chat_update": "Chat Update: Linh chuyển giao Module Tích hợp Đa kênh sang cho Nguyên phụ trách chính.",
        "question": "Module tích hợp Đa kênh của Hilark hiện tại do ai đảm nhận và trước đó do ai làm?",
        "expected_keywords": ["Nguyên", "Linh"],
    },
    {
        "id": "SCENARIO_2",
        "title": "KỊCH BẢN 2: Điều chỉnh Ngân sách Dự án (650 Triệu ➔ 800 Triệu VNĐ)",
        "charter_fact": "PDF Charter: Ngân sách duyệt ban đầu là 650.000.000 VNĐ.",
        "chat_update": "Chat Update: Khách hàng Cowi phê duyệt bổ sung hạ tầng AI, nâng tổng ngân sách lên 800 triệu VNĐ.",
        "question": "Dự án nào vừa được tăng ngân sách lên 800 triệu VNĐ và trước đó ngân sách là bao nhiêu?",
        "expected_keywords": ["800 triệu", "650 triệu"],
    },
    {
        "id": "SCENARIO_3",
        "title": "KỊCH BẢN 3: Dời Hạn Mốc Bàn giao M4 (15/11 ➔ Cuối tháng 11 ➔ 25/11/2026)",
        "charter_fact": "PDF Charter: Mốc M4 (Tích hợp bot sự kiện và UAT) có hạn chót 15/11/2026.",
        "chat_update": "Chat Update: Khách hàng xin lùi hạn cuối tháng 11, sau đó chốt chính thức dời sang 25/11/2026.",
        "question": "Mốc deadline M4 của dự án Hilark đã được chốt dời sang ngày nào? Lịch sử biến động ra sao?",
        "expected_keywords": ["25/11/2026", "15/11/2026"],
    },
    {
        "id": "SCENARIO_4",
        "title": "KỊCH BẢN 4: Đối tác Chiến lược & Trọng tâm Triển khai",
        "charter_fact": "PDF Charter: Đối tác & Khách hàng gồm Do Agency và Cowi Tech Group.",
        "chat_update": "Chat Update: Ký kết mở rộng với Cowi, nhóm dự án chuyển dịch trọng tâm từ Do Agency sang Cowi.",
        "question": "Đối tác khách hàng của dự án HiLark gồm những bên nào và có cập nhật gì mới về Cowi?",
        "expected_keywords": ["Cowi", "Do Agency"],
    },
]


def run_qa_tests():
    print(f"\n{C_CYAN}{C_BOLD}" + "=" * 80)
    print("   📋 KIỂM THỬ TRUY VẤN CLAIMS DỰ TRÊN TÀI LIỆU DU_AN_MAU_HILARK.PDF")
    print("   Đối chiếu giữa Hồ sơ Kế hoạch Gốc (PDF) và Lịch sử Biến động Chat (MongoDB)")
    print("=" * 80 + C_RESET)

    querier = ClaimQuerier(data_source="MONGODB")
    print(f"{C_GREEN}Dữ liệu hiện tại trong MongoDB:{C_RESET}")
    print(f" • Tổng số Thực thể (Entities): {C_BOLD}{len(querier.entities)}{C_RESET}")
    print(f" • Tổng số Mệnh đề (Facts/Claims): {C_BOLD}{len(querier.facts_by_id)}{C_RESET}\n")

    for idx, sc in enumerate(PDF_SCENARIO_QUESTIONS, 1):
        print(f"{C_PURPLE}{C_BOLD}--------------------------------------------------------------------------------{C_RESET}")
        print(f"{C_PURPLE}{C_BOLD}▶ [{idx}/4] {sc['title']}{C_RESET}")
        print(f"   {C_DIM}📄 {sc['charter_fact']}{C_RESET}")
        print(f"   {C_DIM}💬 {sc['chat_update']}{C_RESET}")
        print(f"   {C_CYAN}❓ CÂU HỎI:{C_RESET} {C_BOLD}\"{sc['question']}\"{C_RESET}")

        t0 = time.time()
        resp = querier.ask(sc["question"])
        elapsed = time.time() - t0

        answer = resp.get("answer", "")
        citations = resp.get("citations", [])
        extraction = resp.get("extraction")

        print(f"\n   {C_GREEN}{C_BOLD}🤖 AI TRẢ LỜI ({elapsed:.2f}s):{C_RESET}")
        print(f"   {answer}")

        if citations:
            c_docs = [c.get("doc", "Tài liệu") for c in citations]
            print(f"   {C_BLUE}📚 Nguồn trích dẫn (WeKnora): {', '.join(set(c_docs))}{C_RESET}")

        if extraction and extraction.get("facts"):
            print(f"   {C_YELLOW}💾 Đã ghi nhận thêm {len(extraction.get('facts'))} Facts mới vào MongoDB{C_RESET}")

        # Đánh giá sơ bộ
        matched_kw = [kw for kw in sc["expected_keywords"] if kw.lower() in answer.lower()]
        if len(matched_kw) == len(sc["expected_keywords"]):
            print(f"   {C_GREEN}✔ ĐÁNH GIÁ: CHÍNH XÁC HOÀN TOÀN (Khớp {', '.join(matched_kw)}){C_RESET}")
        else:
            print(f"   {C_YELLOW}⚠ ĐÁNH GIÁ: Khớp {len(matched_kw)}/{len(sc['expected_keywords'])} từ khóa ({', '.join(matched_kw)}){C_RESET}")

        print("")

    print(f"{C_CYAN}{C_BOLD}" + "=" * 80)
    print("   🎉 HOÀN TẤT KIỂM THỬ 4 KỊCH BẢN CLAIMS!")
    print("=" * 80 + C_RESET + "\n")


def main():
    parser = argparse.ArgumentParser(description="Kiểm thử Kịch bản Claims PDF HiLark")
    parser.add_argument("--run-all", action="store_true", help="Chạy toàn bộ kịch bản kiểm thử")
    args = parser.parse_args()

    run_qa_tests()


if __name__ == "__main__":
    main()
