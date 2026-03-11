from bcd.config import get_settings
from bcd.profile.schemas import OnboardingAnswerInput, UserOnboardingInput
from bcd.profile.service import ProfileService
from bcd.storage.database import init_db, session_scope


def test_manual_onboarding_creates_profile_and_seed_memories(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        profile = ProfileService(session, settings).create_profile_from_onboarding(
            UserOnboardingInput(
                display_name="Casey",
                answers=[
                    OnboardingAnswerInput(
                        question="How do you usually make everyday choices?",
                        answer="I usually optimize for comfort and reliability.",
                    ),
                    OnboardingAnswerInput(
                        question="What do you prefer or avoid?",
                        answer="I prefer warm food and structured plans, and I avoid chaotic or greasy options.",
                    ),
                ],
            )
        )

    assert profile.user_id.startswith("casey-")
    assert profile.memory_count >= 1
    assert profile.profile_card_path is not None
