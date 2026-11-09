"""
HiLark - MongoDB Schema Migration for Provider-Agnostic LLM & Telemetry
=======================================================================
Vị trí: scripts/migrate_llm_schema.py

Mục đích:
  1. Chuẩn hóa collection `user_settings`:
     - Backfill `encrypted_gemini_api_key` -> `encrypted_llm_api_key` (nếu thiếu/rỗng/None).
     - Backfill `masked_gemini_api_key` -> `masked_llm_api_key` (nếu thiếu/rỗng/None).
     - Mặc định khi `--apply` sẽ `$unset` xóa sạch `encrypted_gemini_api_key` và
       `masked_gemini_api_key` (trừ khi truyền `--keep-legacy`).
  2. Chuẩn hóa collection `cost_telemetry`:
     - Backfill `output_tokens` từ `candidates_tokens` (hoặc `0` nếu không có).
     - Backfill `thinking_tokens = 0` nếu thiếu/None.
     - Chuẩn hóa `service == "gemini"` -> `"google"`.
     - Mặc định khi `--apply` sẽ `$unset` xóa sạch `candidates_tokens` (trừ khi
       truyền `--keep-legacy`).
  3. Hỗ trợ `--dry-run` (mặc định, chỉ đọc và thống kê) và `--apply` để thực thi thật.

Cách chạy:
  cd server && python ../scripts/migrate_llm_schema.py                        # Dry-run (mặc định)
  cd server && python ../scripts/migrate_llm_schema.py --dry-run              # Dry-run tường minh
  cd server && python ../scripts/migrate_llm_schema.py --apply                # Backfill + $unset field cũ
  cd server && python ../scripts/migrate_llm_schema.py --apply --keep-legacy  # Backfill, giữ lại field cũ
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, Optional

SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from core.config import settings  # noqa: E402
from database.db import get_sync_db  # noqa: E402


USER_SETTINGS_QUERY: Dict[str, Any] = {
    "$or": [
        {"encrypted_gemini_api_key": {"$exists": True}},
        {"masked_gemini_api_key": {"$exists": True}},
    ]
}

TELEMETRY_QUERY: Dict[str, Any] = {
    "$or": [
        {"candidates_tokens": {"$exists": True}},
        {"output_tokens": {"$exists": False}},
        {"output_tokens": None},
        {"thinking_tokens": {"$exists": False}},
        {"thinking_tokens": None},
        {"service": "gemini"},
    ]
}


def _is_missing_or_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _count_total_docs(coll: Any) -> int:
    if hasattr(coll, "count_documents"):
        return int(coll.count_documents({}))
    return sum(1 for _ in coll.find({}))


def _extract_modified_count(res: Any) -> int:
    modified = getattr(res, "modified_count", None)
    if modified is None:
        return 1
    return int(modified)


def _build_user_settings_filter(doc: Dict[str, Any]) -> Dict[str, Any]:
    if "_id" in doc:
        return {"_id": doc["_id"]}
    if "open_id" in doc and doc["open_id"] is not None:
        doc_filter: Dict[str, Any] = {"open_id": doc["open_id"]}
        if "tenant_key" in doc:
            doc_filter["tenant_key"] = doc["tenant_key"]
        return doc_filter
    return dict(doc)


def _build_telemetry_filter(doc: Dict[str, Any]) -> Dict[str, Any]:
    if "_id" in doc:
        return {"_id": doc["_id"]}
    if "id" in doc and doc["id"] is not None:
        return {"id": doc["id"]}
    return dict(doc)


def _build_user_settings_update(
    doc: Dict[str, Any],
    keep_legacy: bool = False,
) -> Optional[Dict[str, Any]]:
    set_fields: Dict[str, Any] = {}
    unset_fields: Dict[str, str] = {}

    if _is_missing_or_empty(doc.get("encrypted_llm_api_key")) and not _is_missing_or_empty(
        doc.get("encrypted_gemini_api_key")
    ):
        set_fields["encrypted_llm_api_key"] = doc["encrypted_gemini_api_key"]

    if _is_missing_or_empty(doc.get("masked_llm_api_key")) and not _is_missing_or_empty(
        doc.get("masked_gemini_api_key")
    ):
        set_fields["masked_llm_api_key"] = doc["masked_gemini_api_key"]

    if not keep_legacy and (
        "encrypted_gemini_api_key" in doc or "masked_gemini_api_key" in doc
    ):
        unset_fields["encrypted_gemini_api_key"] = ""
        unset_fields["masked_gemini_api_key"] = ""

    update_doc: Dict[str, Any] = {}
    if set_fields:
        update_doc["$set"] = set_fields
    if unset_fields:
        update_doc["$unset"] = unset_fields
    return update_doc or None


def _build_telemetry_update(
    doc: Dict[str, Any],
    keep_legacy: bool = False,
) -> Optional[Dict[str, Any]]:
    set_fields: Dict[str, Any] = {}
    unset_fields: Dict[str, str] = {}

    if "output_tokens" not in doc or doc.get("output_tokens") is None:
        legacy_output = doc.get("candidates_tokens")
        set_fields["output_tokens"] = legacy_output if legacy_output is not None else 0

    if "thinking_tokens" not in doc or doc.get("thinking_tokens") is None:
        set_fields["thinking_tokens"] = 0

    if doc.get("service") == "gemini":
        set_fields["service"] = "google"

    if not keep_legacy and "candidates_tokens" in doc:
        unset_fields["candidates_tokens"] = ""

    update_doc: Dict[str, Any] = {}
    if set_fields:
        update_doc["$set"] = set_fields
    if unset_fields:
        update_doc["$unset"] = unset_fields
    return update_doc or None


def _migrate_user_settings(
    db: Any,
    apply: bool,
    keep_legacy: bool,
) -> Dict[str, Any]:
    coll_name = getattr(settings, "MONGO_USER_SETTINGS_COLLECTION", "user_settings")
    coll = db[coll_name]

    total_docs = _count_total_docs(coll)
    matched_docs = 0
    pending_docs = 0
    backfilled_docs = 0
    unset_docs = 0
    modified_docs = 0

    for doc in coll.find(USER_SETTINGS_QUERY):
        matched_docs += 1
        update_doc = _build_user_settings_update(doc, keep_legacy=keep_legacy)
        if not update_doc:
            continue
        pending_docs += 1
        if "$set" in update_doc:
            backfilled_docs += 1
        if "$unset" in update_doc:
            unset_docs += 1
        if apply:
            res = coll.update_one(_build_user_settings_filter(doc), update_doc)
            modified_docs += _extract_modified_count(res)

    return {
        "collection": coll_name,
        "total_docs": total_docs,
        "matched_docs": matched_docs,
        "pending_docs": pending_docs,
        "backfilled_docs": backfilled_docs,
        "unset_docs": unset_docs,
        "modified_docs": modified_docs,
    }


def _migrate_cost_telemetry(
    db: Any,
    apply: bool,
    keep_legacy: bool,
) -> Dict[str, Any]:
    coll_name = getattr(settings, "MONGO_TELEMETRY_COLLECTION", "cost_telemetry")
    coll = db[coll_name]

    total_docs = _count_total_docs(coll)
    matched_docs = 0
    pending_docs = 0
    backfilled_docs = 0
    unset_docs = 0
    modified_docs = 0

    for doc in coll.find(TELEMETRY_QUERY):
        matched_docs += 1
        update_doc = _build_telemetry_update(doc, keep_legacy=keep_legacy)
        if not update_doc:
            continue
        pending_docs += 1
        if "$set" in update_doc:
            backfilled_docs += 1
        if "$unset" in update_doc:
            unset_docs += 1
        if apply:
            res = coll.update_one(_build_telemetry_filter(doc), update_doc)
            modified_docs += _extract_modified_count(res)

    return {
        "collection": coll_name,
        "total_docs": total_docs,
        "matched_docs": matched_docs,
        "pending_docs": pending_docs,
        "backfilled_docs": backfilled_docs,
        "unset_docs": unset_docs,
        "modified_docs": modified_docs,
    }


def _print_collection_summary(label: str, stats: Dict[str, Any], apply: bool, keep_legacy: bool) -> None:
    print(f"\nCollection `{label}` ({stats['collection']}):")
    print(f"  - Tổng số document: {stats['total_docs']}")
    print(f"  - Số document khớp điều kiện legacy: {stats['matched_docs']}")
    print(f"  - Số document cần migrate: {stats['pending_docs']}")
    print(f"  - Số document cần backfill ($set): {stats['backfilled_docs']}")
    if keep_legacy:
        print("  - Xóa field cũ ($unset): KHÔNG (giữ lại do --keep-legacy)")
    else:
        print(f"  - Số document cần xóa field cũ ($unset): {stats['unset_docs']}")
    if apply:
        print(f"  - Số document đã sửa trong DB: {stats['modified_docs']}")


def run_migration(
    apply: bool = False,
    keep_legacy: bool = False,
    db: Any = None,
) -> Dict[str, Any]:
    """
    Chạy migration chuẩn hóa schema LLM (`user_settings` & `cost_telemetry`).

    Args:
        apply: False (mặc định) = dry-run chỉ đọc; True = thực thi update vào DB.
        keep_legacy: False (mặc định) = `$unset` field cũ; True = giữ lại field cũ.
        db: PyMongo Database (hoặc fake DB khi unit test). Nếu None sẽ gọi `get_sync_db()`.
    """
    target_db = db if db is not None else get_sync_db()
    unset_legacy_fields = not keep_legacy
    mode_label = "APPLY" if apply else "DRY-RUN"

    print(f"=== MIGRATION SCHEMA LLM [{mode_label}] ===")
    print(
        "Chính sách field cũ: "
        + ("$unset xóa sạch field cũ" if unset_legacy_fields else "giữ lại field cũ (--keep-legacy)")
    )

    user_settings_stats = _migrate_user_settings(
        target_db,
        apply=apply,
        keep_legacy=keep_legacy,
    )
    cost_telemetry_stats = _migrate_cost_telemetry(
        target_db,
        apply=apply,
        keep_legacy=keep_legacy,
    )

    summary: Dict[str, Any] = {
        "mode": "apply" if apply else "dry_run",
        "apply": bool(apply),
        "keep_legacy": bool(keep_legacy),
        "unset_legacy_fields": unset_legacy_fields,
        "user_settings": user_settings_stats,
        "cost_telemetry": cost_telemetry_stats,
        "total_docs": user_settings_stats["total_docs"] + cost_telemetry_stats["total_docs"],
        "total_pending_docs": user_settings_stats["pending_docs"] + cost_telemetry_stats["pending_docs"],
        "total_modified_docs": user_settings_stats["modified_docs"] + cost_telemetry_stats["modified_docs"],
    }

    _print_collection_summary("user_settings", user_settings_stats, apply=apply, keep_legacy=keep_legacy)
    _print_collection_summary("cost_telemetry", cost_telemetry_stats, apply=apply, keep_legacy=keep_legacy)

    print("\n--- TỔNG KẾT ---")
    print(f"  - Tổng số document (2 collections): {summary['total_docs']}")
    print(f"  - Tổng số document cần migrate: {summary['total_pending_docs']}")
    print(f"  - Có $unset field cũ hay không: {'CÓ' if unset_legacy_fields else 'KHÔNG'}")

    if not apply:
        print("\n[DRY RUN] Chế độ xem trước - không có thay đổi nào được thực hiện.")
        print("Để thực thi (backfill + $unset field cũ), hãy chạy lại với cờ `--apply`.")
    else:
        print(f"  - Tổng số document đã sửa: {summary['total_modified_docs']}")
        print("\n✅ Migration hoàn tất thành công!")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate MongoDB user_settings và cost_telemetry sang schema LLM provider-agnostic."
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Chế độ xem trước mặc định, không sửa dữ liệu trong DB",
    )
    mode_group.add_argument(
        "--apply",
        action="store_true",
        help="Thực thi thay đổi thật sự vào DB",
    )
    parser.add_argument(
        "--keep-legacy",
        action="store_true",
        help="Giữ lại các field cũ sau khi backfill (mặc định khi --apply sẽ $unset xóa sạch field cũ)",
    )
    args = parser.parse_args()

    run_migration(apply=bool(args.apply), keep_legacy=bool(args.keep_legacy))


if __name__ == "__main__":
    main()
