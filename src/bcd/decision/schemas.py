"""Decision input and output schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from bcd.memory.schemas import RetrievedMemory


class LLMRuntimeConfig(BaseModel):
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4.1-mini"
    timeout_seconds: float = 30.0


class DecisionOptionInput(BaseModel):
    option_text: str
    option_metadata: dict = Field(default_factory=dict)


class DecisionPredictionInput(BaseModel):
    user_id: str
    prompt: str
    category: str
    options: list[DecisionOptionInput]
    context: dict = Field(default_factory=dict)
    prediction_mode: Literal["baseline", "llm", "hybrid"] | None = None
    llm_config: LLMRuntimeConfig | None = None

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[DecisionOptionInput]) -> list[DecisionOptionInput]:
        if len(value) < 2 or len(value) > 5:
            raise ValueError("A decision request must contain between 2 and 5 options.")
        return value


class RankedOption(BaseModel):
    option_id: str
    option_text: str
    raw_score: float
    confidence: float
    reasons: list[str] = Field(default_factory=list)


class PredictionResponse(BaseModel):
    request_id: str
    prediction_id: str
    predicted_option_id: str
    predicted_option_text: str
    confidence: float
    explanation: str
    strategy: str
    llm_used: bool = False
    llm_provider: str | None = None
    llm_error: str | None = None
    profile_card_path: str | None = None
    ranked_options: list[RankedOption]
    retrieved_memories: list[RetrievedMemory] = Field(default_factory=list)
    created_at: datetime


class FeedbackInput(BaseModel):
    actual_option_id: str
    reason_text: str | None = None
    reason_tags: list[str] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)
    context_updates: dict = Field(default_factory=dict)
    preference_shift_note: str | None = None


class FeedbackResponse(BaseModel):
    feedback_id: str
    reflection_id: str
    request_id: str
    actual_option_id: str
    actual_option_text: str
    prediction_correct: bool
    created_memory_id: str
    updated_snapshot_id: str
    created_at: datetime


class HistoryEvent(BaseModel):
    request_id: str
    prompt: str
    category: str
    context: dict
    options: list[dict]
    prediction: dict | None
    feedback: dict | None
    created_at: datetime
