# ==============================================================================
# Production Dockerfile for HiLark FastAPI Backend
# Multi-stage build with Astral uv & Python 3.13-slim
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build virtual environment with uv (tối ưu tốc độ & không cần compiler)
# ------------------------------------------------------------------------------
FROM python:3.13-slim AS builder

WORKDIR /app

# Copy uv binary trực tiếp từ image chính thức (nhẹ và nhanh)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy danh sách dependency đã tinh gọn
COPY pyproject.toml uv.lock ./

# Đồng bộ virtualenv cô lập, chỉ cài production packages (--no-dev)
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
RUN uv sync --frozen --no-dev --no-install-project

# ------------------------------------------------------------------------------
# Stage 2: Final lightweight, hardened runtime image
# ------------------------------------------------------------------------------
FROM python:3.13-slim AS runner

WORKDIR /app

# Chỉ cài curl phục vụ container healthcheck và chứng chỉ SSL
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Tạo user bảo mật non-root
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -s /bin/bash -m appuser

# Copy virtualenv siêu nhẹ từ builder stage
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy mã nguồn ứng dụng (các thư mục docs/, tests/ đã bị loại bởi .dockerignore)
COPY --chown=appuser:appuser . /app/

USER appuser

EXPOSE 8000

# Production Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD curl --fail http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

