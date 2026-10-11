import os
import re
import json
import uuid
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Any, Optional, List, Union, Dict, Tuple
import httpx
from pydantic import BaseModel, Field

# Thử import settings từ core.config
try:
    from core.config import settings
    GEMINI_API_KEY = (
        getattr(settings, "GEMINI_API_KEY", "")
        or getattr(settings, "gemini_api", "")
        or os.getenv("gemini_api", "")
    )
except Exception:
    GEMINI_API_KEY = os.getenv("gemini_api", "")


class Claim(BaseModel):
    """
    Schema đại diện cho một Claim tương ứng với bảng trong PostgreSQL:
    Field               Kiểu PostgreSQL     Ý nghĩa
    id                  UUID                ID của Claim
    entity              TEXT                Đối tượng, ví dụ project_atlas
    predicate           TEXT                Thuộc tính, ví dụ deadline
    value               JSONB               Giá trị của Claim
    source_message_id   TEXT                Tin nhắn Lark tạo ra Claim
    status              TEXT                Trạng thái Claim
    superseded_by       UUID, nullable      Claim mới thay thế Claim này
    created_at          TIMESTAMPTZ         Thời điểm tạo Claim
    """
    id: UUID = Field(default_factory=uuid4, description="ID của Claim (UUID)")
    entity: str = Field(..., description="Đối tượng, ví dụ project_atlas")
    predicate: str = Field(..., description="Thuộc tính, ví dụ deadline")
    value: Any = Field(..., description="Giá trị của Claim (JSONB compatible)")
    source_message_id: Optional[str] = Field(default=None, description="Tin nhắn Lark tạo ra Claim")
    status: str = Field(default="active", description="Trạng thái Claim")
    superseded_by: Optional[UUID] = Field(default=None, description="Claim mới thay thế Claim này")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Thời điểm tạo Claim (TIMESTAMPTZ)"
    )

    def to_dict(self) -> Dict[str, Any]:
        """
        Chuyển đổi Claim sang dictionary với các kiểu dữ liệu chuẩn PostgreSQL / JSON.
        """
        return {
            "id": str(self.id),
            "entity": self.entity,
            "predicate": self.predicate,
            "value": self.value,
            "source_message_id": self.source_message_id,
            "status": self.status,
            "superseded_by": str(self.superseded_by) if self.superseded_by else None,
            "created_at": self.created_at.isoformat()
        }


class ClaimExtractor:
    """
    Utility trích xuất Claim từ request / tin nhắn bằng Gemini LLM API.
    """

    DEFAULT_MODELS = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = 30.0
    ):
        self.api_key = api_key or GEMINI_API_KEY or os.getenv("gemini_api", "")
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.timeout = timeout
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def _parse_input_request(
        self,
        request: Union[str, dict, Any],
        source_message_id: Optional[str] = None
    ) -> Tuple[str, Optional[str]]:
        """
        Phân giải request đầu vào thành (text_content, source_message_id).
        Hỗ trợ:
        - Chuỗi văn bản (str)
        - Dict (chứa keys như query, text, message, content, source_message_id, message_id)
        - Pydantic BaseModel (như ChatRequest) hoặc object có thuộc tính tương ứng
        """
        text_content = ""
        msg_id = source_message_id

        if isinstance(request, str):
            text_content = request
        elif isinstance(request, dict):
            text_content = (
                request.get("query")
                or request.get("text")
                or request.get("message")
                or request.get("content")
                or ""
            )
            if not msg_id:
                msg_id = (
                    request.get("source_message_id")
                    or request.get("message_id")
                    or request.get("msg_id")
                    or request.get("id")
                )
        elif hasattr(request, "model_dump"):
            # Pydantic v2
            data = request.model_dump()
            text_content = (
                data.get("query")
                or data.get("text")
                or data.get("message")
                or data.get("content")
                or ""
            )
            if not msg_id:
                msg_id = (
                    data.get("source_message_id")
                    or data.get("message_id")
                    or data.get("msg_id")
                )
        else:
            # Object thông thường
            text_content = (
                getattr(request, "query", None)
                or getattr(request, "text", None)
                or getattr(request, "message", None)
                or str(request)
            )
            if not msg_id:
                msg_id = (
                    getattr(request, "source_message_id", None)
                    or getattr(request, "message_id", None)
                )

        return str(text_content).strip(), str(msg_id) if msg_id else None

    def _build_prompt(self, text: str) -> str:
        """
        Xây dựng prompt chi tiết yêu cầu Gemini trích xuất Claims dưới dạng JSON có cấu trúc.
        """
        return f"""Bạn là một chuyên gia trích xuất thông tin (Claim Extraction Engine) chuyên phân tích các tin nhắn và yêu cầu trong môi trường làm việc doanh nghiệp (Lark/Feishu).

Mục tiêu của bạn:
Trích xuất tất cả các Claim (khẳng định thông tin sự thật, quyết định, thỏa thuận, cam kết, trạng thái, thuộc tính của đối tượng) từ nội dung tin nhắn được cung cấp.

Quy tắc trích xuất:
1. `entity`: Đối tượng được nhắc tới. Chuẩn hóa thành danh từ ngắn gọn, snake_case (ví dụ: `project_atlas`, `hop_dong_abc`, `server_production`, `nhan_su_nam`).
2. `predicate`: Thuộc tính, sự kiện hoặc mối quan hệ được khẳng định (ví dụ: `deadline`, `budget`, `so_dot_thanh_toan`, `status`, `owner`, `assigned_to`, `link_drive`).
3. `value`: Giá trị của thuộc tính (định dạng hợp lệ với kiểu JSONB: có thể là chuỗi ngày tháng, số, boolean, object hoặc list). Ví dụ: "2026-10-20", 500000000, true, {{"dot": 3, "tien_do": "chua_xong"}}.
4. `status`: Trạng thái của Claim trong ngữ cảnh (mặc định là "active", hoặc "proposed", "tentative", "confirmed").

Lưu ý quan trọng:
- Nếu tin nhắn KHÔNG chứa thông tin hay khẳng định nào đáng lưu trữ (ví dụ: chỉ là lời chào hỏi xã giao, cảm ơn, tán gẫu thông thường, câu hỏi không có dữ kiện mới), hãy trả về danh sách claims rỗng: `{{"claims": []}}`.
- Nếu có nhiều khẳng định về cùng một đối tượng hoặc nhiều đối tượng khác nhau, hãy tách thành các Claim riêng biệt.
- Chỉ trả về JSON thuần túy, không kèm giải thích bên ngoài.

Nội dung tin nhắn cần trích xuất:
\"\"\"{text}\"\"\"

Định dạng JSON bắt buộc:
{{
  "claims": [
    {{
      "entity": "tên đối tượng dạng snake_case",
      "predicate": "thuộc tính",
      "value": "giá trị (JSONB)",
      "status": "active"
    }}
  ]
}}"""

    def _clean_json_response(self, raw_text: str) -> str:
        """
        Làm sạch output của LLM (loại bỏ markdown block ```json ... ```).
        """
        text = raw_text.strip()
        # Loại bỏ markdown code fence nếu có
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        return text

    async def _call_gemini_api(self, prompt: str, model: str) -> str:
        """
        Gọi REST API của Gemini qua httpx async.
        """
        if not self.api_key:
            raise ValueError(
                "Thiếu Gemini API Key. Hãy cấu hình 'gemini_api' trong .env hoặc config.py."
            )

        url = f"{self.base_url}/models/{model}:generateContent"
        params = {"key": self.api_key}
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            }
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, params=params, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

            # Trích xuất nội dung phản hồi từ candidates
            candidates = data.get("candidates", [])
            if not candidates:
                raise ValueError(f"Gemini API không trả về candidate nào: {data}")

            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                raise ValueError(f"Gemini response rỗng: {data}")

            return parts[0].get("text", "")

    async def extract(
        self,
        request: Union[str, dict, Any],
        source_message_id: Optional[str] = None
    ) -> List[Claim]:
        """
        Hàm chính: Trích xuất danh sách Claims từ một request đầu vào.
        
        Args:
            request: Nội dung tin nhắn (chuỗi str), dict hoặc Request object (ChatRequest).
            source_message_id: Tùy chọn ID tin nhắn Lark (nếu chưa có trong request).
            
        Returns:
            List[Claim]: Danh sách các Claim đã được trích xuất và chuẩn hóa theo schema PostgreSQL.
        """
        text, msg_id = self._parse_input_request(request, source_message_id)
        if not text:
            return []

        prompt = self._build_prompt(text)

        # Thử với model chỉ định hoặc fallback danh sách model nếu gặp lỗi model not found
        models_to_try = [self.model_name] + [m for m in self.DEFAULT_MODELS if m != self.model_name]
        last_error = None
        raw_text = None

        for model in models_to_try:
            try:
                raw_text = await self._call_gemini_api(prompt, model)
                if raw_text:
                    break
            except httpx.HTTPStatusError as e:
                last_error = e
                # Nếu lỗi 404 (model không hỗ trợ trên version/endpoint này), thử model tiếp theo
                if e.response.status_code == 404:
                    continue
                raise
            except Exception as e:
                last_error = e
                break

        if not raw_text:
            if last_error:
                raise last_error
            return []

        # Parse JSON
        cleaned_json = self._clean_json_response(raw_text)
        try:
            parsed = json.loads(cleaned_json)
        except json.JSONDecodeError as e:
            # Fallback nếu LLM trả về text có chứa json
            match = re.search(r"(\[.*\]|\{.*\})", cleaned_json, re.DOTALL)
            if match:
                parsed = json.loads(match.group(1))
            else:
                raise ValueError(f"Không thể parse JSON từ phản hồi LLM: {cleaned_json}") from e

        # Chuẩn hóa danh sách claim items
        claim_items = []
        if isinstance(parsed, dict):
            claim_items = parsed.get("claims") or parsed.get("data") or [parsed]
        elif isinstance(parsed, list):
            claim_items = parsed

        if not isinstance(claim_items, list):
            claim_items = [claim_items]

        # Khởi tạo các đối tượng Claim
        claims: List[Claim] = []
        for item in claim_items:
            if not isinstance(item, dict):
                continue

            entity = str(item.get("entity") or "").strip()
            predicate = str(item.get("predicate") or "").strip()
            value = item.get("value")

            # Bỏ qua nếu thiếu entity hoặc predicate
            if not entity or not predicate:
                continue

            status = str(item.get("status") or "active").strip()

            claim = Claim(
                id=uuid4(),
                entity=entity,
                predicate=predicate,
                value=value,
                source_message_id=msg_id,
                status=status,
                superseded_by=None,
                created_at=datetime.now(timezone.utc)
            )
            claims.append(claim)

        return claims

    def extract_sync(
        self,
        request: Union[str, dict, Any],
        source_message_id: Optional[str] = None
    ) -> List[Claim]:
        """
        Bản đồng bộ (sync wrapper) của hàm extract phục vụ chạy trong script hoặc lab test.
        """
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run,
                    self.extract(request, source_message_id)
                ).result()
        else:
            return asyncio.run(self.extract(request, source_message_id))


# Singleton instance dùng trực tiếp
claim_extractor = ClaimExtractor()


async def extract_claims(
    request: Union[str, dict, Any],
    source_message_id: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None
) -> List[Claim]:
    """
    Hàm tiện ích trích xuất danh sách Claims từ một request đầu vào.
    
    Usage:
        claims = await extract_claims("Dự án Atlas deadline là 20/10", source_message_id="msg_123")
    """
    extractor = claim_extractor
    if api_key or model_name:
        extractor = ClaimExtractor(api_key=api_key, model_name=model_name)
    return await extractor.extract(request, source_message_id=source_message_id)


async def extract_claim(
    request: Union[str, dict, Any],
    source_message_id: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None
) -> Optional[Claim]:
    """
    Hàm tiện ích trích xuất một Claim đơn lẻ đầu tiên (nếu có).
    """
    claims = await extract_claims(
        request,
        source_message_id=source_message_id,
        api_key=api_key,
        model_name=model_name
    )
    return claims[0] if claims else None
