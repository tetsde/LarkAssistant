"""
Data models for the benchmark dataset.
All entity types, relationship types, and benchmark question structures.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Entity Types
# ---------------------------------------------------------------------------
class EntityType(str, Enum):
    USER = "User"
    DEPARTMENT = "Department"
    TEAM = "Team"
    PROJECT = "Project"
    CUSTOMER = "Customer"
    TASK = "Task"
    MEETING = "Meeting"
    MESSAGE = "Message"
    DOCUMENT = "Document"
    DECISION = "Decision"
    ISSUE = "Issue"
    CAMPAIGN = "Campaign"


class RelationshipType(str, Enum):
    MEMBER_OF = "member_of"
    BELONGS_TO = "belongs_to"
    RESPONSIBLE_FOR = "responsible_for"
    WORKS_WITH = "works_with"
    HAS_TASK = "has_task"
    HAS_MEETING = "has_meeting"
    HAS_DOCUMENT = "has_document"
    HAS_ISSUE = "has_issue"
    SENT_BY = "sent_by"
    MENTIONS = "mentions"
    DISCUSSES = "discusses"
    RELATED_TO = "related_to"
    INVOLVES = "involves"
    RESULTS_IN = "results_in"
    CREATES = "creates"
    AFFECTS = "affects"
    CHANGES = "changes"
    ASSIGNED_TO = "assigned_to"
    REPORTED_BY = "reported_by"
    BLOCKS = "blocks"
    SOURCE_OF = "source_of"
    REFERENCES = "references"
    TARGETS = "targets"


# ---------------------------------------------------------------------------
# Entity models
# ---------------------------------------------------------------------------
class Entity(BaseModel):
    id: str
    type: EntityType
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Relationship(BaseModel):
    source_id: str
    target_id: str
    type: RelationshipType
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Concrete entity models (for richer dataset generation)
# ---------------------------------------------------------------------------
class UserEntity(Entity):
    type: EntityType = EntityType.USER
    email: str = ""
    role: str = ""


class DepartmentEntity(Entity):
    type: EntityType = EntityType.DEPARTMENT
    description: str = ""


class TeamEntity(Entity):
    type: EntityType = EntityType.TEAM
    focus_area: str = ""


class ProjectEntity(Entity):
    type: EntityType = EntityType.PROJECT
    status: str = ""
    priority: str = ""
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None


class CustomerEntity(Entity):
    type: EntityType = EntityType.CUSTOMER
    industry: str = ""
    tier: str = ""


class TaskEntity(Entity):
    type: EntityType = EntityType.TASK
    status: str = ""
    priority: str = ""
    due_date: Optional[datetime] = None


class MeetingEntity(Entity):
    type: EntityType = EntityType.MEETING
    date: Optional[datetime] = None
    duration_minutes: int = 60
    summary: str = ""
    agenda: str = ""


class MessageEntity(Entity):
    type: EntityType = EntityType.MESSAGE
    content: str = ""
    channel: str = ""
    timestamp: Optional[datetime] = None


class DocumentEntity(Entity):
    type: EntityType = EntityType.DOCUMENT
    doc_type: str = ""
    content: str = ""
    version: str = "1.0"


class DecisionEntity(Entity):
    type: EntityType = EntityType.DECISION
    description: str = ""
    rationale: str = ""
    status: str = ""
    date: Optional[datetime] = None


class IssueEntity(Entity):
    type: EntityType = EntityType.ISSUE
    severity: str = ""
    status: str = ""
    description: str = ""
    reported_date: Optional[datetime] = None
    resolved_date: Optional[datetime] = None


class CampaignEntity(Entity):
    type: EntityType = EntityType.CAMPAIGN
    campaign_type: str = ""
    status: str = ""
    budget: float = 0.0
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    target_audience: str = ""


# ---------------------------------------------------------------------------
# Question difficulty
# ---------------------------------------------------------------------------
class QuestionDifficulty(str, Enum):
    SINGLE_HOP = "single_hop"
    TWO_HOP = "two_hop"
    MULTI_HOP = "multi_hop"
    TEMPORAL = "temporal"
    CROSS_SOURCE = "cross_source"
    AGGREGATION = "aggregation"
    RELATIONSHIP = "relationship"
    EXECUTIVE = "executive"
    DISTRACTOR = "distractor"


class BenchmarkQuestion(BaseModel):
    """A single benchmark question with full ground truth."""
    question_id: str
    question: str
    difficulty: QuestionDifficulty
    category: str = ""
    required_entities: list[str] = Field(default_factory=list)
    required_relationships: list[str] = Field(default_factory=list)
    ground_truth_answer: str
    ground_truth_sources: list[str] = Field(default_factory=list)
    hop_count: int = 1
    distractor_entities: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Dataset container
# ---------------------------------------------------------------------------
class Dataset(BaseModel):
    """Full benchmark dataset."""
    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    questions: list[BenchmarkQuestion] = Field(default_factory=list)
    version: str = "1.0.0"
    seed: int = 42
    generated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Benchmark result models
# ---------------------------------------------------------------------------
class TimingBreakdown(BaseModel):
    query_understanding_ms: float = 0.0
    retrieval_ms: float = 0.0
    context_building_ms: float = 0.0
    generation_ms: float = 0.0
    total_latency_ms: float = 0.0


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    embedding_tokens: int = 0


class RetrievalResult(BaseModel):
    retrieved_entity_ids: list[str] = Field(default_factory=list)
    retrieved_source_ids: list[str] = Field(default_factory=list)
    retrieved_relationships: list[str] = Field(default_factory=list)
    context_text: str = ""
    num_sql_queries: int = 0
    num_graph_operations: int = 0
    num_vector_searches: int = 0
    num_llm_calls: int = 0


class QueryResult(BaseModel):
    """Result of a single query against one system."""
    question_id: str
    system_name: str
    run_index: int = 0
    answer: str = ""
    timing: TimingBreakdown = Field(default_factory=TimingBreakdown)
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    retrieval: RetrievalResult = Field(default_factory=RetrievalResult)
    error: Optional[str] = None


class JudgeScore(BaseModel):
    correct: bool = False
    score: float = 0.0
    reason: str = ""
    entity_recall: float = 0.0
    relationship_recall: float = 0.0
    source_recall: float = 0.0


class EvaluatedResult(BaseModel):
    """QueryResult with evaluation scores attached."""
    query_result: QueryResult
    judge: JudgeScore = Field(default_factory=JudgeScore)


class SystemBuildMetrics(BaseModel):
    """Metrics captured during the knowledge construction phase."""
    system_name: str
    ingestion_time_seconds: float = 0.0
    indexing_time_seconds: float = 0.0
    llm_processing_time_seconds: float = 0.0
    llm_tokens: TokenUsage = Field(default_factory=TokenUsage)
    construction_cost: float = 0.0
    storage_size_bytes: int = 0


class BenchmarkRun(BaseModel):
    """A full benchmark run record for reproducibility."""
    timestamp: str = ""
    dataset_version: str = ""
    model: str = ""
    embedding_model: str = ""
    temperature: float = 0.0
    seed: int = 42
    question_count: int = 0
    runs_per_question: int = 3
    build_metrics: list[SystemBuildMetrics] = Field(default_factory=list)
    results: list[EvaluatedResult] = Field(default_factory=list)
