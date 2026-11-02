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
from typing import Any, Dict, List, Optional, Set, Tuple

from core.config import settings
from database.scoped_query import get_current_tenant_key
from services.lark.bitable import lark_base_service
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
        # Lark có thể gọi handler từ webhook và WebSocket trên các event loop
        # khác nhau. asyncio.Lock global sẽ bị bind vào loop đầu tiên và gây
        # "bound to a different event loop" ở các lượt sync tiếp theo.
        self._sync_lock_guard = threading.Lock()
        self._sync_locks: Dict[int, asyncio.Lock] = {}
        self._last_synced_tokens: Set[str] = set()
        self._last_sync_time: Optional[str] = None

    def _get_sync_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        loop_id = id(loop)
        with self._sync_lock_guard:
            lock = self._sync_locks.get(loop_id)
            if lock is None:
                lock = asyncio.Lock()
                self._sync_locks[loop_id] = lock
            return lock

    async def fetch_policy_records_from_base(self, tenant_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Đọc toàn bộ các dòng từ bảng Chính Sách & Quy Định trên Lark Base.
        Hỗ trợ phân giải token động qua base_provision_service.
        """
        from services.lark.base_provision_service import base_provision_service
        app_token, table_id = await base_provision_service.get_policy_target(tenant_key=tenant_key)
        domain = lark_base_service.domain

        if not app_token or not table_id:
            logger.warning("[PolicySync] Thiếu LARK_BASE_APP_TOKEN hoặc LARK_BASE_POLICY_TABLE_ID.")
            return []

        url = f"{domain}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"

        def _do_request():
            return lark_base_service._request(
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
            logger.info(f"[PolicySync] Đã đọc thành công {len(items)} bản ghi từ bảng {table_id}.")
            return items
        except Exception as e:
            logger.error(f"[PolicySync] Lỗi khi đọc bản ghi từ Lark Base: {e}", exc_info=True)
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
            logger.info("[PolicySync] POLICY_SYNC_ENABLED = false. Bỏ qua đồng bộ.")
            return {"status": "disabled", "synced": False}

        eff_tenant = tenant_key or get_current_tenant_key()
        tenant_cfg = None
        if eff_tenant:
            try:
                from database.db import get_tenant_config
                tenant_cfg = await get_tenant_config(eff_tenant)
            except Exception:
                pass

        target_policy_kb = (tenant_cfg.get("weknora_policy_dataset_id") if tenant_cfg else None) or settings.WEKNORA_POLICY_DATASET_ID
        weknora_tenant_id = tenant_cfg.get("weknora_tenant_id") if tenant_cfg else None
        ds_id = settings.WEKNORA_POLICY_DATASOURCE_ID

        if not ds_id and not target_policy_kb:
            logger.warning("[PolicySync] Chưa cấu hình WEKNORA_POLICY_DATASOURCE_ID hoặc weknora_policy_dataset_id. Bỏ qua.")
            return {"status": "missing_datasource_id", "synced": False}

        # Tránh xung đột các lần sync đồng thời
        async with self._get_sync_lock():
            logger.info(f"🔄 [PolicySync] Bắt đầu kiểm tra đồng bộ chính sách (KB: {target_policy_kb}, Tenant: {eff_tenant})...")

            # 1. Đọc Base
            records = await self.fetch_policy_records_from_base(tenant_key=eff_tenant)
            if not records:
                logger.warning("[PolicySync] Bảng chính sách trống hoặc không thể kết nối Base.")

            # 2. Bóc tách & Khử trùng lặp
            new_tokens, attachments = self.parse_policy_tokens_and_attachments(records)
            if records and not new_tokens and not attachments:
                shapes = {
                    str(key): _describe_field_shape(value)
                    for record in records[:3]
                    for key, value in (record.get("fields") or {}).items()
                }
                logger.warning("[PolicySync] Không tìm thấy link/file trong fields; shapes=%s", shapes)
            logger.info(f"[PolicySync] Trích xuất được {len(new_tokens)} tokens và {len(attachments)} files đính kèm: {new_tokens}")

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
                        logger.info(f"⚡ [PolicySync] Phát hiện thay đổi tokens: {current_set} -> {new_set}. Đang cập nhật WeKnora...")
                        await active_weknora.update_datasource_resources(ds_id, new_tokens)
                        await active_weknora.trigger_datasource_sync(ds_id)
                    elif force:
                        await active_weknora.trigger_datasource_sync(ds_id)
                except Exception as ds_err:
                    logger.warning(f"[PolicySync] Đồng bộ qua Datasource {ds_id} gặp lỗi (sẽ tiếp tục nạp file trực tiếp): {ds_err}")

            # 4. Tải nạp trực tiếp tài liệu vào WeKnora Policy Dataset
            uploaded_files = []
            if target_policy_kb:
                # 4.1 Tải tệp đính kèm
                for att in attachments:
                    try:
                        file_token = att["file_token"]
                        fname = att["name"]
                        file_bytes = await asyncio.to_thread(
                            lark_base_service.download_attachment,
                            file_token,
                            use_tenant_token=True,
                        )
                        if file_bytes:
                            up_res = await active_weknora.upload_file(
                                file_name=fname,
                                file_bytes=file_bytes,
                                dataset_id=target_policy_kb,
                                mime_type="application/pdf",
                                tenant_id=weknora_tenant_id,
                            )
                            if up_res.get("success"):
                                uploaded_files.append(fname)
                                logger.info(f"✔ [PolicySync] Đã nạp chính sách '{fname}' vào KB {target_policy_kb}")
                    except Exception as e:
                        logger.error(f"[PolicySync] Lỗi khi upload tệp chính sách '{att.get('name')}': {e}")

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
                            logger.info(
                                "[PolicySync] Lark runtime bound tenant=%s app=%s",
                                eff_tenant,
                                app_record.get("app_id"),
                            )

                    for tok in new_tokens:
                        try:
                            doc_res = await doc_parser_service.parse_lark_docx(tok)
                            if not doc_res or not doc_res.success:
                                doc_res = await doc_parser_service.parse_lark_wiki(tok)
                            if doc_res and doc_res.success and doc_res.markdown_content:
                                doc_bytes = doc_res.markdown_content.encode("utf-8")
                                safe_name = f"{doc_res.doc_name or f'Policy_{tok}'}.md"
                                up_res = await active_weknora.upload_file(
                                    file_name=safe_name,
                                    file_bytes=doc_bytes,
                                    dataset_id=target_policy_kb,
                                    mime_type="text/markdown",
                                    tenant_id=weknora_tenant_id,
                                )
                                if up_res.get("success"):
                                    uploaded_files.append(safe_name)
                                    logger.info(f"✔ [PolicySync] Đã nạp Lark Doc '{safe_name}' vào KB {target_policy_kb}")
                        except Exception as tok_err:
                            logger.warning(f"[PolicySync] Lỗi khi nạp token '{tok}': {tok_err}")
                finally:
                    if runtime_context_token is not None:
                        from services.lark.runtime import reset_current_lark_service
                        reset_current_lark_service(runtime_context_token)

            return {
                "status": "success",
                "synced": True,
                "dataset_id": target_policy_kb,
                "uploaded_files": uploaded_files,
                "resource_ids": new_tokens,
            }

            self._last_synced_tokens = new_set

            # 7. Xử lý tải các tệp đính kèm trực tiếp (nếu có)
            uploaded_files = []
            if attachments and settings.WEKNORA_POLICY_DATASET_ID:
                for att in attachments:
                    try:
                        file_token = att["file_token"]
                        fname = att["name"]
                        file_bytes = await asyncio.to_thread(
                            lark_base_service.download_attachment, file_token, True
                        )
                        if file_bytes:
                            up_res = await active_weknora.upload_file(
                                file_bytes=file_bytes,
                                filename=fname,
                                dataset_id=settings.WEKNORA_POLICY_DATASET_ID,
                            )
                            uploaded_files.append({"filename": fname, "res": up_res})
                    except Exception as e:
                        logger.warning(f"[PolicySync] Lỗi khi upload attachment {att.get('name')}: {e}")

            return {
                "status": "success",
                "synced": True,
                "previous_count": len(current_set),
                "new_count": len(new_set),
                "resource_ids": new_tokens,
                "sync_trigger_result": sync_res,
                "uploaded_attachments_count": len(uploaded_files),
            }

    async def start_loop(self) -> None:
        """Alias khởi động worker vòng lặp đồng bộ định kỳ."""
        await start_policy_sync_loop()


policy_sync_service = PolicySyncService()


async def start_policy_sync_loop() -> None:
    """
    Background worker chạy định kỳ mỗi POLICY_SYNC_INTERVAL_SECONDS
    để tự động đồng bộ chính sách từ Lark Base sang WeKnora.
    """
    if not settings.POLICY_SYNC_ENABLED:
        logger.info("[PolicySync Loop] POLICY_SYNC_ENABLED = false. Không khởi động loop.")
        return

    interval = max(60, settings.POLICY_SYNC_INTERVAL_SECONDS)
    logger.info(f"⏰ [PolicySync Loop] Khởi động worker đồng bộ định kỳ (Chu kỳ {interval}s).")

    # Lần đầu: Chờ 5 giây sau khi server khởi động để hệ thống ổn định
    await asyncio.sleep(5)
    try:
        await policy_sync_service.sync_policies(force=True)
    except Exception as e:
        logger.error(f"[PolicySync Loop] Lỗi đồng bộ ban đầu: {e}", exc_info=True)

    # Vòng lặp định kỳ
    while True:
        try:
            await asyncio.sleep(interval)
            await policy_sync_service.sync_policies(force=True)
        except asyncio.CancelledError:
            logger.info("[PolicySync Loop] Đã nhận tín hiệu dừng worker.")
            break
        except Exception as e:
            logger.error(f"[PolicySync Loop] Lỗi trong vòng lặp đồng bộ: {e}", exc_info=True)
            await asyncio.sleep(60)

