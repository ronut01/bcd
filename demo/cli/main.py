"""Typer CLI for the bcd MVP."""

from __future__ import annotations

import json

import typer

from bcd.config import get_settings
from bcd.decision.schemas import DecisionOptionInput, DecisionPredictionInput, FeedbackInput
from bcd.decision.service import DecisionService
from bcd.evaluation.service import EvaluationService
from bcd.profile.service import ProfileService
from bcd.reflection.service import ReflectionService
from bcd.storage.database import init_db, session_scope


app = typer.Typer(help="CLI for the bcd personalized decision prediction MVP.")


def _pretty_dump(payload) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    typer.echo(json.dumps(payload, indent=2, default=str))


@app.command()
def bootstrap() -> None:
    """Initialize the sample user and seed history."""

    settings = get_settings()
    init_db(settings)
    with session_scope(settings.database_url) as session:
        profile = ProfileService(session, settings).bootstrap_sample_profile()
        _pretty_dump(profile)


@app.command()
def predict(
    user_id: str,
    prompt: str,
    category: str,
    options: str = typer.Option(..., help="Pipe-separated option texts, for example 'A|B|C'."),
    context_json: str = typer.Option("{}", help="JSON object describing optional context."),
) -> None:
    """Submit a decision request and print the prediction."""

    settings = get_settings()
    init_db(settings)
    with session_scope(settings.database_url) as session:
        prediction = DecisionService(session, settings).predict(
            DecisionPredictionInput(
                user_id=user_id,
                prompt=prompt,
                category=category,
                context=json.loads(context_json),
                options=[DecisionOptionInput(option_text=item.strip()) for item in options.split("|") if item.strip()],
            )
        )
        _pretty_dump(prediction)


@app.command()
def feedback(
    request_id: str,
    actual_option_id: str,
    reason_text: str = typer.Option("", help="Optional free-text reason."),
    reason_tags: str = typer.Option("", help="Comma-separated reason tags."),
) -> None:
    """Record the actual user choice and update memory."""

    settings = get_settings()
    init_db(settings)
    with session_scope(settings.database_url) as session:
        result = ReflectionService(session).record_feedback(
            request_id=request_id,
            payload=FeedbackInput(
                actual_option_id=actual_option_id,
                reason_text=reason_text or None,
                reason_tags=[tag.strip() for tag in reason_tags.split(",") if tag.strip()],
            ),
        )
        _pretty_dump(result)


@app.command()
def history(user_id: str, limit: int = 10) -> None:
    """Inspect previous decision events for a user."""

    settings = get_settings()
    init_db(settings)
    with session_scope(settings.database_url) as session:
        result = ReflectionService(session).list_user_history(user_id=user_id, limit=limit)
        _pretty_dump([item.model_dump(mode="json") for item in result])


@app.command()
def evaluate() -> None:
    """Run the baseline evaluation on sample cases."""

    settings = get_settings()
    init_db(settings)
    with session_scope(settings.database_url) as session:
        result = EvaluationService(session, settings).run_sample_evaluation()
        _pretty_dump(result)


def run_demo_flow() -> dict:
    """Run a single deterministic demo flow for local inspection."""

    settings = get_settings()
    init_db(settings)
    with session_scope(settings.database_url) as session:
        profile_service = ProfileService(session, settings)
        profile = profile_service.bootstrap_sample_profile()
        prediction = DecisionService(session, settings).predict(
            DecisionPredictionInput(
                user_id=profile.user_id,
                prompt="Choose dinner after an exhausting rainy evening.",
                category="food",
                context={
                    "time_of_day": "night",
                    "energy": "low",
                    "weather": "rainy",
                    "with": "alone",
                },
                options=[
                    DecisionOptionInput(option_text="Warm udon soup near home"),
                    DecisionOptionInput(option_text="Double bacon cheeseburger"),
                    DecisionOptionInput(option_text="Late-night salad delivery"),
                ],
            )
        )
        feedback = ReflectionService(session).record_feedback(
            request_id=prediction.request_id,
            payload=FeedbackInput(
                actual_option_id=prediction.predicted_option_id,
                reason_text="The warm and familiar option felt easiest after a long day.",
                reason_tags=["warm", "familiar", "low_energy"],
            ),
        )
        history = ReflectionService(session).list_user_history(profile.user_id, limit=3)

    return {
        "profile": profile.model_dump(mode="json"),
        "prediction": prediction.model_dump(mode="json"),
        "feedback": feedback.model_dump(mode="json"),
        "recent_history": [item.model_dump(mode="json") for item in history],
    }


@app.command()
def demo() -> None:
    """Run the default local MVP demo flow."""

    _pretty_dump(run_demo_flow())


if __name__ == "__main__":
    app()
