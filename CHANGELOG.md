# Changelog

All notable changes to bcd are documented here.

## [0.1.0] - 2026-06-01

### Added

- Local-first React/Vite interface for onboarding, decisions, profile review, and memory browsing.
- Node HTTP API for profile storage, Codex CLI checks, option suggestions, predictions, feedback, and memories.
- Markdown/JSON file storage under `~/.bcd`.
- Codex-backed memory selection before prediction.
- Fast prediction mode plus adaptive deep mode for high-stakes, explicit deep, or low-confidence decisions.
- Three-role deep prediction panel with value fit, practicality, and regret-risk judgments.
- Background decision-card generation from saved feedback.
- Validation, prompt, storage, prediction-gate, and route tests.

### Security And Privacy

- Runtime profile, memory, feedback, raw imports, and debug logs are stored outside the repository.
- `.env*`, `.omx/`, `bcd.md`, `dist/`, `node_modules/`, and `.DS_Store` are ignored.
- Raw external profile imports require explicit storage consent.

### Known Gaps

- No packaged desktop app yet.
- No import/export bundle yet.
- Real Codex CLI smoke testing depends on a local authenticated Codex environment.
