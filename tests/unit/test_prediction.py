from math import isclose

from bcd.config import get_settings
from bcd.decision.schemas import DecisionOptionInput, DecisionPredictionInput
from bcd.decision.service import DecisionService
from bcd.profile.schemas import RecentStateNoteInput
from bcd.profile.service import ProfileService
from bcd.storage.database import init_db, session_scope


def test_predict_returns_valid_option_and_normalized_confidence(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        ProfileService(session, settings).bootstrap_sample_profile()
        prediction = DecisionService(session, settings).predict(
            DecisionPredictionInput(
                user_id="sample-alex",
                prompt="Pick dinner after a cold and rainy commute.",
                category="food",
                context={"energy": "low", "weather": "rainy", "time_of_day": "night"},
                options=[
                    DecisionOptionInput(option_text="Warm noodle soup"),
                    DecisionOptionInput(option_text="Heavy fried platter"),
                    DecisionOptionInput(option_text="Raw salad box"),
                ],
            )
        )

    confidences = [item.confidence for item in prediction.ranked_options]
    assert prediction.predicted_option_id in {item.option_id for item in prediction.ranked_options}
    assert isclose(sum(confidences), 1.0, rel_tol=1e-4, abs_tol=1e-4)
    assert prediction.explanation_sections.top_choice_summary
    assert prediction.ranked_options[0].component_scores
    assert prediction.ranked_options[0].supporting_evidence


def test_recent_state_note_can_shift_the_top_prediction(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        profile_service = ProfileService(session, settings)
        profile_service.bootstrap_sample_profile()
        baseline_prediction = DecisionService(session, settings).predict(
            DecisionPredictionInput(
                user_id="sample-alex",
                prompt="Pick dinner after a cold and rainy commute.",
                category="food",
                context={"energy": "low", "weather": "rainy", "time_of_day": "night"},
                options=[
                    DecisionOptionInput(option_text="Warm noodle soup"),
                    DecisionOptionInput(option_text="Greasy burger"),
                ],
            )
        )
        profile_service.add_recent_state_note(
            "sample-alex",
            RecentStateNoteInput(note_text="Today the user specifically wants a greasy burger right now."),
        )
        shifted_prediction = DecisionService(session, settings).predict(
            DecisionPredictionInput(
                user_id="sample-alex",
                prompt="Pick dinner after a cold and rainy commute.",
                category="food",
                context={"energy": "low", "weather": "rainy", "time_of_day": "night"},
                options=[
                    DecisionOptionInput(option_text="Warm noodle soup"),
                    DecisionOptionInput(option_text="Greasy burger"),
                ],
            )
        )

    assert baseline_prediction.predicted_option_text in {"Warm noodle soup", "Greasy burger"}
    assert shifted_prediction.predicted_option_text == "Greasy burger"
    assert any(
        component.name == "recent_state_influence" and component.weighted_score > 0
        for component in shifted_prediction.ranked_options[0].component_scores
    )
