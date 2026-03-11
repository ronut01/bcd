"""Decision prediction services."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from sqlmodel import Session

from bcd.config import Settings, get_settings
from bcd.decision.schemas import DecisionPredictionInput, PredictionResponse, RankedOption
from bcd.llm.base import LLMRankingRequest, LLMRankingResult, LLMRanker, NullLLMRanker
from bcd.llm.openai_compatible import OpenAICompatibleLLMRanker
from bcd.memory.retriever import MemoryRetriever, RetrievalQuery
from bcd.profile.service import ProfileService
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

    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        llm_ranker: LLMRanker | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repository = BCDRepository(session)
        self.retriever = MemoryRetriever(session)
        self.profile_service = ProfileService(session, self.settings)
        self.llm_ranker = llm_ranker or OpenAICompatibleLLMRanker.from_settings(self.settings) or NullLLMRanker()

    def predict(self, payload: DecisionPredictionInput) -> PredictionResponse:
        user = self.repository.get_user_profile(payload.user_id)
        if user is None:
            raise ValueError(f"User profile '{payload.user_id}' was not found.")
        prediction_mode: Literal["baseline", "llm", "hybrid"] = payload.prediction_mode or self.settings.prediction_mode

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
        profile_card_path = self.profile_service.ensure_profile_card(payload.user_id)
        profile_card_markdown = self.profile_service.get_profile_card(payload.user_id)["content"]

        heuristic_scored = [
            self._score_option(
                user.long_term_preferences_json,
                snapshot,
                option,
                payload.context,
                payload.category,
                retrieved_memories,
            )
            for option in options
        ]
        heuristic_ranked = self._normalize_and_sort(heuristic_scored)
        llm_result, llm_error = self._maybe_rank_with_llm(
            prediction_mode=prediction_mode,
            prompt=payload.prompt,
            category=payload.category,
            context=payload.context,
            options=options,
            retrieved_memories=retrieved_memories,
            profile_card_markdown=profile_card_markdown,
            heuristic_ranked=heuristic_ranked,
        )
        ranked, strategy, explanation, llm_used = self._resolve_final_ranking(
            prediction_mode=prediction_mode,
            heuristic_ranked=heuristic_ranked,
            llm_result=llm_result,
            llm_error=llm_error,
            retrieved_memories=retrieved_memories,
        )
        top = ranked[0]

        prediction = self.repository.add(
            PredictionResult(
                request_id=request.request_id,
                predicted_option_id=top.option.option_id,
                ranked_option_ids_json=[item.option.option_id for item in ranked],
                score_breakdown_json={item.option.option_id: item.breakdown for item in ranked},
                confidence_by_option_json={item.option.option_id: item.confidence for item in ranked},
                explanation=explanation,
                strategy=strategy,
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
            llm_used=llm_used,
            profile_card_path=profile_card_path,
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

    @staticmethod
    def _normalize_and_sort(scored: list[_OptionScore]) -> list[_OptionScore]:
        confidences = DecisionService._softmax([item.raw_score for item in scored])
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
        return ranked

    def _maybe_rank_with_llm(
        self,
        prediction_mode: Literal["baseline", "llm", "hybrid"],
        prompt: str,
        category: str,
        context: dict,
        options: list[DecisionOption],
        retrieved_memories,
        profile_card_markdown: str,
        heuristic_ranked: list[_OptionScore],
    ) -> tuple[LLMRankingResult | None, str | None]:
        if prediction_mode == "baseline":
            return None, None

        request = LLMRankingRequest(
            prompt=prompt,
            category=category,
            context=context,
            options=[option.option_text for option in options],
            memory_summaries=[memory.summary for memory in retrieved_memories],
            profile_card_markdown=profile_card_markdown,
            heuristic_ranking=[item.option.option_text for item in heuristic_ranked],
        )
        try:
            result = self.llm_ranker.rank(request)
            if result is None:
                return None, "LLM ranker is not configured."
            return result, None
        except Exception as exc:
            return None, str(exc)

    def _resolve_final_ranking(
        self,
        prediction_mode: Literal["baseline", "llm", "hybrid"],
        heuristic_ranked: list[_OptionScore],
        llm_result: LLMRankingResult | None,
        llm_error: str | None,
        retrieved_memories,
    ) -> tuple[list[_OptionScore], str, str, bool]:
        if prediction_mode == "baseline" or llm_result is None:
            explanation = self._build_explanation(
                heuristic_ranked[0].option.option_text,
                heuristic_ranked[0].reasons,
                retrieved_memories,
                llm_note=(
                    f"LLM fallback: {llm_error}"
                    if prediction_mode in {"llm", "hybrid"} and llm_error
                    else None
                ),
            )
            strategy = (
                "heuristic-retrieval-hybrid"
                if prediction_mode == "baseline" or not llm_error
                else f"{prediction_mode}-fallback-to-baseline"
            )
            return heuristic_ranked, strategy, explanation, False

        if prediction_mode == "llm":
            llm_ranked = self._llm_rank_only(heuristic_ranked, llm_result)
            explanation = self._build_explanation(
                llm_ranked[0].option.option_text,
                llm_ranked[0].reasons,
                retrieved_memories,
                llm_note=llm_result.explanation,
            )
            return llm_ranked, "llm-ranking", explanation, True

        hybrid_ranked = self._blend_hybrid_ranking(heuristic_ranked, llm_result)
        explanation = self._build_explanation(
            hybrid_ranked[0].option.option_text,
            hybrid_ranked[0].reasons,
            retrieved_memories,
            llm_note=llm_result.explanation,
        )
        return hybrid_ranked, "hybrid-heuristic-llm", explanation, True

    @staticmethod
    def _llm_rank_only(heuristic_ranked: list[_OptionScore], llm_result: LLMRankingResult) -> list[_OptionScore]:
        option_map = {item.option.option_text: item for item in heuristic_ranked}
        ordered_items = [
            option_map[text]
            for text in llm_result.ranked_options
            if text in option_map
        ]
        ordered_items.extend(item for item in heuristic_ranked if item not in ordered_items)
        llm_scores = [len(ordered_items) - index for index in range(len(ordered_items))]
        confidences = DecisionService._softmax(llm_scores)
        result: list[_OptionScore] = []
        for item, confidence, llm_score in zip(ordered_items, confidences, llm_scores, strict=True):
            breakdown = dict(item.breakdown)
            breakdown["llm_rank_bonus"] = float(llm_score)
            breakdown["total"] = round(float(llm_score), 4)
            reasons = list(dict.fromkeys(item.reasons + ["The LLM ranked this option highly given the user card and memories."]))
            result.append(
                _OptionScore(
                    option=item.option,
                    raw_score=float(llm_score),
                    confidence=confidence,
                    breakdown=breakdown,
                    reasons=reasons,
                )
            )
        return result

    @staticmethod
    def _blend_hybrid_ranking(heuristic_ranked: list[_OptionScore], llm_result: LLMRankingResult) -> list[_OptionScore]:
        llm_position_map = {
            text: len(llm_result.ranked_options) - index
            for index, text in enumerate(llm_result.ranked_options)
        }
        blended: list[_OptionScore] = []
        for item in heuristic_ranked:
            llm_bonus = llm_position_map.get(item.option.option_text, 0) * 0.8
            raw_score = item.raw_score + llm_bonus
            breakdown = dict(item.breakdown)
            breakdown["llm_rank_bonus"] = round(llm_bonus, 4)
            breakdown["total"] = round(raw_score, 4)
            reasons = list(item.reasons)
            if llm_bonus:
                reasons.append("The LLM also ranked this option highly after reading the profile card.")
            blended.append(
                _OptionScore(
                    option=item.option,
                    raw_score=raw_score,
                    confidence=0.0,
                    breakdown=breakdown,
                    reasons=list(dict.fromkeys(reasons)),
                )
            )
        return DecisionService._normalize_and_sort(blended)

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
    def _build_explanation(
        predicted_option_text: str,
        reasons: list[str],
        retrieved_memories,
        llm_note: str | None = None,
    ) -> str:
        explanation_parts = [f"The system predicts '{predicted_option_text}'."]
        if reasons:
            explanation_parts.append(" ".join(reasons[:2]))
        if retrieved_memories:
            explanation_parts.append(
                f"It also found {len(retrieved_memories)} relevant memories, led by '{retrieved_memories[0].chosen_option_text}'."
            )
        if llm_note:
            explanation_parts.append(f"LLM note: {llm_note}")
        return " ".join(explanation_parts)
