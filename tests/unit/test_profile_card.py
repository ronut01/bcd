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
    assert "Stable Profile Card" in card["content"]
    assert "Recent State Card" in card["content"]
    assert "Representative recent memories" in card["content"]
    assert "stable_content" in card
    assert "recent_content" in card
