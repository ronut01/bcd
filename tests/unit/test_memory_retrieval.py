from bcd.config import get_settings
from bcd.memory.retriever import MemoryRetriever, RetrievalQuery
from bcd.profile.service import ProfileService
from bcd.storage.database import init_db, session_scope


def test_retriever_prioritizes_matching_food_memories(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        ProfileService(session, settings).bootstrap_sample_profile()
        memories = MemoryRetriever(session).retrieve(
            RetrievalQuery(
                user_id="sample-alex",
                category="food",
                prompt="Pick a warm dinner after a tiring day.",
                options=["Warm ramen near home", "Cold salad bowl"],
                context={"energy": "low", "time_of_day": "night"},
                limit=3,
            )
        )

    assert memories
    assert memories[0].category == "food"
    assert "warm" in memories[0].summary.lower() or "ramen" in memories[0].chosen_option_text.lower()
    assert memories[0].retrieval_components
    assert memories[0].why_retrieved
    assert memories[0].memory_role in {"direct_match", "supporting", "context_match", "recent_repeat"}
