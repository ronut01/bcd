"""Provider-agnostic LLM interfaces for future ranking experiments."""

from __future__ import annotations

from typing import Protocol


class LLMRanker(Protocol):
    """Protocol for optional LLM-assisted option ranking."""

    def rank(self, prompt: str, options: list[str], context: dict, memory_summaries: list[str]) -> list[str] | None:
        """Return ranked option texts or ``None`` if the ranker is unavailable."""


class NullLLMRanker:
    """A no-op ranker used in the deterministic MVP baseline."""

    def rank(self, prompt: str, options: list[str], context: dict, memory_summaries: list[str]) -> list[str] | None:
        return None
