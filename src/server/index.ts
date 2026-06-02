import fs from "node:fs/promises";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { CodexCliError, CodexClient } from "./codex.js";
import {
  buildDecisionCardPrompt,
  buildDeepPredictionPrompt,
  buildDeepPredictionWithMemoryPrompt,
  buildExternalAiProfilePrompt,
  buildOptionSuggestionPrompt,
  buildPredictionPrompt,
  buildPredictionWithMemoryPrompt,
  buildProfileImportNormalizationPrompt
} from "./prompts.js";
import {
  canAttemptDeep,
  evaluatePostFastEscalation,
  evaluatePrePredictionGate,
  withInsufficientDeepBudget
} from "./prediction-gate.js";
import { BcdStorage } from "./storage.js";
import {
  validateDecisionCardDraft,
  validateDeepPrediction,
  validateDeepPredictionWithMemorySelection,
  validateNormalizedExternalProfile,
  validateOptionSuggestion,
  validatePrediction,
  validatePredictionWithMemorySelection
} from "./validators.js";
import type {
  DecisionRequest,
  DecisionCard,
  ExternalProfileImportRequest,
  FeedbackPayload,
  MemorySelection,
  OnboardingInput,
  PanelJudgment,
  PanelJudgmentRole,
  PredictionGate,
  PredictionMode
} from "../shared/types.js";

const PORT = Number(process.env.BCD_PORT ?? 3737);
const serverDir = path.dirname(fileURLToPath(import.meta.url));
const defaultStaticDir = path.resolve(serverDir, "../../client");
const MAX_RAW_IMPORT_CHARS = 100_000;

export interface CodexJsonRunner {
  checkConnection(): Promise<unknown>;
  runJson<T>(purpose: string, prompt: string, validate: (value: unknown) => T, options?: { sensitive?: boolean }): Promise<T>;
}

export interface BcdServerOptions {
  storage?: BcdStorage;
  codex?: CodexJsonRunner;
  staticDir?: string;
}

export function createBcdServer(options: BcdServerOptions = {}) {
  const storage = options.storage ?? new BcdStorage();
  const codex = options.codex ?? new CodexClient(storage);
  const staticDir = options.staticDir ?? defaultStaticDir;

  async function route(request: IncomingMessage, response: ServerResponse): Promise<void> {
    const url = new URL(request.url ?? "/", `http://${request.headers.host ?? "127.0.0.1"}`);

    if (url.pathname === "/api/health" && request.method === "GET") {
      sendJson(response, 200, { ok: true, dataDir: storage.paths.root });
      return;
    }

    if (url.pathname === "/api/bootstrap" && request.method === "GET") {
      const profileMarkdown = await storage.readProfileMarkdown();
      const memories = await storage.listDecisionCards();
      const rawImport = await storage.rawProfileImportMetadata();
      sendJson(response, 200, {
        hasProfile: profileMarkdown !== null,
        profileMarkdown,
        memoryCount: memories.length,
        dataDir: storage.paths.root,
        hasRawProfileImport: rawImport.exists,
        rawProfileImportPath: rawImport.path
      });
      return;
    }

    if (url.pathname === "/api/codex/check" && request.method === "POST") {
      sendJson(response, 200, await codex.checkConnection());
      return;
    }

    if (url.pathname === "/api/profile-import/prompt" && request.method === "GET") {
      sendJson(response, 200, { prompt: buildExternalAiProfilePrompt() });
      return;
    }

    if (url.pathname === "/api/profile-import" && request.method === "POST") {
      const input = validateExternalProfileImport(await readJson(request));
      const prompt = buildProfileImportNormalizationPrompt(input.rawImport);
      const normalized = await codex.runJson(
        "profile_import_normalization",
        prompt,
        validateNormalizedExternalProfile,
        { sensitive: true }
      );
      const result = await storage.writeExternalProfileImport(input.rawImport, normalized);
      sendJson(response, 201, result);
      return;
    }

    if (url.pathname === "/api/profile-import/raw" && request.method === "DELETE") {
      const result = await storage.clearRawProfileImport();
      sendJson(response, 200, {
        cleared: true,
        rawImportPath: null,
        profileMarkdown: result.profileMarkdown
      });
      return;
    }

    if (url.pathname === "/api/onboarding" && request.method === "POST") {
      const input = validateOnboarding(await readJson(request));
      const profileMarkdown = await storage.writeProfile(input);
      sendJson(response, 201, { profileMarkdown });
      return;
    }

    if (url.pathname === "/api/profile" && request.method === "GET") {
      const profileMarkdown = await storage.readProfileMarkdown();
      if (!profileMarkdown) {
        sendJson(response, 404, { error: "No profile exists yet." });
        return;
      }
      const rawImport = await storage.rawProfileImportMetadata();
      sendJson(response, 200, {
        profileMarkdown,
        path: storage.paths.profile,
        hasRawProfileImport: rawImport.exists,
        rawProfileImportPath: rawImport.path
      });
      return;
    }

    if (url.pathname === "/api/memories" && request.method === "GET") {
      sendJson(response, 200, { memories: await storage.listDecisionCards() });
      return;
    }

    if (url.pathname === "/api/options/suggest" && request.method === "POST") {
      const profileMarkdown = await requireProfile();
      const body = asRecord(await readJson(request));
      const question = nonEmptyString(body.question, "question");
      const options = optionalStringArray(body.options);
      const context = optionalString(body.context);
      const prompt = buildOptionSuggestionPrompt(profileMarkdown, { question, options, context });
      const suggestion = await codex.runJson("option_suggestion", prompt, validateOptionSuggestion);
      sendJson(response, 200, suggestion);
      return;
    }

    if (url.pathname === "/api/predict" && request.method === "POST") {
      const routeStartedAt = Date.now();
      const profileMarkdown = await requireProfile();
      const body = asRecord(await readJson(request));
      if (body.confirmedOptions !== true) {
        sendJson(response, 400, { error: "Confirm the options before asking for a prediction." });
        return;
      }
      const decision = validateDecisionRequest(body.request);
      const candidates = await storage.gatherCandidateCards(decision);
      const candidateIds = new Set(candidates.map((card) => card.id));
      const preGate = evaluatePrePredictionGate(decision, profileMarkdown);

      const runDeepPrediction = async (gate: PredictionGate, selection: MemorySelection, selectedCards: DecisionCard[]) => {
        const selectedIds = new Set(selectedCards.map((card) => card.id));
        const deepPrompt = buildDeepPredictionPrompt(profileMarkdown, decision, selectedCards, gate);
        const deepPrediction = await codex.runJson("prediction_deep", deepPrompt, (value) =>
          validateDeepPrediction(value, decision.options, selectedIds)
        );
        sendJson(response, 200, {
          prediction: deepPrediction.synthesis,
          memorySelection: selection,
          candidateMemoryCount: candidates.length,
          mode: "deep",
          gate: { ...gate, mode: "deep" },
          panelJudgments: deepPrediction.panelJudgments
        });
      };

      if (preGate.mode === "deep" && canAttemptDeep(routeStartedAt)) {
        if (candidates.length === 0) {
          await runDeepPrediction(preGate, noCandidateMemorySelection(), []);
          return;
        }

        const deepPrompt = buildDeepPredictionWithMemoryPrompt(profileMarkdown, decision, candidates, preGate);
        const deepPrediction = await codex.runJson("prediction_deep", deepPrompt, (value) =>
          validateDeepPredictionWithMemorySelection(value, decision.options, candidateIds)
        );
        sendJson(response, 200, {
          prediction: deepPrediction.synthesis,
          memorySelection: deepPrediction.memorySelection,
          candidateMemoryCount: candidates.length,
          mode: "deep",
          gate: { ...preGate, mode: "deep" },
          panelJudgments: deepPrediction.panelJudgments
        });
        return;
      }

      const gateForFast = preGate.mode === "deep"
        ? withInsufficientDeepBudget(preGate, routeStartedAt)
        : preGate;
      const fastResult = candidates.length === 0
        ? {
            memorySelection: noCandidateMemorySelection(),
            prediction: await codex.runJson("prediction", buildPredictionPrompt(profileMarkdown, decision, []), (value) =>
              validatePrediction(value, decision.options, new Set<string>())
            )
          }
        : await codex.runJson(
            "prediction",
            buildPredictionWithMemoryPrompt(profileMarkdown, decision, candidates),
            (value) => validatePredictionWithMemorySelection(value, decision.options, candidateIds)
          );
      const selectedCards = cardsSelectedBy(fastResult.memorySelection, candidates);
      const prediction = fastResult.prediction;
      const postGate = evaluatePostFastEscalation(gateForFast, decision, prediction, routeStartedAt);

      if (postGate.mode === "deep") {
        await runDeepPrediction(postGate, fastResult.memorySelection, selectedCards);
        return;
      }

      sendJson(response, 200, {
        prediction,
        memorySelection: fastResult.memorySelection,
        candidateMemoryCount: candidates.length,
        mode: "fast",
        gate: { ...postGate, mode: "fast" }
      });
      return;
    }

    if (url.pathname === "/api/feedback" && request.method === "POST") {
      const payload = validateFeedback(await readJson(request));
      const feedbackId = await storage.saveFeedbackRecord(payload);
      queueDecisionCardGeneration(payload);
      sendJson(response, 202, {
        saved: true,
        feedbackId,
        cardStatus: "queued"
      });
      return;
    }

    await serveStatic(url.pathname, response);
  }

  async function requireProfile(): Promise<string> {
    const profileMarkdown = await storage.readProfileMarkdown();
    if (!profileMarkdown) {
      throw new HttpError(409, "Create a profile before using Codex decisions.");
    }
    return profileMarkdown;
  }

  function queueDecisionCardGeneration(payload: FeedbackPayload): void {
    setTimeout(() => {
      void (async () => {
        const profileMarkdown = (await storage.readProfileMarkdown()) ?? "";
        const prompt = buildDecisionCardPrompt(profileMarkdown, payload);
        const draft = await codex.runJson("decision_card", prompt, validateDecisionCardDraft);
        await storage.writeDecisionCard(payload, draft);
      })().catch((error) => {
        void storage.appendDebugLog({
          at: new Date().toISOString(),
          purpose: "decision_card_background_error",
          error: error instanceof Error ? error.message : String(error)
        });
      });
    }, 0);
  }

  function noCandidateMemorySelection(): MemorySelection {
    return {
      selectedMemoryIds: [],
      reasoning: "No prior decision memories exist yet."
    };
  }

  function cardsSelectedBy(selection: MemorySelection, candidates: DecisionCard[]): DecisionCard[] {
    const selectedIds = new Set(selection.selectedMemoryIds);
    return candidates.filter((card) => selectedIds.has(card.id));
  }

  async function serveStatic(pathname: string, response: ServerResponse): Promise<void> {
    const requested = pathname === "/" ? "/index.html" : pathname;
    const safePath = path.normalize(requested).replace(/^(\.\.[/\\])+/, "");
    const filePath = path.join(staticDir, safePath);
    const fallbackPath = path.join(staticDir, "index.html");

    try {
      const content = await fs.readFile(filePath);
      response.writeHead(200, { "Content-Type": contentType(filePath) });
      response.end(content);
    } catch {
      try {
        const fallback = await fs.readFile(fallbackPath);
        response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        response.end(fallback);
      } catch {
        response.writeHead(404, { "Content-Type": "application/json; charset=utf-8" });
        response.end(JSON.stringify({ error: "Frontend build not found. Run npm run dev or npm run build." }));
      }
    }
  }

  const server = createServer((request, response) => {
    void route(request, response).catch((error) => handleError(response, error));
  });

  return server;
}

async function startDefaultServer(): Promise<void> {
  const storage = new BcdStorage();
  await storage.ensure();
  const server = createBcdServer({ storage, codex: new CodexClient(storage) });
  server.listen(PORT, "127.0.0.1", () => {
    console.log(`bcd API listening on http://127.0.0.1:${PORT}`);
    console.log(`bcd data directory: ${storage.paths.root}`);
  });
}

async function readJson(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    if (Buffer.concat(chunks).length > 1_000_000) {
      throw new HttpError(413, "Request body is too large.");
    }
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  return raw ? JSON.parse(raw) : {};
}

function sendJson(response: ServerResponse, status: number, value: unknown): void {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store"
  });
  response.end(JSON.stringify(value));
}

function handleError(response: ServerResponse, error: unknown): void {
  if (error instanceof HttpError) {
    sendJson(response, error.status, { error: error.message });
    return;
  }
  if (error instanceof CodexCliError) {
    sendJson(response, 502, {
      error: error.message,
      details: error.details
    });
    return;
  }
  if (error instanceof SyntaxError) {
    sendJson(response, 400, { error: "Invalid JSON request body." });
    return;
  }
  console.error(error);
  sendJson(response, 500, { error: "Unexpected server error." });
}

class HttpError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

function validateExternalProfileImport(value: unknown): ExternalProfileImportRequest {
  const object = asRecord(value);
  const rawImport = nonEmptyString(object.rawImport, "rawImport");
  if (rawImport.length > MAX_RAW_IMPORT_CHARS) {
    throw new HttpError(400, `rawImport must be ${MAX_RAW_IMPORT_CHARS} characters or fewer.`);
  }
  if (object.rawStorageConsent !== true) {
    throw new HttpError(400, "Confirm local raw import storage before saving.");
  }
  return { rawImport, rawStorageConsent: true };
}

function validateOnboarding(value: unknown): OnboardingInput {
  const object = asRecord(value);
  const mbti = nonEmptyString(object.mbti, "mbti").toUpperCase();
  const preferences = arrayValue(object.preferences, "preferences").map((entry) => {
    const pref = asRecord(entry);
    return {
      id: nonEmptyString(pref.id, "preference.id"),
      label: nonEmptyString(pref.label, "preference.label"),
      answer: nonEmptyString(pref.answer, "preference.answer")
    };
  });
  if (preferences.length < 3) {
    throw new HttpError(400, "Answer at least three preference questions.");
  }
  return { mbti, preferences };
}

function validateDecisionRequest(value: unknown): DecisionRequest {
  const object = asRecord(value);
  const options = arrayValue(object.options, "options")
    .map((entry) => nonEmptyString(entry, "option"))
    .filter(Boolean);
  if (options.length < 2) {
    throw new HttpError(400, "Enter at least two options.");
  }
  return {
    question: nonEmptyString(object.question, "question"),
    options,
    context: optionalString(object.context),
    category: optionalString(object.category),
    tags: optionalStringArray(object.tags)
  };
}

function validateFeedback(value: unknown): FeedbackPayload {
  const object = asRecord(value);
  const request = validateDecisionRequest(object.request);
  const prediction = asRecord(object.prediction);
  const feedback: FeedbackPayload = {
    request,
    prediction: {
      chosenOption: nonEmptyString(prediction.chosenOption, "prediction.chosenOption"),
      explanation: nonEmptyString(prediction.explanation, "prediction.explanation"),
      confidence: validateConfidence(prediction.confidence),
      usedMemoryIds: optionalStringArray(prediction.usedMemoryIds)
    },
    actualChoice: nonEmptyString(object.actualChoice, "actualChoice"),
    reasonTags: optionalStringArray(object.reasonTags),
    reasonText: optionalString(object.reasonText)
  };
  const predictionMode = optionalPredictionMode(object.predictionMode);
  const predictionGate = optionalPredictionGate(object.predictionGate);
  const panelJudgments = optionalPanelJudgments(object.panelJudgments, request.options);

  if (predictionMode) {
    feedback.predictionMode = predictionMode;
  }
  if (predictionGate) {
    feedback.predictionGate = predictionGate;
  }
  if (panelJudgments) {
    feedback.panelJudgments = panelJudgments;
  }

  return feedback;
}

function validateConfidence(value: unknown): "low" | "medium" | "high" {
  if (value === "low" || value === "medium" || value === "high") {
    return value;
  }
  throw new HttpError(400, "prediction.confidence must be low, medium, or high.");
}

function optionalPredictionMode(value: unknown): PredictionMode | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (value === "fast" || value === "deep") {
    return value;
  }
  throw new HttpError(400, "predictionMode must be fast or deep.");
}

function optionalPredictionGate(value: unknown): PredictionGate | undefined {
  if (value === undefined) {
    return undefined;
  }
  const object = asRecord(value);
  const mode = optionalPredictionMode(object.mode);
  if (!mode) {
    throw new HttpError(400, "predictionGate.mode is required.");
  }
  const stage = validateGateStage(object.stage);
  const signals = asRecord(object.signals ?? {});
  return {
    mode,
    stage,
    score: finiteNumber(object.score, "predictionGate.score"),
    threshold: finiteNumber(object.threshold, "predictionGate.threshold"),
    reasons: optionalStringArray(object.reasons),
    signals: {
      explicitDeepRequest: optionalBoolean(signals.explicitDeepRequest),
      highStakes: optionalBoolean(signals.highStakes),
      complexityScore: optionalNumber(signals.complexityScore),
      profileConflict: optionalBoolean(signals.profileConflict),
      fastConfidence: optionalConfidence(signals.fastConfidence),
      elapsedMs: optionalNumber(signals.elapsedMs),
      remainingBudgetMs: optionalNumber(signals.remainingBudgetMs)
    }
  };
}

function optionalPanelJudgments(value: unknown, options: string[]): PanelJudgment[] | undefined {
  if (value === undefined) {
    return undefined;
  }
  const seen = new Set<PanelJudgmentRole>();
  const judgments = arrayValue(value, "panelJudgments").map((entry) => {
    const object = asRecord(entry);
    const role = validatePanelRole(object.role);
    if (seen.has(role)) {
      throw new HttpError(400, `Duplicate panelJudgments.role: ${role}.`);
    }
    seen.add(role);
    const recommendedOption = nonEmptyString(object.recommendedOption, "panelJudgments.recommendedOption");
    if (!options.includes(recommendedOption)) {
      throw new HttpError(400, "panelJudgments.recommendedOption must match a confirmed option.");
    }
    return {
      role,
      recommendedOption,
      rationale: nonEmptyString(object.rationale, "panelJudgments.rationale"),
      confidence: validateConfidence(object.confidence),
      concerns: requiredStringArray(object.concerns, "panelJudgments.concerns")
    };
  });
  for (const role of ["value_taste_fit", "practicality_cost", "risk_regret"] satisfies PanelJudgmentRole[]) {
    if (!seen.has(role)) {
      throw new HttpError(400, `Missing panelJudgments.role: ${role}.`);
    }
  }
  return judgments;
}

function validateGateStage(value: unknown): PredictionGate["stage"] {
  if (value === "pre" || value === "post-fast" || value === "fast-only") {
    return value;
  }
  throw new HttpError(400, "predictionGate.stage must be pre, post-fast, or fast-only.");
}

function validatePanelRole(value: unknown): PanelJudgmentRole {
  if (value === "value_taste_fit" || value === "practicality_cost" || value === "risk_regret") {
    return value;
  }
  throw new HttpError(400, "panelJudgments.role must be value_taste_fit, practicality_cost, or risk_regret.");
}

function finiteNumber(value: unknown, label: string): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  throw new HttpError(400, `${label} must be a number.`);
}

function optionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function optionalBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function optionalConfidence(value: unknown): "low" | "medium" | "high" | undefined {
  if (value === undefined) {
    return undefined;
  }
  return validateConfidence(value);
}

function asRecord(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new HttpError(400, "Expected a JSON object.");
  }
  return value as Record<string, unknown>;
}

function arrayValue(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new HttpError(400, `${label} must be an array.`);
  }
  return value;
}

function optionalStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((entry): entry is string => typeof entry === "string" && entry.trim() !== "").map((entry) => entry.trim());
}

function requiredStringArray(value: unknown, label: string): string[] {
  const items = optionalStringArray(value);
  if (!Array.isArray(value) || items.length === 0) {
    throw new HttpError(400, `${label} must be a non-empty array.`);
  }
  return items;
}

function nonEmptyString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new HttpError(400, `${label} is required.`);
  }
  return value.trim();
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function contentType(filePath: string): string {
  if (filePath.endsWith(".html")) {
    return "text/html; charset=utf-8";
  }
  if (filePath.endsWith(".js")) {
    return "text/javascript; charset=utf-8";
  }
  if (filePath.endsWith(".css")) {
    return "text/css; charset=utf-8";
  }
  if (filePath.endsWith(".svg")) {
    return "image/svg+xml";
  }
  return "application/octet-stream";
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await startDefaultServer();
}
