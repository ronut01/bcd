"""Run the sample baseline evaluation."""

import json

from bcd.config import get_settings
from bcd.evaluation.service import EvaluationService
from bcd.storage.database import init_db, session_scope


if __name__ == "__main__":
    settings = get_settings()
    init_db(settings)
    with session_scope(settings.database_url) as session:
        result = EvaluationService(session, settings).run_sample_evaluation()
    print(json.dumps(result, indent=2, default=str))
