"""
Benchmark Configuration — loaded from .env and benchmark_config.yaml
All API keys, model names, pricing, and benchmark parameters are configured here.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
GENERATED_DIR = DATA_DIR / "generated"
GROUND_TRUTH_DIR = DATA_DIR / "ground_truth"
RESULTS_DIR = PROJECT_ROOT / "results"
REPORTS_DIR = PROJECT_ROOT / "reports"

for d in [DATA_DIR, RAW_DIR, GENERATED_DIR, GROUND_TRUTH_DIR, RESULTS_DIR, REPORTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Pydantic config models
# ---------------------------------------------------------------------------
class LLMConfig(BaseModel):
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    temperature: float = 0.0


class EmbeddingConfig(BaseModel):
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "text-embedding-3-small"


class PricingConfig(BaseModel):
    llm_input_per_1m: float = 0.15
    llm_output_per_1m: float = 0.60
    embedding_per_1m: float = 0.02


class BenchmarkParams(BaseModel):
    runs_per_question: int = 3
    temperature: float = 0.0
    seed: int = 42
    max_concurrent: int = 5


class DatabaseConfig(BaseModel):
    url: str = "sqlite:///data/benchmark.db"


class Config(BaseModel):
    """Top-level configuration — single source of truth."""
    llm: LLMConfig = Field(default_factory=LLMConfig)
    judge: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    pricing: PricingConfig = Field(default_factory=PricingConfig)
    benchmark: BenchmarkParams = Field(default_factory=BenchmarkParams)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)


def load_config(env_path: Optional[str | Path] = None) -> Config:
    """Load configuration from .env file and environment variables."""
    if env_path is None:
        env_path = PROJECT_ROOT / ".env"
    load_dotenv(str(env_path), override=True)

    llm = LLMConfig(
        api_key=os.getenv("LLM_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        temperature=float(os.getenv("BENCHMARK_TEMPERATURE", "0")),
    )

    # Judge defaults to LLM settings if not explicitly set
    judge = LLMConfig(
        api_key=os.getenv("JUDGE_API_KEY", "") or llm.api_key,
        base_url=os.getenv("JUDGE_BASE_URL", "") or llm.base_url,
        model=os.getenv("JUDGE_MODEL", "") or llm.model,
        temperature=0.0,
    )

    embedding = EmbeddingConfig(
        api_key=os.getenv("EMBEDDING_API_KEY", "") or llm.api_key,
        base_url=os.getenv("EMBEDDING_BASE_URL", "") or llm.base_url,
        model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
    )

    pricing = PricingConfig(
        llm_input_per_1m=float(os.getenv("LLM_INPUT_PRICE_PER_1M", "0.15")),
        llm_output_per_1m=float(os.getenv("LLM_OUTPUT_PRICE_PER_1M", "0.60")),
        embedding_per_1m=float(os.getenv("EMBEDDING_PRICE_PER_1M", "0.02")),
    )

    params = BenchmarkParams(
        runs_per_question=int(os.getenv("BENCHMARK_RUNS_PER_QUESTION", "3")),
        temperature=float(os.getenv("BENCHMARK_TEMPERATURE", "0")),
        seed=int(os.getenv("BENCHMARK_SEED", "42")),
        max_concurrent=int(os.getenv("BENCHMARK_MAX_CONCURRENT", "5")),
    )

    db = DatabaseConfig(
        url=os.getenv("DATABASE_URL", "sqlite:///data/benchmark.db"),
    )

    return Config(
        llm=llm,
        judge=judge,
        embedding=embedding,
        pricing=pricing,
        benchmark=params,
        database=db,
    )
