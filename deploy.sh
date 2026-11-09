#!/usr/bin/env bash
# ==============================================================================
# HiLark Enterprise Assistant - Production 1-Click Deployment Script
# ==============================================================================
set -e

# Tự động điều hướng về thư mục gốc của HiLark (nơi chứa deploy.sh, .env và docker-compose.prod.yml)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ANSI Color codes for clean terminal output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}===================================================================${NC}"
echo -e "${BLUE}       🚀 HILARK ENTERPRISE AI ASSISTANT - PRODUCTION DEPLOY       ${NC}"
echo -e "${BLUE}===================================================================${NC}"
echo ""

# ------------------------------------------------------------------------------
# 1. Kiểm tra môi trường & công cụ tiên quyết
# ------------------------------------------------------------------------------
echo -e "${YELLOW}[1/5] Kiểm tra công cụ hệ thống...${NC}"

if ! command -v docker >/dev/null 2>&1; then
    echo -e "${RED}❌ Lỗi: Docker chưa được cài đặt. Vui lòng cài đặt Docker trước khi tiếp tục.${NC}"
    exit 1
fi

DOCKER_COMPOSE_CMD=""
if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker-compose"
else
    echo -e "${RED}❌ Lỗi: Docker Compose chưa được cài đặt.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Đã tìm thấy Docker & ${DOCKER_COMPOSE_CMD}${NC}"

# ------------------------------------------------------------------------------
# 2. Kiểm tra cấu hình môi trường (.env)
# ------------------------------------------------------------------------------
echo -e "${YELLOW}[2/5] Kiểm tra tệp cấu hình môi trường (.env)...${NC}"
if [ ! -f ".env" ]; then
    if [ -f ".env.production.example" ]; then
        echo -e "${YELLOW}⚠️ Chưa tìm thấy file .env. Đang tự động sao chép từ .env.production.example...${NC}"
        cp .env.production.example .env
        echo -e "${YELLOW}⚠️ Vui lòng mở file .env và cập nhật thông tin Lark App & API Keys thực tế!${NC}"
    else
        echo -e "${RED}❌ Lỗi: Không tìm thấy file .env hoặc .env.production.example!${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ Tệp cấu hình .env đã sẵn sàng.${NC}"
fi

# ------------------------------------------------------------------------------
# 3. Kiểm tra trạng thái WeKnora On-premise Vault
# ------------------------------------------------------------------------------
echo -e "${YELLOW}[3/5] Kiểm tra kết nối WeKnora On-Premise Knowledge Vault...${NC}"
WEKNORA_RUNNING=false
if curl -s -f http://localhost:8080/health >/dev/null 2>&1; then
    WEKNORA_RUNNING=true
    echo -e "${GREEN}✓ WeKnora Core API đang hoạt động tại http://localhost:8080${NC}"
elif [ -d "WeKnora" ] && [ -f "WeKnora/docker-compose.yml" ]; then
    echo -e "${YELLOW}ℹ️ WeKnora chưa chạy. Bạn có thể khởi động WeKnora độc lập bằng lệnh:${NC}"
    echo -e "   cd WeKnora && docker compose up -d"
else
    echo -e "${YELLOW}ℹ️ Tiếp tục triển khai HiLark Server...${NC}"
fi

# ------------------------------------------------------------------------------
# 4. Xây dựng và khởi chạy Docker Compose Stack
# ------------------------------------------------------------------------------
COMPOSE_FILE="docker-compose.prod.yml"
if [ "$1" == "--all-in-one" ] || [ "$1" == "-a" ]; then
    COMPOSE_FILE="docker-compose.all-in-one.yml"
    echo -e "${GREEN}✓ Chế độ All-in-One được kích hoạt: Khởi chạy trọn bộ HiLark + WeKnora Vault.${NC}"
fi

echo -e "${YELLOW}[4/5] Xây dựng và khởi chạy các dịch vụ sản xuất (${COMPOSE_FILE})...${NC}"
$DOCKER_COMPOSE_CMD -f "$COMPOSE_FILE" build
$DOCKER_COMPOSE_CMD -f "$COMPOSE_FILE" up -d

# ------------------------------------------------------------------------------
# 5. Kiểm tra Healthcheck dịch vụ
# ------------------------------------------------------------------------------
echo -e "${YELLOW}[5/5] Đang chờ hệ thống sẵn sàng và kiểm tra Healthcheck...${NC}"

MAX_RETRIES=20
RETRY_COUNT=0
HEALTHY=false

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    RETRY_COUNT=$((RETRY_COUNT+1))
    if curl -s -f http://localhost:8000/health >/dev/null 2>&1; then
        HEALTHY=true
        break
    fi
    echo -n "."
    sleep 2
done
echo ""

if [ "$HEALTHY" = true ]; then
    echo -e "${GREEN}===================================================================${NC}"
    echo -e "${GREEN}  🎉 TRIỂN KHAI HILARK SẢN XUẤT THÀNH CÔNG!                       ${NC}"
    echo -e "${GREEN}===================================================================${NC}"
    echo ""
    echo -e "📍 ${BLUE}Cổng dịch vụ & Liên kết điều hành:${NC}"
    echo -e "   • API Server & Healthcheck:  ${GREEN}http://localhost:8000/health${NC}"
    echo -e "   • Onboarding Screen Guide:   ${GREEN}http://localhost:8000/onboarding/wizard${NC}"
    echo -e "   • API Swagger Docs:          ${GREEN}http://localhost:8000/docs${NC}"
    echo -e "   • Lark Webhook Gateway:      ${GREEN}POST /api/lark/events (HTTP Callback)${NC}"
    echo ""
    echo -e "🛠️ ${BLUE}Các lệnh quản trị thông dụng:${NC}"
    echo -e "   • Xem logs máy chủ:          ${YELLOW}$DOCKER_COMPOSE_CMD -f docker-compose.prod.yml logs -f hilark-server${NC}"
    echo -e "   • Khởi động lại dịch vụ:     ${YELLOW}$DOCKER_COMPOSE_CMD -f docker-compose.prod.yml restart${NC}"
    echo -e "   • Dừng toàn bộ hệ thống:     ${YELLOW}$DOCKER_COMPOSE_CMD -f docker-compose.prod.yml down${NC}"
    echo ""
else
    echo -e "${RED}⚠️ Dịch vụ khởi động mất nhiều thời gian hơn dự kiến hoặc có lỗi.${NC}"
    echo -e "Vui lòng kiểm tra logs chi tiết bằng lệnh: ${YELLOW}$DOCKER_COMPOSE_CMD -f docker-compose.prod.yml logs${NC}"
fi

