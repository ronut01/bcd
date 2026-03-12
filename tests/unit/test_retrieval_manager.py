from datetime import datetime, timezone

from bcd.memory.backends import RetrievalManager, RetrievalQuery
from bcd.storage.models import MemoryEntry


class StubBackend:
    name = "stub"

    def retrieve(self, memories, query):
        self.last_query = query
        self.last_memories = memories
        return []


def test_retrieval_manager_accepts_pluggable_backend():
    backend = StubBackend()
    manager = RetrievalManager(backend=backend)
    query = RetrievalQuery(
        user_id="user-1",
        category="food",
        prompt="Pick dinner.",
        options=["Soup", "Burger"],
        context={},
        limit=3,
    )
    memories = [
        MemoryEntry(
            user_id="user-1",
            source_request_id="req-1",
            category="food",
            summary="summary",
            chosen_option_text="Soup",
            context_json={},
            tags_json=[],
            created_at=datetime.now(timezone.utc),
        )
    ]

    result = manager.retrieve(memories=memories, query=query)

    assert result == []
    assert backend.last_query.category == "food"
    assert len(backend.last_memories) == 1
