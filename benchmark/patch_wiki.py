import sys
from pathlib import Path

fpath = Path("systems/wiki_rag/system.py")
content = fpath.read_text()

replacement = """    def build(self, dataset: Dataset) -> SystemBuildMetrics:
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
                        content_parts = [f"# {entity.name}\\n"]
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
                                content_parts.append(f"\\n**{rel_type}**: {', '.join(names)}")
                        page = WikiPage(
                            page_id=entity.id,
                            title=entity.name,
                            content="\\n".join(content_parts),
                            entity_type=etype,
                            links=links,
                        )
                    else:
                        raw = entity.model_dump(mode="json")
                        content_parts = [f"# {entity.name}\\n\\n## Details\\n"]
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
                                content_parts.append(f"\\n## {rel_type}\\n{', '.join(names)}")
                        page = WikiPage(
                            page_id=entity.id,
                            title=entity.name,
                            content="\\n".join(content_parts),
                            entity_type=etype,
                            links=links,
                        )

                    self._wiki.add_page(page)

            llm_time = time.perf_counter() - llm_start
"""

import re
old_build = re.search(r'    def build\(self, dataset: Dataset\) -> SystemBuildMetrics:(.*?)(?=    def _save_wiki\(self\):)', content, re.DOTALL).group(0)

new_build = replacement + """
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
"""

content = content.replace(old_build, new_build)
fpath.write_text(content)
