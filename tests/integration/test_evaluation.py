from bcd.config import get_settings
from bcd.evaluation.service import EvaluationService
from bcd.storage.database import init_db, session_scope


def test_baseline_evaluation_runs(configured_env):
    settings = get_settings()
    init_db(settings)

    with session_scope(settings.database_url) as session:
        results = EvaluationService(session, settings).run_sample_evaluation()

    assert results["num_cases"] >= 1
    assert 0.0 <= results["top1_accuracy"] <= 1.0
    assert 0.0 <= results["average_top_confidence"] <= 1.0
