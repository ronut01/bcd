"""Memory retrieval schema models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RetrievedMemory(BaseModel):
    memory_id: str
    category: str
    summary: str
    chosen_option_text: str
    tags: list[str] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)
    retrieval_score: float
    matched_terms: list[str] = Field(default_factory=list)
    created_at: datetime
