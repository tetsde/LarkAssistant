"""
HiLark Bot - Standalone Runner
==============================
Vị trí: server/run_lark_bot.py

Lưu ý:
    Hiện tại Bot Service đã được tích hợp trực tiếp vào FastAPI Lifespan (main.py).
    Bạn chỉ cần chạy duy nhất 1 lệnh cho toàn bộ hệ thống:
        uv run uvicorn main:app --reload

    File này được giữ lại để tương thích ngược nếu bạn muốn chạy riêng Bot mà không bật Web API:
        uv run python run_lark_bot.py
"""

import os
import sys

SERVER_ROOT = os.path.dirname(os.path.abspath(__file__))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from services.bot_service import run_standalone_bot

if __name__ == "__main__":
    run_standalone_bot()
