"""
LLM and Embedding client abstraction.

All API calls go through these two classes so that swapping
provider/model only requires changing .env — zero code changes.

Uses the OpenAI SDK which works with any OpenAI-compatible endpoint
(OpenAI, Azure, Groq, Together, local vLLM, Ollama, etc.).
"""
from __future__ import annotations

import time
from typing import Any, Optional

import tiktoken
from openai import OpenAI

from benchmark.config import LLMConfig, EmbeddingConfig, PricingConfig
from benchmark.models import TokenUsage


class LLMClient:
    """Thin wrapper around OpenAI-compatible chat completions."""

    def __init__(self, config: LLMConfig, pricing: Optional[PricingConfig] = None):
        self.config = config
        self.pricing = pricing or PricingConfig()
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        # Token counting — fallback to cl100k_base for unknown models
        try:
            self._encoding = tiktoken.encoding_for_model(config.model)
        except KeyError:
            self._encoding = tiktoken.get_encoding("cl100k_base")

        # Cumulative tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_calls = 0

    def count_tokens(self, text: str) -> int:
        """Count tokens in a string."""
        return len(self._encoding.encode(text))

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: int = 4096,
        response_format: Optional[dict[str, Any]] = None,
    ) -> tuple[str, TokenUsage, float]:
        """
        Send a chat completion request.

        Returns:
            (response_text, token_usage, latency_seconds)
        """
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.config.temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format

        start = time.perf_counter()
        response = self._client.chat.completions.create(**kwargs)
        elapsed = time.perf_counter() - start

        content = response.choices[0].message.content or ""
        usage = response.usage

        if usage:
            tokens = TokenUsage(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            )
        else:
            # Estimate if provider doesn't return usage
            in_tok = sum(self.count_tokens(m.get("content", "")) for m in messages)
            out_tok = self.count_tokens(content)
            tokens = TokenUsage(
                input_tokens=in_tok,
                output_tokens=out_tok,
                total_tokens=in_tok + out_tok,
            )

        self.total_input_tokens += tokens.input_tokens
        self.total_output_tokens += tokens.output_tokens
        self.total_calls += 1

        return content, tokens, elapsed

    def estimate_cost(self, tokens: TokenUsage) -> float:
        """Estimate cost in USD for a single call."""
        input_cost = (tokens.input_tokens / 1_000_000) * self.pricing.llm_input_per_1m
        output_cost = (tokens.output_tokens / 1_000_000) * self.pricing.llm_output_per_1m
        return input_cost + output_cost

    def total_cost(self) -> float:
        """Total estimated cost across all calls."""
        return self.estimate_cost(TokenUsage(
            input_tokens=self.total_input_tokens,
            output_tokens=self.total_output_tokens,
            total_tokens=self.total_input_tokens + self.total_output_tokens,
        ))


class EmbeddingClient:
    """Thin wrapper around OpenAI-compatible embeddings endpoint."""

    def __init__(self, config: EmbeddingConfig, pricing: Optional[PricingConfig] = None):
        self.config = config
        self.pricing = pricing or PricingConfig()
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self.total_tokens = 0
        self.total_calls = 0

    def embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        """
        Generate embeddings for a list of texts.

        Returns:
            (embeddings, total_tokens)
        """
        if not texts:
            return [], 0

        response = self._client.embeddings.create(
            model=self.config.model,
            input=texts,
        )

        embeddings = [item.embedding for item in response.data]
        tokens_used = response.usage.total_tokens if response.usage else 0

        self.total_tokens += tokens_used
        self.total_calls += 1

        return embeddings, tokens_used

    def embed_single(self, text: str) -> tuple[list[float], int]:
        """Embed a single text string."""
        embeddings, tokens = self.embed([text])
        return embeddings[0] if embeddings else [], tokens

    def estimate_cost(self, tokens: int) -> float:
        return (tokens / 1_000_000) * self.pricing.embedding_per_1m

    def total_cost(self) -> float:
        return self.estimate_cost(self.total_tokens)
