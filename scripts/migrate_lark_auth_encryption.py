"""
HiLark - MongoDB Auth Encryption & Legacy Cleanup Migration
=========================================================
Vị trí: scripts/migrate_lark_auth_encryption.py

Mục đích:
  1. Chuẩn hóa collection `lark_auth`:
     - Mã hóa AES-256 Fernet cho `access_token` và `refresh_token` plaintext
       đang nằm trong DB, gắn cờ `token_encrypted: True`.
     - Phát hiện document legacy `_id == "primary_user_token"`: khi `--apply`
       sẽ mã hóa token (nếu còn plaintext), lưu trữ an toàn sang
       `_id == "archived_legacy_primary_user_token"` (`archived_legacy=True`)
       và xóa bản ghi `_id == "primary_user_token"` để không còn tồn tại trong
       truy vấn hoạt động.
  2. Hỗ trợ `--dry-run` (mặc định, chỉ đọc và thống kê) và `--apply` để thực thi.
     Chạy lại sau `--apply` là idempotent (`total_pending_docs == 0`).

Cách chạy:
  python3 scripts/migrate_lark_auth_encryption.py --help
  cd server && .venv/bin/python ../scripts/migrate_lark_auth_encryption.py --dry-run
  cd server && .venv/bin/python ../scripts/migrate_lark_auth_encryption.py --apply
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
import sys
from typing import Any, Dict, List, Optional, Tuple


ARCHIVED_LEGACY_PRIMARY_DOC_ID = "archived_legacy_primary_user_token"
LEGACY_PRIMARY_DOC_ID = "primary_user_token"


def _ensure_server_on_path() -> None:
    server_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "server",
    )
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)


def _doc_filter(doc: Dict[str, Any]) -> Dict[str, Any]:
    if "_id" in doc and doc["_id"] is not None:
        return {"_id": doc["_id"]}
    key_filter: Dict[str, Any] = {}
    for field in ("app_id", "tenant_key", "open_id"):
        if field in doc and doc[field] is not None:
            key_filter[field] = doc[field]
    return key_filter or dict(doc)


def _encrypt_secret_if_needed(raw_value: Any, ai_config_manager: Any) -> Tuple[str, bool, bool]:
    """
    Trả về `(final_value, has_secret, was_plaintext)`.
    - Chỉ mã hóa khi giá trị khác rỗng và chưa phải Fernet hợp lệ.
    """
    if raw_value is None:
        return "", False, False
    val = str(raw_value).strip()
    if not val:
        return "", False, False
    if val.startswith("gAAAAA"):
        decrypted = ai_config_manager.decrypt_key(val)
        if decrypted:
            return val, True, False
    return ai_config_manager.encrypt_key(val), True, True


def _migrate_lark_auth(
    target_db: Any,
    *,
    auth_coll_name: str,
    ai_config_manager: Any,
    apply: bool,
) -> Dict[str, Any]:
    col = target_db[auth_coll_name]
    docs: List[Dict[str, Any]] = list(col.find({}))
    now_iso = datetime.now(timezone.utc).isoformat()

    stats: Dict[str, Any] = {
        "collection": auth_coll_name,
        "total_docs": len(docs),
        "pending_docs": 0,
        "encrypt_pending_docs": 0,
        "legacy_primary_found": 0,
        "legacy_primary_archived": 0,
        "encrypted_docs": 0,
        "modified_docs": 0,
    }

    for doc in docs:
        doc_id = doc.get("_id")

        # 1. Xử lý document legacy dùng chung `_id == "primary_user_token"`
        if doc_id == LEGACY_PRIMARY_DOC_ID:
            stats["legacy_primary_found"] += 1
            stats["pending_docs"] += 1
            if apply:
                archived_payload = {k: v for k, v in doc.items() if k != "_id"}
                enc_acc, _, _ = _encrypt_secret_if_needed(
                    archived_payload.get("access_token"), ai_config_manager
                )
                enc_ref, _, _ = _encrypt_secret_if_needed(
                    archived_payload.get("refresh_token"), ai_config_manager
                )
                if "access_token" in archived_payload or enc_acc:
                    archived_payload["access_token"] = enc_acc
                if "refresh_token" in archived_payload or enc_ref:
                    archived_payload["refresh_token"] = enc_ref
                archived_payload["token_encrypted"] = True
                archived_payload["archived_legacy"] = True
                archived_payload["archived_from"] = LEGACY_PRIMARY_DOC_ID
                archived_payload["status"] = "archived_legacy"
                archived_payload["archived_at"] = now_iso
                archived_payload["updated_at"] = now_iso

                col.update_one(
                    {"_id": ARCHIVED_LEGACY_PRIMARY_DOC_ID},
                    {"$set": archived_payload},
                    upsert=True,
                )
                col.delete_one({"_id": LEGACY_PRIMARY_DOC_ID})
                stats["legacy_primary_archived"] += 1
                stats["modified_docs"] += 1
            continue

        # 2. Document thường (hoặc archived_legacy còn sót plaintext)
        enc_acc, has_acc, acc_was_plain = _encrypt_secret_if_needed(
            doc.get("access_token"), ai_config_manager
        )
        enc_ref, has_ref, ref_was_plain = _encrypt_secret_if_needed(
            doc.get("refresh_token"), ai_config_manager
        )

        has_any_secret = has_acc or has_ref
        needs_flag_backfill = has_any_secret and not bool(doc.get("token_encrypted"))
        needs_encrypt = acc_was_plain or ref_was_plain

        if needs_encrypt or needs_flag_backfill:
            stats["pending_docs"] += 1
            stats["encrypt_pending_docs"] += 1
            if apply:
                set_fields: Dict[str, Any] = {
                    "token_encrypted": True,
                    "updated_at": now_iso,
                }
                if acc_was_plain:
                    set_fields["access_token"] = enc_acc
                if ref_was_plain:
                    set_fields["refresh_token"] = enc_ref
                col.update_one(_doc_filter(doc), {"$set": set_fields})
                stats["encrypted_docs"] += 1
                stats["modified_docs"] += 1

    return stats


def _print_summary(summary: Dict[str, Any]) -> None:
    mode_label = "APPLY" if summary["apply"] else "DRY-RUN"
    la = summary["lark_auth"]

    print(f"=== MIGRATION MÃ HÓA LARK AUTH [{mode_label}] ===")
    print(f"\n[Collection: {la['collection']}]")
    print(f"  - Tổng số document: {la['total_docs']}")
    print(f"  - Cần migrate: {la['pending_docs']}")
    print(f"  - Bản ghi plaintext/thiếu cờ token_encrypted: {la['encrypt_pending_docs']}")
    print(f"  - Bản ghi legacy `primary_user_token` phát hiện: {la['legacy_primary_found']}")
    if summary["apply"]:
        print(f"  - Đã mã hóa AES-256 Fernet: {la['encrypted_docs']}")
        print(f"  - Đã lưu trữ & gỡ `primary_user_token`: {la['legacy_primary_archived']}")
        print(f"  - Tổng document đã cập nhật: {la['modified_docs']}")

    print("\n--- TỔNG KẾT ---")
    print(f"  - Tổng số document: {summary['total_docs']}")
    print(f"  - Tổng số document cần migrate: {summary['total_pending_docs']}")
    if not summary["apply"]:
        print("\n[DRY RUN] Không có thay đổi nào được ghi xuống MongoDB.")
        print("Để thực thi mã hóa & dọn legacy, chạy lại với cờ `--apply`.")
    else:
        print(f"  - Tổng số document đã sửa/dọn: {summary['total_modified_docs']}")


def run_migration(apply: bool = False, db: Any = None) -> Dict[str, Any]:
    """
    Chạy migration mã hóa AES-256 Fernet cho `lark_auth` và lưu trữ `primary_user_token`.

    Args:
        apply: False (mặc định) = dry-run chỉ đọc; True = thực thi update/archive vào DB.
        db: PyMongo Database (hoặc fake DB khi unit test). Nếu None sẽ gọi `get_sync_db()`.
    """
    _ensure_server_on_path()
    from core.config import settings
    from database.db import get_sync_db
    from services.ai.ai_config_manager import ai_config_manager

    target_db = db if db is not None else get_sync_db()
    auth_coll_name = getattr(settings, "MONGO_AUTH_COLLECTION", "lark_auth")

    lark_auth_stats = _migrate_lark_auth(
        target_db,
        auth_coll_name=auth_coll_name,
        ai_config_manager=ai_config_manager,
        apply=apply,
    )

    summary: Dict[str, Any] = {
        "mode": "apply" if apply else "dry_run",
        "apply": bool(apply),
        "lark_auth": lark_auth_stats,
        "total_docs": lark_auth_stats["total_docs"],
        "total_pending_docs": lark_auth_stats["pending_docs"],
        "total_modified_docs": lark_auth_stats["modified_docs"],
    }
    _print_summary(summary)
    return summary


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Mã hóa AES-256 Fernet cho token trong `lark_auth` và lưu trữ "
            "bản ghi legacy `primary_user_token`."
        )
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
        help="Thực thi mã hóa và dọn bản ghi legacy vào MongoDB",
    )
    args = parser.parse_args(argv)
    run_migration(apply=bool(args.apply))


if __name__ == "__main__":
    main()

