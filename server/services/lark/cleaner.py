"""
HiLark - Lark Base (Bitable) Field Cleaner & Token Utilities
===========================================================
Vị trí: server/services/lark/cleaner.py

Mục đích:
    Chuẩn hóa và làm sạch các giá trị thô phức tạp được trả về từ Lark Bitable API
    (như mảng text object, user array, attachment, url dict, timestamp mili-giây)
    về dạng dữ liệu Python cơ bản (str, int, float, list, datetime string)
    giúp dễ dàng hiển thị hoặc nạp vào LLM/Context.
    Đồng thời cung cấp tiện ích giải mã và kiểm tra hạn sử dụng Lark Access Token.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.auth.token_verifier import decode_jwt_token_payload

VIETNAM_TZ = timezone(timedelta(hours=7))


def clean_field_value(raw_value: Any) -> Any:
    """
    Chuẩn hóa giá trị từ Lark Bitable API thành kiểu dữ liệu Python cơ bản:
      - Text array: nối chuỗi văn bản thuần túy.
      - User object: lấy tên hoặc open_id người dùng.
      - Timestamp millisecond: chuyển thành chuỗi ngày giờ Việt Nam (YYYY-MM-DD HH:MM:SS).
      - Url: lấy link thuần hoặc 'text (link)'.
      - Attachment: lấy tên tệp hoặc link.
    """
    if raw_value is None:
        return None

    # Kiểu danh sách (List)
    if isinstance(raw_value, list):
        if not raw_value:
            return []

        # Trường hợp mảng chứa các đoạn văn bản: [{"type": "text", "text": "..."}]
        if all(isinstance(x, dict) and "text" in x for x in raw_value):
            return "".join(x.get("text", "") for x in raw_value)

        # Trường hợp mảng User: [{"id": "...", "name": "..."}]
        if all(isinstance(x, dict) and "name" in x for x in raw_value):
            return [x.get("name") or x.get("id") for x in raw_value]

        # Trường hợp mảng Attachment: [{"name": "file.pdf", ...}]
        if all(isinstance(x, dict) and "name" in x for x in raw_value):
            return [x.get("name") for x in raw_value]

        # Mảng string cơ bản (MultiSelect, Link IDs, ...)
        return [clean_field_value(x) for x in raw_value]

    # Kiểu từ điển (Dict)
    if isinstance(raw_value, dict):
        # Url field: {"text": "...", "link": "..."}
        if "link" in raw_value:
            text = raw_value.get("text")
            link = raw_value.get("link")
            if text and text != link:
                return f"{text} ({link})"
            return link or text

        # User field đơn lẻ
        if "name" in raw_value:
            return raw_value.get("name") or raw_value.get("id")

        # Location: {"address": "...", "pname": "..."}
        if "address" in raw_value:
            return raw_value.get("address")

        return raw_value

    # Kiểu int lớn (khả năng là Unix timestamp tính bằng mili-giây)
    # Lark Base trả về DateTime dạng mili-giây (ví dụ 1700000000000)
    if isinstance(raw_value, int) and raw_value > 1_000_000_000_000:
        try:
            dt = datetime.fromtimestamp(raw_value / 1000.0, tz=VIETNAM_TZ)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return raw_value

    return raw_value


def clean_record_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Làm sạch toàn bộ các trường trong một bản ghi Lark Base."""
    cleaned = {}
    for k, v in fields.items():
        cleaned[k] = clean_field_value(v)
    return cleaned


def inspect_bitable_token(token: str) -> Dict[str, Any]:
    """
    Kiểm tra chi tiết thông tin token Lark Bitable:
      - Trạng thái hết hạn (expired/valid)
      - Thời gian hết hạn (theo giờ Việt Nam)
      - Danh sách quyền (scopes) và kiểm tra có quyền Bitable (bitable:app) hay không
    """
    if not token:
        return {"status": "missing", "is_valid": False, "message": "Chưa có Token."}

    payload = decode_jwt_token_payload(token)
    if not payload:
        return {
            "status": "opaque_or_invalid",
            "is_valid": True,
            "message": "Token không phải JWT định dạng chuẩn hoặc là Opaque Token.",
        }

    exp = payload.get("exp")
    iat = payload.get("iat")
    scopes = payload.get("scope", "")
    now = time.time()

    is_expired = False
    remaining_sec = None
    if exp:
        remaining_sec = int(exp - now)
        is_expired = remaining_sec <= 0

    exp_dt_str = ""
    if exp:
        exp_dt = datetime.fromtimestamp(exp, tz=VIETNAM_TZ)
        exp_dt_str = exp_dt.strftime("%Y-%m-%d %H:%M:%S")

    has_bitable_scope = "bitable:app" in scopes

    return {
        "status": "expired" if is_expired else "valid",
        "is_valid": not is_expired,
        "is_expired": is_expired,
        "expires_at": exp_dt_str,
        "remaining_seconds": remaining_sec,
        "scopes": scopes,
        "has_bitable_scope": has_bitable_scope,
        "app_id": payload.get("client_id", ""),
        "user_type": payload.get("user_type", ""),
    }
