from fastapi.testclient import TestClient

from bcd.api.app import create_app
from bcd.config import get_settings
from bcd.storage.database import init_db


def test_api_happy_path(configured_env):
    settings = get_settings()
    init_db(settings)
    app = create_app()
    client = TestClient(app)

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
