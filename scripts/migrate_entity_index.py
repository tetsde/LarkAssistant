"""
HiLark - MongoDB Index Migration & Backfill for Entity Isolation (B4 Fix)
========================================================================
Vị trí: scripts/migrate_entity_index.py

Mục đích:
  1. Drop index unique cũ `idx_memories_id_unique` (chỉ unique theo id toàn cầu).
  2. Backfill `tenant_key` cho mọi memory record đang trống / null sang `__LEGACY__`.
  3. Tạo compound unique index `idx_memories_tenant_id_unique` (unique theo (tenant_key, id)).
  4. Hỗ trợ --dry-run (mặc định) và --apply để thực thi an toàn.

Cách chạy:
  cd server && python ../scripts/migrate_entity_index.py            # Xem trước (Dry-run)
  cd server && python ../scripts/migrate_entity_index.py --apply    # Thực thi thật
"""

from __future__ import annotations

import argparse
import os
import sys

SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from pymongo import ASCENDING, IndexModel  # noqa: E402
from core.config import settings  # noqa: E402
from database.db import get_sync_db  # noqa: E402


def run_migration(apply: bool = False) -> None:
    db = get_sync_db()
    coll = db[settings.MONGO_MEMORY_COLLECTION]

    print(f"Collection: {settings.MONGO_MEMORY_COLLECTION}")
    existing_indexes = coll.index_information()
    print(f"Các index hiện tại ({len(existing_indexes)}): {list(existing_indexes.keys())}")

    # Đếm số record không có tenant_key
    orphan_count = coll.count_documents({"tenant_key": {"$in": [None, ""]}})
    total_count = coll.count_documents({})
    print(f"Tổng số thực thể: {total_count}, Số thực thể thiếu tenant_key: {orphan_count}")

    has_old_index = "idx_memories_id_unique" in existing_indexes
    has_new_index = "idx_memories_tenant_id_unique" in existing_indexes

    print(f"Index cũ 'idx_memories_id_unique' tồn tại: {has_old_index}")
    print(f"Index mới 'idx_memories_tenant_id_unique' tồn tại: {has_new_index}")

    if not apply:
        print("\n[DRY RUN] Chế độ xem trước - không có thay đổi nào được thực hiện.")
        print("Để thực thi, hãy chạy lại với cờ `--apply`.")
        return

    print("\n--- BẮT ĐẦU THỰC THI MIGRATION ---")

    # 1. Drop index cũ nếu còn
    if has_old_index:
        coll.drop_index("idx_memories_id_unique")
        print("✔ Đã drop index cũ: idx_memories_id_unique")
    else:
        print("ℹ Index cũ không tồn tại hoặc đã được drop trước đó.")

    # 2. Backfill tenant_key
    if orphan_count > 0:
        res = coll.update_many(
            {"tenant_key": {"$in": [None, ""]}},
            {"$set": {"tenant_key": "__LEGACY__"}}
        )
        print(f"✔ Đã backfill tenant_key='__LEGACY__' cho {res.modified_count} thực thể.")
    else:
        print("ℹ Không có thực thể nào cần backfill.")

    # 3. Tạo compound unique index mới
    if not has_new_index:
        new_model = IndexModel(
            [("tenant_key", ASCENDING), ("id", ASCENDING)],
            unique=True,
            name="idx_memories_tenant_id_unique"
        )
        created_name = coll.create_indexes([new_model])
        print(f"✔ Đã tạo index mới: {created_name}")
    else:
        print("ℹ Index mới đã tồn tại.")

    print("\n✅ Migration hoàn tất thành công!")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate MongoDB entity unique index for cross-tenant isolation.")
    parser.add_argument("--apply", action="store_true", help="Thực thi thay đổi thật sự vào DB")
    args = parser.parse_args()

    run_migration(apply=args.apply)


if __name__ == "__main__":
    main()

