"""
Abstract base class for all retrieval systems.
Each system must implement build() and query() with the same interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from benchmark.models import (
    Dataset,
    QueryResult,
    SystemBuildMetrics,
)


class BaseRetrievalSystem(ABC):
    """Interface that all three systems must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable system name for reports."""
        ...

    @abstractmethod
    def build(self, dataset: Dataset) -> SystemBuildMetrics:
        """
        Ingest the dataset and build internal knowledge structures.

        Returns metrics about the construction phase.
        """
        ...

    @abstractmethod
    def query(self, question: str, question_id: str = "") -> QueryResult:
        """
        Answer a single question.

        Must populate:
        - answer text
        - timing breakdown
        - token usage
        - retrieval details (entities found, sources, operations count)

        Returns a QueryResult.
        """
        ...

    def cleanup(self):
        """Optional cleanup after benchmark is done."""
        pass
