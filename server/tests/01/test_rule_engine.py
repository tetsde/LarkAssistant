"""
Unit Tests cho Unified Rule Engine (server/utils/rule_engine.py)
==============================================================
Kiểm thử các tầng bảo mật của Rule Engine:
  1. Tầng 1: Canonical Property Mapping (Ngân sách -> budget, Lương -> salary...)
  2. Tầng 2: Dynamic Literal Substring Scan (Bất kỳ nhãn mới nào từ Lark Base: "Thầu phụ", "Đối tác chiến lược"...)
  3. Phòng chống False-Positive: Nhãn "Lương" không chặn nhầm "Số lượng"
  4. Hỗ trợ Unaccented Match cho các nhãn nhiều từ
  5. Tuple unpacking và tương thích đa cấu trúc (Dict, Fact, RetrievedChunk)
"""

import unittest
from utils.rule_engine import (
    UnifiedRuleEngine,
    SanitizeResult,
    parse_labels,
    remove_vietnamese_accents,
    rule_engine,
    sanitize,
)
from models.memory import Fact, FactStatus


class TestUnifiedRuleEngine(unittest.TestCase):

    def setUp(self):
        self.engine = UnifiedRuleEngine()

    def test_parse_labels(self):
        # String dạng danh sách phân tách bởi dấu phẩy và chấm phẩy
        s = "Ngân sách, Lương; Thầu phụ, Ngân sách\nBảo mật"
        labels = parse_labels(s)
        self.assertEqual(labels, ["Ngân sách", "Lương", "Thầu phụ", "Bảo mật"])

        # List chứa dicts từ Lark Base multi-select
        raw_list = [{"text": "Ngân sách"}, {"text": "Dự án mật"}, "Chi phí"]
        labels2 = parse_labels(raw_list)
        self.assertEqual(labels2, ["Ngân sách", "Dự án mật", "Chi phí"])

    def test_tier1_canonical_property_mapping(self):
        """Nhãn 'Ngân sách' phải tự động chặn các claim có property 'budget', 'cost'."""
        claims = [
            {"id": "c1", "property": "budget", "value": "150 triệu", "source_snippet": "Atlas budget"},
            {"id": "c2", "property": "cost", "value": "20 triệu", "source_snippet": "Chi phí thiết kế"},
            {"id": "c3", "property": "deadline", "value": "30/10/2026", "source_snippet": "Deadline 30/10"},
        ]

        result = self.engine.sanitize(
            claims=claims,
            forbidden_labels=["Ngân sách"],
        )

        # c1 và c2 bị loại bỏ, c3 được giữ lại
        self.assertEqual(len(result.clean_claims), 1)
        self.assertEqual(result.clean_claims[0]["id"], "c3")
        self.assertEqual(len(result.dropped_claims), 2)
        dropped_ids = [c["id"] for c in result.dropped_claims]
        self.assertIn("c1", dropped_ids)
        self.assertIn("c2", dropped_ids)

    def test_tier2_dynamic_label_larkbase(self):
        """Khi Sếp tạo nhãn cấm mới trên Lark Base: 'Thầu phụ'."""
        chunks = [
            {
                "chunk_id": "chk_1",
                "content": "Phần thầu phụ của dự án sẽ do công ty An Phát đảm nhận.",
                "document_name": "Kế hoạch quý 4.docx",
            },
            {
                "chunk_id": "chk_2",
                "content": "Kiến trúc hệ thống sử dụng microservices và Golang.",
                "document_name": "Tài liệu kỹ thuật.pdf",
            },
        ]

        claims = [
            {
                "id": "cl_1",
                "property": "scope",
                "value": "Phần thầu phụ giao bên thứ 3",
                "source_snippet": "thầu phụ đã chốt",
            },
            {
                "id": "cl_2",
                "property": "assignee",
                "value": "Trí AI",
                "source_snippet": "giao Trí phụ trách AI",
            },
        ]

        result = self.engine.sanitize(
            chunks=chunks,
            claims=claims,
            forbidden_labels=["Thầu phụ"],
        )

        # Chunks: chk_1 bị loại, chk_2 an toàn
        self.assertEqual(len(result.clean_chunks), 1)
        self.assertEqual(result.clean_chunks[0]["chunk_id"], "chk_2")
        self.assertEqual(len(result.dropped_chunks), 1)
        self.assertEqual(result.dropped_chunks[0]["chunk_id"], "chk_1")

        # Claims: cl_1 bị loại, cl_2 an toàn
        self.assertEqual(len(result.clean_claims), 1)
        self.assertEqual(result.clean_claims[0]["id"], "cl_2")
        self.assertEqual(len(result.dropped_claims), 1)
        self.assertEqual(result.dropped_claims[0]["id"], "cl_1")

    def test_false_positive_protection_so_luong(self):
        """Nhãn 'Lương' tuyệt đối không được chặn nhầm cụm từ 'Số lượng'."""
        chunks = [
            {
                "chunk_id": "chk_sl",
                "content": "Số lượng thành viên trong team hiện tại là 10 người.",
                "document_name": "Báo cáo nhân sự.pdf",
            },
            {
                "chunk_id": "chk_luong",
                "content": "Mức lương cơ bản của kỹ sư là 25 triệu.",
                "document_name": "Chính sách nhân sự.pdf",
            },
        ]

        result = self.engine.sanitize(
            chunks=chunks,
            forbidden_labels=["Lương"],
        )

        # chk_sl ("Số lượng") PHẢI ĐƯỢC GIỮ LẠI!
        # chk_luong ("Mức lương") PHẢI BỊ LOẠI BỎ!
        self.assertEqual(len(result.clean_chunks), 1)
        self.assertEqual(result.clean_chunks[0]["chunk_id"], "chk_sl")
        self.assertEqual(len(result.dropped_chunks), 1)
        self.assertEqual(result.dropped_chunks[0]["chunk_id"], "chk_luong")

    def test_unaccented_matching_multiword(self):
        """Nhãn 'Hợp đồng đối tác' phải chặn được cả khi người viết gõ 'hop dong doi tac'."""
        chunks = [
            {
                "chunk_id": "chk_unaccent",
                "content": "Lưu ý ve hop dong doi tac phai bao mat thong tin.",
                "document_name": "Ghi chú.txt",
            }
        ]

        result = self.engine.sanitize(
            chunks=chunks,
            forbidden_labels=["Hợp đồng đối tác"],
        )
        self.assertEqual(len(result.clean_chunks), 0)
        self.assertEqual(len(result.dropped_chunks), 1)

    def test_tuple_unpacking(self):
        """Hỗ trợ unpack trực tiếp: clean_chunks, clean_claims = rule_engine.sanitize(...)"""
        chunks = [{"content": "An toàn", "document_name": "doc1"}]
        claims = [{"property": "status", "value": "active"}]

        clean_chunks, clean_claims = sanitize(
            chunks=chunks,
            claims=claims,
            forbidden_labels=[],
        )
        self.assertEqual(len(clean_chunks), 1)
        self.assertEqual(len(clean_claims), 1)

    def test_fact_object_support(self):
        """Hỗ trợ truyền vào danh sách các Fact instance trực tiếp từ models.memory."""
        fact_safe = Fact(
            id="f1",
            entity_id="ent_1",
            property="assignee",
            value="Nguyễn Văn A",
            status=FactStatus.CURRENT,
        )
        fact_unsafe = Fact(
            id="f2",
            entity_id="ent_1",
            property="budget",
            value="500 triệu",
            status=FactStatus.CURRENT,
        )

        clean_chunks, clean_claims = sanitize(
            claims=[fact_safe, fact_unsafe],
            forbidden_labels=["Ngân sách"],
        )
        self.assertEqual(len(clean_claims), 1)
        self.assertEqual(clean_claims[0]["id"], "f1")


if __name__ == "__main__":
    unittest.main()
