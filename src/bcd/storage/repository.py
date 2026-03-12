"""Repository helpers used by the service layer."""

from __future__ import annotations

from collections.abc import Sequence

from sqlmodel import Session, select

from bcd.storage.models import (
    ActualChoiceFeedback,
    DecisionOption,
    DecisionRequest,
    MemoryEntry,
    PreferenceSnapshot,
    PredictionReflection,
    PredictionResult,
    ProfileSignal,
    RecentStateNote,
    UserProfile,
)


class BCDRepository:
    """Thin repository around a SQLModel session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, model):
        self.session.add(model)
        self.session.flush()
        self.session.refresh(model)
        return model

    def add_all(self, models: Sequence):
        for model in models:
            self.session.add(model)
        self.session.flush()
        for model in models:
            self.session.refresh(model)
        return list(models)

    def get_user_profile(self, user_id: str) -> UserProfile | None:
        return self.session.get(UserProfile, user_id)

    def list_user_profiles(self) -> list[UserProfile]:
        return list(self.session.exec(select(UserProfile)))

    def get_latest_snapshot(self, user_id: str) -> PreferenceSnapshot | None:
        statement = (
            select(PreferenceSnapshot)
            .where(PreferenceSnapshot.user_id == user_id)
            .order_by(PreferenceSnapshot.created_at.desc())
        )
        return self.session.exec(statement).first()

    def list_snapshots(self, user_id: str) -> list[PreferenceSnapshot]:
        statement = (
            select(PreferenceSnapshot)
            .where(PreferenceSnapshot.user_id == user_id)
            .order_by(PreferenceSnapshot.created_at.desc())
        )
        return list(self.session.exec(statement))

    def get_request(self, request_id: str) -> DecisionRequest | None:
        return self.session.get(DecisionRequest, request_id)

    def list_requests_for_user(self, user_id: str, limit: int = 50) -> list[DecisionRequest]:
        statement = (
            select(DecisionRequest)
            .where(DecisionRequest.user_id == user_id)
            .order_by(DecisionRequest.created_at.desc())
            .limit(limit)
        )
        return list(self.session.exec(statement))

    def list_options_for_request(self, request_id: str) -> list[DecisionOption]:
        statement = select(DecisionOption).where(DecisionOption.request_id == request_id).order_by(DecisionOption.position)
        return list(self.session.exec(statement))

    def get_prediction_by_request(self, request_id: str) -> PredictionResult | None:
        statement = (
            select(PredictionResult)
            .where(PredictionResult.request_id == request_id)
            .order_by(PredictionResult.created_at.desc())
        )
        return self.session.exec(statement).first()

    def get_feedback_by_request(self, request_id: str) -> ActualChoiceFeedback | None:
        statement = (
            select(ActualChoiceFeedback)
            .where(ActualChoiceFeedback.request_id == request_id)
            .order_by(ActualChoiceFeedback.created_at.desc())
        )
        return self.session.exec(statement).first()

    def list_feedback_for_user_requests(self, request_ids: list[str]) -> list[ActualChoiceFeedback]:
        if not request_ids:
            return []
        statement = select(ActualChoiceFeedback).where(ActualChoiceFeedback.request_id.in_(request_ids))
        return list(self.session.exec(statement))

    def list_predictions_for_requests(self, request_ids: list[str]) -> list[PredictionResult]:
        if not request_ids:
            return []
        statement = select(PredictionResult).where(PredictionResult.request_id.in_(request_ids))
        return list(self.session.exec(statement))

    def list_memories(self, user_id: str, limit: int = 100) -> list[MemoryEntry]:
        statement = (
            select(MemoryEntry)
            .where(MemoryEntry.user_id == user_id)
            .order_by(MemoryEntry.created_at.desc())
            .limit(limit)
        )
        return list(self.session.exec(statement))

    def list_profile_signals(self, user_id: str, limit: int = 200) -> list[ProfileSignal]:
        statement = (
            select(ProfileSignal)
            .where(ProfileSignal.user_id == user_id)
            .order_by(ProfileSignal.created_at.desc())
            .limit(limit)
        )
        return list(self.session.exec(statement))

    def get_profile_signal(self, signal_id: str) -> ProfileSignal | None:
        return self.session.get(ProfileSignal, signal_id)

    def list_reflections_for_requests(self, request_ids: list[str]) -> list[PredictionReflection]:
        if not request_ids:
            return []
        statement = select(PredictionReflection).where(PredictionReflection.request_id.in_(request_ids))
        return list(self.session.exec(statement))

    def list_recent_state_notes(self, user_id: str, limit: int = 20) -> list[RecentStateNote]:
        statement = (
            select(RecentStateNote)
            .where(RecentStateNote.user_id == user_id)
            .where(RecentStateNote.active.is_(True))
            .order_by(RecentStateNote.created_at.desc())
            .limit(limit)
        )
        return list(self.session.exec(statement))

    def get_recent_state_note(self, note_id: str) -> RecentStateNote | None:
        return self.session.get(RecentStateNote, note_id)
