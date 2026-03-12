"""Provider-agnostic LLM interfaces for ranking experiments."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class LLMRankingRequest(BaseModel):
    """Structured request for an optional LLM ranking call."""

    prompt: str
    category: str
    context: dict
    options: list[str]
    memory_summaries: list[str] = Field(default_factory=list)
    profile_card_markdown: str
    stable_profile_markdown: str | None = None
    recent_state_markdown: str | None = None
    heuristic_ranking: list[str] = Field(default_factory=list)
    reviewed_profile_signals: list[dict] = Field(default_factory=list)
    memory_evidence: list[dict] = Field(default_factory=list)


class LLMRankingResult(BaseModel):
    """Result returned by an LLM ranker."""

    ranked_options: list[str]
    explanation: str
    provider: str = "unknown"
    raw_response: dict | None = None


class LLMRanker(Protocol):
    """Protocol for optional LLM-assisted option ranking."""

    def rank(self, request: LLMRankingRequest) -> LLMRankingResult | None:
        """Return ranked options or ``None`` if the ranker is unavailable."""


class NullLLMRanker:
    """A no-op ranker used in the deterministic MVP baseline."""

    def rank(self, request: LLMRankingRequest) -> LLMRankingResult | None:
        return None
