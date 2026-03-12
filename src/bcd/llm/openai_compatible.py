"""OpenAI-compatible chat completion client for optional ranking."""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from bcd.decision.schemas import LLMRuntimeConfig
from bcd.config import Settings
from bcd.llm.base import LLMRankingRequest, LLMRankingResult


def _extract_json_object(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        raise ValueError("The LLM response did not contain a JSON object.")
    return json.loads(text[start : end + 1])


@dataclass(slots=True)
class OpenAICompatibleLLMRanker:
    """Optional ranker backed by an OpenAI-compatible chat completion API."""

    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 30.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "OpenAICompatibleLLMRanker | None":
        if not settings.llm_api_key:
            return None
        return cls(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    @classmethod
    def from_runtime_config(cls, config: LLMRuntimeConfig) -> "OpenAICompatibleLLMRanker":
        return cls(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            timeout_seconds=config.timeout_seconds,
        )

    def rank(self, request: LLMRankingRequest) -> LLMRankingResult | None:
        endpoint = self.base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"

        system_prompt = (
            "You predict which option a specific user is most likely to choose in practice. "
            "Use retrieved memories as the strongest evidence, then current context, then stable profile signals. "
            "Treat the heuristic ranking as a weak prior, not as ground truth. "
            "Do not recommend the objectively best option unless it is also the most likely human choice. "
            "Return strict JSON with keys ranked_options and explanation."
        )
        user_prompt = json.dumps(
            {
                "task": "Rank candidate options by the user's likely real-world choice.",
                "decision_prompt": request.prompt,
                "category": request.category,
                "context": request.context,
                "options": request.options,
                "profile_card_markdown": request.profile_card_markdown,
                "stable_profile_markdown": request.stable_profile_markdown,
                "recent_state_markdown": request.recent_state_markdown,
                "retrieved_memory_summaries": request.memory_summaries,
                "memory_evidence": request.memory_evidence,
                "reviewed_profile_signals": request.reviewed_profile_signals,
                "heuristic_ranking": request.heuristic_ranking,
                "requirements": {
                    "rank_all_options": True,
                    "top_choice_should_reflect_user_likelihood": True,
                    "ground_explanation_in_recent_memories_and_context": True,
                    "output_json_only": True,
                },
                "output_schema": {
                    "ranked_options": ["option text in ranked order"],
                    "explanation": "short explanation grounded in profile, memories, and context",
                },
            }
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()

        content = body["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        parsed = _extract_json_object(content)
        ranked_options = parsed.get("ranked_options") or []
        explanation = parsed.get("explanation") or "The LLM ranked the options."
        if not isinstance(ranked_options, list) or not all(isinstance(item, str) for item in ranked_options):
            raise ValueError("The LLM response contained an invalid ranked_options field.")
        return LLMRankingResult(
            ranked_options=ranked_options,
            explanation=explanation,
            provider="openai-compatible",
            raw_response=body,
        )
