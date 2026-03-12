"""SQLModel table definitions for the bcd MVP."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel

from bcd.utils.time import utc_now


def generate_id() -> str:
    """Generate a compact opaque identifier."""

    return uuid4().hex


class UserProfile(SQLModel, table=True):
    user_id: str = Field(default_factory=generate_id, primary_key=True)
    display_name: str
    profile_summary: str = Field(sa_column=Column(Text))
    personality_signals_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    long_term_preferences_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    onboarding_answers_json: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DecisionRequest(SQLModel, table=True):
    request_id: str = Field(default_factory=generate_id, primary_key=True)
    user_id: str = Field(index=True, foreign_key="userprofile.user_id")
    prompt: str = Field(sa_column=Column(Text))
    category: str = Field(index=True)
    context_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now, index=True)


class DecisionOption(SQLModel, table=True):
    option_id: str = Field(default_factory=generate_id, primary_key=True)
    request_id: str = Field(index=True, foreign_key="decisionrequest.request_id")
    option_text: str
    option_metadata_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    position: int


class PredictionResult(SQLModel, table=True):
    prediction_id: str = Field(default_factory=generate_id, primary_key=True)
    request_id: str = Field(index=True, foreign_key="decisionrequest.request_id")
    predicted_option_id: str = Field(foreign_key="decisionoption.option_id")
    ranked_option_ids_json: list = Field(default_factory=list, sa_column=Column(JSON))
    score_breakdown_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    confidence_by_option_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    explanation: str = Field(sa_column=Column(Text))
    strategy: str
    retrieved_memory_ids_json: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now, index=True)


class ActualChoiceFeedback(SQLModel, table=True):
    feedback_id: str = Field(default_factory=generate_id, primary_key=True)
    request_id: str = Field(index=True, foreign_key="decisionrequest.request_id")
    actual_option_id: str = Field(foreign_key="decisionoption.option_id")
    reason_text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    reason_tags_json: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now, index=True)


class MemoryEntry(SQLModel, table=True):
    memory_id: str = Field(default_factory=generate_id, primary_key=True)
    user_id: str = Field(index=True, foreign_key="userprofile.user_id")
    source_request_id: str = Field(index=True, foreign_key="decisionrequest.request_id")
    source_feedback_id: str | None = Field(default=None, foreign_key="actualchoicefeedback.feedback_id")
    category: str = Field(index=True)
    summary: str = Field(sa_column=Column(Text))
    chosen_option_text: str
    context_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    tags_json: list = Field(default_factory=list, sa_column=Column(JSON))
    salience_score: float = 1.0
    embedding_json: list | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=utc_now, index=True)


class PreferenceSnapshot(SQLModel, table=True):
    snapshot_id: str = Field(default_factory=generate_id, primary_key=True)
    user_id: str = Field(index=True, foreign_key="userprofile.user_id")
    summary: str = Field(sa_column=Column(Text))
    short_term_preference_notes_json: list = Field(default_factory=list, sa_column=Column(JSON))
    drift_markers_json: list = Field(default_factory=list, sa_column=Column(JSON))
    derived_statistics_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now, index=True)


class ProfileSignal(SQLModel, table=True):
    signal_id: str = Field(default_factory=generate_id, primary_key=True)
    user_id: str = Field(index=True, foreign_key="userprofile.user_id")
    source_type: str = Field(index=True)
    signal_kind: str = Field(index=True)
    signal_name: str = Field(index=True)
    proposed_value_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    current_value_json: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    evidence_text: str = Field(sa_column=Column(Text))
    review_note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    status: str = Field(default="pending", index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now, index=True)


class PredictionReflection(SQLModel, table=True):
    reflection_id: str = Field(default_factory=generate_id, primary_key=True)
    request_id: str = Field(index=True, foreign_key="decisionrequest.request_id")
    prediction_id: str | None = Field(default=None, foreign_key="predictionresult.prediction_id")
    actual_option_id: str = Field(foreign_key="decisionoption.option_id")
    predicted_option_id: str | None = Field(default=None, foreign_key="decisionoption.option_id")
    outcome: str = Field(index=True)
    failure_reasons_json: list = Field(default_factory=list, sa_column=Column(JSON))
    context_updates_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    preference_shift_note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=utc_now, index=True)


class RecentStateNote(SQLModel, table=True):
    note_id: str = Field(default_factory=generate_id, primary_key=True)
    user_id: str = Field(index=True, foreign_key="userprofile.user_id")
    note_text: str = Field(sa_column=Column(Text))
    tags_json: list = Field(default_factory=list, sa_column=Column(JSON))
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now, index=True)
