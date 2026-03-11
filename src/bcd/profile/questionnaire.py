"""Structured onboarding questionnaire for cold-start user modeling."""

from __future__ import annotations

QUESTIONNAIRE_VERSION = "v1"

MBTI_OPTIONS = [
    "INTJ", "INTP", "ENTJ", "ENTP",
    "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ",
    "ISTP", "ISFP", "ESTP", "ESFP",
]

STRUCTURED_ONBOARDING_QUESTIONS = [
    {
        "question_id": "travel_preference",
        "title": "Travel preference",
        "prompt": "Which travel setting feels more naturally appealing?",
        "options": [
            {
                "option_id": "mountains",
                "label": "Mountains",
                "description": "Quiet scenery, slower pace, reflective mood.",
                "effects": {
                    "decision_style": ["reflective"],
                    "values": ["calm"],
                    "context_preferences": {"energy_low": ["quiet", "calm"]},
                },
            },
            {
                "option_id": "ocean",
                "label": "Ocean",
                "description": "Open atmosphere, brighter energy, lighter mood.",
                "effects": {
                    "decision_style": ["open"],
                    "values": ["ease"],
                    "context_preferences": {"energy_high": ["open", "fresh"]},
                },
            },
        ],
    },
    {
        "question_id": "meal_when_tired",
        "title": "Meal when tired",
        "prompt": "When you are tired, which meal sounds more likely?",
        "options": [
            {
                "option_id": "warm_comfort",
                "label": "Warm comfort food",
                "description": "Soup, noodles, rice, or something familiar.",
                "effects": {
                    "decision_style": ["comfort-seeking"],
                    "values": ["comfort"],
                    "category_preferences": {
                        "food": {"preferred_keywords": ["warm", "soup", "noodle", "rice", "familiar"]}
                    },
                    "context_preferences": {"energy_low": ["warm", "easy", "familiar"]},
                },
            },
            {
                "option_id": "light_clean",
                "label": "Light and clean food",
                "description": "Something lighter or cleaner even when tired.",
                "effects": {
                    "decision_style": ["disciplined"],
                    "values": ["health"],
                    "category_preferences": {
                        "food": {"preferred_keywords": ["light", "clean", "fresh", "salad"]}
                    },
                    "context_preferences": {"energy_low": ["light", "clean"]},
                },
            },
        ],
    },
    {
        "question_id": "planning_style",
        "title": "Planning style",
        "prompt": "Which study or work approach sounds more like you?",
        "options": [
            {
                "option_id": "checklist",
                "label": "Checklist and structure",
                "description": "I prefer clear steps and a realistic plan.",
                "effects": {
                    "decision_style": ["structured", "practical"],
                    "values": ["clarity", "efficiency"],
                    "category_preferences": {
                        "study": {"preferred_keywords": ["structured", "checklist", "focused", "realistic"]}
                    },
                },
            },
            {
                "option_id": "explore",
                "label": "Open exploration",
                "description": "I like space to improvise and discover.",
                "effects": {
                    "decision_style": ["exploratory"],
                    "values": ["curiosity"],
                    "category_preferences": {
                        "study": {"preferred_keywords": ["open-ended", "creative", "explore", "novel"]}
                    },
                },
            },
        ],
    },
    {
        "question_id": "social_choice",
        "title": "Social choice",
        "prompt": "When you are with friends, what matters more?",
        "options": [
            {
                "option_id": "group_fit",
                "label": "What works for the group",
                "description": "I optimize for shareability and social fit.",
                "effects": {
                    "decision_style": ["social"],
                    "values": ["social fit"],
                    "context_preferences": {"with_friends": ["shareable", "social", "group"]},
                },
            },
            {
                "option_id": "personal_favorite",
                "label": "What I personally want most",
                "description": "I still anchor on my own favorite option.",
                "effects": {
                    "decision_style": ["self-directed"],
                    "values": ["consistency"],
                    "context_preferences": {"with_friends": ["familiar", "preferred"]},
                },
            },
        ],
    },
    {
        "question_id": "budget_style",
        "title": "Budget style",
        "prompt": "Which budget attitude feels more accurate?",
        "options": [
            {
                "option_id": "value_first",
                "label": "Value first",
                "description": "I usually care whether the option feels worth it.",
                "effects": {
                    "decision_style": ["practical"],
                    "values": ["value"],
                    "context_preferences": {"budget_sensitive": ["affordable", "practical", "value"]},
                },
            },
            {
                "option_id": "quality_first",
                "label": "Quality first",
                "description": "I am willing to spend more for the right option.",
                "effects": {
                    "decision_style": ["quality-seeking"],
                    "values": ["quality"],
                    "context_preferences": {"budget_sensitive": ["quality", "worthwhile"]},
                },
            },
        ],
    },
    {
        "question_id": "weekend_energy",
        "title": "Weekend energy",
        "prompt": "Which weekend plan sounds more likely by default?",
        "options": [
            {
                "option_id": "restorative",
                "label": "Recharge quietly",
                "description": "Stay in, recover, or keep things simple.",
                "effects": {
                    "decision_style": ["restorative"],
                    "values": ["comfort"],
                    "context_preferences": {"energy_low": ["cozy", "simple", "quiet"]},
                },
            },
            {
                "option_id": "active",
                "label": "Go out and do something",
                "description": "I want momentum, people, or activity.",
                "effects": {
                    "decision_style": ["active"],
                    "values": ["energy"],
                    "context_preferences": {"energy_high": ["active", "social", "explore"]},
                },
            },
        ],
    },
    {
        "question_id": "media_choice",
        "title": "Media choice",
        "prompt": "What are you more likely to pick for entertainment?",
        "options": [
            {
                "option_id": "cozy_familiar",
                "label": "Cozy and familiar",
                "description": "Character-driven, familiar, or emotionally easy.",
                "effects": {
                    "decision_style": ["comfort-seeking"],
                    "values": ["familiarity"],
                    "category_preferences": {
                        "entertainment": {"preferred_keywords": ["cozy", "familiar", "character", "drama", "comedy"]}
                    },
                },
            },
            {
                "option_id": "intense_novel",
                "label": "Intense or novel",
                "description": "Something new, bold, or stimulating.",
                "effects": {
                    "decision_style": ["novelty-seeking"],
                    "values": ["novelty"],
                    "category_preferences": {
                        "entertainment": {"preferred_keywords": ["intense", "novel", "thriller", "experimental"]}
                    },
                },
            },
        ],
    },
    {
        "question_id": "time_pressure",
        "title": "Time pressure",
        "prompt": "When you are under time pressure, which option feels more like you?",
        "options": [
            {
                "option_id": "finishable",
                "label": "Simple and finishable",
                "description": "I choose something realistic that I can complete.",
                "effects": {
                    "decision_style": ["practical", "structured"],
                    "values": ["completion"],
                    "context_preferences": {"time_pressure": ["simple", "finishable", "clear"]},
                    "category_preferences": {
                        "study": {"preferred_keywords": ["realistic", "focused", "finishable"]}
                    },
                },
            },
            {
                "option_id": "ambitious",
                "label": "Stretch and ambitious",
                "description": "I still lean toward the bigger, more exciting option.",
                "effects": {
                    "decision_style": ["ambitious"],
                    "values": ["growth"],
                    "context_preferences": {"time_pressure": ["ambitious", "high-risk", "stretch"]},
                },
            },
        ],
    },
]
