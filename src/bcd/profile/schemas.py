"""Profile-facing schema models."""

from __future__ import annotations

from datetime import datetime

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
