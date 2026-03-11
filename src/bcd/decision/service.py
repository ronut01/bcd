"""Decision prediction services."""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlmodel import Session

from bcd.config import Settings, get_settings
from bcd.decision.schemas import DecisionPredictionInput, PredictionResponse, RankedOption
from bcd.memory.retriever import MemoryRetriever, RetrievalQuery
from bcd.profile.schemas import PreferenceSnapshotRead
from bcd.storage.models import DecisionOption, DecisionRequest, PredictionResult
from bcd.storage.repository import BCDRepository
from bcd.utils.text import flatten_to_text, overlap_count, tokenize


@dataclass(slots=True)
class _OptionScore:
    option: DecisionOption
    raw_score: float
    confidence: float
    breakdown: dict[str, float]
    reasons: list[str]


class DecisionService:
    """Stores decision requests and produces a deterministic prediction."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repository = BCDRepository(session)
        self.retriever = MemoryRetriever(session)

    def predict(self, payload: DecisionPredictionInput) -> PredictionResponse:
        user = self.repository.get_user_profile(payload.user_id)
        if user is None:
            raise ValueError(f"User profile '{payload.user_id}' was not found.")

        request = self.repository.add(
            DecisionRequest(
                user_id=payload.user_id,
                prompt=payload.prompt,
                category=payload.category,
                context_json=payload.context,
            )
        )
        options = self.repository.add_all(
            [
                DecisionOption(
                    request_id=request.request_id,
                    option_text=option.option_text,
                    option_metadata_json=option.option_metadata,
                    position=index,
                )
                for index, option in enumerate(payload.options)
            ]
        )
        retrieved_memories = self.retriever.retrieve(
            RetrievalQuery(
                user_id=payload.user_id,
                category=payload.category,
                prompt=payload.prompt,
                options=[option.option_text for option in options],
                context=payload.context,
                limit=self.settings.retrieval_top_k,
            )
        )
        snapshot_row = self.repository.get_latest_snapshot(payload.user_id)
        snapshot = (
            PreferenceSnapshotRead(
                snapshot_id=snapshot_row.snapshot_id,
                user_id=snapshot_row.user_id,
                summary=snapshot_row.summary,
                short_term_preference_notes=snapshot_row.short_term_preference_notes_json,
                drift_markers=snapshot_row.drift_markers_json,
                derived_statistics=snapshot_row.derived_statistics_json,
                created_at=snapshot_row.created_at,
            )
            if snapshot_row
            else None
        )

        scored = [self._score_option(user.long_term_preferences_json, snapshot, option, payload.context, payload.category, retrieved_memories) for option in options]
        confidences = self._softmax([item.raw_score for item in scored])
        ranked: list[_OptionScore] = []
        for item, confidence in zip(scored, confidences, strict=True):
            ranked.append(
                _OptionScore(
                    option=item.option,
                    raw_score=item.raw_score,
                    confidence=confidence,
                    breakdown=item.breakdown,
                    reasons=item.reasons,
                )
            )
        ranked.sort(key=lambda item: item.confidence, reverse=True)
        top = ranked[0]
        explanation = self._build_explanation(top.option.option_text, top.reasons, retrieved_memories)

        prediction = self.repository.add(
            PredictionResult(
                request_id=request.request_id,
                predicted_option_id=top.option.option_id,
                ranked_option_ids_json=[item.option.option_id for item in ranked],
                score_breakdown_json={item.option.option_id: item.breakdown for item in ranked},
                confidence_by_option_json={item.option.option_id: item.confidence for item in ranked},
                explanation=explanation,
                strategy="heuristic-retrieval-hybrid",
                retrieved_memory_ids_json=[memory.memory_id for memory in retrieved_memories],
            )
        )

        return PredictionResponse(
            request_id=request.request_id,
            prediction_id=prediction.prediction_id,
            predicted_option_id=top.option.option_id,
            predicted_option_text=top.option.option_text,
            confidence=round(top.confidence, 4),
            explanation=prediction.explanation,
            strategy=prediction.strategy,
            ranked_options=[
                RankedOption(
                    option_id=item.option.option_id,
                    option_text=item.option.option_text,
                    raw_score=round(item.raw_score, 4),
                    confidence=round(item.confidence, 4),
                    reasons=item.reasons[:3],
                )
                for item in ranked
            ],
            retrieved_memories=retrieved_memories,
            created_at=prediction.created_at,
        )

    def _score_option(
        self,
        long_term_preferences: dict,
        snapshot: PreferenceSnapshotRead | None,
        option: DecisionOption,
        context: dict,
        category: str,
        retrieved_memories,
    ) -> _OptionScore:
        option_tokens = set(tokenize(option.option_text) + tokenize(flatten_to_text(option.option_metadata_json)))
        reasons: list[str] = []

        category_preferences = long_term_preferences.get("category_preferences", {}).get(category, {})
        preferred_tokens = {token.lower() for token in category_preferences.get("preferred_keywords", [])}
        avoided_tokens = {token.lower() for token in category_preferences.get("avoided_keywords", [])}

        preferred_overlap = overlap_count(option_tokens, preferred_tokens)
        avoided_overlap = overlap_count(option_tokens, avoided_tokens)
        profile_affinity = preferred_overlap * 1.1 - avoided_overlap * 0.9
        if preferred_overlap:
            reasons.append(f"It matches {category} preference keywords from the user profile.")
        if avoided_overlap:
            reasons.append("It includes keywords the user often avoids, lowering the score.")

        context_tokens = set(tokenize(flatten_to_text(context)))
        context_compatibility = 0.0
        context_preferences = long_term_preferences.get("context_preferences", {})
        derived_context_keys = []
        if context.get("energy"):
            derived_context_keys.append(f"energy_{str(context['energy']).lower()}")
        if context.get("with") and str(context["with"]).lower() == "friends":
            derived_context_keys.append("with_friends")
        if context.get("budget") and str(context["budget"]).lower() in {"low", "tight", "medium"}:
            derived_context_keys.append("budget_sensitive")

        for key in derived_context_keys:
            preferred_context_tokens = {token.lower() for token in context_preferences.get(key, [])}
            overlap = overlap_count(option_tokens, preferred_context_tokens)
            context_compatibility += overlap * 0.75
            if overlap:
                reasons.append(f"It aligns with the user's '{key}' context preference.")

        memory_support = 0.0
        for memory in retrieved_memories:
            memory_tokens = set(tokenize(memory.summary) + tokenize(memory.chosen_option_text) + [tag.lower() for tag in memory.tags])
            overlap = overlap_count(option_tokens, memory_tokens)
            if memory.chosen_option_text.lower() == option.option_text.lower():
                overlap += 2
            memory_support += overlap * 0.35 + memory.retrieval_score * 0.15
        if memory_support:
            reasons.append("Similar past choices support this option.")

        recent_trend_bonus = 0.0
        if snapshot:
            option_counts = snapshot.derived_statistics.get("recent_option_counts", {}).get(category, {})
            recent_count = option_counts.get(option.option_text, 0)
            recent_trend_bonus = recent_count * 0.5
            if recent_count:
                reasons.append("Recent choice patterns in this category point toward this option.")

            recent_tags = {tag.lower() for tag in snapshot.derived_statistics.get("recent_tags", [])}
            tag_overlap = overlap_count(option_tokens, recent_tags)
            recent_trend_bonus += tag_overlap * 0.25
            if tag_overlap:
                reasons.append("Its wording overlaps with recent short-term preference signals.")

        if context_tokens:
            direct_context_overlap = overlap_count(option_tokens, context_tokens)
            context_compatibility += direct_context_overlap * 0.2

        raw_score = 0.1 + profile_affinity + context_compatibility + memory_support + recent_trend_bonus
        breakdown = {
            "profile_affinity": round(profile_affinity, 4),
            "memory_support": round(memory_support, 4),
            "context_compatibility": round(context_compatibility, 4),
            "recent_trend_bonus": round(recent_trend_bonus, 4),
            "total": round(raw_score, 4),
        }
        if not reasons:
            reasons.append("No strong positive cue was found, so this stayed near the baseline.")

        return _OptionScore(option=option, raw_score=raw_score, confidence=0.0, breakdown=breakdown, reasons=reasons)

    @staticmethod
    def _softmax(scores: list[float]) -> list[float]:
        max_score = max(scores)
        scaled = [math.exp(score - max_score) for score in scores]
        total = sum(scaled)
        return [value / total for value in scaled]

    @staticmethod
    def _build_explanation(predicted_option_text: str, reasons: list[str], retrieved_memories) -> str:
        explanation_parts = [f"The system predicts '{predicted_option_text}'."]
        if reasons:
            explanation_parts.append(" ".join(reasons[:2]))
        if retrieved_memories:
            explanation_parts.append(
                f"It also found {len(retrieved_memories)} relevant memories, led by '{retrieved_memories[0].chosen_option_text}'."
            )
        return " ".join(explanation_parts)
