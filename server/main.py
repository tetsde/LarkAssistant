import os
import sys

SERVER_ROOT = os.path.dirname(os.path.abspath(__file__))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.http_client import init_http_client, close_http_client
from database.db import ensure_database_indexes, close_mongo_connections
from routers import health, chat, lark, digest, scope, policy, auth
from services.bot_service import start_bot_service, stop_bot_service
from services.token_service import token_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Khởi tạo chỉ mục Database tối ưu tốc độ truy vấn & toàn vẹn
    await ensure_database_indexes()
    # 2. Khởi tạo Persistent HTTP Client Connection Pool
    await init_http_client()
    # 3. Nạp Token User còn hiệu lực từ MongoDB vào RAM
    await token_service.init_token_on_startup()
    # 4. Khởi động Lark Bot Service (WebSocket Client, Event Handlers, Daily Digest Scheduler)
    start_bot_service()
    yield
    # Dọn dẹp an toàn khi tắt server
    stop_bot_service()
    await close_http_client()
    await close_mongo_connections()


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



if __name__ == "__main__":
    import uvicorn
    # Lưu ý: Nếu chạy bằng lệnh `uv run uvicorn main:app`, dòng dưới đây không được gọi.
    # Dòng này chỉ chạy khi bạn gọi trực tiếp bằng `python main.py`
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
