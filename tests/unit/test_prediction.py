from math import isclose

from bcd.config import get_settings
from bcd.decision.schemas import DecisionOptionInput, DecisionOptionSuggestionInput, DecisionPredictionInput, FeedbackInput
from bcd.decision.service import DecisionService
from bcd.profile.schemas import RecentStateNoteInput
from bcd.profile.service import ProfileService
from bcd.reflection.service import ReflectionService
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
    assert prediction.decision_audit.confidence_label
    assert prediction.ranked_options[0].component_scores
    assert prediction.ranked_options[0].supporting_evidence
    assert prediction.agent_workflow.profile_agent.agent_name == "Profile Agent"
    assert prediction.agent_workflow.recent_state_agent.agent_name == "Recent State Agent"
    assert prediction.agent_workflow.memory_agent.agent_name == "Memory Agent"
    assert prediction.agent_workflow.choice_reasoning_agent.agent_name == "Choice Reasoning Agent"
    assert prediction.agent_workflow.reflection_agent.agent_name == "Reflection Agent"
    assert prediction.top_choice_influence.option_id == prediction.predicted_option_id
    assert prediction.option_influences[0].option_id == prediction.predicted_option_id
    assert prediction.agent_agreement.summary
    assert prediction.agent_agreement.signals


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
            RecentStateNoteInput(
                note_text="Today the user specifically wants a greasy burger right now and does not want warm noodle soup."
            ),
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
    assert shifted_prediction.agent_workflow.recent_state_agent.observations
    assert any("Recent state note supports this option" in item for item in shifted_prediction.option_influences[0].why_choose)
    assert shifted_prediction.agent_agreement.supporting_agents
    assert shifted_prediction.agent_agreement.opposing_agents


def test_feedback_context_updates_carry_into_the_next_prediction(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        ProfileService(session, settings).bootstrap_sample_profile()
        decision_service = DecisionService(session, settings)
        reflection_service = ReflectionService(session)

        first_prediction = decision_service.predict(
            DecisionPredictionInput(
                user_id="sample-alex",
                prompt="Choose a study plan for a deadline tonight.",
                category="study",
                context={"urgency": "high"},
                options=[
                    DecisionOptionInput(option_text="Structured checklist sprint"),
                    DecisionOptionInput(option_text="Open-ended exploration"),
                ],
            )
        )
        reflection_service.record_feedback(
            first_prediction.request_id,
            FeedbackInput(
                actual_option_id=first_prediction.ranked_options[0].option_id,
                reason_text="Needed the most realistic option for a deadline tonight.",
                reason_tags=["urgent", "structured"],
                context_updates={"deadline": "tonight", "energy": "very_low"},
                preference_shift_note="Urgency is dominating curiosity right now.",
            ),
        )
        next_prediction = decision_service.predict(
            DecisionPredictionInput(
                user_id="sample-alex",
                prompt="Choose another study approach.",
                category="study",
                context={"urgency": "high"},
                options=[
                    DecisionOptionInput(option_text="Structured checklist sprint"),
                    DecisionOptionInput(option_text="Long open-ended exploration"),
                ],
            )
        )

    assert next_prediction.decision_audit.active_context["deadline"] == "tonight"
    assert next_prediction.decision_audit.adaptation_signals
    assert any(
        component.name == "adaptive_context_alignment"
        for component in next_prediction.ranked_options[0].component_scores
    )
    assert next_prediction.agent_workflow.reflection_agent.observations
    assert "deadline=tonight" in " ".join(next_prediction.agent_workflow.reflection_agent.observations)


def test_social_context_beyond_friends_changes_the_prediction(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        ProfileService(session, settings).bootstrap_sample_profile()
        decision_service = DecisionService(session, settings)

        neutral_prediction = decision_service.predict(
            DecisionPredictionInput(
                user_id="sample-alex",
                prompt="Pick dinner for tonight.",
                category="food",
                context={},
                options=[
                    DecisionOptionInput(option_text="Solo noodle bowl"),
                    DecisionOptionInput(option_text="Cozy shared pasta"),
                ],
            )
        )
        partner_prediction = decision_service.predict(
            DecisionPredictionInput(
                user_id="sample-alex",
                prompt="Pick dinner for tonight.",
                category="food",
                context={"with": "partner"},
                options=[
                    DecisionOptionInput(option_text="Solo noodle bowl"),
                    DecisionOptionInput(option_text="Cozy shared pasta"),
                ],
            )
        )

    assert neutral_prediction.predicted_option_text in {"Solo noodle bowl", "Cozy shared pasta"}
    assert partner_prediction.predicted_option_text == "Cozy shared pasta"
    assert any(
        component.name == "context_compatibility" and component.weighted_score > 0
        for component in partner_prediction.ranked_options[0].component_scores
    )


def test_urgency_now_uses_time_pressure_preferences(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        ProfileService(session, settings).bootstrap_sample_profile()
        prediction = DecisionService(session, settings).predict(
            DecisionPredictionInput(
                user_id="sample-alex",
                prompt="Choose a study plan for an urgent deadline.",
                category="study",
                context={"urgency": "high"},
                options=[
                    DecisionOptionInput(option_text="Simple finishable checklist"),
                    DecisionOptionInput(option_text="Ambitious open-ended research sprint"),
                ],
            )
        )

    assert prediction.predicted_option_text == "Simple finishable checklist"
    assert any(
        component.name == "context_compatibility" and component.weighted_score > 0
        for component in prediction.ranked_options[0].component_scores
    )


def test_time_of_day_now_uses_profile_context_preferences(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        ProfileService(session, settings).bootstrap_sample_profile()
        prediction = DecisionService(session, settings).predict(
            DecisionPredictionInput(
                user_id="sample-alex",
                prompt="Pick something to watch late tonight.",
                category="entertainment",
                context={"time_of_day": "night"},
                options=[
                    DecisionOptionInput(option_text="A cozy short drama"),
                    DecisionOptionInput(option_text="A bright morning travel show"),
                ],
            )
        )

    assert prediction.predicted_option_text == "A cozy short drama"
    assert any(
        component.name == "context_compatibility" and component.weighted_score > 0
        for component in prediction.ranked_options[0].component_scores
    )


def test_suggest_options_returns_personalized_candidates_without_duplicates(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        ProfileService(session, settings).bootstrap_sample_profile()
        suggestions = DecisionService(session, settings).suggest_options(
            DecisionOptionSuggestionInput(
                user_id="sample-alex",
                prompt="Pick dinner after a tiring rainy evening.",
                category="food",
                context={"energy": "low", "weather": "rainy", "time_of_day": "night"},
                existing_options=["Greasy burger"],
                max_suggestions=4,
            )
        )

    assert suggestions.suggestions
    assert all(item.option_text.lower() != "greasy burger" for item in suggestions.suggestions)
    assert any(label in {"stable profile", "current context", "memory match"} for label in suggestions.suggestions[0].source_labels)
    assert suggestions.suggestions[0].rationale


def test_suggest_options_tracks_the_current_prompt_not_the_previous_one(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        ProfileService(session, settings).bootstrap_sample_profile()
        decision_service = DecisionService(session, settings)

        dinner_suggestions = decision_service.suggest_options(
            DecisionOptionSuggestionInput(
                user_id="sample-alex",
                prompt="Pick dinner after a tiring rainy evening.",
                category="food",
                context={"energy": "low", "weather": "rainy", "time_of_day": "night"},
                max_suggestions=4,
            )
        )
        lunch_suggestions = decision_service.suggest_options(
            DecisionOptionSuggestionInput(
                user_id="sample-alex",
                prompt="Choose lunch for a bright sunny workday.",
                category="food",
                context={"weather": "sunny", "time_of_day": "morning"},
                max_suggestions=4,
            )
        )

    assert dinner_suggestions.suggestions[0].option_text != lunch_suggestions.suggestions[0].option_text
    assert lunch_suggestions.suggestions[0].option_text == "Fresh salad bowl"
