# Contributing

Thanks for considering a contribution to bcd.

## Project Principles

- Keep bcd local-first.
- Keep user-owned data readable and stored under `~/.bcd`.
- Do not add fallback predictions when Codex CLI fails.
- Prefer small, reviewable changes.
- Avoid new dependencies unless they remove clear complexity.

## Development

```bash
npm install
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173).

## Verification

Run these before opening a pull request:

```bash
npm run typecheck
npm test
npm run build
```

For local API smoke testing:

```bash
BCD_E2E_BASE_URL=http://127.0.0.1:3940 BCD_E2E_CODEX=0 npm run smoke:e2e
```

## Pull Requests

Please include:

- What changed and why
- How the local-first data contract is preserved
- Commands used for verification
- Any known gaps or follow-up work

Large behavior changes should start as an issue so the scope can be discussed before implementation.
