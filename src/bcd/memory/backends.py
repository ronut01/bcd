"""Retrieval backends for memory lookup."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from bcd.memory.schemas import RetrievedMemory, RetrievalComponentScore
from bcd.storage.models import MemoryEntry
from bcd.utils.text import flatten_to_text, overlap_count, tokenize
from bcd.utils.time import ensure_utc


@dataclass(slots=True)
class RetrievalQuery:
    user_id: str
    category: str
    prompt: str
    options: list[str]
    context: dict
    limit: int = 5


class RetrievalBackend(Protocol):
    """Protocol for retrieval backends."""

    name: str

    def retrieve(self, memories: list[MemoryEntry], query: RetrievalQuery) -> list[RetrievedMemory]:
        """Return scored memory candidates for a query."""


class LexicalRetrievalBackend:
    """Keyword and metadata based retrieval backend."""

    name = "lexical"

    def retrieve(self, memories: list[MemoryEntry], query: RetrievalQuery) -> list[RetrievedMemory]:
        query_tokens = set(
            tokenize(query.prompt)
            + tokenize(query.category)
            + tokenize(" ".join(query.options))
            + tokenize(flatten_to_text(query.context))
        )
        option_tokens = {token.lower() for token in tokenize(" ".join(query.options))}

        scored: list[RetrievedMemory] = []
        for memory in memories:
            memory_tokens = set(
                tokenize(memory.summary)
                + tokenize(memory.chosen_option_text)
                + tokenize(flatten_to_text(memory.context_json))
                + [str(tag).lower() for tag in memory.tags_json]
            )

            category_score = 2.0 if memory.category == query.category else 0.0
            option_similarity = 1.2 if memory.chosen_option_text.lower() in {item.lower() for item in query.options} else 0.0
            prompt_overlap = overlap_count(query_tokens, memory_tokens) * 0.45
            tag_overlap = overlap_count(option_tokens, {str(tag).lower() for tag in memory.tags_json}) * 0.35
            salience_bonus = memory.salience_score * 0.15
            age_days = max((datetime.now(timezone.utc) - ensure_utc(memory.created_at)).days, 0)
            recency_decay = 0.5 / (1 + age_days / 21)

            total_score = category_score + option_similarity + prompt_overlap + tag_overlap + salience_bonus + recency_decay
            if total_score <= 0.65:
                continue

            matched_terms = sorted(query_tokens & memory_tokens)[:8]
            components = [
                RetrievalComponentScore(name="category_match", score=round(category_score, 4), detail="Same category as the current decision." if category_score else "Different category."),
                RetrievalComponentScore(name="option_similarity", score=round(option_similarity, 4), detail="Chosen option text directly matches a current candidate." if option_similarity else "No direct candidate match."),
                RetrievalComponentScore(name="prompt_overlap", score=round(prompt_overlap, 4), detail="Overlap between the current prompt/context and memory wording."),
                RetrievalComponentScore(name="tag_overlap", score=round(tag_overlap, 4), detail="Overlap between candidate tokens and memory tags."),
                RetrievalComponentScore(name="recency_decay", score=round(recency_decay, 4), detail="More recent memories are preferred."),
                RetrievalComponentScore(name="salience_bonus", score=round(salience_bonus, 4), detail="High-salience memories get a small bonus."),
            ]

            role = self._classify_role(memory=memory, query=query, option_similarity=option_similarity, recency_decay=recency_decay)
            why_retrieved = [
                component.detail
                for component in components
                if component.score > 0
            ][:3]

            scored.append(
                RetrievedMemory(
                    memory_id=memory.memory_id,
                    category=memory.category,
                    summary=memory.summary,
                    chosen_option_text=memory.chosen_option_text,
                    tags=list(memory.tags_json),
                    context=dict(memory.context_json),
                    retrieval_score=round(total_score, 4),
                    matched_terms=matched_terms,
                    retrieval_components=components,
                    why_retrieved=why_retrieved,
                    memory_role=role,
                    created_at=memory.created_at,
                )
            )

        scored.sort(key=lambda item: item.retrieval_score, reverse=True)
        return scored[: query.limit]

    @staticmethod
    def _classify_role(
        memory: MemoryEntry,
        query: RetrievalQuery,
        option_similarity: float,
        recency_decay: float,
    ) -> str:
        if option_similarity:
            return "direct_match"
        if memory.category == query.category and recency_decay >= 0.35:
            return "recent_repeat"
        if memory.category == query.category:
            return "supporting"
        return "context_match"


class RetrievalManager:
    """Choose and run retrieval backends behind a stable interface."""

    def __init__(self, backend: RetrievalBackend | None = None) -> None:
        self.backend = backend or LexicalRetrievalBackend()

    def retrieve(self, memories: list[MemoryEntry], query: RetrievalQuery) -> list[RetrievedMemory]:
        return self.backend.retrieve(memories=memories, query=query)
