"""Sample data loaders used for bootstrapping the MVP."""

from __future__ import annotations

import json
from pathlib import Path


def load_json(path: Path):
    """Load a JSON file from disk."""

    return json.loads(path.read_text(encoding="utf-8"))
