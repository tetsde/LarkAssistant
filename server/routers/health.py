from fastapi import APIRouter
from core.config import settings
from database.db import check_mongo_connection

router = APIRouter(tags=["health"])

@router.get("/")
@router.get("/health")
async def health_check():
    mongo_status = await check_mongo_connection()
    return {
        "status": "ok",
        "base_url": settings.BASE_URL,
        "api_key_loaded": bool(settings.WEKNORA_API_KEY),
        "mongodb": mongo_status,
    }
