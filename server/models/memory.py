from __future__ import annotations

from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

# Múi giờ Việt Nam (UTC+7 / ICT)
VIETNAM_TZ = timezone(timedelta(hours=7))


def get_vietnam_now() -> datetime:
    """Lấy thời gian hiện tại theo múi giờ Việt Nam (UTC+7)."""
    return datetime.now(VIETNAM_TZ)


def get_vietnam_now_iso() -> str:
    """Lấy chuỗi ISO timestamp theo chuẩn giờ Việt Nam (UTC+7, ví dụ: 2026-10-11T23:55:00+07:00)."""
    return datetime.now(VIETNAM_TZ).isoformat()


class EntityStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MERGED = "merged"


class FactStatus(str, Enum):
    """Status of a fact/claim about an entity."""
    CURRENT = "current"        # Active, valid information (decision by owner or confirmed fact)
    PROPOSED = "proposed"      # Proposal, request or unconfirmed claim from team member
    SUPERSEDED = "superseded"  # Replaced by a newer fact
    CONFLICTED = "conflicted"  # Direct contradiction across sources
    UNCERTAIN = "uncertain"    # Ambiguous, speculative, unconfirmed
    REVOKED = "revoked"        # Thu hồi do tin nhắn gốc bị thu hồi


class AssertedBy(BaseModel):
    """
    Thông tin người phát ngôn / khẳng định Fact và vai trò thẩm quyền.
    role: 'owner' (CEO/Founder/Sếp - Nguồn sự thật tối cao) | 'member' (Nhân sự - Đề xuất/Báo cáo).
    """
    user_id: Optional[str] = Field(default=None, description="Open ID của người nói trên Lark")
    user_name: Optional[str] = Field(default=None, description="Tên hiển thị của người nói")
    role: str = Field(default="member", description="'owner' (CEO/Founder) hoặc 'member' (Nhân sự)")

    model_config = {"use_enum_values": True}

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class Entity(BaseModel):
    """
    A recognized business entity (project, person, team, customer, feature, document).
    
    Fields:
      - id: Stable deterministic ID (e.g. ent_abc123)
      - name: Standardized name of the entity
      - type: project, person, team, customer, feature, document
      - aliases: Alternative names with clear evidence
      - description: One-sentence context summary
    """
    id: str = Field(..., description="Stable entity ID (e.g. ent_abc123)")
    workspace_id: str = Field(default="default")
    name: str = Field(..., description="Standardized name of the entity")
    type: str = Field(..., description="project, person, team, customer, feature, document")
    aliases: List[str] = Field(default_factory=list)
    description: str = Field(default="")
    attributes: Dict[str, Any] = Field(default_factory=dict)
    status: EntityStatus = Field(default=EntityStatus.ACTIVE)
    chat_id: Optional[str] = Field(default=None, description="Lark chat_id nơi thực thể được khởi tạo/đề cập")
    project_tag: Optional[str] = Field(default=None, description="Tên/Mã dự án liên kết")
    scope_type: str = Field(default="chat", description="'chat' (nội bộ nhóm), 'project' (dự án), 'global' (toàn công ty)")
    source_message_ids: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=get_vietnam_now_iso)
    updated_at: str = Field(default_factory=get_vietnam_now_iso)

    model_config = {"use_enum_values": True}

    def to_dict(self) -> Dict[str, Any]:
        data = self.model_dump()
        if not data.get("attributes"):
            data.pop("attributes", None)
        return data


class Fact(BaseModel):
    """
    A single piece of factual information about an Entity.
    Answers: "What was stated, about which entity, is it still valid, who asserted it, and where did it come from?"
    
    Fields:
      - id: Unique fact ID (e.g. fact_abc123)
      - entity_id: ID of the parent entity this fact belongs to
      - property: Business attribute (deadline, assignee, status, budget, scope...)
      - value: Concise value (e.g. "30/10", "Nam", "200M VND")
      - status: current, proposed, superseded, conflicted, uncertain
      - chat_id: Lark chat_id (e.g. oc_xxx) nơi phát sinh mệnh đề
      - project_tag: Tên/Mã dự án của nhóm chat
      - scope_type: 'chat' | 'project' | 'global'
      - asserted_by: Metadata về người phát ngôn (user_id, user_name, role='owner'|'member')
      - source: Evidence (snippet text or metadata dict)
      - replaces: ID of the old fact this one replaces (or None)
    """
    id: str = Field(..., description="Unique fact ID (e.g. fact_abc123)")
    entity_id: str = Field(..., description="ID of the parent entity")
    property: str = Field(..., description="Business attribute: deadline, assignee, status, budget, scope")
    value: Any = Field(..., description="Concise value")
    status: FactStatus = Field(default=FactStatus.CURRENT)
    chat_id: Optional[str] = Field(default=None, description="Lark chat_id (oc_xxx) nơi phát ngôn mệnh đề")
    project_tag: Optional[str] = Field(default=None, description="Tên/Mã dự án liên kết")
    scope_type: str = Field(default="chat", description="'chat' (nội bộ nhóm), 'project' (dự án), 'global' (toàn công ty)")
    asserted_by: Optional[Union[AssertedBy, Dict[str, Any]]] = Field(
        default=None,
        description="Người khẳng định fact và thẩm quyền phát ngôn ('owner' vs 'member')"
    )
    source: Union[str, Dict[str, Any]] = Field(default="")
    replaces: Optional[str] = Field(default=None, description="ID of old fact this one replaces")
    created_at: str = Field(default_factory=get_vietnam_now_iso)
    updated_at: str = Field(default_factory=get_vietnam_now_iso)

    model_config = {"use_enum_values": True}

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


def build_entity_tree(
    entities: List[Union[Entity, Dict[str, Any]]],
    facts: List[Union[Fact, Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """
    Group flat entities + facts into a Parent-Child tree:
      Each Entity is a parent node containing:
        - active_facts: Facts currently valid (current, uncertain, conflicted)
        - history_facts: Old facts that have been replaced (superseded)
    """
    nodes: Dict[str, Dict[str, Any]] = {}
    for ent in entities:
        if isinstance(ent, Entity):
            node = ent.to_dict()
        else:
            node = dict(ent)
        node["active_facts"] = []
        node["history_facts"] = []
        nodes[node["id"]] = node

    for f in facts:
        if isinstance(f, Fact):
            fd = f.to_dict()
        else:
            fd = dict(f)

        eid = fd.get("entity_id")
        target = nodes.get(eid)
        if target:
            if fd.get("status") == "superseded":
                target["history_facts"].append(fd)
            else:
                target["active_facts"].append(fd)

    return list(nodes.values())


# Compatibility aliases
build_hierarchical_memory = build_entity_tree
MemoryEntity = Entity
Claim = Fact
ClaimStatus = FactStatus
