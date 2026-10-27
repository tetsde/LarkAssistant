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
import logging
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

from core.config import settings
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
        self._sync_lock = asyncio.Lock()
        self._last_synced_tokens: Set[str] = set()
        self._last_sync_time: Optional[str] = None

    async def fetch_policy_records_from_base(self) -> List[Dict[str, Any]]:
        """
        Đọc toàn bộ các dòng từ bảng Chính Sách & Quy Định trên Lark Base.
        """
        table_id = settings.LARK_BASE_POLICY_TABLE_ID
        app_token = lark_base_service.app_token
        domain = lark_base_service.domain

        if not app_token or not table_id:
            logger.warning("[PolicySync] Thiếu LARK_BASE_APP_TOKEN hoặc LARK_BASE_POLICY_TABLE_ID.")
            return []

        url = f"{domain}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"

        def _do_request():
            return lark_base_service._request(
                "GET",
                url,
                params={"page_size": 100},
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
          - Lọc các bản ghi đang hiệu lực (bỏ qua 'Hết hiệu lực', 'Hết hạn').
          - Bóc tách token từ cột 'Liên kết Docs' (flda6eq0MW).
          - Chống trùng lặp bằng set().
          - Trích xuất danh sách file đính kèm từ cột 'Tệp (Nếu có)' (fldiIc2WlU).
        """
        valid_tokens: Set[str] = set()
        attachments: List[Dict[str, Any]] = []

        for record in records:
            fields = record.get("fields") or {}

            # Kiểm tra trạng thái nếu có
            status_val = fields.get("Trạng thái") or fields.get("fldqHyvDt6")
            if status_val:
                status_str = str(status_val).lower()
                if any(bad in status_str for bad in ["hết hiệu lực", "hết hạn", "deprecated", "bãi bỏ"]):
                    continue

            # 1. Trích xuất link docs / folder
            link_val = fields.get("Liên kết Docs") or fields.get("flda6eq0MW")
            if link_val:
                token = extract_lark_token(link_val)
                if token:
                    valid_tokens.add(token)

            # 2. Trích xuất file đính kèm (nếu có)
            file_val = fields.get("Tệp (Nếu có)") or fields.get("fldiIc2WlU")
            if file_val and isinstance(file_val, list):
                for att in file_val:
                    if isinstance(att, dict) and att.get("file_token"):
                        attachments.append({
                            "name": att.get("name", "policy_doc.pdf"),
                            "file_token": att.get("file_token"),
                            "size": att.get("size", 0),
                        })

        return sorted(list(valid_tokens)), attachments

    async def sync_policies(self, force: bool = False) -> Dict[str, Any]:
        """
        Thực hiện chu trình đồng bộ hoàn chỉnh:
          1. Đọc Base -> bóc tách tokens & attachments.
          2. Khử trùng lặp.
          3. So sánh Diff với WeKnora Data Source.
          4. Nếu có thay đổi (hoặc force=True): Update WeKnora Data Source & Trigger Sync.
        """
        if not settings.POLICY_SYNC_ENABLED and not force:
            logger.info("[PolicySync] POLICY_SYNC_ENABLED = false. Bỏ qua đồng bộ.")
            return {"status": "disabled", "synced": False}

        ds_id = settings.WEKNORA_POLICY_DATASOURCE_ID
        if not ds_id:
            logger.warning("[PolicySync] Chưa cấu hình WEKNORA_POLICY_DATASOURCE_ID. Bỏ qua.")
            return {"status": "missing_datasource_id", "synced": False}

        # Tránh xung đột các lần sync đồng thời
        async with self._sync_lock:
            logger.info(f"🔄 [PolicySync] Bắt đầu kiểm tra đồng bộ chính sách (Datasource: {ds_id})...")

            # 1. Đọc Base
            records = await self.fetch_policy_records_from_base()
            if not records:
                logger.warning("[PolicySync] Bảng chính sách trống hoặc không thể kết nối Base.")

            # 2. Bóc tách & Khử trùng lặp
            new_tokens, attachments = self.parse_policy_tokens_and_attachments(records)
            logger.info(f"[PolicySync] Trích xuất được {len(new_tokens)} folder/doc tokens duy nhất: {new_tokens}")

            active_weknora = _get_active_weknora()

            # 3. Lấy cấu hình WeKnora hiện tại để so sánh Diff
            current_ds_info = await active_weknora.get_datasource_info(ds_id)
            current_tokens = []
            if current_ds_info and isinstance(current_ds_info, dict):
                current_tokens = (current_ds_info.get("config") or {}).get("resource_ids") or []

            current_set = set(current_tokens)
            new_set = set(new_tokens)

            # 4. Kiểm tra Diff
            has_diff = (current_set != new_set)

            if not has_diff and not force:
                logger.info(
                    f"✅ [PolicySync] Không có thay đổi về danh sách tài liệu ({len(new_set)} tokens). Bỏ qua re-sync WeKnora."
                )
                return {
                    "status": "no_change",
                    "resource_ids": list(new_set),
                    "synced": False,
                    "message": "Danh sách tài liệu không thay đổi. Không cần kích hoạt sync.",
                }

            # 5. Cập nhật Data Source trên WeKnora nếu có thay đổi cấu hình resource_ids
            if has_diff:
                logger.info(f"⚡ [PolicySync] Phát hiện thay đổi tokens: {current_set} -> {new_set}. Đang cập nhật WeKnora...")
                update_ok = await active_weknora.update_datasource_resources(ds_id, new_tokens)
                if not update_ok:
                    logger.error("[PolicySync] Cập nhật resource_ids vào WeKnora Data Source thất bại.")
                    return {
                        "status": "update_failed",
                        "resource_ids": new_tokens,
                        "synced": False,
                        "error": "Failed to update WeKnora datasource resources",
                    }
            else:
                logger.info(f"🔄 [PolicySync] Danh sách tokens không đổi ({len(new_set)} tokens). Kích hoạt re-sync WeKnora...")

            # 6. Kích hoạt đồng bộ trên WeKnora
            logger.info(f"🚀 [PolicySync] Đang kích hoạt đồng bộ WeKnora Data Source {ds_id}...")
            sync_res = await active_weknora.trigger_datasource_sync(ds_id)

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

