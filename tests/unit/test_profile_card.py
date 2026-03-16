from pathlib import Path

from bcd.config import get_settings
from bcd.profile.service import ProfileService
from bcd.storage.database import init_db, session_scope


def test_profile_card_is_generated_for_sample_user(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        service = ProfileService(session, settings)
        profile = service.bootstrap_sample_profile()
        card = service.get_profile_card(profile.user_id)

    card_path = Path(card["path"])
    assert card_path.exists()
    assert profile.user_id in card["content"]
    assert "Profile Agent Brief" in card["content"]
    assert "Recent State + Reflection Brief" in card["content"]
    assert "Memory Agent quick recall" in card["content"]
    assert "stable_content" in card
    assert "recent_content" in card
    assert "stable_agent_brief" in card
    assert "recent_state_agent_brief" in card
