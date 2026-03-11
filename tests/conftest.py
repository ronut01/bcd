"""Test configuration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def configured_env(tmp_path, monkeypatch):
    database_path = tmp_path / "test.sqlite"
    profile_card_dir = tmp_path / "profile_cards"
    monkeypatch.setenv("BCD_DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("BCD_PROFILE_CARD_DIR", str(profile_card_dir))
    monkeypatch.setenv("BCD_SAMPLE_PROFILE_PATH", str(ROOT / "data/sample_profiles/alex_chen.json"))
    monkeypatch.setenv("BCD_SAMPLE_DECISIONS_PATH", str(ROOT / "data/sample_decisions/seed_history.json"))
    monkeypatch.setenv("BCD_EVAL_CASES_PATH", str(ROOT / "data/sample_decisions/eval_cases.json"))

    from bcd.storage.database import _ENGINE_CACHE

    _ENGINE_CACHE.clear()
    yield
