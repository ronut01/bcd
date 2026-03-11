from bcd.config import get_settings
from bcd.profile.service import ProfileService
from bcd.storage.database import init_db, session_scope


def test_bootstrap_creates_sample_profile_and_seed_history(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        profile = ProfileService(session, settings).bootstrap_sample_profile()

    assert profile.user_id == "sample-alex"
    assert profile.history_count >= 4
    assert profile.memory_count >= 4
    assert profile.latest_snapshot is not None
