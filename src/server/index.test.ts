import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { AddressInfo } from "node:net";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CodexCliError, redactSensitiveDetails } from "./codex.js";
import { createBcdServer, type CodexJsonRunner } from "./index.js";
import { BcdStorage } from "./storage.js";

const RAW_SENTINEL = "RAW_IMPORT_SENTINEL_DO_NOT_LEAK";
const tempRoots: string[] = [];

async function tempRoot(): Promise<string> {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "bcd-route-test-"));
  tempRoots.push(root);
  return root;
}

afterEach(async () => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  await Promise.all(tempRoots.splice(0).map((root) => fs.rm(root, { recursive: true, force: true })));
});

describe("profile import routes", () => {
  it("returns the external AI import prompt", async () => {
    const app = await testApp();
    try {
      const result = await app.request("GET", "/api/profile-import/prompt");

      expect(result.status).toBe(200);
      expect(result.payload.prompt).toContain("personal choice mirror");
      expect(result.payload.prompt).toContain("choice patterns");
    } finally {
      await app.close();
    }
  });

  it("requires raw storage consent and writes no files on validation failure", async () => {
    const app = await testApp();
    try {
      const result = await app.request("POST", "/api/profile-import", {
        rawImport: `${RAW_SENTINEL}: prefers calm focus.`,
        rawStorageConsent: false
      });

      expect(result.status).toBe(400);
      expect(await app.storage.readProfileMarkdown()).toBeNull();
      await expect(fs.stat(app.storage.paths.latestProfileImportRaw)).rejects.toThrow();
    } finally {
      await app.close();
    }
  });

  it("normalizes, stores raw import, and exposes bootstrap metadata", async () => {
    const fakeCodex = new FakeCodex();
    const app = await testApp(fakeCodex);
    try {
      const result = await app.request("POST", "/api/profile-import", {
        rawImport: `${RAW_SENTINEL}: prefers calm focus.`,
        rawStorageConsent: true
      });

      expect(result.status).toBe(201);
      expect(result.payload.profileMarkdown).toContain('profileSource: "external_ai_import"');
      expect(result.payload.profileMarkdown).not.toContain(RAW_SENTINEL);
      expect(fakeCodex.lastOptions).toEqual({ sensitive: true });

      const raw = await fs.readFile(app.storage.paths.latestProfileImportRaw, "utf8");
      expect(raw).toContain(RAW_SENTINEL);

      const bootstrap = await app.request("GET", "/api/bootstrap");
      expect(bootstrap.payload.hasProfile).toBe(true);
      expect(bootstrap.payload.hasRawProfileImport).toBe(true);
      expect(bootstrap.payload.rawProfileImportPath).toBe(app.storage.paths.latestProfileImportRaw);
    } finally {
      await app.close();
    }
  });

  it("redacts client-visible details when normalization fails", async () => {
    const app = await testApp(new FailingCodex());
    try {
      const result = await app.request("POST", "/api/profile-import", {
        rawImport: `${RAW_SENTINEL}: prefers calm focus.`,
        rawStorageConsent: true
      });

      expect(result.status).toBe(502);
      expect(JSON.stringify(result.payload)).not.toContain(RAW_SENTINEL);
      expect(await app.storage.readProfileMarkdown()).toBeNull();
    } finally {
      await app.close();
    }
  });

  it("clears raw import without deleting normalized profile", async () => {
    const app = await testApp();
    try {
      await app.request("POST", "/api/profile-import", {
        rawImport: `${RAW_SENTINEL}: prefers calm focus.`,
        rawStorageConsent: true
      });

      const cleared = await app.request("DELETE", "/api/profile-import/raw");
      expect(cleared.status).toBe(200);
      expect(cleared.payload.profileMarkdown).toContain('rawImportStored: false');
      expect(cleared.payload.profileMarkdown).not.toContain(RAW_SENTINEL);
      await expect(fs.stat(app.storage.paths.latestProfileImportRaw)).rejects.toThrow();

      const bootstrap = await app.request("GET", "/api/bootstrap");
      expect(bootstrap.payload.hasProfile).toBe(true);
      expect(bootstrap.payload.hasRawProfileImport).toBe(false);
    } finally {
      await app.close();
    }
  });
});

describe("manual onboarding route", () => {
  it("preserves the existing MBTI plus three preferences contract", async () => {
    const app = await testApp();
    try {
      const invalid = await app.request("POST", "/api/onboarding", {
        mbti: "INTJ",
        preferences: [
          { id: "pace", label: "Decision pace", answer: "Compare tradeoffs" },
          { id: "risk", label: "Risk posture", answer: "Low risk" }
        ]
      });
      expect(invalid.status).toBe(400);

      const valid = await app.request("POST", "/api/onboarding", {
        mbti: "INTJ",
        preferences: [
          { id: "pace", label: "Decision pace", answer: "Compare tradeoffs" },
          { id: "risk", label: "Risk posture", answer: "Low risk" },
          { id: "energy", label: "Energy signal", answer: "Protect calm" }
        ]
      });
      expect(valid.status).toBe(201);
      expect(valid.payload.profileMarkdown).toContain('mbti: "INTJ"');
    } finally {
      await app.close();
    }
  });
});


describe("prediction route adaptive modes", () => {
  it("returns the existing fast prediction contract plus mode and gate metadata", async () => {
    const fakeCodex = new FakeCodex();
    const app = await testApp(fakeCodex);
    try {
      await seedProfile(app.storage);
      const result = await app.request("POST", "/api/predict", {
        confirmedOptions: true,
        request: { question: "Tea or coffee?", options: ["Tea", "Coffee"], category: "drink" }
      });

      expect(result.status).toBe(200);
      expect(result.payload.prediction.chosenOption).toBe("Tea");
      expect(result.payload.memorySelection.selectedMemoryIds).toHaveLength(1);
      expect(result.payload.candidateMemoryCount).toBe(1);
      expect(result.payload.mode).toBe("fast");
      expect(result.payload.gate).toMatchObject({ mode: "fast", stage: "fast-only" });
      expect(fakeCodex.purposes).toEqual(["memory_selection", "prediction"]);
    } finally {
      await app.close();
    }
  });

  it("pre-gated deep predictions return panel judgments and map synthesis to the public prediction", async () => {
    const fakeCodex = new FakeCodex();
    const app = await testApp(fakeCodex);
    try {
      await seedProfile(app.storage);
      const result = await app.request("POST", "/api/predict", {
        confirmedOptions: true,
        request: { question: "Please use deep analysis: Home desk or Cafe?", options: ["Home desk", "Cafe"] }
      });

      expect(result.status).toBe(200);
      expect(result.payload.mode).toBe("deep");
      expect(result.payload.gate).toMatchObject({ mode: "deep", stage: "pre" });
      expect(result.payload.panelJudgments).toHaveLength(3);
      expect(result.payload.prediction).toMatchObject({
        chosenOption: "Home desk",
        explanation: expect.stringContaining("quiet focus"),
        confidence: "high",
        usedMemoryIds: expect.any(Array)
      });
      expect(fakeCodex.purposes).toContain("prediction_deep");
      expect(fakeCodex.purposes).not.toContain("prediction");
    } finally {
      await app.close();
    }
  });

  it("escalates a low-confidence fast prediction to deep when budget allows", async () => {
    const fakeCodex = new FakeCodex({ fastPrediction: { confidence: "low" } });
    const app = await testApp(fakeCodex);
    try {
      await seedProfile(app.storage);
      const result = await app.request("POST", "/api/predict", {
        confirmedOptions: true,
        request: { question: "Tea or coffee?", options: ["Tea", "Coffee"] }
      });

      expect(result.status).toBe(200);
      expect(result.payload.mode).toBe("deep");
      expect(result.payload.gate.stage).toBe("post-fast");
      expect(result.payload.gate.reasons).toEqual(expect.arrayContaining(["low_fast_confidence", "post_fast_escalation"]));
      expect(fakeCodex.purposes).toEqual(["memory_selection", "prediction", "prediction_deep"]);
    } finally {
      await app.close();
    }
  });

  it("routes high-stakes medium-confidence decisions through deep mode when budget allows", async () => {
    const fakeCodex = new FakeCodex({ fastPrediction: { confidence: "medium" } });
    const app = await testApp(fakeCodex);
    try {
      await seedProfile(app.storage);
      const result = await app.request("POST", "/api/predict", {
        confirmedOptions: true,
        request: { question: "Which medical treatment should I choose?", options: ["Treatment A", "Treatment B"] }
      });

      expect(result.status).toBe(200);
      expect(result.payload.mode).toBe("deep");
      expect(["pre", "post-fast"]).toContain(result.payload.gate.stage);
      expect(result.payload.gate.reasons).toEqual(expect.arrayContaining(["high_stakes"]));
    } finally {
      await app.close();
    }
  });

  it("falls back to fast when a pre-gated deep request has insufficient remaining budget", async () => {
    vi.useFakeTimers();
    const start = new Date("2026-05-15T00:00:00.000Z").getTime();
    vi.setSystemTime(start);
    const fakeCodex = new FakeCodex({ afterPurpose: { memory_selection: () => vi.setSystemTime(start + 169_000) } });
    const app = await testApp(fakeCodex);
    try {
      await seedProfile(app.storage);
      const result = await app.request("POST", "/api/predict", {
        confirmedOptions: true,
        request: { question: "Please use deep analysis: Tea or Coffee?", options: ["Tea", "Coffee"] }
      });

      expect(result.status).toBe(200);
      expect(result.payload.mode).toBe("fast");
      expect(result.payload.gate.reasons).toContain("insufficient_deep_budget");
      expect(fakeCodex.purposes).toEqual(["memory_selection", "prediction"]);
    } finally {
      await app.close();
    }
  });

  it("skips post-fast escalation when remaining budget is insufficient", async () => {
    vi.useFakeTimers();
    const start = new Date("2026-05-15T00:00:00.000Z").getTime();
    vi.setSystemTime(start);
    const fakeCodex = new FakeCodex({
      fastPrediction: { confidence: "low" },
      afterPurpose: { prediction: () => vi.setSystemTime(start + 169_000) }
    });
    const app = await testApp(fakeCodex);
    try {
      await seedProfile(app.storage);
      const result = await app.request("POST", "/api/predict", {
        confirmedOptions: true,
        request: { question: "Tea or coffee?", options: ["Tea", "Coffee"] }
      });

      expect(result.status).toBe(200);
      expect(result.payload.mode).toBe("fast");
      expect(result.payload.prediction.confidence).toBe("low");
      expect(result.payload.gate.reasons).toContain("insufficient_deep_budget");
      expect(fakeCodex.purposes).toEqual(["memory_selection", "prediction"]);
    } finally {
      await app.close();
    }
  });

  it("preserves Codex validation failures as 502 responses", async () => {
    const app = await testApp(new FailingCodex());
    try {
      await seedProfile(app.storage);
      const result = await app.request("POST", "/api/predict", {
        confirmedOptions: true,
        request: { question: "Tea or coffee?", options: ["Tea", "Coffee"] }
      });

      expect(result.status).toBe(502);
      expect(result.payload.error).toContain("Codex CLI failed");
    } finally {
      await app.close();
    }
  });

  it("preserves optional prediction metadata through feedback validation", async () => {
    const fakeCodex = new FakeCodex();
    const app = await testApp(fakeCodex);
    try {
      await seedProfile(app.storage);
      const payload = feedbackWithDeepMetadata();
      const result = await app.request("POST", "/api/feedback", payload);

      expect(result.status).toBe(202);
      const files = await fs.readdir(app.storage.paths.feedback);
      const saved = JSON.parse(await fs.readFile(path.join(app.storage.paths.feedback, files[0]), "utf8"));
      expect(saved.predictionMode).toBe("deep");
      expect(saved.predictionGate.reasons).toContain("post_fast_escalation");
      expect(saved.panelJudgments).toHaveLength(3);
      await new Promise((resolve) => setTimeout(resolve, 25));
    } finally {
      await app.close();
    }
  });

  it("rejects malformed feedback panel metadata before storage", async () => {
    const app = await testApp(new FakeCodex());
    try {
      await seedProfile(app.storage);
      const payload = feedbackWithDeepMetadata();
      payload.panelJudgments[2] = { ...payload.panelJudgments[0] };
      const result = await app.request("POST", "/api/feedback", payload);

      expect(result.status).toBe(400);
      expect(result.payload.error).toContain("Duplicate panelJudgments.role");
      const files = await fs.readdir(app.storage.paths.feedback);
      expect(files).toHaveLength(0);
    } finally {
      await app.close();
    }
  });
});

async function testApp(codex: CodexJsonRunner = new FakeCodex()) {
  const storage = new BcdStorage(await tempRoot());
  const server = createBcdServer({ storage, codex, staticDir: path.join(await tempRoot(), "empty-static") });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    storage,
    async request(method: string, pathname: string, body?: unknown) {
      const response = await fetch(`http://127.0.0.1:${port}${pathname}`, {
        method,
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body)
      });
      const payload = await response.json().catch(() => ({}));
      return { status: response.status, payload };
    },
    close: () => new Promise<void>((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())))
  };
}

class FakeCodex implements CodexJsonRunner {
  lastOptions: { sensitive?: boolean } | undefined;
  purposes: string[] = [];

  constructor(
    private readonly options: {
      fastPrediction?: Partial<{ chosenOption: string; explanation: string; confidence: "low" | "medium" | "high"; usedMemoryIds: string[] }>;
      afterPurpose?: Record<string, () => void>;
    } = {}
  ) {}

  async checkConnection(): Promise<unknown> {
    return { ok: true, checkedAt: new Date().toISOString(), command: "fake-codex" };
  }

  async runJson<T>(purpose: string, prompt: string, validate: (value: unknown) => T, options?: { sensitive?: boolean }): Promise<T> {
    this.lastOptions = options;
    this.purposes.push(purpose);
    const raw = this.rawForPurpose(purpose, prompt);
    this.options.afterPurpose?.[purpose]?.();
    return validate(raw);
  }

  private rawForPurpose(purpose: string, prompt: string): unknown {
    if (purpose === "profile_import_normalization") {
      return normalizedProfile();
    }
    if (purpose === "memory_selection") {
      return { selectedMemoryIds: [firstCandidateId(prompt) ?? "mem_1"], reasoning: "Prior quiet-focus memory is relevant." };
    }
    if (purpose === "prediction") {
      return {
        chosenOption: this.options.fastPrediction?.chosenOption ?? firstOption(prompt) ?? "Tea",
        explanation: this.options.fastPrediction?.explanation ?? "You usually choose the calmer ritual.",
        confidence: this.options.fastPrediction?.confidence ?? "medium",
        usedMemoryIds: this.options.fastPrediction?.usedMemoryIds ?? [firstMemoryId(prompt) ?? "mem_1"]
      };
    }
    if (purpose === "prediction_deep") {
      return deepPredictionRaw(firstOption(prompt) ?? "Home desk", firstMemoryId(prompt) ?? "mem_1");
    }
    if (purpose === "decision_card") {
      return {
        title: "Tea as the quieter ritual",
        summary: "The user chose tea for a quieter moment.",
        category: "daily-ritual",
        tags: ["calm", "routine"],
        choicePattern: "Chooses quieter rituals when energy is low.",
        contextSignals: ["Wanted calm"]
      };
    }
    throw new Error(`Unexpected fake Codex purpose: ${purpose}`);
  }
}

async function seedProfile(storage: BcdStorage): Promise<void> {
  await storage.writeExternalProfileImport("quiet focus", normalizedProfile());
  await storage.writeDecisionCard(
    {
      request: { question: "Where should I work?", options: ["Home desk", "Cafe"], category: "work", tags: ["focus"] },
      prediction: { chosenOption: "Home desk", explanation: "Quiet focus.", confidence: "high", usedMemoryIds: [] },
      actualChoice: "Home desk",
      reasonTags: ["focus"],
      reasonText: "Needed quiet."
    },
    {
      title: "Home desk for focus",
      summary: "Chose the quiet home desk for demanding work.",
      category: "work",
      tags: ["focus"],
      choicePattern: "Chooses quiet focus when work quality matters.",
      contextSignals: ["Deep work needed"]
    }
  );
}

function normalizedProfile() {
  return {
    summary: "Protects quiet focus and chooses calm contexts for demanding work.",
    choicePatterns: ["Chooses quiet focus when work quality matters."],
    tradeoffSignals: ["Trades novelty away when execution quality is at stake."],
    riskSignals: ["Accepts low-risk novelty after obligations are satisfied."],
    energySignals: ["Protects calm routines when energy is limited."],
    contextSignals: ["Work decisions depend on depth, noise, and recovery time."],
    uncertaintyNotes: ["More real decisions will improve confidence."]
  };
}

function deepPredictionRaw(chosenOption = "Home desk", memoryId = "mem_1") {
  return {
    panelJudgments: [
      {
        role: "value_taste_fit",
        recommendedOption: chosenOption,
        rationale: "It best matches the user's quiet-focus pattern.",
        confidence: "high",
        concerns: ["May feel routine."]
      },
      {
        role: "practicality_cost",
        recommendedOption: chosenOption,
        rationale: "It avoids travel time and setup cost.",
        confidence: "medium",
        concerns: ["Requires avoiding home distractions."]
      },
      {
        role: "risk_regret",
        recommendedOption: chosenOption,
        rationale: "It minimizes regret around lost focus.",
        confidence: "medium",
        concerns: ["Less novelty."]
      }
    ],
    synthesis: {
      chosenOption,
      explanation: "The panel judgments converge on quiet focus over novelty.",
      confidence: "high",
      usedMemoryIds: [memoryId]
    }
  };
}


function firstOption(prompt: string): string | undefined {
  const match = prompt.match(/Decision:\n({.*})\nMemories:/s);
  if (!match) return undefined;
  try {
    const parsed = JSON.parse(match[1]) as { options?: string[] };
    return parsed.options?.[0];
  } catch {
    return undefined;
  }
}

function firstCandidateId(prompt: string): string | undefined {
  const match = prompt.match(/Candidates:\n(\[.*\])$/s);
  if (!match) return undefined;
  try {
    const parsed = JSON.parse(match[1]) as Array<{ id?: string }>;
    return parsed[0]?.id;
  } catch {
    return undefined;
  }
}

function firstMemoryId(prompt: string): string | undefined {
  const match = prompt.match(/Memories:\n(\[.*\])$/s);
  if (!match) return undefined;
  try {
    const parsed = JSON.parse(match[1]) as Array<{ id?: string }>;
    return parsed[0]?.id;
  } catch {
    return undefined;
  }
}

function feedbackWithDeepMetadata() {
  return {
    request: { question: "Where work?", options: ["Home desk", "Cafe"], category: "work", tags: ["focus"] },
    prediction: {
      chosenOption: "Home desk",
      explanation: "The panels converge on quiet focus.",
      confidence: "high",
      usedMemoryIds: ["mem_1"]
    },
    actualChoice: "Home desk",
    reasonTags: ["focus"],
    reasonText: "Quiet mattered.",
    predictionMode: "deep",
    predictionGate: {
      mode: "deep",
      stage: "post-fast",
      score: 75,
      threshold: 70,
      reasons: ["low_fast_confidence", "post_fast_escalation"],
      signals: { fastConfidence: "low", remainingBudgetMs: 130_001 }
    },
    panelJudgments: deepPredictionRaw().panelJudgments
  };
}

class FailingCodex extends FakeCodex {
  override async runJson<T>(_: string, __: string, ___: (value: unknown) => T, options?: { sensitive?: boolean }): Promise<T> {
    throw new CodexCliError(
      "Codex CLI failed. No prediction was generated.",
      redactSensitiveDetails(`stderr echoed ${RAW_SENTINEL}`, options)
    );
  }
}
