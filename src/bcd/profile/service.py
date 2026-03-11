"""Profile and bootstrap services."""

from __future__ import annotations

from uuid import uuid4

from sqlmodel import Session

from bcd.config import Settings, get_settings
from bcd.profile.card import ProfileCardRenderer, write_profile_card
from bcd.profile.inference import (
    PreferenceSeed,
    build_preference_profile,
    build_profile_from_chatgpt_export,
    load_chatgpt_export,
    slugify_display_name,
)
from bcd.profile.sample_data import load_json
from bcd.profile.schemas import (
    ChatGPTImportResponse,
    PreferenceSnapshotRead,
    UserOnboardingInput,
    UserProfileRead,
)
from bcd.storage.models import (
    ActualChoiceFeedback,
    DecisionOption,
    DecisionRequest,
    MemoryEntry,
    PreferenceSnapshot,
    PredictionResult,
    UserProfile,
)
from bcd.storage.repository import BCDRepository
from bcd.utils.text import extract_context_tags, flatten_to_text, tokenize


def _build_seed_summary(event: dict, chosen_text: str) -> str:
    context_text = flatten_to_text(event.get("context", {})).strip()
    reason_text = event.get("reason_text", "").strip()
    summary = f"User chose '{chosen_text}' for {event['category']} after: {event['prompt']}"
    if context_text:
        summary += f" Context: {context_text}."
    if reason_text:
        summary += f" Reason: {reason_text}"
    return summary


def _is_meaningful_snapshot_tag(tag: str) -> bool:
    stop_tags = {"time", "of", "day", "with", "energy", "weather", "budget", "mood", "a", "the"}
    if tag in stop_tags:
        return False
    return True


class ProfileService:
    """Handles profile initialization and retrieval."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repository = BCDRepository(session)
        self.card_renderer = ProfileCardRenderer()

    def bootstrap_sample_profile(self) -> UserProfileRead:
        """Create the sample profile and seed history if it does not exist."""

        sample_profile = load_json(self.settings.sample_profile_path)
        existing = self.repository.get_user_profile(sample_profile["user_id"])
        if existing:
            bundle = self.get_profile_bundle(existing.user_id)
            self.ensure_profile_card(existing.user_id, bundle=bundle)
            return self.get_profile_bundle(existing.user_id)

        profile = UserProfile(
            user_id=sample_profile["user_id"],
            display_name=sample_profile["display_name"],
            profile_summary=sample_profile["profile_summary"],
            personality_signals_json=sample_profile["personality_signals"],
            long_term_preferences_json=sample_profile["long_term_preferences"],
            onboarding_answers_json=sample_profile["onboarding_answers"],
        )
        self.repository.add(profile)

        seed_history = load_json(self.settings.sample_decisions_path)
        for event in seed_history:
            request = self.repository.add(
                DecisionRequest(
                    user_id=profile.user_id,
                    prompt=event["prompt"],
                    category=event["category"],
                    context_json=event.get("context", {}),
                )
            )
            options = self.repository.add_all(
                [
                    DecisionOption(
                        request_id=request.request_id,
                        option_text=option["option_text"],
                        option_metadata_json=option.get("option_metadata", {}),
                        position=index,
                    )
                    for index, option in enumerate(event["options"])
                ]
            )
            option_by_text = {option.option_text: option for option in options}
            predicted_option = option_by_text[event["predicted_option_text"]]
            actual_option = option_by_text[event["actual_option_text"]]

            prediction = self.repository.add(
                PredictionResult(
                    request_id=request.request_id,
                    predicted_option_id=predicted_option.option_id,
                    ranked_option_ids_json=[predicted_option.option_id] + [
                        option.option_id for option in options if option.option_id != predicted_option.option_id
                    ],
                    score_breakdown_json={
                        predicted_option.option_id: {
                            "profile_affinity": 1.0,
                            "memory_support": 0.0,
                            "context_compatibility": 1.0,
                            "recent_trend_bonus": 0.0,
                            "total": 2.0,
                        }
                    },
                    confidence_by_option_json={
                        option.option_id: 0.8 if option.option_id == predicted_option.option_id else 0.1
                        for option in options
                    },
                    explanation=f"Seed history indicates a preference for '{predicted_option.option_text}' in similar situations.",
                    strategy="seed-data",
                    retrieved_memory_ids_json=[],
                )
            )
            feedback = self.repository.add(
                ActualChoiceFeedback(
                    request_id=request.request_id,
                    actual_option_id=actual_option.option_id,
                    reason_text=event.get("reason_text"),
                    reason_tags_json=event.get("reason_tags", []),
                )
            )
            combined_tags = list(
                dict.fromkeys(
                    event.get("reason_tags", [])
                    + extract_context_tags(event.get("context", {}))
                    + tokenize(actual_option.option_text)
                )
            )
            self.repository.add(
                MemoryEntry(
                    user_id=profile.user_id,
                    source_request_id=request.request_id,
                    source_feedback_id=feedback.feedback_id,
                    category=event["category"],
                    summary=_build_seed_summary(event, actual_option.option_text),
                    chosen_option_text=actual_option.option_text,
                    context_json=event.get("context", {}),
                    tags_json=combined_tags,
                    salience_score=1.0 if prediction.predicted_option_id == actual_option.option_id else 1.25,
                )
            )

        snapshot = self._rebuild_snapshot(profile.user_id)
        self.repository.add(snapshot)
        bundle = self.get_profile_bundle(profile.user_id)
        self.ensure_profile_card(profile.user_id, bundle=bundle)
        return self.get_profile_bundle(profile.user_id)

    def get_profile_bundle(self, user_id: str) -> UserProfileRead:
        """Return a profile together with the latest snapshot and counts."""

        profile = self.repository.get_user_profile(user_id)
        if profile is None:
            raise ValueError(f"User profile '{user_id}' was not found.")

        snapshot = self.repository.get_latest_snapshot(user_id)
        memories = self.repository.list_memories(user_id)
        history = self.repository.list_requests_for_user(user_id, limit=500)

        bundle = UserProfileRead(
            user_id=profile.user_id,
            display_name=profile.display_name,
            profile_summary=profile.profile_summary,
            personality_signals=profile.personality_signals_json,
            long_term_preferences=profile.long_term_preferences_json,
            onboarding_answers=profile.onboarding_answers_json,
            latest_snapshot=PreferenceSnapshotRead(
                snapshot_id=snapshot.snapshot_id,
                user_id=snapshot.user_id,
                summary=snapshot.summary,
                short_term_preference_notes=snapshot.short_term_preference_notes_json,
                drift_markers=snapshot.drift_markers_json,
                derived_statistics=snapshot.derived_statistics_json,
                created_at=snapshot.created_at,
            )
            if snapshot
            else None,
            memory_count=len(memories),
            history_count=len(history),
            profile_card_path=self._profile_card_path(user_id).as_posix() if self._profile_card_path(user_id).exists() else None,
        )
        return bundle

    def create_profile_from_onboarding(self, payload: UserOnboardingInput) -> UserProfileRead:
        """Create a new user profile from explicit onboarding answers."""

        if not payload.answers:
            raise ValueError("At least one onboarding answer is required.")
        user_id = payload.user_id or f"{slugify_display_name(payload.display_name)}-{uuid4().hex[:6]}"
        if self.repository.get_user_profile(user_id):
            raise ValueError(f"User profile '{user_id}' already exists.")

        source_answers = [answer.model_dump(mode="json") for answer in payload.answers]
        inferred = build_preference_profile(
            display_name=payload.display_name,
            source_answers=source_answers,
            free_texts=[answer.answer for answer in payload.answers],
        )
        self._create_profile_record(
            user_id=user_id,
            display_name=payload.display_name,
            profile_summary=inferred["profile_summary"],
            personality_signals=inferred["personality_signals"],
            long_term_preferences=inferred["long_term_preferences"],
            onboarding_answers=inferred["onboarding_answers"],
            memory_seeds=inferred["memory_seeds"],
        )
        bundle = self.get_profile_bundle(user_id)
        self.ensure_profile_card(user_id, bundle=bundle)
        return self.get_profile_bundle(user_id)

    def import_profile_from_chatgpt_export(
        self,
        display_name: str,
        file_bytes: bytes,
        filename: str,
        user_id: str | None = None,
    ) -> ChatGPTImportResponse:
        """Create a user profile from an uploaded ChatGPT export file."""

        resolved_user_id = user_id or f"{slugify_display_name(display_name)}-{uuid4().hex[:6]}"
        if self.repository.get_user_profile(resolved_user_id):
            raise ValueError(f"User profile '{resolved_user_id}' already exists.")

        payloads = load_chatgpt_export(file_bytes=file_bytes, filename=filename)
        inferred = build_profile_from_chatgpt_export(display_name=display_name, imported_payloads=payloads)
        self._create_profile_record(
            user_id=resolved_user_id,
            display_name=display_name,
            profile_summary=inferred["profile_summary"],
            personality_signals=inferred["personality_signals"],
            long_term_preferences=inferred["long_term_preferences"],
            onboarding_answers=inferred["onboarding_answers"],
            memory_seeds=inferred["memory_seeds"],
        )
        bundle = self.get_profile_bundle(resolved_user_id)
        self.ensure_profile_card(resolved_user_id, bundle=bundle)
        return ChatGPTImportResponse(
            user_profile=self.get_profile_bundle(resolved_user_id),
            import_stats=inferred["import_stats"],
        )

    def ensure_profile_card(self, user_id: str, bundle: UserProfileRead | None = None) -> str:
        """Render and persist the user's Markdown profile card."""

        profile_bundle = bundle or self.get_profile_bundle(user_id)
        recent_memories = self.repository.list_memories(user_id, limit=5)
        seen_summaries: set[str] = set()
        recent_memory_payload: list[dict] = []
        for memory in recent_memories:
            if memory.summary in seen_summaries:
                continue
            seen_summaries.add(memory.summary)
            recent_memory_payload.append(
                {
                    "category": memory.category,
                    "summary": memory.summary,
                }
            )
        content = self.card_renderer.render(
            profile_bundle,
            recent_memories=recent_memory_payload,
        )
        path = write_profile_card(self.settings.profile_card_dir, user_id, content)
        return path.as_posix()

    def get_profile_card(self, user_id: str) -> dict:
        """Return the current Markdown profile card and file path."""

        path = self.ensure_profile_card(user_id)
        return {
            "user_id": user_id,
            "path": path,
            "content": self._profile_card_path(user_id).read_text(encoding="utf-8"),
        }

    def _profile_card_path(self, user_id: str):
        return self.settings.profile_card_dir / f"{user_id}.md"

    def _create_profile_record(
        self,
        user_id: str,
        display_name: str,
        profile_summary: str,
        personality_signals: dict,
        long_term_preferences: dict,
        onboarding_answers: list,
        memory_seeds: list[PreferenceSeed],
    ) -> None:
        profile = UserProfile(
            user_id=user_id,
            display_name=display_name,
            profile_summary=profile_summary,
            personality_signals_json=personality_signals,
            long_term_preferences_json=long_term_preferences,
            onboarding_answers_json=onboarding_answers,
        )
        self.repository.add(profile)

        for index, seed in enumerate(memory_seeds):
            request = self.repository.add(
                DecisionRequest(
                    user_id=user_id,
                    prompt=f"Imported preference seed {index + 1}",
                    category=seed.category,
                    context_json=seed.context,
                )
            )
            self.repository.add(
                MemoryEntry(
                    user_id=user_id,
                    source_request_id=request.request_id,
                    category=seed.category,
                    summary=seed.summary,
                    chosen_option_text=seed.chosen_option_text,
                    context_json=seed.context,
                    tags_json=seed.tags,
                    salience_score=0.85,
                )
            )

        snapshot = self._rebuild_snapshot(user_id)
        self.repository.add(snapshot)

    def _rebuild_snapshot(self, user_id: str) -> PreferenceSnapshot:
        memories = self.repository.list_memories(user_id, limit=100)
        if not memories:
            return PreferenceSnapshot(
                user_id=user_id,
                summary="No decision history has been recorded yet.",
                short_term_preference_notes_json=[],
                drift_markers_json=[],
                derived_statistics_json={},
            )

        recent_memories = memories[:5]
        category_counts: dict[str, int] = {}
        recent_tag_counts: dict[str, int] = {}
        recent_option_counts: dict[str, dict[str, int]] = {}
        all_tag_counts: dict[str, int] = {}

        for memory in memories:
            category_counts[memory.category] = category_counts.get(memory.category, 0) + 1
            for tag in memory.tags_json:
                all_tag_counts[tag] = all_tag_counts.get(tag, 0) + 1

        for memory in recent_memories:
            recent_option_counts.setdefault(memory.category, {})
            recent_option_counts[memory.category][memory.chosen_option_text] = (
                recent_option_counts[memory.category].get(memory.chosen_option_text, 0) + 1
            )
            for tag in memory.tags_json:
                if _is_meaningful_snapshot_tag(tag):
                    recent_tag_counts[tag] = recent_tag_counts.get(tag, 0) + 1

        top_recent_tags = [tag for tag, _ in sorted(recent_tag_counts.items(), key=lambda item: item[1], reverse=True)[:4]]
        overall_top_tag = next(iter(sorted(all_tag_counts.items(), key=lambda item: item[1], reverse=True)), None)
        recent_top_tag = next(iter(sorted(recent_tag_counts.items(), key=lambda item: item[1], reverse=True)), None)

        drift_markers: list[str] = []
        if overall_top_tag and recent_top_tag and overall_top_tag[0] != recent_top_tag[0]:
            drift_markers.append(
                f"Recent choices emphasize '{recent_top_tag[0]}' more than the longer-term pattern '{overall_top_tag[0]}'."
            )

        summary_parts = [
            f"Recent decisions show the strongest activity in {max(category_counts, key=category_counts.get)}.",
        ]
        if top_recent_tags:
            summary_parts.append(f"Short-term signals currently emphasize {', '.join(top_recent_tags[:3])}.")

        return PreferenceSnapshot(
            user_id=user_id,
            summary=" ".join(summary_parts),
            short_term_preference_notes_json=[
                f"Recent choices repeatedly include '{tag}'." for tag in top_recent_tags[:3]
            ],
            drift_markers_json=drift_markers,
            derived_statistics_json={
                "category_counts": category_counts,
                "recent_option_counts": recent_option_counts,
                "recent_tags": top_recent_tags,
            },
        )
