from pathlib import Path

from bcd.config import get_settings
from bcd.profile.service import ProfileService
from bcd.storage.database import init_db, session_scope


def test_chatgpt_json_import_creates_profile(configured_env):
    settings = get_settings()
    init_db(settings)
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt_conversations.json"

    with session_scope(settings.database_url) as session:
        result = ProfileService(session, settings).import_profile_from_chatgpt_export(
            display_name="Jordan",
            filename="conversations.json",
            file_bytes=fixture_path.read_bytes(),
        )

    assert result.user_profile.user_id.startswith("jordan-")
    assert result.import_stats["conversation_count"] == 2
    assert result.user_profile.memory_count >= 1
