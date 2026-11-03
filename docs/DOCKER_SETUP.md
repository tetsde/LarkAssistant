# HiLark Server Docker Setup & Management

## 🚀 Quick Start

### Khởi động container
```bash
cd /Users/hoainam/Desktop/HiLark
./hilark-docker.sh start
```

### Kiểm tra trạng thái
```bash
./hilark-docker.sh status
```

### Xem logs
```bash
./hilark-docker.sh logs
```

### Kiểm tra health
```bash
./hilark-docker.sh health
# Hoặc:
curl http://localhost:8000/health
```

---

## 📋 Các lệnh quản lý

Script `hilark-docker.sh` cung cấp các lệnh sau:

| Lệnh | Mô tả |
|------|-------|
| `start` | Khởi động container (tự động stop container cũ nếu có) |
| `stop` | Dừng container |
| `restart` | Restart container |
| `logs` | Theo dõi logs realtime (Ctrl+C để thoát) |
| `status` | Hiển thị trạng thái container |
| `shell` | Mở bash shell trong container |
| `health` | Kiểm tra endpoint `/health` |
| `rebuild` | Build lại Docker image |
| `clean` | Dừng và xóa container |

### Ví dụ sử dụng

```bash
# Khởi động
./hilark-docker.sh start

# Theo dõi logs
./hilark-docker.sh logs

# Restart khi có thay đổi config
./hilark-docker.sh restart

# Build lại image sau khi sửa code
./hilark-docker.sh rebuild
./hilark-docker.sh start

# Dọn dẹp
./hilark-docker.sh clean
```

---

## 🏗️ Build Image Thủ Công

Nếu cần build image với options đặc biệt:

```bash
cd /Users/hoainam/Desktop/HiLark

# Build với tag mặc định
docker build -f server/Dockerfile -t hilark/server:latest ./server

# Build với tag khác
docker build -f server/Dockerfile -t hilark/server:v1.0.0 ./server

# Build no-cache (bỏ qua cache layers)
docker build --no-cache -f server/Dockerfile -t hilark/server:latest ./server
```

---

## 🔧 Cấu hình Container

### Environment Variables

Container sử dụng file `.env` để load environment variables. Đảm bảo file `.env` đã được cấu hình đúng:

```bash
# Kiểm tra file .env
cat .env | grep -E "MONGO_URL|LARK_APP_ID|WEKNORA_API_KEY"
```

### Network

Container chạy trên network `hilark-network` để kết nối với các services khác (MongoDB, WeKnora).

Kiểm tra network:
```bash
docker network inspect hilark-network
```

### Ports

- `8000:8000` - FastAPI server (HTTP)

### Volumes

Container không mount volumes persistent. Logs và data được lưu trong MongoDB và external services.

---

## 🐛 Troubleshooting

### Container không start

```bash
# Kiểm tra logs lỗi
./hilark-docker.sh logs

# Kiểm tra container có tồn tại không
docker ps -a | grep hilark-server

# Xóa container cũ và thử lại
./hilark-docker.sh clean
./hilark-docker.sh start
```

### Lỗi kết nối MongoDB

```bash
# Kiểm tra MONGO_URL trong .env
grep MONGO_URL .env

# Test kết nối từ trong container
docker exec hilark-server python -c "from pymongo import MongoClient; print(MongoClient(os.getenv('MONGO_URL')).admin.command('ping'))"
```

### Lỗi token hết hạn

Với fix auto-refresh token mới:
- Token sẽ tự động làm mới khi còn < 10 phút
- Kiểm tra logs để xác nhận auto-refresh hoạt động:

```bash
./hilark-docker.sh logs | grep "AUTO-REFRESH"
```

Bạn sẽ thấy log:
```
✅ [BITABLE AUTO-REFRESH] User token đã được làm mới hoặc vẫn còn hạn
✅ [CLIENT AUTO-REFRESH] User token đã được làm mới hoặc vẫn còn hạn
```

### Container bị crash/restart liên tục

```bash
# Kiểm tra health check
docker inspect hilark-server | grep -A 10 Health

# Kiểm tra resource usage
docker stats hilark-server --no-stream

# Xem logs đầy đủ
docker logs hilark-server --tail 200
```

---

## 🔄 Update & Deployment

### Quy trình update code

1. **Sửa code** trong `server/`
2. **Build lại image**:
   ```bash
   ./hilark-docker.sh rebuild
   ```
3. **Restart container**:
   ```bash
   ./hilark-docker.sh start
   ```
4. **Kiểm tra logs**:
   ```bash
   ./hilark-docker.sh logs
   ```

### Rolling update (zero downtime)

Nếu cần zero downtime, sử dụng docker-compose với nhiều replicas:

```bash
cd /Users/hoainam/Desktop/HiLark
docker-compose -f docker-compose.prod.yml up -d --scale hilark-server=2 --no-recreate
```

---

## 📊 Monitoring

### Kiểm tra trạng thái

```bash
# Container status
./hilark-docker.sh status

# Health endpoint
curl -s http://localhost:8000/health | jq

# Resource usage
docker stats hilark-server --no-stream
```

### Log locations

- **Container logs**: `docker logs hilark-server`
- **Application logs**: Trong container tại `/app/logs/` (nếu có cấu hình)

---

## 🔐 Security Notes

- Container chạy với non-root user (`appuser:1000`)
- Không mount sensitive directories
- Environment variables được load từ `.env` (không commit vào git)
- Network isolated với `hilark-network`

---

## ✅ Auto-Refresh Token Fix

Container này đã được apply fix auto-refresh token cho:

1. **Lark Base Service** (`bitable.py`)
   - Tự động refresh User Access Token khi hết hạn
   - Method: `_get_valid_user_token()`

2. **Lark Client Service** (`client.py`)
   - Auto-refresh cho DocX, Wiki, Drive APIs
   - Method: `_get_valid_user_token()`

3. **Token Service Integration**
   - Tích hợp với `token_service.get_valid_user_token()`
   - Refresh tự động khi token còn < 10 phút
   - Fallback về token cũ nếu refresh thất bại

**Kết quả:**
- ✅ Không còn lỗi `99991668: Invalid access token`
- ✅ Token tự động làm mới trong background
- ✅ Xử lý cả sync và async context

---

## 📚 Tài liệu liên quan

- [Dockerfile](../server/Dockerfile)
- [Token Auto-Refresh Fix](./BITABLE_TOKEN_AUTO_REFRESH_FIX.md)
- [Docker Compose](../docker-compose.prod.yml)

---

**Last Updated:** 2026-11-02  
**Docker Image:** `hilark/server:latest`  
**Python Version:** 3.13-slim  
**Base Image:** `python:3.13-slim` + `astral-sh/uv`
