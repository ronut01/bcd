import { existsSync } from "node:fs";
import fs from "node:fs/promises";
import { spawn } from "node:child_process";
import path from "node:path";
import type { CodexConnectionStatus } from "../shared/types.js";
import type { BcdStorage } from "./storage.js";

export class CodexCliError extends Error {
  constructor(message: string, readonly details?: string) {
    super(message);
    this.name = "CodexCliError";
  }
}

export class CodexClient {
  constructor(private readonly storage: BcdStorage) {}

  async checkConnection(): Promise<CodexConnectionStatus> {
    const command = process.env.BCD_CODEX_BIN ?? defaultCodexCommand();
    const checkedAt = new Date().toISOString();
    const version = await runProcess(command, ["--version"], "", "10000");

    if (version.exitCode !== 0) {
      return {
        ok: false,
        checkedAt,
        command,
        details: version.stderr || version.stdout || "Codex CLI version check failed."
      };
    }

    const outputPath = path.join(this.storage.paths.temp, `codex_connection_${Date.now()}.txt`);
    const args = buildCodexArgs(outputPath);
    const prompt = 'Return only this JSON object: {"ok":true}';
    const execution = await runProcess(command, args, prompt, process.env.BCD_CODEX_CHECK_TIMEOUT_MS ?? "60000");
    const finalMessage = existsSync(outputPath) ? await fs.readFile(outputPath, "utf8") : execution.stdout;
    await fs.rm(outputPath, { force: true });

    await this.storage.appendDebugLog({
      at: checkedAt,
      purpose: "codex_connection_check",
      command,
      version: version.stdout.trim(),
      exitCode: execution.exitCode,
      stdout: truncate(execution.stdout),
      stderr: truncate(execution.stderr),
      finalMessage: truncate(finalMessage)
    });

    if (execution.exitCode !== 0) {
      return {
        ok: false,
        checkedAt,
        command,
        version: version.stdout.trim(),
        details: execution.stderr || execution.stdout || "Codex CLI execution check failed."
      };
    }

    try {
      const parsed = parseJson(finalMessage) as { ok?: unknown };
      return {
        ok: parsed.ok === true,
        checkedAt,
        command,
        version: version.stdout.trim(),
        details: parsed.ok === true ? undefined : "Codex CLI responded, but not with the expected readiness JSON."
      };
    } catch (error) {
      return {
        ok: false,
        checkedAt,
        command,
        version: version.stdout.trim(),
        details: error instanceof Error ? error.message : "Codex CLI readiness response could not be parsed."
      };
    }
  }

  async runJson<T>(
    purpose: string,
    prompt: string,
    validate: (value: unknown) => T,
    options: { sensitive?: boolean } = {}
  ): Promise<T> {
    const startedAt = Date.now();
    const outputPath = path.join(this.storage.paths.temp, `${purpose}_${Date.now()}.txt`);
    const command = process.env.BCD_CODEX_BIN ?? defaultCodexCommand();
    const args = buildCodexArgs(outputPath);

    const execution = await runProcess(command, args, prompt, process.env.BCD_CODEX_TIMEOUT_MS);
    const finalMessage = existsSync(outputPath) ? await fs.readFile(outputPath, "utf8") : execution.stdout;
    const logEntry = redactCodexLogEntry({
      at: new Date().toISOString(),
      purpose,
      command,
      args,
      durationMs: Date.now() - startedAt,
      prompt,
      stdout: truncate(execution.stdout),
      stderr: truncate(execution.stderr),
      finalMessage: truncate(finalMessage),
      exitCode: execution.exitCode
    }, options);

    await this.storage.appendDebugLog(logEntry);
    await fs.rm(outputPath, { force: true });

    if (execution.exitCode !== 0) {
      throw new CodexCliError(
        "Codex CLI failed. No prediction was generated.",
        redactSensitiveDetails(execution.stderr || execution.stdout, options)
      );
    }

    try {
      return validate(parseJson(finalMessage));
    } catch (error) {
      const message = redactSensitiveDetails(
        error instanceof Error ? error.message : "Unknown JSON validation error",
        options
      );
      throw new CodexCliError("Codex CLI returned invalid JSON. No prediction was generated.", message);
    }
  }
}

export function redactCodexLogEntry<T extends Record<string, unknown>>(
  entry: T,
  options: { sensitive?: boolean } = {}
): T {
  if (!options.sensitive) {
    return entry;
  }
  return {
    ...entry,
    prompt: "[redacted sensitive Codex prompt]",
    stdout: redactSensitiveDetails(String(entry.stdout ?? ""), options),
    stderr: redactSensitiveDetails(String(entry.stderr ?? ""), options),
    finalMessage: redactSensitiveDetails(String(entry.finalMessage ?? ""), options)
  };
}

export function redactSensitiveDetails(value: string | undefined, options: { sensitive?: boolean } = {}): string {
  if (!value) {
    return "";
  }
  return options.sensitive ? "[redacted sensitive Codex output]" : value;
}

export function buildCodexArgs(outputPath: string): string[] {
  const args = [
    "exec",
    "--sandbox",
    "read-only",
    "--ephemeral",
    "--ignore-rules",
    "--color",
    "never",
    "--output-last-message",
    outputPath
  ];

  if (process.env.BCD_CODEX_MODEL) {
    args.push("-m", process.env.BCD_CODEX_MODEL);
  }

  args.push("-");
  return args;
}

function defaultCodexCommand(): string {
  const appBundle = "/Applications/Codex.app/Contents/Resources/codex";
  return existsSync(appBundle) ? appBundle : "codex";
}

function runProcess(
  command: string,
  args: string[],
  input: string,
  timeoutMsRaw: string | undefined
): Promise<{ stdout: string; stderr: string; exitCode: number }> {
  const timeoutMs = Number(timeoutMsRaw ?? 120_000);

  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: ["pipe", "pipe", "pipe"],
      env: process.env
    });

    let stdout = "";
    let stderr = "";
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
    }, Number.isFinite(timeoutMs) && timeoutMs > 0 ? timeoutMs : 120_000);

    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(new CodexCliError("Codex CLI could not be started.", error.message));
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (timedOut) {
        resolve({ stdout, stderr: `${stderr}\nCodex CLI timed out.`, exitCode: 124 });
        return;
      }
      resolve({ stdout, stderr, exitCode: code ?? 1 });
    });

    child.stdin.end(input);
  });
}

function parseJson(text: string): unknown {
  const trimmed = text.trim();
  if (!trimmed) {
    throw new Error("Empty Codex response");
  }

  const withoutFence = trimmed
    .replace(/^```json\s*/i, "")
    .replace(/^```\s*/i, "")
    .replace(/\s*```$/i, "")
    .trim();

  try {
    return JSON.parse(withoutFence);
  } catch {
    const start = withoutFence.indexOf("{");
    const end = withoutFence.lastIndexOf("}");
    if (start === -1 || end === -1 || end <= start) {
      throw new Error("Response did not contain a JSON object");
    }
    return JSON.parse(withoutFence.slice(start, end + 1));
  }
}

function truncate(value: string, limit = 25_000): string {
  return value.length > limit ? `${value.slice(0, limit)}\n[truncated]` : value;
}
