from math import isclose

from bcd.config import get_settings
from bcd.decision.schemas import DecisionOptionInput, DecisionPredictionInput, LLMRuntimeConfig
from bcd.decision.service import DecisionService
from bcd.llm.base import LLMRankingRequest, LLMRankingResult
from bcd.llm.openai_compatible import OpenAICompatibleLLMRanker
from bcd.profile.service import ProfileService
from bcd.storage.database import init_db, session_scope


class StubLLMRanker:
    def rank(self, request: LLMRankingRequest) -> LLMRankingResult | None:
        assert "User Preference Card" in request.profile_card_markdown
        return LLMRankingResult(
            ranked_options=[
                "Greasy burger",
                "Warm noodle soup",
                "Raw salad box",
            ],
            explanation="The LLM emphasized an indulgent comfort choice for this context.",
            provider="stub",
        )


def test_hybrid_mode_uses_llm_ranker_and_preserves_confidence_distribution(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        ProfileService(session, settings).bootstrap_sample_profile()
        prediction = DecisionService(session, settings, llm_ranker=StubLLMRanker()).predict(
            DecisionPredictionInput(
                user_id="sample-alex",
                prompt="Pick dinner after a cold and rainy commute.",
                category="food",
                context={"energy": "low", "weather": "rainy", "time_of_day": "night"},
                prediction_mode="hybrid",
                options=[
                    DecisionOptionInput(option_text="Warm noodle soup"),
                    DecisionOptionInput(option_text="Greasy burger"),
                    DecisionOptionInput(option_text="Raw salad box"),
                ],
            )
        )

    confidences = [item.confidence for item in prediction.ranked_options]
    assert prediction.llm_used is True
    assert prediction.strategy == "hybrid-heuristic-llm"
    assert prediction.llm_provider == "stub"
    assert prediction.profile_card_path is not None
    assert isclose(sum(confidences), 1.0, rel_tol=1e-4, abs_tol=1e-4)


def test_request_scoped_llm_config_uses_runtime_ranker(configured_env, monkeypatch):
    settings = get_settings()
    init_db(settings)

    monkeypatch.setattr(
        OpenAICompatibleLLMRanker,
        "from_runtime_config",
        classmethod(lambda cls, config: StubLLMRanker()),
    )

    with session_scope(settings.database_url) as session:
        ProfileService(session, settings).bootstrap_sample_profile()
        prediction = DecisionService(session, settings).predict(
            DecisionPredictionInput(
                user_id="sample-alex",
                prompt="Pick dinner after a cold and rainy commute.",
                category="food",
                context={"energy": "low", "weather": "rainy", "time_of_day": "night"},
                prediction_mode="llm",
                llm_config=LLMRuntimeConfig(
                    api_key="test-key",
                    base_url="https://example.com/v1",
                    model="dummy-model",
                ),
                options=[
                    DecisionOptionInput(option_text="Warm noodle soup"),
                    DecisionOptionInput(option_text="Greasy burger"),
                    DecisionOptionInput(option_text="Raw salad box"),
                ],
            )
        )

    assert prediction.llm_used is True
    assert prediction.strategy == "llm-ranking"
    assert prediction.llm_provider == "stub"
