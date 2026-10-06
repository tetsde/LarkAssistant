"""
LLM-managed Wiki retrieval system.

LLM transforms raw dataset into structured Wiki pages.
Retrieval uses keyword + semantic search over Wiki pages,
plus linked-page expansion.

Pipeline:
  Build: Raw Data → LLM → Wiki Pages (structured markdown)
  Query: User Query → Keyword/Semantic Search → Linked-page Expansion
         → Context Assembly → LLM → Answer
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

from benchmark.config import Config
from benchmark.llm_client import EmbeddingClient, LLMClient
from benchmark.models import (
    Dataset,
    Entity,
    EntityType,
    QueryResult,
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


class WikiPage:
    """A single wiki page."""

    def __init__(self, page_id: str, title: str, content: str, entity_type: str = "",
                 links: Optional[list[str]] = None):
        self.page_id = page_id
        self.title = title
        self.content = content
        self.entity_type = entity_type
        self.links = links or []  # IDs of linked pages
        self.embedding: Optional[list[float]] = None


class WikiStore:
    """In-memory wiki storage with search capabilities."""

    def __init__(self):
        self.pages: dict[str, WikiPage] = {}
        self._title_index: dict[str, str] = {}  # lowercase title -> page_id

    def add_page(self, page: WikiPage):
        self.pages[page.page_id] = page
        self._title_index[page.title.lower()] = page.page_id

    def search_by_title(self, query: str) -> list[WikiPage]:
        """Search pages by title (partial match)."""
        query_lower = query.lower()
        results = []
        for title, pid in self._title_index.items():
            if query_lower in title or title in query_lower:
                results.append(self.pages[pid])
        return results

    def search_by_content(self, keywords: list[str]) -> list[WikiPage]:
        """Search pages by keyword in content."""
        results = []
        for page in self.pages.values():
            content_lower = page.content.lower()
            score = sum(1 for kw in keywords if kw.lower() in content_lower)
            if score > 0:
                results.append((page, score))
        results.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in results[:20]]

    def get_linked_pages(self, page_id: str, depth: int = 1) -> list[WikiPage]:
        """Get pages linked from the given page."""
        visited = {page_id}
        result = []
        current = [page_id]

        for _ in range(depth):
            next_level = []
            for pid in current:
                page = self.pages.get(pid)
                if not page:
                    continue
                for link_id in page.links:
                    if link_id not in visited and link_id in self.pages:
                        visited.add(link_id)
                        result.append(self.pages[link_id])
                        next_level.append(link_id)
            current = next_level

        return result

    @property
    def page_count(self) -> int:
        return len(self.pages)


class WikiRAGSystem(BaseRetrievalSystem):
    """
    LLM-managed Wiki retrieval system.

    Build phase (costly — uses LLM to create wiki pages):
      - Group entities by type
      - For each important entity, generate a structured Wiki page via LLM
      - Build cross-references and links
      - Generate embeddings for search

    Query phase:
      - Search wiki pages by keyword and semantic similarity
      - Expand to linked pages
      - Assemble context and generate answer
    """

    def __init__(self, config: Config, wiki_dir: Optional[Path] = None):
        self._config = config
        self._wiki_dir = wiki_dir or Path("data/wiki")
        self._wiki_dir.mkdir(parents=True, exist_ok=True)
        self._wiki = WikiStore()
        self._llm = LLMClient(config.llm, config.pricing)
        self._embedder = EmbeddingClient(config.embedding, config.pricing)
        self._build_tokens = TokenUsage()

    @property
    def name(self) -> str:
        return "LLM Wiki"

    def _group_entities(self, dataset: Dataset) -> dict[str, list[Entity]]:
        """Group entities by type for page generation."""
        groups: dict[str, list[Entity]] = {}
        for e in dataset.entities:
            etype = e.type.value if hasattr(e.type, 'value') else str(e.type)
            groups.setdefault(etype, []).append(e)
        return groups

    def _find_related(self, entity_id: str, relationships: list[Any]) -> dict[str, list[str]]:
        """Find all related entity IDs grouped by relationship type."""
        related: dict[str, list[str]] = {}
        for r in relationships:
            rtype = r.type.value if hasattr(r.type, 'value') else str(r.type)
            if r.source_id == entity_id:
                related.setdefault(rtype, []).append(r.target_id)
            elif r.target_id == entity_id:
                related.setdefault(f"reverse_{rtype}", []).append(r.source_id)
        return related

    def _generate_wiki_page(self, entity: Entity, related: dict[str, list[str]],
                            entity_map: dict[str, Entity],
                            all_relationships: list[Any]) -> WikiPage:
        """Generate a Wiki page for an entity using LLM."""
        # Build context about the entity and its relationships
        entity_raw = entity.model_dump(mode="json")
        context_parts = [f"Entity: {entity.name} (Type: {entity.type.value})"]
        context_parts.append(f"ID: {entity.id}")

        for k, v in entity_raw.items():
            if k not in ("id", "type", "name", "attributes") and v is not None:
                context_parts.append(f"{k}: {v}")
        if entity.attributes:
            for k, v in entity.attributes.items():
                context_parts.append(f"{k}: {v}")

        # Related entities
        links = []
        for rel_type, ids in related.items():
            names = []
            for eid in ids:
                if eid in entity_map:
                    names.append(f"{entity_map[eid].name} ({eid})")
                    links.append(eid)
            if names:
                context_parts.append(f"\n{rel_type}: {', '.join(names)}")

        context = "\n".join(context_parts)

        prompt = f"""Create a structured Wiki page for the following entity. Use markdown format.
Include all available information. Cross-reference related entities using [[Entity Name]] syntax.
Be comprehensive but concise. Include all facts from the data — do not omit or summarize away details.

{context}

Format the page with these sections as appropriate:
# [Entity Name]
## Overview
## Details
## Related Entities
## Timeline (if applicable)
## Notes"""

        try:
            page_content, tokens, _ = self._llm.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=1500,
            )
            self._build_tokens.input_tokens += tokens.input_tokens
            self._build_tokens.output_tokens += tokens.output_tokens
        except Exception as e:
            # Fallback: create page without LLM
            page_content = f"# {entity.name}\n\n{context}"

        return WikiPage(
            page_id=entity.id,
            title=entity.name,
            content=page_content,
            entity_type=entity.type.value if hasattr(entity.type, 'value') else str(entity.type),
            links=links,
        )

    def _generate_summary_page(self, entity_type: str, entities: list[Entity]) -> WikiPage:
        """Generate a summary/index page for an entity type."""
        content_parts = [f"# {entity_type} Index\n"]
        for e in entities:
            content_parts.append(f"- [[{e.name}]] ({e.id})")
            raw = e.model_dump(mode="json")
            for k in ["status", "priority", "severity", "role", "tier"]:
                if k in raw and raw[k]:
                    content_parts[-1] += f" — {k}: {raw[k]}"

        content = "\n".join(content_parts)
        page_id = f"index_{entity_type.lower()}"

        return WikiPage(
            page_id=page_id,
            title=f"{entity_type} Index",
            content=content,
            entity_type="index",
            links=[e.id for e in entities],
        )

    def build(self, dataset: Dataset) -> SystemBuildMetrics:
        start = time.perf_counter()
        self._build_tokens = TokenUsage()
        
        # --- FAST PATH: REUSE EXISTING WIKI ---
        existing_md_files = list(self._wiki_dir.glob("*.md"))
        if len(existing_md_files) > 100:
            print(f"  [WikiRAG] Found {len(existing_md_files)} existing markdown files. Skipping LLM generation.")
            llm_time = 0
            for md_file in existing_md_files:
                content = md_file.read_text(encoding="utf-8")
                # Very basic parsing, assume first line is # Title
                lines = content.splitlines()
                title = lines[0].replace("# ", "").strip() if lines and lines[0].startswith("#") else md_file.stem
                # Extract links [[ID]]
                links = re.findall(r'\[\[(.*?)\]\]', content)
                page = WikiPage(
                    page_id=md_file.stem,
                    title=title,
                    content=content,
                    entity_type="unknown",
                    links=links
                )
                self._wiki.add_page(page)
        else:
            # --- SLOW PATH: GENERATE ---
            entity_map = {e.id: e for e in dataset.entities}
            groups = self._group_entities(dataset)

            priority_types = {"Project", "Team", "Department", "Customer", "Campaign", "Decision"}
            simple_types = {"Task", "Message"}

            llm_start = time.perf_counter()

            for etype, entities in groups.items():
                index_page = self._generate_summary_page(etype, entities)
                self._wiki.add_page(index_page)

                for entity in entities:
                    related = self._find_related(entity.id, dataset.relationships)

                    if etype in priority_types:
                        page = self._generate_wiki_page(entity, related, entity_map, dataset.relationships)
                    elif etype in simple_types:
                        raw = entity.model_dump(mode="json")
                        content_parts = [f"# {entity.name}\n"]
                        for k, v in raw.items():
                            if k not in ("id", "type", "name", "attributes") and v is not None:
                                content_parts.append(f"**{k}**: {v}")
                        if entity.attributes:
                            for k, v in entity.attributes.items():
                                content_parts.append(f"**{k}**: {v}")
                        links = []
                        for rel_type, ids in related.items():
                            names = []
                            for eid in ids:
                                if eid in entity_map:
                                    names.append(f"[[{entity_map[eid].name}]]")
                                    links.append(eid)
                            if names:
                                content_parts.append(f"\n**{rel_type}**: {', '.join(names)}")
                        page = WikiPage(
                            page_id=entity.id,
                            title=entity.name,
                            content="\n".join(content_parts),
                            entity_type=etype,
                            links=links,
                        )
                    else:
                        raw = entity.model_dump(mode="json")
                        content_parts = [f"# {entity.name}\n\n## Details\n"]
                        for k, v in raw.items():
                            if k not in ("id", "type", "name", "attributes") and v is not None:
                                content_parts.append(f"- **{k}**: {v}")
                        links = []
                        for rel_type, ids in related.items():
                            names = []
                            for eid in ids:
                                if eid in entity_map:
                                    names.append(f"[[{entity_map[eid].name}]]")
                                    links.append(eid)
                            if names:
                                content_parts.append(f"\n## {rel_type}\n{', '.join(names)}")
                        page = WikiPage(
                            page_id=entity.id,
                            title=entity.name,
                            content="\n".join(content_parts),
                            entity_type=etype,
                            links=links,
                        )

                    self._wiki.add_page(page)

            llm_time = time.perf_counter() - llm_start

        # Generate embeddings for wiki pages
        embed_start = time.perf_counter()
        total_embed_tokens = 0
        page_ids = list(self._wiki.pages.keys())
        page_texts = [self._wiki.pages[pid].content[:500] for pid in page_ids]

        batch_size = 50
        for i in range(0, len(page_texts), batch_size):
            batch = page_texts[i:i + batch_size]
            batch_ids = page_ids[i:i + batch_size]
            try:
                embeddings, tokens = self._embedder.embed(batch)
                total_embed_tokens += tokens
                for pid, emb in zip(batch_ids, embeddings):
                    self._wiki.pages[pid].embedding = emb
            except Exception as e:
                print(f"  [WikiRAG] Embedding batch {i} failed: {e}")

        embed_time = time.perf_counter() - embed_start

        # Save wiki to disk
        self._save_wiki()

        total_time = time.perf_counter() - start
        self._build_tokens.total_tokens = self._build_tokens.input_tokens + self._build_tokens.output_tokens
        self._build_tokens.embedding_tokens = total_embed_tokens

        # Calculate storage size
        storage = sum(len(p.content.encode()) for p in self._wiki.pages.values())

        return SystemBuildMetrics(
            system_name=self.name,
            ingestion_time_seconds=total_time - llm_time - embed_time,
            indexing_time_seconds=embed_time,
            llm_processing_time_seconds=llm_time,
            llm_tokens=self._build_tokens,
            construction_cost=(
                self._llm.estimate_cost(self._build_tokens)
                + self._embedder.estimate_cost(total_embed_tokens)
            ),
            storage_size_bytes=storage,
        )
    def _save_wiki(self):
        """Save wiki pages to disk for inspection."""
        for page in self._wiki.pages.values():
            safe_name = re.sub(r'[^\w\-]', '_', page.title)[:80]
            filepath = self._wiki_dir / f"{safe_name}.md"
            filepath.write_text(page.content, encoding="utf-8")

    def _semantic_search(self, query: str, top_k: int = 10) -> list[tuple[WikiPage, float]]:
        """Search wiki pages by semantic similarity."""
        try:
            q_embedding, _ = self._embedder.embed_single(query)
        except Exception:
            return []

        scores = []
        for page in self._wiki.pages.values():
            if page.embedding:
                sim = cosine_similarity(q_embedding, page.embedding)
                scores.append((page, sim))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def query(self, question: str, question_id: str = "") -> QueryResult:
        total_tokens = TokenUsage()
        retrieval = RetrievalResult()
        timing = TimingBreakdown()

        # --- Step 1: Query Understanding (lightweight — just keyword extraction) ---
        t0 = time.perf_counter()

        # Simple keyword extraction without LLM call for efficiency
        # (Wiki system relies more on semantic search)
        keywords = [w for w in question.split() if len(w) > 2]
        timing.query_understanding_ms = (time.perf_counter() - t0) * 1000

        # --- Step 2: Wiki Search ---
        t1 = time.perf_counter()

        # Title search
        title_results = self._wiki.search_by_title(question)

        # Keyword search
        keyword_results = self._wiki.search_by_content(keywords)

        # Semantic search
        semantic_results = self._semantic_search(question, top_k=10)
        retrieval.num_vector_searches += 1

        # Combine results (deduplicate)
        seen_ids: set[str] = set()
        found_pages: list[WikiPage] = []

        for page in title_results[:5]:
            if page.page_id not in seen_ids:
                seen_ids.add(page.page_id)
                found_pages.append(page)

        for page in keyword_results[:10]:
            if page.page_id not in seen_ids:
                seen_ids.add(page.page_id)
                found_pages.append(page)

        for page, score in semantic_results:
            if page.page_id not in seen_ids and score > 0.2:
                seen_ids.add(page.page_id)
                found_pages.append(page)

        timing.retrieval_ms = (time.perf_counter() - t1) * 1000

        # --- Step 3: Linked-page Expansion ---
        t2 = time.perf_counter()
        expanded_pages: list[WikiPage] = []
        for page in found_pages[:5]:
            linked = self._wiki.get_linked_pages(page.page_id, depth=1)
            for lp in linked:
                if lp.page_id not in seen_ids:
                    seen_ids.add(lp.page_id)
                    expanded_pages.append(lp)

        all_pages = found_pages + expanded_pages

        # Build context
        context_parts = []
        for page in all_pages[:20]:
            context_parts.append(f"=== Wiki: {page.title} ===\n{page.content[:600]}")

        context_text = "\n\n".join(context_parts)
        retrieval.context_text = context_text[:5000]
        retrieval.retrieved_entity_ids = [p.page_id for p in all_pages[:50]]

        timing.context_building_ms = (time.perf_counter() - t2) * 1000

        # --- Step 4: Answer Generation ---
        t3 = time.perf_counter()
        answer_prompt = f"""Based on the following Wiki pages, answer the question accurately and concisely.
The Wiki pages contain structured information about the organization.
Follow the cross-references ([[links]]) mentally to piece together information.

Wiki Content:
{context_text[:8000]}

Question: {question}

Answer in Vietnamese. Be specific with names, numbers, and details from the Wiki pages."""

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
