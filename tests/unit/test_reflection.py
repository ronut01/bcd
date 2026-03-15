import pytest

from bcd.config import get_settings
from bcd.decision.schemas import DecisionOptionInput, DecisionPredictionInput, FeedbackInput
from bcd.decision.service import DecisionService
from bcd.profile.service import ProfileService
from bcd.reflection.service import ReflectionService
from bcd.storage.database import init_db, session_scope


def test_feedback_creates_memory_and_updates_snapshot(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        ProfileService(session, settings).bootstrap_sample_profile()
        prediction = DecisionService(session, settings).predict(
            DecisionPredictionInput(
                user_id="sample-alex",
                prompt="Choose a study plan for an urgent task.",
                category="study",
                context={"urgency": "high", "energy": "medium"},
                options=[
                    DecisionOptionInput(option_text="Structured checklist review"),
                    DecisionOptionInput(option_text="Open-ended exploration"),
                ],
            )
        )
        result = ReflectionService(session).record_feedback(
            prediction.request_id,
            FeedbackInput(
                actual_option_id=prediction.predicted_option_id,
                reason_text="Needed a realistic and structured plan.",
                reason_tags=["structured", "urgent"],
                failure_reasons=["context_missing"],
                context_updates={"deadline": "tonight"},
                preference_shift_note="Urgency outweighed normal exploration.",
            ),
        )

    assert result.created_memory_id
    assert result.reflection_id
    assert result.updated_snapshot_id


def test_duplicate_feedback_for_same_prediction_is_rejected(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        ProfileService(session, settings).bootstrap_sample_profile()
        prediction = DecisionService(session, settings).predict(
            DecisionPredictionInput(
                user_id="sample-alex",
                prompt="Choose a study plan for an urgent task.",
                category="study",
                context={"urgency": "high"},
                options=[
                    DecisionOptionInput(option_text="Structured checklist review"),
                    DecisionOptionInput(option_text="Open-ended exploration"),
                ],
            )
        )
        reflection_service = ReflectionService(session)
        payload = FeedbackInput(
            actual_option_id=prediction.predicted_option_id,
            reason_text="Needed the option that would actually get finished.",
            reason_tags=["urgent"],
            failure_reasons=[],
            context_updates={},
            preference_shift_note=None,
        )

        reflection_service.record_feedback(prediction.request_id, payload)

        with pytest.raises(ValueError, match="already been recorded"):
            reflection_service.record_feedback(prediction.request_id, payload)
