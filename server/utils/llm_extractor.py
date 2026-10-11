"""
LLM Extractor Module for HiLark
================================
Tiện ích sử dụng LLM để phân tích và bóc tách một truy vấn/tin nhắn đầu vào thành 2 nhánh:
  - Nhánh 1: Memory (Thực thể chuẩn, nhận diện thực thể, đồng bộ danh tính)
  - Nhánh 2: Claim (Mệnh đề thông tin động, kiểm chứng nguồn gốc, audit trail và lịch sử thay đổi)

Mục tiêu cốt lõi của 2 collections:
  1. Entities (Memory):
     ent_001 — Dự án Atlas: Tên chuẩn + aliases + mô tả ngữ cảnh.
     * Quy tắc: Chỉ tạo entity mới khi không tìm được entity phù hợp. Tên gần giống chưa đủ để merge.
  2. Claims:
     Trả lời: "Thông tin gì đã được nói, áp dụng cho entity nào, còn hiệu lực không và lấy từ đâu?"
     * Quy tắc: Thông tin mới thay thế thông tin cũ -> claim cũ thành superseded, claim mới liên kết bằng supersedes.
     * Mơ hồ hoặc mâu thuẫn: Lưu trạng thái uncertain hoặc conflicted; không tự chọn một entity/giá trị chỉ vì LLM tự tin.
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import httpx
from pydantic import BaseModel, Field

# Đảm bảo đường dẫn import server modules
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_ROOT = os.path.dirname(CURRENT_DIR)
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from core.config import settings


# ==============================================================================
# 1. ENUMS & SCHEMAS (IMPORTED FROM MODELS)
# ==============================================================================

from models.memory import (
    EntityStatus,
    ClaimStatus,
    MemoryEntity,
    Claim,
)


# ==============================================================================
# 2. HELPER FUNCTIONS: ID GENERATION & STRING CLEANING
# ==============================================================================

def generate_stable_entity_id(workspace_id: str, canonical_name: str) -> str:
    """
    Tạo ID ổn định do Python sinh ra (Deterministic ID dựa trên uuid5).
    Đảm bảo cùng một thực thể trong cùng một workspace sẽ luôn có _id đồng nhất.
    """
    clean_name = re.sub(r"\s+", " ", canonical_name.strip().lower())
    clean_ws = workspace_id.strip().lower()
    seed = f"{clean_ws}:{clean_name}"
    stable_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, seed)
    return f"ent_{stable_uuid.hex[:12]}"


def generate_claim_id() -> str:
    """Tạo ID cho claim mới (clm_xxxx)."""
    return f"clm_{uuid.uuid4().hex[:8]}"


def clean_json_text(text: str) -> str:
    """Loại bỏ markdown code blocks (```json ... ```) để parse JSON thuần."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    return text.strip()


def safe_parse_json_list(raw_text: str, fallback_type: str = "items") -> List[Dict[str, Any]]:
    """
    Parse an toàn JSON trả về từ LLM thành danh sách các dictionary:
      - Bóc markdown block ```json ... ```
      - Thử parse JSON trực tiếp (list hoặc dict)
      - Fallback regex quét tìm mảng [...] hoặc đối tượng {...}
      - Tuyệt đối không ném ngoại lệ làm crash server (Graceful Degradation).
    """
    if not raw_text or not isinstance(raw_text, str):
        return []

    cleaned = clean_json_text(raw_text)
    if not cleaned:
        return []

    # 1. Thử parse trực tiếp
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass

    # 2. Fallback regex tìm mảng [...]
    array_match = re.search(r"\[\s*\{.*?\}\s*\]", cleaned, re.DOTALL)
    if array_match:
        try:
            data = json.loads(array_match.group(0))
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass

    # 3. Fallback regex tìm đối tượng đơn lẻ {...}
    obj_match = re.search(r"\{.*?\}", cleaned, re.DOTALL)
    if obj_match:
        try:
            data = json.loads(obj_match.group(0))
            if isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            pass

    print(f"[CẢNH BÁO] Không thể parse JSON từ phản hồi LLM cho {fallback_type}. Nội dung: {raw_text[:200]}")
    return []


def normalize_predicate(predicate: str) -> str:
    """Chuẩn hoá predicate về dạng chữ thường, snake_case đơn giản."""
    p = predicate.strip().lower()
    p = re.sub(r"[^\w\s]", "", p)
    p = re.sub(r"\s+", "_", p)
    return p

# ==============================================================================
# 3. PROMPT TEMPLATES (NHÁNH 1 & NHÁNH 2)
# ==============================================================================

MEMORY_EXTRACTION_PROMPT = """\
Bạn là chuyên gia phân tích thực thể (Named Entity Recognition & Entity Resolution).
Nhiệm vụ của bạn là đọc đoạn văn bản/truy vấn đầu vào và trích xuất CÁC THỰC THỂ CỐT LÕI (core entities) có giá trị nghiệp vụ dài hạn.

VĂN BẢN ĐẦU VÀO:
\"\"\"{query}\"\"\"

{context_existing_entities}

QUY TẮC BẮT BUỘC (TUÂN THỦ NGHIÊM NGẶT ĐỂ TRÁNH DỮ LIỆU RÁC):
1. "canonical_name": Tên chuẩn xác, ngắn gọn của thực thể.
2. "entity_type": Chỉ chọn 1 trong các nhóm nghiệp vụ chính:
   - "project": Dự án, sản phẩm (HiLark, Atlas...)
   - "feature": Tính năng cụ thể thuộc sản phẩm/dự án (Tính năng xóa giỏ hàng, Thanh toán QR...)
   - "team": Phòng ban, nhóm làm việc cụ thể (Tech Team, Ban Giám đốc...)
   - "customer": Doanh nghiệp khách hàng, đối tác (LarkTech, Khách hàng A...)
   - "person": Nhân sự cụ thể có tên hoặc vai trò rõ ràng (Tuấn PM, Anh Long Techlead...)
   - "document": Hợp đồng, tài liệu, quy trình quan trọng.
3. "aliases": Các tên gọi khác, viết tắt có bằng chứng rõ ràng trong văn bản.
4. "description": Tóm tắt 1 câu ngắn gọn về vai trò/vị trí của thực thể.

⛔ BLACKLIST - TUYỆT ĐỐI KHÔNG TẠO ENTITY CHO CÁC TRƯỜNG HỢP SAU:
- CẤM TẠO ENTITY TỪ ĐẠI TỪ NHÂN XƯNG: "anh", "em", "các bạn", "bên mình", "tôi", "người ta", "khách" (nếu chỉ là đại từ chung). Chúng không mang danh tính tri thức!
- CẤM TẠO ENTITY TỪ MỐC THỜI GIAN: "ngày 18", "ngày 30", "năm sau", "hôm nay". Mốc thời gian là Giá trị (Value) của Deadline, KHÔNG PHẢI là Entity!

⚠️ QUY TẮC ĐỐI TƯỢNG MỚI (NEW INSTANCE):
- Khi văn bản nói: "một khách mới", "khách khác", "dự án mới", "hợp đồng mới" -> BẮT BUỘC tạo thực thể mới với tên rõ ràng (ví dụ: "Khách hàng mới (Ký hợp đồng năm sau)"), TUYỆT ĐỐI KHÔNG merge vào các thực thể danh từ chung cũ như "Khách hàng".

Chỉ trả về JSON Array hợp lệ (tối đa 1-3 thực thể cốt lõi nhất):
[
  {{
    "canonical_name": "Atlas",
    "entity_type": "project",
    "aliases": ["Dự án Atlas"],
    "description": "Dự án phát triển phần mềm.",
    "attributes": {{}}
  }}
]
"""


CLAIM_EXTRACTION_PROMPT = """\
Bạn là chuyên gia thẩm định và trích xuất mệnh đề thông tin (Fact & Claim Extraction).
Mục tiêu của bạn là trả lời:
"Thông tin gì đã được nói, áp dụng cho entity nào, còn hiệu lực không và lấy từ đâu?"

VĂN BẢN ĐẦU VÀO:
\"\"\"{query}\"\"\"

DANH SÁCH THỰC THỂ ĐÃ XÁC ĐỊNH (ENTITIES):
{entities_json}

DANH SÁCH CÁC CLAIMS HIỆN CÓ ĐANG CÓ HIỆU LỰC (CURRENT CLAIMS TRONG BỘ NHỚ):
{existing_claims_json}

THÔNG TIN NGUỒN:
- Message ID: {source_message_id}
- Sender: {sender}

QUY TẮC TRÍCH XUẤT CLAIMS (BẮT BUỘC TUÂN THỦ NGHIÊM NGẶT):
1. "entity_id": BẮT BUỘC trỏ chính xác đến trường "_id" của một entity trong DANH SÁCH THỰC THỂ ở trên.
2. "predicate": CHỈ TRÍCH XUẤT CÁC THUỘC TÍNH NGHIỆP VỤ CỐT LÕI (CORE BUSINESS FACTS):
   - "deadline": Hạn chót, ngày giao hàng, thời điểm hoàn thành (ví dụ value: "30/10", "năm sau").
   - "owner" / "assignee": Người/nhóm chịu trách nhiệm (ví dụ value: "Tuấn PM").
   - "status": Trạng thái công việc/dự án/hợp đồng (ví dụ value: "signed", "in_progress", "resigned").
   - "scope" / "requirement": Yêu cầu tính năng hoặc phạm vi công việc.
   - "budget": Ngân sách, chi phí.

⛔ BLACKLIST - TUYỆT ĐỐI KHÔNG BÓC TÁCH CÁC MỆNH ĐỀ GIAO TIẾP VỤN VẶT (CHATTER):
- CẤM tạo các predicate giao tiếp đời thường như: "action", "chat", "message", "sent_message", "received_message", "urging_deadline", "báo lại", "nhắn tin". Hệ thống chỉ lưu tri thức nghiệp vụ, không lưu nhật ký hành vi nhắn tin!

🎯 QUY TẮC CÔ ĐỌNG & XẾP HẠNG OUTPUT (STRICT OUTPUT CONTROL & RANKING):
- Số lượng: Mỗi tin nhắn CHỈ ĐƯỢC sinh tối đa từ 1 đến 3 claims cô đọng nhất.
- Thứ tự ưu tiên: Sắp xếp mảng claims theo thứ tự giảm dần theo mức độ quan trọng nghiệp vụ (claim quan trọng nhất đứng đầu tiên).
- Phân loại giá trị: Ưu tiên bóc tách các sự kiện hoặc thuộc tính then chốt (deadline, status, owner/assignee, scope, budget, milestones).
- KHÔNG phân mảnh thuộc tính: Cùng 1 sự việc chỉ tạo 1 claim duy nhất, không chia nhỏ thành nhiều predicate gây nhiễu.

3. "value": Giá trị cực kỳ ngắn gọn, cô đọng (TỐI ĐA 10 TỪ / DƯỚI 20 TOKENS).
   - Ví dụ hợp lệ: "30/10", "signed", "resigned", "Tuấn PM", "200M VND".
   - TUYỆT ĐỐI KHÔNG copy cả câu hoặc đoạn văn dài vào "value" (trích dẫn nguyên văn câu thì để ở trường "source_snippet").
4. "status":
   - "current": Thông tin mới được khẳng định rõ ràng và có hiệu lực.
   - "superseded": Thông tin cũ đã bị thay thế.
   - "conflicted": Khi có mâu thuẫn trực tiếp giữa các nguồn.
   - "uncertain": Khi thông tin mơ hồ, phỏng đoán, chưa chốt ("hình như", "có thể", "khoảng", "nghe nói", "dự kiến").
5. "source_snippet": Trích dẫn nguyên văn câu văn bản làm chứng cứ.
6. "supersedes": Nếu thông tin mới này THAY THẾ một claim cũ (cùng entity_id và cùng thuộc tính, ví dụ đổi deadline từ 18/10 thành 30/10), hãy điền chính xác "_id" của claim cũ đó (ví dụ "clm_001"). Nếu không thay thế claim nào, để null.

Chỉ trả về JSON Array các claims hợp lệ theo thứ tự ưu tiên (tối đa 1-3 claims cốt lõi):
[
  {{
    "entity_id": "ent_...",
    "predicate": "deadline",
    "value": "30/10",
    "status": "current",
    "source_snippet": "dời từ ngày 18 sang ngày 30 nhé",
    "supersedes": "clm_000"
  }}
]
"""


# ==============================================================================
# 4. LLM API CLIENT (GEMINI VIA HTTPX)
# ==============================================================================

class GeminiClient:
    """Client giao tiếp với Gemini REST API sử dụng httpx."""

    DEFAULT_MODELS = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash"]

    def __init__(self, api_key: Optional[str] = None):
        # Lưu key nếu có, nếu chưa có thì lúc generate mới kiểm tra để tránh crash lúc import module (Issue 2)
        self.api_key = api_key or getattr(settings, "GEMINI_API_KEY", None) or getattr(settings, "gemini_api", None)

    def _ensure_api_key(self) -> str:
        """Lazy validation: chỉ raise error khi thực sự cần gọi Gemini API."""
        key = self.api_key or getattr(settings, "GEMINI_API_KEY", None) or getattr(settings, "gemini_api", None)
        if not key:
            raise ValueError("Chưa tìm thấy GEMINI_API_KEY trong cấu hình hoặc file .env (key: gemini_api).")
        return key

    def _get_url(self, model_name: str) -> str:
        key = self._ensure_api_key()
        return f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"

    def generate(self, prompt: str, model_name: Optional[str] = None) -> str:
        """Gọi Gemini API đồng bộ (sync)."""
        models_to_try = [model_name] if model_name else self.DEFAULT_MODELS
        last_error = None

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "maxOutputTokens": 800,
            },
        }

        with httpx.Client(timeout=45.0) as client:
            for model in models_to_try:
                url = self._get_url(model)
                try:
                    resp = client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            finish_reason = candidates[0].get("finishReason")
                            if finish_reason == "SAFETY":
                                last_error = f"Gemini model {model} đã chặn câu trả lời do bộ lọc an toàn (finishReason: SAFETY)."
                                continue
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                return parts[0].get("text", "")

                        # Kiểm tra safety filter ở promptFeedback
                        prompt_fb = data.get("promptFeedback", {})
                        if prompt_fb.get("blockReason"):
                            last_error = f"Gemini prompt bị chặn bởi Safety Filter ({prompt_fb.get('blockReason')})."
                            continue

                        last_error = f"Gemini model {model} trả về 200 nhưng không có parts text hợp lệ."
                    elif resp.status_code == 429:
                        last_error = f"Gemini Rate Limit / Quota Exceeded (HTTP 429) ở model {model}."
                        continue
                    elif resp.status_code == 404:
                        continue
                    else:
                        last_error = f"HTTP {resp.status_code}: {resp.text}"
                except Exception as e:
                    last_error = str(e)

        raise RuntimeError(f"Không thể gọi Gemini API sau khi thử các models. Chi tiết: {last_error}")

    async def generate_async(self, prompt: str, model_name: Optional[str] = None) -> str:
        """Gọi Gemini API bất đồng bộ (async)."""
        models_to_try = [model_name] if model_name else self.DEFAULT_MODELS
        last_error = None

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "maxOutputTokens": 800,
            },
        }

        async with httpx.AsyncClient(timeout=45.0) as client:
            for model in models_to_try:
                url = self._get_url(model)
                try:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            finish_reason = candidates[0].get("finishReason")
                            if finish_reason == "SAFETY":
                                last_error = f"Gemini model {model} đã chặn câu trả lời do bộ lọc an toàn (finishReason: SAFETY)."
                                continue
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                return parts[0].get("text", "")

                        prompt_fb = data.get("promptFeedback", {})
                        if prompt_fb.get("blockReason"):
                            last_error = f"Gemini prompt bị chặn bởi Safety Filter ({prompt_fb.get('blockReason')})."
                            continue

                        last_error = f"Gemini model {model} trả về 200 nhưng không có parts text hợp lệ."
                    elif resp.status_code == 429:
                        last_error = f"Gemini Rate Limit / Quota Exceeded (HTTP 429) ở model {model}."
                        continue
                    elif resp.status_code == 404:
                        continue
                    else:
                        last_error = f"HTTP {resp.status_code}: {resp.text}"
                except Exception as e:
                    last_error = str(e)

        raise RuntimeError(f"Không thể gọi Gemini API (async). Chi tiết: {last_error}")


# ==============================================================================
# 5. ENTITY MATCHING & RESOLUTION (QUY TẮC 1: KHÔNG MERGE TÙY TIỆN)
# ==============================================================================

def find_matching_entity(
    candidate_name: str,
    candidate_aliases: List[str],
    existing_entities: List[Union[MemoryEntity, Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """
    Tìm entity phù hợp từ danh sách entities đã có.
    Quy tắc 1:
      - Chỉ merge khi trùng chính xác canonical_name hoặc trùng một alias đã được ghi nhận.
      - Tên gần giống nhau (như 'Dự án Alpha' vs 'Dự án Atlas') KHÔNG ĐƯỢC MERGE.
    """
    cand_norm = re.sub(r"\s+", " ", candidate_name.strip().lower())
    cand_alias_norms = {re.sub(r"\s+", " ", a.strip().lower()) for a in candidate_aliases if a.strip()}

    for ent in existing_entities:
        ent_dict = ent.to_dict() if isinstance(ent, MemoryEntity) else ent
        c_name = re.sub(r"\s+", " ", str(ent_dict.get("canonical_name", "")).strip().lower())
        e_aliases = {
            re.sub(r"\s+", " ", str(a).strip().lower())
            for a in ent_dict.get("aliases", [])
            if str(a).strip()
        }

        # 1. Trùng canonical_name
        if cand_norm and cand_norm == c_name:
            return ent_dict

        # 2. Tên ứng viên nằm trong aliases của entity đã có
        if cand_norm and cand_norm in e_aliases:
            return ent_dict

        # 3. Một alias của ứng viên trùng với canonical_name của entity đã có
        if c_name and c_name in cand_alias_norms:
            return ent_dict

        # 4. Trùng khớp alias có bằng chứng
        if cand_alias_norms and (cand_alias_norms & e_aliases):
            return ent_dict

    return None


# ==============================================================================
# 6. CORE LOGIC: NHÁNH 1 (MEMORY)
# ==============================================================================

def parse_memory_entities(
    raw_response: str,
    workspace_id: str = "default",
    source_message_id: Optional[str] = None,
    existing_entities: Optional[List[Union[MemoryEntity, Dict[str, Any]]]] = None,
) -> List[MemoryEntity]:
    """Parse JSON trả về từ LLM và chuyển đổi thành MemoryEntity."""
    data = safe_parse_json_list(raw_response, fallback_type="Memory Entities")
    if not data:
        return []

    message_ids = [source_message_id] if source_message_id else []
    existing = existing_entities or []
    entities: List[MemoryEntity] = []

    for item in data:
        if not isinstance(item, dict):
            continue

        canonical_name = str(item.get("canonical_name", "")).strip()
        if not canonical_name:
            continue

        entity_type = str(item.get("entity_type", "entity")).strip().lower()
        aliases = [str(a).strip() for a in item.get("aliases", []) if str(a).strip()]
        description = str(item.get("description", "")).strip()
        attributes = item.get("attributes", {})
        if not isinstance(attributes, dict):
            attributes = {"raw_value": attributes}

        # Kiểm tra xem có match với entity đã có không
        matched = find_matching_entity(canonical_name, aliases, existing)
        if matched:
            # Tái sử dụng ID ổn định đã có
            entity_id = matched.get("_id") or matched.get("id")
            # Gộp aliases (không trùng lặp)
            merged_aliases = list(dict.fromkeys(matched.get("aliases", []) + aliases))
            merged_sources = list(dict.fromkeys(matched.get("source_message_ids", []) + message_ids))
            merged_attrs = dict(matched.get("attributes", {}))
            merged_attrs.update(attributes)

            entity = MemoryEntity(
                _id=entity_id,
                workspace_id=matched.get("workspace_id", workspace_id),
                canonical_name=matched.get("canonical_name", canonical_name),
                entity_type=matched.get("entity_type", entity_type),
                aliases=merged_aliases,
                description=description or matched.get("description", ""),
                attributes=merged_attrs,
                status=EntityStatus.ACTIVE,
                source_message_ids=merged_sources,
            )
        else:
            # Tạo entity mới (Quy tắc 1: Chỉ tạo mới khi không tìm được entity phù hợp)
            stable_id = generate_stable_entity_id(workspace_id=workspace_id, canonical_name=canonical_name)
            entity = MemoryEntity(
                _id=stable_id,
                workspace_id=workspace_id,
                canonical_name=canonical_name,
                entity_type=entity_type,
                aliases=aliases,
                description=description,
                attributes=attributes,
                status=EntityStatus.ACTIVE,
                source_message_ids=list(message_ids),
            )

        entities.append(entity)

    return entities


def extract_memory(
    query: str,
    workspace_id: str = "default",
    source_message_id: Optional[str] = None,
    existing_entities: Optional[List[Union[MemoryEntity, Dict[str, Any]]]] = None,
    api_key: Optional[str] = None,
    client: Optional[GeminiClient] = None,
) -> List[Dict[str, Any]]:
    """Trích xuất Nhánh 1: Memory (Sync)."""
    llm_client = client or GeminiClient(api_key=api_key)

    context_str = ""
    if existing_entities:
        simple_list = [
            {
                "_id": e.get("_id") if isinstance(e, dict) else e.id,
                "canonical_name": e.get("canonical_name") if isinstance(e, dict) else e.canonical_name,
                "aliases": e.get("aliases", []) if isinstance(e, dict) else e.aliases,
            }
            for e in existing_entities
        ]
        context_str = f"DANH SÁCH THỰC THỂ HIỆN CÓ TRONG WORKSPACE:\n{json.dumps(simple_list, ensure_ascii=False, indent=2)}\n"

    prompt = MEMORY_EXTRACTION_PROMPT.format(
        query=query,
        context_existing_entities=context_str,
    )
    raw_response = llm_client.generate(prompt)
    entities = parse_memory_entities(
        raw_response=raw_response,
        workspace_id=workspace_id,
        source_message_id=source_message_id,
        existing_entities=existing_entities,
    )
    return [e.to_dict() for e in entities]


async def extract_memory_async(
    query: str,
    workspace_id: str = "default",
    source_message_id: Optional[str] = None,
    existing_entities: Optional[List[Union[MemoryEntity, Dict[str, Any]]]] = None,
    api_key: Optional[str] = None,
    client: Optional[GeminiClient] = None,
) -> List[Dict[str, Any]]:
    """Trích xuất Nhánh 1: Memory (Async)."""
    llm_client = client or GeminiClient(api_key=api_key)

    context_str = ""
    if existing_entities:
        simple_list = [
            {
                "_id": e.get("_id") if isinstance(e, dict) else e.id,
                "canonical_name": e.get("canonical_name") if isinstance(e, dict) else e.canonical_name,
                "aliases": e.get("aliases", []) if isinstance(e, dict) else e.aliases,
            }
            for e in existing_entities
        ]
        context_str = f"DANH SÁCH THỰC THỂ HIỆN CÓ TRONG WORKSPACE:\n{json.dumps(simple_list, ensure_ascii=False, indent=2)}\n"

    prompt = MEMORY_EXTRACTION_PROMPT.format(
        query=query,
        context_existing_entities=context_str,
    )
    raw_response = await llm_client.generate_async(prompt)
    entities = parse_memory_entities(
        raw_response=raw_response,
        workspace_id=workspace_id,
        source_message_id=source_message_id,
        existing_entities=existing_entities,
    )
    return [e.to_dict() for e in entities]


# ==============================================================================
# 7. CORE LOGIC: NHÁNH 2 (CLAIMS)
# ==============================================================================

def parse_claims(
    raw_response: str,
    resolved_entities: List[Dict[str, Any]],
    existing_claims: Optional[List[Union[Claim, Dict[str, Any]]]] = None,
    source_message_id: Optional[str] = None,
    sender: Optional[str] = None,
) -> List[Claim]:
    """Parse JSON trả về từ LLM và chuyển đổi thành danh sách Claim."""
    data = safe_parse_json_list(raw_response, fallback_type="Claims")
    if not data:
        return []

    # Map tra cứu entity_id hợp lệ
    known_entity_ids = {e.get("_id") for e in resolved_entities if e.get("_id")}
    # Map name -> entity_id fallback nếu LLM trả về tên thay vì ID
    name_to_id = {}
    for e in resolved_entities:
        eid = e.get("_id")
        if eid:
            name_to_id[str(e.get("canonical_name", "")).strip().lower()] = eid
            for a in e.get("aliases", []):
                name_to_id[str(a).strip().lower()] = eid

    now_iso = datetime.now(timezone.utc).isoformat()
    claims: List[Claim] = []

    for item in data:
        if not isinstance(item, dict):
            continue

        raw_ent_id = str(item.get("entity_id", "")).strip()
        # Fallback map nếu LLM trả về canonical_name thay vì entity_id
        if raw_ent_id in known_entity_ids:
            entity_id = raw_ent_id
        else:
            entity_id = name_to_id.get(raw_ent_id.lower())
            if not entity_id:
                # Nếu vẫn không match và chỉ có 1 entity duy nhất vừa được trích xuất
                if len(resolved_entities) == 1:
                    entity_id = resolved_entities[0].get("_id")
                else:
                    # Bỏ qua nếu không thể gán vào entity nào có căn cứ
                    continue

        predicate = normalize_predicate(str(item.get("predicate", "info")))
        value = item.get("value")
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            # Trần an toàn: giới hạn độ dài value tối đa 15 từ / 120 ký tự
            words = value.split()
            if len(words) > 15:
                value = " ".join(words[:15]) + "..."
            elif len(value) > 120:
                value = value[:117] + "..."

        # Status validation (current, superseded, conflicted, uncertain)
        status_str = str(item.get("status", ClaimStatus.CURRENT.value)).strip().lower()
        try:
            claim_status = ClaimStatus(status_str)
        except ValueError:
            if status_str == "conflict":
                claim_status = ClaimStatus.CONFLICTED
            else:
                claim_status = ClaimStatus.CURRENT

        # Source context
        source_snippet = str(item.get("source_snippet", item.get("source", ""))).strip()
        source_meta: Dict[str, Any] = {
            "snippet": source_snippet,
            "message_id": source_message_id or "",
            "sender": sender or "User",
        }

        # Supersedes tracking (Quy tắc 2)
        supersedes_id = item.get("supersedes")
        if supersedes_id and str(supersedes_id).strip().lower() in ("null", "none", ""):
            supersedes_id = None
        else:
            supersedes_id = str(supersedes_id).strip() if supersedes_id else None

        # Tự động phát hiện claim cũ bị thay thế nếu LLM chưa kịp điền trường supersedes
        if not supersedes_id and claim_status == ClaimStatus.CURRENT and existing_claims:
            for old_c in existing_claims:
                old_dict = old_c.to_dict() if isinstance(old_c, Claim) else old_c
                if (
                    old_dict.get("entity_id") == entity_id
                    and normalize_predicate(str(old_dict.get("predicate", ""))) == predicate
                    and old_dict.get("status") == ClaimStatus.CURRENT.value
                    and str(old_dict.get("value")) != str(value)
                ):
                    supersedes_id = old_dict.get("_id") or old_dict.get("id")
                    break

        new_claim = Claim(
            _id=generate_claim_id(),
            entity_id=entity_id,
            predicate=predicate,
            value=value,
            status=claim_status,
            source=source_meta,
            supersedes=supersedes_id,
            created_at=now_iso,
            updated_at=now_iso,
        )
        claims.append(new_claim)

    # BƯỚC 3: COMPACTNESS & DEDUPLICATION (GỘP & GIỚI HẠN SỐ LƯỢNG)
    # 1. Khử trùng lặp cùng 1 (entity_id, predicate): giữ claim xuất hiện đầu tiên
    seen_keys: Dict[tuple, Claim] = {}
    for c in claims:
        key = (c.entity_id, c.predicate)
        if key not in seen_keys:
            seen_keys[key] = c
    deduped_claims = list(seen_keys.values())

    # 2. Giới hạn trần an toàn (Safety Cap: tối đa 3 claims theo thứ tự ưu tiên từ LLM)
    if len(deduped_claims) > 3:
        deduped_claims = deduped_claims[:3]

    return deduped_claims


def extract_claims(
    query: str,
    entities: List[Union[MemoryEntity, Dict[str, Any]]],
    existing_claims: Optional[List[Union[Claim, Dict[str, Any]]]] = None,
    source_message_id: Optional[str] = None,
    sender: Optional[str] = None,
    api_key: Optional[str] = None,
    client: Optional[GeminiClient] = None,
) -> Dict[str, Any]:
    """
    Trích xuất Nhánh 2: Claims (Sync).
    
    Returns:
        {
            "claims": [Claim dict...],              # Các claims mới trích xuất
            "superseded_claims": [Claim dict...],   # Các claims cũ trong existing_claims vừa bị đánh dấu superseded
        }
    """
    if not entities:
        return {"claims": [], "superseded_claims": []}

    llm_client = client or GeminiClient(api_key=api_key)

    entities_dicts = [e.to_dict() if isinstance(e, MemoryEntity) else e for e in entities]
    clean_entities = [
        {
            "_id": e.get("_id"),
            "canonical_name": e.get("canonical_name"),
            "entity_type": e.get("entity_type"),
            "aliases": e.get("aliases", []),
            "description": e.get("description", ""),
        }
        for e in entities_dicts
    ]

    # Chỉ đưa các claims đang CURRENT của các entities này vào ngữ cảnh
    relevant_existing_claims = []
    if existing_claims:
        target_ids = {e.get("_id") for e in clean_entities}
        for c in existing_claims:
            c_dict = c.to_dict() if isinstance(c, Claim) else c
            if c_dict.get("entity_id") in target_ids and c_dict.get("status") == ClaimStatus.CURRENT.value:
                relevant_existing_claims.append({
                    "_id": c_dict.get("_id") or c_dict.get("id"),
                    "entity_id": c_dict.get("entity_id"),
                    "predicate": c_dict.get("predicate"),
                    "value": c_dict.get("value"),
                    "status": c_dict.get("status"),
                })

    prompt = CLAIM_EXTRACTION_PROMPT.format(
        query=query,
        entities_json=json.dumps(clean_entities, ensure_ascii=False, indent=2),
        existing_claims_json=json.dumps(relevant_existing_claims, ensure_ascii=False, indent=2),
        source_message_id=source_message_id or "unknown_msg",
        sender=sender or "User",
    )

    raw_response = llm_client.generate(prompt)
    new_claims = parse_claims(
        raw_response=raw_response,
        resolved_entities=entities_dicts,
        existing_claims=existing_claims,
        source_message_id=source_message_id,
        sender=sender,
    )

    # Cập nhật trạng thái superseded cho các claim cũ (Quy tắc 2)
    superseded_claims: List[Dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    superseded_target_ids = {c.supersedes for c in new_claims if c.supersedes}

    if existing_claims and superseded_target_ids:
        for old_c in existing_claims:
            old_dict = old_c if isinstance(old_c, dict) else old_c.to_dict()
            cid = old_dict.get("_id") or old_dict.get("id")
            if cid in superseded_target_ids:
                old_dict["status"] = ClaimStatus.SUPERSEDED.value
                old_dict["updated_at"] = now_iso
                superseded_claims.append(old_dict)

    return {
        "claims": [c.to_dict() for c in new_claims],
        "superseded_claims": superseded_claims,
    }


async def extract_claims_async(
    query: str,
    entities: List[Union[MemoryEntity, Dict[str, Any]]],
    existing_claims: Optional[List[Union[Claim, Dict[str, Any]]]] = None,
    source_message_id: Optional[str] = None,
    sender: Optional[str] = None,
    api_key: Optional[str] = None,
    client: Optional[GeminiClient] = None,
) -> Dict[str, Any]:
    """Trích xuất Nhánh 2: Claims (Async)."""
    if not entities:
        return {"claims": [], "superseded_claims": []}

    llm_client = client or GeminiClient(api_key=api_key)

    entities_dicts = [e.to_dict() if isinstance(e, MemoryEntity) else e for e in entities]
    clean_entities = [
        {
            "_id": e.get("_id"),
            "canonical_name": e.get("canonical_name"),
            "entity_type": e.get("entity_type"),
            "aliases": e.get("aliases", []),
            "description": e.get("description", ""),
        }
        for e in entities_dicts
    ]

    relevant_existing_claims = []
    if existing_claims:
        target_ids = {e.get("_id") for e in clean_entities}
        for c in existing_claims:
            c_dict = c.to_dict() if isinstance(c, Claim) else c
            if c_dict.get("entity_id") in target_ids and c_dict.get("status") == ClaimStatus.CURRENT.value:
                relevant_existing_claims.append({
                    "_id": c_dict.get("_id") or c_dict.get("id"),
                    "entity_id": c_dict.get("entity_id"),
                    "predicate": c_dict.get("predicate"),
                    "value": c_dict.get("value"),
                    "status": c_dict.get("status"),
                })

    prompt = CLAIM_EXTRACTION_PROMPT.format(
        query=query,
        entities_json=json.dumps(clean_entities, ensure_ascii=False, indent=2),
        existing_claims_json=json.dumps(relevant_existing_claims, ensure_ascii=False, indent=2),
        source_message_id=source_message_id or "unknown_msg",
        sender=sender or "User",
    )

    raw_response = await llm_client.generate_async(prompt)
    new_claims = parse_claims(
        raw_response=raw_response,
        resolved_entities=entities_dicts,
        existing_claims=existing_claims,
        source_message_id=source_message_id,
        sender=sender,
    )

    superseded_claims: List[Dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    superseded_target_ids = {c.supersedes for c in new_claims if c.supersedes}

    if existing_claims and superseded_target_ids:
        for old_c in existing_claims:
            old_dict = old_c if isinstance(old_c, dict) else old_c.to_dict()
            cid = old_dict.get("_id") or old_dict.get("id")
            if cid in superseded_target_ids:
                old_dict["status"] = ClaimStatus.SUPERSEDED.value
                old_dict["updated_at"] = now_iso
                superseded_claims.append(old_dict)

    return {
        "claims": [c.to_dict() for c in new_claims],
        "superseded_claims": superseded_claims,
    }


# ==============================================================================
# 8. LLM EXTRACTOR CLASS (TỔNG HỢP CẢ 2 NHÁNH)
# ==============================================================================

class LLMExtractor:
    """
    Bộ bóc tách tổng hợp hoàn chỉnh 2 nhánh:
      - Nhánh 1: Memory (Thực thể chuẩn, aliases, mô tả)
      - Nhánh 2: Claims (Mệnh đề thông tin, audit trail, supersedes, trạng thái)
    """

    def __init__(self, api_key: Optional[str] = None):
        self.client = GeminiClient(api_key=api_key)

    def extract_memory(
        self,
        query: str,
        workspace_id: str = "default",
        source_message_id: Optional[str] = None,
        existing_entities: Optional[List[Union[MemoryEntity, Dict[str, Any]]]] = None,
    ) -> List[Dict[str, Any]]:
        """Bóc tách riêng Nhánh 1: Memory."""
        return extract_memory(
            query=query,
            workspace_id=workspace_id,
            source_message_id=source_message_id,
            existing_entities=existing_entities,
            client=self.client,
        )

    async def extract_memory_async(
        self,
        query: str,
        workspace_id: str = "default",
        source_message_id: Optional[str] = None,
        existing_entities: Optional[List[Union[MemoryEntity, Dict[str, Any]]]] = None,
    ) -> List[Dict[str, Any]]:
        """Bóc tách riêng Nhánh 1: Memory (Async)."""
        return await extract_memory_async(
            query=query,
            workspace_id=workspace_id,
            source_message_id=source_message_id,
            existing_entities=existing_entities,
            client=self.client,
        )

    def extract_claims(
        self,
        query: str,
        entities: List[Union[MemoryEntity, Dict[str, Any]]],
        existing_claims: Optional[List[Union[Claim, Dict[str, Any]]]] = None,
        source_message_id: Optional[str] = None,
        sender: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Bóc tách riêng Nhánh 2: Claims."""
        return extract_claims(
            query=query,
            entities=entities,
            existing_claims=existing_claims,
            source_message_id=source_message_id,
            sender=sender,
            client=self.client,
        )

    async def extract_claims_async(
        self,
        query: str,
        entities: List[Union[MemoryEntity, Dict[str, Any]]],
        existing_claims: Optional[List[Union[Claim, Dict[str, Any]]]] = None,
        source_message_id: Optional[str] = None,
        sender: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Bóc tách riêng Nhánh 2: Claims (Async)."""
        return await extract_claims_async(
            query=query,
            entities=entities,
            existing_claims=existing_claims,
            source_message_id=source_message_id,
            sender=sender,
            client=self.client,
        )

    def extract(
        self,
        query: str,
        workspace_id: str = "default",
        source_message_id: Optional[str] = None,
        sender: Optional[str] = None,
        existing_entities: Optional[List[Union[MemoryEntity, Dict[str, Any]]]] = None,
        existing_claims: Optional[List[Union[Claim, Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """
        Bóc tách toàn diện một câu truy vấn/tin nhắn thành cả 2 nhánh (Sync):
          - Nhánh 1 (Memory): Trích xuất & chuẩn hoá entities
          - Nhánh 2 (Claims): Trích xuất claims gắn với entity_id chuẩn, xử lý quan hệ supersedes
          
        Returns:
            {
                "memory": [...],             # Danh sách entities (MemoryEntity dicts)
                "claims": [...],             # Danh sách claims mới (Claim dicts)
                "superseded_claims": [...],  # Danh sách claims cũ vừa bị đánh dấu superseded
            }
        """
        # Bước 1: Trích xuất Nhánh 1 (Memory)
        memory_result = self.extract_memory(
            query=query,
            workspace_id=workspace_id,
            source_message_id=source_message_id,
            existing_entities=existing_entities,
        )

        # Hợp nhất danh sách entities phục vụ liên kết claim
        all_entities = list(existing_entities or []) + memory_result

        # Bước 2: Trích xuất Nhánh 2 (Claims) liên kết với entities
        claims_result = self.extract_claims(
            query=query,
            entities=all_entities,
            existing_claims=existing_claims,
            source_message_id=source_message_id,
            sender=sender,
        )

        return {
            "memory": memory_result,
            "claims": claims_result.get("claims", []),
            "superseded_claims": claims_result.get("superseded_claims", []),
        }

    async def extract_async(
        self,
        query: str,
        workspace_id: str = "default",
        source_message_id: Optional[str] = None,
        sender: Optional[str] = None,
        existing_entities: Optional[List[Union[MemoryEntity, Dict[str, Any]]]] = None,
        existing_claims: Optional[List[Union[Claim, Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """Bóc tách toàn diện cả 2 nhánh (Async)."""
        memory_result = await self.extract_memory_async(
            query=query,
            workspace_id=workspace_id,
            source_message_id=source_message_id,
            existing_entities=existing_entities,
        )

        all_entities = list(existing_entities or []) + memory_result

        claims_result = await self.extract_claims_async(
            query=query,
            entities=all_entities,
            existing_claims=existing_claims,
            source_message_id=source_message_id,
            sender=sender,
        )

        return {
            "memory": memory_result,
            "claims": claims_result.get("claims", []),
            "superseded_claims": claims_result.get("superseded_claims", []),
        }


# Global instance
llm_extractor = LLMExtractor()


def extract(
    query: str,
    workspace_id: str = "default",
    source_message_id: Optional[str] = None,
    sender: Optional[str] = None,
    existing_entities: Optional[List[Union[MemoryEntity, Dict[str, Any]]]] = None,
    existing_claims: Optional[List[Union[Claim, Dict[str, Any]]]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Hàm tiện ích cấp module: bóc tách toàn diện 2 nhánh (Sync)."""
    extractor = LLMExtractor(api_key=api_key) if api_key else llm_extractor
    return extractor.extract(
        query=query,
        workspace_id=workspace_id,
        source_message_id=source_message_id,
        sender=sender,
        existing_entities=existing_entities,
        existing_claims=existing_claims,
    )


async def extract_async(
    query: str,
    workspace_id: str = "default",
    source_message_id: Optional[str] = None,
    sender: Optional[str] = None,
    existing_entities: Optional[List[Union[MemoryEntity, Dict[str, Any]]]] = None,
    existing_claims: Optional[List[Union[Claim, Dict[str, Any]]]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Hàm tiện ích cấp module: bóc tách toàn diện 2 nhánh (Async)."""
    extractor = LLMExtractor(api_key=api_key) if api_key else llm_extractor
    return await extractor.extract_async(
        query=query,
        workspace_id=workspace_id,
        source_message_id=source_message_id,
        sender=sender,
        existing_entities=existing_entities,
        existing_claims=existing_claims,
    )


# ==============================================================================
# 9. STORAGE HELPERS (PERSISTENCE CHO MEMORY & CLAIMS)
# ==============================================================================

DATA_DIR = os.path.join(CURRENT_DIR, "data")
MEMORY_STORE_PATH = os.path.join(DATA_DIR, "memory_store.json")
CLAIM_STORE_PATH = os.path.join(DATA_DIR, "claim_store.json")


def load_stored_entities() -> List[Dict[str, Any]]:
    """Tải toàn bộ danh sách entities từ memory_store.json."""
    if not os.path.exists(MEMORY_STORE_PATH):
        return []
    try:
        with open(MEMORY_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def load_stored_claims() -> List[Dict[str, Any]]:
    """Tải toàn bộ danh sách claims từ claim_store.json."""
    if not os.path.exists(CLAIM_STORE_PATH):
        return []
    try:
        with open(CLAIM_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_stored_entities(entities: List[Dict[str, Any]]) -> None:
    """Lưu danh sách entities vào memory_store.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MEMORY_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(entities, f, ensure_ascii=False, indent=2)


def save_stored_claims(claims: List[Dict[str, Any]]) -> None:
    """Lưu danh sách claims vào claim_store.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CLAIM_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(claims, f, ensure_ascii=False, indent=2)


def clear_stores() -> None:
    """Xóa sạch bộ nhớ lưu trữ entities và claims."""
    save_stored_entities([])
    save_stored_claims([])


def apply_and_save_extraction(extraction_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Cập nhật kết quả trích xuất mới vào kho dữ liệu lưu trữ (NoSQL JSON Store):
      - Upsert entities mới vào memory_store.json (nếu trùng _id thì merge/cập nhật)
      - Đánh dấu superseded cho claims cũ trong claim_store.json
      - Thêm claims mới vào claim_store.json
    """
    stored_entities = load_stored_entities()
    stored_claims = load_stored_claims()

    new_entities = extraction_result.get("memory", [])
    new_claims = extraction_result.get("claims", [])
    superseded_claims = extraction_result.get("superseded_claims", [])

    # 1. Upsert entities
    for ent in new_entities:
        e_id = ent.get("_id") or ent.get("id")
        idx = next((i for i, e in enumerate(stored_entities) if (e.get("_id") or e.get("id")) == e_id), None)
        if idx is not None:
            # Gộp aliases và attributes nếu đã có
            existing_ent = stored_entities[idx]
            existing_aliases = existing_ent.get("aliases", [])
            new_aliases = ent.get("aliases", [])
            ent["aliases"] = list(dict.fromkeys(existing_aliases + new_aliases))
            stored_entities[idx] = ent
        else:
            stored_entities.append(ent)

    # 2. Cập nhật superseded claims
    superseded_ids = {c.get("_id") or c.get("id") for c in superseded_claims if (c.get("_id") or c.get("id"))}
    now_iso = datetime.now(timezone.utc).isoformat()
    for c in stored_claims:
        cid = c.get("_id") or c.get("id")
        if cid in superseded_ids:
            c["status"] = ClaimStatus.SUPERSEDED.value
            c["updated_at"] = now_iso

    # 3. Thêm claims mới vào store
    stored_claims.extend(new_claims)

    save_stored_entities(stored_entities)
    save_stored_claims(stored_claims)

    return {
        "memory": new_entities,
        "claims": new_claims,
        "superseded_claims": superseded_claims,
        "total_stored_entities": len(stored_entities),
        "total_stored_claims": len(stored_claims),
    }
