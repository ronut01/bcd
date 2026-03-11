"""Text normalization helpers used by retrieval and scoring."""

from __future__ import annotations

import re
from collections.abc import Iterable


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Return lowercase alphanumeric tokens from free text."""

    return TOKEN_PATTERN.findall(text.lower())


def flatten_to_text(value: object) -> str:
    """Flatten nested context structures into a single string."""

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(f"{key} {flatten_to_text(item)}" for key, item in value.items())
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        return " ".join(flatten_to_text(item) for item in value)
    return str(value)


def overlap_count(left: set[str], right: set[str]) -> int:
    """Count token overlap between two token sets."""

    return len(left & right)


def extract_context_tags(context: dict) -> list[str]:
    """Create compact context tags such as ``energy_low``."""

    tags: list[str] = []
    for key, value in context.items():
        key_text = str(key).strip().lower().replace(" ", "_")
        if isinstance(value, dict):
            nested_text = flatten_to_text(value)
            if nested_text:
                tags.append(f"{key_text}_{nested_text.strip().lower().replace(' ', '_')}")
            continue
        if isinstance(value, (list, tuple, set)):
            nested_text = flatten_to_text(value)
            if nested_text:
                tags.append(f"{key_text}_{nested_text.strip().lower().replace(' ', '_')}")
            continue
        value_text = str(value).strip().lower().replace(" ", "_")
        if value_text:
            tags.append(f"{key_text}_{value_text}")
    return tags
