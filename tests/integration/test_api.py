from fastapi.testclient import TestClient

from bcd.api.app import create_app
from bcd.config import get_settings
from bcd.storage.database import init_db
from pathlib import Path


def test_api_happy_path(configured_env):
    settings = get_settings()
    init_db(settings)
    app = create_app()
    client = TestClient(app)

    root_response = client.get("/", follow_redirects=False)
    assert root_response.status_code == 307
    assert root_response.headers["location"] == "/app"

    app_response = client.get("/app")
    assert app_response.status_code == 200
    assert "local demo" in app_response.text.lower()

    questionnaire_response = client.get("/profiles/onboarding-questionnaire")
    assert questionnaire_response.status_code == 200
    questionnaire_payload = questionnaire_response.json()
    assert questionnaire_payload["version"] == "v1"
    assert len(questionnaire_payload["questions"]) >= 5
    preview_response = client.post(
        "/profiles/onboard/preview",
        json={
            "display_name": "Taylor",
            "mbti": "INTJ",
            "responses": [
                {"question_id": "meal_when_tired", "option_id": "warm_comfort"},
                {"question_id": "planning_style", "option_id": "checklist"},
            ],
        },
    )
    assert preview_response.status_code == 200
    assert "profile_summary" in preview_response.json()

    bootstrap_response = client.post("/profiles/bootstrap-sample")
    assert bootstrap_response.status_code == 200
    user_id = bootstrap_response.json()["user_id"]
    card_response = client.get(f"/profiles/{user_id}/card")
    assert card_response.status_code == 200
    assert "content" in card_response.json()
    signals_response = client.get(f"/profiles/{user_id}/signals")
    assert signals_response.status_code == 200
    assert len(signals_response.json()) >= 1
    recent_state_create = client.post(
        f"/profiles/{user_id}/recent-state",
        json={"note_text": "Today the user is unusually tired and wants low-friction choices.", "tags": ["tired"]},
    )
    assert recent_state_create.status_code == 200
    recent_state_list = client.get(f"/profiles/{user_id}/recent-state")
    assert recent_state_list.status_code == 200
    assert len(recent_state_list.json()) == 1

    prediction_response = client.post(
        "/decisions/predict",
        json={
            "user_id": user_id,
            "prompt": "Pick dinner after a tiring rainy evening.",
            "category": "food",
            "context": {"energy": "low", "weather": "rainy", "time_of_day": "night"},
            "options": [
                {"option_text": "Warm noodle soup"},
                {"option_text": "Greasy burger"},
                {"option_text": "Raw salad"},
            ],
        },
    )
    assert prediction_response.status_code == 200
    prediction_payload = prediction_response.json()
    assert prediction_payload["explanation_sections"]["top_choice_summary"]
    assert prediction_payload["ranked_options"][0]["component_scores"]
    assert "why_retrieved" in prediction_payload["retrieved_memories"][0]

    feedback_response = client.post(
        f"/decisions/{prediction_payload['request_id']}/feedback",
        json={
            "actual_option_id": prediction_payload["predicted_option_id"],
            "reason_text": "Wanted something warm and easy.",
            "reason_tags": ["warm", "easy"],
            "failure_reasons": ["context_missing"],
            "context_updates": {"energy": "very_low"},
            "preference_shift_note": "Rain made comfort more important.",
        },
    )
    assert feedback_response.status_code == 200
    assert feedback_response.json()["reflection_id"]

    history_response = client.get(f"/users/{user_id}/history")
    memories_response = client.get(f"/users/{user_id}/memories")

    assert history_response.status_code == 200
    assert memories_response.status_code == 200
    assert len(history_response.json()) >= 1
    assert len(memories_response.json()) >= 1

    onboarding_response = client.post(
        "/profiles/onboard",
        json={
            "display_name": "Taylor",
            "mbti": "INTJ",
            "responses": [
                {
                    "question_id": "meal_when_tired",
                    "option_id": "warm_comfort"
                },
                {
                    "question_id": "planning_style",
                    "option_id": "checklist"
                }
            ]
        },
    )
    assert onboarding_response.status_code == 200
    onboarded_user_id = onboarding_response.json()["user_id"]
    assert onboarded_user_id.startswith("taylor-")
    reviewed_signal = client.get(f"/profiles/{onboarded_user_id}/signals")
    assert reviewed_signal.status_code == 200

    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt_conversations.json"
    with fixture_path.open("rb") as handle:
        import_response = client.post(
            "/profiles/import-chatgpt-export",
            data={"display_name": "Morgan"},
            files={"file": ("conversations.json", handle, "application/json")},
        )
    assert import_response.status_code == 200
    imported_user_id = import_response.json()["user_profile"]["user_id"]
    assert imported_user_id.startswith("morgan-")
    imported_signals = client.get(f"/profiles/{imported_user_id}/signals")
    assert imported_signals.status_code == 200
    pending_signal = next(item for item in imported_signals.json() if item["status"] == "pending")
    signal_review_response = client.post(
        f"/profiles/{imported_user_id}/signals/{pending_signal['signal_id']}/review",
        json={
            "action": "edit",
            "edited_value": {"label": "curated signal"},
            "review_note": "User corrected the inferred label.",
        },
    )
    assert signal_review_response.status_code == 200
    assert signal_review_response.json()["signal"]["status"] == "edited"
