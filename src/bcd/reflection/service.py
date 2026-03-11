"""Feedback logging, memory updates, and history inspection."""

from __future__ import annotations

from sqlmodel import Session

from bcd.decision.schemas import FeedbackInput, FeedbackResponse, HistoryEvent
from bcd.profile.service import ProfileService
from bcd.storage.models import ActualChoiceFeedback, MemoryEntry
from bcd.storage.repository import BCDRepository
from bcd.utils.text import extract_context_tags, flatten_to_text, tokenize


class ReflectionService:
    """Update memory and snapshots after observing actual user choices."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = BCDRepository(session)
        self.profile_service = ProfileService(session)

    def record_feedback(self, request_id: str, payload: FeedbackInput) -> FeedbackResponse:
        request = self.repository.get_request(request_id)
        if request is None:
            raise ValueError(f"Decision request '{request_id}' was not found.")

        options = self.repository.list_options_for_request(request_id)
        option_by_id = {option.option_id: option for option in options}
        if payload.actual_option_id not in option_by_id:
            raise ValueError("The provided actual option id does not belong to this request.")

        prediction = self.repository.get_prediction_by_request(request_id)
        feedback = self.repository.add(
            ActualChoiceFeedback(
                request_id=request_id,
                actual_option_id=payload.actual_option_id,
                reason_text=payload.reason_text,
                reason_tags_json=payload.reason_tags,
            )
        )
        chosen_option = option_by_id[payload.actual_option_id]
        memory_summary = self._build_memory_summary(
            prompt=request.prompt,
            category=request.category,
            chosen_option_text=chosen_option.option_text,
            context=request.context_json,
            reason_text=payload.reason_text,
        )
        tags = list(
            dict.fromkeys(
                payload.reason_tags
                + tokenize(chosen_option.option_text)
                + extract_context_tags(request.context_json)
            )
        )
        memory = self.repository.add(
            MemoryEntry(
                user_id=request.user_id,
                source_request_id=request.request_id,
                source_feedback_id=feedback.feedback_id,
                category=request.category,
                summary=memory_summary,
                chosen_option_text=chosen_option.option_text,
                context_json=request.context_json,
                tags_json=tags,
                salience_score=1.25 if prediction and prediction.predicted_option_id != chosen_option.option_id else 1.0,
            )
        )
        snapshot = self.profile_service._rebuild_snapshot(request.user_id)
        snapshot = self.repository.add(snapshot)

        return FeedbackResponse(
            feedback_id=feedback.feedback_id,
            request_id=request_id,
            actual_option_id=chosen_option.option_id,
            actual_option_text=chosen_option.option_text,
            prediction_correct=bool(prediction and prediction.predicted_option_id == chosen_option.option_id),
            created_memory_id=memory.memory_id,
            updated_snapshot_id=snapshot.snapshot_id,
            created_at=feedback.created_at,
        )

    def list_user_history(self, user_id: str, limit: int = 50) -> list[HistoryEvent]:
        requests = self.repository.list_requests_for_user(user_id, limit=limit)
        request_ids = [request.request_id for request in requests]
        predictions = {item.request_id: item for item in self.repository.list_predictions_for_requests(request_ids)}
        feedbacks = {item.request_id: item for item in self.repository.list_feedback_for_user_requests(request_ids)}

        history: list[HistoryEvent] = []
        for request in requests:
            options = self.repository.list_options_for_request(request.request_id)
            feedback = feedbacks.get(request.request_id)
            prediction = predictions.get(request.request_id)
            history.append(
                HistoryEvent(
                    request_id=request.request_id,
                    prompt=request.prompt,
                    category=request.category,
                    context=request.context_json,
                    options=[
                        {
                            "option_id": option.option_id,
                            "option_text": option.option_text,
                            "option_metadata": option.option_metadata_json,
                            "position": option.position,
                        }
                        for option in options
                    ],
                    prediction={
                        "prediction_id": prediction.prediction_id,
                        "predicted_option_id": prediction.predicted_option_id,
                        "ranked_option_ids": prediction.ranked_option_ids_json,
                        "confidence_by_option": prediction.confidence_by_option_json,
                        "explanation": prediction.explanation,
                        "strategy": prediction.strategy,
                    }
                    if prediction
                    else None,
                    feedback={
                        "feedback_id": feedback.feedback_id,
                        "actual_option_id": feedback.actual_option_id,
                        "reason_text": feedback.reason_text,
                        "reason_tags": feedback.reason_tags_json,
                    }
                    if feedback
                    else None,
                    created_at=request.created_at,
                )
            )
        return history

    def list_user_memories(self, user_id: str, limit: int = 20) -> list[dict]:
        memories = self.repository.list_memories(user_id, limit=limit)
        return [
            {
                "memory_id": memory.memory_id,
                "category": memory.category,
                "summary": memory.summary,
                "chosen_option_text": memory.chosen_option_text,
                "context": memory.context_json,
                "tags": memory.tags_json,
                "salience_score": memory.salience_score,
                "created_at": memory.created_at,
            }
            for memory in memories
        ]

    @staticmethod
    def _build_memory_summary(
        prompt: str,
        category: str,
        chosen_option_text: str,
        context: dict,
        reason_text: str | None,
    ) -> str:
        pieces = [f"For {category}, the user chose '{chosen_option_text}' after '{prompt}'."]
        if context:
            pieces.append(f"Context: {flatten_to_text(context)}.")
        if reason_text:
            pieces.append(f"Reason: {reason_text}")
        return " ".join(pieces)
