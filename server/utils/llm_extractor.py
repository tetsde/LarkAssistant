"""
LLM Extractor Module for HiLark
================================
Phân tích và bóc tách thông tin từ tin nhắn hội thoại thành 2 nhánh dữ liệu:
  - Nhánh 1: Entities (Thực thể kinh doanh chuẩn: Project, Person, Team, Customer, Feature, Document)
  - Nhánh 2: Facts (Mệnh đề sự thật gắn với Entity: deadline, assignee, status, budget, scope...)

Mô hình dữ liệu trực quan:
  Parent (Entity: id, name, type, aliases, description)
    └── Children (Facts: id, entity_id, property, value, status, replaces, source)
"""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger(__name__)

# ==============================================================================
# 1. ENUMS & SCHEMAS (IMPORTED FROM MODELS)
# ==============================================================================

from models.memory import (
    EntityStatus,
    FactStatus,
    AssertedBy,
    Entity,
    Fact,
    build_entity_tree,
    # Vietnam timezone utilities
    VIETNAM_TZ,
    get_vietnam_now,
    get_vietnam_now_iso,
    # Backward compatibility aliases
    ClaimStatus,
    MemoryEntity,
    Claim,
)


# ==============================================================================
# 2. HELPER FUNCTIONS: ID GENERATION & STRING CLEANING
# ==============================================================================

def generate_stable_entity_id(workspace_id: str, name: str) -> str:
    """
    Tạo ID ổn định do Python sinh ra (Deterministic ID dựa trên uuid5).
    Đảm bảo cùng một thực thể trong cùng một workspace luôn có id đồng nhất.
    """
    clean_name = re.sub(r"\s+", " ", name.strip().lower())
    clean_ws = workspace_id.strip().lower()
    seed = f"{clean_ws}:{clean_name}"
    stable_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, seed)
    return f"ent_{stable_uuid.hex[:12]}"


def generate_fact_id() -> str:
    """Tạo ID cho fact mới (fact_xxxx)."""
    return f"fact_{uuid.uuid4().hex[:8]}"


# Backward compatibility alias
generate_claim_id = generate_fact_id


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
      - Graceful Degradation: Không crash server nếu output bị lỗi format.
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


def normalize_property(property_name: str) -> str:
    """Chuẩn hoá tên thuộc tính/property về chữ thường snake_case."""
    p = property_name.strip().lower()
    p = re.sub(r"[^\w\s]", "", p)
    p = re.sub(r"\s+", "_", p)
    return p


# Backward compatibility alias
normalize_predicate = normalize_property


def normalize_time_value(prop: str, val: Any, reference_dt: Optional[datetime] = None) -> Any:
    """
    Chuẩn hoá giá trị thuộc tính thời gian (deadline, due_date, milestone, etc.)
    theo chuẩn lịch và giờ Việt Nam (UTC+7).
    """
    if not isinstance(val, str) or not val.strip():
        return val

    time_props = {"deadline", "due_date", "milestone", "schedule", "start_date", "end_date", "completion_date", "target_date"}
    if prop.lower() not in time_props:
        return val

    ref = reference_dt or get_vietnam_now()
    val_clean = val.strip()

    # 1. Xử lý các dạng lỗi do gõ hoặc chat như 'ngày/10' -> 'ngày 10'
    val_clean = re.sub(r"^ngày\s*/\s*(\d{1,2})$", r"ngày \1", val_clean, flags=re.IGNORECASE)

    # 2. 'DD/MM' -> 'DD/MM/YYYY' (vd: 30/10 -> 30/10/2026)
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})$", val_clean)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        return f"{day:02d}/{month:02d}/{ref.year}"

    # 3. 'ngày DD/MM' -> 'DD/MM/YYYY' (vd: ngày 15/11 -> 15/11/2026)
    m = re.match(r"^ngày\s+(\d{1,2})[/-](\d{1,2})$", val_clean, flags=re.IGNORECASE)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        return f"{day:02d}/{month:02d}/{ref.year}"

    # 4. 'ngày DD' -> 'DD/MM/YYYY' (vd: ngày 10 -> 10/10/2026)
    m = re.match(r"^ngày\s+(\d{1,2})$", val_clean, flags=re.IGNORECASE)
    if m:
        day = int(m.group(1))
        return f"{day:02d}/{ref.month:02d}/{ref.year}"

    # 5. 'tháng MM' -> 'MM/YYYY' (vd: tháng 12 -> 12/2026)
    m = re.match(r"^tháng\s+(\d{1,2})$", val_clean, flags=re.IGNORECASE)
    if m:
        month = int(m.group(1))
        return f"{month:02d}/{ref.year}"

    return val_clean


# ==============================================================================
# 3. PROMPT TEMPLATES (ENTITIES & FACTS)
# ==============================================================================

ENTITY_EXTRACTION_PROMPT = """\
You are an expert in Named Entity Recognition & Entity Resolution.
Your task is to analyze the input text and extract CORE BUSINESS ENTITIES that hold long-term operational value.

INPUT TEXT:
\"\"\"{query}\"\"\"

{context_existing_entities}

MANDATORY RULES:
1. "name": The standardized, official name of the entity.
2. "type": Must be one of the core domain categories:
   - "project": A specific project or product (e.g., HiLark, Atlas, or a distinct unnamed project).
   - "feature": A specific capability or module of a product/project (e.g., QR Payment, Cart Checkout, API).
   - "team": A department, group, or work unit (e.g., Tech Team, Executive Board).
   - "customer": A client company or business partner (e.g., LarkTech, Client A).
   - "person": A specific individual with a clear name or distinct role (e.g., Tuan PM, Lead Engineer Long).
   - "document": Contracts, specifications, or key operating procedures.
3. "aliases": Alternative names, conversational references, or nicknames with clear evidence in the text.
4. "description": A concise one-sentence summary of the entity's role or purpose.

🔗 COREFERENCE RESOLUTION & ATTRIBUTE MATCHING (CRITICAL):
- When the input text refers to an entity using indirect descriptors, past attributes, or pronouns:
  * Patterns: "Dự án bữa anh nói [X]", "dự án có ngân sách [X]", "dự án của [người Y]", "dự án deadline [Z]", "cái dự án đó", "dự án này"
  * ALWAYS inspect "known_attributes" in EXISTING ENTITIES IN WORKSPACE above!
  * Example: If the text says "Dự án bữa anh nói 150tr bây h được bên khách hàng tăng lên 500tr", and existing entity "Atlas" has known_attributes {{"budget": "150 triệu"}}, this text is referring to ATLAS!
    -> YOU MUST RE-USE the existing entity: "name": "Atlas"
    -> NEVER create a new entity like "Dự án đã trao đổi" or "Dự án 150tr".
    -> Add the reference phrase (e.g. "Dự án bữa anh nói") into its "aliases".

🌟 CONTEXTUAL ENTITIES (ONLY FOR TRULY NEW / UNNAMED WORK ITEMS):
- ONLY create a new Contextual Entity if there is NO matching existing entity in workspace (by name, alias, or known_attributes).
- If a work item is genuinely new and unnamed:
  * "name": A clear descriptive name capturing its context (e.g., "Dự án giao đợt 20/10" or "Dự án API").
  * "aliases": Verbatim phrases used in chat.
  * "type": project or feature.
  * "description": Brief context from the message.

🔄 ENTITY RESOLUTION WITH EXISTING ENTITIES:
- Look at EXISTING ENTITIES IN WORKSPACE above.
- If the input text refers to an existing entity (by its name, an alias, or matching attributes), RE-USE that entity's name and update its description/aliases. DO NOT create duplicate entities!
- When the text refers to "a new customer", "another project", or a distinct separate work item, create a distinctly named entity (e.g., "New Customer (Alpha Project)"), NEVER merge it into older unrelated entities.

⛔ RESTRICTIONS:
- DO NOT create entities for generic anonymous roles without proper brand or company names: "khách hàng", "bên khách hàng", "người dùng", "khách", "đối tác", "team", "anh em", "chúng tôi".
- DO NOT create entities for bare conversational pronouns or particles: "anh", "em", "chúng tôi", "ai đó", "dạ", "alo".
- TUYỆT ĐỐI KHÔNG đưa đại từ xưng hô ("mình", "bên mình", "em", "anh", "tôi", "bạn", "chúng tôi") vào trường "aliases" của bất kỳ entity nào. Aliases chỉ được là tên gọi tắt, mã dự án hoặc biệt danh chính danh.
- Timestamps and dates alone ("today", "tomorrow", "Oct 18") are NOT entities. Dates are values of Facts (e.g. deadlines), linked to the project entity!
- VIETNAMESE DISAMBIGUATION: The word "Mai" at sentence starts in Vietnamese almost always means "Tomorrow" (temporal marker), NOT a person named Mai, unless preceded by explicit honorifics like "chị Mai" or "bạn Mai".
- PERSON ASSIGNMENT: In phrases like "giao [X] lead" or "cho [X] phụ trách", [X] is the person being assigned even if written in lowercase (e.g., "giao nguyên lead" -> person name is "Nguyên").

Return ONLY a valid JSON Array (max 1-3 core entities):
[
  {{
    "name": "Atlas",
    "type": "project",
    "aliases": ["Atlas Project"],
    "description": "Software development project.",
    "attributes": {{}}
  }}
]
"""

# Alias for backward compatibility
MEMORY_EXTRACTION_PROMPT = ENTITY_EXTRACTION_PROMPT


FACT_EXTRACTION_PROMPT = """\
You are an expert in Fact Extraction and Business Knowledge Graphs.
Your goal is to answer:
"What fact was stated, about which entity, is it currently valid, and what is the source?"

INPUT TEXT:
\"\"\"{query}\"\"\"

IDENTIFIED ENTITIES:
{entities_json}

CURRENT FACTS IN MEMORY (ACTIVE FACTS):
{existing_facts_json}

SOURCE METADATA:
- Message ID: {source_message_id}
- Sender: {sender}
- Reference Time: {reference_time_vn} (Vietnam Timezone - UTC+7)

EXTRACTION RULES:
1. "entity_id": MUST accurately reference the "id" of an entity from the IDENTIFIED ENTITIES list above.
2. "property": Extract ONLY core business attributes:
   - "deadline": Target dates, due dates, completion milestones.
   - "assignee" / "owner": Responsible person or team (e.g., value: "Tuan PM").
   - "status": Operational status of a task, project, or contract (e.g., value: "signed", "in_progress", "resigned").
   - "scope" / "requirement": Feature request, deliverable, or functional scope.
   - "budget": Monetary cost or allocated funds.

🕒 TIME & DEADLINE NORMALIZATION (VIETNAM TIMEZONE - UTC+7):
- The current reference time is: {reference_time_vn} (Vietnam Timezone, GMT+7).
- For all time-related properties (especially "deadline", "milestone", "schedule"):
  * Always normalize relative time phrases into standard Vietnamese calendar format based on the reference time:
    - Relative day ("hôm nay", "ngày mai", "chiều mai", "hôm qua", "tuần sau", "thứ 2 tới", "cuối tuần") -> Calculate exact date as "DD/MM/YYYY" (e.g., "12/10/2026").
    - If a specific hour is stated (e.g., "15h chiều mai", "9h sáng thứ 2", "14h30") -> Format as "HH:mm DD/MM/YYYY" (24-hour Vietnam time, e.g., "15:00 12/10/2026").
  * If the input provides only day and month (e.g., "ngày 10", "10/10", "15/11", "30/10") -> Resolve with the current reference year: "10/10/2026", "15/11/2026", "30/10/2026".
  * If only month is provided (e.g., "tháng 12") -> Format as "12/2026".
  * If approximate or period (e.g., "cuối tháng 10", "quý 4") -> Format as "cuối tháng 10/2026" or "Q4/2026".
  * DO NOT output raw fragmented strings like "ngày/10" or relative words if they can be resolved to exact Vietnam calendar time.

⛔ RESTRICTIONS - DO NOT EXTRACT CHATTER, INQUIRIES, OR CONVERSATIONAL NOISE:
- FORBIDDEN properties: "action", "chat", "message", "sent_message", "received_message", "urging_deadline", "notify". The system only records persistent business facts, not communication activity logs.
- FORBIDDEN INQUIRIES / QUESTIONS: DO NOT extract questions, inquiries, or rhetorical requests ("báo ai", "ai làm", "ở đâu", "khi nào", "thế nào", "làm sao") as facts. For example, NEVER extract property="assignee", value="ai" from a question "báo ai ạ?".
- FORBIDDEN PERSONAL LIFE / HEALTH: DO NOT extract individual health or personal leave ("mai em ốm", "bận việc riêng", "đi ăn cưới", "nghỉ phép") as a project's operational "status" or "scope". Only extract persistent business/technical facts about the entity!

🎯 OUTPUT CONTROL & RANKING RULES:
- Quantity: Extract a MAXIMUM of 1 to 5 concise facts per message.
- Priority Ranking: Order the array by descending business importance (most critical fact first).
- Focus on Milestones: Prioritize deadlines, statuses, owners, scope, and key contractual events.
- Do NOT fragment facts: A single event (e.g., a deadline change) must generate only ONE fact with property="deadline".

3. "value": Highly concise value (MAXIMUM 10 WORDS / UNDER 20 TOKENS).
   - Valid examples: "30/10/2026", "signed", "resigned", "Tuan PM", "200M VND".
   - DO NOT paste whole sentences into "value" (full sentences belong in "source_snippet").
4. "status":
   - "current": Confirmed, active fact that is currently valid.
   - "proposed": Proposal, request, or suggestion (e.g. asking to change roles, requesting to become lead, suggested ideas).
   - "superseded": Old fact that has been replaced.
   - "conflicted": Direct contradiction across sources.
   - "uncertain": Ambiguous, speculative, or unconfirmed ("maybe", "looks like", "around", "tentative").
5. "source_snippet": Exact verbatim quotation from the input text as evidence.
6. "replaces": If this fact REPLACES an existing fact (same entity_id and same property, e.g., changing deadline from 18/10/2026 to 30/10/2026), specify the exact "id" of the replaced fact (e.g., "fact_001"). If it does not replace any fact, set to null.

Return ONLY a valid JSON Array ordered by priority (max 1-5 core facts):
[
  {{
    "entity_id": "ent_...",
    "property": "deadline",
    "value": "30/10/2026",
    "status": "current",
    "source_snippet": "moved from the 18th to the 30th",
    "replaces": "fact_000"
  }}
]
"""

# Alias for backward compatibility
CLAIM_EXTRACTION_PROMPT = FACT_EXTRACTION_PROMPT


# ==============================================================================
# 4. LLM API CLIENT (GEMINI VIA SERVICES.LLM_CLIENT)
# ==============================================================================

from services.llm_client import GeminiClient, LLMClient, llm_client




FORBIDDEN_PRONOUNS = {
    "mình", "bên mình", "em", "anh", "tôi", "bạn", "chúng tôi", "chúng mình",
    "họ", "ai đó", "dạ", "alo", "nhé", "nha", "ạ"
}


# ==============================================================================
# 5. ENTITY MATCHING & RESOLUTION (QUY TẮC: KHÔNG MERGE TÙY TIỆN)
# ==============================================================================

def find_matching_entity(
    candidate_name: str,
    candidate_aliases: List[str],
    existing_entities: List[Union[Entity, Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """
    Tìm entity phù hợp từ danh sách entities đã có.
    Quy tắc:
      - Chỉ merge khi trùng chính xác name hoặc trùng một alias đã được ghi nhận.
      - Tên gần giống nhau (như 'Dự án Alpha' vs 'Dự án Atlas') KHÔNG ĐƯỢC MERGE.
    """
    cand_norm = re.sub(r"\s+", " ", candidate_name.strip().lower())
    cand_alias_norms = {re.sub(r"\s+", " ", a.strip().lower()) for a in candidate_aliases if a.strip()}

    for ent in existing_entities:
        ent_dict = ent.to_dict() if isinstance(ent, Entity) else ent
        e_name = ent_dict.get("name") or ent_dict.get("canonical_name", "")
        c_name = re.sub(r"\s+", " ", str(e_name).strip().lower())
        e_aliases = {
            re.sub(r"\s+", " ", str(a).strip().lower())
            for a in ent_dict.get("aliases", [])
            if str(a).strip()
        }

        # 1. Trùng name
        if cand_norm and cand_norm == c_name:
            return ent_dict

        # 2. Tên ứng viên nằm trong aliases của entity đã có
        if cand_norm and cand_norm in e_aliases:
            return ent_dict

        # 3. Một alias của ứng viên trùng với name của entity đã có
        if c_name and c_name in cand_alias_norms:
            return ent_dict

        # 4. Trùng khớp alias có bằng chứng
        if cand_alias_norms and (cand_alias_norms & e_aliases):
            return ent_dict

    return None


# ==============================================================================
# 6. CORE LOGIC: NHÁNH 1 (ENTITIES)
# ==============================================================================

def parse_entities(
    raw_response: str,
    workspace_id: str = "default",
    source_message_id: Optional[str] = None,
    existing_entities: Optional[List[Union[Entity, Dict[str, Any]]]] = None,
) -> List[Entity]:
    """Parse JSON trả về từ LLM và chuyển đổi thành Entity."""
    data = safe_parse_json_list(raw_response, fallback_type="Entities")
    if not data:
        return []

    message_ids = [source_message_id] if source_message_id else []
    existing = existing_entities or []
    entities: List[Entity] = []

    for item in data:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name") or item.get("canonical_name", "")).strip()
        if not name or name.lower() in FORBIDDEN_PRONOUNS:
            continue

        ent_type = str(item.get("type") or item.get("entity_type", "project")).strip().lower()
        raw_aliases = [str(a).strip() for a in item.get("aliases", []) if str(a).strip()]
        aliases = [a for a in raw_aliases if a.lower() not in FORBIDDEN_PRONOUNS]
        description = str(item.get("description", "")).strip()
        attributes = item.get("attributes", {})
        if not isinstance(attributes, dict):
            attributes = {"raw_value": attributes}

        # Kiểm tra xem có match với entity đã có không
        matched = find_matching_entity(name, aliases, existing)
        if matched:
            entity_id = matched.get("id") or matched.get("_id")
            existing_clean_aliases = [a for a in matched.get("aliases", []) if str(a).strip().lower() not in FORBIDDEN_PRONOUNS]
            merged_aliases = list(dict.fromkeys(existing_clean_aliases + aliases))
            merged_sources = list(dict.fromkeys(matched.get("source_message_ids", []) + message_ids))
            merged_attrs = dict(matched.get("attributes", {}))
            merged_attrs.update(attributes)

            matched_name = matched.get("name") or matched.get("canonical_name", name)
            matched_type = matched.get("type") or matched.get("entity_type", ent_type)

            entity = Entity(
                id=entity_id,
                workspace_id=matched.get("workspace_id", workspace_id),
                name=matched_name,
                type=matched_type,
                aliases=merged_aliases,
                description=description or matched.get("description", ""),
                attributes=merged_attrs,
                status=EntityStatus.ACTIVE,
                source_message_ids=merged_sources,
            )
        else:
            stable_id = generate_stable_entity_id(workspace_id=workspace_id, name=name)
            entity = Entity(
                id=stable_id,
                workspace_id=workspace_id,
                name=name,
                type=ent_type,
                aliases=aliases,
                description=description,
                attributes=attributes,
                status=EntityStatus.ACTIVE,
                source_message_ids=list(message_ids),
            )

        entities.append(entity)

    return entities


# Backward compatibility alias
parse_memory_entities = parse_entities


def extract_entities(
    query: str,
    workspace_id: str = "default",
    source_message_id: Optional[str] = None,
    existing_entities: Optional[List[Union[Entity, Dict[str, Any]]]] = None,
    existing_facts: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
    api_key: Optional[str] = None,
    client: Optional[GeminiClient] = None,
) -> List[Dict[str, Any]]:
    """Trích xuất Nhánh 1: Entities (Sync)."""
    llm_client = client or GeminiClient(api_key=api_key)

    context_str = ""
    if existing_entities:
        simple_list = []
        for e in existing_entities:
            eid = e.get("id") or e.get("_id") if isinstance(e, dict) else e.id
            ename = e.get("name") or e.get("canonical_name") if isinstance(e, dict) else e.name
            etype = e.get("type") or e.get("entity_type") if isinstance(e, dict) else e.type
            aliases = e.get("aliases", []) if isinstance(e, dict) else e.aliases

            ent_info: Dict[str, Any] = {
                "id": eid,
                "name": ename,
                "type": etype,
                "aliases": aliases,
            }

            # Lấy các active facts của entity này để giải quyết Coreference Resolution
            if existing_facts:
                attrs = {}
                for f in existing_facts:
                    f_dict = f.to_dict() if isinstance(f, Fact) else f
                    if (f_dict.get("entity_id") == eid) and (f_dict.get("status") == FactStatus.CURRENT.value):
                        prop = f_dict.get("property") or f_dict.get("predicate")
                        val = f_dict.get("value")
                        if prop and val:
                            attrs[prop] = val
                if attrs:
                    ent_info["known_attributes"] = attrs

            simple_list.append(ent_info)

        context_str = f"EXISTING ENTITIES IN WORKSPACE:\n{json.dumps(simple_list, ensure_ascii=False, indent=2)}\n"

    prompt = ENTITY_EXTRACTION_PROMPT.format(
        query=query,
        context_existing_entities=context_str,
    )
    raw_response = llm_client.generate(prompt)
    entities = parse_entities(
        raw_response=raw_response,
        workspace_id=workspace_id,
        source_message_id=source_message_id,
        existing_entities=existing_entities,
    )
    return [e.to_dict() for e in entities]


# Backward compatibility alias
extract_memory = extract_entities


async def extract_entities_async(
    query: str,
    workspace_id: str = "default",
    source_message_id: Optional[str] = None,
    existing_entities: Optional[List[Union[Entity, Dict[str, Any]]]] = None,
    existing_facts: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
    api_key: Optional[str] = None,
    client: Optional[GeminiClient] = None,
) -> List[Dict[str, Any]]:
    """Trích xuất Nhánh 1: Entities (Async)."""
    llm_client = client or GeminiClient(api_key=api_key)

    context_str = ""
    if existing_entities:
        simple_list = []
        for e in existing_entities:
            eid = e.get("id") or e.get("_id") if isinstance(e, dict) else e.id
            ename = e.get("name") or e.get("canonical_name") if isinstance(e, dict) else e.name
            etype = e.get("type") or e.get("entity_type") if isinstance(e, dict) else e.type
            aliases = e.get("aliases", []) if isinstance(e, dict) else e.aliases

            ent_info: Dict[str, Any] = {
                "id": eid,
                "name": ename,
                "type": etype,
                "aliases": aliases,
            }

            # Lấy các active facts của entity này để giải quyết Coreference Resolution
            if existing_facts:
                attrs = {}
                for f in existing_facts:
                    f_dict = f.to_dict() if isinstance(f, Fact) else f
                    if (f_dict.get("entity_id") == eid) and (f_dict.get("status") == FactStatus.CURRENT.value):
                        prop = f_dict.get("property") or f_dict.get("predicate")
                        val = f_dict.get("value")
                        if prop and val:
                            attrs[prop] = val
                if attrs:
                    ent_info["known_attributes"] = attrs

            simple_list.append(ent_info)

        context_str = f"EXISTING ENTITIES IN WORKSPACE:\n{json.dumps(simple_list, ensure_ascii=False, indent=2)}\n"

    prompt = ENTITY_EXTRACTION_PROMPT.format(
        query=query,
        context_existing_entities=context_str,
    )
    raw_response = await llm_client.generate_async(prompt)
    entities = parse_entities(
        raw_response=raw_response,
        workspace_id=workspace_id,
        source_message_id=source_message_id,
        existing_entities=existing_entities,
    )
    return [e.to_dict() for e in entities]


# Backward compatibility alias
extract_memory_async = extract_entities_async


# ==============================================================================
# 7. CORE LOGIC: NHÁNH 2 (FACTS)
# ==============================================================================

def parse_facts(
    raw_response: str,
    resolved_entities: List[Dict[str, Any]],
    existing_facts: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
    source_message_id: Optional[str] = None,
    sender: Optional[str] = None,
    asserted_by: Optional[Union[AssertedBy, Dict[str, Any]]] = None,
) -> List[Fact]:
    """Parse JSON trả về từ LLM và chuyển đổi thành danh sách Fact kèm thẩm quyền phát ngôn."""
    data = safe_parse_json_list(raw_response, fallback_type="Facts")
    if not data:
        return []

    # Xác định vai trò của người phát ngôn (owner vs member)
    speaker_role = "member"
    if asserted_by:
        if isinstance(asserted_by, dict):
            speaker_role = str(asserted_by.get("role", "member")).lower()
        else:
            speaker_role = str(getattr(asserted_by, "role", "member")).lower()

    # Map tra cứu entity_id hợp lệ
    known_entity_ids = {e.get("id") or e.get("_id") for e in resolved_entities if (e.get("id") or e.get("_id"))}
    # Map name -> entity_id fallback nếu LLM trả về tên thay vì ID
    name_to_id = {}
    for e in resolved_entities:
        eid = e.get("id") or e.get("_id")
        if eid:
            ename = e.get("name") or e.get("canonical_name", "")
            name_to_id[str(ename).strip().lower()] = eid
            for a in e.get("aliases", []):
                name_to_id[str(a).strip().lower()] = eid

    now_iso = get_vietnam_now_iso()
    facts: List[Fact] = []

    for item in data:
        if not isinstance(item, dict):
            continue

        raw_ent_id = str(item.get("entity_id", "")).strip()
        # Fallback map nếu LLM trả về name thay vì entity_id
        if raw_ent_id in known_entity_ids:
            entity_id = raw_ent_id
        else:
            entity_id = name_to_id.get(raw_ent_id.lower())
            if not entity_id:
                if len(resolved_entities) == 1:
                    entity_id = resolved_entities[0].get("id") or resolved_entities[0].get("_id")
                else:
                    continue

        prop = normalize_property(str(item.get("property") or item.get("predicate", "info")))
        value = item.get("value")
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            # Chuẩn hoá giá trị thời gian theo chuẩn giờ và lịch Việt Nam (UTC+7)
            value = normalize_time_value(prop, value)
            words = value.split()
            if len(words) > 15:
                value = " ".join(words[:15]) + "..."
            elif len(value) > 120:
                value = value[:117] + "..."

        # [FACT SANITIZER - EDL-0008]: Loại bỏ fact là câu hỏi nghi vấn hoặc việc riêng cá nhân
        val_clean = str(value).strip().lower()
        QUESTION_PRONOUNS = {"ai", "gì", "đâu", "nào", "sao", "ai ạ", "ai vậy", "ai nhỉ", "ai đó", "?"}
        if val_clean in QUESTION_PRONOUNS or val_clean.endswith("?") or val_clean.startswith("ai "):
            logger.info(f"🚫 [Fact Sanitizer] Loại bỏ fact câu hỏi nghi vấn: prop='{prop}', value='{value}'")
            continue

        PERSONAL_LEAVE_KEYWORDS = {"ốm", "nghỉ ốm", "bận việc riêng", "đi viện", "việc gia đình", "đám cưới"}
        if prop in ("status", "scope") and any(kw in val_clean for kw in PERSONAL_LEAVE_KEYWORDS):
            logger.info(f"🚫 [Fact Sanitizer] Loại bỏ fact sinh hoạt cá nhân: prop='{prop}', value='{value}'")
            continue

        # Source context
        source_snippet = str(item.get("source_snippet", item.get("source", ""))).strip()
        source_meta: Dict[str, Any] = {
            "snippet": source_snippet,
            "message_id": source_message_id or "",
            "sender": sender or "User",
        }

        # Status validation (current, proposed, superseded, conflicted, uncertain)
        status_str = str(item.get("status", FactStatus.CURRENT.value)).strip().lower()
        try:
            fact_status = FactStatus(status_str)
        except ValueError:
            if status_str == "conflict":
                fact_status = FactStatus.CONFLICTED
            elif status_str == "proposed":
                fact_status = FactStatus.PROPOSED
            else:
                fact_status = FactStatus.CURRENT

        # Replaces tracking với SUPERSEDE SHIELD
        replaces_id = item.get("replaces") or item.get("supersedes")
        if replaces_id and str(replaces_id).strip().lower() in ("null", "none", ""):
            replaces_id = None
        else:
            replaces_id = str(replaces_id).strip() if replaces_id else None

        # Tự động phát hiện fact cũ bị thay thế nếu LLM chưa điền trường replaces
        if not replaces_id and fact_status == FactStatus.CURRENT and existing_facts:
            for old_f in existing_facts:
                old_dict = old_f.to_dict() if isinstance(old_f, Fact) else old_f
                old_prop = normalize_property(str(old_dict.get("property") or old_dict.get("predicate", "")))
                if (
                    old_dict.get("entity_id") == entity_id
                    and old_prop == prop
                    and old_dict.get("status") == FactStatus.CURRENT.value
                    and str(old_dict.get("value")) != str(value)
                ):
                    # [SUPERSEDE SHIELD]: Nhân sự (member) TUYỆT ĐỐI KHÔNG được ghi đè Fact do Owner chốt!
                    old_asserted = old_dict.get("asserted_by") or {}
                    old_role = (old_asserted.get("role") if isinstance(old_asserted, dict) else getattr(old_asserted, "role", "member")) if old_asserted else "member"
                    if speaker_role == "member" and old_role == "owner":
                        # Đề xuất của nhân sự đi ngược quyết định của Sếp -> Giữ nguyên trạng thái đề xuất, cấm ghi đè!
                        fact_status = FactStatus.PROPOSED
                        replaces_id = None
                        break

                    replaces_id = old_dict.get("id") or old_dict.get("_id")
                    break

        # Nếu replaces_id do LLM tự điền, kiểm tra lại Supersede Shield đối với fact của Owner
        if replaces_id and speaker_role == "member" and existing_facts:
            for old_f in existing_facts:
                old_dict = old_f.to_dict() if isinstance(old_f, Fact) else old_f
                fid = old_dict.get("id") or old_dict.get("_id")
                if fid == replaces_id:
                    old_asserted = old_dict.get("asserted_by") or {}
                    old_role = (old_asserted.get("role") if isinstance(old_asserted, dict) else getattr(old_asserted, "role", "member")) if old_asserted else "member"
                    if old_role == "owner":
                        fact_status = FactStatus.PROPOSED
                        replaces_id = None
                    break

        new_fact = Fact(
            id=generate_fact_id(),
            entity_id=entity_id,
            property=prop,
            value=value,
            status=fact_status,
            asserted_by=asserted_by,
            source=source_meta,
            replaces=replaces_id,
            created_at=now_iso,
            updated_at=now_iso,
        )
        facts.append(new_fact)

    # Khử trùng lặp cùng 1 (entity_id, property): giữ fact xuất hiện đầu tiên
    seen_keys: Dict[tuple, Fact] = {}
    for f in facts:
        key = (f.entity_id, f.property)
        if key not in seen_keys:
            seen_keys[key] = f
    deduped_facts = list(seen_keys.values())

    # Giới hạn an toàn (tối đa 5 facts quan trọng nhất)
    if len(deduped_facts) > 5:
        deduped_facts = deduped_facts[:5]

    return deduped_facts


# Backward compatibility alias
parse_claims = parse_facts


def extract_facts(
    query: str,
    entities: List[Union[Entity, Dict[str, Any]]],
    existing_facts: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
    source_message_id: Optional[str] = None,
    sender: Optional[str] = None,
    asserted_by: Optional[Union[AssertedBy, Dict[str, Any]]] = None,
    api_key: Optional[str] = None,
    client: Optional[GeminiClient] = None,
) -> Dict[str, Any]:
    """
    Trích xuất Nhánh 2: Facts (Sync).
    
    Returns:
        {
            "facts": [Fact dict...],              # Các facts mới trích xuất
            "superseded_facts": [Fact dict...],   # Các facts cũ vừa bị đánh dấu superseded
        }
    """
    if not entities:
        return {
            "facts": [],
            "superseded_facts": [],
            "claims": [],
            "superseded_claims": [],
        }

    llm_client = client or GeminiClient(api_key=api_key)

    entities_dicts = [e.to_dict() if isinstance(e, Entity) else e for e in entities]
    clean_entities = [
        {
            "id": e.get("id") or e.get("_id"),
            "name": e.get("name") or e.get("canonical_name"),
            "type": e.get("type") or e.get("entity_type"),
            "aliases": e.get("aliases", []),
            "description": e.get("description", ""),
        }
        for e in entities_dicts
    ]

    # Chỉ đưa các facts đang CURRENT vào context
    relevant_existing_facts = []
    if existing_facts:
        target_ids = {e.get("id") or e.get("_id") for e in clean_entities}
        for f in existing_facts:
            f_dict = f.to_dict() if isinstance(f, Fact) else f
            if f_dict.get("entity_id") in target_ids and f_dict.get("status") == FactStatus.CURRENT.value:
                relevant_existing_facts.append({
                    "id": f_dict.get("id") or f_dict.get("_id"),
                    "entity_id": f_dict.get("entity_id"),
                    "property": f_dict.get("property") or f_dict.get("predicate"),
                    "value": f_dict.get("value"),
                    "status": f_dict.get("status"),
                })

    now_vn_str = get_vietnam_now().strftime("%d/%m/%Y %H:%M:%S (UTC+7)")
    prompt = FACT_EXTRACTION_PROMPT.format(
        query=query,
        entities_json=json.dumps(clean_entities, ensure_ascii=False, indent=2),
        existing_facts_json=json.dumps(relevant_existing_facts, ensure_ascii=False, indent=2),
        source_message_id=source_message_id or "unknown_msg",
        sender=sender or "User",
        reference_time_vn=now_vn_str,
    )

    raw_response = llm_client.generate(prompt)
    new_facts = parse_facts(
        raw_response=raw_response,
        resolved_entities=entities_dicts,
        existing_facts=existing_facts,
        source_message_id=source_message_id,
        sender=sender,
        asserted_by=asserted_by,
    )

    # Cập nhật trạng thái superseded cho các fact cũ
    superseded_facts: List[Dict[str, Any]] = []
    now_iso = get_vietnam_now_iso()
    superseded_target_ids = {f.replaces for f in new_facts if f.replaces}

    if existing_facts and superseded_target_ids:
        for old_f in existing_facts:
            old_dict = old_f if isinstance(old_f, dict) else old_f.to_dict()
            fid = old_dict.get("id") or old_dict.get("_id")
            if fid in superseded_target_ids:
                old_dict["status"] = FactStatus.SUPERSEDED.value
                old_dict["updated_at"] = now_iso
                superseded_facts.append(old_dict)

    fact_dicts = [f.to_dict() for f in new_facts]
    return {
        "facts": fact_dicts,
        "superseded_facts": superseded_facts,
        # Backward compatibility
        "claims": fact_dicts,
        "superseded_claims": superseded_facts,
    }


# Backward compatibility alias
def extract_claims(query, entities, existing_claims=None, **kwargs):
    return extract_facts(query, entities, existing_facts=existing_claims, **kwargs)


async def extract_facts_async(
    query: str,
    entities: List[Union[Entity, Dict[str, Any]]],
    existing_facts: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
    source_message_id: Optional[str] = None,
    sender: Optional[str] = None,
    asserted_by: Optional[Union[AssertedBy, Dict[str, Any]]] = None,
    api_key: Optional[str] = None,
    client: Optional[GeminiClient] = None,
) -> Dict[str, Any]:
    """Trích xuất Nhánh 2: Facts (Async)."""
    if not entities:
        return {
            "facts": [],
            "superseded_facts": [],
            "claims": [],
            "superseded_claims": [],
        }

    llm_client = client or GeminiClient(api_key=api_key)

    entities_dicts = [e.to_dict() if isinstance(e, Entity) else e for e in entities]
    clean_entities = [
        {
            "id": e.get("id") or e.get("_id"),
            "name": e.get("name") or e.get("canonical_name"),
            "type": e.get("type") or e.get("entity_type"),
            "aliases": e.get("aliases", []),
            "description": e.get("description", ""),
        }
        for e in entities_dicts
    ]

    relevant_existing_facts = []
    if existing_facts:
        target_ids = {e.get("id") or e.get("_id") for e in clean_entities}
        for f in existing_facts:
            f_dict = f.to_dict() if isinstance(f, Fact) else f
            if f_dict.get("entity_id") in target_ids and f_dict.get("status") == FactStatus.CURRENT.value:
                relevant_existing_facts.append({
                    "id": f_dict.get("id") or f_dict.get("_id"),
                    "entity_id": f_dict.get("entity_id"),
                    "property": f_dict.get("property") or f_dict.get("predicate"),
                    "value": f_dict.get("value"),
                    "status": f_dict.get("status"),
                })

    now_vn_str = get_vietnam_now().strftime("%d/%m/%Y %H:%M:%S (UTC+7)")
    prompt = FACT_EXTRACTION_PROMPT.format(
        query=query,
        entities_json=json.dumps(clean_entities, ensure_ascii=False, indent=2),
        existing_facts_json=json.dumps(relevant_existing_facts, ensure_ascii=False, indent=2),
        source_message_id=source_message_id or "unknown_msg",
        sender=sender or "User",
        reference_time_vn=now_vn_str,
    )

    raw_response = await llm_client.generate_async(prompt)
    new_facts = parse_facts(
        raw_response=raw_response,
        resolved_entities=entities_dicts,
        existing_facts=existing_facts,
        source_message_id=source_message_id,
        sender=sender,
        asserted_by=asserted_by,
    )

    superseded_facts: List[Dict[str, Any]] = []
    now_iso = get_vietnam_now_iso()
    superseded_target_ids = {f.replaces for f in new_facts if f.replaces}

    if existing_facts and superseded_target_ids:
        for old_f in existing_facts:
            old_dict = old_f if isinstance(old_f, dict) else old_f.to_dict()
            fid = old_dict.get("id") or old_dict.get("_id")
            if fid in superseded_target_ids:
                old_dict["status"] = FactStatus.SUPERSEDED.value
                old_dict["updated_at"] = now_iso
                superseded_facts.append(old_dict)

    fact_dicts = [f.to_dict() for f in new_facts]
    return {
        "facts": fact_dicts,
        "superseded_facts": superseded_facts,
        # Backward compatibility
        "claims": fact_dicts,
        "superseded_claims": superseded_facts,
    }


# Backward compatibility alias
async def extract_claims_async(query, entities, existing_claims=None, **kwargs):
    return await extract_facts_async(query, entities, existing_facts=existing_claims, **kwargs)


# ==============================================================================
# 8. LLM EXTRACTOR CLASS
# ==============================================================================

class LLMExtractor:
    """
    Bộ bóc tách tổng hợp hoàn chỉnh:
      - Nhánh 1: Entities (Thực thể chuẩn, aliases, mô tả)
      - Nhánh 2: Facts (Mệnh đề thông tin, audit trail, replaces, trạng thái)
    """

    def __init__(self, api_key: Optional[str] = None):
        self.client = GeminiClient(api_key=api_key)

    def extract_entities(
        self,
        query: str,
        workspace_id: str = "default",
        source_message_id: Optional[str] = None,
        existing_entities: Optional[List[Union[Entity, Dict[str, Any]]]] = None,
        existing_facts: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
    ) -> List[Dict[str, Any]]:
        """Bóc tách riêng Nhánh 1: Entities."""
        return extract_entities(
            query=query,
            workspace_id=workspace_id,
            source_message_id=source_message_id,
            existing_entities=existing_entities,
            existing_facts=existing_facts,
            client=self.client,
        )

    # Alias
    extract_memory = extract_entities

    async def extract_entities_async(
        self,
        query: str,
        workspace_id: str = "default",
        source_message_id: Optional[str] = None,
        existing_entities: Optional[List[Union[Entity, Dict[str, Any]]]] = None,
        existing_facts: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
    ) -> List[Dict[str, Any]]:
        """Bóc tách riêng Nhánh 1: Entities (Async)."""
        return await extract_entities_async(
            query=query,
            workspace_id=workspace_id,
            source_message_id=source_message_id,
            existing_entities=existing_entities,
            existing_facts=existing_facts,
            client=self.client,
        )

    # Alias
    extract_memory_async = extract_entities_async

    def extract_facts(
        self,
        query: str,
        entities: List[Union[Entity, Dict[str, Any]]],
        existing_facts: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
        source_message_id: Optional[str] = None,
        sender: Optional[str] = None,
        asserted_by: Optional[Union[AssertedBy, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Bóc tách riêng Nhánh 2: Facts."""
        return extract_facts(
            query=query,
            entities=entities,
            existing_facts=existing_facts,
            source_message_id=source_message_id,
            sender=sender,
            asserted_by=asserted_by,
            client=self.client,
        )

    # Alias
    extract_claims = extract_facts

    async def extract_facts_async(
        self,
        query: str,
        entities: List[Union[Entity, Dict[str, Any]]],
        existing_facts: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
        source_message_id: Optional[str] = None,
        sender: Optional[str] = None,
        asserted_by: Optional[Union[AssertedBy, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Bóc tách riêng Nhánh 2: Facts (Async)."""
        return await extract_facts_async(
            query=query,
            entities=entities,
            existing_facts=existing_facts,
            source_message_id=source_message_id,
            sender=sender,
            asserted_by=asserted_by,
            client=self.client,
        )

    # Alias
    extract_claims_async = extract_facts_async

    def extract(
        self,
        query: str,
        workspace_id: str = "default",
        source_message_id: Optional[str] = None,
        sender: Optional[str] = None,
        asserted_by: Optional[Union[AssertedBy, Dict[str, Any]]] = None,
        existing_entities: Optional[List[Union[Entity, Dict[str, Any]]]] = None,
        existing_facts: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
        # Legacy keyword compatibility
        existing_claims: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """
        Bóc tách toàn diện một câu truy vấn/tin nhắn thành cả 2 nhánh (Sync):
          - Nhánh 1 (Entities): Trích xuất & chuẩn hoá entities (sử dụng existing_facts để giải quyết coreference)
          - Nhánh 2 (Facts): Trích xuất facts gắn với entity_id chuẩn, xử lý quan hệ replaces
        """
        current_existing_facts = existing_facts if existing_facts is not None else existing_claims

        # Bước 1: Trích xuất Nhánh 1 (Entities) - truyền existing_facts để nhận diện tham chiếu gián tiếp
        entities_result = self.extract_entities(
            query=query,
            workspace_id=workspace_id,
            source_message_id=source_message_id,
            existing_entities=existing_entities,
            existing_facts=current_existing_facts,
        )

        all_entities = list(existing_entities or []) + entities_result

        # Bước 2: Trích xuất Nhánh 2 (Facts)
        facts_result = self.extract_facts(
            query=query,
            entities=all_entities,
            existing_facts=current_existing_facts,
            source_message_id=source_message_id,
            sender=sender,
            asserted_by=asserted_by,
        )

        new_facts = facts_result.get("facts", [])
        superseded_facts = facts_result.get("superseded_facts", [])

        return {
            "entities": entities_result,
            "facts": new_facts,
            "superseded_facts": superseded_facts,
            # Backward compatibility
            "memory": entities_result,
            "claims": new_facts,
            "superseded_claims": superseded_facts,
        }

    async def extract_async(
        self,
        query: str,
        workspace_id: str = "default",
        source_message_id: Optional[str] = None,
        sender: Optional[str] = None,
        asserted_by: Optional[Union[AssertedBy, Dict[str, Any]]] = None,
        existing_entities: Optional[List[Union[Entity, Dict[str, Any]]]] = None,
        existing_facts: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
        # Legacy keyword compatibility
        existing_claims: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """Bóc tách toàn diện cả 2 nhánh (Async)."""
        current_existing_facts = existing_facts if existing_facts is not None else existing_claims

        entities_result = await self.extract_entities_async(
            query=query,
            workspace_id=workspace_id,
            source_message_id=source_message_id,
            existing_entities=existing_entities,
            existing_facts=current_existing_facts,
        )

        all_entities = list(existing_entities or []) + entities_result

        facts_result = await self.extract_facts_async(
            query=query,
            entities=all_entities,
            existing_facts=current_existing_facts,
            source_message_id=source_message_id,
            sender=sender,
            asserted_by=asserted_by,
        )

        new_facts = facts_result.get("facts", [])
        superseded_facts = facts_result.get("superseded_facts", [])

        return {
            "entities": entities_result,
            "facts": new_facts,
            "superseded_facts": superseded_facts,
            # Backward compatibility
            "memory": entities_result,
            "claims": new_facts,
            "superseded_claims": superseded_facts,
        }


# Global instance
llm_extractor = LLMExtractor()


def extract(
    query: str,
    workspace_id: str = "default",
    source_message_id: Optional[str] = None,
    sender: Optional[str] = None,
    asserted_by: Optional[Union[AssertedBy, Dict[str, Any]]] = None,
    existing_entities: Optional[List[Union[Entity, Dict[str, Any]]]] = None,
    existing_facts: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
    existing_claims: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Hàm tiện ích cấp module: bóc tách toàn diện 2 nhánh (Sync)."""
    extractor = LLMExtractor(api_key=api_key) if api_key else llm_extractor
    return extractor.extract(
        query=query,
        workspace_id=workspace_id,
        source_message_id=source_message_id,
        sender=sender,
        asserted_by=asserted_by,
        existing_entities=existing_entities,
        existing_facts=existing_facts,
        existing_claims=existing_claims,
    )


async def extract_async(
    query: str,
    workspace_id: str = "default",
    source_message_id: Optional[str] = None,
    sender: Optional[str] = None,
    asserted_by: Optional[Union[AssertedBy, Dict[str, Any]]] = None,
    existing_entities: Optional[List[Union[Entity, Dict[str, Any]]]] = None,
    existing_facts: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
    existing_claims: Optional[List[Union[Fact, Dict[str, Any]]]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Hàm tiện ích cấp module: bóc tách toàn diện 2 nhánh (Async)."""
    extractor = LLMExtractor(api_key=api_key) if api_key else llm_extractor
    return await extractor.extract_async(
        query=query,
        workspace_id=workspace_id,
        source_message_id=source_message_id,
        sender=sender,
        asserted_by=asserted_by,
        existing_entities=existing_entities,
        existing_facts=existing_facts,
        existing_claims=existing_claims,
    )


# ==============================================================================
# 9. STORAGE HELPERS (PERSISTENCE) - MONGODB SINGLE SOURCE OF TRUTH
# ==============================================================================


def load_stored_entities() -> List[Dict[str, Any]]:
    """Tải danh sách entities từ MongoDB (Single Source of Truth)."""
    try:
        from database.db import get_all_entities_sync
        return get_all_entities_sync()
    except Exception as e:
        logger.warning(f"Không thể nạp entities từ MongoDB: {e}")
        return []


def load_stored_facts(
    entity_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    project_tag: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Tải danh sách facts từ MongoDB (Single Source of Truth) có lọc theo scope."""
    try:
        from database.db import get_all_facts_sync
        return get_all_facts_sync(entity_id=entity_id, chat_id=chat_id, project_tag=project_tag)
    except Exception as e:
        logger.warning(f"Không thể nạp facts từ MongoDB: {e}")
        return []


# Backward compatibility
load_stored_claims = load_stored_facts


def save_stored_entities(entities: List[Dict[str, Any]]) -> None:
    """Lưu danh sách entities vào MongoDB (Single Source of Truth)."""
    try:
        from database.db import upsert_entity_sync
        for ent in entities:
            upsert_entity_sync(ent)
    except Exception as e:
        logger.warning(f"Không thể lưu entities vào MongoDB: {e}")


def save_stored_facts(facts: List[Dict[str, Any]]) -> None:
    """Lưu danh sách facts vào MongoDB (Single Source of Truth)."""
    try:
        from database.db import get_sync_claims_collection
        claims_col = get_sync_claims_collection()
        for fact in facts:
            fid = fact.get("id")
            if not fid:
                continue
            fact_copy = dict(fact)
            fact_copy.pop("_id", None)
            claims_col.update_one({"id": fid}, {"$set": fact_copy}, upsert=True)
    except Exception as e:
        logger.warning(f"Không thể lưu facts vào MongoDB: {e}")


# Backward compatibility
save_stored_claims = save_stored_facts


def clear_stores() -> None:
    """Xóa sạch bộ nhớ lưu trữ entities và facts trên MongoDB."""
    try:
        from database.db import clear_mongo_stores_sync
        clear_mongo_stores_sync()
    except Exception as e:
        logger.warning(f"Không thể xóa stores trên MongoDB: {e}")



def apply_and_save_extraction(
    extraction_result: Dict[str, Any],
    chat_id: Optional[str] = None,
    project_tag: Optional[str] = None,
    scope_type: str = "chat",
) -> Dict[str, Any]:
    """
    Cập nhật kết quả trích xuất trực tiếp vào MongoDB (Single Source of Truth).
    Ủy quyền cho save_extraction_to_mongo_sync.
    """
    from database.db import save_extraction_to_mongo_sync
    return save_extraction_to_mongo_sync(
        extraction_result,
        chat_id=chat_id,
        project_tag=project_tag,
        scope_type=scope_type,
    )

