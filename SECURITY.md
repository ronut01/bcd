# Security Policy

## Supported Versions

The current public version is `0.1.x`.

## Reporting A Vulnerability

Please report security issues through GitHub private vulnerability reporting if available, or open a minimal issue that does not disclose exploit details.

Useful reports include:

- The affected version or commit
- Impacted local files or API routes
- Reproduction steps
- Whether sensitive local data may be exposed

## Local Data Boundary

bcd stores runtime data under `~/.bcd` by default:

- profile data
- raw profile imports when consented
- decision memories
- feedback records
- Codex debug logs

The repository should not contain user profiles, `.env*` files, `.omx/`, `bcd.md`, `dist/`, or `node_modules/`.
