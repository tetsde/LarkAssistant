from fastapi import APIRouter
from core.config import settings

router = APIRouter(tags=["health"])

@router.get("/")
def health_check():
    return {
        "status": "ok",
        "base_url": settings.BASE_URL,
        "api_key_loaded": bool(settings.WEKNORA_API_KEY)
    }
