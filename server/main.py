from fastapi import FastAPI
from routers import health, chat

app = FastAPI(
    title="WeKnora API Server",
    description="Refactored server with clean architecture (Router, Database, Services, Models)",
    version="1.0.0"
)

# Đăng ký các Router
app.include_router(health.router)
app.include_router(chat.router)

if __name__ == "__main__":
    import uvicorn
    # Lưu ý: Nếu chạy bằng lệnh `uv run uvicorn main:app`, dòng dưới đây không được gọi.
    # Dòng này chỉ chạy khi bạn gọi trực tiếp bằng `python main.py`
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
