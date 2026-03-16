"""Decision input and output schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from bcd.memory.schemas import RetrievedMemory


class RankedOptionComponentScore(BaseModel):
    name: str
    raw_score: float
    weight: float
    weighted_score: float
    reason: str


class AgentBrief(BaseModel):
    agent_name: str
    focus: str
    observations: list[str] = Field(default_factory=list)
    conclusion: str


class AgentInfluenceBreakdown(BaseModel):
    option_id: str
    option_text: str
    stable_profile: float = 0.0
    recent_state: float = 0.0
    memory: float = 0.0
    context: float = 0.0
    llm: float = 0.0
    dominant_signals: list[str] = Field(default_factory=list)


class AgentOptionAssessment(BaseModel):
    option_id: str
    option_text: str
    why_choose: list[str] = Field(default_factory=list)
    why_avoid: list[str] = Field(default_factory=list)
    influence: AgentInfluenceBreakdown


class AgentWorkflowTrace(BaseModel):
    profile_agent: AgentBrief
    recent_state_agent: AgentBrief
    memory_agent: AgentBrief
    choice_reasoning_agent: AgentBrief
    reflection_agent: AgentBrief


class AgentAgreementSignal(BaseModel):
    agent_name: str
    stance: Literal["support", "oppose", "mixed", "neutral"]
    strength: float = 0.0
    rationale: str


class AgentAgreementSummary(BaseModel):
    overall_label: Literal["strong_agreement", "partial_agreement", "mixed", "fragile"]
    summary: str
    supporting_agents: list[str] = Field(default_factory=list)
    opposing_agents: list[str] = Field(default_factory=list)
    neutral_agents: list[str] = Field(default_factory=list)
    signals: list[AgentAgreementSignal] = Field(default_factory=list)


class ExplanationSections(BaseModel):
    top_choice_summary: str
    why_this_option: list[str] = Field(default_factory=list)
    what_memories_mattered: list[str] = Field(default_factory=list)
    what_recent_state_mattered: list[str] = Field(default_factory=list)
    why_other_options_lost: list[str] = Field(default_factory=list)


class DecisionAudit(BaseModel):
    confidence_label: str
    margin_vs_runner_up: float = 0.0
    decisive_factors: list[str] = Field(default_factory=list)
    watchouts: list[str] = Field(default_factory=list)
    adaptation_signals: list[str] = Field(default_factory=list)
    active_context: dict = Field(default_factory=dict)


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


class DecisionOptionSuggestionInput(BaseModel):
    user_id: str
    prompt: str
    category: str
    context: dict = Field(default_factory=dict)
    existing_options: list[str] = Field(default_factory=list)
    max_suggestions: int = 4

    @field_validator("max_suggestions")
    @classmethod
    def validate_max_suggestions(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("Option suggestions must request between 1 and 5 items.")
        return value


class RankedOption(BaseModel):
    option_id: str
    option_text: str
    raw_score: float
    confidence: float
    reasons: list[str] = Field(default_factory=list)
    component_scores: list[RankedOptionComponentScore] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    reason_summary: str = ""


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
    agent_workflow: AgentWorkflowTrace
    top_choice_influence: AgentInfluenceBreakdown
    option_influences: list[AgentOptionAssessment] = Field(default_factory=list)
    agent_agreement: AgentAgreementSummary
    explanation_sections: ExplanationSections
    decision_audit: DecisionAudit
    created_at: datetime


class SuggestedOption(BaseModel):
    option_text: str
    confidence: float
    rationale: str
    source_labels: list[str] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)


class OptionSuggestionResponse(BaseModel):
    strategy: str
    active_context: dict = Field(default_factory=dict)
    suggestions: list[SuggestedOption] = Field(default_factory=list)


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
    model_update_summary: str
    snapshot_delta: list[str] = Field(default_factory=list)
    new_memory_summary: str
    active_carry_over: list[str] = Field(default_factory=list)
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
