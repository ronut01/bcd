"""Profile and bootstrap services."""

from __future__ import annotations

from uuid import uuid4

from sqlmodel import Session

from bcd.config import Settings, get_settings
from bcd.profile.card import ProfileCardRenderer, write_profile_card, write_state_card
from bcd.profile.inference import (
    PreferenceSeed,
    build_profile_from_structured_onboarding,
    build_profile_from_chatgpt_export,
    get_structured_questionnaire,
    load_chatgpt_export,
    slugify_display_name,
)
from bcd.profile.sample_data import load_json
from bcd.profile.schemas import (
    ChatGPTImportResponse,
    OnboardingQuestionOptionRead,
    OnboardingQuestionRead,
    OnboardingQuestionnaireRead,
    OnboardingPreviewRead,
    ProfileSignalRead,
    ProfileSignalReviewInput,
    ProfileSignalReviewResponse,
    PreferenceSnapshotRead,
    RecentStateNoteInput,
    RecentStateNoteRead,
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
    ProfileSignal,
    RecentStateNote,
    UserProfile,
)
from bcd.storage.repository import BCDRepository
from bcd.utils.time import utc_now
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


def _to_signal_read(signal: ProfileSignal) -> ProfileSignalRead:
    return ProfileSignalRead(
        signal_id=signal.signal_id,
        user_id=signal.user_id,
        source_type=signal.source_type,
        signal_kind=signal.signal_kind,
        signal_name=signal.signal_name,
        proposed_value=signal.proposed_value_json,
        current_value=signal.current_value_json,
        evidence_text=signal.evidence_text,
        review_note=signal.review_note,
        status=signal.status,  # type: ignore[arg-type]
        created_at=signal.created_at,
        updated_at=signal.updated_at,
    )


def _to_recent_state_note_read(note: RecentStateNote) -> RecentStateNoteRead:
    return RecentStateNoteRead(
        note_id=note.note_id,
        user_id=note.user_id,
        note_text=note.note_text,
        tags=note.tags_json,
        active=note.active,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


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
            existing_signals = self.repository.list_profile_signals(existing.user_id, limit=10)
            if not existing_signals:
                self.repository.add_all(
                    self._build_profile_signal_rows(
                        user_id=existing.user_id,
                        personality_signals=existing.personality_signals_json,
                        long_term_preferences=existing.long_term_preferences_json,
                        source_type="sample_profile",
                        evidence_prefix="Backfilled from the bundled sample profile.",
                        status="accepted",
                    )
                )
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
        self.repository.add_all(
            self._build_profile_signal_rows(
                user_id=profile.user_id,
                personality_signals=sample_profile["personality_signals"],
                long_term_preferences=sample_profile["long_term_preferences"],
                source_type="sample_profile",
                evidence_prefix="Loaded from the bundled sample profile.",
                status="accepted",
            )
        )

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
        signals = self.repository.list_profile_signals(user_id, limit=500)

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
            signal_count=len(signals),
            pending_signal_count=sum(1 for signal in signals if signal.status == "pending"),
        )
        return bundle

    def create_profile_from_onboarding(self, payload: UserOnboardingInput) -> UserProfileRead:
        """Create a new user profile from explicit onboarding answers."""

        if not payload.responses:
            raise ValueError("At least one onboarding response is required.")
        user_id = payload.user_id or f"{slugify_display_name(payload.display_name)}-{uuid4().hex[:6]}"
        if self.repository.get_user_profile(user_id):
            raise ValueError(f"User profile '{user_id}' already exists.")

        inferred = build_profile_from_structured_onboarding(
            display_name=payload.display_name,
            mbti=payload.mbti,
            responses=[response.model_dump(mode="json") for response in payload.responses],
        )
        self._create_profile_record(
            user_id=user_id,
            display_name=payload.display_name,
            profile_summary=inferred["profile_summary"],
            personality_signals=inferred["personality_signals"],
            long_term_preferences=inferred["long_term_preferences"],
            onboarding_answers=inferred["onboarding_answers"],
            memory_seeds=inferred["memory_seeds"],
            signal_source_type="structured_onboarding",
            signal_status="accepted",
            signal_evidence_prefix="Derived from the user's explicit structured onboarding answers.",
        )
        bundle = self.get_profile_bundle(user_id)
        self.ensure_profile_card(user_id, bundle=bundle)
        return self.get_profile_bundle(user_id)

    def preview_onboarding_profile(self, payload: UserOnboardingInput) -> OnboardingPreviewRead:
        """Preview the structured profile that onboarding answers would produce."""

        if not payload.responses:
            raise ValueError("At least one onboarding response is required.")
        inferred = build_profile_from_structured_onboarding(
            display_name=payload.display_name,
            mbti=payload.mbti,
            responses=[response.model_dump(mode="json") for response in payload.responses],
        )
        return OnboardingPreviewRead(
            display_name=payload.display_name,
            profile_summary=inferred["profile_summary"],
            personality_signals=inferred["personality_signals"],
            long_term_preferences=inferred["long_term_preferences"],
        )

    def get_onboarding_questionnaire(self) -> OnboardingQuestionnaireRead:
        """Return the structured onboarding questionnaire."""

        raw = get_structured_questionnaire()
        return OnboardingQuestionnaireRead(
            version=raw["version"],
            mbti_options=raw["mbti_options"],
            questions=[
                OnboardingQuestionRead(
                    question_id=question["question_id"],
                    title=question["title"],
                    prompt=question["prompt"],
                    options=[
                        OnboardingQuestionOptionRead(**option)
                        for option in question["options"]
                    ],
                )
                for question in raw["questions"]
            ],
        )

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
            signal_source_type="chatgpt_export",
            signal_status="pending",
            signal_evidence_prefix="Inferred from the uploaded ChatGPT export and awaiting user review.",
        )
        bundle = self.get_profile_bundle(resolved_user_id)
        self.ensure_profile_card(resolved_user_id, bundle=bundle)
        return ChatGPTImportResponse(
            user_profile=self.get_profile_bundle(resolved_user_id),
            import_stats=inferred["import_stats"],
        )

    def get_profile_signals(self, user_id: str) -> list[ProfileSignalRead]:
        """Return stored profile signals for review and correction."""

        profile = self.repository.get_user_profile(user_id)
        if profile is None:
            raise ValueError(f"User profile '{user_id}' was not found.")
        signals = self.repository.list_profile_signals(user_id, limit=500)
        if not signals:
            self.repository.add_all(
                self._build_profile_signal_rows(
                    user_id=user_id,
                    personality_signals=profile.personality_signals_json,
                    long_term_preferences=profile.long_term_preferences_json,
                    source_type="backfill",
                    evidence_prefix="Backfilled from the current stored profile state.",
                    status="accepted",
                )
            )
            signals = self.repository.list_profile_signals(user_id, limit=500)
        status_order = {"pending": 0, "edited": 1, "accepted": 2, "rejected": 3}
        signals.sort(key=lambda item: (status_order.get(item.status, 9), item.created_at))
        return [_to_signal_read(signal) for signal in signals]

    def list_recent_state_notes(self, user_id: str) -> list[RecentStateNoteRead]:
        """Return user-authored recent state notes."""

        if self.repository.get_user_profile(user_id) is None:
            raise ValueError(f"User profile '{user_id}' was not found.")
        notes = self.repository.list_recent_state_notes(user_id, limit=50)
        return [_to_recent_state_note_read(note) for note in notes]

    def add_recent_state_note(self, user_id: str, payload: RecentStateNoteInput) -> RecentStateNoteRead:
        """Store a manual recent-state note used by cards and ranking."""

        if self.repository.get_user_profile(user_id) is None:
            raise ValueError(f"User profile '{user_id}' was not found.")
        if not payload.note_text.strip():
            raise ValueError("Recent state notes cannot be empty.")

        note = self.repository.add(
            RecentStateNote(
                user_id=user_id,
                note_text=payload.note_text.strip(),
                tags_json=payload.tags,
            )
        )
        self.ensure_profile_card(user_id)
        return _to_recent_state_note_read(note)

    def delete_recent_state_note(self, user_id: str, note_id: str) -> dict:
        """Deactivate a manual recent-state note."""

        note = self.repository.get_recent_state_note(note_id)
        if note is None or note.user_id != user_id:
            raise ValueError(f"Recent state note '{note_id}' was not found for user '{user_id}'.")

        note.active = False
        note.updated_at = utc_now()
        self.session.add(note)
        self.session.flush()
        self.session.refresh(note)
        self.ensure_profile_card(user_id)
        return {"note_id": note.note_id, "deleted": True}

    def review_profile_signal(
        self,
        user_id: str,
        signal_id: str,
        payload: ProfileSignalReviewInput,
    ) -> ProfileSignalReviewResponse:
        """Review a proposed profile signal and rebuild the stable profile."""

        signal = self.repository.get_profile_signal(signal_id)
        if signal is None or signal.user_id != user_id:
            raise ValueError(f"Profile signal '{signal_id}' was not found for user '{user_id}'.")

        if payload.action == "edit" and not payload.edited_value:
            raise ValueError("An edited_value payload is required when action='edit'.")

        if payload.action == "accept":
            signal.status = "accepted"
            signal.current_value_json = signal.proposed_value_json
        elif payload.action == "reject":
            signal.status = "rejected"
            signal.current_value_json = None
        else:
            signal.status = "edited"
            signal.current_value_json = payload.edited_value

        signal.review_note = payload.review_note
        signal.updated_at = utc_now()
        self.session.add(signal)
        self.session.flush()
        self.session.refresh(signal)

        self._rebuild_profile_from_signals(user_id)
        bundle = self.get_profile_bundle(user_id)
        self.ensure_profile_card(user_id, bundle=bundle)
        return ProfileSignalReviewResponse(signal=_to_signal_read(signal), user_profile=self.get_profile_bundle(user_id))

    def ensure_profile_card(self, user_id: str, bundle: UserProfileRead | None = None) -> str:
        """Render and persist the user's Markdown profile card."""

        profile_bundle = bundle or self.get_profile_bundle(user_id)
        recent_state_payload = self.get_recent_state_payload(user_id)
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
        stable_content, recent_content, combined_content = self.card_renderer.render(
            profile_bundle,
            recent_memories=recent_memory_payload,
            manual_recent_notes=recent_state_payload["manual_notes"],
            feedback_shift_notes=recent_state_payload["feedback_shift_notes"],
        )
        path = write_profile_card(self.settings.profile_card_dir, user_id, combined_content)
        write_state_card(self.settings.profile_card_dir, user_id, recent_content)
        return path.as_posix()

    def get_profile_card(self, user_id: str) -> dict:
        """Return the current Markdown profile card and file path."""

        path = self.ensure_profile_card(user_id)
        bundle = self.get_profile_bundle(user_id)
        recent_state_payload = self.get_recent_state_payload(user_id)
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
        stable_content, recent_content, combined_content = self.card_renderer.render(
            bundle,
            recent_memory_payload,
            manual_recent_notes=recent_state_payload["manual_notes"],
            feedback_shift_notes=recent_state_payload["feedback_shift_notes"],
        )
        return {
            "user_id": user_id,
            "path": path,
            "content": combined_content,
            "stable_content": stable_content,
            "recent_content": recent_content,
            "stable_summary": {
                "signal_count": bundle.signal_count,
                "pending_signal_count": bundle.pending_signal_count,
                "decision_style": bundle.personality_signals.get("decision_style", []),
                "values": bundle.personality_signals.get("values", []),
            },
            "recent_summary": recent_state_payload,
        }

    def get_recent_state_payload(self, user_id: str) -> dict:
        """Return a structured view of recent state separate from the stable profile."""

        snapshot = self.repository.get_latest_snapshot(user_id)
        manual_notes = [note.note_text for note in self.repository.list_recent_state_notes(user_id, limit=5)]
        snapshot_notes = snapshot.short_term_preference_notes_json if snapshot else []
        drift_markers = snapshot.drift_markers_json if snapshot else []
        feedback_shift_notes = []
        if snapshot:
            feedback_shift_notes = snapshot.derived_statistics_json.get("recent_shift_notes", [])
        return {
            "manual_notes": manual_notes,
            "snapshot_notes": snapshot_notes,
            "drift_markers": drift_markers,
            "feedback_shift_notes": feedback_shift_notes,
            "combined_notes": list(dict.fromkeys(manual_notes + snapshot_notes + feedback_shift_notes)),
        }

    def _profile_card_path(self, user_id: str):
        return self.settings.profile_card_dir / f"{user_id}.md"

    def _build_profile_signal_rows(
        self,
        user_id: str,
        personality_signals: dict,
        long_term_preferences: dict,
        source_type: str,
        evidence_prefix: str,
        status: str,
    ) -> list[ProfileSignal]:
        rows: list[ProfileSignal] = []

        mbti = personality_signals.get("mbti")
        if isinstance(mbti, str) and mbti:
            rows.append(
                ProfileSignal(
                    user_id=user_id,
                    source_type=source_type,
                    signal_kind="mbti",
                    signal_name="mbti",
                    proposed_value_json={"mbti": mbti},
                    current_value_json={"mbti": mbti},
                    evidence_text=f"{evidence_prefix} MBTI was set to '{mbti}'.",
                    status=status,
                )
            )

        for style in personality_signals.get("decision_style", []):
            rows.append(
                ProfileSignal(
                    user_id=user_id,
                    source_type=source_type,
                    signal_kind="decision_style",
                    signal_name=str(style),
                    proposed_value_json={"label": str(style)},
                    current_value_json={"label": str(style)},
                    evidence_text=f"{evidence_prefix} Decision style emphasized '{style}'.",
                    status=status,
                )
            )

        for value in personality_signals.get("values", []):
            rows.append(
                ProfileSignal(
                    user_id=user_id,
                    source_type=source_type,
                    signal_kind="value",
                    signal_name=str(value),
                    proposed_value_json={"label": str(value)},
                    current_value_json={"label": str(value)},
                    evidence_text=f"{evidence_prefix} Value preference emphasized '{value}'.",
                    status=status,
                )
            )

        for note in personality_signals.get("behavior_notes", []):
            rows.append(
                ProfileSignal(
                    user_id=user_id,
                    source_type=source_type,
                    signal_kind="behavior_note",
                    signal_name=str(note)[:80],
                    proposed_value_json={"label": str(note)},
                    current_value_json={"label": str(note)},
                    evidence_text=f"{evidence_prefix} Behavior note captured from the source profile.",
                    status=status,
                )
            )

        for category, bundle in long_term_preferences.get("category_preferences", {}).items():
            rows.append(
                ProfileSignal(
                    user_id=user_id,
                    source_type=source_type,
                    signal_kind="category_preference",
                    signal_name=str(category),
                    proposed_value_json={
                        "category": category,
                        "preferred_keywords": bundle.get("preferred_keywords", []),
                        "avoided_keywords": bundle.get("avoided_keywords", []),
                    },
                    current_value_json={
                        "category": category,
                        "preferred_keywords": bundle.get("preferred_keywords", []),
                        "avoided_keywords": bundle.get("avoided_keywords", []),
                    },
                    evidence_text=f"{evidence_prefix} Category preference was derived for '{category}'.",
                    status=status,
                )
            )

        for context_key, values in long_term_preferences.get("context_preferences", {}).items():
            rows.append(
                ProfileSignal(
                    user_id=user_id,
                    source_type=source_type,
                    signal_kind="context_preference",
                    signal_name=str(context_key),
                    proposed_value_json={"context_key": context_key, "values": list(values)},
                    current_value_json={"context_key": context_key, "values": list(values)},
                    evidence_text=f"{evidence_prefix} Context preference was derived for '{context_key}'.",
                    status=status,
                )
            )

        return rows

    @staticmethod
    def _effective_signal_payload(signal: ProfileSignal) -> dict | None:
        if signal.status == "rejected":
            return None
        return signal.current_value_json or signal.proposed_value_json

    def _build_profile_summary(
        self,
        display_name: str,
        mbti: str | None,
        decision_styles: list[str],
        values: list[str],
        category_preferences: dict[str, dict[str, list[str]]],
        pending_signal_count: int,
    ) -> str:
        style_text = ", ".join(decision_styles[:3]) if decision_styles else "context-sensitive, practical"
        value_text = ", ".join(values[:3]) if values else "comfort, reliability"
        category_text = ", ".join(list(category_preferences)[:3]) if category_preferences else "general choices"
        summary = f"{display_name} has a profile built from structured and reviewed preference signals."
        if mbti:
            summary += f" MBTI prior: {mbti}."
        summary += f" Stable tendencies emphasize {style_text}."
        summary += f" Stronger long-term preference activity appears around {category_text}."
        summary += f" The user tends to optimize for {value_text}."
        if pending_signal_count:
            summary += f" {pending_signal_count} imported signal(s) are still awaiting review."
        return summary

    def _rebuild_profile_from_signals(self, user_id: str) -> UserProfile:
        profile = self.repository.get_user_profile(user_id)
        if profile is None:
            raise ValueError(f"User profile '{user_id}' was not found.")

        signals = self.repository.list_profile_signals(user_id, limit=500)
        decision_styles: list[str] = []
        values: list[str] = []
        behavior_notes: list[str] = []
        category_preferences: dict[str, dict[str, set[str]]] = {}
        context_preferences: dict[str, set[str]] = {}
        mbti: str | None = None

        for signal in signals:
            payload = self._effective_signal_payload(signal)
            if not payload:
                continue
            if signal.signal_kind == "mbti":
                mbti = payload.get("mbti", mbti)
            elif signal.signal_kind == "decision_style":
                label = payload.get("label")
                if label:
                    decision_styles.append(str(label))
            elif signal.signal_kind == "value":
                label = payload.get("label")
                if label:
                    values.append(str(label))
            elif signal.signal_kind == "behavior_note":
                label = payload.get("label")
                if label:
                    behavior_notes.append(str(label))
            elif signal.signal_kind == "category_preference":
                category = payload.get("category")
                if not category:
                    continue
                bundle = category_preferences.setdefault(
                    str(category),
                    {"preferred_keywords": set(), "avoided_keywords": set()},
                )
                bundle["preferred_keywords"].update(payload.get("preferred_keywords", []))
                bundle["avoided_keywords"].update(payload.get("avoided_keywords", []))
            elif signal.signal_kind == "context_preference":
                context_key = payload.get("context_key")
                if not context_key:
                    continue
                bucket = context_preferences.setdefault(str(context_key), set())
                bucket.update(payload.get("values", []))

        dedup_decision_styles = list(dict.fromkeys(decision_styles))[:6]
        dedup_values = list(dict.fromkeys(values))[:6]
        dedup_behavior_notes = list(dict.fromkeys(behavior_notes))[:6]
        category_payload = {
            category: {
                "preferred_keywords": sorted(bundle["preferred_keywords"]),
                "avoided_keywords": sorted(bundle["avoided_keywords"]),
            }
            for category, bundle in category_preferences.items()
            if bundle["preferred_keywords"] or bundle["avoided_keywords"]
        }
        context_payload = {
            key: sorted(values_set)
            for key, values_set in context_preferences.items()
            if values_set
        }
        pending_signal_count = sum(1 for signal in signals if signal.status == "pending")

        profile.personality_signals_json = {
            **({"mbti": mbti} if mbti else {}),
            "decision_style": dedup_decision_styles or ["context-sensitive", "practical"],
            "values": dedup_values or ["comfort", "reliability"],
            "behavior_notes": dedup_behavior_notes,
        }
        profile.long_term_preferences_json = {
            "category_preferences": category_payload,
            "context_preferences": context_payload,
        }
        profile.profile_summary = self._build_profile_summary(
            display_name=profile.display_name,
            mbti=mbti,
            decision_styles=dedup_decision_styles,
            values=dedup_values,
            category_preferences=category_payload,
            pending_signal_count=pending_signal_count,
        )
        profile.updated_at = utc_now()
        self.session.add(profile)
        self.session.flush()
        self.session.refresh(profile)
        return profile

    def _create_profile_record(
        self,
        user_id: str,
        display_name: str,
        profile_summary: str,
        personality_signals: dict,
        long_term_preferences: dict,
        onboarding_answers: list,
        memory_seeds: list[PreferenceSeed],
        signal_source_type: str,
        signal_status: str,
        signal_evidence_prefix: str,
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
        self.repository.add_all(
            self._build_profile_signal_rows(
                user_id=user_id,
                personality_signals=personality_signals,
                long_term_preferences=long_term_preferences,
                source_type=signal_source_type,
                evidence_prefix=signal_evidence_prefix,
                status=signal_status,
            )
        )

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
        recent_requests = self.repository.list_requests_for_user(user_id, limit=20)
        request_ids = [request.request_id for request in recent_requests]
        recent_reflections = self.repository.list_reflections_for_requests(request_ids)
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
        recent_shift_notes: list[str] = []
        recent_failure_reasons: dict[str, int] = {}

        for memory in memories:
            category_counts[memory.category] = category_counts.get(memory.category, 0) + 1
            for tag in memory.tags_json:
                all_tag_counts[tag] = all_tag_counts.get(tag, 0) + 1

        for reflection in recent_reflections[:5]:
            if reflection.preference_shift_note:
                recent_shift_notes.append(reflection.preference_shift_note)
            for reason in reflection.failure_reasons_json:
                recent_failure_reasons[reason] = recent_failure_reasons.get(reason, 0) + 1

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
        if recent_shift_notes:
            drift_markers.append("Recent feedback suggests at least one temporary preference shift is active.")

        summary_parts = [
            f"Recent decisions show the strongest activity in {max(category_counts, key=category_counts.get)}.",
        ]
        if top_recent_tags:
            summary_parts.append(f"Short-term signals currently emphasize {', '.join(top_recent_tags[:3])}.")
        if recent_shift_notes:
            summary_parts.append("Feedback-derived shift markers are influencing the short-term state.")

        return PreferenceSnapshot(
            user_id=user_id,
            summary=" ".join(summary_parts),
            short_term_preference_notes_json=[
                f"Recent choices repeatedly include '{tag}'." for tag in top_recent_tags[:3]
            ] + [f"Recent feedback shift: {note}" for note in recent_shift_notes[:2]],
            drift_markers_json=drift_markers,
            derived_statistics_json={
                "category_counts": category_counts,
                "recent_option_counts": recent_option_counts,
                "recent_tags": top_recent_tags,
                "recent_shift_notes": recent_shift_notes[:5],
                "recent_failure_reasons": recent_failure_reasons,
            },
        )
