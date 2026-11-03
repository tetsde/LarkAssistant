import os
import sys
import logging

SERVER_ROOT = os.path.dirname(os.path.abspath(__file__))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from core import token_loop
from core.config import settings
from core.http_client import init_http_client, close_http_client
from core.tenant_errors import TenantResolutionError, TokenUnavailable
from database.db import ensure_database_indexes, close_mongo_connections
from routers import health, chat, lark, digest, scope, policy, auth, onboarding, setup
from services.bot_service import start_bot_service, stop_bot_service
from services.auth_service import token_service
from services.auth.oauth_state_service import OAuthStateError


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 0. Chặn chế độ dev ghi dữ liệu giả: dry-run không được chạy ở production
    if str(getattr(settings, "ENVIRONMENT", "")).lower() == "production" and getattr(
        settings, "WEKNORA_PROVISION_DRY_RUN", False
    ):
        raise RuntimeError(
            "WEKNORA_PROVISION_DRY_RUN=True không được phép bật khi ENVIRONMENT=production: "
            "pipeline sẽ ghi vào MongoDB các dataset_id giả và tenant vẫn chuyển sang 'ready'."
        )
    # 1. Khởi tạo chỉ mục Database tối ưu tốc độ truy vấn & toàn vẹn
    await ensure_database_indexes()
    # 2. Khởi tạo Persistent HTTP Client Connection Pool
    await init_http_client()
    # 3. Khởi động token loop (không nạp legacy token vào RAM nữa — xem init_token_on_startup)
    await token_service.init_token_on_startup()
    # 4. Khởi động Lark Bot Service (WebSocket Client, Event Handlers, Daily Digest Scheduler)
    start_bot_service()
    yield
    # Dọn dẹp an toàn khi tắt server
    stop_bot_service()
    await close_http_client()
    await close_mongo_connections()
    # Token loop là daemon thread của process; dừng để không bỏ lại coroutine đang chờ.
    token_loop.stop()


app = FastAPI(
    title="WeKnora API Server",
    description="Refactored server with clean architecture (Router, Database, Services, Models)",
    version="1.0.0",
    lifespan=lifespan,
)

# Đăng ký các Router
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(lark.router)
app.include_router(digest.router)
app.include_router(scope.router)
app.include_router(policy.router)
app.include_router(auth.router)
app.include_router(onboarding.router)
app.include_router(setup.router)


@app.exception_handler(TenantResolutionError)
async def tenant_resolution_error_handler(request, exc: TenantResolutionError) -> JSONResponse:
    """
    Hợp đồng lỗi của tầng tenant: mỗi exception đã tự mang `http_status` và `error_code`,
    router không cần (và không nên) tự phiên dịch kiểu "chuẩn bị fallback".

    Body luôn kèm `tenant_key` để quản trị viên/người dùng biết doanh nghiệp nào đang thiếu gì,
    thay vì nhận 500 trống rỗng hoặc nhận kết quả của một tenant khác.
    """
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "success": False,
            "error_code": exc.error_code,
            "tenant_key": getattr(exc, "tenant_key", None),
            "message": str(exc),
            "detail": {
                k: v
                for k, v in {
                    "missing_fields": getattr(exc, "missing_fields", None),
                    "status": getattr(exc, "status", None),
                    "kind": getattr(exc, "kind", None),
                    "app_id": getattr(exc, "app_id", None),
                    "lark_code": getattr(exc, "lark_code", None),
                }.items()
                if v is not None
            },
        },
    )


@app.exception_handler(TokenUnavailable)
async def token_unavailable_error_handler(request, exc: TokenUnavailable) -> JSONResponse:
    """
    Hợp đồng lỗi của tầng token: `TokenUnavailable` → 503, còn `UserTokenMissing`
    (subclass) → 401 vì mỗi lớp tự mang `http_status`/`error_code` riêng.
    Router không được phép biến hai lỗi này thành 500 hoặc 400 chung chung.
    """
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "success": False,
            "error_code": exc.error_code,
            "tenant_key": getattr(exc, "tenant_key", None),
            "message": str(exc),
            "detail": {
                k: v
                for k, v in {
                    "kind": getattr(exc, "kind", None),
                    "app_id": getattr(exc, "app_id", None),
                    "lark_code": getattr(exc, "lark_code", None),
                }.items()
                if v is not None
            },
        },
    )


@app.exception_handler(OAuthStateError)
async def oauth_state_error_handler(request, exc: OAuthStateError) -> JSONResponse:
    """State ủy quyền không hợp lệ/hết hạn: 400 kèm mã lỗi để frontend hiện nút login lại."""
    return JSONResponse(
        status_code=400,
        content={"success": False, "error_code": exc.error_code, "message": str(exc)},
    )



if __name__ == "__main__":
    import uvicorn
    # Lưu ý: Nếu chạy bằng lệnh `uv run uvicorn main:app`, dòng dưới đây không được gọi.
    # Dòng này chỉ chạy khi bạn gọi trực tiếp bằng `python main.py`
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
