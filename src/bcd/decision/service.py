"""Decision prediction services."""

from __future__ import annotations

from collections import OrderedDict
import math
from dataclasses import dataclass
from typing import Literal

from sqlmodel import Session

from bcd.config import Settings, get_settings
from bcd.decision.schemas import (
    AgentBrief,
    AgentAgreementSignal,
    AgentAgreementSummary,
    AgentInfluenceBreakdown,
    AgentOptionAssessment,
    AgentWorkflowTrace,
    DecisionAudit,
    DecisionOptionSuggestionInput,
    DecisionPredictionInput,
    ExplanationSections,
    LLMRuntimeConfig,
    OptionSuggestionResponse,
    PredictionResponse,
    RankedOption,
    RankedOptionComponentScore,
    SuggestedOption,
)
from bcd.decision.scoring import ComponentScore, ScoredOption, ScoringContext, default_scoring_pipeline
from bcd.llm.base import LLMRankingRequest, LLMRankingResult, LLMRanker, NullLLMRanker
from bcd.llm.openai_compatible import OpenAICompatibleLLMRanker
from bcd.memory.retriever import MemoryRetriever, RetrievalQuery
from bcd.profile.service import ProfileService
from bcd.profile.schemas import PreferenceSnapshotRead, ProfileSignalRead
from bcd.storage.models import DecisionOption, DecisionRequest, PredictionResult
from bcd.storage.repository import BCDRepository
from bcd.utils.text import flatten_to_text, tokenize


SUGGESTION_LIBRARY: dict[str, list[dict[str, object]]] = {
    "food": [
        {"text": "Warm noodle soup", "tags": ["warm", "noodle", "soup", "cozy", "easy", "familiar", "dinner", "evening", "night", "rainy"]},
        {"text": "Comfort rice bowl", "tags": ["warm", "rice", "comfort", "practical", "familiar", "lunch", "workday"]},
        {"text": "Hot tea and snack set", "tags": ["warm", "tea", "light", "cozy", "easy", "morning", "break", "workday"]},
        {"text": "Quick budget takeout", "tags": ["quick", "cheap", "affordable", "easy", "practical", "lunch", "workday", "office"]},
        {"text": "Cozy shared pasta", "tags": ["cozy", "shared", "comfortable", "evening", "social"]},
        {"text": "Shareable family pizza", "tags": ["shareable", "group", "familiar", "easy", "social"]},
        {"text": "Fresh salad bowl", "tags": ["fresh", "light", "clean", "healthy", "lunch", "sunny", "workday"]},
        {"text": "Heavy comfort burger", "tags": ["heavy", "greasy", "comfort"]},
    ],
    "entertainment": [
        {"text": "A cozy short drama", "tags": ["cozy", "short", "drama", "familiar", "night", "indoor"]},
        {"text": "A light comfort comedy", "tags": ["light", "comfort", "comedy", "easy", "familiar"]},
        {"text": "A familiar rewatch night", "tags": ["familiar", "cozy", "easy", "night"]},
        {"text": "A social game night", "tags": ["social", "group", "shared", "active"]},
        {"text": "A quiet solo reading session", "tags": ["quiet", "alone", "cozy", "easy"]},
        {"text": "A bright travel documentary", "tags": ["fresh", "morning", "explore", "light"]},
        {"text": "An intense long thriller", "tags": ["intense", "long", "dark"]},
    ],
    "study": [
        {"text": "Structured checklist sprint", "tags": ["structured", "checklist", "finishable", "clear", "quick"]},
        {"text": "Short focused review block", "tags": ["short", "focused", "practical", "clear"]},
        {"text": "Practical example walkthrough", "tags": ["practical", "incremental", "clear", "focused"]},
        {"text": "Quick summary pass", "tags": ["quick", "simple", "finishable", "light"]},
        {"text": "Long open-ended exploration", "tags": ["open-ended", "ambitious", "long", "chaotic"]},
        {"text": "Deep ambitious research sprint", "tags": ["ambitious", "deep", "long", "complex"]},
    ],
    "shopping": [
        {"text": "Practical durable option", "tags": ["practical", "durable", "reliable", "value"]},
        {"text": "Budget-friendly basic version", "tags": ["budget", "cheap", "affordable", "practical"]},
        {"text": "One worthwhile quality upgrade", "tags": ["quality", "worthwhile", "reliable"]},
        {"text": "Comfort purchase that feels easy", "tags": ["comfort", "easy", "familiar"]},
        {"text": "Novel impulse pick", "tags": ["novel", "spontaneous", "risky"]},
    ],
    "custom": [
        {"text": "The familiar safe option", "tags": ["familiar", "safe", "easy", "reliable"]},
        {"text": "The simple low-friction option", "tags": ["simple", "easy", "quick", "practical"]},
        {"text": "The social shared option", "tags": ["shared", "social", "group"]},
        {"text": "The ambitious stretch option", "tags": ["ambitious", "explore", "complex"]},
        {"text": "The budget-aware practical option", "tags": ["budget", "cheap", "practical", "value"]},
    ],
}

SUGGESTION_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "to",
    "of",
    "for",
    "after",
    "before",
    "with",
    "without",
    "choose",
    "pick",
    "what",
    "should",
    "i",
    "my",
    "me",
    "something",
}


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

    def suggest_options(self, payload: DecisionOptionSuggestionInput) -> OptionSuggestionResponse:
        user = self.repository.get_user_profile(payload.user_id)
        if user is None:
            raise ValueError(f"User profile '{payload.user_id}' was not found.")
        if not payload.prompt.strip():
            raise ValueError("Enter a question before requesting option suggestions.")

        snapshot = self._load_snapshot(payload.user_id)
        profile_signals = self.profile_service.get_profile_signals(payload.user_id)
        recent_state_payload = self.profile_service.get_recent_state_payload(payload.user_id)
        effective_context = dict(payload.context)
        suggestion_sources = self._build_suggestion_candidates(
            user_id=payload.user_id,
            category=payload.category,
            prompt=payload.prompt,
            existing_options=payload.existing_options,
            long_term_preferences=user.long_term_preferences_json,
            recent_state_payload=recent_state_payload,
            snapshot=snapshot,
            effective_context=effective_context,
            max_candidates=max(payload.max_suggestions * 3, 6),
        )
        if not suggestion_sources:
            raise ValueError("No personalized option suggestions were available for this request.")

        candidate_texts = list(suggestion_sources.keys())
        retrieved_memories = self.retriever.retrieve(
            RetrievalQuery(
                user_id=payload.user_id,
                category=payload.category,
                prompt=payload.prompt,
                options=candidate_texts,
                context=payload.context,
                limit=self.settings.retrieval_top_k,
            )
        )
        scoring_context = ScoringContext(
            category=payload.category,
            prompt=payload.prompt,
            context=payload.context,
            long_term_preferences=user.long_term_preferences_json,
            profile_signals=profile_signals,
            snapshot=snapshot,
            recent_state_notes=recent_state_payload["combined_notes"],
            retrieved_memories=retrieved_memories,
            effective_context=effective_context,
        )
        scored_candidates = [
            self.scoring_pipeline.score_option(
                scoring_context=scoring_context,
                option=DecisionOption(
                    request_id="suggestion-preview",
                    option_text=option_text,
                    option_metadata_json={
                        "suggested": True,
                        "suggestion_tags": sorted(suggestion_sources[option_text]["tags"]),
                    },
                    position=index,
                ),
            )
            for index, option_text in enumerate(candidate_texts)
        ]
        ranked = self._normalize_suggested_options(
            scored=scored_candidates,
            prompt=payload.prompt,
            context=effective_context,
            suggestion_sources=suggestion_sources,
        )
        suggestions = [
            SuggestedOption(
                option_text=item.scored_option.option.option_text,
                confidence=round(item.confidence, 4),
                rationale=self._build_suggestion_rationale(item.scored_option),
                source_labels=self._build_suggestion_source_labels(
                    initial_labels=suggestion_sources[item.scored_option.option.option_text]["labels"],
                    scored_option=item.scored_option,
                ),
                supporting_evidence=item.scored_option.supporting_evidence[:3],
            )
            for item in ranked[: payload.max_suggestions]
        ]
        return OptionSuggestionResponse(
            strategy="profile-memory-suggestion-ranker",
            active_context=effective_context,
            suggestions=suggestions,
        )

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
        effective_context = self._build_effective_context(
            request_context=payload.context,
            recent_state_payload=recent_state_payload,
            snapshot=snapshot,
        )

        scoring_context = ScoringContext(
            category=payload.category,
            prompt=payload.prompt,
            context=payload.context,
            long_term_preferences=user.long_term_preferences_json,
            profile_signals=profile_signals,
            snapshot=snapshot,
            recent_state_notes=recent_state_payload["combined_notes"],
            retrieved_memories=retrieved_memories,
            effective_context=effective_context,
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
        option_influences = self._build_option_assessments(ranked=ranked)
        agent_workflow = self._build_agent_workflow(
            user=user,
            category=payload.category,
            profile_signals=profile_signals,
            recent_state_payload=recent_state_payload,
            retrieved_memories=retrieved_memories,
            ranked=ranked,
            option_influences=option_influences,
            effective_context=effective_context,
        )
        top_choice_influence = option_influences[0].influence
        agent_agreement = self._build_agent_agreement(
            top_assessment=option_influences[0],
            agent_workflow=agent_workflow,
        )
        explanation_sections = self._build_explanation_sections(
            ranked=ranked,
            retrieved_memories=retrieved_memories,
            recent_state_payload=recent_state_payload,
            llm_note=llm_result.explanation if llm_result else llm_error,
            agent_workflow=agent_workflow,
            option_influences=option_influences,
            agent_agreement=agent_agreement,
            display_name=user.display_name,
            effective_context=effective_context,
        )
        decision_audit = self._build_decision_audit(
            ranked=ranked,
            recent_state_payload=recent_state_payload,
            retrieved_memories=retrieved_memories,
            effective_context=effective_context,
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
            agent_workflow=agent_workflow,
            top_choice_influence=top_choice_influence,
            option_influences=option_influences,
            agent_agreement=agent_agreement,
            explanation_sections=explanation_sections,
            decision_audit=decision_audit,
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

    def _build_agent_workflow(
        self,
        user,
        category: str,
        profile_signals: list[ProfileSignalRead],
        recent_state_payload: dict,
        retrieved_memories,
        ranked: list[_ResolvedOptionScore],
        option_influences: list[AgentOptionAssessment],
        effective_context: dict,
    ) -> AgentWorkflowTrace:
        return AgentWorkflowTrace(
            profile_agent=self._build_profile_agent_brief(
                user=user,
                category=category,
                profile_signals=profile_signals,
            ),
            recent_state_agent=self._build_recent_state_agent_brief(
                recent_state_payload=recent_state_payload,
                effective_context=effective_context,
            ),
            memory_agent=self._build_memory_agent_brief(retrieved_memories=retrieved_memories),
            choice_reasoning_agent=self._build_choice_reasoning_agent_brief(
                ranked=ranked,
                option_influences=option_influences,
            ),
            reflection_agent=self._build_reflection_agent_brief(
                recent_state_payload=recent_state_payload,
                effective_context=effective_context,
            ),
        )

    @staticmethod
    def _build_profile_agent_brief(
        user,
        category: str,
        profile_signals: list[ProfileSignalRead],
    ) -> AgentBrief:
        reviewed_signals = [signal for signal in profile_signals if signal.status in {"accepted", "edited"}]
        values = user.personality_signals_json.get("values", [])[:2]
        decision_style = user.personality_signals_json.get("decision_style", [])[:2]
        category_preferences = user.long_term_preferences_json.get("category_preferences", {}).get(category, {})
        preferred_keywords = category_preferences.get("preferred_keywords", [])[:3]
        observations = [user.profile_summary]
        if reviewed_signals:
            observations.append(f"{len(reviewed_signals)} reviewed profile signals are actively shaping the stable model.")
        if values:
            observations.append(f"Core values that recur in this profile: {', '.join(values)}.")
        if decision_style:
            observations.append(f"Decision style markers: {', '.join(decision_style)}.")
        if preferred_keywords:
            observations.append(f"For {category}, the stable profile leans toward {', '.join(preferred_keywords)}.")
        conclusion = (
            f"In general, {user.display_name} tends to choose {category} options that feel "
            f"{', '.join(preferred_keywords[:2])}."
            if preferred_keywords
            else f"In general, {user.display_name}'s stable profile is coherent enough to guide this decision."
        )
        return AgentBrief(
            agent_name="Profile Agent",
            focus="Describe who this user is in general and what stable preferences usually persist.",
            observations=observations[:4],
            conclusion=conclusion,
        )

    @staticmethod
    def _build_recent_state_agent_brief(
        recent_state_payload: dict,
        effective_context: dict,
    ) -> AgentBrief:
        manual_notes = recent_state_payload.get("manual_notes", [])[:2]
        snapshot_notes = recent_state_payload.get("snapshot_notes", [])[:2]
        drift_markers = recent_state_payload.get("drift_markers", [])[:2]
        active_overrides = recent_state_payload.get("active_context_overrides", {})
        observations = list(dict.fromkeys(manual_notes + snapshot_notes + drift_markers))
        if active_overrides:
            observations.append(
                "Active carry-over context: "
                + ", ".join(f"{key}={value}" for key, value in list(active_overrides.items())[:3])
                + "."
            )
        if not observations and effective_context:
            observations.append(
                "Current explicit context is "
                + ", ".join(f"{key}={value}" for key, value in effective_context.items())
                + "."
            )
        active_recent_pressure = bool(manual_notes or snapshot_notes or drift_markers or active_overrides)
        conclusion = (
            "Right now, temporary state is materially changing what would feel natural to choose."
            if active_recent_pressure
            else "No temporary state is strongly overriding the stable profile right now."
        )
        return AgentBrief(
            agent_name="Recent State Agent",
            focus="Identify what matters about this user right now rather than in general.",
            observations=observations[:4],
            conclusion=conclusion,
        )

    @staticmethod
    def _build_memory_agent_brief(retrieved_memories) -> AgentBrief:
        observations = [
            f"{memory.chosen_option_text}: {memory.why_retrieved[0] if memory.why_retrieved else memory.summary}"
            for memory in retrieved_memories[:3]
        ]
        direct_precedent = next(
            (memory for memory in retrieved_memories if memory.memory_role in {"direct_match", "recent_repeat"}),
            None,
        )
        conclusion = (
            f"A close precedent exists: the user recently chose '{direct_precedent.chosen_option_text}' in a similar situation."
            if direct_precedent
            else "No exact precedent dominated, so analogous memories are guiding the comparison."
        )
        if not observations:
            observations = ["No retrieved memory strongly matched this request."]
        return AgentBrief(
            agent_name="Memory Agent",
            focus="Find which past choices are genuinely relevant for this decision.",
            observations=observations,
            conclusion=conclusion,
        )

    def _build_choice_reasoning_agent_brief(
        self,
        ranked: list[_ResolvedOptionScore],
        option_influences: list[AgentOptionAssessment],
    ) -> AgentBrief:
        top = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else None
        top_assessment = option_influences[0]
        observations = list(top_assessment.why_choose[:2])
        if runner_up:
            runner_up_assessment = next(
                (item for item in option_influences if item.option_id == runner_up.scored_option.option.option_id),
                None,
            )
            if runner_up_assessment and runner_up_assessment.why_avoid:
                observations.append(
                    f"Runner-up friction for '{runner_up_assessment.option_text}': {runner_up_assessment.why_avoid[0]}"
                )
        influence = top_assessment.influence
        influence_pairs = [
            ("stable profile", influence.stable_profile),
            ("recent state", influence.recent_state),
            ("memory", influence.memory),
            ("context", influence.context),
            ("llm", influence.llm),
        ]
        strongest_label, strongest_score = max(influence_pairs, key=lambda item: abs(item[1]))
        strongest_direction = "push" if strongest_score >= 0 else "drag"
        conclusion = (
            f"'{top.scored_option.option.option_text}' wins because {strongest_label} supplied the strongest {strongest_direction} "
            f"({round(strongest_score, 2)})."
        )
        return AgentBrief(
            agent_name="Choice Reasoning Agent",
            focus="Compare candidate options and explain why this user would choose or avoid each one.",
            observations=observations[:4],
            conclusion=conclusion,
        )

    @staticmethod
    def _build_reflection_agent_brief(
        recent_state_payload: dict,
        effective_context: dict,
    ) -> AgentBrief:
        feedback_shift_notes = recent_state_payload.get("feedback_shift_notes", [])[:2]
        adaptation_signals = recent_state_payload.get("adaptation_signals", [])[:2]
        active_overrides = recent_state_payload.get("active_context_overrides", {})
        observations = list(dict.fromkeys(feedback_shift_notes + adaptation_signals))
        if active_overrides:
            observations.append(
                "Carry-over from recent feedback remains active for "
                + ", ".join(f"{key}={value}" for key, value in list(active_overrides.items())[:3])
                + "."
            )
        if not observations and effective_context:
            observations.append("No recent feedback override is active beyond the explicit current context.")
        has_reflection_pressure = bool(feedback_shift_notes or adaptation_signals or active_overrides)
        conclusion = (
            "Recent feedback is still updating the user model and should remain visible in the next few decisions."
            if has_reflection_pressure
            else "No strong feedback-driven carry-over is active beyond the current baseline profile."
        )
        return AgentBrief(
            agent_name="Reflection Agent",
            focus="Track how recent feedback should update the near-term user model.",
            observations=observations[:4],
            conclusion=conclusion,
        )

    @staticmethod
    def _build_influence_breakdown(scored_option: ScoredOption) -> AgentInfluenceBreakdown:
        bucket_map = {
            "profile_affinity": "stable_profile",
            "memory_support": "memory",
            "recent_state_influence": "recent_state",
            "recent_trend_influence": "recent_state",
            "adaptive_context_alignment": "recent_state",
            "context_compatibility": "context",
            "llm_rank_bonus": "llm",
        }
        totals = {
            "stable_profile": 0.0,
            "recent_state": 0.0,
            "memory": 0.0,
            "context": 0.0,
            "llm": 0.0,
        }
        dominant_signals: list[str] = []
        sorted_components = sorted(
            scored_option.component_scores,
            key=lambda component: abs(component.weighted_score),
            reverse=True,
        )
        for component in sorted_components:
            bucket = bucket_map.get(component.name)
            if bucket is not None:
                totals[bucket] += component.weighted_score
            if component.reason and abs(component.weighted_score) >= 0.12:
                direction = "support" if component.weighted_score >= 0 else "drag"
                dominant_signals.append(
                    f"{bucket.replace('_', ' ') if bucket else component.name} {direction}: {component.reason}"
                )
        return AgentInfluenceBreakdown(
            option_id=scored_option.option.option_id,
            option_text=scored_option.option.option_text,
            stable_profile=round(totals["stable_profile"], 4),
            recent_state=round(totals["recent_state"], 4),
            memory=round(totals["memory"], 4),
            context=round(totals["context"], 4),
            llm=round(totals["llm"], 4),
            dominant_signals=dominant_signals[:4],
        )

    def _build_option_assessments(
        self,
        ranked: list[_ResolvedOptionScore],
    ) -> list[AgentOptionAssessment]:
        assessments: list[AgentOptionAssessment] = []
        for index, item in enumerate(ranked):
            scored_option = item.scored_option
            positive_component_reasons = [
                component.reason
                for component in scored_option.component_scores
                if component.weighted_score > 0 and component.reason
            ]
            negative_component_reasons = [
                component.reason
                for component in scored_option.component_scores
                if component.weighted_score < 0 and component.reason
            ]
            why_choose = list(dict.fromkeys(scored_option.supporting_evidence + positive_component_reasons))[:4]
            why_avoid = list(dict.fromkeys(scored_option.counter_evidence + negative_component_reasons))[:4]
            if not why_choose:
                why_choose = [scored_option.reason_summary]
            if not why_avoid and index > 0:
                why_avoid = ["Other candidate options received stronger personalized support for this user."]
            assessments.append(
                AgentOptionAssessment(
                    option_id=scored_option.option.option_id,
                    option_text=scored_option.option.option_text,
                    why_choose=why_choose,
                    why_avoid=why_avoid,
                    influence=self._build_influence_breakdown(scored_option),
                )
            )
        return assessments

    @staticmethod
    def _stance_from_score(score: float) -> tuple[str, float]:
        magnitude = abs(score)
        if magnitude < 0.12:
            return "neutral", magnitude
        if score > 0:
            return "support", magnitude
        return "oppose", magnitude

    def _build_agent_agreement(
        self,
        top_assessment: AgentOptionAssessment,
        agent_workflow: AgentWorkflowTrace,
    ) -> AgentAgreementSummary:
        influence = top_assessment.influence
        raw_signals = [
            ("Profile Agent", influence.stable_profile, agent_workflow.profile_agent.conclusion),
            ("Recent State Agent", influence.recent_state, agent_workflow.recent_state_agent.conclusion),
            ("Memory Agent", influence.memory, agent_workflow.memory_agent.conclusion),
            ("Choice Reasoning Agent", sum([
                influence.stable_profile,
                influence.recent_state,
                influence.memory,
                influence.context,
                influence.llm,
            ]), agent_workflow.choice_reasoning_agent.conclusion),
            ("Reflection Agent", influence.recent_state, agent_workflow.reflection_agent.conclusion),
        ]
        if abs(influence.context) >= 0.12:
            raw_signals.append(("Context Signal", influence.context, "Current situational context materially affected the top choice."))
        if abs(influence.llm) >= 0.12:
            raw_signals.append(("LLM Tie-Breaker", influence.llm, "LLM ranking added a meaningful extra push on the final ordering."))

        signals: list[AgentAgreementSignal] = []
        supporting_agents: list[str] = []
        opposing_agents: list[str] = []
        neutral_agents: list[str] = []
        for agent_name, score, rationale in raw_signals:
            stance, strength = self._stance_from_score(score)
            signal = AgentAgreementSignal(
                agent_name=agent_name,
                stance=stance,  # type: ignore[arg-type]
                strength=round(strength, 4),
                rationale=rationale,
            )
            signals.append(signal)
            if stance == "support":
                supporting_agents.append(agent_name)
            elif stance == "oppose":
                opposing_agents.append(agent_name)
            else:
                neutral_agents.append(agent_name)

        support_count = len(supporting_agents)
        oppose_count = len(opposing_agents)
        if support_count >= 4 and oppose_count == 0:
            overall_label = "strong_agreement"
        elif support_count >= 3 and oppose_count <= 1:
            overall_label = "partial_agreement"
        elif oppose_count >= 2:
            overall_label = "mixed"
        else:
            overall_label = "fragile"

        if overall_label == "strong_agreement":
            summary = (
                f"Most agents aligned behind '{top_assessment.option_text}', so the final prediction reflects broad agreement."
            )
        elif overall_label == "partial_agreement":
            summary = (
                f"Several agents supported '{top_assessment.option_text}', though not every signal pointed in the same direction."
            )
        elif overall_label == "mixed":
            summary = (
                f"The final pick '{top_assessment.option_text}' won despite meaningful disagreement between agents."
            )
        else:
            summary = (
                f"The final pick '{top_assessment.option_text}' is fragile because agent support is limited or weak."
            )

        return AgentAgreementSummary(
            overall_label=overall_label,  # type: ignore[arg-type]
            summary=summary,
            supporting_agents=supporting_agents,
            opposing_agents=opposing_agents,
            neutral_agents=neutral_agents,
            signals=signals,
        )

    def _build_explanation_sections(
        self,
        ranked: list[_ResolvedOptionScore],
        retrieved_memories,
        recent_state_payload: dict,
        llm_note: str | None,
        agent_workflow: AgentWorkflowTrace,
        option_influences: list[AgentOptionAssessment],
        agent_agreement: AgentAgreementSummary,
        display_name: str,
        effective_context: dict,
    ) -> ExplanationSections:
        top = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else None
        top_assessment = option_influences[0]
        top_reason = (
            top_assessment.why_choose[0]
            if top_assessment.why_choose
            else top.scored_option.supporting_evidence[0]
            if top.scored_option.supporting_evidence
            else top.scored_option.reason_summary
        )
        context_summary = ", ".join(f"{key}={value}" for key, value in effective_context.items() if value)
        memory_evidence = [
            f"{memory.chosen_option_text}: {memory.why_retrieved[0] if memory.why_retrieved else memory.summary}"
            for memory in retrieved_memories[:3]
        ]
        recent_notes = recent_state_payload.get("combined_notes", [])[:3]
        losing_reasons: list[str] = []
        if runner_up:
            runner_up_assessment = next(
                (item for item in option_influences if item.option_id == runner_up.scored_option.option.option_id),
                None,
            )
            if runner_up_assessment and runner_up_assessment.why_avoid:
                losing_reasons.extend(runner_up_assessment.why_avoid[:2])
            elif runner_up.scored_option.counter_evidence:
                losing_reasons.extend(runner_up.scored_option.counter_evidence[:2])
            else:
                losing_reasons.append(
                    f"'{runner_up.scored_option.option.option_text}' received less combined support from stable profile, recent state, memory, and context."
                )
        if llm_note:
            losing_reasons.append(f"LLM note: {llm_note}")
        adaptation_notes = recent_state_payload.get("adaptation_signals", [])[:2]
        if adaptation_notes:
            losing_reasons.extend(adaptation_notes)

        return ExplanationSections(
            top_choice_summary=" ".join(
                part
                for part in [
                    (
                        f"{display_name} is most likely to choose '{top.scored_option.option.option_text}' right now"
                        f"{' under ' + context_summary if context_summary else ''}."
                    ),
                    " ".join(
                        conclusion
                        for conclusion in [
                            agent_workflow.profile_agent.conclusion,
                            agent_workflow.recent_state_agent.conclusion,
                            agent_workflow.memory_agent.conclusion,
                            agent_agreement.summary,
                        ]
                        if conclusion
                    ),
                    (
                        f"It beats '{runner_up.scored_option.option.option_text}' because "
                        f"{top_reason.lower() if top_reason else 'it has stronger combined support from stable profile, memory, and current context'}."
                        if runner_up
                        else "It has the strongest combined support from stable profile, memory, and recent context."
                    ),
                ]
                if part
            ),
            why_this_option=top_assessment.why_choose[:4] or [top.scored_option.reason_summary],
            what_memories_mattered=memory_evidence or agent_workflow.memory_agent.observations[:3],
            what_recent_state_mattered=(
                agent_workflow.recent_state_agent.observations[:3]
                + recent_notes
                + recent_state_payload.get("adaptation_signals", [])[:2]
            )[:4]
            or ["No recent-state note or short-term drift marker strongly changed the result."],
            why_other_options_lost=(losing_reasons + top_assessment.influence.dominant_signals[:1])[:4],
        )

    def _build_suggestion_candidates(
        self,
        user_id: str,
        category: str,
        prompt: str,
        existing_options: list[str],
        long_term_preferences: dict,
        recent_state_payload: dict,
        snapshot: PreferenceSnapshotRead | None,
        effective_context: dict,
        max_candidates: int,
    ) -> dict[str, dict[str, object]]:
        candidate_sources: OrderedDict[str, dict[str, object]] = OrderedDict()
        excluded = {option.strip().lower() for option in existing_options if option.strip()}

        category_preferences = long_term_preferences.get("category_preferences", {}).get(category, {})
        preferred_tokens = {token.lower() for token in category_preferences.get("preferred_keywords", [])}
        active_context_keys = self._context_preference_keys(effective_context)
        context_tokens: set[str] = set()
        context_preferences = long_term_preferences.get("context_preferences", {})
        for key in active_context_keys:
            context_tokens.update(str(token).lower() for token in context_preferences.get(key, []))
        prompt_tokens = self._suggestion_tokens(prompt)
        recent_tokens = {
            token.lower()
            for token in self._suggestion_tokens(" ".join(recent_state_payload.get("combined_notes", [])[:3]))
        }

        def add_candidate(
            option_text: str,
            labels: list[str],
            tags: set[str] | None = None,
            seed_score: float = 0.0,
        ) -> None:
            normalized = option_text.strip()
            if not normalized or normalized.lower() in excluded:
                return
            if normalized not in candidate_sources:
                candidate_sources[normalized] = {"labels": [], "tags": set(), "seed_score": 0.0}
            for label in labels:
                if label and label not in candidate_sources[normalized]["labels"]:
                    candidate_sources[normalized]["labels"].append(label)
            if tags:
                candidate_sources[normalized]["tags"].update(tags)
            candidate_sources[normalized]["seed_score"] = max(
                float(candidate_sources[normalized]["seed_score"]),
                float(seed_score),
            )

        for memory in self.repository.list_memories(user_id, limit=12):
            if memory.category != category:
                continue
            memory_tags = self._suggestion_tokens(
                memory.summary,
                memory.chosen_option_text,
                flatten_to_text(memory.context_json),
                *[str(tag) for tag in memory.tags_json],
            )
            prompt_overlap = len(memory_tags & prompt_tokens)
            context_overlap = len(memory_tags & context_tokens)
            recent_overlap = len(memory_tags & recent_tokens)
            if prompt_overlap + context_overlap < 2:
                continue
            seed_score = prompt_overlap * 2.5 + context_overlap * 2.1 + recent_overlap * 1.0 + memory.salience_score * 0.3
            add_candidate(
                memory.chosen_option_text,
                ["recent memory"],
                tags=memory_tags,
                seed_score=seed_score,
            )

        if snapshot is not None:
            recent_options = snapshot.derived_statistics.get("recent_option_counts", {}).get(category, {})
            for option_text in recent_options:
                option_tags = self._suggestion_tokens(option_text)
                overlap = len(option_tags & prompt_tokens) + len(option_tags & context_tokens)
                if overlap:
                    add_candidate(option_text, ["recent trend"], tags=option_tags, seed_score=overlap * 1.7)

        library = SUGGESTION_LIBRARY.get(category, SUGGESTION_LIBRARY["custom"])
        scored_entries: list[tuple[float, int, dict[str, object], list[str]]] = []
        for index, entry in enumerate(library):
            entry_tags = {str(tag).lower() for tag in entry.get("tags", [])}
            labels = ["candidate archetype"]
            profile_overlap = len(entry_tags & preferred_tokens)
            context_overlap = len(entry_tags & context_tokens)
            prompt_overlap = len(entry_tags & prompt_tokens)
            recent_overlap = len(entry_tags & recent_tokens)
            if profile_overlap:
                labels.append("stable profile")
            if context_overlap:
                labels.append("current context")
            if recent_overlap:
                labels.append("recent state")
            if prompt_overlap:
                labels.append("prompt framing")
            score = (
                profile_overlap * 1.45
                + context_overlap * 2.4
                + recent_overlap * 1.0
                + prompt_overlap * 2.8
            )
            scored_entries.append((score, index, entry, labels))

        scored_entries.sort(key=lambda item: (-item[0], item[1]))
        for score, _, entry, labels in scored_entries:
            if score > 0 or len(candidate_sources) < max_candidates:
                add_candidate(
                    str(entry["text"]),
                    labels,
                    tags={str(tag).lower() for tag in entry.get("tags", [])},
                    seed_score=score,
                )
            if len(candidate_sources) >= max_candidates:
                break

        for option_text, payload in candidate_sources.items():
            payload["tags"].update(self._suggestion_tokens(option_text))

        return dict(candidate_sources)

    def _normalize_suggested_options(
        self,
        scored: list[ScoredOption],
        prompt: str,
        context: dict,
        suggestion_sources: dict[str, dict[str, object]],
    ) -> list[_ResolvedOptionScore]:
        adjusted_scores: list[float] = []
        for item in scored:
            source_payload = suggestion_sources.get(item.option.option_text, {})
            seed_score = float(source_payload.get("seed_score", 0.0))
            prompt_alignment = self._compute_suggestion_prompt_alignment(
                prompt=prompt,
                context=context,
                option_text=item.option.option_text,
                tags={str(tag).lower() for tag in source_payload.get("tags", set())},
            )
            base_score = 0.1
            for component in item.component_scores:
                weight = 1.0
                if component.name == "memory_support":
                    weight = 0.2
                elif component.name == "recent_trend_influence":
                    weight = 0.45
                base_score += component.weighted_score * weight
            adjusted_scores.append(base_score + seed_score * 0.12 + prompt_alignment * 1.8)
        confidences = self._softmax(adjusted_scores)
        ranked = [
            _ResolvedOptionScore(scored_option=item, confidence=confidence)
            for item, confidence in zip(scored, confidences, strict=True)
        ]
        ranked.sort(key=lambda item: item.confidence, reverse=True)
        return ranked

    @staticmethod
    def _suggestion_tokens(*parts: str) -> set[str]:
        tokens: set[str] = set()
        for part in parts:
            for token in tokenize(part):
                normalized = str(token).lower().strip()
                if len(normalized) <= 2 or normalized in SUGGESTION_STOPWORDS:
                    continue
                tokens.add(normalized)
        return tokens

    @staticmethod
    def _compute_suggestion_prompt_alignment(
        prompt: str,
        context: dict,
        option_text: str,
        tags: set[str],
    ) -> float:
        prompt_tokens = DecisionService._suggestion_tokens(prompt)
        option_tokens = DecisionService._suggestion_tokens(option_text)
        combined_tokens = set(tags) | option_tokens
        score = len(combined_tokens & prompt_tokens) * 0.55

        prompt_text = prompt.lower()
        if "lunch" in prompt_text:
            if combined_tokens & {"light", "fresh", "quick", "salad", "tea"}:
                score += 3.2
            if combined_tokens & {"heavy", "cozy", "night", "stew", "warm", "soup", "noodle"}:
                score -= 3.4
        if "dinner" in prompt_text or "evening" in prompt_text or "tonight" in prompt_text:
            if combined_tokens & {"warm", "cozy", "shared", "soup", "noodle"}:
                score += 1.35
        if "watch" in prompt_text or "movie" in prompt_text or "show" in prompt_text:
            if combined_tokens & {"drama", "comedy", "rewatch", "thriller", "documentary"}:
                score += 0.9
        weather = str(context.get("weather", "")).lower()
        if weather == "sunny" and combined_tokens & {"fresh", "light", "outdoor"}:
            score += 1.8
        if weather == "sunny" and combined_tokens & {"warm", "cozy", "soup", "noodle"}:
            score -= 2.4
        if weather == "rainy" and combined_tokens & {"warm", "cozy", "indoor"}:
            score += 1.1
        return score

    @staticmethod
    def _build_effective_context(
        request_context: dict,
        recent_state_payload: dict,
        snapshot: PreferenceSnapshotRead | None,
    ) -> dict:
        effective_context = dict(request_context)
        if snapshot is None:
            return effective_context
        active_overrides = snapshot.derived_statistics.get("active_context_overrides", {})
        for key, value in active_overrides.items():
            effective_context.setdefault(key, value)
        return effective_context

    @staticmethod
    def _context_preference_keys(effective_context: dict) -> list[str]:
        keys: list[str] = []
        energy = str(effective_context.get("energy", "")).strip().lower()
        if energy in {"low", "high"}:
            keys.append(f"energy_{energy}")
        social = str(effective_context.get("with", "")).strip().lower()
        if social in {"alone", "partner", "friends", "family"}:
            keys.append(f"with_{social}")
        budget = str(effective_context.get("budget", "")).strip().lower()
        if budget in {"low", "tight"}:
            keys.append("budget_sensitive")
        urgency = str(effective_context.get("urgency", "")).strip().lower()
        if urgency == "high":
            keys.append("time_pressure")
        time_of_day = str(effective_context.get("time_of_day", "")).strip().lower()
        if time_of_day:
            keys.append(f"time_of_day_{time_of_day}")
        weather = str(effective_context.get("weather", "")).strip().lower()
        if weather:
            keys.append(f"weather_{weather}")
        return keys

    @staticmethod
    def _build_suggestion_rationale(scored_option: ScoredOption) -> str:
        if scored_option.supporting_evidence:
            return " ".join(scored_option.supporting_evidence[:2])
        return scored_option.reason_summary

    @staticmethod
    def _build_suggestion_source_labels(initial_labels: list[str], scored_option: ScoredOption) -> list[str]:
        labels = list(initial_labels)
        component_label_map = {
            "profile_affinity": "stable profile",
            "memory_support": "memory match",
            "context_compatibility": "current context",
            "recent_state_influence": "recent state",
            "recent_trend_influence": "recent trend",
            "adaptive_context_alignment": "current context",
        }
        for component in scored_option.component_scores:
            if component.weighted_score <= 0:
                continue
            label = component_label_map.get(component.name)
            if label and label not in labels:
                labels.append(label)
        return labels[:4]

    @staticmethod
    def _build_decision_audit(
        ranked: list[_ResolvedOptionScore],
        recent_state_payload: dict,
        retrieved_memories,
        effective_context: dict,
    ) -> DecisionAudit:
        top = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else None
        margin = round(top.confidence - runner_up.confidence, 4) if runner_up else round(top.confidence, 4)
        confidence_label = "high" if margin >= 0.3 else "medium" if margin >= 0.12 else "fragile"
        decisive_factors = list(
            dict.fromkeys(
                top.scored_option.supporting_evidence
                + [component.reason for component in top.scored_option.component_scores if component.weighted_score > 0]
            )
        )[:4]
        watchouts = top.scored_option.counter_evidence[:2]
        if runner_up:
            watchouts.extend(runner_up.scored_option.supporting_evidence[:2])
        if not watchouts:
            watchouts.append("No single counter-signal strongly challenged the winning option.")

        adaptation_signals = list(
            dict.fromkeys(
                recent_state_payload.get("adaptation_signals", [])
                + recent_state_payload.get("feedback_shift_notes", [])
                + [
                    f"Retrieved memory emphasis: {memory.chosen_option_text}"
                    for memory in retrieved_memories[:2]
                    if memory.memory_role in {"direct_match", "recent_repeat"}
                ]
            )
        )[:4]

        return DecisionAudit(
            confidence_label=confidence_label,
            margin_vs_runner_up=margin,
            decisive_factors=decisive_factors or [top.scored_option.reason_summary],
            watchouts=watchouts[:4],
            adaptation_signals=adaptation_signals,
            active_context=effective_context,
        )
