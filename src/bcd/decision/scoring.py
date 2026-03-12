"""Composable scoring pipeline for personalized choice prediction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bcd.memory.schemas import RetrievedMemory
from bcd.profile.schemas import PreferenceSnapshotRead, ProfileSignalRead
from bcd.storage.models import DecisionOption
from bcd.utils.text import flatten_to_text, overlap_count, tokenize


LOW_ENERGY_PENALTIES = {"complex", "late", "adventure", "exploration", "long", "heavy"}
RAINY_WEATHER_PENALTIES = {"outdoor", "walk", "picnic", "street", "park"}
LOW_BUDGET_PENALTIES = {"premium", "luxury", "expensive", "exclusive"}
TEMPORARY_OVERRIDE_TERMS = {"today", "currently", "right", "now", "this", "time", "for", "now"}
NEGATION_TERMS = {"avoid", "not", "dont", "don't", "skip", "no"}


@dataclass(slots=True)
class ScoringContext:
    """Normalized inputs shared by all score components."""

    category: str
    prompt: str
    context: dict
    long_term_preferences: dict
    profile_signals: list[ProfileSignalRead]
    snapshot: PreferenceSnapshotRead | None
    recent_state_notes: list[str]
    retrieved_memories: list[RetrievedMemory]


@dataclass(slots=True)
class ComponentScore:
    """Result from a single score component."""

    name: str
    raw_score: float
    weight: float
    weighted_score: float
    reason: str
    supporting_evidence: list[str]
    counter_evidence: list[str]


@dataclass(slots=True)
class ScoredOption:
    """Aggregated score details for a candidate option."""

    option: DecisionOption
    raw_score: float
    component_scores: list[ComponentScore]
    supporting_evidence: list[str]
    counter_evidence: list[str]
    reason_summary: str


class ScoreComponent(Protocol):
    """Protocol for pluggable score components."""

    name: str
    weight: float

    def score(self, scoring_context: ScoringContext, option: DecisionOption) -> ComponentScore:
        """Return a weighted contribution for one option."""


class ScoringStrategy(Protocol):
    """Protocol for composing component scores into a final option score."""

    def combine(self, option: DecisionOption, component_scores: list[ComponentScore]) -> ScoredOption:
        """Combine component scores for an option."""


class WeightedSumScoringStrategy:
    """Simple weighted-sum strategy for the deterministic baseline."""

    def combine(self, option: DecisionOption, component_scores: list[ComponentScore]) -> ScoredOption:
        raw_score = 0.1 + sum(item.weighted_score for item in component_scores)
        supporting_evidence: list[str] = []
        counter_evidence: list[str] = []
        for item in component_scores:
            supporting_evidence.extend(item.supporting_evidence)
            counter_evidence.extend(item.counter_evidence)

        supporting_evidence = list(dict.fromkeys(supporting_evidence))[:6]
        counter_evidence = list(dict.fromkeys(counter_evidence))[:6]
        top_reasons = [item.reason for item in component_scores if item.reason]
        summary = " ".join(top_reasons[:3]) or "This option remained near the baseline because no strong personalized cue dominated."

        return ScoredOption(
            option=option,
            raw_score=round(raw_score, 4),
            component_scores=component_scores,
            supporting_evidence=supporting_evidence,
            counter_evidence=counter_evidence,
            reason_summary=summary,
        )


class ScoringPipeline:
    """Run a set of score components and compose their outputs."""

    def __init__(self, components: list[ScoreComponent], strategy: ScoringStrategy | None = None) -> None:
        self.components = components
        self.strategy = strategy or WeightedSumScoringStrategy()

    def score_option(self, scoring_context: ScoringContext, option: DecisionOption) -> ScoredOption:
        component_scores = [component.score(scoring_context, option) for component in self.components]
        return self.strategy.combine(option=option, component_scores=component_scores)


class ProfileAffinityComponent:
    name = "profile_affinity"
    weight = 1.0

    def score(self, scoring_context: ScoringContext, option: DecisionOption) -> ComponentScore:
        option_tokens = _option_tokens(option)
        category_preferences = scoring_context.long_term_preferences.get("category_preferences", {}).get(
            scoring_context.category,
            {},
        )
        preferred_tokens = {token.lower() for token in category_preferences.get("preferred_keywords", [])}
        avoided_tokens = {token.lower() for token in category_preferences.get("avoided_keywords", [])}
        preferred_overlap = overlap_count(option_tokens, preferred_tokens)
        avoided_overlap = overlap_count(option_tokens, avoided_tokens)
        category_consistency_bonus = 0.25 if preferred_tokens and not avoided_overlap else 0.0
        confidence_factor = _stable_profile_confidence(scoring_context.profile_signals)

        raw_score = (preferred_overlap * 1.1) - (avoided_overlap * 0.95) + category_consistency_bonus
        weighted_score = raw_score * self.weight * confidence_factor
        supporting = []
        counter = []
        if preferred_overlap:
            supporting.append(f"Stable profile matches {scoring_context.category} preference keywords.")
        if category_consistency_bonus:
            supporting.append("Stable category preferences are available for this decision type.")
        if avoided_overlap:
            counter.append("The option overlaps with keywords the stable profile tends to avoid.")
        if confidence_factor < 0.85:
            counter.append("Some stable profile signals are still pending review, so profile influence is dampened.")

        reason = "Stable profile affinity influenced this option." if raw_score else "Stable profile provided only a weak signal."
        return _component_result(
            name=self.name,
            raw_score=raw_score,
            weight=self.weight * confidence_factor,
            reason=reason,
            supporting=supporting,
            counter=counter,
        )


class MemorySupportComponent:
    name = "memory_support"
    weight = 1.0

    def score(self, scoring_context: ScoringContext, option: DecisionOption) -> ComponentScore:
        option_tokens = _option_tokens(option)
        direct_support = 0.0
        contextual_support = 0.0
        contradictory_pressure = 0.0
        supporting = []
        counter = []

        for memory in scoring_context.retrieved_memories:
            memory_tokens = set(
                tokenize(memory.summary)
                + tokenize(memory.chosen_option_text)
                + tokenize(flatten_to_text(memory.context))
                + [tag.lower() for tag in memory.tags]
            )
            overlap = overlap_count(option_tokens, memory_tokens)
            is_exact_match = memory.chosen_option_text.lower() == option.option_text.lower()
            if is_exact_match:
                direct_support += 1.35 + memory.retrieval_score * 0.2
                supporting.append(f"Past memory directly repeats this option: '{memory.chosen_option_text}'.")
            elif overlap:
                contextual_support += overlap * 0.28 + memory.retrieval_score * 0.08
                supporting.append(f"Retrieved memory '{memory.chosen_option_text}' supports similar wording or context.")
            elif memory.memory_role == "direct_match":
                contradictory_pressure += 0.4 + memory.retrieval_score * 0.05
                counter.append(f"A stronger retrieved memory points to another exact past choice: '{memory.chosen_option_text}'.")

        raw_score = direct_support + contextual_support - contradictory_pressure
        reason = "Retrieved memories materially affected this option." if raw_score else "Retrieved memories did not strongly favor this option."
        return _component_result(
            name=self.name,
            raw_score=raw_score,
            weight=self.weight,
            reason=reason,
            supporting=supporting[:4],
            counter=counter[:3],
        )


class ContextCompatibilityComponent:
    name = "context_compatibility"
    weight = 1.0

    def score(self, scoring_context: ScoringContext, option: DecisionOption) -> ComponentScore:
        option_tokens = _option_tokens(option)
        context_tokens = set(tokenize(flatten_to_text(scoring_context.context)))
        context_preferences = scoring_context.long_term_preferences.get("context_preferences", {})

        raw_score = overlap_count(option_tokens, context_tokens) * 0.2
        supporting = []
        counter = []

        derived_context_keys = []
        if scoring_context.context.get("energy"):
            derived_context_keys.append(f"energy_{str(scoring_context.context['energy']).lower()}")
        if scoring_context.context.get("with") and str(scoring_context.context["with"]).lower() == "friends":
            derived_context_keys.append("with_friends")
        if scoring_context.context.get("budget") and str(scoring_context.context["budget"]).lower() in {"low", "tight", "medium"}:
            derived_context_keys.append("budget_sensitive")

        for key in derived_context_keys:
            preferred_context_tokens = {token.lower() for token in context_preferences.get(key, [])}
            overlap = overlap_count(option_tokens, preferred_context_tokens)
            if overlap:
                raw_score += overlap * 0.8
                supporting.append(f"The option matches the user's '{key}' context preference.")

        contradiction_penalty = 0.0
        if str(scoring_context.context.get("energy", "")).lower() == "low":
            contradiction_penalty += overlap_count(option_tokens, LOW_ENERGY_PENALTIES) * 0.65
        if str(scoring_context.context.get("weather", "")).lower() == "rainy":
            contradiction_penalty += overlap_count(option_tokens, RAINY_WEATHER_PENALTIES) * 0.5
        if str(scoring_context.context.get("budget", "")).lower() in {"low", "tight"}:
            contradiction_penalty += overlap_count(option_tokens, LOW_BUDGET_PENALTIES) * 0.55

        if contradiction_penalty:
            raw_score -= contradiction_penalty
            counter.append("The option conflicts with part of the current situational context.")

        reason = "Current context pushed this option up or down." if raw_score else "Current context provided only a weak signal."
        return _component_result(
            name=self.name,
            raw_score=raw_score,
            weight=self.weight,
            reason=reason,
            supporting=supporting[:3],
            counter=counter[:3],
        )


class RecentStateInfluenceComponent:
    name = "recent_state_influence"
    weight = 1.0

    def score(self, scoring_context: ScoringContext, option: DecisionOption) -> ComponentScore:
        option_tokens = _option_tokens(option)
        raw_score = 0.0
        supporting = []
        counter = []

        for note in scoring_context.recent_state_notes:
            lowered_note = note.lower()
            note_tokens = set(tokenize(note))
            overlap = overlap_count(option_tokens, note_tokens)
            exact_option_mention = option.option_text.lower() in lowered_note
            if not overlap and not exact_option_mention:
                continue
            multiplier = 1.3 if note_tokens & TEMPORARY_OVERRIDE_TERMS else 1.0
            if note_tokens & NEGATION_TERMS:
                raw_score -= (overlap * 0.7 + (2.25 if exact_option_mention else 0.0)) * multiplier
                counter.append(f"Recent state note pushes away from this option: '{note}'.")
            else:
                raw_score += (overlap * 0.85 + (4.5 if exact_option_mention else 0.0)) * multiplier
                supporting.append(f"Recent state note supports this option: '{note}'.")

        reason = "Recent temporary state had a direct effect on this option." if raw_score else "Recent manual or feedback-derived state did not strongly target this option."
        return _component_result(
            name=self.name,
            raw_score=raw_score,
            weight=self.weight,
            reason=reason,
            supporting=supporting[:3],
            counter=counter[:3],
        )


class RecentTrendInfluenceComponent:
    name = "recent_trend_influence"
    weight = 1.0

    def score(self, scoring_context: ScoringContext, option: DecisionOption) -> ComponentScore:
        if scoring_context.snapshot is None:
            return _component_result(
                name=self.name,
                raw_score=0.0,
                weight=self.weight,
                reason="No short-term snapshot was available.",
                supporting=[],
                counter=[],
            )

        option_tokens = _option_tokens(option)
        derived = scoring_context.snapshot.derived_statistics
        recent_option_counts = derived.get("recent_option_counts", {}).get(scoring_context.category, {})
        recent_tags = {tag.lower() for tag in derived.get("recent_tags", [])}
        recent_shift_notes = derived.get("recent_shift_notes", [])

        raw_score = recent_option_counts.get(option.option_text, 0) * 0.55
        supporting = []
        counter = []

        tag_overlap = overlap_count(option_tokens, recent_tags)
        if tag_overlap:
            raw_score += tag_overlap * 0.25
            supporting.append("The option overlaps with short-term preference tags from recent behavior.")

        for note in recent_shift_notes[:3]:
            note_tokens = set(tokenize(note))
            overlap = overlap_count(option_tokens, note_tokens)
            if overlap:
                raw_score += overlap * 0.25
                supporting.append(f"Recent feedback suggests a temporary shift toward this option: '{note}'.")

        if recent_option_counts.get(option.option_text, 0):
            supporting.append("The same option has appeared in very recent choices.")

        reason = "Recent trend history changed this option's score." if raw_score else "Short-term trend history did not strongly favor this option."
        return _component_result(
            name=self.name,
            raw_score=raw_score,
            weight=self.weight,
            reason=reason,
            supporting=supporting[:3],
            counter=counter[:2],
        )


def default_scoring_pipeline() -> ScoringPipeline:
    """Return the default deterministic scoring pipeline."""

    return ScoringPipeline(
        components=[
            ProfileAffinityComponent(),
            MemorySupportComponent(),
            ContextCompatibilityComponent(),
            RecentStateInfluenceComponent(),
            RecentTrendInfluenceComponent(),
        ]
    )


def _option_tokens(option: DecisionOption) -> set[str]:
    return set(tokenize(option.option_text) + tokenize(flatten_to_text(option.option_metadata_json)))


def _stable_profile_confidence(profile_signals: list[ProfileSignalRead]) -> float:
    if not profile_signals:
        return 1.0
    accepted = sum(1 for signal in profile_signals if signal.status == "accepted")
    edited = sum(1 for signal in profile_signals if signal.status == "edited")
    pending = sum(1 for signal in profile_signals if signal.status == "pending")
    reviewed = accepted + edited
    total = reviewed + pending
    if total == 0:
        return 1.0
    return max(0.55, min(1.0, (accepted + edited * 0.9 + pending * 0.55) / total))


def _component_result(
    name: str,
    raw_score: float,
    weight: float,
    reason: str,
    supporting: list[str],
    counter: list[str],
) -> ComponentScore:
    return ComponentScore(
        name=name,
        raw_score=round(raw_score, 4),
        weight=round(weight, 4),
        weighted_score=round(raw_score * weight, 4),
        reason=reason,
        supporting_evidence=list(dict.fromkeys(supporting)),
        counter_evidence=list(dict.fromkeys(counter)),
    )
