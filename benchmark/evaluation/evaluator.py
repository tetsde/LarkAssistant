"""
Evaluator for benchmark results.

Computes retrieval metrics (entity recall, source recall, relationship recall)
and uses LLM-as-a-Judge to evaluate the final answer against the ground truth.
"""
from __future__ import annotations

import json
from typing import Any

from benchmark.config import Config
from benchmark.llm_client import LLMClient
from benchmark.models import BenchmarkQuestion, EvaluatedResult, JudgeScore, QueryResult


class Evaluator:
    """Evaluates query results against ground truth."""

    def __init__(self, config: Config):
        self.config = config
        self.judge = LLMClient(config.judge, config.pricing)

    def evaluate(self, result: QueryResult, ground_truth: BenchmarkQuestion) -> EvaluatedResult:
        """Evaluate a single query result."""
        
        # 1. Deterministic Retrieval Metrics
        retrieval = result.retrieval
        
        # Entity Recall
        req_entities = set(ground_truth.required_entities)
        found_entities = set(retrieval.retrieved_entity_ids)
        if req_entities:
            entity_recall = len(req_entities.intersection(found_entities)) / len(req_entities)
        else:
            entity_recall = 1.0

        # Source Recall
        req_sources = set(ground_truth.ground_truth_sources)
        found_sources = set(retrieval.retrieved_source_ids)
        # Note: Postgres/Graph may store sources as entities or use text_content IDs,
        # but in this mock, we approximate source recall by checking if the required
        # source ID appears anywhere in the context or found entities.
        found_source_count = 0
        context_text = retrieval.context_text.lower()
        found_combined = found_entities.union(found_sources)
        
        if req_sources:
            for rs in req_sources:
                if rs in found_combined or rs.lower() in context_text:
                    found_source_count += 1
            source_recall = found_source_count / len(req_sources)
        else:
            source_recall = 1.0

        # Relationship Recall (approximate via text match in context or retrieved rels)
        req_rels = ground_truth.required_relationships
        found_rels_text = " ".join(retrieval.retrieved_relationships).lower()
        found_rel_count = 0
        if req_rels:
            for rel in req_rels:
                # Basic string match in context or explicitly found rels
                rel_parts = [r.strip().lower() for r in rel.split("->")]
                if len(rel_parts) == 3:
                    rel_type = rel_parts[1]
                    if rel_type in context_text or rel_type in found_rels_text:
                        found_rel_count += 1
                else:
                    if rel.lower() in context_text or rel.lower() in found_rels_text:
                        found_rel_count += 1
            rel_recall = found_rel_count / len(req_rels)
        else:
            rel_recall = 1.0

        # 2. LLM-as-a-Judge for Answer Correctness
        judge_score = self._evaluate_answer(
            question=ground_truth.question,
            ground_truth_answer=ground_truth.ground_truth_answer,
            generated_answer=result.answer,
        )

        # Attach retrieval metrics
        judge_score.entity_recall = entity_recall
        judge_score.source_recall = source_recall
        judge_score.relationship_recall = rel_recall

        # For total_tokens counting, we should ideally track judge tokens too,
        # but for benchmark simplicity, we keep query tokens and judge tokens separate.

        return EvaluatedResult(
            query_result=result,
            judge=judge_score,
        )

    def _evaluate_answer(self, question: str, ground_truth_answer: str, generated_answer: str) -> JudgeScore:
        """Use LLM to evaluate answer correctness."""
        
        if not generated_answer.strip():
            return JudgeScore(correct=False, score=0.0, reason="Empty answer.")

        prompt = f"""You are an expert evaluator grading an AI assistant's answer.

Question: {question}

Ground Truth Answer:
{ground_truth_answer}

Generated Answer:
{generated_answer}

Evaluate if the Generated Answer correctly and fully answers the question based on the Ground Truth Answer.
It does not need to be an exact word-for-word match, but the factual information and entities mentioned must be correct.
If the Generated Answer says "I don't know" or "information is insufficient", but the Ground Truth has the answer, it is incorrect.

Return a JSON object with:
- "correct": boolean (true if it captures the core facts of the ground truth, false otherwise)
- "score": float between 0.0 and 1.0
- "reason": brief string explaining why

Only return the JSON."""

        try:
            text, _, _ = self.judge.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            data = json.loads(text)
            return JudgeScore(
                correct=data.get("correct", False),
                score=float(data.get("score", 0.0)),
                reason=data.get("reason", ""),
            )
        except Exception as e:
            return JudgeScore(correct=False, score=0.0, reason=f"Evaluation failed: {e}")
