"""Bundled showcase personas and signature scenarios for the local demo."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


DEMO_PERSONAS: list[dict] = [
    {
        "sample_id": "alex_chen",
        "user_id": "sample-alex",
        "display_name": "Alex Chen",
        "headline": "Comfort-first, low-friction decider",
        "signature_hook": "Best first run if you want an instantly legible winner, runner-up, and adaptation twist.",
        "description": (
            "Alex usually defaults to familiar, warm, practical choices and becomes even more predictable "
            "when tired or under light pressure."
        ),
        "tags": ["food", "comfort", "low-energy", "memory-rich"],
        "default_scenario_id": "alex_rainy_dinner",
        "profile_path": "data/sample_profiles/alex_chen.json",
        "history_path": "data/sample_decisions/alex_seed_history.json",
    },
    {
        "sample_id": "maya_patel",
        "user_id": "sample-maya",
        "display_name": "Maya Patel",
        "headline": "Tasteful explorer with a social streak",
        "signature_hook": "Good for demos where taste, vibe, and social fit should beat generic convenience.",
        "description": (
            "Maya likes options that feel curated, expressive, and a bit memorable, but still notices budget, "
            "effort, and whether the choice fits the vibe of the people involved."
        ),
        "tags": ["entertainment", "shopping", "social", "curated taste"],
        "default_scenario_id": "maya_friday_plan",
        "profile_path": "data/sample_profiles/maya_patel.json",
        "history_path": "data/sample_decisions/maya_seed_history.json",
    },
    {
        "sample_id": "jordan_lee",
        "user_id": "sample-jordan",
        "display_name": "Jordan Lee",
        "headline": "Structured optimizer who avoids chaos",
        "signature_hook": "Best for showing that bcd predicts a person's realistic pick, not the flashiest option.",
        "description": (
            "Jordan tends to choose clean, time-boxed, efficient options, especially for study, routines, and "
            "practical purchases."
        ),
        "tags": ["study", "shopping", "structured", "practical"],
        "default_scenario_id": "jordan_focus_block",
        "profile_path": "data/sample_profiles/jordan_lee.json",
        "history_path": "data/sample_decisions/jordan_seed_history.json",
    },
]


DEMO_SCENARIOS: list[dict] = [
    {
        "scenario_id": "alex_rainy_dinner",
        "sample_id": "alex_chen",
        "title": "Rainy low-energy dinner",
        "subtitle": "A fast first-run scenario that makes the profile, memory, and current context line up immediately.",
        "category": "food",
        "prompt": "Pick dinner after a cold rainy commute when Alex has almost no energy left.",
        "context": {"time_of_day": "night", "energy": "low", "weather": "rainy", "with": "alone"},
        "options": ["Warm noodle soup", "Double bacon burger", "Late-night salad box"],
        "demo_takeaway": "Shows comfort, recent state, and dinner memory snapping into a quick personalized winner.",
        "feedback_demo": {
            "title": "Add a temporary lighter-food shift",
            "actual_option_text": "Late-night salad box",
            "reason_text": "Wanted something lighter after eating heavy food earlier.",
            "reason_tags": ["light", "reset"],
            "failure_reasons": ["recent_state_not_captured"],
            "context_updates": {"energy": "low", "mood": "reset"},
            "preference_shift_note": "Tonight Alex wanted something lighter than usual.",
            "expected_effect": "The rerun should visibly promote the lighter option and surface a new short-term shift.",
        },
    },
    {
        "scenario_id": "alex_friends_night",
        "sample_id": "alex_chen",
        "title": "Friends visiting tonight",
        "subtitle": "Shows how the same person becomes more social and group-aware in a different context.",
        "category": "food",
        "prompt": "Choose dinner for Alex when two friends are visiting and everyone wants something easy to share.",
        "context": {"time_of_day": "night", "energy": "medium", "with": "friends", "budget": "medium"},
        "options": ["Shareable hotpot restaurant", "Solo ramen counter", "Expensive tasting menu"],
        "demo_takeaway": "Shows the same person shifting from solo comfort toward a social, shareable pick.",
        "feedback_demo": {
            "title": "Add a low-energy last-minute mood drop",
            "actual_option_text": "Solo ramen counter",
            "reason_text": "Alex suddenly wanted something quieter and less effort than a group dinner.",
            "reason_tags": ["low_energy", "quiet"],
            "failure_reasons": ["recent_state_not_captured"],
            "context_updates": {"energy": "low", "with": "alone"},
            "preference_shift_note": "The social plan collapsed and Alex wanted the easiest solo fallback.",
            "expected_effect": "The rerun should shrink the social bias and make the solo comfort option more competitive.",
        },
    },
    {
        "scenario_id": "maya_friday_plan",
        "sample_id": "maya_patel",
        "title": "Friday night vibe check",
        "subtitle": "Highlights taste, social context, and why a curated option wins over generic convenience.",
        "category": "entertainment",
        "prompt": "Pick Maya's Friday night plan after a demanding week when one close friend is free.",
        "context": {"time_of_day": "evening", "energy": "medium", "with": "friends", "budget": "medium"},
        "options": ["Neighborhood wine bar with live jazz", "Stay home with random streaming", "Huge loud sports bar"],
        "demo_takeaway": "Highlights why taste and vibe fit can beat generic convenience for a specific person.",
        "feedback_demo": {
            "title": "Add a sudden need for a quiet reset",
            "actual_option_text": "Stay home with random streaming",
            "reason_text": "Maya wanted a low-effort reset instead of going out after the week felt longer than expected.",
            "reason_tags": ["quiet", "reset", "low_effort"],
            "failure_reasons": ["recent_state_not_captured"],
            "context_updates": {"energy": "low", "with": "alone"},
            "preference_shift_note": "Tonight Maya wants a quiet reset more than a curated social experience.",
            "expected_effect": "The rerun should show recent state pulling Maya away from the more expressive social option.",
        },
    },
    {
        "scenario_id": "maya_weekend_purchase",
        "sample_id": "maya_patel",
        "title": "Weekend personal purchase",
        "subtitle": "Shows Maya balancing aesthetics, quality, and budget without collapsing into the cheapest option.",
        "category": "shopping",
        "prompt": "Choose a weekend purchase Maya is actually likely to make for her apartment.",
        "context": {"time_of_day": "morning", "budget": "medium", "urgency": "low"},
        "options": ["Thoughtful ceramic mug set", "Generic discount mug pack", "Pricey designer vase"],
        "demo_takeaway": "Shows taste-sensitive shopping without collapsing into the cheapest or the flashiest option.",
        "feedback_demo": {
            "title": "Add a sudden budget clamp",
            "actual_option_text": "Generic discount mug pack",
            "reason_text": "An unexpected expense made Maya want the cheapest workable option today.",
            "reason_tags": ["budget", "practical"],
            "failure_reasons": ["context_missing"],
            "context_updates": {"budget": "tight"},
            "preference_shift_note": "For this weekend only, Maya is more budget constrained than usual.",
            "expected_effect": "The rerun should visibly strengthen budget pressure and narrow the gap with the cheaper option.",
        },
    },
    {
        "scenario_id": "jordan_focus_block",
        "sample_id": "jordan_lee",
        "title": "High-pressure study block",
        "subtitle": "A strong demo for structured reasoning, recent state, and why open-ended choices lose.",
        "category": "study",
        "prompt": "Pick Jordan's study plan for a stressful Saturday morning before a deadline.",
        "context": {"time_of_day": "morning", "energy": "medium", "urgency": "high", "with": "alone"},
        "options": ["Structured 90-minute checklist sprint", "Read six random papers", "Follow an open-ended side quest"],
        "demo_takeaway": "Makes bcd's identity obvious: predict the realistic choice for this person, not the most ambitious story.",
        "feedback_demo": {
            "title": "Add a curiosity spike that breaks routine",
            "actual_option_text": "Read six random papers",
            "reason_text": "Jordan got pulled into exploratory reading after finding one unusually relevant paper.",
            "reason_tags": ["curiosity", "exploration"],
            "failure_reasons": ["similar_memory_missing"],
            "context_updates": {"urgency": "medium"},
            "preference_shift_note": "Today Jordan is more exploratory than the usual deadline mode suggests.",
            "expected_effect": "The rerun should show exploration pressure entering the model instead of pure structure.",
        },
    },
    {
        "scenario_id": "jordan_practical_buy",
        "sample_id": "jordan_lee",
        "title": "Practical purchase under time pressure",
        "subtitle": "Shows the project predicting what this person would really buy, not what sounds flashy.",
        "category": "shopping",
        "prompt": "Choose the laptop stand Jordan is most likely to buy after comparing options for too long.",
        "context": {"time_of_day": "night", "budget": "medium", "urgency": "high"},
        "options": ["Reliable adjustable stand with good reviews", "Ultra-cheap unstable stand", "Premium designer stand"],
        "demo_takeaway": "Good for showing bcd favoring practical, review-backed choices over extremes.",
        "feedback_demo": {
            "title": "Add a one-time premium splurge mood",
            "actual_option_text": "Premium designer stand",
            "reason_text": "Jordan decided to spend more once rather than keep researching and second-guessing.",
            "reason_tags": ["premium", "decisive"],
            "failure_reasons": ["stable_profile_wrong"],
            "context_updates": {"budget": "flexible"},
            "preference_shift_note": "For this purchase, Jordan was unusually willing to pay for finish and design.",
            "expected_effect": "The rerun should make the premium option less dismissible and highlight a temporary shift.",
        },
    },
]


def get_demo_showcase() -> dict:
    """Return serialized persona and scenario data for the browser demo."""

    return {
        "personas": DEMO_PERSONAS,
        "scenarios": DEMO_SCENARIOS,
    }


def get_demo_persona(sample_id: str) -> dict:
    """Resolve a bundled persona by sample id."""

    for persona in DEMO_PERSONAS:
        if persona["sample_id"] == sample_id:
            return persona
    raise ValueError(f"Unknown demo sample '{sample_id}'.")


def get_demo_persona_paths(sample_id: str) -> tuple[Path, Path]:
    """Return the profile and history paths for a bundled persona."""

    persona = get_demo_persona(sample_id)
    return (
        (PROJECT_ROOT / persona["profile_path"]).resolve(),
        (PROJECT_ROOT / persona["history_path"]).resolve(),
    )
