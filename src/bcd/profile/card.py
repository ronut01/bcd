"""Profile card generation for LLM-facing user summaries."""

from __future__ import annotations

from pathlib import Path

from bcd.profile.schemas import UserProfileRead


class ProfileCardRenderer:
    """Render a stable Markdown card summarizing a user's decision tendencies."""

    def render_stable(
        self,
        profile: UserProfileRead,
    ) -> str:
        lines = [
            f"# Stable Profile Card: {profile.display_name}",
            "",
            f"- User ID: `{profile.user_id}`",
            f"- Profile summary: {profile.profile_summary}",
            f"- Stable signal count: {profile.signal_count}",
            f"- Pending signal review count: {profile.pending_signal_count}",
            "",
            "## Stable signals",
        ]

        for key, value in profile.personality_signals.items():
            lines.append(f"- {key.replace('_', ' ').title()}: {value}")

        lines.extend(["", "## Long-term preferences"])
        category_preferences = profile.long_term_preferences.get("category_preferences", {})
        for category, signals in category_preferences.items():
            preferred = ", ".join(signals.get("preferred_keywords", [])) or "None"
            avoided = ", ".join(signals.get("avoided_keywords", [])) or "None"
            lines.append(f"- {category}: prefers [{preferred}] and avoids [{avoided}]")

        context_preferences = profile.long_term_preferences.get("context_preferences", {})
        if context_preferences:
            lines.extend(["", "## Context preferences"])
            for key, value in context_preferences.items():
                lines.append(f"- {key}: {', '.join(value)}")

        if profile.onboarding_answers:
            lines.extend(["", "## Onboarding answers"])
            for item in profile.onboarding_answers:
                lines.append(f"- Q: {item['question']}")
                lines.append(f"  A: {item['answer']}")

        return "\n".join(lines).strip() + "\n"

    def render_recent_state(
        self,
        profile: UserProfileRead,
        recent_memories: list[dict],
        manual_recent_notes: list[str] | None = None,
        feedback_shift_notes: list[str] | None = None,
    ) -> str:
        lines = [
            f"# Recent State Card: {profile.display_name}",
            "",
            f"- User ID: `{profile.user_id}`",
        ]

        if profile.latest_snapshot:
            lines.extend(
                [
                    "",
                    "## Latest short-term snapshot",
                    f"- Summary: {profile.latest_snapshot.summary}",
                ]
            )
            if profile.latest_snapshot.short_term_preference_notes:
                lines.append(
                    f"- Notes: {'; '.join(profile.latest_snapshot.short_term_preference_notes)}"
                )
            if profile.latest_snapshot.drift_markers:
                lines.append(f"- Drift markers: {'; '.join(profile.latest_snapshot.drift_markers)}")

        if manual_recent_notes:
            lines.extend(["", "## Manual recent-state notes"])
            for note in manual_recent_notes[:5]:
                lines.append(f"- {note}")

        if feedback_shift_notes:
            lines.extend(["", "## Feedback-derived shift markers"])
            for note in feedback_shift_notes[:5]:
                lines.append(f"- {note}")

        if recent_memories:
            lines.extend(["", "## Representative recent memories"])
            for memory in recent_memories[:5]:
                lines.append(f"- [{memory['category']}] {memory['summary']}")

        lines.extend(
            [
                "",
                "## Prediction guidance",
                "- Prefer what this user is likely to choose in practice.",
                "- Use current context and recent memories, not just generic preference keywords.",
                "- When uncertain, favor low-friction, familiar, context-compatible options.",
            ]
        )
        return "\n".join(lines).strip() + "\n"

    def render(
        self,
        profile: UserProfileRead,
        recent_memories: list[dict],
        manual_recent_notes: list[str] | None = None,
        feedback_shift_notes: list[str] | None = None,
    ) -> tuple[str, str, str]:
        stable = self.render_stable(profile)
        recent = self.render_recent_state(
            profile,
            recent_memories,
            manual_recent_notes=manual_recent_notes,
            feedback_shift_notes=feedback_shift_notes,
        )
        combined = f"{stable}\n{recent}"
        return stable, recent, combined


def write_profile_card(card_dir: Path, user_id: str, content: str) -> Path:
    """Write the profile card to disk and return its path."""

    card_dir.mkdir(parents=True, exist_ok=True)
    path = card_dir / f"{user_id}.md"
    path.write_text(content, encoding="utf-8")
    return path


def write_state_card(card_dir: Path, user_id: str, content: str) -> Path:
    """Write the recent-state card to disk and return its path."""

    card_dir.mkdir(parents=True, exist_ok=True)
    path = card_dir / f"{user_id}.recent.md"
    path.write_text(content, encoding="utf-8")
    return path
