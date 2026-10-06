"""
Benchmark runner.
Executes the dataset generation, knowledge construction, and query phases.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

from benchmark.config import Config
from benchmark.models import BenchmarkRun, Dataset, EvaluatedResult
from data.generate_dataset import DatasetGenerator, save_dataset
from evaluation.evaluator import Evaluator
from systems.base import BaseRetrievalSystem
from systems.graph_rag.system import GraphRAGSystem
from systems.postgres_rag.system import PostgresRAGSystem
from systems.wiki_rag.system import WikiRAGSystem


class BenchmarkRunner:
    """Orchestrates the entire benchmark lab."""

    def __init__(self, config: Config):
        self.config = config
        self.dataset: Dataset | None = None
        self.systems: list[BaseRetrievalSystem] = []
        self.evaluator = Evaluator(config)
        self.run_record = BenchmarkRun(
            timestamp=datetime.now().isoformat(),
            model=config.llm.model,
            embedding_model=config.embedding.model,
            temperature=config.benchmark.temperature,
            seed=config.benchmark.seed,
            runs_per_question=config.benchmark.runs_per_question,
        )

    def generate_dataset(self, output_dir: Path) -> Dataset:
        """Generate and save the benchmark dataset."""
        print("--- Phase 0: Generating Dataset ---")
        generator = DatasetGenerator(seed=self.config.benchmark.seed)
        self.dataset = generator.generate()
        save_dataset(self.dataset, output_dir)
        self.run_record.dataset_version = self.dataset.version
        self.run_record.question_count = len(self.dataset.questions)
        return self.dataset

    def load_dataset(self, dataset_path: Path) -> Dataset:
        """Load an existing dataset from disk."""
        print(f"--- Loading Dataset from {dataset_path} ---")
        with open(dataset_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.dataset = Dataset.model_validate(data)
        self.run_record.dataset_version = self.dataset.version
        self.run_record.question_count = len(self.dataset.questions)
        return self.dataset

    def setup_systems(self):
        """Initialize all three retrieval systems."""
        print("--- Initializing Systems ---")
        self.systems = [
            PostgresRAGSystem(self.config),
            GraphRAGSystem(self.config),
            WikiRAGSystem(self.config),
        ]

    def build_knowledge_bases(self):
        """Phase A: Knowledge Construction."""
        if not self.dataset:
            raise ValueError("Dataset not loaded.")

        print("\n--- Phase A: Knowledge Construction ---")
        for system in self.systems:
            print(f"Building {system.name}...")
            metrics = system.build(self.dataset)
            self.run_record.build_metrics.append(metrics)
            print(f"  Ingestion: {metrics.ingestion_time_seconds:.2f}s")
            print(f"  Indexing:  {metrics.indexing_time_seconds:.2f}s")
            print(f"  LLM Proc:  {metrics.llm_processing_time_seconds:.2f}s")
            print(f"  Cost:      ${metrics.construction_cost:.4f}")

    def run_queries(self, subset_size: int = 0):
        """Phase B: Querying and Evaluation."""
        if not self.dataset:
            raise ValueError("Dataset not loaded.")

        print("\n--- Phase B: Querying and Evaluation ---")
        
        questions = self.dataset.questions
        if subset_size > 0:
            questions = questions[:subset_size]
            print(f"Running subset of {subset_size} questions.")

        results: list[EvaluatedResult] = []
        runs = self.config.benchmark.runs_per_question

        for system in self.systems:
            print(f"\nEvaluating System: {system.name}")
            for q in tqdm(questions, desc=f"Queries ({system.name})"):
                for run_idx in range(runs):
                    try:
                        # 1. Query System
                        q_result = system.query(q.question, q.question_id)
                        q_result.run_index = run_idx
                        
                        # 2. Evaluate Answer
                        eval_result = self.evaluator.evaluate(q_result, q)
                        results.append(eval_result)
                    except Exception as e:
                        print(f"\nError on {q.question_id} ({system.name}): {e}")
                        # Record error result
                        from benchmark.models import QueryResult, TimingBreakdown, TokenUsage, RetrievalResult, JudgeScore
                        err_res = QueryResult(
                            question_id=q.question_id,
                            system_name=system.name,
                            run_index=run_idx,
                            error=str(e),
                            timing=TimingBreakdown(),
                            tokens=TokenUsage(),
                            retrieval=RetrievalResult(),
                        )
                        results.append(EvaluatedResult(query_result=err_res, judge=JudgeScore()))

        self.run_record.results = results

    def cleanup(self):
        """Cleanup system resources."""
        for system in self.systems:
            system.cleanup()

    def save_results(self, output_dir: Path):
        """Save benchmark results to disk."""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = output_dir / f"benchmark_run_{self.run_record.timestamp.replace(':', '')}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.run_record.model_dump(mode="json"), f, ensure_ascii=False, indent=2, default=str)
        
        print(f"\nResults saved to {file_path}")
        return file_path
