"""
Main entry point to run the complete benchmark lab end-to-end.
"""
import argparse
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.config import load_config
from benchmark.runner import BenchmarkRunner
from reports.generator import ReportGenerator

def main():
    parser = argparse.ArgumentParser(description="Run RAG Benchmark Lab")
    parser.add_argument("--skip-generation", action="store_true", help="Skip dataset generation if it already exists")
    parser.add_argument("--subset", type=int, default=0, help="Run only a subset of questions (e.g. 10 for quick testing)")
    args = parser.parse_args()

    # Load configuration from .env
    config = load_config()

    if not config.llm.api_key:
        print("ERROR: LLM_API_KEY is not set in .env")
        sys.exit(1)

    runner = BenchmarkRunner(config)
    data_dir = PROJECT_ROOT / "data"
    
    # 1. Dataset Generation
    if args.skip_generation and (data_dir / "generated" / "dataset_full.json").exists():
        print("Skipping dataset generation...")
        runner.load_dataset(data_dir / "generated" / "dataset_full.json")
    else:
        runner.generate_dataset(data_dir / "generated")

    # 2. Phase A: Construction
    runner.setup_systems()
    runner.build_knowledge_bases()

    # 3. Phase B: Querying
    runner.run_queries(subset_size=args.subset)
    
    # 4. Save Raw Results
    timestamp = runner.run_record.timestamp.replace(":", "").replace("-", "")
    results_dir = PROJECT_ROOT / "results" / timestamp
    raw_file = runner.save_results(results_dir)
    
    # Cleanup
    runner.cleanup()

    # 5. Generate Reports
    print("\n--- Phase C: Reporting ---")
    reporter = ReportGenerator(raw_file, results_dir, config)
    reporter.generate_all()
    
    print(f"\n✅ Benchmark complete! View the report at: {results_dir}/benchmark_report.md")

if __name__ == "__main__":
    main()
