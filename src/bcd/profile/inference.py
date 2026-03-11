"""Heuristic profile inference from onboarding answers and imported chat data."""

from __future__ import annotations

import json
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from io import BytesIO

from bcd.profile.questionnaire import MBTI_OPTIONS, STRUCTURED_ONBOARDING_QUESTIONS
from bcd.utils.text import tokenize


STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "always",
    "and",
    "because",
    "been",
    "but",
    "choose",
    "choosing",
    "conversation",
    "data",
    "dont",
    "from",
    "have",
    "into",
    "just",
    "like",
    "make",
    "more",
    "much",
    "need",
    "often",
    "prefer",
    "really",
    "said",
    "something",
    "that",
    "them",
    "then",
    "they",
    "this",
    "those",
    "usually",
    "very",
    "want",
    "when",
    "with",
    "would",
    "your",
}

CATEGORY_KEYWORDS = {
    "food": {"food", "dinner", "lunch", "breakfast", "ramen", "meal", "restaurant", "coffee", "tea", "dessert"},
    "entertainment": {"movie", "show", "book", "music", "watch", "game", "drama", "comedy", "film"},
    "study": {"study", "learn", "course", "project", "paper", "research", "checklist", "plan", "focus"},
    "shopping": {"buy", "purchase", "shop", "budget", "price", "cheap", "expensive", "clothes", "outfit"},
}

STYLE_KEYWORDS = {
    "structured": {"structured", "checklist", "step", "plan", "organized", "outline", "systematic"},
    "practical": {"practical", "realistic", "efficient", "simple", "reliable", "low-friction"},
    "comfort-seeking": {"comfort", "cozy", "warm", "familiar", "safe", "easy"},
    "social": {"friends", "group", "social", "together", "shareable", "partner"},
    "exploratory": {"explore", "experiment", "creative", "novel", "new", "brainstorm"},
    "reflective": {"feel", "think", "reflect", "why", "concern", "worry", "meaning"},
}

VALUE_KEYWORDS = {
    "comfort": {"comfort", "cozy", "warm", "easy"},
    "reliability": {"reliable", "familiar", "safe", "stable"},
    "efficiency": {"efficient", "fast", "quick", "productive"},
    "social fit": {"group", "social", "shareable", "together"},
    "curiosity": {"explore", "novel", "creative", "new"},
}

POSITIVE_PATTERNS = [
    re.compile(r"\b(?:i|we)\s+(?:really\s+)?(?:like|love|prefer|enjoy)\s+([^.!?\n]{3,120})", re.IGNORECASE),
    re.compile(r"\b(?:i|we)\s+(?:usually|often|tend to)\s+(?:choose|pick|go for)\s+([^.!?\n]{3,120})", re.IGNORECASE),
]

NEGATIVE_PATTERNS = [
    re.compile(r"\b(?:i|we)\s+(?:do not|don't|dislike|hate|avoid)\s+([^.!?\n]{3,120})", re.IGNORECASE),
]


@dataclass(slots=True)
class PreferenceSeed:
    category: str
    summary: str
    chosen_option_text: str
    tags: list[str]
    context: dict


@dataclass(slots=True)
class ChatGPTImportPayload:
    title: str
    text: str
    created_at: str | None = None


def slugify_display_name(display_name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")
    return base or "custom-user"


def _meaningful_tokens(text: str) -> list[str]:
    return [token for token in tokenize(text) if len(token) > 2 and token not in STOPWORDS]


def _extract_phrases(text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    phrases: list[str] = []
    for pattern in patterns:
        for match in pattern.findall(text):
            phrase = re.sub(r"\s+", " ", match).strip(" ,.;:")
            if phrase:
                phrases.append(phrase)
    return phrases


def infer_category(text: str) -> str:
    token_set = set(_meaningful_tokens(text))
    best_category = "general"
    best_score = 0
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = len(token_set & keywords)
        if score > best_score:
            best_category = category
            best_score = score
    return best_category


def get_structured_questionnaire() -> dict:
    """Return the structured onboarding questionnaire definition."""

    return {
        "version": "v1",
        "mbti_options": MBTI_OPTIONS,
        "questions": [
            {
                "question_id": question["question_id"],
                "title": question["title"],
                "prompt": question["prompt"],
                "options": [
                    {
                        "option_id": option["option_id"],
                        "label": option["label"],
                        "description": option["description"],
                    }
                    for option in question["options"]
                ],
            }
            for question in STRUCTURED_ONBOARDING_QUESTIONS
        ],
    }


def build_profile_from_structured_onboarding(
    display_name: str,
    mbti: str,
    responses: list[dict],
) -> dict:
    """Build a deterministic starter profile from structured onboarding responses."""

    if mbti not in MBTI_OPTIONS:
        raise ValueError(f"Unsupported MBTI type '{mbti}'.")

    question_index = {item["question_id"]: item for item in STRUCTURED_ONBOARDING_QUESTIONS}
    style_counter: Counter[str] = Counter()
    value_counter: Counter[str] = Counter()
    category_preferences: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"preferred_keywords": set(), "avoided_keywords": set()}
    )
    context_preferences: dict[str, set[str]] = defaultdict(set)
    behavior_notes: list[str] = []
    onboarding_answers: list[dict] = []
    memory_seeds: list[PreferenceSeed] = []

    mbti_effects = {
        "I": {"decision_style": ["reflective"], "values": ["personal fit"]},
        "E": {"decision_style": ["social"], "values": ["energy"]},
        "S": {"decision_style": ["practical"], "values": ["clarity"]},
        "N": {"decision_style": ["exploratory"], "values": ["curiosity"]},
        "T": {"decision_style": ["analytical"], "values": ["consistency"]},
        "F": {"decision_style": ["value-sensitive"], "values": ["personal meaning"]},
        "J": {"decision_style": ["structured"], "values": ["predictability"]},
        "P": {"decision_style": ["adaptive"], "values": ["flexibility"]},
    }

    for letter in mbti:
        effect = mbti_effects.get(letter)
        if not effect:
            continue
        for style in effect.get("decision_style", []):
            style_counter[style] += 1
        for value in effect.get("values", []):
            value_counter[value] += 1

    for response in responses:
        question = question_index.get(response["question_id"])
        if question is None:
            raise ValueError(f"Unknown onboarding question id '{response['question_id']}'.")
        option = next((item for item in question["options"] if item["option_id"] == response["option_id"]), None)
        if option is None:
            raise ValueError(
                f"Unknown option id '{response['option_id']}' for question '{response['question_id']}'."
            )

        onboarding_answers.append(
            {
                "question_id": question["question_id"],
                "question": question["prompt"],
                "option_id": option["option_id"],
                "answer": option["label"],
            }
        )
        effects = option.get("effects", {})
        for style in effects.get("decision_style", []):
            style_counter[style] += 2
        for value in effects.get("values", []):
            value_counter[value] += 2
        for context_key, values in effects.get("context_preferences", {}).items():
            context_preferences[context_key].update(values)
        for category, preference_bundle in effects.get("category_preferences", {}).items():
            category_preferences[category]["preferred_keywords"].update(
                preference_bundle.get("preferred_keywords", [])
            )
            category_preferences[category]["avoided_keywords"].update(
                preference_bundle.get("avoided_keywords", [])
            )

        behavior_notes.append(
            f"For '{question['title']}', the user selected '{option['label']}'."
        )
        derived_category = next(iter(effects.get("category_preferences", {})), "general")
        memory_seeds.append(
            PreferenceSeed(
                category=derived_category,
                summary=(
                    f"Structured onboarding signal: for '{question['prompt']}', "
                    f"the user selected '{option['label']}'."
                ),
                chosen_option_text=option["label"],
                tags=[
                    question["question_id"],
                    option["option_id"],
                    *list(dict.fromkeys(tokenize(option["label"])))[:4],
                ],
                context={"source": "structured_onboarding", "mbti": mbti},
            )
        )

    if not onboarding_answers:
        raise ValueError("At least one onboarding response is required.")

    top_styles = [item for item, _ in style_counter.most_common(4)] or ["context-sensitive", "practical"]
    top_values = [item for item, _ in value_counter.most_common(4)] or ["comfort", "reliability"]
    category_preferences_payload = {
        category: {
            "preferred_keywords": sorted(values["preferred_keywords"]),
            "avoided_keywords": sorted(values["avoided_keywords"]),
        }
        for category, values in category_preferences.items()
        if values["preferred_keywords"] or values["avoided_keywords"]
    }
    context_preferences_payload = {
        key: sorted(values)
        for key, values in context_preferences.items()
        if values
    }
    prominent_categories = list(category_preferences_payload)[:3] or ["general"]

    profile_summary = (
        f"{display_name} has a structured cold-start profile built from MBTI {mbti} and objective preference choices. "
        f"Current stable signals emphasize {', '.join(top_styles[:3])}, with stronger preference activity around "
        f"{', '.join(prominent_categories)}. The user appears to optimize for {', '.join(top_values[:3])}."
    )

    return {
        "profile_summary": profile_summary,
        "personality_signals": {
            "mbti": mbti,
            "decision_style": top_styles,
            "values": top_values,
            "behavior_notes": list(dict.fromkeys(behavior_notes))[:4],
        },
        "long_term_preferences": {
            "category_preferences": category_preferences_payload,
            "context_preferences": context_preferences_payload,
        },
        "onboarding_answers": onboarding_answers,
        "memory_seeds": memory_seeds[:10],
    }


def build_preference_profile(
    display_name: str,
    source_answers: list[dict],
    free_texts: list[str],
) -> dict:
    style_counter: Counter[str] = Counter()
    value_counter: Counter[str] = Counter()
    positive_tokens_by_category: dict[str, Counter[str]] = defaultdict(Counter)
    negative_tokens_by_category: dict[str, Counter[str]] = defaultdict(Counter)
    behavior_notes: list[str] = []
    memory_seeds: list[PreferenceSeed] = []

    for text in free_texts:
        lowered = text.lower()
        category = infer_category(text)
        positive_phrases = _extract_phrases(text, POSITIVE_PATTERNS)
        negative_phrases = _extract_phrases(text, NEGATIVE_PATTERNS)

        for style, keywords in STYLE_KEYWORDS.items():
            style_counter[style] += sum(token in lowered for token in keywords)
        for value, keywords in VALUE_KEYWORDS.items():
            value_counter[value] += sum(token in lowered for token in keywords)

        if "tired" in lowered or "low energy" in lowered or "exhaust" in lowered:
            behavior_notes.append("When low on energy, this user tends to simplify choices and favor easier options.")
        if "friends" in lowered or "group" in lowered or "together" in lowered:
            behavior_notes.append("Social context appears to increase flexibility and preference for group-compatible options.")
        if "budget" in lowered or "afford" in lowered or "cheap" in lowered:
            behavior_notes.append("Budget sensitivity shows up in the user's decision framing.")

        for phrase in positive_phrases:
            for token in _meaningful_tokens(phrase):
                positive_tokens_by_category[category][token] += 1
            memory_seeds.append(
                PreferenceSeed(
                    category=category,
                    summary=f"Preference signal from onboarding or imported data: the user positively described '{phrase}'.",
                    chosen_option_text=phrase[:120],
                    tags=list(dict.fromkeys(_meaningful_tokens(phrase)))[:8],
                    context={},
                )
            )

        for phrase in negative_phrases:
            for token in _meaningful_tokens(phrase):
                negative_tokens_by_category[category][token] += 1

    decision_style = [item for item, count in style_counter.most_common(3) if count > 0] or [
        "context-sensitive",
        "preference-driven",
        "practical",
    ]
    values = [item for item, count in value_counter.most_common(3) if count > 0] or [
        "comfort",
        "reliability",
        "efficiency",
    ]

    category_preferences: dict[str, dict[str, list[str]]] = {}
    for category in set(list(positive_tokens_by_category) + list(negative_tokens_by_category)):
        preferred = [token for token, _ in positive_tokens_by_category[category].most_common(8)]
        avoided = [token for token, _ in negative_tokens_by_category[category].most_common(6)]
        if preferred or avoided:
            category_preferences[category] = {
                "preferred_keywords": preferred,
                "avoided_keywords": avoided,
            }

    top_categories = [category for category, prefs in category_preferences.items() if prefs.get("preferred_keywords")]
    if not top_categories:
        top_categories = ["general"]

    unique_behavior_notes = list(dict.fromkeys(behavior_notes))[:3]
    profile_summary = (
        f"{display_name} appears to make decisions in a {', '.join(decision_style[:2])} way. "
        f"Current signals suggest stronger preference activity around {', '.join(top_categories[:3])}. "
        f"The user tends to optimize for {', '.join(values[:3])}."
    )

    return {
        "profile_summary": profile_summary,
        "personality_signals": {
            "decision_style": decision_style,
            "values": values,
            "behavior_notes": unique_behavior_notes,
        },
        "long_term_preferences": {
            "category_preferences": category_preferences,
            "context_preferences": {
                "energy_low": ["easy", "warm", "familiar", "simple"],
                "with_friends": ["shareable", "social", "group", "together"],
                "budget_sensitive": ["affordable", "value", "practical", "cheap"],
            },
        },
        "onboarding_answers": source_answers,
        "memory_seeds": memory_seeds[:8],
    }


def _extract_message_text(message: dict) -> str:
    content = message.get("content") or {}
    if isinstance(content, dict):
        parts = content.get("parts")
        if isinstance(parts, list):
            return "\n".join(str(part) for part in parts if isinstance(part, str)).strip()
        text = content.get("text")
        if isinstance(text, str):
            return text.strip()
    return ""


def load_chatgpt_export(file_bytes: bytes, filename: str) -> list[ChatGPTImportPayload]:
    lower_name = filename.lower()
    raw_data: object
    if lower_name.endswith(".zip"):
        with zipfile.ZipFile(BytesIO(file_bytes)) as archive:
            target_name = next((name for name in archive.namelist() if name.endswith("conversations.json")), None)
            if target_name is None:
                raise ValueError("The uploaded ChatGPT export zip does not contain conversations.json.")
            raw_data = json.loads(archive.read(target_name).decode("utf-8"))
    elif lower_name.endswith(".json"):
        raw_data = json.loads(file_bytes.decode("utf-8"))
    else:
        raise ValueError("Unsupported file type. Upload a ChatGPT export .zip or a conversations.json file.")

    if not isinstance(raw_data, list):
        raise ValueError("The uploaded conversations file did not contain the expected conversation list.")

    results: list[ChatGPTImportPayload] = []
    for conversation in raw_data:
        if not isinstance(conversation, dict):
            continue
        title = str(conversation.get("title") or "Untitled conversation")
        mapping = conversation.get("mapping") or {}
        if not isinstance(mapping, dict):
            continue
        snippets: list[str] = []
        for node in mapping.values():
            if not isinstance(node, dict):
                continue
            message = node.get("message")
            if not isinstance(message, dict):
                continue
            author = message.get("author") or {}
            if not isinstance(author, dict) or author.get("role") != "user":
                continue
            text = _extract_message_text(message)
            if text:
                snippets.append(text)
        if snippets:
            results.append(
                ChatGPTImportPayload(
                    title=title,
                    text="\n".join(snippets[:10]),
                    created_at=str(conversation.get("create_time")) if conversation.get("create_time") else None,
                )
            )
    if not results:
        raise ValueError("No user-authored messages were found in the uploaded ChatGPT export.")
    return results


def build_profile_from_chatgpt_export(display_name: str, imported_payloads: list[ChatGPTImportPayload]) -> dict:
    free_texts = [payload.text for payload in imported_payloads[:150]]
    source_answers = [
        {"question": "Imported source", "answer": "ChatGPT data export"},
        {"question": "Conversation count analyzed", "answer": str(len(imported_payloads))},
        {"question": "Representative titles", "answer": [payload.title for payload in imported_payloads[:5]]},
    ]
    inferred = build_preference_profile(display_name=display_name, source_answers=source_answers, free_texts=free_texts)
    if not inferred["memory_seeds"]:
        title_tokens = Counter()
        for payload in imported_payloads[:20]:
            title_tokens.update(_meaningful_tokens(payload.title))
            inferred["memory_seeds"].append(
                PreferenceSeed(
                    category=infer_category(payload.title + " " + payload.text),
                    summary=f"Imported conversation signal from '{payload.title}'.",
                    chosen_option_text=payload.title[:120],
                    tags=list(dict.fromkeys(_meaningful_tokens(payload.title + ' ' + payload.text)))[:8],
                    context={"source": "chatgpt_export"},
                )
            )
        top_tokens = [token for token, _ in title_tokens.most_common(6)]
        inferred["profile_summary"] += (
            f" Imported conversations repeatedly focused on: {', '.join(top_tokens)}."
            if top_tokens
            else " Imported conversations provided additional preference evidence."
        )
    import_stats = {
        "conversation_count": len(imported_payloads),
        "sample_titles": [payload.title for payload in imported_payloads[:5]],
    }
    inferred["import_stats"] = import_stats
    return inferred
