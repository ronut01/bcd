from pathlib import Path

from bcd.config import get_settings
from bcd.profile.schemas import ProfileSignalReviewInput
from bcd.profile.service import ProfileService
from bcd.storage.database import init_db, session_scope


def test_chatgpt_import_creates_pending_signals_that_can_be_reviewed(configured_env):
    settings = get_settings()
    init_db(settings)
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt_conversations.json"

    with session_scope(settings.database_url) as session:
        service = ProfileService(session, settings)
        with fixture_path.open("rb") as handle:
            imported = service.import_profile_from_chatgpt_export(
                display_name="Morgan",
                filename="conversations.json",
                file_bytes=handle.read(),
            )

        user_id = imported.user_profile.user_id
        signals = service.get_profile_signals(user_id)
        pending_signal = next(signal for signal in signals if signal.status == "pending")

        reviewed = service.review_profile_signal(
            user_id,
            pending_signal.signal_id,
            ProfileSignalReviewInput(
                action="edit",
                edited_value={"label": "curated signal"},
                review_note="Adjusted after user review.",
            ),
        )

    assert imported.user_profile.pending_signal_count >= 1
    assert reviewed.signal.status == "edited"
    assert reviewed.signal.current_value == {"label": "curated signal"}
    assert reviewed.user_profile.profile_summary
