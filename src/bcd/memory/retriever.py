"""Memory retrieval logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session

from bcd.memory.schemas import RetrievedMemory
from bcd.storage.repository import BCDRepository
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


class MemoryRetriever:
    """Retrieve the most relevant memories for a new decision request."""

    def __init__(self, session: Session) -> None:
        self.repository = BCDRepository(session)

    def retrieve(self, query: RetrievalQuery) -> list[RetrievedMemory]:
        memories = self.repository.list_memories(query.user_id, limit=100)
        query_tokens = set(
            tokenize(query.prompt)
            + tokenize(query.category)
            + tokenize(" ".join(query.options))
            + tokenize(flatten_to_text(query.context))
        )

        scored: list[RetrievedMemory] = []
        for memory in memories:
            memory_tokens = set(
                tokenize(memory.summary)
                + tokenize(memory.chosen_option_text)
                + tokenize(flatten_to_text(memory.context_json))
                + [str(tag).lower() for tag in memory.tags_json]
            )
            overlap = overlap_count(query_tokens, memory_tokens)
            score = overlap * 0.45
            if memory.category == query.category:
                score += 2.0
            if memory.chosen_option_text.lower() in [option.lower() for option in query.options]:
                score += 1.0

            age_days = max((datetime.now(timezone.utc) - ensure_utc(memory.created_at)).days, 0)
            score += 0.4 / (1 + age_days / 30)

            if score <= 0.5:
                continue

            matched_terms = sorted(query_tokens & memory_tokens)[:8]
            scored.append(
                RetrievedMemory(
                    memory_id=memory.memory_id,
                    category=memory.category,
                    summary=memory.summary,
                    chosen_option_text=memory.chosen_option_text,
                    tags=list(memory.tags_json),
                    context=dict(memory.context_json),
                    retrieval_score=round(score, 4),
                    matched_terms=matched_terms,
                    created_at=memory.created_at,
                )
            )

        scored.sort(key=lambda item: item.retrieval_score, reverse=True)
        return scored[: query.limit]
