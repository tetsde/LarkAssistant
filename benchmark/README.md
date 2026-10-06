# LAB BENCHMARK: GraphRAG vs PostgreSQL+RAG vs LLM Wiki

This is a comprehensive, end-to-end benchmark lab designed to compare three distinct knowledge retrieval architectures:
1. **GraphRAG**: Knowledge Graph (NetworkX prototype) + Vector Search
2. **PostgreSQL + RAG**: Relational DB (SQLite prototype) + Vector Search + LLM Query Planning
3. **LLM Wiki**: Structured Markdown Pages + Keyword/Semantic Search + Linked-Page Expansion

## 🎯 Objectives
* Provide an unbiased, metric-driven comparison.
* Test on single-hop, multi-hop, aggregation, and relationship queries.
* Measure **Latency**, **Cost**, **Accuracy**, and **Token Usage** for both the *Construction Phase* and *Query Phase*.

---

## 🚀 1. Setup

### Requirements
- Python 3.11+
- Virtual environment (recommended)

### Installation
```bash
cd benchmark
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## ⚙️ 2. Configuration (MANDATORY)

The system is provider-agnostic via the OpenAI SDK. You can use OpenAI, Azure, Groq, Together, vLLM, or Ollama.

**How to change API/Model:**
Open the `.env` file (copy from `.env.example` if needed):
```bash
cp .env.example .env
```

Edit `.env`:
```env
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

EMBEDDING_API_KEY=your_api_key
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
```

**How to change Benchmark Parameters:**
Edit these values in `.env`:
```env
# Number of times each question is asked per system
BENCHMARK_RUNS_PER_QUESTION=3

# Temperature for LLM calls during benchmark
BENCHMARK_TEMPERATURE=0
```

---

## 🏃 3. Running the Benchmark

The entire lab (dataset generation, construction, and querying) is orchestrated by a single script.

To run the full benchmark (~100 questions):
```bash
python scripts/run_all.py
```

### Quick Testing
To test the pipeline quickly (only 5 questions):
```bash
python scripts/run_all.py --subset 5
```

To skip dataset generation and reuse the existing one:
```bash
python scripts/run_all.py --skip-generation
```

---

## 📊 4. Viewing Results

All results are saved in the `results/{TIMESTAMP}/` directory.

After a successful run, the following artifacts are generated:
- `benchmark_report.md`: The final comparative report with summary tables.
- `charts/`: Folder containing visualized metrics:
  - `accuracy.png`
  - `latency.png`
  - `recall.png`
  - `tokens.png`
- `aggregated_metrics.csv`: Aggregate statistics per system.
- `raw_queries.csv`: Detailed results for every single question asked.

---

## 🧠 5. Architecture Details

### Dataset Generator (`data/generate_dataset.py`)
Generates a deterministic dataset of Users, Teams, Projects, Customers, Tasks, Issues, Meetings, Decisions, Campaigns, Documents, and Messages. It also auto-generates >100 ground-truth questions spanning 9 difficulty categories (Single-hop, Multi-hop, Temporal, Aggregation, etc.).

### System 1: PostgreSQL + RAG (`systems/postgres_rag/system.py`)
- **Prototype**: Uses SQLite locally for zero-setup execution.
- **Query**: LLM creates a JSON query plan (tables, keywords, relationships). System executes SQL + Vector Search, expands context via foreign keys, and answers.

### System 2: GraphRAG (`systems/graph_rag/system.py`)
- **Prototype**: Uses NetworkX in-memory graph.
- **Query**: LLM extracts entities and intent. System does a BFS traversal starting from seed nodes, retrieves source texts, and answers.

### System 3: LLM Wiki (`systems/wiki_rag/system.py`)
- **Prototype**: Local Markdown files + In-memory text search.
- **Build**: VERY EXPENSIVE. LLM reads raw data and writes structured wiki pages.
- **Query**: Keyword + Semantic Search, follows `[[Wiki Links]]` to expand context, and answers.

---

## ⚠️ 6. Limitations of this Benchmark
1. **Local Prototypes**: For ease of setup, PostgreSQL uses SQLite and Graph uses NetworkX. Performance metrics reflect prototype overhead, not necessarily production scale DB overhead.
2. **Context Limits**: The prototype truncates context to fit within standard context windows.
3. **LLM as a Judge**: Correctness is evaluated by an LLM prompt. While temperature=0, it may still exhibit minor variations in grading.
