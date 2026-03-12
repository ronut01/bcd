"""Decision prediction services."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from sqlmodel import Session

from bcd.config import Settings, get_settings
from bcd.decision.schemas import (
    DecisionPredictionInput,
    ExplanationSections,
    LLMRuntimeConfig,
    PredictionResponse,
    RankedOption,
    RankedOptionComponentScore,
)
from bcd.decision.scoring import ComponentScore, ScoredOption, ScoringContext, default_scoring_pipeline
from bcd.llm.base import LLMRankingRequest, LLMRankingResult, LLMRanker, NullLLMRanker
from bcd.llm.openai_compatible import OpenAICompatibleLLMRanker
from bcd.memory.retriever import MemoryRetriever, RetrievalQuery
from bcd.profile.service import ProfileService
from bcd.profile.schemas import PreferenceSnapshotRead, ProfileSignalRead
from bcd.storage.models import DecisionOption, DecisionRequest, PredictionResult
from bcd.storage.repository import BCDRepository


@dataclass(slots=True)
class _ResolvedOptionScore:
    scored_option: ScoredOption
    confidence: float


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
        self.retriever = MemoryRetriever(session, self.settings)
        self.profile_service = ProfileService(session, self.settings)
        self.scoring_pipeline = default_scoring_pipeline()
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
        snapshot = self._load_snapshot(payload.user_id)
        profile_card_path = self.profile_service.ensure_profile_card(payload.user_id)
        profile_card_payload = self.profile_service.get_profile_card(payload.user_id)
        profile_signals = self.profile_service.get_profile_signals(payload.user_id)
        recent_state_payload = self.profile_service.get_recent_state_payload(payload.user_id)

        scoring_context = ScoringContext(
            category=payload.category,
            prompt=payload.prompt,
            context=payload.context,
            long_term_preferences=user.long_term_preferences_json,
            profile_signals=profile_signals,
            snapshot=snapshot,
            recent_state_notes=recent_state_payload["combined_notes"],
            retrieved_memories=retrieved_memories,
        )
        heuristic_scored = [
            self.scoring_pipeline.score_option(scoring_context=scoring_context, option=option)
            for option in options
        ]
        heuristic_ranked = self._normalize_and_sort(heuristic_scored)

        llm_result, llm_error = self._maybe_rank_with_llm(
            prediction_mode=prediction_mode,
            payload_llm_config=payload.llm_config,
            prompt=payload.prompt,
            category=payload.category,
            context=payload.context,
            options=options,
            retrieved_memories=retrieved_memories,
            profile_card_payload=profile_card_payload,
            heuristic_ranked=heuristic_ranked,
            profile_signals=profile_signals,
            recent_state_payload=recent_state_payload,
        )
        ranked, strategy, llm_used, llm_provider = self._resolve_final_ranking(
            prediction_mode=prediction_mode,
            heuristic_ranked=heuristic_ranked,
            llm_result=llm_result,
            llm_error=llm_error,
        )
        explanation_sections = self._build_explanation_sections(
            ranked=ranked,
            retrieved_memories=retrieved_memories,
            recent_state_payload=recent_state_payload,
            llm_note=llm_result.explanation if llm_result else llm_error,
        )
        top = ranked[0]
        explanation = explanation_sections.top_choice_summary

        prediction = self.repository.add(
            PredictionResult(
                request_id=request.request_id,
                predicted_option_id=top.scored_option.option.option_id,
                ranked_option_ids_json=[item.scored_option.option.option_id for item in ranked],
                score_breakdown_json={
                    item.scored_option.option.option_id: {
                        component.name: component.weighted_score for component in item.scored_option.component_scores
                    }
                    | {"total": item.scored_option.raw_score}
                    for item in ranked
                },
                confidence_by_option_json={item.scored_option.option.option_id: item.confidence for item in ranked},
                explanation=explanation,
                strategy=strategy,
                retrieved_memory_ids_json=[memory.memory_id for memory in retrieved_memories],
            )
        )

        return PredictionResponse(
            request_id=request.request_id,
            prediction_id=prediction.prediction_id,
            predicted_option_id=top.scored_option.option.option_id,
            predicted_option_text=top.scored_option.option.option_text,
            confidence=round(top.confidence, 4),
            explanation=prediction.explanation,
            strategy=prediction.strategy,
            llm_used=llm_used,
            llm_provider=llm_provider,
            llm_error=llm_error,
            profile_card_path=profile_card_path,
            ranked_options=[
                RankedOption(
                    option_id=item.scored_option.option.option_id,
                    option_text=item.scored_option.option.option_text,
                    raw_score=round(item.scored_option.raw_score, 4),
                    confidence=round(item.confidence, 4),
                    reasons=[component.reason for component in item.scored_option.component_scores if component.reason][:5],
                    component_scores=[
                        RankedOptionComponentScore(
                            name=component.name,
                            raw_score=component.raw_score,
                            weight=component.weight,
                            weighted_score=component.weighted_score,
                            reason=component.reason,
                        )
                        for component in item.scored_option.component_scores
                    ],
                    supporting_evidence=item.scored_option.supporting_evidence,
                    counter_evidence=item.scored_option.counter_evidence,
                    reason_summary=item.scored_option.reason_summary,
                )
                for item in ranked
            ],
            retrieved_memories=retrieved_memories,
            explanation_sections=explanation_sections,
            created_at=prediction.created_at,
        )

    def _load_snapshot(self, user_id: str) -> PreferenceSnapshotRead | None:
        snapshot_row = self.repository.get_latest_snapshot(user_id)
        if snapshot_row is None:
            return None
        return PreferenceSnapshotRead(
            snapshot_id=snapshot_row.snapshot_id,
            user_id=snapshot_row.user_id,
            summary=snapshot_row.summary,
            short_term_preference_notes=snapshot_row.short_term_preference_notes_json,
            drift_markers=snapshot_row.drift_markers_json,
            derived_statistics=snapshot_row.derived_statistics_json,
            created_at=snapshot_row.created_at,
        )

    @staticmethod
    def _normalize_and_sort(scored: list[ScoredOption]) -> list[_ResolvedOptionScore]:
        confidences = DecisionService._softmax([item.raw_score for item in scored])
        ranked = [
            _ResolvedOptionScore(scored_option=item, confidence=confidence)
            for item, confidence in zip(scored, confidences, strict=True)
        ]
        ranked.sort(key=lambda item: item.confidence, reverse=True)
        return ranked

    def _maybe_rank_with_llm(
        self,
        prediction_mode: Literal["baseline", "llm", "hybrid"],
        payload_llm_config: LLMRuntimeConfig | None,
        prompt: str,
        category: str,
        context: dict,
        options: list[DecisionOption],
        retrieved_memories,
        profile_card_payload: dict,
        heuristic_ranked: list[_ResolvedOptionScore],
        profile_signals: list[ProfileSignalRead],
        recent_state_payload: dict,
    ) -> tuple[LLMRankingResult | None, str | None]:
        if prediction_mode == "baseline":
            return None, None

        ranker = self._resolve_llm_ranker(payload_llm_config=payload_llm_config)
        request = LLMRankingRequest(
            prompt=prompt,
            category=category,
            context=context,
            options=[option.option_text for option in options],
            memory_summaries=[memory.summary for memory in retrieved_memories],
            profile_card_markdown=profile_card_payload["content"],
            stable_profile_markdown=profile_card_payload.get("stable_content"),
            recent_state_markdown=profile_card_payload.get("recent_content"),
            heuristic_ranking=[item.scored_option.option.option_text for item in heuristic_ranked],
            reviewed_profile_signals=[
                {
                    "signal_kind": signal.signal_kind,
                    "signal_name": signal.signal_name,
                    "status": signal.status,
                    "current_value": signal.current_value,
                }
                for signal in profile_signals
                if signal.status != "rejected"
            ][:20],
            memory_evidence=[
                {
                    "category": memory.category,
                    "chosen_option_text": memory.chosen_option_text,
                    "summary": memory.summary,
                    "retrieval_score": memory.retrieval_score,
                    "matched_terms": memory.matched_terms,
                    "tags": memory.tags,
                    "memory_role": memory.memory_role,
                }
                for memory in retrieved_memories
            ],
        )
        try:
            result = ranker.rank(request)
            if result is None:
                return None, "LLM ranker is not configured."
            if recent_state_payload["combined_notes"] and result.explanation:
                result.explanation = (
                    f"{result.explanation} Recent-state notes considered: "
                    f"{'; '.join(recent_state_payload['combined_notes'][:2])}."
                )
            return result, None
        except Exception as exc:
            return None, str(exc)

    def _resolve_llm_ranker(self, payload_llm_config: LLMRuntimeConfig | None) -> LLMRanker:
        if payload_llm_config is not None:
            return OpenAICompatibleLLMRanker.from_runtime_config(payload_llm_config)
        return self.llm_ranker

    def _resolve_final_ranking(
        self,
        prediction_mode: Literal["baseline", "llm", "hybrid"],
        heuristic_ranked: list[_ResolvedOptionScore],
        llm_result: LLMRankingResult | None,
        llm_error: str | None,
    ) -> tuple[list[_ResolvedOptionScore], str, bool, str | None]:
        if prediction_mode == "baseline" or llm_result is None:
            strategy = (
                "heuristic-retrieval-hybrid"
                if prediction_mode == "baseline" or not llm_error
                else f"{prediction_mode}-fallback-to-baseline"
            )
            return heuristic_ranked, strategy, False, None

        if prediction_mode == "llm":
            return self._llm_rank_only(heuristic_ranked, llm_result), "llm-ranking", True, llm_result.provider

        return self._blend_hybrid_ranking(heuristic_ranked, llm_result), "hybrid-heuristic-llm", True, llm_result.provider

    @staticmethod
    def _llm_rank_only(
        heuristic_ranked: list[_ResolvedOptionScore],
        llm_result: LLMRankingResult,
    ) -> list[_ResolvedOptionScore]:
        option_map = {item.scored_option.option.option_text: item.scored_option for item in heuristic_ranked}
        ordered_items = [option_map[text] for text in llm_result.ranked_options if text in option_map]
        ordered_items.extend(item.scored_option for item in heuristic_ranked if item.scored_option not in ordered_items)
        llm_scores = [len(ordered_items) - index for index in range(len(ordered_items))]
        confidences = DecisionService._softmax(llm_scores)
        result: list[_ResolvedOptionScore] = []
        for item, confidence, llm_score in zip(ordered_items, confidences, llm_scores, strict=True):
            augmented = DecisionService._augment_with_llm_component(
                item,
                llm_score=float(llm_score),
                explanation="The LLM ranked this option highly after reading memories, recent state, and the stable profile.",
            )
            result.append(_ResolvedOptionScore(scored_option=augmented, confidence=confidence))
        return result

    @staticmethod
    def _blend_hybrid_ranking(
        heuristic_ranked: list[_ResolvedOptionScore],
        llm_result: LLMRankingResult,
    ) -> list[_ResolvedOptionScore]:
        llm_position_map = {
            text: len(llm_result.ranked_options) - index
            for index, text in enumerate(llm_result.ranked_options)
        }
        blended_scored: list[ScoredOption] = []
        for item in heuristic_ranked:
            llm_bonus = llm_position_map.get(item.scored_option.option.option_text, 0) * 0.8
            blended_scored.append(
                DecisionService._augment_with_llm_component(
                    item.scored_option,
                    llm_score=llm_bonus,
                    explanation="The LLM also favored this option after reading the retrieved memories and recent state.",
                )
            )
        return DecisionService._normalize_and_sort(blended_scored)

    @staticmethod
    def _augment_with_llm_component(
        scored_option: ScoredOption,
        llm_score: float,
        explanation: str,
    ) -> ScoredOption:
        llm_component = ComponentScore(
            name="llm_rank_bonus",
            raw_score=round(llm_score, 4),
            weight=1.0,
            weighted_score=round(llm_score, 4),
            reason=explanation,
            supporting_evidence=[explanation] if llm_score > 0 else [],
            counter_evidence=[],
        )
        return ScoredOption(
            option=scored_option.option,
            raw_score=round(scored_option.raw_score + llm_score, 4),
            component_scores=list(scored_option.component_scores) + [llm_component],
            supporting_evidence=list(dict.fromkeys(scored_option.supporting_evidence + llm_component.supporting_evidence)),
            counter_evidence=scored_option.counter_evidence,
            reason_summary=scored_option.reason_summary,
        )

    @staticmethod
    def _softmax(scores: list[float]) -> list[float]:
        max_score = max(scores)
        scaled = [math.exp(score - max_score) for score in scores]
        total = sum(scaled)
        return [value / total for value in scaled]

    def _build_explanation_sections(
        self,
        ranked: list[_ResolvedOptionScore],
        retrieved_memories,
        recent_state_payload: dict,
        llm_note: str | None,
    ) -> ExplanationSections:
        top = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else None
        memory_evidence = [
            f"{memory.chosen_option_text}: {memory.why_retrieved[0] if memory.why_retrieved else memory.summary}"
            for memory in retrieved_memories[:3]
        ]
        recent_notes = recent_state_payload.get("combined_notes", [])[:3]
        losing_reasons: list[str] = []
        if runner_up:
            if runner_up.scored_option.counter_evidence:
                losing_reasons.extend(runner_up.scored_option.counter_evidence[:2])
            else:
                losing_reasons.append(
                    f"'{runner_up.scored_option.option.option_text}' received less combined support from profile, memory, and recent state."
                )
        if llm_note:
            losing_reasons.append(f"LLM note: {llm_note}")

        return ExplanationSections(
            top_choice_summary=(
                f"The system predicts '{top.scored_option.option.option_text}' because it has the strongest combined support "
                f"from stable preferences, retrieved memories, current context, and recent state."
            ),
            why_this_option=top.scored_option.supporting_evidence[:4] or [top.scored_option.reason_summary],
            what_memories_mattered=memory_evidence or ["No strong retrieved memory dominated this prediction."],
            what_recent_state_mattered=recent_notes or ["No recent-state note or short-term drift marker strongly changed the result."],
            why_other_options_lost=losing_reasons[:4],
        )
