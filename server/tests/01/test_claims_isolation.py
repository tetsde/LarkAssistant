"""
Unit Tests: Claims & Facts Scope Isolation
==========================================
Kiểm tra tính cô lập tri thức giữa các nhóm chat và dự án khác nhau:
1. save_extraction_to_mongo và save_extraction_to_mongo_sync lưu đúng chat_id, project_tag, scope_type.
2. get_all_facts và get_all_facts_sync chỉ trả về facts thuộc đúng scope (hoặc global).
3. Tri thức nhóm A không bị rò rỉ sang nhóm B.
"""

import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from database.db import (
    get_all_facts,
    get_all_facts_sync,
    save_extraction_to_mongo,
    save_extraction_to_mongo_sync,
)


class TestClaimsScopeIsolation(unittest.IsolatedAsyncioTestCase):

    async def test_get_all_facts_scope_filtering_async(self):
        """Kiểm tra get_all_facts lọc chính xác theo chat_id và global."""
        mock_facts = [
            {"id": "fact_alpha_1", "chat_id": "oc_group_alpha", "project_tag": "Alpha", "scope_type": "chat"},
            {"id": "fact_beta_1", "chat_id": "oc_group_beta", "project_tag": "Beta", "scope_type": "chat"},
            {"id": "fact_global_1", "scope_type": "global"},
        ]

        class AsyncCursorMock:
            def __init__(self, items):
                self.items = list(items)

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self.items:
                    raise StopAsyncIteration
                return self.items.pop(0)

        with patch("database.db.get_claims_collection") as mock_get_col:
            mock_col = MagicMock()
            mock_get_col.return_value = mock_col

            def mock_find(query):
                # Giả lập logic MongoDB query filter
                filtered = []
                for f in mock_facts:
                    if "$or" in query:
                        or_conds = query["$or"]
                        matched = False
                        for cond in or_conds:
                            if "scope_type" in cond and f.get("scope_type") == cond["scope_type"]:
                                matched = True
                            if "chat_id" in cond and f.get("chat_id") == cond["chat_id"]:
                                matched = True
                            if "project_tag" in cond and f.get("project_tag") == cond["project_tag"]:
                                matched = True
                        if matched:
                            filtered.append(f)
                    else:
                        filtered.append(f)
                return AsyncCursorMock(filtered)

            mock_col.find.side_effect = mock_find

            # 1. Query cho Nhóm Alpha
            res_alpha = await get_all_facts(chat_id="oc_group_alpha", project_tag="Alpha")
            ids_alpha = [f["id"] for f in res_alpha]
            self.assertIn("fact_alpha_1", ids_alpha)
            self.assertIn("fact_global_1", ids_alpha)
            self.assertNotIn("fact_beta_1", ids_alpha, "Lỗi rò rỉ: Fact của nhóm Beta xuất hiện trong nhóm Alpha!")

            # 2. Query cho Nhóm Beta
            res_beta = await get_all_facts(chat_id="oc_group_beta", project_tag="Beta")
            ids_beta = [f["id"] for f in res_beta]
            self.assertIn("fact_beta_1", ids_beta)
            self.assertIn("fact_global_1", ids_beta)
            self.assertNotIn("fact_alpha_1", ids_beta, "Lỗi rò rỉ: Fact của nhóm Alpha xuất hiện trong nhóm Beta!")

            # 3. Query không truyền scope (backward compatible)
            res_all = await get_all_facts()
            self.assertEqual(len(res_all), 3)

    def test_get_all_facts_sync_scope_filtering(self):
        """Kiểm tra get_all_facts_sync lọc chính xác theo scope."""
        mock_facts = [
            {"id": "fact_a", "chat_id": "oc_alpha", "project_tag": "Alpha", "scope_type": "chat"},
            {"id": "fact_b", "chat_id": "oc_beta", "project_tag": "Beta", "scope_type": "chat"},
            {"id": "fact_g", "scope_type": "global"},
        ]

        with patch("database.db.get_sync_claims_collection") as mock_get_col:
            mock_col = MagicMock()
            mock_get_col.return_value = mock_col

            def mock_find(query):
                filtered = []
                for f in mock_facts:
                    if "$or" in query:
                        matched = any(
                            (cond.get("scope_type") and f.get("scope_type") == cond["scope_type"]) or
                            (cond.get("chat_id") and f.get("chat_id") == cond["chat_id"]) or
                            (cond.get("project_tag") and f.get("project_tag") == cond["project_tag"])
                            for cond in query["$or"]
                        )
                        if matched:
                            filtered.append(f)
                    else:
                        filtered.append(f)
                return filtered

            mock_col.find.side_effect = mock_find

            res_alpha = get_all_facts_sync(chat_id="oc_alpha")
            ids_alpha = [f["id"] for f in res_alpha]
            self.assertIn("fact_a", ids_alpha)
            self.assertIn("fact_g", ids_alpha)
            self.assertNotIn("fact_b", ids_alpha)

    async def test_save_extraction_to_mongo_persists_scope(self):
        """Kiểm tra save_extraction_to_mongo gán đúng scope_type, chat_id, project_tag."""
        extraction = {
            "entities": [{"id": "ent_1", "name": "Dự án Alpha"}],
            "facts": [{"id": "fact_1", "property": "deadline", "value": "2026-12-31"}],
            "superseded_facts": [],
        }

        with patch("database.db.upsert_entity", new_callable=AsyncMock) as mock_upsert_ent, \
             patch("database.db.get_claims_collection") as mock_get_claims, \
             patch("database.db.get_memories_collection") as mock_get_mem:

            mock_claims = MagicMock()
            mock_claims.update_one = AsyncMock()
            mock_claims.count_documents = AsyncMock(return_value=1)
            mock_get_claims.return_value = mock_claims

            mock_mem = MagicMock()
            mock_mem.count_documents = AsyncMock(return_value=1)
            mock_get_mem.return_value = mock_mem

            await save_extraction_to_mongo(
                extraction,
                chat_id="oc_group_123",
                project_tag="AlphaProject",
                scope_type="chat",
            )

            # Kiểm tra entity được gán scope
            called_entity = mock_upsert_ent.call_args[0][0]
            self.assertEqual(called_entity.get("chat_id"), "oc_group_123")
            self.assertEqual(called_entity.get("project_tag"), "AlphaProject")
            self.assertEqual(called_entity.get("scope_type"), "chat")

            # Kiểm tra fact được update với scope
            claim_update_call = mock_claims.update_one.call_args
            update_data = claim_update_call[0][1]["$set"]
            self.assertEqual(update_data.get("chat_id"), "oc_group_123")
            self.assertEqual(update_data.get("project_tag"), "AlphaProject")
            self.assertEqual(update_data.get("scope_type"), "chat")


if __name__ == "__main__":
    unittest.main()
