import os
import re
import json
import ast
import uuid
import asyncio
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Any, Optional, List, Union, Dict, Tuple
import httpx
from flashtext import KeywordProcessor
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


class ClaimSchemaValidator:
    """
    Lớp kiểm tra định dạng và schema của phản hồi LLM sử dụng kết hợp FlashText và Regex
    ngay trước khi chuyển sang bước xử lý tiếp theo.
    """
    def __init__(self):
        self.keyword_processor = KeywordProcessor()
        # Đăng ký các từ khóa bắt buộc trong schema
        self.keyword_processor.add_keyword("claims")
        self.keyword_processor.add_keyword("entity")
        self.keyword_processor.add_keyword("predicate")
        self.keyword_processor.add_keyword("value")

    def validate(self, raw_text: str) -> Tuple[bool, Optional[str]]:
        """
        Kiểm tra tính hợp lệ của raw_text:
        - Sử dụng Regex và FlashText kiểm tra sự hiện diện của các key bắt buộc (đặc biệt là 'predicate').
        - Kiểm tra cấu trúc JSON và từng claim item.
        Trả về (True, None) nếu hợp lệ, (False, error_message) nếu vi phạm.
        """
        if not raw_text or not raw_text.strip():
            return False, "Empty response received from LLM."

        text = raw_text.strip()

        # 1. Regex & FlashText: Kiểm tra key gốc 'claims'
        has_claims_key = bool(re.search(r'["\']claims["\']\s*:', text))

        if not has_claims_key and not (text.startswith("[") and text.endswith("]")):
            return False, (
                "Schema violation: Missing root key 'claims'. "
                "Expected a JSON object with format: {\"claims\": [...]}. "
                f"Received text: {text[:150]}"
            )

        # 2. Kiểm tra nếu là claims rỗng: {"claims": []}
        if re.search(r'["\']claims["\']\s*:\s*\[\s*\]', text):
            return True, None

        # 3. FlashText & Regex: Kiểm tra key bắt buộc 'predicate'
        # Nếu có dấu hiệu của claim object (ví dụ xuất hiện 'entity' hoặc '{') nhưng thiếu chữ 'predicate':
        has_predicate_key = bool(re.search(r'["\']predicate["\']\s*:', text))
        has_claim_items = bool(re.search(r'\{\s*["\'](?:entity|predicate|value)', text))

        if has_claim_items and not has_predicate_key:
            # Phát hiện LLM đã thay thế 'predicate' bằng từ khác (ví dụ: fjdfdifd, attribute, property,...)
            found_keys = re.findall(r'["\']([a-zA-Z0-9_]+)["\']\s*:', text)
            return False, (
                "CRITICAL SCHEMA VIOLATION: Missing required key 'predicate' in claim object! "
                f"You used invalid/hallucinated keys: {found_keys}. "
                "Every claim MUST have the exact key \"predicate\": \"<attribute_name>\". "
                "Do NOT use arbitrary keys or synonyms like 'attribute', 'property', or random words!"
            )

        # 4. Parse thử bằng fix_json để kiểm tra chi tiết từng claim item
        try:
            parsed = fix_json(text)
        except Exception as e:
            return False, f"JSON Parsing Error: {str(e)}"

        if not isinstance(parsed, (dict, list)):
            return False, f"Output is not a JSON object or array. Got: {type(parsed).__name__}"

        claims_list = parsed.get("claims") if isinstance(parsed, dict) else parsed
        if not isinstance(claims_list, list):
            return False, f"The 'claims' field must be a JSON array, got: {type(claims_list).__name__}"

        # Kiểm tra chi tiết từng claim trong array
        for idx, item in enumerate(claims_list):
            if not isinstance(item, dict):
                return False, f"Claim at index {idx} is not a JSON object: {item}"

            # Kiểm tra bắt buộc có 'predicate'
            if "predicate" not in item:
                keys_found = list(item.keys())
                return False, (
                    f"Claim at index {idx} is missing the required key 'predicate'! "
                    f"Found keys: {keys_found}. "
                    "You MUST use 'predicate' for the property/attribute name (e.g. \"predicate\": \"deadline\")."
                )

            # Kiểm tra bắt buộc có 'entity'
            if "entity" not in item:
                return False, f"Claim at index {idx} is missing the required key 'entity'!"

            # Kiểm tra bắt buộc có 'value'
            if "value" not in item:
                return False, f"Claim at index {idx} is missing the required key 'value'!"

            # Kiểm tra giá trị entity và predicate không được rỗng
            if not str(item.get("entity", "")).strip():
                return False, f"Claim at index {idx} has an empty 'entity' value."
            if not str(item.get("predicate", "")).strip():
                return False, f"Claim at index {idx} has an empty 'predicate' value."

        return True, None


class ClaimExtractor:
    """
    Utility trích xuất Claim từ request / tin nhắn bằng Gemini LLM API,
    tích hợp:
    - Prompt siết chặt định dạng JSON.
    - Lớp kiểm tra Regex & FlashText xác thực schema.
    - Cơ chế feedback LLM tự sửa lỗi tối đa 2 lần.
    - Xử lý RateLimit và Cooldown (Exponential Backoff).
    """

    DEFAULT_MODELS = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = 30.0,
        max_fix_attempts: int = 2,
        rate_limit_retries: int = 3,
        cooldown_seconds: float = 2.0
    ):
        self.api_key = api_key or GEMINI_API_KEY or os.getenv("gemini_api", "")
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.timeout = timeout
        self.max_fix_attempts = max_fix_attempts
        self.rate_limit_retries = rate_limit_retries
        self.cooldown_seconds = cooldown_seconds
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self.validator = ClaimSchemaValidator()
        self.last_call_usage: Dict[str, int] = {}
        self.last_metrics: Dict[str, Any] = {}

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
        Build a strictly constrained prompt instructing Gemini to extract claims in exact JSON format.
        """
        return f"""You are a specialized, deterministic Claim Extraction Engine for enterprise communication messages (Lark/Feishu).

Your strict task:
Extract atomic factual assertions (Claims) from the message into a JSON structure matching the EXACT schema specified below.

STRICT SCHEMA RULES:
1. Root element MUST be a JSON object with a single key: "claims".
2. "claims" MUST be an array of JSON objects. If no claims are found, return: {{"claims": []}}.
3. EVERY object in "claims" MUST contain EXACTLY these four keys:
   - "entity": (string, lower snake_case) The subject or target entity (e.g., "project_atlas", "contract_abc").
   - "predicate": (string, lower snake_case) The property, event, or attribute asserted (e.g., "deadline", "budget", "status").
     CRITICAL REQUIREMENT: You MUST use the exact key name "predicate". NEVER replace it with "attribute", "property", "relation", "field", or any random/hallucinated word!
   - "value": (JSONB compatible) The value of the predicate. Can be string ("2026-10-20"), number (500000000), boolean (true), object, or array.
   - "status": (string) The status of the claim (e.g., "active", "proposed", "confirmed"). Default to "active".

NON-CLAIM FILTER:
- If the message is chit-chat, greetings, polite thanks, or vague remarks with no concrete assertions, return {{"claims": []}}.

OUTPUT CONSTRAINT:
- Output ONLY pure, valid JSON. Do not include markdown code fences (```), commentary, or any text before or after the JSON.

Message to analyze:
\"\"\"{text}\"\"\"

Required JSON output format:
{{
  "claims": [
    {{
      "entity": "project_atlas",
      "predicate": "deadline",
      "value": "2026-10-20",
      "status": "active"
    }}
  ]
}}"""

    def _build_fix_prompt(
        self,
        original_text: str,
        wrong_output: str,
        error_msg: str,
        attempt: int
    ) -> str:
        """
        Build a targeted feedback prompt demanding LLM to fix its schema violations.
        """
        return f"""CRITICAL VALIDATION FAILURE! Your previous response violated the strict schema rules.

VALIDATION ERROR:
{error_msg}

YOUR INVALID OUTPUT:
\"\"\"{wrong_output}\"\"\"

ORIGINAL MESSAGE:
\"\"\"{original_text}\"\"\"

CORRECTION INSTRUCTIONS (Fix Attempt {attempt} of {self.max_fix_attempts}):
1. Fix the error above immediately.
2. The key "predicate" MUST be used for the property name in every claim object. DO NOT replace "predicate" with random characters or any other key.
3. The root JSON object must contain {{"claims": [...]}}.
4. Return ONLY the corrected, valid JSON. No conversational text, no markdown fences.

Corrected JSON:"""

    def _clean_json_response(self, raw_text: str) -> str:
        """
        Làm sạch output của LLM (loại bỏ markdown block ```json ... ```).
        """
        text = raw_text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        return text

    async def _call_gemini_api(
        self,
        prompt: str,
        model: str,
        max_rate_limit_retries: Optional[int] = None,
        initial_backoff: Optional[float] = None
    ) -> str:
        """
        Gọi REST API của Gemini qua httpx async.
        Tích hợp try-except xử lý RateLimit (429) và Cooldown (503) với Exponential Backoff.
        """
        if not self.api_key:
            raise ValueError(
                "Thiếu Gemini API Key. Hãy cấu hình 'gemini_api' trong .env hoặc config.py."
            )

        retries = max_rate_limit_retries if max_rate_limit_retries is not None else self.rate_limit_retries
        backoff = initial_backoff if initial_backoff is not None else self.cooldown_seconds

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

        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, params=params, headers=headers, json=payload)

                    # 1. Bắt RateLimit (429) hoặc Server Overloaded / Cooldown (503)
                    if response.status_code in (429, 503):
                        if attempt < retries:
                            retry_after_str = response.headers.get("retry-after")
                            try:
                                wait_time = float(retry_after_str) if retry_after_str else backoff
                            except (ValueError, TypeError):
                                wait_time = backoff

                            # Cooldown chờ LLM hồi phục
                            await asyncio.sleep(wait_time)
                            backoff *= 2.0  # Exponential backoff
                            continue
                        else:
                            response.raise_for_status()

                    response.raise_for_status()
                    data = response.json()

                    candidates = data.get("candidates", [])
                    if not candidates:
                        raise ValueError(f"Gemini API không trả về candidate nào: {data}")

                    parts = candidates[0].get("content", {}).get("parts", [])
                    if not parts:
                        raise ValueError(f"Gemini response rỗng: {data}")

                    # Trích xuất và lưu usageMetadata từ Gemini
                    usage = data.get("usageMetadata", {})
                    self.last_call_usage = {
                        "prompt_tokens": usage.get("promptTokenCount", 0),
                        "candidates_tokens": usage.get("candidatesTokenCount", 0),
                        "total_tokens": usage.get("totalTokenCount", 0),
                    }

                    return parts[0].get("text", "")

            except httpx.HTTPStatusError as e:
                # Nếu 429 hoặc 503 bị văng ra từ raise_for_status
                if e.response.status_code in (429, 503) and attempt < retries:
                    retry_after_str = e.response.headers.get("retry-after")
                    try:
                        wait_time = float(retry_after_str) if retry_after_str else backoff
                    except (ValueError, TypeError):
                        wait_time = backoff

                    await asyncio.sleep(wait_time)
                    backoff *= 2.0
                    continue
                raise
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
                # Lỗi mạng tạm thời hoặc timeout kết nối -> cooldown và retry
                if attempt < retries:
                    await asyncio.sleep(backoff)
                    backoff *= 2.0
                    continue
                raise

        raise RuntimeError("Vượt quá số lần retry cho Gemini API.")

    async def extract(
        self,
        request: Union[str, dict, Any],
        source_message_id: Optional[str] = None,
        save_to_db: bool = True
    ) -> List[Claim]:
        """
        Hàm chính: Trích xuất danh sách Claims từ một request đầu vào.
        
        Quy trình xử lý:
        1. Phân giải text và message id.
        2. Gọi LLM với prompt siết chặt schema.
        3. Kiểm tra kết quả qua lớp Regex / FlashText (SchemaValidator).
        4. Nếu vi phạm, gửi lại LLM yêu cầu sửa lỗi kèm mô tả chi tiết (tối đa 2 lần fix).
        5. Parse và chuẩn hóa JSON kết quả thành danh sách Claim chuẩn PostgreSQL.
        """
        text, msg_id = self._parse_input_request(request, source_message_id)
        if not text:
            return []

        prompt = self._build_prompt(text)

        # Thử với model chỉ định hoặc fallback danh sách model nếu gặp lỗi model not found
        models_to_try = [self.model_name] + [m for m in self.DEFAULT_MODELS if m != self.model_name]
        last_error = None
        parsed = None
        start_time = asyncio.get_event_loop().time()
        total_prompt_tokens = 0
        total_candidates_tokens = 0
        fix_count = 0

        for model in models_to_try:
            try:
                # Bước 1: Gọi LLM ban đầu
                current_raw = await self._call_gemini_api(prompt, model)
                total_prompt_tokens += self.last_call_usage.get("prompt_tokens", 0)
                total_candidates_tokens += self.last_call_usage.get("candidates_tokens", 0)

                # Bước 2: Lớp kiểm tra Regex / FlashText & Tự sửa lỗi (Fix tối đa 2 lần)
                for fix_idx in range(self.max_fix_attempts + 1):
                    is_valid, validation_error = self.validator.validate(current_raw)
                    if is_valid:
                        break

                    # Nếu bị lỗi và còn lượt sửa (tối đa 2 lần fix)
                    if fix_idx < self.max_fix_attempts:
                        fix_count += 1
                        fix_prompt = self._build_fix_prompt(
                            original_text=text,
                            wrong_output=current_raw,
                            error_msg=validation_error,
                            attempt=fix_idx + 1
                        )
                        current_raw = await self._call_gemini_api(fix_prompt, model)
                        total_prompt_tokens += self.last_call_usage.get("prompt_tokens", 0)
                        total_candidates_tokens += self.last_call_usage.get("candidates_tokens", 0)
                    else:
                        # Hết lượt sửa lỗi, tiếp tục qua fix_json thử vớt vát
                        pass

                # Bước 3: Parse và sửa JSON
                parsed = fix_json(current_raw)
                if parsed is not None:
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

        if parsed is None:
            if last_error:
                raise last_error
            return []

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

        # Tự động lưu trực tiếp vào CSDL claim.db nếu save_to_db=True
        if save_to_db and claims:
            self.save_claims_to_db(claims)

        # Cập nhật metrics cuối cùng cho lần trích xuất này
        latency = asyncio.get_event_loop().time() - start_time
        self.last_metrics = {
            "prompt_tokens": total_prompt_tokens,
            "candidates_tokens": total_candidates_tokens,
            "total_tokens": total_prompt_tokens + total_candidates_tokens,
            "fix_attempts": fix_count,
            "latency": latency,
        }

        return claims

    def save_claims_to_db(self, claims: List[Claim]) -> int:
        """
        Lưu danh sách Claims trực tiếp vào SQLite database claim.db.
        """
        try:
            from database.db import save_claims
            return save_claims(claims)
        except Exception:
            try:
                from server.database.db import save_claims
                return save_claims(claims)
            except Exception as e:
                print(f"⚠️ Cảnh báo: Không thể lưu claim vào claim.db: {e}")
                return 0

    def extract_sync(
        self,
        request: Union[str, dict, Any],
        source_message_id: Optional[str] = None,
        save_to_db: bool = True
    ) -> List[Claim]:
        """
        Bản đồng bộ (sync wrapper) của hàm extract phục vụ chạy trong script hoặc lab test.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run,
                    self.extract(request, source_message_id, save_to_db=save_to_db)
                ).result()
        else:
            return asyncio.run(self.extract(request, source_message_id, save_to_db=save_to_db))


# Singleton instance dùng trực tiếp
claim_extractor = ClaimExtractor()


async def extract_claims(
    request: Union[str, dict, Any],
    source_message_id: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    save_to_db: bool = True
) -> List[Claim]:
    """
    Hàm tiện ích trích xuất danh sách Claims từ một request đầu vào và tự động lưu vào claim.db.
    
    Usage:
        claims = await extract_claims("Dự án Atlas deadline là 20/10", source_message_id="msg_123")
    """
    extractor = claim_extractor
    if api_key or model_name:
        extractor = ClaimExtractor(api_key=api_key, model_name=model_name)
    return await extractor.extract(
        request,
        source_message_id=source_message_id,
        save_to_db=save_to_db
    )


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


def validate_claim_schema(raw_text: str) -> Tuple[bool, Optional[str]]:
    """
    Hàm tiện ích kiểm tra schema phản hồi từ LLM bằng Regex & FlashText.
    """
    validator = ClaimSchemaValidator()
    return validator.validate(raw_text)


def _auto_close_json(s: str) -> str:
    """
    Cân bằng và tự động đóng các dấu ngoặc { }, [ ] còn thiếu nếu chuỗi JSON bị cắt ngắn (truncated).
    """
    stack = []
    in_string = False
    escape = False

    for char in s:
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if not in_string:
            if char == "{":
                stack.append("}")
            elif char == "[":
                stack.append("]")
            elif char in ("}", "]"):
                if stack and stack[-1] == char:
                    stack.pop()

    res = s
    if in_string:
        res += '"'
    # Bỏ dấu phẩy thừa ở cuối trước khi đóng ngoặc
    res = re.sub(r",\s*$", "", res)
    while stack:
        res += stack.pop()
    return res


def fix_json(raw_text: str) -> Union[Dict[str, Any], List[Any], Any]:
    """
    Sửa lỗi và parse chuỗi JSON bị lỗi hoặc malformed từ phản hồi LLM.
    
    Hỗ trợ xử lý:
    1. Loại bỏ markdown code blocks (```json ... ```).
    2. Tách phần JSON ra khỏi văn bản đệm/hội thoại của LLM.
    3. Xóa comment (// hoặc /* */).
    4. Sửa trailing commas (dấu phẩy thừa trước dấu đóng ngoặc).
    5. Chuyển đổi hằng số Python (True, False, None) thành JSON (true, false, null).
    6. Tự động đóng các dấu ngoặc nhọn/vuông nếu JSON bị cắt ngắn (truncated).
    7. Fallback an toàn qua ast.literal_eval đối với cú pháp Python dictionary/list.
    """
    if not raw_text or not isinstance(raw_text, str):
        return {}

    text = raw_text.strip()

    # 1. Loại bỏ markdown code fence nếu có
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    # 2. Thử parse trực tiếp
    try:
        return json.loads(text)
    except Exception:
        pass

    # 3. Trích xuất substring giữa dấu mở và đóng ngoặc đầu/cuối
    start_brace = text.find("{")
    start_bracket = text.find("[")

    if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
        start_idx = start_brace
        end_idx = text.rfind("}")
    elif start_bracket != -1:
        start_idx = start_bracket
        end_idx = text.rfind("]")
    else:
        start_idx = -1
        end_idx = -1

    if start_idx != -1:
        if end_idx != -1 and end_idx >= start_idx:
            text = text[start_idx : end_idx + 1].strip()
        else:
            text = text[start_idx:].strip()

    # 4. Thử parse lại sau khi trích xuất
    try:
        return json.loads(text)
    except Exception:
        pass

    # 5. Fallback qua ast.literal_eval (hiệu quả khi LLM trả về single quotes hoặc Python dict)
    try:
        evaluated = ast.literal_eval(text)
        if isinstance(evaluated, (dict, list)):
            return evaluated
    except Exception:
        pass

    # 6. Sửa lỗi cú pháp chuỗi JSON
    cleaned = text

    # Xóa comment 1 dòng //...
    cleaned = re.sub(r"//.*$", "", cleaned, flags=re.MULTILINE)
    # Xóa comment nhiều dòng /*...*/
    cleaned = re.sub(r"/\*[\s\S]*?\*/", "", cleaned)

    # Thay thế True, False, None -> true, false, null
    cleaned = re.sub(r"\bTrue\b", "true", cleaned)
    cleaned = re.sub(r"\bFalse\b", "false", cleaned)
    cleaned = re.sub(r"\bNone\b", "null", cleaned)

    # Xóa trailing commas: ,} -> } hoặc ,] -> ]
    cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)

    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # 7. Thay thế single quote thành double quote cho key và string
    sq_replaced = re.sub(r"(?<!\\)'", '"', cleaned)
    sq_replaced = re.sub(r",\s*([\]}])", r"\1", sq_replaced)
    try:
        return json.loads(sq_replaced)
    except Exception:
        pass

    # 8. Tự động đóng các dấu ngoặc nếu JSON bị cắt ngắn (incomplete/truncated)
    repaired = _auto_close_json(cleaned)
    try:
        return json.loads(repaired)
    except Exception:
        pass

    repaired_sq = _auto_close_json(sq_replaced)
    try:
        return json.loads(repaired_sq)
    except Exception:
        pass

    # 9. Fallback ast.literal_eval trên bản repaired
    try:
        evaluated = ast.literal_eval(repaired)
        if isinstance(evaluated, (dict, list)):
            return evaluated
    except Exception:
        pass

    raise ValueError(f"Không thể parse hoặc sửa JSON từ chuỗi: {raw_text[:200]}")
