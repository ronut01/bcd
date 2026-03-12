"""Profile-facing schema models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PreferenceSnapshotRead(BaseModel):
    snapshot_id: str
    user_id: str
    summary: str
    short_term_preference_notes: list[str] = Field(default_factory=list)
    drift_markers: list[str] = Field(default_factory=list)
    derived_statistics: dict = Field(default_factory=dict)
    created_at: datetime


class UserProfileRead(BaseModel):
    user_id: str
    display_name: str
    profile_summary: str
    personality_signals: dict = Field(default_factory=dict)
    long_term_preferences: dict = Field(default_factory=dict)
    onboarding_answers: list = Field(default_factory=list)
    latest_snapshot: PreferenceSnapshotRead | None = None
    memory_count: int = 0
    history_count: int = 0
    profile_card_path: str | None = None
    signal_count: int = 0
    pending_signal_count: int = 0


class OnboardingQuestionOptionRead(BaseModel):
    option_id: str
    label: str
    description: str


class OnboardingQuestionRead(BaseModel):
    question_id: str
    title: str
    prompt: str
    options: list[OnboardingQuestionOptionRead] = Field(default_factory=list)


class OnboardingQuestionnaireRead(BaseModel):
    version: str
    mbti_options: list[str] = Field(default_factory=list)
    questions: list[OnboardingQuestionRead] = Field(default_factory=list)


class StructuredOnboardingResponseInput(BaseModel):
    question_id: str
    option_id: str


class OnboardingAnswerRead(BaseModel):
    question_id: str
    question: str
    option_id: str
    answer: str


class UserOnboardingInput(BaseModel):
    display_name: str
    user_id: str | None = None
    mbti: str
    responses: list[StructuredOnboardingResponseInput]


class ChatGPTImportResponse(BaseModel):
    user_profile: UserProfileRead
    import_source: Literal["chatgpt_export"] = "chatgpt_export"
    import_stats: dict = Field(default_factory=dict)


class ProfileSignalRead(BaseModel):
    signal_id: str
    user_id: str
    source_type: str
    signal_kind: str
    signal_name: str
    proposed_value: dict = Field(default_factory=dict)
    current_value: dict | None = None
    evidence_text: str
    review_note: str | None = None
    status: Literal["pending", "accepted", "rejected", "edited"]
    created_at: datetime
    updated_at: datetime


class ProfileSignalReviewInput(BaseModel):
    action: Literal["accept", "reject", "edit"]
    edited_value: dict | None = None
    review_note: str | None = None


class ProfileSignalReviewResponse(BaseModel):
    signal: ProfileSignalRead
    user_profile: UserProfileRead


class RecentStateNoteInput(BaseModel):
    note_text: str
    tags: list[str] = Field(default_factory=list)


class RecentStateNoteRead(BaseModel):
    note_id: str
    user_id: str
    note_text: str
    tags: list[str] = Field(default_factory=list)
    active: bool
    created_at: datetime
    updated_at: datetime
