from datetime import datetime, timezone

from bcd.decision.scoring import ScoringContext, default_scoring_pipeline
from bcd.memory.schemas import RetrievedMemory
from bcd.profile.schemas import PreferenceSnapshotRead, ProfileSignalRead
from bcd.storage.models import DecisionOption


def test_scoring_pipeline_returns_modular_component_scores():
    pipeline = default_scoring_pipeline()
    scoring_context = ScoringContext(
        category="food",
        prompt="Pick dinner after a long rainy day.",
        context={"energy": "low", "weather": "rainy", "time_of_day": "night"},
        long_term_preferences={
            "category_preferences": {
                "food": {
                    "preferred_keywords": ["warm", "soup", "comfort"],
                    "avoided_keywords": ["raw"],
                }
            },
            "context_preferences": {"energy_low": ["easy", "warm", "familiar"]},
        },
        profile_signals=[
            ProfileSignalRead(
                signal_id="sig-1",
                user_id="u-1",
                source_type="sample",
                signal_kind="decision_style",
                signal_name="comfort-seeking",
                proposed_value={"label": "comfort-seeking"},
                current_value={"label": "comfort-seeking"},
                evidence_text="sample",
                status="accepted",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        ],
        snapshot=PreferenceSnapshotRead(
            snapshot_id="snap-1",
            user_id="u-1",
            summary="Recent choices emphasize warm dinners.",
            short_term_preference_notes=["Recent choices repeatedly include 'warm'."],
            drift_markers=[],
            derived_statistics={
                "recent_option_counts": {"food": {"Warm noodle soup": 2}},
                "recent_tags": ["warm"],
                "recent_shift_notes": ["Today the user wants comfort food."],
            },
            created_at=datetime.now(timezone.utc),
        ),
        recent_state_notes=["Today the user wants comfort food right now."],
        retrieved_memories=[
            RetrievedMemory(
                memory_id="mem-1",
                category="food",
                summary="User previously chose warm noodle soup after a tiring rainy evening.",
                chosen_option_text="Warm noodle soup",
                tags=["warm", "comfort"],
                context={"weather": "rainy"},
                retrieval_score=3.2,
                matched_terms=["warm", "rainy"],
                retrieval_components=[],
                why_retrieved=["Same category and strong prompt overlap."],
                memory_role="direct_match",
                created_at=datetime.now(timezone.utc),
            )
        ],
    )
    option = DecisionOption(request_id="req-1", option_text="Warm noodle soup", option_metadata_json={}, position=0)

    scored = pipeline.score_option(scoring_context=scoring_context, option=option)

    component_names = {component.name for component in scored.component_scores}
    assert component_names == {
        "profile_affinity",
        "memory_support",
        "context_compatibility",
        "recent_state_influence",
        "recent_trend_influence",
    }
    assert scored.supporting_evidence
