"""
HiLark - Read-Only Tenant Config Audit
=====================================
Vị trí: scripts/audit_tenant_config_readonly.py

Mục đích:
  Kiểm tra MongoDB đã lưu đủ cấu hình cho từng tenant (doanh nghiệp) chưa,
  và chỉ ra chính xác field nào đang phải fallback về .env.

Ràng buộc an toàn:
  - CHỈ ĐỌC. Không insert/update/delete bất kỳ collection nào.
  - Không in giá trị secret (app_secret, token, password). Chỉ in trạng thái SET/EMPTY.
  - Không in MONGO_URL đầy đủ (đã che user/password/host).

Cách chạy:
  cd server && python ../scripts/audit_tenant_config_readonly.py
  # Ghi đè DB để kiểm tra an toàn trên local/DB seed mà không đụng .env production:
  cd server && python ../scripts/audit_tenant_config_readonly.py --mongo-url mongodb://localhost:27017 --mongo-db LarkAssistant_test
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from core.config import settings  # noqa: E402
from database.db import get_sync_db  # noqa: E402

# Các field BẮT BUỘC phải có trong collection `tenants` để phục vụ runtime multi-tenant
REQUIRED_TENANT_FIELDS = [
    "app_id",
    "weknora_tenant_id",
    "weknora_policy_dataset_id",
    "weknora_wiki_dataset_id",
    "weknora_default_dataset_id",
    "bitable_app_token",
    "chat_scope_table_id",
    "company_policy_table_id",
]

# Các biến .env thuộc phạm vi tenant (không nên tồn tại trong production multi-tenant)
TENANT_SCOPED_ENV = [
    "LARK_APP_ID",
    "LARK_APP_SECRET",
    "LARK_VERIFICATION_TOKEN",
    "LARK_ENCRYPT_KEY",
    "WEKNORA_DATASET_ID",
    "WEKNORA_WIKI_DATASET_ID",
    "WEKNORA_POLICY_DATASET_ID",
    "LARK_BASE_APP_TOKEN",
    "LARK_BASE_TABLE_ID",
    "LARK_BASE_POLICY_TABLE_ID",
]

# Trạng thái vòng đời hợp lệ (đúng bảng trong services/tenancy/tenant_state.py).
# Khai báo tại chỗ để script không import `services.*` (tránh kéo theo vòng khởi động).
KNOWN_STATUSES = {
    "provisioning",
    "provisioning_failed",
    "ready",
    "active",
    "inactive",
    "uninstalled",
}
# Trạng thái mà resolver cho phép phục vụ dữ liệu thật.
SERVING_STATUSES = {"ready"}


def _set(value) -> str:
    """Trả về trạng thái SET/EMPTY, không bao giờ trả về giá trị thật."""
    if value is None:
        return "EMPTY"
    if isinstance(value, str):
        return "SET" if value.strip() else "EMPTY"
    if isinstance(value, (list, dict)):
        return "SET" if value else "EMPTY"
    return "SET"


def _mask_tenant(tenant_key) -> str:
    """Che tenant_key để log an toàn nhưng vẫn phân biệt được các dòng."""
    token = str(tenant_key or "<none>")
    if len(token) <= 8:
        return token
    return f"{token[:6]}…{token[-4:]}"


def _mask_url(url: str) -> str:
    if not url:
        return "<empty>"
    if "@" in url:
        head, tail = url.split("@", 1)
        scheme = head.split("://", 1)[0] if "://" in head else ""
        host = tail.split("/", 1)[0]
        return f"{scheme}://***:***@{host}/***"
    return "<redacted>"


def _section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit CHỈ ĐỌC cấu hình tenant trong MongoDB."
    )
    parser.add_argument("--mongo-url", default="", help="Ghi đè MONGO_URL (chạy an toàn trên DB local/seed).")
    parser.add_argument("--mongo-db", default="", help="Ghi đè MONGO_DB.")
    args = parser.parse_args(argv)

    # Ghi đè TRƯỚC khi get_sync_db(): settings bị .env nạp với override=True nên env var
    # bên ngoài không thắng được; flag là lối vào duy nhất an toàn.
    if args.mongo_url:
        settings.MONGO_URL = args.mongo_url
    if args.mongo_db:
        settings.MONGO_DB = args.mongo_db

    _section("0. KẾT NỐI")
    print(f"MONGO_URL : {_mask_url(settings.MONGO_URL)}")
    print(f"MONGO_DB  : {settings.MONGO_DB}")
    print(f"ENVIRONMENT: {settings.ENVIRONMENT}")
    print(f"IS_ISV_MODE: {settings.IS_ISV_MODE}")
    print(f"WEKNORA_PROVISION_DRY_RUN: {settings.WEKNORA_PROVISION_DRY_RUN}")

    try:
        db = get_sync_db()
        db.command("ping")
    except Exception as exc:  # noqa: BLE001
        print(f"\n[FAIL] Không kết nối được MongoDB: {exc}")
        return 2

    # ---------------------------------------------------------------- collections
    _section("1. COLLECTIONS & SỐ BẢN GHI")
    names = sorted(db.list_collection_names())
    counts = {}
    for name in names:
        try:
            counts[name] = db[name].estimated_document_count()
        except Exception:  # noqa: BLE001
            counts[name] = -1
    for name in names:
        if name.startswith("system."):
            continue
        print(f"  {name:38s} {counts[name]:>8}")

    tenants_col = settings.MONGO_TENANTS_COLLECTION
    apps_col = settings.MONGO_LARK_APPS_COLLECTION
    auth_col = settings.MONGO_AUTH_COLLECTION

    # ---------------------------------------------------------------- tenants
    _section(f"2. TENANTS ({tenants_col}) — CẤU HÌNH THEO DOANH NGHIỆP")
    tenants = list(db[tenants_col].find({}))
    if not tenants:
        print("  (trống) — chưa có tenant nào được lưu.")
    else:
        header = f"  {'TENANT_KEY':40s} {'STATUS':20s} " + " ".join(f"{f[:9]:>9s}" for f in REQUIRED_TENANT_FIELDS)
        print(header)
        print("  " + "-" * (len(header) - 2))
        for doc in tenants:
            row = f"  {str(doc.get('tenant_key') or '<none>'):40s} {str(doc.get('status') or '<none>'):20s} "
            row += " ".join(f"{_set(doc.get(f)):>9s}" for f in REQUIRED_TENANT_FIELDS)
            print(row)

    # ---------------------------------------------------------------- verdict per tenant
    _section("3. ĐÁNH GIÁ: TENANT NÀO ĐANG THIẾU CONFIG")
    env_values = {name: getattr(settings, name, "") for name in TENANT_SCOPED_ENV}

    ready_complete, ready_incomplete, not_ready = [], [], []
    for doc in tenants:
        tk = doc.get("tenant_key") or "<none>"
        missing = [f for f in REQUIRED_TENANT_FIELDS if _set(doc.get(f)) == "EMPTY"]
        status = str(doc.get("status") or "")
        if status == "ready":
            if missing:
                ready_incomplete.append((tk, missing))
            else:
                ready_complete.append(tk)
        else:
            not_ready.append((tk, status, missing))

    print(f"  ready + đủ config      : {len(ready_complete)}")
    for tk in ready_complete:
        print(f"      ✔ {_mask_tenant(tk)}")

    print(f"\n  ready + THIẾU config   : {len(ready_incomplete)}  ← resolver sẽ raise `TenantConfigIncomplete`")
    for tk, missing in ready_incomplete:
        print(f"      ✘ {_mask_tenant(tk)}: thiếu {', '.join(missing)}")

    print(f"\n  chưa ready             : {len(not_ready)}  ← sẽ lỗi nếu user nhắn bot")
    for tk, status, missing in not_ready:
        suffix = f" | thiếu {', '.join(missing)}" if missing else ""
        print(f"      … {_mask_tenant(tk)}: status={status or '<none>'}{suffix}")

    # ---------------------------------------------------------------- app credentials
    _section(f"4. LARK APP CREDENTIALS ({apps_col})")
    apps = list(db[apps_col].find({}))
    if not apps:
        print("  (trống) — resolver sẽ raise `AppCredentialMissing` cho mọi tenant.")
    else:
        for doc in apps:
            has_secret = _set(doc.get("encrypted_app_secret"))
            has_vt = _set(doc.get("encrypted_verification_token"))
            has_ek = _set(doc.get("encrypted_encrypt_key"))
            tk = doc.get("tenant_key")
            mark = "✔" if _set(tk) == "SET" else "✘ KHÔNG GẮN TENANT"
            print(
                f"  app_id={str(doc.get('app_id'))[:10]}…  status={str(doc.get('status')):10s} "
                f"tenant={_mask_tenant(tk)}  secret={has_secret} vt={has_vt} ek={has_ek}  {mark}"
            )
        unbound = [d for d in apps if _set(d.get("tenant_key")) == "EMPTY"]
        print(f"\n  Tổng app: {len(apps)} | Không gắn tenant_key: {len(unbound)}")

        # Cross-check: tenant 'ready' có app_id trong `tenants` nhưng KHÔNG có
        # credential tương ứng trong `lark_app_credentials` ⇒ runtime không thể lấy
        # app_secret và sẽ rơi sang App của tenant khác (rò rỉ credential).
        apps_by_tenant = {d.get("tenant_key"): d for d in apps if d.get("tenant_key")}
        apps_by_app_id = {d.get("app_id"): d for d in apps if d.get("app_id")}
        print("\n  Đối chiếu tenant 'ready' ↔ credential:")
        for doc in tenants:
            if str(doc.get("status")) != "ready":
                continue
            tk = doc.get("tenant_key")
            app_id = doc.get("app_id")
            by_tk = apps_by_tenant.get(tk)
            by_id = apps_by_app_id.get(app_id)
            if by_tk:
                print(f"      ✔ tenant={tk} → credential khớp tenant_key")
            elif by_id:
                print(
                    f"      ✘ tenant={tk} → có app_id={str(app_id)[:10]}… nhưng credential "
                    f"KHÔNG gắn tenant_key (đang thuộc tenant khác)"
                )
            else:
                print(f"      ✘ tenant={tk} → app_id={str(app_id)[:10]}… KHÔNG có credential trong DB")

    # `apps` có thể rỗng ⇒ vẫn cần bản map này cho phần kiểm tra state machine bên dưới
    apps_by_tenant_all = {d.get("tenant_key"): d for d in apps if d.get("tenant_key")}

    # ---------------------------------------------------------------- user tokens
    _section(f"5. USER TOKENS ({auth_col})")
    tokens = list(db[auth_col].find({}, {"_id": 1, "app_id": 1, "tenant_key": 1, "open_id": 1, "refresh_token": 1}))
    if not tokens:
        print("  (trống) — chưa có user token nào.")
    else:
        legacy = 0
        for doc in tokens:
            is_legacy = doc.get("_id") == "primary_user_token"
            if is_legacy:
                legacy += 1
            print(
                f"  _id={str(doc.get('_id'))[:28]:30s} app={str(doc.get('app_id') or '-'):10s} "
                f"tenant={_mask_tenant(doc.get('tenant_key'))} refresh={_set(doc.get('refresh_token'))}"
                f"{'   ← LEGACY GLOBAL' if is_legacy else ''}"
            )
        print(f"\n  Tổng token: {len(tokens)} | Token legacy toàn cục: {legacy}")

    # ---------------------------------------------------------------- system config
    _section(f"6. SYSTEM CONFIG ({settings.MONGO_SYSTEM_CONFIG_COLLECTION})")
    try:
        sys_docs = list(db[settings.MONGO_SYSTEM_CONFIG_COLLECTION].find({}))
        if not sys_docs:
            print("  (trống)")
        for doc in sys_docs:
            print(f"  config_key={doc.get('config_key')} tenant={_mask_tenant(doc.get('tenant_key'))} "
                  f"app_token={_set(doc.get('app_token'))}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] {exc}")

    # ---------------------------------------------------------------- env
    _section("7. BIẾN .env THUỘC PHẠM VI TENANT (presence only)")
    for name in TENANT_SCOPED_ENV:
        state = _set(env_values[name])
        note = "  ← SẼ ĐƯỢC DÙNG LÀM FALLBACK" if state == "SET" else ""
        print(f"  {name:28s} {state}{note}")

    # ---------------------------------------------------------------- data scoping
    _section("8. MỨC ĐỘ GẮN tenant_key TRONG DỮ LIỆU NGHIỆP VỤ")
    for coll_name in [
        settings.MONGO_CHAT_SCOPE_COLLECTION,
        settings.MONGO_MEMORY_COLLECTION,
        settings.MONGO_CLAIMS_COLLECTION,
        settings.MONGO_DIGEST_COLLECTION,
        settings.MONGO_MASTER_DIGEST_COLLECTION,
    ]:
        if coll_name not in names:
            print(f"  {coll_name:32s} (chưa tồn tại)")
            continue
        total = counts.get(coll_name, 0)
        scoped = db[coll_name].count_documents({"tenant_key": {"$nin": [None, ""]}})
        unscoped = total - scoped
        flag = "  ← CẦN BACKFILL" if unscoped > 0 else ""
        print(f"  {coll_name:32s} total={total:<6} có_tenant={scoped:<6} không_tenant={unscoped}{flag}")

    # ---------------------------------------------------------------- state machine & app_id
    _section("9. HỢP ĐỒNG STATE MACHINE ↔ RESOLVER (kiểm tra sau GĐ2/GĐ5)")
    status_violations, serving_violations, app_id_mismatches = [], [], []
    for doc in tenants:
        tk = doc.get("tenant_key") or "<none>"
        status = str(doc.get("status") or "")
        if status not in KNOWN_STATUSES:
            status_violations.append((tk, status or "<empty>"))
        if status not in SERVING_STATUSES:
            continue
        # Cùng một hợp đồng mà `tenant_resolver.resolve()` áp dụng lúc runtime:
        # thiếu field bắt buộc ⇒ `TenantConfigIncomplete`, lệch app_id ⇒ từ chối phục vụ.
        missing = [f for f in REQUIRED_TENANT_FIELDS if _set(doc.get(f)) == "EMPTY"]
        if missing:
            serving_violations.append((tk, f"thiếu {', '.join(missing)}"))
        cred = apps_by_tenant_all.get(tk)
        if not cred or _set(cred.get("encrypted_app_secret")) == "EMPTY":
            serving_violations.append((tk, "không có credential App cho chính tenant này"))
            continue
        tenant_app_id = str(doc.get("app_id") or "").strip()
        cred_app_id = str(cred.get("app_id") or "").strip()
        if tenant_app_id != cred_app_id:
            app_id_mismatches.append((tk, tenant_app_id, cred_app_id))

    print(f"  Trạng thái không thuộc bảng ({len(KNOWN_STATUSES)} giá trị hợp lệ): {len(status_violations)}")
    for tk, status in status_violations:
        print(f"      ✘ {_mask_tenant(tk)}: status={status}")

    print(f"\n  Tenant đang được phục vụ nhưng VI PHẠM hợp đồng resolver: {len(serving_violations)}")
    for tk, reason in serving_violations:
        print(f"      ✘ {_mask_tenant(tk)}: {reason}")

    print(f"\n  `tenants.app_id` lệch với `lark_app_credentials.app_id`: {len(app_id_mismatches)}")
    for tk, t_app, c_app in app_id_mismatches:
        print(f"      ✘ {_mask_tenant(tk)}: tenants={str(t_app)[:12] or '<empty>'} vs credential={str(c_app)[:12]}")

    if not (status_violations or serving_violations or app_id_mismatches):
        print("  ✔ Mọi tenant đang phục vụ đều thoả hợp đồng resolver (fail-closed an toàn).")

    # ---------------------------------------------------------------- summary
    _section("10. KẾT LUẬN")
    if not tenants:
        print("  • Chưa có tenant nào trong DB ⇒ resolver raise `TenantNotFound` cho mọi request.")
        print("  • Không còn fallback .env: muốn chạy được phải setup tenant qua luồng One-click Setup.")
    else:
        if ready_incomplete:
            print(f"  • {len(ready_incomplete)} tenant 'ready' nhưng thiếu config ⇒ backfill qua setup, không đổ .env.")
        else:
            print("  • Không có tenant 'ready' nào thiếu config.")
        if not_ready:
            print(f"  • {len(not_ready)} tenant chưa ready ⇒ bị chặn bằng `TenantNotReady` (state machine GĐ5).")
        if env_values.get("LARK_APP_ID") and len(tenants) > 1:
            print("  • LARK_APP_ID vẫn được set trong khi có nhiều tenant ⇒ nguy cơ dùng nhầm App.")
        if settings.WEKNORA_PROVISION_DRY_RUN:
            print("  • CẢNH BÁO: WEKNORA_PROVISION_DRY_RUN=true ⇒ dataset id sinh ra là giả.")
    if status_violations:
        print("  • Có tenant mang trạng thái lạ ⇒ sửa qua `services.tenancy.tenant_state`, không viết `$set` trực tiếp.")
    if serving_violations or app_id_mismatches:
        print(
            f"  • {len(serving_violations)} tenant 'ready' vi phạm hợp đồng và "
            f"{len(app_id_mismatches)} tenant lệch app_id ⇒ runtime sẽ raise "
            "`TenantConfigIncomplete` (không còn fallback .env)."
        )

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
