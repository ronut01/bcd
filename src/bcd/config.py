"""Configuration helpers for the bcd project."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _resolve_path(value: str, project_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (project_root / path).resolve()


@dataclass(slots=True)
class Settings:
    """Application settings loaded from environment variables."""

    project_root: Path
    database_url: str
    retrieval_top_k: int
    sample_profile_path: Path
    sample_decisions_path: Path
    eval_cases_path: Path


def get_settings() -> Settings:
    """Load settings using environment variables with local defaults."""

    project_root = Path(__file__).resolve().parents[2]
    return Settings(
        project_root=project_root,
        database_url=os.getenv("BCD_DATABASE_URL", "sqlite:///./data/runtime/bcd.sqlite"),
        retrieval_top_k=int(os.getenv("BCD_RETRIEVAL_TOP_K", "5")),
        sample_profile_path=_resolve_path(
            os.getenv("BCD_SAMPLE_PROFILE_PATH", "./data/sample_profiles/alex_chen.json"),
            project_root,
        ),
        sample_decisions_path=_resolve_path(
            os.getenv("BCD_SAMPLE_DECISIONS_PATH", "./data/sample_decisions/seed_history.json"),
            project_root,
        ),
        eval_cases_path=_resolve_path(
            os.getenv("BCD_EVAL_CASES_PATH", "./data/sample_decisions/eval_cases.json"),
            project_root,
        ),
    )
