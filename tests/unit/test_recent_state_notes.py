from bcd.config import get_settings
from bcd.profile.schemas import RecentStateNoteInput
from bcd.profile.service import ProfileService
from bcd.storage.database import init_db, session_scope


def test_recent_state_notes_can_be_added_and_removed(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        service = ProfileService(session, settings)
        profile = service.bootstrap_sample_profile()
        note = service.add_recent_state_note(
            profile.user_id,
            RecentStateNoteInput(note_text="Today the user is unusually tired and wants the easiest option."),
        )
        listed = service.list_recent_state_notes(profile.user_id)
        deleted = service.delete_recent_state_note(profile.user_id, note.note_id)
        remaining = service.list_recent_state_notes(profile.user_id)

    assert note.note_id
    assert len(listed) == 1
    assert deleted["deleted"] is True
    assert remaining == []
