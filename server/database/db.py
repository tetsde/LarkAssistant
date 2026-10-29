"""
HiLark MongoDB Database Service
===============================
Cung cấp kết nối bất đồng bộ (Motor AsyncIO) và đồng bộ (PyMongo)
đến MongoDB phục vụ lưu trữ Thực thể (Entities / Memories) và Mệnh đề (Facts / Claims).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from pymongo import MongoClient
from pymongo.database import Database

from core.config import settings
from models.memory import FactStatus, get_vietnam_now_iso
from database.indexes import ensure_database_indexes, get_index_specifications

logger = logging.getLogger(__name__)

# Singletons cho Async Motor client
_async_client: Optional[AsyncIOMotorClient] = None
# Singleton cho Sync PyMongo client
_sync_client: Optional[MongoClient] = None


async def close_mongo_connections() -> None:
    """Đóng sạch sẽ các kết nối MongoDB (Async Motor và Sync PyMongo) khi tắt server."""
    global _async_client, _sync_client
    closed_any = False
    if _async_client is not None:
        try:
            _async_client.close()
            closed_any = True
        except Exception as e:
            logger.debug(f"Lỗi khi đóng Async Motor Client: {e}")
        _async_client = None

    if _sync_client is not None:
        try:
            _sync_client.close()
            closed_any = True
        except Exception as e:
            logger.debug(f"Lỗi khi đóng Sync PyMongo Client: {e}")
        _sync_client = None

    if closed_any:
        logger.info("✔ Đã đóng toàn bộ kết nối MongoDB an toàn.")



def get_async_client() -> AsyncIOMotorClient:
    """Khởi tạo hoặc trả về Async Motor Client an toàn với event loop."""
    global _async_client
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _async_client is not None:
        try:
            client_loop = _async_client.get_io_loop()
            if client_loop.is_closed() or (current_loop and client_loop != current_loop):
                _async_client = None
        except Exception:
            _async_client = None

    if _async_client is None:
        _async_client = AsyncIOMotorClient(
            settings.MONGO_URL,
            serverSelectionTimeoutMS=3000,
        )
    return _async_client


def get_async_db() -> AsyncIOMotorDatabase:
    """Trả về Motor Database theo cấu hình."""
    client = get_async_client()
    return client[settings.MONGO_DB]


def get_memories_collection() -> AsyncIOMotorCollection:
    """Collection lưu trữ Thực thể (Entities / Memories)."""
    db = get_async_db()
    return db[settings.MONGO_MEMORY_COLLECTION]


def get_claims_collection() -> AsyncIOMotorCollection:
    """Collection lưu trữ Mệnh đề & Sự thật (Facts / Claims)."""
    db = get_async_db()
    return db[settings.MONGO_CLAIMS_COLLECTION]

def get_staging_collection() -> AsyncIOMotorCollection:
    """Collection lưu trữ Vùng đệm tin nhắn trong ngày (Conversation Staging)."""
    db = get_async_db()
    return db[settings.MONGO_STAGING_COLLECTION]


def get_daily_digests_collection() -> AsyncIOMotorCollection:
    """Collection lưu trữ Bản tổng hợp ngày (Daily Digests)."""
    db = get_async_db()
    return db[settings.MONGO_DIGEST_COLLECTION]


def get_master_daily_digests_collection() -> AsyncIOMotorCollection:
    """Collection lưu trữ Bản tổng hợp ngày Cấp Điều Hành (Master Daily Digests)."""
    db = get_async_db()
    return db[settings.MONGO_MASTER_DIGEST_COLLECTION]


def get_chat_scopes_collection() -> AsyncIOMotorCollection:
    """Collection lưu trữ Ánh xạ phân quyền dữ liệu nhóm chat (Chat Scopes / KB Mappings)."""
    db = get_async_db()
    return db[settings.MONGO_CHAT_SCOPE_COLLECTION]


def get_draft_logs_collection() -> AsyncIOMotorCollection:
    """Collection lưu các bản nháp đang chờ duyệt và trạng thái gửi Lark."""
    db = get_async_db()
    return db[settings.MONGO_DRAFT_LOGS_COLLECTION]


def get_auth_collection() -> AsyncIOMotorCollection:
    """Collection lưu trạng thái Token OAuth2 & Refresh Token của Lark."""
    db = get_async_db()
    return db[settings.MONGO_AUTH_COLLECTION]


def get_telemetry_collection() -> AsyncIOMotorCollection:
    """Collection lưu nhật ký đo lường chi phí LLM & JEV (Cost Telemetry)."""
    db = get_async_db()
    return db[settings.MONGO_TELEMETRY_COLLECTION]


def get_sync_client() -> MongoClient:
    """Khởi tạo hoặc trả về Sync PyMongo Client (cho CLI/Scripts)."""
    global _sync_client
    if _sync_client is None:
        _sync_client = MongoClient(
            settings.MONGO_URL,
            serverSelectionTimeoutMS=3000,
        )
    return _sync_client


def get_sync_db() -> Database:
    """Trả về PyMongo Database đồng bộ."""
    client = get_sync_client()
    return client[settings.MONGO_DB]


async def check_mongo_connection() -> Dict[str, Any]:
    """
    Kiểm tra trạng thái kết nối tới MongoDB.
    Trả về dict chi tiết gồm trạng thái, database, collections, và tổng số bản ghi.
    """
    try:
        client = get_async_client()
        # Ping server admin
        ping_res = await client.admin.command("ping")
        db = get_async_db()
        collections = await db.list_collection_names()
        
        memories_count = 0
        claims_count = 0
        if settings.MONGO_MEMORY_COLLECTION in collections:
            memories_count = await db[settings.MONGO_MEMORY_COLLECTION].count_documents({})
        if settings.MONGO_CLAIMS_COLLECTION in collections:
            claims_count = await db[settings.MONGO_CLAIMS_COLLECTION].count_documents({})

        return {
            "connected": True,
            "status": "ok",
            "ping": ping_res,
            "mongo_url": settings.MONGO_URL,
            "database": settings.MONGO_DB,
            "collections": collections,
            "counts": {
                settings.MONGO_MEMORY_COLLECTION: memories_count,
                settings.MONGO_CLAIMS_COLLECTION: claims_count,
            },
        }
    except Exception as e:
        logger.error(f"Lỗi kết nối MongoDB: {e}")
        return {
            "connected": False,
            "status": "error",
            "error": str(e),
            "mongo_url": settings.MONGO_URL,
            "database": settings.MONGO_DB,
        }


def _clean_mongo_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Chuyển đổi _id của Mongo thành chuỗi để JSON Serializable an toàn."""
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


# ==========================================
# THAO TÁC CRUD ENTITIES (MEMORIES)
# ==========================================

async def get_all_entities(workspace_id: str = "default") -> List[Dict[str, Any]]:
    """Lấy danh sách tất cả entities trong MongoDB."""
    col = get_memories_collection()
    query = {"workspace_id": workspace_id} if workspace_id else {}
    cursor = col.find(query)
    entities = []
    async for doc in cursor:
        entities.append(_clean_mongo_doc(doc))
    return entities


async def get_entity_by_id(entity_id: str) -> Optional[Dict[str, Any]]:
    """Tra cứu thực thể theo entity_id."""
    col = get_memories_collection()
    doc = await col.find_one({"id": entity_id})
    return _clean_mongo_doc(doc) if doc else None


async def upsert_entity(entity: Dict[str, Any]) -> Dict[str, Any]:
    """
    Thêm mới hoặc cập nhật thực thể:
    Nếu thực thể đã có, tự động merge alias và cập nhật thông tin.
    """
    col = get_memories_collection()
    entity_id = entity.get("id")
    if not entity_id:
        raise ValueError("Entity thiếu trường 'id'")

    existing = await col.find_one({"id": entity_id})
    now_iso = get_vietnam_now_iso()

    if existing:
        # Hợp nhất alias
        existing_aliases = existing.get("aliases", [])
        new_aliases = entity.get("aliases", [])
        merged_aliases = list(dict.fromkeys(existing_aliases + new_aliases))
        entity["aliases"] = merged_aliases
        entity["updated_at"] = now_iso
        
        # Giữ lại các trường cũ nếu entity mới không ghi đè
        await col.update_one(
            {"id": entity_id},
            {"$set": {k: v for k, v in entity.items() if k != "_id"}},
        )
    else:
        entity["created_at"] = entity.get("created_at") or now_iso
        entity["updated_at"] = now_iso
        insert_data = {k: v for k, v in entity.items() if k != "_id"}
        await col.insert_one(insert_data)

    saved = await col.find_one({"id": entity_id})
    return _clean_mongo_doc(saved)


# ==========================================
# THAO TÁC CRUD FACTS / CLAIMS
# ==========================================

async def get_all_facts(
    entity_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    project_tag: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Lấy danh sách facts trong MongoDB:
      - Tùy chọn lọc theo entity_id.
      - Tùy chọn lọc theo scope (chat_id, project_tag hoặc scope_type=='global').
    """
    col = get_claims_collection()
    query: Dict[str, Any] = {}
    if entity_id:
        query["entity_id"] = entity_id

    if chat_id or project_tag:
        scope_or: List[Dict[str, Any]] = [{"scope_type": "global"}]
        if chat_id:
            scope_or.append({"chat_id": chat_id})
        if project_tag:
            scope_or.append({"project_tag": project_tag})

        if query:
            query = {"$and": [query, {"$or": scope_or}]}
        else:
            query = {"$or": scope_or}

    cursor = col.find(query)
    facts = []
    async for doc in cursor:
        facts.append(_clean_mongo_doc(doc))
    return facts


async def supersede_facts_by_ids(fact_ids: List[str]) -> int:
    """Đánh dấu superseded cho danh sách fact_ids."""
    if not fact_ids:
        return 0
    col = get_claims_collection()
    now_iso = get_vietnam_now_iso()
    result = await col.update_many(
        {"id": {"$in": fact_ids}},
        {
            "$set": {
                "status": FactStatus.SUPERSEDED.value,
                "updated_at": now_iso,
            }
        },
    )
    return result.modified_count


async def promote_claims_by_ids(
    fact_ids: List[str],
    approver_info: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Thăng hạng danh sách claims từ PROPOSED -> CURRENT (Phê duyệt chính thức).
    Cập nhật status, updated_at và asserted_by (nếu có thông tin người duyệt).
    """
    if not fact_ids:
        return 0
    col = get_claims_collection()
    now_iso = get_vietnam_now_iso()
    update_fields: Dict[str, Any] = {
        "status": FactStatus.CURRENT.value,
        "updated_at": now_iso,
        "promoted_at": now_iso,
    }
    if approver_info:
        update_fields["asserted_by"] = {
            "user_id": approver_info.get("user_id") or approver_info.get("open_id") or "",
            "user_name": approver_info.get("user_name") or "Lãnh đạo",
            "role": "owner",
        }
    result = await col.update_many(
        {"id": {"$in": fact_ids}},
        {"$set": update_fields},
    )
    return result.modified_count


async def promote_claims_by_message_id(
    message_id: str,
    approver_info: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Thăng hạng các claims PROPOSED phát sinh từ một message_id cụ thể thành CURRENT.
    Dùng cho Reaction Approval (Tầng 1) hoặc Thread Reply (Tầng 2).
    """
    if not message_id:
        return 0
    col = get_claims_collection()
    now_iso = get_vietnam_now_iso()
    query = {
        "status": FactStatus.PROPOSED.value,
        "$or": [
            {"source.message_id": message_id},
            {"source_message_id": message_id},
        ],
    }
    update_fields: Dict[str, Any] = {
        "status": FactStatus.CURRENT.value,
        "updated_at": now_iso,
        "promoted_at": now_iso,
        "promoted_by_message_id": message_id,
    }
    if approver_info:
        update_fields["asserted_by"] = {
            "user_id": approver_info.get("user_id") or approver_info.get("open_id") or "",
            "user_name": approver_info.get("user_name") or "Lãnh đạo",
            "role": "owner",
        }
    result = await col.update_many(query, {"$set": update_fields})
    return result.modified_count


async def promote_proposed_claims_for_chat(
    chat_id: str,
    approver_info: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Thăng hạng tất cả các claims PROPOSED trong một nhóm chat thành CURRENT.
    Dùng khi Sếp duyệt Daily Master Digest (Tầng 3).
    """
    if not chat_id:
        return 0
    col = get_claims_collection()
    now_iso = get_vietnam_now_iso()
    query = {
        "chat_id": chat_id,
        "status": FactStatus.PROPOSED.value,
    }
    update_fields: Dict[str, Any] = {
        "status": FactStatus.CURRENT.value,
        "updated_at": now_iso,
        "promoted_at": now_iso,
    }
    if approver_info:
        update_fields["asserted_by"] = {
            "user_id": approver_info.get("user_id") or approver_info.get("open_id") or "",
            "user_name": approver_info.get("user_name") or "Lãnh đạo",
            "role": "owner",
        }
    result = await col.update_many(query, {"$set": update_fields})
    return result.modified_count


async def get_pending_proposed_claims(
    date_str: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Lấy danh sách các claims đang ở trạng thái PROPOSED.
    Có thể lọc theo ngày (ví dụ: '2026-10-27') hoặc theo nhóm chat.
    """
    col = get_claims_collection()
    query: Dict[str, Any] = {"status": FactStatus.PROPOSED.value}
    if chat_id:
        query["chat_id"] = chat_id
    if date_str:
        query["$or"] = [
            {"created_at": {"$regex": f"^{date_str}"}},
            {"updated_at": {"$regex": f"^{date_str}"}},
            {"date": date_str},
        ]
    cursor = col.find(query).sort("created_at", -1)
    claims = await cursor.to_list(length=200)
    if claims:
        # Tự động ánh xạ tên thực thể từ collection memories để hiển thị thân thiện
        entity_ids = list({c.get("entity_id") for c in claims if c.get("entity_id")})
        if entity_ids:
            try:
                memories_col = get_memories_collection()
                ent_cursor = memories_col.find({"id": {"$in": entity_ids}})
                ent_docs = await ent_cursor.to_list(length=len(entity_ids) + 50)
                ent_map = {
                    e["id"]: (e.get("name") or e.get("canonical_name"))
                    for e in ent_docs
                    if e.get("id") and (e.get("name") or e.get("canonical_name"))
                }
                for c in claims:
                    eid = c.get("entity_id")
                    if eid in ent_map and ent_map[eid]:
                        c["entity_name"] = ent_map[eid]
            except Exception as e:
                logger.debug(f"Không thể ánh xạ entity_name cho pending claims: {e}")
    return claims


async def promote_all_proposed_claims(
    date_str: Optional[str] = None,
    chat_id: Optional[str] = None,
    approver_info: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Thăng hạng toàn bộ claims PROPOSED thành CURRENT (duyệt hàng loạt cuối ngày).
    """
    col = get_claims_collection()
    now_iso = get_vietnam_now_iso()
    query: Dict[str, Any] = {"status": FactStatus.PROPOSED.value}
    if chat_id:
        query["chat_id"] = chat_id
    if date_str:
        query["$or"] = [
            {"created_at": {"$regex": f"^{date_str}"}},
            {"updated_at": {"$regex": f"^{date_str}"}},
            {"date": date_str},
        ]
    update_fields: Dict[str, Any] = {
        "status": FactStatus.CURRENT.value,
        "updated_at": now_iso,
        "promoted_at": now_iso,
    }
    if approver_info:
        update_fields["asserted_by"] = {
            "user_id": approver_info.get("user_id") or approver_info.get("open_id") or "",
            "user_name": approver_info.get("user_name") or "Lãnh đạo",
            "role": "owner",
        }
    result = await col.update_many(query, {"$set": update_fields})
    return result.modified_count



async def reject_claims_by_message_id(message_id: str) -> int:
    """
    Đánh dấu rejected/superseded cho các claims PROPOSED phát sinh từ một message_id cụ thể.
    """
    if not message_id:
        return 0
    col = get_claims_collection()
    now_iso = get_vietnam_now_iso()
    query = {
        "status": FactStatus.PROPOSED.value,
        "$or": [
            {"source.message_id": message_id},
            {"source_message_id": message_id},
        ],
    }
    result = await col.update_many(
        query,
        {
            "$set": {
                "status": FactStatus.SUPERSEDED.value,
                "rejection_reason": "rejected_by_owner",
                "updated_at": now_iso,
            }
        },
    )
    return result.modified_count


async def reject_claims_by_ids(fact_ids: List[str]) -> int:
    """Đánh dấu rejected/superseded cho danh sách claims theo ID."""
    if not fact_ids:
        return 0
    col = get_claims_collection()
    now_iso = get_vietnam_now_iso()
    result = await col.update_many(
        {"id": {"$in": fact_ids}},
        {
            "$set": {
                "status": FactStatus.SUPERSEDED.value,
                "rejection_reason": "rejected_by_owner",
                "updated_at": now_iso,
            }
        },
    )
    return result.modified_count


async def recall_staging_message(
    message_id: str,
    recall_time: Optional[str] = None,
    recall_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Đánh dấu tin nhắn trong staging là đã bị thu hồi trên Lark.
    Trả về document staging để lấy bot_reply_message_id nếu có.
    """
    if not message_id:
        return None
    from pymongo import ReturnDocument
    col = get_staging_collection()
    now_iso = get_vietnam_now_iso()
    doc = await col.find_one_and_update(
        {"message_id": message_id},
        {
            "$set": {
                "is_recalled": True,
                "recalled_at": recall_time or now_iso,
                "recall_type": recall_type,
                "updated_at": now_iso,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    return _clean_mongo_doc(doc) if doc else None


async def save_bot_reply_to_staging(
    message_id: str,
    bot_reply_message_id: str,
) -> bool:
    """Ghi nhận message_id câu trả lời của bot vào tin nhắn gốc trong staging."""
    if not message_id or not bot_reply_message_id:
        return False
    col = get_staging_collection()
    now_iso = get_vietnam_now_iso()
    res = await col.update_one(
        {"message_id": message_id},
        {"$set": {"bot_reply_message_id": bot_reply_message_id, "updated_at": now_iso}},
    )
    return res.modified_count > 0


async def revoke_claims_by_message_id(
    message_id: str,
    reason: str = "Tin nhắn gốc đã bị thu hồi",
) -> Dict[str, int]:
    """
    Xử lý thu hồi facts/claims khi tin nhắn gốc bị thu hồi:
      1. Với các facts PROPOSED: Chuyển thành REVOKED (thu hồi hoàn toàn đề xuất).
      2. Với các facts CURRENT: Đánh dấu source_recalled = True (nguồn đã bị rút lại).
    """
    if not message_id:
        return {"proposed_revoked": 0, "current_flagged": 0}

    col = get_claims_collection()
    now_iso = get_vietnam_now_iso()
    query_base = {
        "$or": [
            {"source.message_id": message_id},
            {"source_message_id": message_id},
        ]
    }

    # 1. Thu hồi các claim PROPOSED
    res_proposed = await col.update_many(
        {"status": FactStatus.PROPOSED.value, **query_base},
        {
            "$set": {
                "status": FactStatus.REVOKED.value,
                "revocation_reason": reason,
                "revoked_at": now_iso,
                "updated_at": now_iso,
            }
        },
    )

    # 2. Gắn cờ nguồn đã bị thu hồi cho các claim CURRENT
    res_current = await col.update_many(
        {"status": FactStatus.CURRENT.value, **query_base},
        {
            "$set": {
                "source_recalled": True,
                "source_recalled_at": now_iso,
                "source_recalled_reason": reason,
                "updated_at": now_iso,
            }
        },
    )

    return {
        "proposed_revoked": res_proposed.modified_count,
        "current_flagged": res_current.modified_count,
    }


async def cancel_pending_drafts_by_message_id(
    message_id: str,
    reason: str = "Tin nhắn gốc đã bị thu hồi",
) -> int:
    """Hủy các bản nháp (draft logs) đang ở trạng thái pending gắn với tin nhắn bị thu hồi."""
    if not message_id:
        return 0
    col = get_draft_logs_collection()
    now_iso = get_vietnam_now_iso()
    res = await col.update_many(
        {"message_id": message_id, "status": "pending"},
        {
            "$set": {
                "status": "recalled",
                "cancellation_reason": reason,
                "updated_at": now_iso,
            }
        },
    )
    return res.modified_count


async def get_latest_proposed_claim(chat_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Lấy thông tin đề xuất (Claim) ở trạng thái proposed gần nhất."""
    col = get_claims_collection()
    query: Dict[str, Any] = {"status": FactStatus.PROPOSED.value}
    if chat_id:
        query["chat_id"] = chat_id
    doc = await col.find_one(query, sort=[("created_at", -1)])
    return doc


async def update_claim_value(
    claim_id: str,
    new_value: str,
    approver_info: Optional[Dict[str, Any]] = None,
) -> bool:
    """Cập nhật giá trị mới cho claim và đồng thời phê duyệt thành CURRENT."""
    col = get_claims_collection()
    now_iso = get_vietnam_now_iso()
    update_fields: Dict[str, Any] = {
        "value": new_value,
        "status": FactStatus.CURRENT.value,
        "updated_at": now_iso,
        "promoted_at": now_iso,
    }
    if approver_info:
        update_fields["asserted_by"] = {
            "user_id": approver_info.get("user_id") or approver_info.get("open_id") or "",
            "user_name": approver_info.get("user_name") or "Lãnh đạo",
            "role": "owner",
        }
    res = await col.update_one({"id": claim_id}, {"$set": update_fields})
    return res.modified_count == 1



# ==========================================
# LƯU KẾT QUẢ TRÍCH XUẤT VÀO MONGODB
# ==========================================

async def save_extraction_to_mongo(
    extraction_result: Dict[str, Any],
    chat_id: Optional[str] = None,
    project_tag: Optional[str] = None,
    scope_type: str = "chat",
) -> Dict[str, Any]:
    """
    Lưu kết quả trích xuất vào MongoDB (Memories & Claims):
      1. Upsert entities vào collection memories (gán scope nếu chưa có).
      2. Đánh dấu superseded cho facts cũ trong collection claims.
      3. Insert/Upsert facts mới vào collection claims gắn thẻ scope.
    """
    new_entities = extraction_result.get("entities") or extraction_result.get("memory", [])
    new_facts = extraction_result.get("facts") or extraction_result.get("claims", [])
    superseded_facts = extraction_result.get("superseded_facts") or extraction_result.get("superseded_claims", [])

    # 1. Upsert entities
    for ent in new_entities:
        if isinstance(ent, dict):
            if chat_id and not ent.get("chat_id"):
                ent["chat_id"] = chat_id
            if project_tag and not ent.get("project_tag"):
                ent["project_tag"] = project_tag
            if not ent.get("scope_type"):
                ent["scope_type"] = scope_type
        await upsert_entity(ent)

    # 2. Cập nhật superseded facts
    superseded_ids = [
        f.get("id") or f.get("_id")
        for f in superseded_facts
        if (f.get("id") or f.get("_id"))
    ]
    if superseded_ids:
        await supersede_facts_by_ids(superseded_ids)

    # 3. Thêm facts mới vào collection claims gắn scope
    claims_col = get_claims_collection()
    for fact in new_facts:
        fid = fact.get("id")
        if not fid:
            continue
        fact_copy = dict(fact)
        fact_copy.pop("_id", None)
        if chat_id and not fact_copy.get("chat_id"):
            fact_copy["chat_id"] = chat_id
        if project_tag and not fact_copy.get("project_tag"):
            fact_copy["project_tag"] = project_tag
        if not fact_copy.get("scope_type"):
            fact_copy["scope_type"] = scope_type
        await claims_col.update_one(
            {"id": fid},
            {"$set": fact_copy},
            upsert=True,
        )

    # Lấy thống kê hiện tại
    memories_col = get_memories_collection()
    total_entities = await memories_col.count_documents({})
    total_facts = await claims_col.count_documents({})

    return {
        "entities": new_entities,
        "facts": new_facts,
        "superseded_facts": superseded_facts,
        "total_stored_entities": total_entities,
        "total_stored_facts": total_facts,
        # Backward compatibility
        "memory": new_entities,
        "claims": new_facts,
        "superseded_claims": superseded_facts,
        "total_stored_claims": total_facts,
    }


async def clear_mongo_stores() -> None:
    """Xóa sạch toàn bộ dữ liệu trong 2 collection memories và claims."""
    memories_col = get_memories_collection()
    claims_col = get_claims_collection()
    await memories_col.delete_many({})
    await claims_col.delete_many({})


# ==========================================
# SYNC HELPERS (DÀNH CHO SCRIPTS / CLI / TESTS)
# ==========================================

def get_sync_memories_collection():
    """Collection memories dạng sync."""
    db = get_sync_db()
    return db[settings.MONGO_MEMORY_COLLECTION]


def get_sync_claims_collection():
    """Collection claims dạng sync."""
    db = get_sync_db()
    return db[settings.MONGO_CLAIMS_COLLECTION]


def get_all_entities_sync(workspace_id: str = "default") -> List[Dict[str, Any]]:
    """Lấy toàn bộ entities từ MongoDB (sync)."""
    col = get_sync_memories_collection()
    query = {"workspace_id": workspace_id} if workspace_id else {}
    return [_clean_mongo_doc(doc) for doc in col.find(query)]


def get_all_facts_sync(
    entity_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    project_tag: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Lấy toàn bộ facts từ MongoDB (sync):
      - Tùy chọn lọc theo entity_id.
      - Tùy chọn lọc theo scope (chat_id, project_tag hoặc scope_type=='global').
    """
    col = get_sync_claims_collection()
    query: Dict[str, Any] = {}
    if entity_id:
        query["entity_id"] = entity_id

    if chat_id or project_tag:
        scope_or: List[Dict[str, Any]] = [{"scope_type": "global"}]
        if chat_id:
            scope_or.append({"chat_id": chat_id})
        if project_tag:
            scope_or.append({"project_tag": project_tag})

        if query:
            query = {"$and": [query, {"$or": scope_or}]}
        else:
            query = {"$or": scope_or}

    return [_clean_mongo_doc(doc) for doc in col.find(query)]


def upsert_entity_sync(entity: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert entity vào MongoDB (sync)."""
    col = get_sync_memories_collection()
    entity_id = entity.get("id")
    if not entity_id:
        raise ValueError("Entity thiếu trường 'id'")

    existing = col.find_one({"id": entity_id})
    now_iso = get_vietnam_now_iso()

    if existing:
        existing_aliases = existing.get("aliases", [])
        new_aliases = entity.get("aliases", [])
        merged_aliases = list(dict.fromkeys(existing_aliases + new_aliases))
        entity["aliases"] = merged_aliases
        entity["updated_at"] = now_iso
        col.update_one(
            {"id": entity_id},
            {"$set": {k: v for k, v in entity.items() if k != "_id"}},
        )
    else:
        entity["created_at"] = entity.get("created_at") or now_iso
        entity["updated_at"] = now_iso
        insert_data = {k: v for k, v in entity.items() if k != "_id"}
        col.insert_one(insert_data)

    saved = col.find_one({"id": entity_id})
    return _clean_mongo_doc(saved)


def supersede_facts_by_ids_sync(fact_ids: List[str]) -> int:
    """Đánh dấu superseded cho danh sách fact_ids (sync)."""
    if not fact_ids:
        return 0
    col = get_sync_claims_collection()
    now_iso = get_vietnam_now_iso()
    result = col.update_many(
        {"id": {"$in": fact_ids}},
        {
            "$set": {
                "status": FactStatus.SUPERSEDED.value,
                "updated_at": now_iso,
            }
        },
    )
    return result.modified_count


def save_extraction_to_mongo_sync(
    extraction_result: Dict[str, Any],
    chat_id: Optional[str] = None,
    project_tag: Optional[str] = None,
    scope_type: str = "chat",
) -> Dict[str, Any]:
    """
    Lưu kết quả trích xuất vào MongoDB đồng bộ (sync):
      1. Upsert entities vào collection memories (gán scope nếu chưa có).
      2. Đánh dấu superseded cho facts cũ trong collection claims.
      3. Insert/Upsert facts mới vào collection claims gắn thẻ scope.
    """
    new_entities = extraction_result.get("entities") or extraction_result.get("memory", [])
    new_facts = extraction_result.get("facts") or extraction_result.get("claims", [])
    superseded_facts = extraction_result.get("superseded_facts") or extraction_result.get("superseded_claims", [])

    for ent in new_entities:
        if isinstance(ent, dict):
            if chat_id and not ent.get("chat_id"):
                ent["chat_id"] = chat_id
            if project_tag and not ent.get("project_tag"):
                ent["project_tag"] = project_tag
            if not ent.get("scope_type"):
                ent["scope_type"] = scope_type
        upsert_entity_sync(ent)

    superseded_ids = [
        f.get("id") or f.get("_id")
        for f in superseded_facts
        if (f.get("id") or f.get("_id"))
    ]
    if superseded_ids:
        supersede_facts_by_ids_sync(superseded_ids)

    claims_col = get_sync_claims_collection()
    for fact in new_facts:
        fid = fact.get("id")
        if not fid:
            continue
        fact_copy = dict(fact)
        fact_copy.pop("_id", None)
        if chat_id and not fact_copy.get("chat_id"):
            fact_copy["chat_id"] = chat_id
        if project_tag and not fact_copy.get("project_tag"):
            fact_copy["project_tag"] = project_tag
        if not fact_copy.get("scope_type"):
            fact_copy["scope_type"] = scope_type
        claims_col.update_one(
            {"id": fid},
            {"$set": fact_copy},
            upsert=True,
        )

    memories_col = get_sync_memories_collection()
    total_entities = memories_col.count_documents({})
    total_facts = claims_col.count_documents({})

    return {
        "entities": new_entities,
        "facts": new_facts,
        "superseded_facts": superseded_facts,
        "total_stored_entities": total_entities,
        "total_stored_facts": total_facts,
        "memory": new_entities,
        "claims": new_facts,
        "superseded_claims": superseded_facts,
        "total_stored_claims": total_facts,
    }


def clear_mongo_stores_sync() -> None:
    """Xóa sạch 2 collection memories và claims (sync)."""
    memories_col = get_sync_memories_collection()
    claims_col = get_sync_claims_collection()
    memories_col.delete_many({})
    claims_col.delete_many({})

