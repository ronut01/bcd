from bcd.config import get_settings
from bcd.profile.schemas import StructuredOnboardingResponseInput, UserOnboardingInput
from bcd.profile.service import ProfileService
from bcd.storage.database import init_db, session_scope


def test_manual_onboarding_creates_profile_and_seed_memories(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        profile = ProfileService(session, settings).create_profile_from_onboarding(
            UserOnboardingInput(
                display_name="Casey",
                mbti="ISTJ",
                responses=[
                    StructuredOnboardingResponseInput(
                        question_id="meal_when_tired",
                        option_id="warm_comfort",
                    ),
                    StructuredOnboardingResponseInput(
                        question_id="planning_style",
                        option_id="checklist",
                    ),
                    StructuredOnboardingResponseInput(
                        question_id="budget_style",
                        option_id="value_first",
                    ),
                ],
            )
        )

    assert profile.user_id.startswith("casey-")
    assert profile.memory_count >= 1
    assert profile.profile_card_path is not None
    assert any(item.get("question_id") == "meal_when_tired" for item in profile.onboarding_answers)
