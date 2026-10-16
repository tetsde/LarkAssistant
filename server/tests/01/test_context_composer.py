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


def test_cross_matching_filter():
    print("\n" + "=" * 60)
    print("TEST 4: KIỂM THỬ SO KHỚP CHÉO (LỌC BỎ DỰ ÁN CRM KHỎI HILARK)")
    print("=" * 60)

    # 1. Chunk WeKnora chỉ nói về dự án HiLark
    chunks = [
        {
            "content": "Dự án HiLark Assistant PRJ-HILARK-2026. Quản lý bởi Nguyễn Hoài Nam. Module Tích hợp Đa kênh.",
            "document_name": "du_an_mau_hilark.pdf",
        }
    ]

    # 2. Danh sách Claims bị trộn lẫn giữa HiLark và Dự án CRM_V2
    mixed_claims = [
        # Claims của HiLark (PHẢI ĐƯỢC GIỮ LẠI)
        {
            "id": "fact_hilark_budget",
            "entity_id": "ent_hilark",
            "_entity_name": "HiLark",
            "property": "budget",
            "value": "800 triệu VNĐ",
            "status": "current",
        },
        {
            "id": "fact_hilark_deadline",
            "entity_id": "ent_hilark",
            "_entity_name": "HiLark",
            "property": "deadline",
            "value": "25/11/2026",
            "status": "current",
        },
        # Claims của CRM_V2 (PHẢI BỊ LOẠI BỎ)
        {
            "id": "fact_crm_budget",
            "entity_id": "ent_crm",
            "_entity_name": "Dự án CRM_V2",
            "property": "budget",
            "value": "1.5 tỷ VNĐ",
            "status": "current",
        },
        {
            "id": "fact_crm_deadline",
            "entity_id": "ent_crm",
            "_entity_name": "Dự án CRM_V2",
            "property": "deadline",
            "value": "31/12/2026",
            "status": "current",
        },
    ]

    composer = ContextComposer()
    result = composer.compose(
        retriever_data=chunks,
        claims_data=mixed_claims,
    )

    print("\n[CONTEXT TEXT SAU KHI LỌC SO KHỚP CHÉO]:")
    print(result["context_text"])

    # Kiểm tra: HiLark phải có mặt, CRM_V2 phải bị loại bỏ hoàn toàn
    assert "800 triệu VNĐ" in result["context_text"]
    assert "25/11/2026" in result["context_text"]
    assert "CRM_V2" not in result["context_text"]
    assert "1.5 tỷ VNĐ" not in result["context_text"]
    assert result["metadata"]["num_claims"] == 2
    assert "HiLark" in result["metadata"]["entities_covered"]
    assert "Dự án CRM_V2" not in result["metadata"]["entities_covered"]
    print("✔ TEST 4 PASSED: ĐÃ LỌC BỎ THÀNH CÔNG CLAIMS CỦA CRM RA KHỎI HILARK!")


def test_composer_authority_and_no_fallback():
    print("\n" + "=" * 60)
    print("TEST 5: THẨM QUYỀN (CEO VS ĐỀ XUẤT NHÂN SỰ) & KHÔNG FALLBACK RÁC")
    print("=" * 60)

    claims = [
        # Fact chốt của Sếp
        {
            "id": "fact_lead_official",
            "entity_id": "ent_atlas",
            "_entity_name": "Atlas",
            "property": "lead",
            "value": "Nguyên Trần",
            "status": "current",
            "asserted_by": {"user_id": "u_ceo", "user_name": "Nam CEO", "role": "owner"},
            "source": {"snippet": "Sếp chốt giao Nguyên làm lead Atlas"},
        },
        # Đề xuất của nhân sự khác
        {
            "id": "fact_lead_proposal",
            "entity_id": "ent_atlas",
            "_entity_name": "Atlas",
            "property": "lead",
            "value": "Hoài Phước",
            "status": "proposed",
            "asserted_by": {"user_id": "u_phuoc", "user_name": "Hoài Phước", "role": "member"},
            "source": {"snippet": "Cho em xin làm lead dự án này dc kh ạ?"},
        },
        # Fact của người hoàn toàn không liên quan (Trí AI)
        {
            "id": "fact_tri_role",
            "entity_id": "ent_tri",
            "_entity_name": "Trí",
            "property": "role",
            "value": "AI Engineer",
            "status": "current",
            "asserted_by": {"user_id": "u_tri", "user_name": "Trí", "role": "member"},
            "source": {"snippet": "Trí làm AI Engineer"},
        },
    ]

    composer = ContextComposer()

    # Case 1: Hỏi về Atlas -> Phải thấy Fact của Sếp và Đề xuất của Hoài Phước, KHÔNG có Trí!
    res_atlas = composer.compose(
        claims_data=claims,
        query="Ai làm lead dự án Atlas?",
        auto_align=True,
    )
    context_text = res_atlas["context_text"]
    print("\n[CONTEXT ATLAS]:\n", context_text)
    assert "⭐ [QUYẾT ĐỊNH CHÍNH THỨC TỪ CEO / BAN ĐIỀU HÀNH]" in context_text
    assert "Nguyên Trần" in context_text
    assert "💡 [ĐỀ XUẤT NHÂN SỰ / CHỜ DUYỆT (PROPOSED)]" in context_text
    assert "Hoài Phước" in context_text
    assert "Trí" not in context_text  # Trí bị loại bỏ hoàn toàn khỏi bối cảnh!

    # Case 2: Hỏi về đối tượng hoàn toàn không có trong database -> Trả về rỗng, KHÔNG DUMP TẤT CẢ!
    res_unknown = composer.compose(
        claims_data=claims,
        query="Tình hình dự án Blockchain XYZ thế nào?",
        auto_align=True,
    )
    print("\n[CONTEXT UNKNOWN]:\n", res_unknown["context_text"])
    assert res_unknown["metadata"]["num_claims"] == 0
    assert "Nguyên Trần" not in res_unknown["context_text"]
    assert "Trí" not in res_unknown["context_text"]
    print("✔ TEST 5 PASSED: ĐÃ PHÂN BIỆT THẨM QUYỀN VÀ KHÔNG FALLBACK RÁC!")


if __name__ == "__main__":
    test_composer_basic()
    test_composer_xml_format()
    test_functional_compose_context()
    test_cross_matching_filter()
    test_composer_authority_and_no_fallback()
    print("\n🎉 TOÀN BỘ TESTS ĐÃ VƯỢT QUA THÀNH CÔNG!")
