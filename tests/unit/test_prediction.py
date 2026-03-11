from math import isclose

from bcd.config import get_settings
from bcd.decision.schemas import DecisionOptionInput, DecisionPredictionInput
from bcd.decision.service import DecisionService
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
