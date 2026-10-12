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

logger = logging.getLogger(__name__)

# Singletons cho Async Motor client
_async_client: Optional[AsyncIOMotorClient] = None
# Singleton cho Sync PyMongo client
_sync_client: Optional[MongoClient] = None


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


def get_chat_scopes_collection() -> AsyncIOMotorCollection:
    """Collection lưu trữ Ánh xạ phân quyền dữ liệu nhóm chat (Chat Scopes / KB Mappings)."""
    db = get_async_db()
    return db[settings.MONGO_CHAT_SCOPE_COLLECTION]


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

async def get_all_facts(entity_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lấy danh sách tất cả facts trong MongoDB, tùy chọn lọc theo entity_id."""
    col = get_claims_collection()
    query = {"entity_id": entity_id} if entity_id else {}
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


# ==========================================
# LƯU KẾT QUẢ TRÍCH XUẤT VÀO MONGODB
# ==========================================

async def save_extraction_to_mongo(extraction_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Lưu kết quả trích xuất vào MongoDB (Memories & Claims):
      1. Upsert entities vào collection memories.
      2. Đánh dấu superseded cho facts cũ trong collection claims.
      3. Insert/Upsert facts mới vào collection claims.
    """
    new_entities = extraction_result.get("entities") or extraction_result.get("memory", [])
    new_facts = extraction_result.get("facts") or extraction_result.get("claims", [])
    superseded_facts = extraction_result.get("superseded_facts") or extraction_result.get("superseded_claims", [])

    # 1. Upsert entities
    for ent in new_entities:
        await upsert_entity(ent)

    # 2. Cập nhật superseded facts
    superseded_ids = [
        f.get("id") or f.get("_id")
        for f in superseded_facts
        if (f.get("id") or f.get("_id"))
    ]
    if superseded_ids:
        await supersede_facts_by_ids(superseded_ids)

    # 3. Thêm facts mới vào collection claims
    claims_col = get_claims_collection()
    for fact in new_facts:
        fid = fact.get("id")
        if not fid:
            continue
        fact_copy = dict(fact)
        fact_copy.pop("_id", None)
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


def get_all_facts_sync(entity_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lấy toàn bộ facts từ MongoDB (sync)."""
    col = get_sync_claims_collection()
    query = {"entity_id": entity_id} if entity_id else {}
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


def save_extraction_to_mongo_sync(extraction_result: Dict[str, Any]) -> Dict[str, Any]:
    """Lưu kết quả trích xuất vào MongoDB đồng bộ (sync)."""
    new_entities = extraction_result.get("entities") or extraction_result.get("memory", [])
    new_facts = extraction_result.get("facts") or extraction_result.get("claims", [])
    superseded_facts = extraction_result.get("superseded_facts") or extraction_result.get("superseded_claims", [])

    for ent in new_entities:
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

