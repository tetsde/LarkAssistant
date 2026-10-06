"""
GraphRAG retrieval system.

Uses NetworkX as a local graph database prototype.
Designed with an abstraction layer so it can be swapped to Neo4j later.

Pipeline:
  User Query → Entity/Intent Extraction → Knowledge Graph Traversal
  → Context Expansion → Source Evidence Retrieval → RAG → LLM → Answer
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

import networkx as nx
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
    a_arr, b_arr = np.array(a), np.array(b)
    dot = np.dot(a_arr, b_arr)
    norm = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    return float(dot / norm) if norm > 0 else 0.0


class GraphStore:
    """
    Graph abstraction layer.
    Currently uses NetworkX; can be replaced with Neo4j driver.
    """

    def __init__(self):
        self.graph = nx.MultiDiGraph()

    def add_node(self, node_id: str, **attrs):
        self.graph.add_node(node_id, **attrs)

    def add_edge(self, source: str, target: str, rel_type: str, **attrs):
        self.graph.add_edge(source, target, rel_type=rel_type, **attrs)

    def get_node(self, node_id: str) -> Optional[dict]:
        if node_id in self.graph:
            return dict(self.graph.nodes[node_id])
        return None

    def get_neighbors(self, node_id: str, direction: str = "both", rel_type: str = "") -> list[tuple[str, str, dict]]:
        """Get neighbors of a node.
        Returns list of (neighbor_id, relationship_type, edge_attrs)."""
        results = []
        if direction in ("out", "both"):
            for _, target, data in self.graph.out_edges(node_id, data=True):
                if not rel_type or data.get("rel_type") == rel_type:
                    results.append((target, data.get("rel_type", ""), data))
        if direction in ("in", "both"):
            for source, _, data in self.graph.in_edges(node_id, data=True):
                if not rel_type or data.get("rel_type") == rel_type:
                    results.append((source, data.get("rel_type", ""), data))
        return results

    def find_nodes_by_attr(self, attr: str, value: Any, partial: bool = False) -> list[str]:
        """Find nodes where attr matches value."""
        results = []
        for node_id, data in self.graph.nodes(data=True):
            node_val = data.get(attr, "")
            if partial and isinstance(node_val, str) and isinstance(value, str):
                if value.lower() in node_val.lower():
                    results.append(node_id)
            elif node_val == value:
                results.append(node_id)
        return results

    def traverse(self, start_nodes: list[str], max_depth: int = 3) -> dict[str, dict]:
        """BFS traversal from start nodes, collecting all reached nodes and edges."""
        visited: dict[str, dict] = {}
        queue: list[tuple[str, int]] = [(n, 0) for n in start_nodes]

        while queue:
            node_id, depth = queue.pop(0)
            if node_id in visited or depth > max_depth:
                continue

            node_data = self.get_node(node_id)
            if node_data is None:
                continue

            neighbors = self.get_neighbors(node_id, direction="both")
            visited[node_id] = {
                "data": node_data,
                "depth": depth,
                "edges": [(nid, rtype) for nid, rtype, _ in neighbors],
            }

            if depth < max_depth:
                for nid, _, _ in neighbors:
                    if nid not in visited:
                        queue.append((nid, depth + 1))

        return visited

    def shortest_path(self, source: str, target: str) -> list[str]:
        """Find shortest path between two nodes."""
        try:
            return nx.shortest_path(self.graph, source, target)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()


class GraphRAGSystem(BaseRetrievalSystem):
    """
    Knowledge Graph + RAG retrieval system.

    Build phase:
      - Build knowledge graph from entities and relationships
      - Store source text references (not full content in graph)
      - Generate embeddings for entity descriptions

    Query phase:
      - LLM extracts entities and intent from question
      - Graph traversal to find relevant subgraph
      - Retrieve source evidence from text store
      - RAG with LLM for answer generation
    """

    def __init__(self, config: Config):
        self._config = config
        self._graph = GraphStore()
        self._llm = LLMClient(config.llm, config.pricing)
        self._embedder = EmbeddingClient(config.embedding, config.pricing)
        self._embeddings: dict[str, list[float]] = {}
        self._source_texts: dict[str, str] = {}  # entity_id -> full text content
        self._entity_names: dict[str, str] = {}  # name -> id (for quick lookup)

    @property
    def name(self) -> str:
        return "GraphRAG"

    def build(self, dataset: Dataset) -> SystemBuildMetrics:
        start = time.perf_counter()

        # Build graph nodes
        for entity in dataset.entities:
            raw = entity.model_dump(mode="json")
            attrs = {
                "type": entity.type.value if hasattr(entity.type, 'value') else str(entity.type),
                "name": entity.name,
            }
            # Add searchable attributes
            for k, v in raw.items():
                if k not in ("id", "type", "name", "attributes") and v is not None:
                    attrs[k] = str(v) if not isinstance(v, (str, int, float, bool)) else v

            # Merge entity.attributes
            if entity.attributes:
                for k, v in entity.attributes.items():
                    attrs[k] = v

            self._graph.add_node(entity.id, **attrs)
            self._entity_names[entity.name.lower()] = entity.id

            # Build source text reference
            content_parts = [entity.name]
            for field in ["content", "description", "summary", "agenda", "rationale"]:
                if field in raw and raw[field]:
                    content_parts.append(str(raw[field]))
            text = "\n".join(content_parts)
            if len(text) > 20:
                self._source_texts[entity.id] = text

        # Build graph edges
        for rel in dataset.relationships:
            rel_type = rel.type.value if hasattr(rel.type, 'value') else str(rel.type)
            self._graph.add_edge(
                rel.source_id, rel.target_id, rel_type,
                **rel.attributes,
            )

        ingest_time = time.perf_counter() - start

        # Generate embeddings for entity descriptions
        embed_start = time.perf_counter()
        total_embed_tokens = 0
        text_ids = list(self._source_texts.keys())
        text_values = [self._source_texts[tid][:500] for tid in text_ids]

        batch_size = 50
        for i in range(0, len(text_values), batch_size):
            batch = text_values[i:i + batch_size]
            batch_ids = text_ids[i:i + batch_size]
            try:
                embeddings, tokens = self._embedder.embed(batch)
                total_embed_tokens += tokens
                for eid, emb in zip(batch_ids, embeddings):
                    self._embeddings[eid] = emb
            except Exception as e:
                print(f"  [GraphRAG] Embedding batch {i} failed: {e}")
                for eid in batch_ids:
                    self._embeddings[eid] = [0.0] * 256

        embed_time = time.perf_counter() - embed_start
        total_time = time.perf_counter() - start

        return SystemBuildMetrics(
            system_name=self.name,
            ingestion_time_seconds=ingest_time,
            indexing_time_seconds=embed_time,
            llm_processing_time_seconds=0.0,
            llm_tokens=TokenUsage(embedding_tokens=total_embed_tokens),
            construction_cost=self._embedder.estimate_cost(total_embed_tokens),
            storage_size_bytes=0,  # In-memory
        )

    def _extract_entities(self, question: str) -> dict:
        """Use LLM to extract entities and intent from the question."""
        prompt = f"""Extract entities and relationships from this question. Return valid JSON only.

Question: {question}

Return a JSON object with:
- "entity_names": list of entity names mentioned (projects, people, teams, etc.)
- "entity_types": list of entity types to look for
- "intent": the type of question (e.g., "lookup", "relationship", "aggregation", "temporal", "comparison")
- "hop_depth": estimated number of relationship hops needed (1-4)
- "keywords": important search keywords
- "temporal_filter": date/time filter if applicable (null if not)

Only return the JSON, no explanation."""

        text, tokens, elapsed = self._llm.chat(
            [{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )

        try:
            return json.loads(text), tokens, elapsed
        except json.JSONDecodeError:
            return {"entity_names": [], "keywords": question.split(), "hop_depth": 2}, tokens, elapsed

    def _find_seed_nodes(self, extraction: dict) -> list[str]:
        """Find starting nodes in the graph based on extracted entities."""
        seed_nodes = []

        # Match by name
        for name in extraction.get("entity_names", []):
            name_lower = name.lower()
            # Exact match
            if name_lower in self._entity_names:
                seed_nodes.append(self._entity_names[name_lower])
            else:
                # Partial match
                matches = self._graph.find_nodes_by_attr("name", name, partial=True)
                seed_nodes.extend(matches[:3])

        # Match by type
        for etype in extraction.get("entity_types", []):
            matches = self._graph.find_nodes_by_attr("type", etype)
            seed_nodes.extend(matches[:5])

        # Vector search for keywords
        keywords = extraction.get("keywords", [])
        if keywords:
            query_text = " ".join(keywords)
            try:
                q_embedding, _ = self._embedder.embed_single(query_text)
                scores = []
                for eid, emb in self._embeddings.items():
                    sim = cosine_similarity(q_embedding, emb)
                    scores.append((eid, sim))
                scores.sort(key=lambda x: x[1], reverse=True)
                seed_nodes.extend([eid for eid, _ in scores[:5]])
            except Exception:
                pass

        return list(set(seed_nodes))[:20]

    def query(self, question: str, question_id: str = "") -> QueryResult:
        total_tokens = TokenUsage()
        retrieval = RetrievalResult()
        timing = TimingBreakdown()

        # --- Step 1: Entity/Intent Extraction ---
        t0 = time.perf_counter()
        extraction, ext_tokens, ext_time = self._extract_entities(question)
        total_tokens.input_tokens += ext_tokens.input_tokens
        total_tokens.output_tokens += ext_tokens.output_tokens
        retrieval.num_llm_calls += 1
        timing.query_understanding_ms = ext_time * 1000

        # --- Step 2: Graph Traversal ---
        t1 = time.perf_counter()
        seed_nodes = self._find_seed_nodes(extraction)
        retrieval.num_graph_operations += 1

        hop_depth = min(extraction.get("hop_depth", 2), 4)
        subgraph = self._graph.traverse(seed_nodes, max_depth=hop_depth)
        retrieval.num_graph_operations += 1

        # Collect entity IDs and relationships found
        found_entity_ids = list(subgraph.keys())
        found_relationships = []
        for node_id, info in subgraph.items():
            for neighbor_id, rel_type in info.get("edges", []):
                found_relationships.append(f"{node_id} -> {rel_type} -> {neighbor_id}")

        retrieval.retrieved_entity_ids = found_entity_ids[:50]
        retrieval.retrieved_relationships = found_relationships[:50]
        timing.retrieval_ms = (time.perf_counter() - t1) * 1000

        # --- Step 3: Source Evidence Retrieval ---
        t2 = time.perf_counter()
        context_parts = []

        # Build structured context from subgraph
        for node_id, info in list(subgraph.items())[:30]:
            node_data = info["data"]
            node_desc = f"[{node_data.get('type', 'Unknown')}] {node_data.get('name', node_id)}"

            # Add key attributes
            for attr in ["status", "priority", "severity", "description", "content",
                         "summary", "role", "industry", "campaign_type"]:
                if attr in node_data and node_data[attr]:
                    node_desc += f"\n  {attr}: {node_data[attr]}"

            # Add relationships
            edges = info.get("edges", [])
            if edges:
                rel_strs = [f"  → {rtype} → {nid}" for nid, rtype in edges[:10]]
                node_desc += "\n" + "\n".join(rel_strs)

            context_parts.append(node_desc)

        # Add source texts for key entities
        for node_id in found_entity_ids[:15]:
            if node_id in self._source_texts:
                context_parts.append(f"[Source: {node_id}] {self._source_texts[node_id][:400]}")
                retrieval.retrieved_source_ids.append(node_id)

        # Also do vector search on the question itself for additional context
        try:
            q_embedding, embed_tokens = self._embedder.embed_single(question)
            total_tokens.embedding_tokens += embed_tokens
            scores = []
            for eid, emb in self._embeddings.items():
                if eid not in found_entity_ids:
                    sim = cosine_similarity(q_embedding, emb)
                    scores.append((eid, sim))
            scores.sort(key=lambda x: x[1], reverse=True)
            for eid, score in scores[:5]:
                if score > 0.3 and eid in self._source_texts:
                    context_parts.append(f"[Vector match {score:.3f}] {self._source_texts[eid][:300]}")
                    retrieval.num_vector_searches += 1
        except Exception:
            pass

        context_text = "\n---\n".join(context_parts)
        retrieval.context_text = context_text[:5000]
        timing.context_building_ms = (time.perf_counter() - t2) * 1000

        # --- Step 4: Answer Generation ---
        t3 = time.perf_counter()
        answer_prompt = f"""You are a knowledge assistant. Based on the following knowledge graph context, answer the question accurately.

The context contains entities and their relationships extracted from a knowledge graph.
Pay attention to relationship chains for multi-hop reasoning.

Context:
{context_text[:8000]}

Question: {question}

Answer in Vietnamese. Be specific with names, numbers, and details. If information is insufficient, state what's missing."""

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
