"""
Unit Test & Demonstration cho ContextComposer
============================================
Vị trí: server/tests/test_context_composer.py

Chạy:
    python server/tests/test_context_composer.py
"""

import os
import sys

# Đảm bảo import được các module từ server
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from utils.context_composer import (
    ContextComposer,
    compose_context,
    RetrievedChunk,
    NormalizedClaim,
)


def test_composer_basic():
    print("\n" + "=" * 60)
    print("TEST 1: ĐÓNG GÓI CƠ BẢN (CHUNKS TỪ WEKNORA + FACTS TỪ MONGODB)")
    print("=" * 60)

    # 1. Giả lập dữ liệu WeKnora Retriever trả về từ file PDF du_an_mau_hilark.pdf
    mock_weknora_retriever = [
        {
            "content": (
                "Dự án HiLark Assistant (Mã PRJ-HILARK-2026) được khởi động từ 01/10/2026. "
                "Tổng ngân sách phê duyệt ban đầu là 650.000.000 VNĐ. "
                "Hạn hoàn thành mốc M4 là 15/11/2026. "
                "Trần Mỹ Linh phụ trách Module Tích hợp Đa kênh."
            ),
            "document_name": "du_an_mau_hilark.pdf",
            "chunk_id": "chunk_a1e9f3ad",
            "score": 0.92,
        }
    ]

    # 2. Giả lập dữ liệu Claims/Facts đã được trích xuất từ các cuộc thảo luận chat
    mock_claims_from_mongo = [
        {
            "id": "fact_5f1d050f",
            "entity_id": "ent_hilark",
            "_entity_name": "HiLark",
            "property": "budget",
            "value": "800 triệu VNĐ",
            "status": "current",
            "replaces": "fact_168a17ef",
            "source": {"snippet": "dự án 650 triệu được tăng tổng ngân sách lên 800 triệu VNĐ"},
        },
        {
            "id": "fact_168a17ef",
            "entity_id": "ent_hilark",
            "_entity_name": "HiLark",
            "property": "budget",
            "value": "650 triệu VNĐ",
            "status": "superseded",
            "source": {"snippet": "Dự án HiLark hiện tại đã được duyệt tổng ngân sách là 650 triệu VNĐ"},
        },
        {
            "id": "fact_de18589f",
            "entity_id": "ent_hilark",
            "_entity_name": "HiLark",
            "property": "deadline",
            "value": "25/11/2026",
            "status": "current",
            "replaces": "fact_1e5c41eb",
            "source": {"snippet": "chốt dời deadline mốc M4 sang ngày 25/11/2026"},
        },
        {
            "id": "fact_5c1a2a76",
            "entity_id": "ent_module_integration",
            "_entity_name": "Module Tích hợp Đa kênh",
            "property": "assignee",
            "value": "Nguyên",
            "status": "current",
            "replaces": "fact_f9992884",
            "source": {"snippet": "Linh chuyển giao Module Tích hợp Đa kênh sang cho Nguyên phụ trách chính nhé."},
        },
    ]

    composer = ContextComposer()
    result = composer.compose(
        retriever_data=mock_weknora_retriever,
        claims_data=mock_claims_from_mongo,
        query="Sếp ơi cho em hỏi ngân sách dự án và deadline mốc M4 hiện tại là bao nhiêu?",
    )

    print("\n--- [1. CONTEXT TEXT OUTPUT] ---")
    print(result["context_text"])

    print("\n--- [2. METADATA STATS] ---")
    print(f"Chunks: {result['metadata']['num_chunks']}")
    print(f"Claims: {result['metadata']['num_claims']} (Active: {result['metadata']['num_active_claims']}, Superseded: {result['metadata']['num_superseded_claims']})")
    print(f"Entities: {result['metadata']['entities_covered']}")
    print(f"Citations: {result['metadata']['citations']}")

    # Assertions
    assert result["metadata"]["num_chunks"] == 1
    assert result["metadata"]["num_claims"] == 4
    assert result["metadata"]["num_active_claims"] == 3
    assert result["metadata"]["num_superseded_claims"] == 1
    assert "800 triệu VNĐ" in result["context_text"]
    assert "du_an_mau_hilark.pdf" in result["context_text"]
    print("✔ TEST 1 PASSED!")


def test_composer_xml_format():
    print("\n" + "=" * 60)
    print("TEST 2: ĐÓNG GÓI DẠNG XML CHO CLAUDE / GEMINI")
    print("=" * 60)

    chunks = [{"content": "Chính sách nghỉ phép 12 ngày/năm.", "document_name": "HR_Policy.pdf"}]
    claims = [{"property": "leave_days", "value": "14 ngày", "status": "current", "_entity_name": "Chính sách"}]

    composer = ContextComposer()
    xml_output = composer.compose_xml(retriever_data=chunks, claims_data=claims, query="Nghỉ phép mấy ngày?")
    print(xml_output)

    assert "<knowledge_context>" in xml_output
    assert "<retrieved_documents>" in xml_output
    assert "<dynamic_claims>" in xml_output
    assert "HR_Policy.pdf" in xml_output
    print("✔ TEST 2 PASSED!")


def test_functional_compose_context():
    print("\n" + "=" * 60)
    print("TEST 3: FUNCTIONAL API COMPOSE_CONTEXT()")
    print("=" * 60)

    res = compose_context(
        retriever_data="Hệ thống chạy trên port 8000.",
        claims_data=[{"property": "port", "value": "8080", "status": "current"}],
        query="Server chạy port mấy?",
    )
    assert res["metadata"]["num_chunks"] == 1
    assert res["metadata"]["num_claims"] == 1
    print("✔ TEST 3 PASSED!")


if __name__ == "__main__":
    test_composer_basic()
    test_composer_xml_format()
    test_functional_compose_context()
    print("\n🎉 TOÀN BỘ TESTS ĐÃ VƯỢT QUA THÀNH CÔNG!")
