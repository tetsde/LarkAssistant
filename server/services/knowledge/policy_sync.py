"""
Module đồng bộ Chính sách & Quy định công ty từ Lark Base sang WeKnora.
Vị trí: server/services/policy_sync_service.py

Chức năng:
  1. Trích xuất Lark Token (folder, docx, wiki, file) từ URL hoặc text.
  2. Đọc bảng 'Chính Sách & Quy Định Toàn Công Ty' (tblZphzEZPLQAy24) từ Lark Base.
  3. Lọc trạng thái hiệu lực và khử trùng lặp token bằng set().
  4. So sánh Diff với cấu hình hiện tại của WeKnora Data Source.
  5. Chỉ cập nhật và kích hoạt WeKnora sync khi có thay đổi thực sự (Zero unnecessary API calls).
  6. Xử lý tệp đính kèm trực tiếp (nếu có) nạp vào Policy Knowledge Base.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from core.config import settings
from database.scoped_query import get_current_tenant_key
from models.memory import VIETNAM_TZ, get_vietnam_now_iso
from services.knowledge.weknora_client import weknora_service

logger = logging.getLogger("hilark.policy_sync")


def _get_active_weknora():
    shim = sys.modules.get("services.knowledge_service") or sys.modules.get("services.policy_sync_service")
    if shim and hasattr(shim, "weknora_service"):
        return shim.weknora_service
    return weknora_service


# =============================================================================
# TOKEN EXTRACTION & NORMALIZATION
# =============================================================================

def extract_lark_token(url_or_token: Any) -> Optional[str]:
    """
    Trích xuất token định danh (folder_token, doc_token, wiki_token, file_token)
    từ chuỗi URL Lark/Feishu hoặc dict trường Link của Lark Base.

    Ví dụ:
      - 'https://company.larksuite.com/drive/folder/Vxojf3r33lzu0tdlHX9jd0pUpFd?from=...'
        -> 'Vxojf3r33lzu0tdlHX9jd0pUpFd'
      - 'https://company.larksuite.com/docx/doxcnabcdef123456'
        -> 'doxcnabcdef123456'
      - {'link': 'https://...', 'text': 'https://...'}
        -> 'Vxojf3r33lzu0tdlHX9jd0pUpFd'
      - 'Vxojf3r33lzu0tdlHX9jd0pUpFd'
        -> 'Vxojf3r33lzu0tdlHX9jd0pUpFd'
    """
    if not url_or_token:
        return None

    # Hỗ trợ trường hợp Lark Base trả về Dict {link, text}
    if isinstance(url_or_token, dict):
        raw = url_or_token.get("link") or url_or_token.get("text") or ""
    elif isinstance(url_or_token, str):
        raw = url_or_token.strip()
    else:
        return None

    if not raw:
        return None

    # 1. Regex trích xuất token từ URL path
    # Hỗ trợ /drive/folder/, /docx/, /docs/, /wiki/, /file/, /folder/
    match = re.search(r"/(?:drive/folder|docx|docs|wiki|file|folder)/([a-zA-Z0-9_-]+)", raw)
    if match:
        return match.group(1)

    # 2. Nếu đã là chuỗi token thô (thường dài 15 - 50 ký tự chữ, số, gạch dưới)
    if re.match(r"^[a-zA-Z0-9_-]{15,50}$", raw):
        return raw

    return None


def _extract_tokens_from_value(value: Any) -> Set[str]:
    """Extract Lark document tokens from all Base field representations.

    The records endpoint may return a mention/link column as a dict, a list of
    dicts, or a JSON-encoded string.  Webhook payloads and records responses do
    not always use the same representation, so parsing must be semantic rather
    than tied to one shape.
    """
    if value is None or value == "":
        return set()

    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith(("[", "{")):
            try:
                return _extract_tokens_from_value(json.loads(raw))
            except (TypeError, ValueError):
                pass
        token = extract_lark_token(raw)
        return {token} if token else set()

    if isinstance(value, dict):
        found: Set[str] = set()
        for key in ("link", "url", "text", "token", "file_token"):
            candidate = value.get(key)
            if key == "file_token":
                # Attachment tokens are handled separately; do not treat them
                # as document/wiki resource IDs here.
                continue
            found.update(_extract_tokens_from_value(candidate))
        return found

    if isinstance(value, list):
        found: Set[str] = set()
        for item in value:
            found.update(_extract_tokens_from_value(item))
        return found

    return set()


def _describe_field_shape(value: Any) -> str:
    """Return a secret-safe description used when extraction unexpectedly fails."""
    if isinstance(value, dict):
        return f"dict(keys={sorted(str(k) for k in value.keys())})"
    if isinstance(value, list):
        item_keys = sorted({str(k) for item in value if isinstance(item, dict) for k in item.keys()})
        return f"list(len={len(value)},item_keys={item_keys})"
    if isinstance(value, str):
        stripped = value.lstrip()
        is_json = stripped.startswith(("[", "{"))
        url_like = "/wiki/" in value or "/docx/" in value or "larksuite.com" in value
        return f"str(len={len(value)},json={is_json},url_like={url_like})"
    return type(value).__name__


# =============================================================================
# POLICY SYNC SERVICE CLASS
# =============================================================================

class PolicySyncService:
    """
    Service quản lý luồng đồng bộ chính sách tự động:
      - Đọc bảng Base
      - Bóc tách token
      - Chống trùng lặp đa tầng
      - Diff checking với WeKnora
      - Trigger sync an toàn với Lock
    """

    def __init__(self):
        # Lark webhook handler hoặc background sync workers có thể chạy trên các event loop
        # khác nhau. asyncio.Lock global sẽ bị bind vào loop đầu tiên và gây
        # "bound to a different event loop" ở các lượt sync tiếp theo.
        self._sync_lock_guard = threading.Lock()
        self._sync_locks: Dict[int, asyncio.Lock] = {}
        self._last_synced_tokens: Set[str] = set()
        self._last_sync_time: Optional[str] = None
        self._recent_logs: Dict[str, List[str]] = {}

    def get_recent_logs(self, tenant_key: Optional[str]) -> List[str]:
        """Lấy danh sách nhật ký đồng bộ gần nhất của tenant."""
        if not tenant_key:
            return []
        return list(self._recent_logs.get(str(tenant_key), []))

    def _append_log(self, tenant_key: Optional[str], message: str) -> None:
        """Thêm một dòng nhật ký có gắn nhãn thời gian Việt Nam vào bộ đệm của tenant."""
        if not tenant_key:
            return
        tk = str(tenant_key)
        if tk not in self._recent_logs:
            self._recent_logs[tk] = []
        now_vn = datetime.now(VIETNAM_TZ).strftime("%H:%M:%S")
        entry = f"[{now_vn}] {message}"
        self._recent_logs[tk].append(entry)
        if len(self._recent_logs[tk]) > 50:
            self._recent_logs[tk] = self._recent_logs[tk][-50:]

    def _get_sync_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        loop_id = id(loop)
        with self._sync_lock_guard:
            lock = self._sync_locks.get(loop_id)
            if lock is None:
                lock = asyncio.Lock()
                self._sync_locks[loop_id] = lock
            return lock

    async def _policy_base_service(self, tenant_key: Optional[str]):
        """
        Dựng `LarkBaseService` trỏ đúng bảng Chính Sách của tenant đang sync.

        Trước đây hàm này dùng singleton `lark_base_service` (app_token/table_id bị các
        luồng khác ghi đè), nên doanh nghiệp B có thể đọc bảng chính sách của A.
        """
        from services.lark.bitable import LarkBaseService
        from services.tenancy.tenant_resolver import tenant_resolver

        resources = await tenant_resolver.resolve(tenant_key)
        return LarkBaseService.for_policy_table(resources)

    async def fetch_policy_records_from_base(self, tenant_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Đọc toàn bộ các dòng từ bảng Chính Sách & Quy Định trên Lark Base của ĐÚNG tenant.
        """
        from services.lark.base_provision_service import base_provision_service

        app_token, table_id = await base_provision_service.get_policy_target(tenant_key=tenant_key)
        base_service = await self._policy_base_service(tenant_key)
        domain = base_service.domain

        if not app_token or not table_id:
            logger.warning(
                "[POLICY_SYNC] skip_base_read tenant=%s reason=missing_policy_table_config",
                tenant_key,
            )
            return []

        url = f"{domain}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"

        def _do_request():
            return base_service._request(
                "GET",
                url,
                params={
                    "page_size": 100,
                    "user_id_type": "open_id",
                    # Preserve rich text/mention structures so Wiki links are
                    # available to the policy parser, not only their display text.
                    "text_field_as_array": "true",
                },
                use_tenant_token=True,
                action_name="Đọc danh mục chính sách từ Base",
            )

        try:
            data = await asyncio.to_thread(_do_request)
            items = data.get("items", []) or []
            logger.info("[POLICY_SYNC] base_records_fetched tenant=%s table=%s count=%d", tenant_key or "-", table_id, len(items))
            return items
        except Exception as e:
            logger.error("[POLICY_SYNC] base_records_failed tenant=%s table=%s error=%s", tenant_key or "-", table_id, e, exc_info=True)
            return []

    def parse_policy_tokens_and_attachments(
        self, records: List[Dict[str, Any]]
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """
        Phân tích các bản ghi Base:
          - Lọc các bản ghi đang hiệu lực (bỏ qua 'Hết hiệu lực', 'Hết hạn', 'superseded').
          - Bóc tách token từ cột 'Văn bản đính kèm / Link', 'Liên kết Docs' (flda6eq0MW).
          - Chống trùng lặp bằng set().
          - Trích xuất danh sách file đính kèm.
        """
        valid_tokens: Set[str] = set()
        attachments: List[Dict[str, Any]] = []

        for record in records:
            fields = record.get("fields") or {}

            # Kiểm tra trạng thái nếu có
            status_val = (
                fields.get("Trạng thái áp dụng")
                or fields.get("Trạng thái")
                or fields.get("fldqHyvDt6")
                or fields.get("fldY4FeEoj")
            )
            if status_val:
                status_str = str(status_val).lower()
                if any(bad in status_str for bad in ["hết hiệu lực", "hết hạn", "deprecated", "bãi bỏ", "superseded"]):
                    continue

            # 1. Trích xuất link docs / folder
            raw_doc_val = (
                fields.get("Văn bản đính kèm / Link")
                or fields.get("Liên kết Docs")
                or fields.get("Tài liệu")
                or fields.get("flda6eq0MW")
                or fields.get("fldxLmYV3v")
            )
            tokens_before_record = len(valid_tokens)
            if raw_doc_val:
                valid_tokens.update(_extract_tokens_from_value(raw_doc_val))

                # Keep direct file attachments supported, including when the
                # attachment column is returned as a JSON string.
                attachment_values: Any = raw_doc_val
                if isinstance(attachment_values, str):
                    try:
                        attachment_values = json.loads(attachment_values)
                    except (TypeError, ValueError):
                        attachment_values = []
                values = attachment_values if isinstance(attachment_values, list) else [attachment_values]
                for item in values:
                    if isinstance(item, dict) and item.get("file_token"):
                        attachments.append({
                            "name": item.get("name") or item.get("text", "policy_doc.pdf"),
                            "file_token": item["file_token"],
                            "size": item.get("size", 0),
                        })

            # Fallback for records responses whose field IDs differ from the
            # webhook schema. Scan values, but only URL/link-like values can
            # produce tokens, so titles/options are not accidentally ingested.
            if len(valid_tokens) == tokens_before_record:
                for value in fields.values():
                    valid_tokens.update(_extract_tokens_from_value(value))

            # 2. Trích xuất file đính kèm từ cột Tệp (Nếu có)
            file_val = fields.get("Tệp (Nếu có)") or fields.get("fldiIc2WlU")
            if isinstance(file_val, str):
                try:
                    file_val = json.loads(file_val)
                except (TypeError, ValueError):
                    file_val = []
            if file_val and isinstance(file_val, list):
                for att in file_val:
                    if isinstance(att, dict) and att.get("file_token"):
                        attachments.append({
                            "name": att.get("name", "policy_doc.pdf"),
                            "file_token": att.get("file_token"),
                            "size": att.get("size", 0),
                        })

        return sorted(list(valid_tokens)), attachments

    async def sync_policies(self, force: bool = False, tenant_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Thực hiện chu trình đồng bộ hoàn chỉnh:
          1. Đọc Base -> bóc tách tokens & attachments.
          2. Khử trùng lặp.
          3. Nếu có tenant_key & weknora_policy_dataset_id: Tải nạp trực tiếp vào Policy KB của Tenant.
          4. Nếu có WEKNORA_POLICY_DATASOURCE_ID: Đồng bộ qua WeKnora Data Source.
        """
        if not settings.POLICY_SYNC_ENABLED and not force:
            logger.info("[POLICY_SYNC] skipped reason=disabled env=POLICY_SYNC_ENABLED")
            return {"status": "disabled", "synced": False}

        eff_tenant = tenant_key or get_current_tenant_key()
        if not eff_tenant:
            # Không có tenant thì không có Policy KB nào để sync. Trước đây hàm này
            # viết thẳng vào `settings.WEKNORA_POLICY_DATASET_ID` - kho của một doanh
            # nghiệp cụ thể - nên loop định kỳ có thể ghi chính sách công ty B vào
            # kho của công ty A.
            logger.warning("[POLICY_SYNC] skipped reason=missing_tenant_key")
            return {"status": "missing_tenant", "synced": False}

        tenant_cfg = None
        try:
            from database.db import get_tenant_config
            tenant_cfg = await get_tenant_config(eff_tenant)
        except Exception as cfg_err:
            logger.warning("[POLICY_SYNC] tenant_config_failed tenant=%s error=%s", eff_tenant, cfg_err)

        target_policy_kb = (tenant_cfg.get("weknora_policy_dataset_id") if tenant_cfg else None) or None
        weknora_tenant_id = tenant_cfg.get("weknora_tenant_id") if tenant_cfg else None
        # Data Source là tài nguyên RIÊNG của từng doanh nghiệp trong WeKnora. Trước đây dòng này
        # đọc `settings.WEKNORA_POLICY_DATASOURCE_ID` (một UUID hardcode của doanh nghiệp đầu tiên),
        # nên `update_datasource_resources()` + `trigger_datasource_sync()` của tenant B lại nạp tài
        # liệu vào data source của tenant A. Thiếu cấu hình => bỏ qua nhánh data source, chỉ nạp file.
        ds_id = (tenant_cfg.get("weknora_policy_datasource_id") if tenant_cfg else None) or ""

        if not ds_id and not target_policy_kb:
            logger.warning("[POLICY_SYNC] skipped tenant=%s reason=missing_datasource_and_dataset", eff_tenant)
            return {"status": "missing_datasource_id", "synced": False}

        # Tránh xung đột các lần sync đồng thời
        async with self._get_sync_lock():
            run_logs: List[str] = []

            def _log(msg: str):
                self._append_log(eff_tenant, msg)
                now_vn = datetime.now(VIETNAM_TZ).strftime("%H:%M:%S")
                run_logs.append(f"[{now_vn}] {msg}")

            _log(f"🔄 Bắt đầu kiểm tra đồng bộ chính sách (KB: {target_policy_kb}, Tenant: {eff_tenant})...")

            # 1. Đọc Base
            records = await self.fetch_policy_records_from_base(tenant_key=eff_tenant)
            if not records:
                logger.warning("[POLICY_SYNC] empty_base tenant=%s", eff_tenant)
                _log("⚠️ Bảng chính sách trên Lark Base hiện chưa có bản ghi nào hoặc bảng trống.")
            else:
                _log(f"📄 Đã đọc thành công {len(records)} bản ghi từ bảng Chính sách trên Lark Base.")

            # 2. Bóc tách & Khử trùng lặp
            new_tokens, attachments = self.parse_policy_tokens_and_attachments(records)
            if records and not new_tokens and not attachments:
                shapes = {
                    str(key): _describe_field_shape(value)
                    for record in records[:3]
                    for key, value in (record.get("fields") or {}).items()
                }
                logger.warning("[POLICY_SYNC] no_resources_found tenant=%s shapes=%s", eff_tenant, shapes)
                _log("⚠️ Không tìm thấy liên kết Docs hoặc tệp đính kèm trong các bản ghi.")
            else:
                _log(f"🔍 Trích xuất được {len(new_tokens)} liên kết Docs và {len(attachments)} tệp đính kèm.")
            logger.info("[POLICY_SYNC] parsed tenant=%s tokens=%d attachments=%d", eff_tenant, len(new_tokens), len(attachments))

            active_weknora = _get_active_weknora()

            # 3. Đồng bộ qua Data Source nếu có ds_id
            if ds_id:
                try:
                    current_ds_info = await active_weknora.get_datasource_info(ds_id)
                    current_tokens = []
                    if current_ds_info and isinstance(current_ds_info, dict):
                        current_tokens = (current_ds_info.get("config") or {}).get("resource_ids") or []

                    current_set = set(current_tokens)
                    new_set = set(new_tokens)
                    has_diff = (current_set != new_set)

                    if has_diff:
                        logger.info(
                            "[POLICY_SYNC] datasource_diff tenant=%s ds_id=%s old=%d new=%d",
                            eff_tenant,
                            ds_id,
                            len(current_set),
                            len(new_set),
                        )
                        _log(f"⚡ Phát hiện thay đổi tokens: Đang cập nhật Data Source WeKnora {ds_id}...")
                        await active_weknora.update_datasource_resources(ds_id, new_tokens)
                        await active_weknora.trigger_datasource_sync(ds_id)
                    elif force:
                        _log(f"⚡ Kích hoạt WeKnora Data Source sync (force=True)...")
                        await active_weknora.trigger_datasource_sync(ds_id)
                except Exception as ds_err:
                    logger.warning("[POLICY_SYNC] datasource_sync_failed tenant=%s ds_id=%s error=%s", eff_tenant, ds_id, ds_err)
                    _log(f"⚠️ Đồng bộ qua Datasource {ds_id} gặp lỗi (tiếp tục nạp trực tiếp): {ds_err}")

            # 4. Tải nạp trực tiếp tài liệu vào WeKnora Policy Dataset của tenant (Cơ chế REBUILD tránh trùng lặp)
            uploaded_files = []
            if target_policy_kb:
                import hashlib
                import mimetypes

                base_service = await self._policy_base_service(eff_tenant)

                # Lấy danh sách tài liệu hiện có trong Policy KB để kiểm tra & rebuild (tránh tạo tài liệu trùng lặp)
                existing_knowledges = await active_weknora.list_knowledges(
                    dataset_id=target_policy_kb,
                    page=1,
                    page_size=500,
                    tenant_id=weknora_tenant_id,
                )
                existing_doc_map: Dict[str, Dict[str, Any]] = {}
                for k_item in existing_knowledges:
                    k_id = k_item.get("id")
                    if not k_id:
                        continue
                    fname = (k_item.get("file_name") or k_item.get("title") or "").strip().lower()
                    if fname:
                        existing_doc_map[fname] = k_item
                        base_fname = fname.rsplit(".", 1)[0]
                        if base_fname and base_fname not in existing_doc_map:
                            existing_doc_map[base_fname] = k_item

                async def _upload_or_rebuild(
                    file_name: str,
                    file_bytes: bytes,
                    mime_type: str,
                    item_type_label: str = "tài liệu",
                ) -> Optional[str]:
                    """
                    Upload tài liệu vào WeKnora với cơ chế REBUILD:
                    - Nếu tài liệu đã có trong WeKnora và nội dung không đổi (và không force): giữ nguyên.
                    - Nếu nội dung đã cập nhật trên Lark Docs hoặc force=True: xoá bản cũ trên WeKnora và nạp lại để rebuild lại toàn bộ chunks/indexes.
                    - Nếu tài liệu chưa có: upload mới.
                    """
                    clean_name = file_name.strip()
                    name_key = clean_name.lower()
                    base_key = name_key.rsplit(".", 1)[0] if "." in name_key else name_key
                    cur_hash = hashlib.md5(file_bytes).hexdigest()

                    existing_doc = existing_doc_map.get(name_key) or existing_doc_map.get(base_key)
                    if existing_doc:
                        old_id = existing_doc.get("id")
                        old_hash = (existing_doc.get("file_hash") or "").strip().lower()
                        # Nếu nội dung hoàn toàn không thay đổi và không force -> giữ nguyên
                        if old_hash and old_hash == cur_hash.lower() and not force:
                            logger.debug("[POLICY_SYNC] unchanged file=%s knowledge_id=%s", clean_name, old_id)
                            _log(f"ℹ️ '{clean_name}' giữ nguyên (nội dung không đổi).")
                            return clean_name

                        # Nếu nội dung thay đổi hoặc người dùng bấm nút đồng bộ (force=True) -> REBUILD LẠI
                        logger.info("[POLICY_SYNC] rebuild file=%s old_knowledge_id=%s", clean_name, old_id)
                        _log(f"🔄 Cập nhật '{clean_name}': Đang xoá bản cũ để rebuild lại chỉ mục...")
                        await active_weknora.delete_knowledge(old_id, tenant_id=weknora_tenant_id)
                        # Chờ worker của WeKnora hoàn tất dọn dẹp hàng đợi xóa trước khi nạp tệp mới (0.5s - 1.5s)
                        for _ in range(6):
                            await asyncio.sleep(0.5)
                            doc_check = await active_weknora.get_document_info(target_policy_kb, old_id, tenant_id=weknora_tenant_id)
                            if not doc_check:
                                break
                        existing_doc_map.pop(name_key, None)
                        existing_doc_map.pop(base_key, None)

                    up_res = await active_weknora.upload_file(
                        file_name=clean_name,
                        file_bytes=file_bytes,
                        dataset_id=target_policy_kb,
                        mime_type=mime_type,
                        tenant_id=weknora_tenant_id,
                    )
                    if up_res.get("success"):
                        k_id = up_res.get("knowledge_id", "")
                        logger.info(
                            "[POLICY_SYNC] uploaded type=%s file=%s dataset=%s knowledge_id=%s",
                            item_type_label,
                            clean_name,
                            target_policy_kb,
                            k_id,
                        )
                        _log(f"✔ Đã nạp & rebuild thành công {item_type_label} '{clean_name}'.")
                        new_item = {"id": k_id, "file_name": clean_name, "file_hash": cur_hash}
                        existing_doc_map[name_key] = new_item
                        existing_doc_map[base_key] = new_item
                        return clean_name
                    else:
                        err_msg = up_res.get("error", "Lỗi không xác định")
                        logger.error("[POLICY_SYNC] upload_failed file=%s error=%s", clean_name, err_msg)
                        _log(f"❌ Lỗi khi nạp '{clean_name}': {err_msg}")
                        return None

                # 4.1 Tải tệp đính kèm
                for att in attachments:
                    try:
                        file_token = att["file_token"]
                        fname = att["name"]
                        file_bytes = await asyncio.to_thread(
                            base_service.download_attachment,
                            file_token,
                            use_tenant_token=True,
                        )
                        if file_bytes:
                            guessed_mime, _ = mimetypes.guess_type(fname)
                            mime_type = guessed_mime or "application/pdf"
                            saved = await _upload_or_rebuild(fname, file_bytes, mime_type, "tệp đính kèm")
                            if saved:
                                uploaded_files.append(saved)
                    except Exception as e:
                        logger.error("[POLICY_SYNC] attachment_upload_failed file=%s error=%s", att.get("name"), e)
                        _log(f"❌ Lỗi khi tải tệp '{att.get('name')}': {e}")

                # 4.2 Tải Lark Doc tokens
                from services.knowledge.doc_parser import doc_parser_service
                runtime_context_token = None
                try:
                    # Bitable webhook/background tasks do not inherit the
                    # ingress ContextVar. Resolve the tenant's Custom App
                    # explicitly so document reads never use another app's
                    # User Token or bot credentials.
                    if eff_tenant:
                        from services.lark_app_service import lark_app_service
                        from services.lark.runtime import get_or_create_lark_service, set_current_lark_service

                        app_record = await lark_app_service.get_by_tenant_key(eff_tenant)
                        if app_record:
                            runtime_service = await get_or_create_lark_service(app_record)
                            runtime_context_token = set_current_lark_service(runtime_service)
                            logger.debug(
                                "[POLICY_SYNC] runtime_bound tenant=%s app_id=%s",
                                eff_tenant,
                                app_record.get("app_id"),
                            )

                    for tok in new_tokens:
                        try:
                            # 1. Thử phân giải dạng Lark DocX (với tenant_key cô lập)
                            doc_res = await doc_parser_service.parse_lark_docx(tok, tenant_key=eff_tenant)
                            
                            # 2. Nếu không phải DocX, thử phân giải dạng Lark Wiki
                            if not doc_res or not doc_res.success:
                                doc_res = await doc_parser_service.parse_lark_wiki(tok, tenant_key=eff_tenant)

                            # 3. Nếu là DocX hoặc Wiki hợp lệ
                            if doc_res and doc_res.success and doc_res.markdown_content:
                                doc_bytes = doc_res.markdown_content.encode("utf-8")
                                safe_name = f"{doc_res.doc_name or f'Policy_{tok}'}.md"
                                saved = await _upload_or_rebuild(safe_name, doc_bytes, "text/markdown", "văn bản Lark")
                                if saved:
                                    uploaded_files.append(saved)
                            
                            # 4. Nếu không phải DocX/Wiki, kiểm tra xem có phải Thư mục Lark Drive (Folder) không
                            elif not doc_res or not doc_res.success:
                                logger.debug("[POLICY_SYNC] probe_drive_folder tenant=%s token=%s", eff_tenant, tok)
                                folder_docs = await doc_parser_service.parse_lark_folder(tok, tenant_key=eff_tenant)
                                if folder_docs:
                                    success_folder_docs = [d for d in folder_docs if d and d.success and d.markdown_content]
                                    _log(f"📁 Phát hiện thư mục Lark Drive ({tok}): Tìm thấy {len(folder_docs)} tệp ({len(success_folder_docs)} tệp hợp lệ).")
                                    for fdoc in success_folder_docs:
                                        doc_bytes = fdoc.markdown_content.encode("utf-8")
                                        raw_name = fdoc.doc_name or f"Doc_{tok}"
                                        safe_name = raw_name if raw_name.endswith(".md") else f"{raw_name}.md"
                                        saved = await _upload_or_rebuild(safe_name, doc_bytes, "text/markdown", "tệp từ thư mục")
                                        if saved:
                                            uploaded_files.append(saved)
                        except Exception as tok_err:
                            logger.warning("[POLICY_SYNC] token_ingest_failed token=%s error=%s", tok, tok_err)
                            _log(f"❌ Lỗi khi nạp token '{tok}': {tok_err}")
                finally:
                    if runtime_context_token is not None:
                        from services.lark.runtime import reset_current_lark_service
                        reset_current_lark_service(runtime_context_token)

            now_iso = get_vietnam_now_iso()
            self._last_sync_time = now_iso
            summary_msg = f"✔ Hoàn tất đồng bộ: Đã xử lý {len(records)} dòng, nạp {len(uploaded_files)} tài liệu mới."
            _log(summary_msg)

            # Lưu lại trạng thái & nhật ký đồng bộ vào collection tenants để hiển thị trên UI
            try:
                from database.db import get_tenants_collection
                recent_logs_to_save = self.get_recent_logs(eff_tenant)[-20:]
                await get_tenants_collection().update_one(
                    {"tenant_key": eff_tenant},
                    {
                        "$set": {
                            "last_policy_sync": {
                                "synced_at": now_iso,
                                "status": "success",
                                "records_count": len(records),
                                "tokens_count": len(new_tokens),
                                "attachments_count": len(attachments),
                                "uploaded_files": uploaded_files,
                                "logs": recent_logs_to_save,
                            }
                        }
                    },
                )
            except Exception as up_err:
                logger.debug("[POLICY_SYNC] status_persist_failed tenant=%s error=%s", eff_tenant, up_err)

            return {
                "status": "success",
                "synced": True,
                "dataset_id": target_policy_kb,
                "uploaded_files": uploaded_files,
                "resource_ids": new_tokens,
                "logs": run_logs,
            }

    async def start_loop(self) -> None:
        """Alias khởi động worker vòng lặp đồng bộ định kỳ."""
        await start_policy_sync_loop()


policy_sync_service = PolicySyncService()


async def _ready_tenants() -> List[Dict[str, Any]]:
    """Danh sách tenant đang được phục vụ kèm cấu hình interval & lần sync cuối."""
    from database.db import get_tenants_collection

    docs: List[Dict[str, Any]] = []
    col = get_tenants_collection()
    async for doc in col.find(
        {"status": "ready"},
        {"tenant_key": 1, "policy_sync_interval_seconds": 1, "last_policy_sync": 1, "_id": 0}
    ):
        if doc.get("tenant_key"):
            docs.append(doc)
    return docs


async def _ready_tenant_keys() -> List[str]:
    """Tương thích ngược trả về danh sách tenant_key."""
    tenants = await _ready_tenants()
    return [str(t["tenant_key"]) for t in tenants if t.get("tenant_key")]


async def start_policy_sync_loop() -> None:
    """
    Background worker chạy định kỳ để tự động đồng bộ chính sách từ Lark Base
    sang WeKnora CHO TỪNG TENANT dựa trên chu kỳ `policy_sync_interval_seconds` riêng.

    Sử dụng vòng lặp tick 60 giây để kiểm tra và kích hoạt đúng lịch cho từng tenant
    mà không cần restart server khi người dùng đổi lịch trên giao diện UI.
    """
    if not settings.POLICY_SYNC_ENABLED:
        logger.info("[POLICY_SYNC] disabled env=POLICY_SYNC_ENABLED")
        return

    logger.info(
        "[POLICY_SYNC] started tick_s=60 default_interval_s=%d source=mongo_tenants",
        settings.POLICY_SYNC_INTERVAL_SECONDS,
    )

    # Lần đầu: Chờ 5 giây sau khi server khởi động để hệ thống ổn định
    await asyncio.sleep(5)
    await _sync_all_tenants_once(force=False)

    # Vòng lặp định kỳ (tick mỗi 60s)
    while True:
        try:
            await asyncio.sleep(60)
            await _sync_all_tenants_once(force=False)
        except asyncio.CancelledError:
            logger.info("[POLICY_SYNC] stopped")
            break
        except Exception as e:
            logger.error("[POLICY_SYNC] loop_error error=%s", e, exc_info=True)
            await asyncio.sleep(60)


async def _sync_all_tenants_once(force: bool = False) -> None:
    """Quét các tenant 'ready'; chỉ kích hoạt khi đã đến chu kỳ hoặc khi force=True."""
    try:
        tenants = await _ready_tenants()
    except Exception as list_err:
        logger.warning("[POLICY_SYNC] list_tenants_failed error=%s", list_err)
        return

    now = datetime.now(VIETNAM_TZ)
    for t_doc in tenants:
        tk = str(t_doc["tenant_key"])
        interval = int(t_doc.get("policy_sync_interval_seconds") or settings.POLICY_SYNC_INTERVAL_SECONDS or 3600)
        last_sync_raw = (t_doc.get("last_policy_sync") or {}).get("synced_at")

        should_sync = force or not last_sync_raw
        if not should_sync and last_sync_raw:
            try:
                last_dt = datetime.fromisoformat(str(last_sync_raw))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=VIETNAM_TZ)
                elapsed = (now - last_dt).total_seconds()
                if elapsed >= interval:
                    should_sync = True
            except Exception:
                should_sync = True

        if should_sync:
            try:
                logger.info("[POLICY_SYNC] scheduled_run tenant=%s interval_s=%d", tk, interval)
                # force=False: chỉ upload khi hash thay đổi thực sự.
                # force=True chỉ dùng khi user bấm "Đồng bộ ngay" trên UI hoặc có Bitable webhook event.
                await policy_sync_service.sync_policies(force=False, tenant_key=tk)
            except Exception as e:
                logger.warning("[POLICY_SYNC] scheduled_failed tenant=%s error=%s", tk, e)

    if not tenants:
        logger.debug("[POLICY_SYNC] tick ready_tenants=0")

