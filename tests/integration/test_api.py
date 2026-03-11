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

    bootstrap_response = client.post("/profiles/bootstrap-sample")
    assert bootstrap_response.status_code == 200
    user_id = bootstrap_response.json()["user_id"]
    card_response = client.get(f"/profiles/{user_id}/card")
    assert card_response.status_code == 200
    assert "content" in card_response.json()

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

    feedback_response = client.post(
        f"/decisions/{prediction_payload['request_id']}/feedback",
        json={
            "actual_option_id": prediction_payload["predicted_option_id"],
            "reason_text": "Wanted something warm and easy.",
            "reason_tags": ["warm", "easy"],
        },
    )
    assert feedback_response.status_code == 200

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
            "answers": [
                {
                    "question": "How do you usually make everyday choices?",
                    "answer": "I usually optimize for comfort and reliability."
                },
                {
                    "question": "What kinds of options do you usually prefer or avoid?",
                    "answer": "I prefer warm food and structured plans, and I avoid chaotic options."
                }
            ]
        },
    )
    assert onboarding_response.status_code == 200
    assert onboarding_response.json()["user_id"].startswith("taylor-")

    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt_conversations.json"
    with fixture_path.open("rb") as handle:
        import_response = client.post(
            "/profiles/import-chatgpt-export",
            data={"display_name": "Morgan"},
            files={"file": ("conversations.json", handle, "application/json")},
        )
    assert import_response.status_code == 200
    assert import_response.json()["user_profile"]["user_id"].startswith("morgan-")
