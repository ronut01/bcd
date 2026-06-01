import { describe, expect, it } from "vitest";
import { buildCodexArgs, CodexCliError, redactCodexLogEntry, redactSensitiveDetails } from "./codex.js";

const RAW_SENTINEL = "RAW_IMPORT_SENTINEL_DO_NOT_LEAK";

describe("Codex CLI args", () => {
  it("uses flags supported by current codex exec", () => {
    const args = buildCodexArgs("/tmp/bcd-output.txt");

    expect(args).toContain("exec");
    expect(args).toContain("--sandbox");
    expect(args).toContain("--ephemeral");
    expect(args).toContain("--ignore-rules");
    expect(args).toContain("--output-last-message");
    expect(args).not.toContain("--ask-for-approval");
  });
});

describe("Codex sensitive redaction", () => {
  it("redacts raw import from all logged Codex channels", () => {
    const redacted = redactCodexLogEntry(
      {
        purpose: "profile_import_normalization",
        prompt: `prompt ${RAW_SENTINEL}`,
        stdout: `stdout ${RAW_SENTINEL}`,
        stderr: `stderr ${RAW_SENTINEL}`,
        finalMessage: `final ${RAW_SENTINEL}`,
        exitCode: 0
      },
      { sensitive: true }
    );

    expect(JSON.stringify(redacted)).not.toContain(RAW_SENTINEL);
    expect(redacted.prompt).toBe("[redacted sensitive Codex prompt]");
    expect(redacted.stdout).toBe("[redacted sensitive Codex output]");
    expect(redacted.stderr).toBe("[redacted sensitive Codex output]");
    expect(redacted.finalMessage).toBe("[redacted sensitive Codex output]");
    expect(redacted.purpose).toBe("profile_import_normalization");
    expect(redacted.exitCode).toBe(0);
  });

  it("redacts client-visible Codex error details for sensitive calls", () => {
    const details = redactSensitiveDetails(`failure ${RAW_SENTINEL}`, { sensitive: true });
    const error = new CodexCliError("Codex CLI failed. No prediction was generated.", details);

    expect(error.details).toBe("[redacted sensitive Codex output]");
    expect(error.details).not.toContain(RAW_SENTINEL);
  });

  it("keeps non-sensitive logs useful", () => {
    const entry = redactCodexLogEntry(
      { prompt: `prompt ${RAW_SENTINEL}`, stdout: "ok", stderr: "", finalMessage: "{}", exitCode: 0 },
      { sensitive: false }
    );

    expect(entry.prompt).toContain(RAW_SENTINEL);
    expect(entry.finalMessage).toBe("{}");
  });
});
