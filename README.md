# bcd

Local-first personal choice app. bcd keeps a lightweight profile and readable decision memories under `~/.bcd`, then asks the Codex CLI which option you would probably choose.

`bcd.md` is intentionally kept as the project direction document, not the README or PRD.

## What V1 Does

- Shows onboarding on first launch, then stores `~/.bcd/profile.md`.
- Checks Codex CLI before first onboarding so setup failures are visible early.
- Lets you enter a decision question, at least two options, and optional context without manual category/tag setup.
- Can ask Codex CLI to suggest options before prediction.
- Gathers candidate decision cards by available metadata and recency; saved memories get Codex-generated category/tags.
- Asks Codex to select relevant cards before asking Codex for the final prediction.
- Returns structured JSON from Codex and shows the stance "you would probably choose this."
- Saves feedback quickly while background decision-card generation continues.
- Stores decision cards as Markdown with frontmatter under `~/.bcd/memories`.
- Keeps bounded raw Codex debug logs under `~/.bcd/debug/codex-calls.json`.

V1 intentionally does not include a local prediction engine, fallback predictions, SQLite, vector search, or multi-agent debate.

## Requirements

- Node.js and npm
- Codex CLI authenticated on the local machine

The server defaults to the `codex` command, with a macOS app-bundle fallback at `/Applications/Codex.app/Contents/Resources/codex`.

Optional environment variables:

- `BCD_HOME`: override the data directory; defaults to `~/.bcd`
- `BCD_PORT`: override the API port; defaults to `3737`
- `BCD_CODEX_BIN`: override the Codex CLI binary path
- `BCD_CODEX_MODEL`: pass a specific model to `codex exec`
- `BCD_CODEX_TIMEOUT_MS`: Codex call timeout; defaults to `120000`

## Develop

```bash
npm install
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). The Vite dev server proxies API calls to [http://127.0.0.1:3737](http://127.0.0.1:3737).

## Build And Run

```bash
npm run build
npm start
```

Then open [http://127.0.0.1:3737](http://127.0.0.1:3737).

## Verify

```bash
npm run typecheck
npm test
npm run build
```

With a local server already running, the API/Codex smoke path can be checked with:

```bash
BCD_E2E_BASE_URL=http://127.0.0.1:3940 npm run smoke:e2e
```

Set `BCD_E2E_CODEX=0` to skip the real Codex calls and verify only local profile/API behavior.

## Data Layout

All user-owned runtime data lives outside the repository:

```text
~/.bcd/
  profile.md
  config.json
  memories/
    *.md
  feedback/
    *.json
  debug/
    codex-calls.json
  tmp/
```

`config.json` currently supports `debugLogLimit`, which controls how many raw Codex request/response records are retained.
