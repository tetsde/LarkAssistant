"""
HiLark Token Utilities & Health Checker
========================================
Vị trí: server/services/auth/token_verifier.py

Mục đích:
    - Tiện ích kiểm tra, phân tích và ping xác thực Lark User Access Token (access_token_user)
      TRƯỚC khi đem vào sử dụng trong hệ thống.
    - Phát hiện sớm token đã hết hạn (expired) hoặc không hợp lệ (code 20005)
      ngay từ timestamp JWT và qua Network Ping tới Lark Open API.
    - Báo cảnh báo chi tiết, kích hoạt chế độ Safe Fallback, TUYỆT ĐỐI KHÔNG làm sập (crash)
      hệ thống khi token hết hạn.

Sử dụng:
    from utils.lark_token import ping_user_access_token, check_and_warn_token

    # 1. Ping kiểm tra nhanh:
    res = ping_user_access_token()
    if not res.is_valid:
        print(f"Cảnh báo: {res.message}")

    # 2. Hoặc in banner cảnh báo trực tiếp:
    check_and_warn_token()
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple

import httpx

# Đảm bảo import được module từ server
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_ROOT = os.path.dirname(CURRENT_DIR)
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from core.config import settings

logger = logging.getLogger("hilark.token")

VIETNAM_TZ = timezone(timedelta(hours=7))


# =============================================================================
# DATA STRUCTURE: TOKEN CHECK RESULT
# =============================================================================

@dataclass
class TokenCheckResult:
    """Kết quả kiểm tra và ping User Access Token."""
    is_valid: bool
    is_expired: bool
    status: str  # "valid", "expired", "invalid_format", "missing", "api_error"
    message: str
    expires_at: Optional[datetime] = None
    expires_in_seconds: Optional[int] = None
    user_name: Optional[str] = None
    user_open_id: Optional[str] = None
    code: Optional[int] = None
    raw_payload: Optional[Dict[str, Any]] = None

    def format_remaining_time(self) -> str:
        """Định dạng thời gian còn lại dễ đọc (tiếng Việt)."""
        if self.expires_in_seconds is None:
            return "Không xác định"
        
        abs_sec = abs(self.expires_in_seconds)
        hours = abs_sec // 3600
        minutes = (abs_sec % 3600) // 60
        seconds = abs_sec % 60

        parts = []
        if hours > 0:
            parts.append(f"{hours} giờ")
        if minutes > 0 or hours > 0:
            parts.append(f"{minutes} phút")
        parts.append(f"{seconds} giây")
        time_str = " ".join(parts)

        if self.expires_in_seconds > 0:
            return f"Còn lại {time_str}"
        elif self.expires_in_seconds == 0:
            return "Hết hạn ngay lúc này"
        else:
            return f"Đã hết hạn cách đây {time_str}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "is_expired": self.is_expired,
            "status": self.status,
            "message": self.message,
            "expires_at": self.expires_at.strftime("%Y-%m-%d %H:%M:%S (%Z)") if self.expires_at else None,
            "expires_in_seconds": self.expires_in_seconds,
            "remaining_time": self.format_remaining_time(),
            "user_name": self.user_name,
            "user_open_id": self.user_open_id,
            "code": self.code,
        }


# =============================================================================
# 1. HÀM BÓC TÁCH JWT EXPIRATION (OFFLINE / FAST CHECK)
# =============================================================================

def decode_jwt_token_payload(token: str) -> Optional[Dict[str, Any]]:
    """Giải mã phần payload của JWT token mà không cần thư viện ngoài."""
    if not token or not isinstance(token, str) or "." not in token:
        return None
    try:
        parts = token.strip().split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1]
            padding = "=" * ((4 - len(payload_b64) % 4) % 4)
            data_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
            return json.loads(data_bytes.decode("utf-8", errors="ignore"))
    except Exception as e:
        logger.debug(f"Không thể parse JWT payload: {e}")
    return None


def parse_jwt_expiration(token: str) -> Tuple[bool, Optional[datetime], Optional[int], Optional[Dict[str, Any]]]:
    """
    Bóc tách payload JWT an toàn để kiểm tra thời hạn (exp timestamp).
    Trả về: (is_expired, expires_at_dt, remaining_seconds, payload_dict)
    """
    payload = decode_jwt_token_payload(token)
    if not payload:
        return True, None, None, None

    exp_timestamp = payload.get("exp")
    if exp_timestamp is None:
        return False, None, None, payload

    now_timestamp = int(time.time())
    remaining = int(exp_timestamp) - now_timestamp
    is_expired = remaining <= 0

    exp_dt = datetime.fromtimestamp(exp_timestamp, tz=VIETNAM_TZ)
    return is_expired, exp_dt, remaining, payload


# =============================================================================
# 2. HÀM PING VÀ KIỂM TRA ACCESS TOKEN (ONLINE CHECK)
# =============================================================================

def ping_user_access_token(
    token: Optional[str] = None,
    domain: Optional[str] = None,
    timeout: float = 6.0,
) -> TokenCheckResult:
    """
    Tiến hành ping và kiểm tra tính hợp lệ của Lark User Access Token:
      1. Kiểm tra rỗng và bóc tách thời hạn JWT nhanh (offline check).
      2. Ping trực tiếp endpoint /open-apis/authen/v1/user_info của Lark Open Platform.
      3. Bắt toàn bộ lỗi (network timeout, invalid code, token expired), đảm bảo KHÔNG làm crash app.

    Trả về: TokenCheckResult
    """
    if token is not None:
        target_token = token.strip()
    else:
        # 1. Ưu tiên lấy token đã nạp vào lark_service
        try:
            from services.lark import lark_service
            target_token = (getattr(lark_service, "user_access_token", "") or "").strip()
        except Exception:
            target_token = ""

        # 2. Nếu rỗng, thử đọc từ MongoDB lark_auth
        if not target_token:
            try:
                from database.db import get_sync_db
                db = get_sync_db()
                doc = db[settings.MONGO_AUTH_COLLECTION].find_one({"_id": "primary_user_token"})
                if doc and doc.get("access_token"):
                    target_token = doc["access_token"].strip()
            except Exception:
                pass

        # 3. Fallback cuối cùng về file .env
        if not target_token:
            target_token = (settings.LARK_USER_ACCESS_TOKEN or "").strip()

    target_domain = (domain or settings.LARK_DOMAIN or "https://open.larksuite.com").rstrip("/")

    # TH1: Token chưa được cấu hình
    if not target_token:
        return TokenCheckResult(
            is_valid=False,
            is_expired=True,
            status="missing",
            message="Chưa cấu hình hoặc chưa có User Access Token. Vui lòng truy cập http://localhost:8000/auth/lark/login để cấp quyền.",
            code=None,
        )

    # TH2: Phân tích nhanh JWT offline
    jwt_expired, exp_dt, remaining_sec, payload = parse_jwt_expiration(target_token)
    if remaining_sec is not None and remaining_sec <= 0:
        exp_str = exp_dt.strftime("%Y-%m-%d %H:%M:%S") if exp_dt else "Không rõ"
        abs_hours = abs(remaining_sec) // 3600
        abs_mins = (abs_sec := abs(remaining_sec) % 3600) // 60
        time_desc = f"{abs_hours} giờ {abs_mins} phút" if abs_hours > 0 else f"{abs_mins} phút"

        return TokenCheckResult(
            is_valid=False,
            is_expired=True,
            status="expired",
            message=(
                f"access_token_user ĐÃ HẾT HẠN theo JWT timestamp vào lúc {exp_str} "
                f"(quá hạn {time_desc}). Vui lòng lấy token mới từ Lark Developer Console."
            ),
            expires_at=exp_dt,
            expires_in_seconds=remaining_sec,
            code=20005,
            raw_payload=payload,
        )

    # TH3: Ping online tới Lark API để xác thực trạng thái từ máy chủ Lark
    url = f"{target_domain}/open-apis/authen/v1/user_info"
    headers = {
        "Authorization": f"Bearer {target_token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers)
            status_code = resp.status_code
            data = resp.json()

        code = data.get("code")
        msg = data.get("msg", "")

        # A. Thành công: code == 0
        if code == 0:
            user_data = data.get("data", {})
            user_name = user_data.get("name", "Người dùng")
            open_id = user_data.get("open_id") or user_data.get("user_id")

            # Nếu token dạng Opaque (u-...), tra cứu thời hạn lưu trong MongoDB
            if remaining_sec is None:
                try:
                    from database.db import get_sync_db
                    db = get_sync_db()
                    doc = db[settings.MONGO_AUTH_COLLECTION].find_one({"_id": "primary_user_token"})
                    if doc and doc.get("access_token") == target_token:
                        exp_at = doc.get("expires_at", 0)
                        now_ts = time.time()
                        if exp_at > now_ts:
                            remaining_sec = int(exp_at - now_ts)
                            exp_dt = datetime.fromtimestamp(exp_at, tz=VIETNAM_TZ)
                except Exception:
                    pass

            time_info = ""
            if remaining_sec is not None:
                time_info = f" ({TokenCheckResult(True, False, 'valid', '', exp_dt, remaining_sec).format_remaining_time()})"

            return TokenCheckResult(
                is_valid=True,
                is_expired=False,
                status="valid",
                message=f"✔ Token hợp lệ! Danh tính: {user_name} (open_id: {open_id}){time_info}",
                expires_at=exp_dt,
                expires_in_seconds=remaining_sec,
                user_name=user_name,
                user_open_id=open_id,
                code=0,
                raw_payload=payload,
            )

        # B. Token hết hạn hoặc không hợp lệ: code == 20005, 99991663, 99991668
        if code in (20005, 99991663, 99991668) or "invalid access token" in msg.lower() or "token expired" in msg.lower():
            return TokenCheckResult(
                is_valid=False,
                is_expired=True,
                status="expired",
                message=f"Lark API từ chối token: {msg} (Mã lỗi: {code}). Token đã hết hạn hoặc bị thu hồi.",
                expires_at=exp_dt,
                expires_in_seconds=remaining_sec,
                code=code,
                raw_payload=payload,
            )

        # C. Các lỗi API khác từ Lark
        return TokenCheckResult(
            is_valid=False,
            is_expired=False,
            status="api_error",
            message=f"Lark API trả về lỗi: {msg} (code={code}, http_status={status_code})",
            expires_at=exp_dt,
            expires_in_seconds=remaining_sec,
            code=code,
            raw_payload=payload,
        )

    except httpx.TimeoutException:
        logger.warning("Ping Lark User Access Token bị timeout. Tiếp tục với offline check.")
        # Nếu online ping timeout nhưng offline jwt còn hạn
        is_ok = (remaining_sec is not None and remaining_sec > 0)
        return TokenCheckResult(
            is_valid=is_ok,
            is_expired=not is_ok,
            status="timeout",
            message="Ping Lark API timeout (mạng chậm). Kết quả tạm dựa trên timestamp JWT offline.",
            expires_at=exp_dt,
            expires_in_seconds=remaining_sec,
            code=None,
            raw_payload=payload,
        )
    except Exception as e:
        logger.warning(f"Lỗi khi ping Lark User Access Token: {e}")
        return TokenCheckResult(
            is_valid=False,
            is_expired=False,
            status="api_error",
            message=f"Không thể kết nối tới Lark API: {str(e)}",
            expires_at=exp_dt,
            expires_in_seconds=remaining_sec,
            code=None,
            raw_payload=payload,
        )


async def aping_user_access_token(
    token: Optional[str] = None,
    domain: Optional[str] = None,
    timeout: float = 6.0,
) -> TokenCheckResult:
    """Phiên bản bất đồng bộ (async) của ping_user_access_token."""
    if token is not None:
        target_token = token.strip()
    else:
        target_token = (settings.LARK_USER_ACCESS_TOKEN or "").strip()

    target_domain = (domain or settings.LARK_DOMAIN or "https://open.larksuite.com").rstrip("/")

    if not target_token:
        return TokenCheckResult(
            is_valid=False,
            is_expired=True,
            status="missing",
            message="Chưa cấu hình `access_token_user` trong .env!",
            code=None,
        )

    jwt_expired, exp_dt, remaining_sec, payload = parse_jwt_expiration(target_token)
    if remaining_sec is not None and remaining_sec <= 0:
        exp_str = exp_dt.strftime("%Y-%m-%d %H:%M:%S") if exp_dt else "Không rõ"
        return TokenCheckResult(
            is_valid=False,
            is_expired=True,
            status="expired",
            message=f"access_token_user ĐÃ HẾT HẠN vào lúc {exp_str} theo JWT. Vui lòng cập nhật token mới.",
            expires_at=exp_dt,
            expires_in_seconds=remaining_sec,
            code=20005,
            raw_payload=payload,
        )

    url = f"{target_domain}/open-apis/authen/v1/user_info"
    headers = {
        "Authorization": f"Bearer {target_token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
            data = resp.json()

        code = data.get("code")
        msg = data.get("msg", "")

        if code == 0:
            user_data = data.get("data", {})
            user_name = user_data.get("name", "Người dùng")
            open_id = user_data.get("open_id") or user_data.get("user_id")
            return TokenCheckResult(
                is_valid=True,
                is_expired=False,
                status="valid",
                message=f"✔ Token hợp lệ! Danh tính: {user_name}",
                expires_at=exp_dt,
                expires_in_seconds=remaining_sec,
                user_name=user_name,
                user_open_id=open_id,
                code=0,
                raw_payload=payload,
            )

        if code in (20005, 99991663, 99991668) or "invalid access token" in msg.lower():
            return TokenCheckResult(
                is_valid=False,
                is_expired=True,
                status="expired",
                message=f"Lark API từ chối token: {msg} (Mã lỗi: {code})",
                expires_at=exp_dt,
                expires_in_seconds=remaining_sec,
                code=code,
                raw_payload=payload,
            )

        return TokenCheckResult(
            is_valid=False,
            is_expired=False,
            status="api_error",
            message=f"Lark API lỗi: {msg} (code={code})",
            expires_at=exp_dt,
            expires_in_seconds=remaining_sec,
            code=code,
            raw_payload=payload,
        )
    except Exception as e:
        return TokenCheckResult(
            is_valid=False,
            is_expired=False,
            status="api_error",
            message=f"Lỗi kết nối Lark API: {str(e)}",
            expires_at=exp_dt,
            expires_in_seconds=remaining_sec,
            code=None,
            raw_payload=payload,
        )


# =============================================================================
# 3. HÀM CHECK VÀ IN CẢNH BÁO AN TOÀN TRÊN TERMINAL
# =============================================================================

def check_and_warn_token(token: Optional[str] = None) -> TokenCheckResult:
    """
    Thực hiện ping kiểm tra token và in cảnh báo trực quan ra Terminal.
    Được gọi khi ứng dụng khởi động.
    """
    result = ping_user_access_token(token=token)

    if result.is_valid:
        print("✔ [LARK TOKEN CHECK] User Access Token HỢP LỆ!")
        print(f"   • Danh tính : {result.user_name} ({result.user_open_id})")
        print(f"   • Thời hạn  : {result.format_remaining_time()}")
    else:
        print("\n" + "!" * 70)
        print("⚠️  [CẢNH BÁO AN TOÀN: LARK USER ACCESS TOKEN KHÔNG HỢP LỆ]")
        print("!" * 70)
        print(f"📌 Trạng thái     : {result.status.upper()}")
        print(f"💬 Chi tiết lỗi   : {result.message}")
        if result.expires_at:
            print(f"🕒 Thời điểm hết hạn : {result.expires_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            print(f"⏳ Tình trạng        : {result.format_remaining_time()}")
        print("-" * 70)
        print("🛡️  CƠ CHẾ BẢO VỆ CHỐNG CRASH HỆ THỐNG:")
        print("   1. Hệ thống KHÔNG CRASH và vẫn duy trì hoạt động bình thường.")
        print("   2. Các tác vụ trả lời nhân danh User sẽ tự động tạm dừng an toàn")
        print("      hoặc báo lỗi rõ ràng thay vì làm sập ứng dụng.")
        print("   3. ĐỂ KHẮC PHỤC: Vui lòng vào Lark Developer Console -> Test Users ->")
        print("      Lấy User Access Token mới và cập nhật vào file `.env` (key: `access_token_user`).")
        print("!" * 70 + "\n")

    return result


# =============================================================================
# CLI RUNNER KHI GỌI TRỰC TIẾP
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🚀 HILARK TOKEN HEALTH CHECKER - KIỂM TRA USER ACCESS TOKEN")
    print("=" * 70)
    res = check_and_warn_token()
    print("Raw Result:", json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
