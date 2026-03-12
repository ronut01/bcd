"""Memory retrieval schema models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RetrievalComponentScore(BaseModel):
    name: str
    score: float
    detail: str


class RetrievedMemory(BaseModel):
    memory_id: str
    category: str
    summary: str
    chosen_option_text: str
    tags: list[str] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)
    retrieval_score: float
    matched_terms: list[str] = Field(default_factory=list)
    retrieval_components: list[RetrievalComponentScore] = Field(default_factory=list)
    why_retrieved: list[str] = Field(default_factory=list)
    memory_role: Literal["direct_match", "supporting", "context_match", "recent_repeat"] = "supporting"
    created_at: datetime
