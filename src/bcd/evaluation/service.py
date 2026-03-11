"""Baseline evaluation helpers."""

from __future__ import annotations

from collections import defaultdict

from sqlmodel import Session

from bcd.config import Settings, get_settings
from bcd.decision.schemas import DecisionOptionInput, DecisionPredictionInput
from bcd.decision.service import DecisionService
from bcd.profile.sample_data import load_json
from bcd.profile.service import ProfileService


class EvaluationService:
    """Run deterministic baseline evaluation on sample cases."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    def run_sample_evaluation(self) -> dict:
        profile = ProfileService(self.session, self.settings).bootstrap_sample_profile()
        cases = load_json(self.settings.eval_cases_path)
        decision_service = DecisionService(self.session, self.settings)
        results = []
        by_category: dict[str, dict[str, float]] = defaultdict(lambda: {"correct": 0, "total": 0})

        for case in cases:
            prediction = decision_service.predict(
                DecisionPredictionInput(
                    user_id=profile.user_id,
                    prompt=case["prompt"],
                    category=case["category"],
                    context=case.get("context", {}),
                    options=[
                        DecisionOptionInput(
                            option_text=option["option_text"],
                            option_metadata=option.get("option_metadata", {}),
                        )
                        for option in case["options"]
                    ],
                )
            )
            correct = prediction.predicted_option_text == case["actual_option_text"]
            by_category[case["category"]]["total"] += 1
            by_category[case["category"]]["correct"] += int(correct)
            results.append(
                {
                    "prompt": case["prompt"],
                    "category": case["category"],
                    "predicted_option_text": prediction.predicted_option_text,
                    "actual_option_text": case["actual_option_text"],
                    "confidence": prediction.confidence,
                    "correct": correct,
                }
            )

        total = len(results)
        accuracy = sum(int(item["correct"]) for item in results) / total if total else 0.0
        average_confidence = sum(item["confidence"] for item in results) / total if total else 0.0

        return {
            "user_id": profile.user_id,
            "num_cases": total,
            "top1_accuracy": round(accuracy, 4),
            "average_top_confidence": round(average_confidence, 4),
            "by_category": {
                category: {
                    "accuracy": round(values["correct"] / values["total"], 4) if values["total"] else 0.0,
                    "total": int(values["total"]),
                }
                for category, values in by_category.items()
            },
            "cases": results,
        }
