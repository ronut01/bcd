"""Profile and bootstrap services."""

from __future__ import annotations

from sqlmodel import Session

from bcd.config import Settings, get_settings
from bcd.profile.sample_data import load_json
from bcd.profile.schemas import PreferenceSnapshotRead, UserProfileRead
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


class ProfileService:
    """Handles profile initialization and retrieval."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repository = BCDRepository(session)

    def bootstrap_sample_profile(self) -> UserProfileRead:
        """Create the sample profile and seed history if it does not exist."""

        sample_profile = load_json(self.settings.sample_profile_path)
        existing = self.repository.get_user_profile(sample_profile["user_id"])
        if existing:
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
        return self.get_profile_bundle(profile.user_id)

    def get_profile_bundle(self, user_id: str) -> UserProfileRead:
        """Return a profile together with the latest snapshot and counts."""

        profile = self.repository.get_user_profile(user_id)
        if profile is None:
            raise ValueError(f"User profile '{user_id}' was not found.")

        snapshot = self.repository.get_latest_snapshot(user_id)
        memories = self.repository.list_memories(user_id)
        history = self.repository.list_requests_for_user(user_id, limit=500)

        return UserProfileRead(
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
        )

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
