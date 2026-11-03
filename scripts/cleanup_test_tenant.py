"""
HiLark - Cleanup Test Tenant (GĐ6)
==================================
Vị trí: scripts/cleanup_test_tenant.py

Mục đích:
  Dọn một tenant rác do test/fixture để lại (mặc định `tenant_save_corp`) khỏi MỌI
  collection có field `tenant_key`. Trước khi GĐ2 xoá fallback `.env`, các luồng test
  ghi dữ liệu bằng tenant_key giả vào thẳng DB production → dữ liệu này không còn
  được đọc bởi resolver nhưng vẫn chiếm dung lượng và gây nhiễu audit.

Ràng buộc an toàn:
  - MẶC ĐỊNH LÀ DRY-RUN: chỉ đếm và liệt kê, không xoá gì cả.
  - Chỉ xoá khi có cả `--apply` lẫn câu xác nhận được gõ đúng tên tenant.
  - Không bao giờ xoá document `tenants` của tenant khác (filter luôn có tenant_key).
  - Không in MONGO_URL đầy đủ.

Cách chạy:
  cd server && python ../scripts/cleanup_test_tenant.py                  # xem sẽ xoá gì
  cd server && python ../scripts/cleanup_test_tenant.py --apply          # xoá thật
  cd server && python ../scripts/cleanup_test_tenant.py --tenant-key tk_other --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from core.config import settings  # noqa: E402
from database.db import get_sync_db  # noqa: E402

DEFAULT_TENANT_KEY = "tenant_save_corp"


def _mask_url(url: str) -> str:
    if not url:
        return "<empty>"
    if "@" in url:
        head, tail = url.split("@", 1)
        scheme = head.split("://", 1)[0] if "://" in head else ""
        host = tail.split("/", 1)[0]
        return f"{scheme}://***:***@{host}/***"
    return "<redacted>"


def _candidate_collections(db) -> List[str]:
    """Mọi collection user-created (bỏ `system.*`) — sẽ được lọc theo tenant_key."""
    return sorted(name for name in db.list_collection_names() if not name.startswith("system."))


def _survey(db, tenant_key: str, collections: List[str]) -> List[Dict[str, Any]]:
    """Đếm số bản ghi sẽ bị xoá ở từng collection. Chỉ đọc."""
    report: List[Dict[str, Any]] = []
    for name in collections:
        try:
            coll = db[name]
            total = coll.estimated_document_count()
            matched = coll.count_documents({"tenant_key": tenant_key}, maxTimeMS=10000)
        except Exception as exc:  # noqa: BLE001 - quyền đọc từng collection có thể khác nhau
            report.append({"collection": name, "error": str(exc)})
            continue
        report.append(
            {
                "collection": name,
                "total": total,
                "matched": matched,
                "samples": [
                    str(doc.get("_id"))
                    for doc in coll.find({"tenant_key": tenant_key}, {"_id": 1}).limit(5)
                ],
            }
        )
    return report


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Xoá một tenant test khỏi mọi collection có `tenant_key` (mặc định dry-run)."
    )
    parser.add_argument("--tenant-key", default=DEFAULT_TENANT_KEY, help="Tenant cần dọn (mặc định tenant_save_corp).")
    parser.add_argument("--apply", action="store_true", help="Thực sự xoá. Không có flag này thì chỉ báo cáo.")
    parser.add_argument("--collections", default="", help="Phạm vi hẹp, ví dụ 'tenants,chat_scopes' (mặc định: tất cả).")
    parser.add_argument("--mongo-url", default="", help="Ghi đè MONGO_URL (để chạy an toàn trên DB local khi audit production).")
    parser.add_argument("--mongo-db", default="", help="Ghi đè MONGO_DB.")
    args = parser.parse_args(argv)

    if args.mongo_url:
        settings.MONGO_URL = args.mongo_url
    if args.mongo_db:
        settings.MONGO_DB = args.mongo_db

    tenant_key = str(args.tenant_key or "").strip()
    if not tenant_key:
        print("[FAIL] --tenant-key không được rỗng.")
        return 2

    print("=" * 78)
    print(f"1. KẾT NỐI {'(DRY-RUN)' if not args.apply else '(APPLY — SẼ XOÁ)'}")
    print("=" * 78)
    print(f"MONGO_URL : {_mask_url(settings.MONGO_URL)}")
    print(f"MONGO_DB  : {settings.MONGO_DB}")
    print(f"ENVIRONMENT: {settings.ENVIRONMENT}")
    print(f"tenant_key: {tenant_key}")

    try:
        db = get_sync_db()
        db.command("ping")
    except Exception as exc:  # noqa: BLE001
        print(f"\n[FAIL] Không kết nối được MongoDB: {exc}")
        return 2

    collections = (
        [c.strip() for c in args.collections.split(",") if c.strip()]
        if args.collections
        else _candidate_collections(db)
    )

    print()
    print("=" * 78)
    print("2. PHẠM VI SẼ ẢNH HƯỞNG")
    print("=" * 78)
    report = _survey(db, tenant_key, collections)
    hit_total = 0
    for row in report:
        if "error" in row:
            print(f"  {row['collection']:34s} [WARN] {row['error']}")
            continue
        hit_total += row["matched"]
        mark = "—" if row["matched"] == 0 else f"✘ {row['matched']} bản ghi"
        print(f"  {row['collection']:34s} total={row['total']:<7} tenant_key match={mark}")
        if row["matched"] and not args.apply:
            print(f"      ids: {', '.join(row['samples'])}")

    tenant_doc = db[settings.MONGO_TENANTS_COLLECTION].find_one({"tenant_key": tenant_key})
    print()
    if tenant_doc:
        print(
            f"  tenants: status={tenant_doc.get('status')} app_id={str(tenant_doc.get('app_id') or '-')[:16]} "
            f"weknora_tenant_id={tenant_doc.get('weknora_tenant_id') or '-'}"
        )
    else:
        print(f"  tenants: KHÔNG có document cho '{tenant_key}' (có thể đã dọn một lần).")

    if hit_total == 0:
        print("\nKhông có bản ghi nào mang tenant_key này ⇒ không cần xoá.")
        return 0

    if not args.apply:
        print(f"\n[DRY-RUN] Sẽ xoá {hit_total} bản ghi. Chạy lại với --apply để xoá thật.")
        return 0

    # Xác nhận kiểu "gõ đúng mới được": tránh xoá nhầm khi chạy trong script/CI.
    answer = input(f"\nGõ đúng '{tenant_key}' để xác nhận XOÁ VĨNH VIỄN {hit_total} bản ghi: ").strip()
    if answer != tenant_key:
        print("[CANCELLED] Xác nhận không khớp ⇒ không xoá gì cả.")
        return 1

    print()
    print("=" * 78)
    print("3. THỰC HIỆN XOÁ")
    print("=" * 78)
    deleted_total = 0
    for row in report:
        if "error" in row or not row.get("matched"):
            continue
        try:
            result = db[row["collection"]].delete_many({"tenant_key": tenant_key})
            deleted_total += result.deleted_count
            print(f"  {row['collection']:34s} deleted={result.deleted_count}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {row['collection']:34s} [FAIL] {exc}")

    remaining = _survey(db, tenant_key, collections)
    leftovers = sum(r.get("matched", 0) for r in remaining if "error" not in r)
    print(f"\nĐã xoá: {deleted_total} | Còn lại mang tenant_key '{tenant_key}': {leftovers}")
    if leftovers:
        print("[WARN] Vẫn còn dữ liệu — kiểm tra collection có field tenant_key kiểu khác (list/nested).")
        return 3

    print("✔ Dọn xong. Chạy lại scripts/audit_tenant_config_readonly.py để xác nhận trạng thái DB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
