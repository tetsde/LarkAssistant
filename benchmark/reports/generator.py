"""
Report generator for benchmark results.
Reads the benchmark JSON result, calculates aggregate metrics,
generates CSVs, plots charts, and writes a Markdown report.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from tabulate import tabulate

from benchmark.config import Config


class ReportGenerator:
    """Generates all final artifacts from benchmark run."""

    def __init__(self, run_record_path: Path, output_dir: Path, config: Config):
        self.run_record_path = run_record_path
        self.output_dir = output_dir
        self.config = config
        
        self.charts_dir = self.output_dir / "charts"
        self.charts_dir.mkdir(parents=True, exist_ok=True)
        
        with open(run_record_path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

        self.df_build = pd.DataFrame(self.data.get("build_metrics", []))
        
        # Flatten results for pandas
        flat_results = []
        for r in self.data.get("results", []):
            qr = r["query_result"]
            j = r["judge"]
            
            # Reconstruct question hop count (we need the dataset or we can attach it, 
            # for now we assume it was passed, but we'll extract it if possible)
            # To keep it simple, we'll calculate it if we load the dataset, or pass it via metadata.
            # We didn't explicitly store hop_count in QueryResult, so let's default to parsing difficulty.
            # (In a real implementation we would attach ground truth metadata to QueryResult, but for prototype
            # we will join with dataset later if needed, or we just rely on basic metrics).
            
            flat_results.append({
                "question_id": qr["question_id"],
                "system": qr["system_name"],
                "run": qr["run_index"],
                "correct": j["correct"],
                "score": j["score"],
                "entity_recall": j.get("entity_recall", 0),
                "source_recall": j.get("source_recall", 0),
                "rel_recall": j.get("relationship_recall", 0),
                
                "latency_understanding": qr["timing"]["query_understanding_ms"],
                "latency_retrieval": qr["timing"]["retrieval_ms"],
                "latency_context": qr["timing"]["context_building_ms"],
                "latency_generation": qr["timing"]["generation_ms"],
                "latency_total": qr["timing"]["total_latency_ms"],
                
                "tokens_in": qr["tokens"]["input_tokens"],
                "tokens_out": qr["tokens"]["output_tokens"],
                "tokens_total": qr["tokens"]["total_tokens"],
                
                "llm_calls": qr["retrieval"]["num_llm_calls"],
                "sql_queries": qr["retrieval"]["num_sql_queries"],
                "graph_ops": qr["retrieval"]["num_graph_operations"],
                "vector_searches": qr["retrieval"]["num_vector_searches"],
                
                "error": qr.get("error", None) is not None,
            })
            
        self.df_queries = pd.DataFrame(flat_results)
        
        # We need query cost. Using config pricing
        p = self.config.pricing
        self.df_queries["cost_usd"] = (
            (self.df_queries["tokens_in"] / 1_000_000) * p.llm_input_per_1m +
            (self.df_queries["tokens_out"] / 1_000_000) * p.llm_output_per_1m
        )

    def generate_all(self):
        print("\n--- Generating Reports ---")
        self._save_csvs()
        self._generate_charts()
        self._generate_markdown()
        print(f"Reports available in {self.output_dir}")

    def _save_csvs(self):
        """Export raw and aggregated CSVs."""
        self.df_queries.to_csv(self.output_dir / "raw_queries.csv", index=False)
        
        # Aggregated
        agg = self.df_queries.groupby("system").agg(
            accuracy=("correct", "mean"),
            avg_score=("score", "mean"),
            avg_entity_recall=("entity_recall", "mean"),
            avg_source_recall=("source_recall", "mean"),
            latency_mean=("latency_total", "mean"),
            latency_p95=("latency_total", lambda x: x.quantile(0.95)),
            tokens_avg=("tokens_total", "mean"),
            cost_avg=("cost_usd", "mean"),
            llm_calls_avg=("llm_calls", "mean"),
            error_rate=("error", "mean")
        ).reset_index()
        
        agg.to_csv(self.output_dir / "aggregated_metrics.csv", index=False)
        self.df_agg = agg

    def _generate_charts(self):
        """Generate comparison plots."""
        sns.set_theme(style="whitegrid")

        # 1. Accuracy
        plt.figure(figsize=(10, 6))
        sns.barplot(data=self.df_agg, x="system", y="accuracy")
        plt.title("System Accuracy (Correctness)")
        plt.ylim(0, 1.05)
        plt.savefig(self.charts_dir / "accuracy.png")
        plt.close()

        # 2. Latency Boxplot
        plt.figure(figsize=(10, 6))
        sns.boxplot(data=self.df_queries, x="system", y="latency_total", showfliers=False)
        plt.title("Latency Distribution (ms)")
        plt.savefig(self.charts_dir / "latency.png")
        plt.close()
        
        # 3. Recall Metrics
        recall_df = self.df_agg[["system", "avg_entity_recall", "avg_source_recall"]]
        recall_melt = pd.melt(recall_df, id_vars="system", var_name="Metric", value_name="Recall")
        plt.figure(figsize=(10, 6))
        sns.barplot(data=recall_melt, x="system", y="Recall", hue="Metric")
        plt.title("Retrieval Recall Metrics")
        plt.ylim(0, 1.05)
        plt.savefig(self.charts_dir / "recall.png")
        plt.close()

        # 4. Token Usage
        plt.figure(figsize=(10, 6))
        sns.barplot(data=self.df_agg, x="system", y="tokens_avg")
        plt.title("Average Total Tokens per Query")
        plt.savefig(self.charts_dir / "tokens.png")
        plt.close()

    def _generate_markdown(self):
        """Generate the final markdown report."""
        md = [
            "# Lab Benchmark Report: GraphRAG vs PostgreSQL+RAG vs LLM Wiki\n",
            f"**Generated At:** {self.data.get('timestamp')}",
            f"**Dataset Version:** {self.data.get('dataset_version')}",
            f"**Model:** {self.data.get('model')} | **Embedding:** {self.data.get('embedding_model')}",
            f"**Questions:** {self.data.get('question_count')} | **Runs per Q:** {self.data.get('runs_per_question')}\n",
            "## 1. Executive Summary\n",
        ]

        # Build comparison table
        table_data = []
        for _, row in self.df_agg.iterrows():
            sys_name = row["system"]
            build_row = self.df_build[self.df_build["system_name"] == sys_name]
            build_cost = build_row["construction_cost"].values[0] if not build_row.empty else 0.0
            
            table_data.append([
                sys_name,
                f"{row['accuracy']:.1%}",
                f"{row['avg_entity_recall']:.1%}",
                f"{row['latency_mean']:.0f} ms",
                f"{row['latency_p95']:.0f} ms",
                f"{row['tokens_avg']:.0f}",
                f"${row['cost_avg']:.4f}",
                f"${build_cost:.4f}",
                f"{row['llm_calls_avg']:.1f}",
            ])

        headers = ["System", "Accuracy", "Entity Recall", "Avg Latency", "P95 Latency", 
                   "Avg Tokens", "Avg Query Cost", "Build Cost", "Avg LLM Calls"]
        
        md.append(tabulate(table_data, headers=headers, tablefmt="github"))
        md.append("\n\n## 2. Construction Phase (Phase A)\n")
        
        build_table = []
        for _, row in self.df_build.iterrows():
            build_table.append([
                row["system_name"],
                f"{row['ingestion_time_seconds']:.2f}s",
                f"{row['indexing_time_seconds']:.2f}s",
                f"{row['llm_processing_time_seconds']:.2f}s",
                f"${row['construction_cost']:.4f}",
                f"{row['storage_size_bytes'] / 1024 / 1024:.2f} MB"
            ])
            
        md.append(tabulate(build_table, headers=["System", "Ingestion Time", "Index Time", "LLM Time", "Total Cost", "Storage (MB)"], tablefmt="github"))
        
        md.append("\n\n## 3. Query Phase (Phase B)\n")
        md.append("### Breakdown of Latency\n")
        
        lat_agg = self.df_queries.groupby("system").agg(
            QU_ms=("latency_understanding", "mean"),
            Ret_ms=("latency_retrieval", "mean"),
            Ctx_ms=("latency_context", "mean"),
            Gen_ms=("latency_generation", "mean")
        ).reset_index()
        
        lat_table = lat_agg.values.tolist()
        md.append(tabulate(lat_table, headers=["System", "Query Under. (ms)", "Retrieval (ms)", "Context (ms)", "Generation (ms)"], tablefmt="github", floatfmt=".1f"))
        
        md.append("\n\n## 4. Charts\n")
        md.append("![Accuracy](./charts/accuracy.png)\n")
        md.append("![Latency](./charts/latency.png)\n")
        md.append("![Recall](./charts/recall.png)\n")
        md.append("![Tokens](./charts/tokens.png)\n")

        with open(self.output_dir / "benchmark_report.md", "w", encoding="utf-8") as f:
            f.write("\n".join(md))
