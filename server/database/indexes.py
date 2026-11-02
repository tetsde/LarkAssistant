"""
HiLark Database Indexes Specification & Manager
===============================================
Vị trí: server/database/indexes.py

Mục đích:
    Quản lý tập trung toàn bộ cấu hình Index cho 8 collections MongoDB của HiLark:
      1. claims                 - Mệnh đề, sự thật, quyết định
      2. memories               - Thực thể, bí danh
      3. conversation_staging   - Vùng đệm tin nhắn
      4. chat_scopes            - Phân quyền & mapping WeKnora KB
      5. daily_digests          - Bản tổng hợp nhóm
      6. master_daily_digests   - Bản tổng hợp cấp điều hành
      7. draft_logs             - Nhật ký bản nháp chờ duyệt
      8. lark_auth              - Trạng thái OAuth Token

    Loại bỏ hoàn toàn nguy cơ Full Collection Scan (COLLSCAN),
    đảm bảo truy vấn thời gian thực < 5ms kể cả khi dữ liệu tăng trưởng.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import OperationFailure

from core.config import settings

logger = logging.getLogger("hilark.database.indexes")


def get_index_specifications() -> Dict[str, List[IndexModel]]:
    """
    Trả về danh sách IndexModel được thiết kế chuyên biệt cho từng collection.
    """
    return {
        # 1. CLAIMS (Mệnh đề / Sự thật trích xuất)
        settings.MONGO_CLAIMS_COLLECTION: [
            IndexModel([("id", ASCENDING)], unique=True, name="idx_claims_id_unique"),
            IndexModel([("entity_id", ASCENDING)], name="idx_claims_entity_id"),
            IndexModel([("chat_id", ASCENDING), ("status", ASCENDING)], name="idx_claims_chat_status"),
            IndexModel([("tenant_key", ASCENDING), ("chat_id", ASCENDING), ("status", ASCENDING)], name="idx_claims_tenant_chat_status"),
            IndexModel([("tenant_key", ASCENDING), ("id", ASCENDING)], name="idx_claims_tenant_id"),
            IndexModel([("scope_type", ASCENDING)], name="idx_claims_scope_type"),
            IndexModel([("source_message_id", ASCENDING)], name="idx_claims_source_msg_id"),
            IndexModel([("source_doc", ASCENDING)], name="idx_claims_source_doc"),
            IndexModel([("created_at", DESCENDING)], name="idx_claims_created_at"),
        ],

        # 2. MEMORIES (Thực thể & Bí danh)
        settings.MONGO_MEMORY_COLLECTION: [
            IndexModel([("id", ASCENDING)], unique=True, name="idx_memories_id_unique"),
            IndexModel([("workspace_id", ASCENDING)], name="idx_memories_workspace_id"),
            IndexModel([("name", ASCENDING)], name="idx_memories_name"),
            IndexModel([("tenant_key", ASCENDING), ("name", ASCENDING)], name="idx_memories_tenant_name"),
            IndexModel([("tenant_key", ASCENDING), ("id", ASCENDING)], name="idx_memories_tenant_id"),
            IndexModel([("aliases", ASCENDING)], name="idx_memories_aliases"),
        ],

        # 3. CONVERSATION STAGING (Vùng đệm tin nhắn trong ngày)
        settings.MONGO_STAGING_COLLECTION: [
            IndexModel([("message_id", ASCENDING)], unique=True, sparse=True, name="idx_staging_msg_id_unique"),
            IndexModel([("chat_id", ASCENDING), ("created_at", DESCENDING)], name="idx_staging_chat_created"),
            IndexModel([("tenant_key", ASCENDING), ("chat_id", ASCENDING), ("created_at", DESCENDING)], name="idx_staging_tenant_chat_created"),
            IndexModel([("status", ASCENDING)], name="idx_staging_status"),
        ],

        # 4. CHAT SCOPES (Ánh xạ phân quyền & WeKnora Knowledge Base)
        settings.MONGO_CHAT_SCOPE_COLLECTION: [
            IndexModel([("chat_id", ASCENDING)], unique=True, name="idx_scopes_chat_id_unique"),
            IndexModel([("tenant_key", ASCENDING), ("chat_id", ASCENDING)], name="idx_scopes_tenant_chat"),
            IndexModel([("knowledge_base_id", ASCENDING)], name="idx_scopes_kb_id"),
            IndexModel([("base_record_id", ASCENDING)], name="idx_scopes_base_record_id"),
        ],

        # 5. DAILY DIGESTS (Bản tổng hợp ngày theo nhóm)
        settings.MONGO_DIGEST_COLLECTION: [
            IndexModel([("id", ASCENDING)], unique=True, name="idx_digest_id_unique"),
            IndexModel([("chat_id", ASCENDING), ("date", DESCENDING)], name="idx_digest_chat_date"),
            IndexModel([("tenant_key", ASCENDING), ("chat_id", ASCENDING), ("date", DESCENDING)], name="idx_digest_tenant_chat_date"),
            IndexModel([("date", DESCENDING)], name="idx_digest_date"),
        ],

        # 6. MASTER DAILY DIGESTS (Bản tổng hợp ngày cấp điều hành)
        settings.MONGO_MASTER_DIGEST_COLLECTION: [
            IndexModel([("id", ASCENDING)], unique=True, name="idx_master_digest_id_unique"),
            IndexModel([("tenant_key", ASCENDING), ("date", DESCENDING)], name="idx_master_digest_tenant_date"),
            IndexModel([("date", DESCENDING)], name="idx_master_digest_date"),
        ],

        # 7. DRAFT LOGS (Nhật ký bản nháp chờ phê duyệt)
        settings.MONGO_DRAFT_LOGS_COLLECTION: [
            IndexModel([("draft_id", ASCENDING)], unique=True, sparse=True, name="idx_drafts_id_unique"),
            IndexModel([("chat_id", ASCENDING), ("status", ASCENDING)], name="idx_drafts_chat_status"),
            IndexModel([("tenant_key", ASCENDING), ("chat_id", ASCENDING), ("status", ASCENDING)], name="idx_drafts_tenant_chat_status"),
            IndexModel([("created_at", DESCENDING)], name="idx_drafts_created_at"),
        ],

        # 8. LARK AUTH (Trạng thái Token OAuth2)
        settings.MONGO_AUTH_COLLECTION: [
            IndexModel([("open_id", ASCENDING)], name="idx_auth_open_id"),
            IndexModel([("status", ASCENDING)], name="idx_auth_status"),
        ],

        # 9. COST TELEMETRY (Đo lường chi phí LLM & JEV)
        settings.MONGO_TELEMETRY_COLLECTION: [
            IndexModel([("timestamp", DESCENDING)], name="idx_telemetry_timestamp"),
            IndexModel([("service", ASCENDING), ("operation", ASCENDING)], name="idx_telemetry_svc_op"),
            IndexModel([("chat_id", ASCENDING)], sparse=True, name="idx_telemetry_chat_id"),
        ],

        # 10. USER SETTINGS & BYOK (Cấu hình người dùng & API Key cá nhân)
        getattr(settings, "MONGO_USER_SETTINGS_COLLECTION", "user_settings"): [
            # Một user có thể thuộc nhiều tenant; uniqueness phải nằm trên cặp
            # (tenant_key, open_id), không phải open_id toàn hệ thống.
            IndexModel([("open_id", ASCENDING)], name="idx_user_settings_open_id"),
            IndexModel([("tenant_key", ASCENDING), ("open_id", ASCENDING)], name="idx_user_settings_tenant_open_id"),
            IndexModel([("updated_at", DESCENDING)], name="idx_user_settings_updated_at"),
        ],

        # 11. SYSTEM CONFIG & AUTO PROVISIONED BITABLE
        getattr(settings, "MONGO_SYSTEM_CONFIG_COLLECTION", "system_config"): [
            IndexModel([("config_key", ASCENDING)], unique=True, name="idx_system_config_key_unique"),
            IndexModel([("tenant_key", ASCENDING)], name="idx_system_config_tenant"),
        ],

        # 12. TENANTS (Danh sách Doanh nghiệp Multi-Tenant ISV - EDL-0020)
        getattr(settings, "MONGO_TENANTS_COLLECTION", "tenants"): [
            IndexModel([("tenant_key", ASCENDING)], unique=True, name="idx_tenants_key_unique"),
            IndexModel([("created_at", DESCENDING)], name="idx_tenants_created_at"),
        ],

        # 13. ISV AUTH (Vé app_ticket & Tenant Token Cache - EDL-0020)
        getattr(settings, "MONGO_ISV_AUTH_COLLECTION", "isv_auth"): [
            IndexModel([("tenant_key", ASCENDING)], sparse=True, name="idx_isv_auth_tenant_key"),
            IndexModel([("updated_at", DESCENDING)], name="idx_isv_auth_updated_at"),
        ],

        # One-click setup sessions phải tra cứu được sau restart/scale-out.
        getattr(settings, "MONGO_SETUP_SESSIONS_COLLECTION", "setup_sessions"): [
            IndexModel([("task_id", ASCENDING)], unique=True, name="uq_setup_sessions_task_id"),
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_setup_sessions_expires_at"),
        ],

        # Credential Custom App theo từng tenant/setup registration.
        getattr(settings, "MONGO_LARK_APPS_COLLECTION", "lark_app_credentials"): [
            IndexModel([("registration_id", ASCENDING)], unique=True, name="uq_lark_apps_registration_id"),
            IndexModel([("app_id", ASCENDING)], unique=True, name="uq_lark_apps_app_id"),
            IndexModel([("tenant_key", ASCENDING)], sparse=True, name="idx_lark_apps_tenant_key"),
            IndexModel([("status", ASCENDING)], name="idx_lark_apps_status"),
        ],
    }


async def ensure_database_indexes(db_instance: Any = None) -> Dict[str, List[str]]:
    """
    Tự động áp dụng tất cả các Index Model vào MongoDB.
    Được gọi tự động trong quá trình khởi động server (FastAPI lifespan).

    Args:
        db_instance: Instance của Motor Database. Nếu None, sẽ lấy qua get_async_db().

    Returns:
        Dict {collection_name: [tên_các_index_đã_tạo]}
    """
    if db_instance is None:
        from database.db import get_async_db
        db_instance = get_async_db()

    specs = get_index_specifications()
    results: Dict[str, List[str]] = {}
    total_created = 0

    for col_name, index_models in specs.items():
        col = db_instance[col_name]
        results[col_name] = []
        try:
            if col_name == getattr(settings, "MONGO_USER_SETTINGS_COLLECTION", "user_settings"):
                # Migration an toàn cho index cũ từng ép open_id global-unique.
                try:
                    await col.drop_index("idx_user_settings_open_id_unique")
                except Exception:
                    pass
            created_names = await col.create_indexes(index_models)
            results[col_name] = created_names
            total_created += len(created_names)
            logger.debug(f"✔ Đã đảm bảo {len(created_names)} indexes trên collection '{col_name}'.")
        except OperationFailure as op_err:
            logger.warning(
                f"⚠️ Lỗi OperationFailure khi tạo index trên '{col_name}': {op_err}. "
                f"Tiến hành tạo từng index để bỏ qua xung đột..."
            )
            # Tạo từng index để bảo đảm các index khác vẫn được tạo nếu 1 index gặp xung đột
            for model in index_models:
                try:
                    name = await col.create_indexes([model])
                    results[col_name].extend(name)
                    total_created += 1
                except Exception as ex:
                    logger.warning(f"  - Không thể tạo index {model.document}: {ex}")
        except Exception as e:
            logger.error(f"❌ Exception khi tạo index cho '{col_name}': {e}", exc_info=True)

    logger.info(f"✅ [DATABASE INDEXES] Đã đảm bảo thành công {total_created} indexes trên {len(specs)} collections.")
    return results
