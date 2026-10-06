"""
PostgreSQL + RAG retrieval system.

Uses SQLite as local drop-in (same SQL semantics for prototyping).
Can switch to PostgreSQL + pgvector by changing DATABASE_URL in .env.

Pipeline:
  User Query → LLM Query Understanding → SQL → Entity Retrieval
  → Vector Search → Context Assembly → LLM → Answer
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

from benchmark.config import Config
from benchmark.llm_client import EmbeddingClient, LLMClient
from benchmark.models import (
    Dataset,
    Entity,
    QueryResult,
    Relationship,
    RetrievalResult,
    SystemBuildMetrics,
    TimingBreakdown,
    TokenUsage,
)
from systems.base import BaseRetrievalSystem


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    dot = np.dot(a_arr, b_arr)
    norm = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    return float(dot / norm) if norm > 0 else 0.0


class PostgresRAGSystem(BaseRetrievalSystem):
    """
    SQL + Vector Search retrieval system.

    Build phase:
      - Store entities, relationships, messages, documents in SQLite/PostgreSQL
      - Generate embeddings for text content
      - Build in-memory vector index

    Query phase:
      - LLM understands the question and generates SQL query plan
      - Execute SQL to find relevant entities
      - Vector search to find relevant text chunks
      - Assemble context and generate answer
    """

    def __init__(self, config: Config, db_path: Optional[Path] = None):
        self._config = config
        self._db_path = db_path or Path("data/benchmark.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._llm = LLMClient(config.llm, config.pricing)
        self._embedder = EmbeddingClient(config.embedding, config.pricing)
        self._embeddings: dict[str, list[float]] = {}  # id -> embedding
        self._texts: dict[str, str] = {}  # id -> text content

    @property
    def name(self) -> str:
        return "PostgreSQL + RAG"

    def _init_db(self):
        if self._conn:
            self._conn.close()
        if self._db_path.exists():
            os.remove(self._db_path)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.cursor()

        cur.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                attributes TEXT DEFAULT '{}',
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                type TEXT NOT NULL,
                attributes TEXT DEFAULT '{}',
                created_at TEXT,
                FOREIGN KEY (source_id) REFERENCES entities(id),
                FOREIGN KEY (target_id) REFERENCES entities(id)
            );

            CREATE TABLE IF NOT EXISTS text_content (
                id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                content TEXT NOT NULL,
                content_type TEXT,
                created_at TEXT,
                FOREIGN KEY (entity_id) REFERENCES entities(id)
            );

            CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
            CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
            CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_id);
            CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_id);
            CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(type);
            CREATE INDEX IF NOT EXISTS idx_text_entity ON text_content(entity_id);
        """)
        self._conn.commit()

    def build(self, dataset: Dataset) -> SystemBuildMetrics:
        start = time.perf_counter()
        self._init_db()
        cur = self._conn.cursor()

        # Insert entities
        for e in dataset.entities:
            attrs = e.attributes.copy()
            # Merge extra fields into attributes
            raw = e.model_dump(mode="json")
            for k, v in raw.items():
                if k not in ("id", "type", "name", "attributes", "created_at", "updated_at"):
                    attrs[k] = v
            cur.execute(
                "INSERT OR REPLACE INTO entities (id, type, name, attributes, created_at) VALUES (?, ?, ?, ?, ?)",
                (e.id, e.type.value if hasattr(e.type, 'value') else str(e.type),
                 e.name, json.dumps(attrs, ensure_ascii=False, default=str),
                 str(e.created_at) if e.created_at else None),
            )

        # Insert relationships
        for r in dataset.relationships:
            cur.execute(
                "INSERT INTO relationships (source_id, target_id, type, attributes, created_at) VALUES (?, ?, ?, ?, ?)",
                (r.source_id, r.target_id,
                 r.type.value if hasattr(r.type, 'value') else str(r.type),
                 json.dumps(r.attributes, ensure_ascii=False, default=str),
                 str(r.created_at) if r.created_at else None),
            )

        # Extract text content for embedding
        text_items: list[tuple[str, str, str, str]] = []
        for e in dataset.entities:
            raw = e.model_dump(mode="json")
            content_parts = [f"{e.name}"]
            for field in ["content", "description", "summary", "agenda", "rationale", "doc_type"]:
                if field in raw and raw[field]:
                    content_parts.append(str(raw[field]))
            if raw.get("attributes"):
                for k, v in raw["attributes"].items():
                    if isinstance(v, str) and len(v) > 5:
                        content_parts.append(f"{k}: {v}")
            content = "\n".join(content_parts)
            if len(content) > 20:
                text_items.append((e.id, e.id, content, e.type.value if hasattr(e.type, 'value') else str(e.type)))
                self._texts[e.id] = content

        for tid, eid, content, ctype in text_items:
            cur.execute(
                "INSERT OR REPLACE INTO text_content (id, entity_id, content, content_type) VALUES (?, ?, ?, ?)",
                (tid, eid, content, ctype),
            )

        self._conn.commit()
        ingest_time = time.perf_counter() - start

        # Generate embeddings
        embed_start = time.perf_counter()
        total_embed_tokens = 0
        batch_size = 50
        text_ids = list(self._texts.keys())
        text_values = [self._texts[tid] for tid in text_ids]

        for i in range(0, len(text_values), batch_size):
            batch = text_values[i:i + batch_size]
            batch_ids = text_ids[i:i + batch_size]
            try:
                embeddings, tokens = self._embedder.embed(batch)
                total_embed_tokens += tokens
                for eid, emb in zip(batch_ids, embeddings):
                    self._embeddings[eid] = emb
            except Exception as e:
                print(f"  [PostgresRAG] Embedding batch {i} failed: {e}")
                # Store zero vectors as fallback
                for eid in batch_ids:
                    self._embeddings[eid] = [0.0] * 256

        embed_time = time.perf_counter() - embed_start
        total_time = time.perf_counter() - start

        storage_size = self._db_path.stat().st_size if self._db_path.exists() else 0

        return SystemBuildMetrics(
            system_name=self.name,
            ingestion_time_seconds=ingest_time,
            indexing_time_seconds=embed_time,
            llm_processing_time_seconds=0.0,
            llm_tokens=TokenUsage(embedding_tokens=total_embed_tokens),
            construction_cost=self._embedder.estimate_cost(total_embed_tokens),
            storage_size_bytes=storage_size,
        )

    def _vector_search(self, query_embedding: list[float], top_k: int = 10) -> list[tuple[str, float]]:
        """Find top-k most similar entities by cosine similarity."""
        scores = []
        for eid, emb in self._embeddings.items():
            sim = cosine_similarity(query_embedding, emb)
            scores.append((eid, sim))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def _sql_search(self, query_plan: dict) -> list[dict]:
        """Execute SQL queries based on the LLM's query plan."""
        results = []
        cur = self._conn.cursor()

        # Search by entity names mentioned in the query
        if "entity_names" in query_plan:
            for name in query_plan["entity_names"]:
                cur.execute(
                    "SELECT * FROM entities WHERE name LIKE ? OR name = ?",
                    (f"%{name}%", name),
                )
                for row in cur.fetchall():
                    results.append(dict(row))

        # Search by entity types
        if "entity_types" in query_plan:
            for etype in query_plan["entity_types"]:
                cur.execute("SELECT * FROM entities WHERE type = ?", (etype,))
                for row in cur.fetchall():
                    results.append(dict(row))

        # Search relationships
        if "relationship_queries" in query_plan:
            for rq in query_plan["relationship_queries"]:
                source = rq.get("source_id", "")
                target = rq.get("target_id", "")
                rtype = rq.get("type", "")
                if source:
                    cur.execute(
                        "SELECT r.*, e.name as target_name, e.type as target_type, e.attributes as target_attrs "
                        "FROM relationships r JOIN entities e ON r.target_id = e.id "
                        "WHERE r.source_id = ? AND (? = '' OR r.type = ?)",
                        (source, rtype, rtype),
                    )
                elif target:
                    cur.execute(
                        "SELECT r.*, e.name as source_name, e.type as source_type, e.attributes as source_attrs "
                        "FROM relationships r JOIN entities e ON r.source_id = e.id "
                        "WHERE r.target_id = ? AND (? = '' OR r.type = ?)",
                        (target, rtype, rtype),
                    )
                for row in cur.fetchall():
                    results.append(dict(row))

        # Full-text search in content
        if "keywords" in query_plan:
            for kw in query_plan["keywords"]:
                cur.execute(
                    "SELECT tc.*, e.name, e.type FROM text_content tc "
                    "JOIN entities e ON tc.entity_id = e.id "
                    "WHERE tc.content LIKE ?",
                    (f"%{kw}%",),
                )
                for row in cur.fetchall():
                    results.append(dict(row))

        return results

    def _expand_context(self, entity_ids: list[str], depth: int = 2) -> list[dict]:
        """Expand context by following relationships from found entities."""
        cur = self._conn.cursor()
        visited = set(entity_ids)
        context = []

        current = list(entity_ids)
        for _ in range(depth):
            next_level = []
            for eid in current:
                # Outgoing relationships
                cur.execute(
                    "SELECT r.type, r.target_id, e.name, e.type as entity_type, e.attributes "
                    "FROM relationships r JOIN entities e ON r.target_id = e.id "
                    "WHERE r.source_id = ?",
                    (eid,),
                )
                for row in cur.fetchall():
                    row_dict = dict(row)
                    context.append(row_dict)
                    if row_dict["target_id"] not in visited:
                        visited.add(row_dict["target_id"])
                        next_level.append(row_dict["target_id"])

                # Incoming relationships
                cur.execute(
                    "SELECT r.type, r.source_id, e.name, e.type as entity_type, e.attributes "
                    "FROM relationships r JOIN entities e ON r.source_id = e.id "
                    "WHERE r.target_id = ?",
                    (eid,),
                )
                for row in cur.fetchall():
                    row_dict = dict(row)
                    context.append(row_dict)
                    if row_dict["source_id"] not in visited:
                        visited.add(row_dict["source_id"])
                        next_level.append(row_dict["source_id"])
            current = next_level

        return context

    def query(self, question: str, question_id: str = "") -> QueryResult:
        total_tokens = TokenUsage()
        retrieval = RetrievalResult()
        timing = TimingBreakdown()

        # --- Step 1: Query Understanding ---
        t0 = time.perf_counter()
        plan_prompt = f"""Analyze this question and create a query plan. Return valid JSON only.

Question: {question}

Return a JSON object with these fields:
- "entity_names": list of entity names mentioned or implied
- "entity_types": list of entity types to search (e.g., "Project", "User", "Team", "Issue", "Campaign")
- "keywords": list of important keywords for text search
- "relationship_queries": list of objects with "source_id" or "target_id" and optional "type"
- "needs_aggregation": boolean
- "needs_temporal": boolean
- "time_filter": optional date string if temporal

Only return the JSON, no explanation."""

        plan_text, plan_tokens, plan_time = self._llm.chat(
            [{"role": "user", "content": plan_prompt}],
            response_format={"type": "json_object"},
        )
        total_tokens.input_tokens += plan_tokens.input_tokens
        total_tokens.output_tokens += plan_tokens.output_tokens
        retrieval.num_llm_calls += 1
        timing.query_understanding_ms = plan_time * 1000

        try:
            query_plan = json.loads(plan_text)
        except json.JSONDecodeError:
            query_plan = {"entity_names": [], "keywords": question.split(), "entity_types": []}

        # --- Step 2: SQL Search ---
        t1 = time.perf_counter()
        sql_results = self._sql_search(query_plan)
        retrieval.num_sql_queries += 1

        # --- Step 3: Vector Search ---
        try:
            q_embedding, embed_tokens = self._embedder.embed_single(question)
            total_tokens.embedding_tokens += embed_tokens
            vector_results = self._vector_search(q_embedding, top_k=15)
            retrieval.num_vector_searches += 1
        except Exception:
            vector_results = []

        timing.retrieval_ms = (time.perf_counter() - t1) * 1000

        # --- Step 4: Context Assembly ---
        t2 = time.perf_counter()
        found_entity_ids = set()

        # From SQL
        for row in sql_results:
            for key in ["id", "source_id", "target_id", "entity_id"]:
                if key in row and row[key]:
                    found_entity_ids.add(row[key])

        # From vector search (top results)
        for eid, score in vector_results[:10]:
            found_entity_ids.add(eid)

        # Expand context
        expanded = self._expand_context(list(found_entity_ids)[:20], depth=2)

        # Build context text
        context_parts = []
        # Add SQL results
        for row in sql_results[:20]:
            context_parts.append(json.dumps(row, ensure_ascii=False, default=str))

        # Add vector search text
        for eid, score in vector_results[:10]:
            if eid in self._texts:
                context_parts.append(f"[Relevance: {score:.3f}] {self._texts[eid][:500]}")

        # Add expanded context
        for ctx in expanded[:20]:
            context_parts.append(json.dumps(ctx, ensure_ascii=False, default=str))

        context_text = "\n---\n".join(context_parts)
        retrieval.context_text = context_text[:5000]
        retrieval.retrieved_entity_ids = list(found_entity_ids)[:50]

        timing.context_building_ms = (time.perf_counter() - t2) * 1000

        # --- Step 5: Answer Generation ---
        t3 = time.perf_counter()
        answer_prompt = f"""Based on the following context, answer the question accurately and concisely.
If the information is not sufficient, say so.

Context:
{context_text[:8000]}

Question: {question}

Answer in Vietnamese. Be specific with names, numbers, and details from the context."""

        answer, answer_tokens, answer_time = self._llm.chat(
            [{"role": "user", "content": answer_prompt}],
        )
        total_tokens.input_tokens += answer_tokens.input_tokens
        total_tokens.output_tokens += answer_tokens.output_tokens
        total_tokens.total_tokens = total_tokens.input_tokens + total_tokens.output_tokens
        retrieval.num_llm_calls += 1

        timing.generation_ms = answer_time * 1000
        timing.total_latency_ms = (time.perf_counter() - t0) * 1000

        return QueryResult(
            question_id=question_id,
            system_name=self.name,
            answer=answer,
            timing=timing,
            tokens=total_tokens,
            retrieval=retrieval,
        )

    def cleanup(self):
        if self._conn:
            self._conn.close()
            self._conn = None
