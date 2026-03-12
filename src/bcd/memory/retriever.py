"""Memory retrieval orchestration."""

from __future__ import annotations

from sqlmodel import Session

from bcd.config import Settings, get_settings
from bcd.memory.backends import LexicalRetrievalBackend, RetrievalManager, RetrievalQuery
from bcd.memory.schemas import RetrievedMemory
from bcd.storage.repository import BCDRepository


class MemoryRetriever:
    """Retrieve relevant memories using a pluggable backend interface."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.repository = BCDRepository(session)
        self.settings = settings or get_settings()
        self.manager = self._build_manager()

    def retrieve(self, query: RetrievalQuery) -> list[RetrievedMemory]:
        memories = self.repository.list_memories(query.user_id, limit=100)
        return self.manager.retrieve(memories=memories, query=query)

    def _build_manager(self) -> RetrievalManager:
        # Semantic / hybrid backends can be registered here later without changing callers.
        _ = self.settings.retrieval_backend
        return RetrievalManager(backend=LexicalRetrievalBackend())


__all__ = ["MemoryRetriever", "RetrievalQuery"]
