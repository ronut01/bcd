import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type {
  DecisionCard,
  DecisionCardDraft,
  DecisionRequest,
  FeedbackPayload,
  NormalizedExternalProfile,
  OnboardingInput
} from "../shared/types.js";
import {
  frontmatterArray,
  frontmatterString,
  parseFrontmatter,
  slugify,
  stringifyFrontmatter
} from "./markdown.js";

export interface BcdConfig {
  debugLogLimit: number;
}

export interface BcdPaths {
  root: string;
  profile: string;
  profileImports: string;
  latestProfileImportRaw: string;
  memories: string;
  feedback: string;
  debug: string;
  temp: string;
  config: string;
  codexLog: string;
}

const DEFAULT_CONFIG: BcdConfig = {
  debugLogLimit: 20
};

export class BcdStorage {
  readonly paths: BcdPaths;

  constructor(root = process.env.BCD_HOME ?? path.join(os.homedir(), ".bcd")) {
    this.paths = {
      root,
      profile: path.join(root, "profile.md"),
      profileImports: path.join(root, "profile-imports"),
      latestProfileImportRaw: path.join(root, "profile-imports", "latest-raw.md"),
      memories: path.join(root, "memories"),
      feedback: path.join(root, "feedback"),
      debug: path.join(root, "debug"),
      temp: path.join(root, "tmp"),
      config: path.join(root, "config.json"),
      codexLog: path.join(root, "debug", "codex-calls.json")
    };
  }

  async ensure(): Promise<void> {
    await fs.mkdir(this.paths.profileImports, { recursive: true });
    await fs.mkdir(this.paths.memories, { recursive: true });
    await fs.mkdir(this.paths.feedback, { recursive: true });
    await fs.mkdir(this.paths.debug, { recursive: true });
    await fs.mkdir(this.paths.temp, { recursive: true });
    if (!existsSync(this.paths.config)) {
      await fs.writeFile(this.paths.config, `${JSON.stringify(DEFAULT_CONFIG, null, 2)}\n`, "utf8");
    }
  }

  async readConfig(): Promise<BcdConfig> {
    await this.ensure();
    try {
      const parsed = JSON.parse(await fs.readFile(this.paths.config, "utf8")) as Partial<BcdConfig>;
      return {
        debugLogLimit: positiveInteger(parsed.debugLogLimit, DEFAULT_CONFIG.debugLogLimit)
      };
    } catch {
      return DEFAULT_CONFIG;
    }
  }

  async hasProfile(): Promise<boolean> {
    await this.ensure();
    return existsSync(this.paths.profile);
  }

  async readProfileMarkdown(): Promise<string | null> {
    await this.ensure();
    if (!existsSync(this.paths.profile)) {
      return null;
    }
    return fs.readFile(this.paths.profile, "utf8");
  }

  async writeProfile(input: OnboardingInput): Promise<string> {
    await this.ensure();
    const markdown = buildProfileMarkdown(input, new Date().toISOString());
    await fs.writeFile(this.paths.profile, markdown, "utf8");
    return markdown;
  }

  async rawProfileImportMetadata(): Promise<{ exists: boolean; path: string | null }> {
    await this.ensure();
    const exists = existsSync(this.paths.latestProfileImportRaw);
    return {
      exists,
      path: exists ? this.paths.latestProfileImportRaw : null
    };
  }

  async writeExternalProfileImport(rawImport: string, normalized: NormalizedExternalProfile): Promise<{
    profileMarkdown: string;
    rawImportPath: string;
  }> {
    await this.ensure();
    const now = new Date().toISOString();
    const rawMarkdown = stringifyFrontmatter(
      {
        createdAt: now,
        source: "external_ai_import"
      },
      ["# Raw External AI Profile Import", "", rawImport.trim()].join("\n")
    );
    await fs.writeFile(this.paths.latestProfileImportRaw, rawMarkdown, "utf8");

    const profileMarkdown = buildExternalProfileMarkdown(normalized, this.paths.latestProfileImportRaw, now);
    await fs.writeFile(this.paths.profile, profileMarkdown, "utf8");
    return {
      profileMarkdown,
      rawImportPath: this.paths.latestProfileImportRaw
    };
  }

  async clearRawProfileImport(): Promise<{ rawImportPath: string; profileMarkdown: string | null }> {
    await this.ensure();
    await fs.rm(this.paths.latestProfileImportRaw, { force: true });
    const profileMarkdown = await this.readProfileMarkdown();
    if (!profileMarkdown) {
      return {
        rawImportPath: this.paths.latestProfileImportRaw,
        profileMarkdown: null
      };
    }
    const { data, body } = parseFrontmatter(profileMarkdown);
    const clearedAt = new Date().toISOString();
    const updated = stringifyFrontmatter(
      {
        ...data,
        updatedAt: clearedAt,
        rawImportStored: false,
        rawImportPath: undefined,
        rawImportClearedAt: clearedAt
      },
      body
    );
    await fs.writeFile(this.paths.profile, updated, "utf8");
    return {
      rawImportPath: this.paths.latestProfileImportRaw,
      profileMarkdown: updated
    };
  }

  async listDecisionCards(): Promise<DecisionCard[]> {
    await this.ensure();
    const entries = await fs.readdir(this.paths.memories, { withFileTypes: true });
    const cards: DecisionCard[] = [];

    for (const entry of entries) {
      if (!entry.isFile() || !entry.name.endsWith(".md")) {
        continue;
      }
      const filePath = path.join(this.paths.memories, entry.name);
      const markdown = await fs.readFile(filePath, "utf8");
      const { data, body } = parseFrontmatter(markdown);
      const id = frontmatterString(data.id) ?? entry.name.replace(/\.md$/, "");
      const title = extractTitle(body) ?? frontmatterString(data.title) ?? "Decision memory";
      const summary = frontmatterString(data.summary) ?? extractSummary(body);

      cards.push({
        id,
        createdAt: frontmatterString(data.createdAt) ?? new Date(0).toISOString(),
        category: frontmatterString(data.category),
        tags: frontmatterArray(data.tags),
        question: frontmatterString(data.question),
        actualChoice: frontmatterString(data.actualChoice) ?? "Unknown",
        predictedChoice: frontmatterString(data.predictedChoice),
        predictionMode: predictionModeFromFrontmatter(frontmatterString(data.predictionMode)),
        title,
        summary,
        body: body.trim(),
        fileName: entry.name
      });
    }

    return cards.sort(compareNewestFirst);
  }

  async gatherCandidateCards(request: DecisionRequest, limit = 12): Promise<DecisionCard[]> {
    const cards = await this.listDecisionCards();
    return gatherCandidateCards(cards, request, limit);
  }

  async saveFeedbackRecord(payload: FeedbackPayload): Promise<string> {
    await this.ensure();
    const id = `feedback_${Date.now()}_${randomUUID().slice(0, 8)}`;
    const filePath = path.join(this.paths.feedback, `${id}.json`);
    const record = {
      id,
      savedAt: new Date().toISOString(),
      ...payload
    };
    await fs.writeFile(filePath, `${JSON.stringify(record, null, 2)}\n`, "utf8");
    return id;
  }

  async writeDecisionCard(payload: FeedbackPayload, draft: DecisionCardDraft): Promise<string> {
    await this.ensure();
    const createdAt = new Date().toISOString();
    const id = `decision_${Date.now()}_${randomUUID().slice(0, 8)}`;
    const category = normalizeLabel(draft.category || payload.request.category || "uncategorized");
    const tags = uniqueStrings([
      ...draft.tags,
      ...(payload.request.tags ?? []),
      ...payload.reasonTags
    ]).slice(0, 12);
    const title = draft.title || `${payload.actualChoice} choice`;
    const predictionProcess = predictionProcessLines(payload);
    const body = [
      `# ${title}`,
      "",
      draft.summary,
      "",
      "## Choice Pattern",
      draft.choicePattern,
      "",
      "## Context Signals",
      ...draft.contextSignals.map((signal) => `- ${signal}`),
      ...(predictionProcess.length ? ["", "## Prediction Process", ...predictionProcess] : []),
      "",
      "## Feedback",
      `Actual choice: ${payload.actualChoice}`,
      payload.reasonText ? `Reason note: ${payload.reasonText}` : undefined
    ]
      .filter((line): line is string => line !== undefined)
      .join("\n");

    const markdown = stringifyFrontmatter(
      {
        id,
        createdAt,
        category,
        tags,
        question: payload.request.question,
        actualChoice: payload.actualChoice,
        predictedChoice: payload.prediction.chosenOption,
        predictionMode: payload.predictionMode,
        predictionGateReasons: payload.predictionGate?.reasons,
        summary: draft.summary
      },
      body
    );
    const fileName = `${createdAt.replace(/[:.]/g, "-")}-${slugify(title)}.md`;
    const filePath = path.join(this.paths.memories, fileName);
    await fs.writeFile(filePath, markdown, "utf8");
    return filePath;
  }

  async appendDebugLog(entry: unknown): Promise<void> {
    await this.ensure();
    const config = await this.readConfig();
    const existing = await readJsonArray(this.paths.codexLog);
    existing.push(entry);
    const retained = existing.slice(-config.debugLogLimit);
    await fs.writeFile(this.paths.codexLog, `${JSON.stringify(retained, null, 2)}\n`, "utf8");
  }
}

export function buildProfileMarkdown(input: OnboardingInput, now: string): string {
  const preferences = input.preferences
    .filter((item) => item.answer.trim())
    .map((item) => `- ${item.label}: ${item.answer.trim()}`)
    .join("\n");

  const body = [
    "# bcd Profile",
    "",
    "This profile is a lightweight cold-start hint for Codex. It is not a fixed identity model.",
    "",
    "## Preference Signals",
    preferences || "- No preference answers recorded yet."
  ].join("\n");

  return stringifyFrontmatter(
    {
      createdAt: now,
      updatedAt: now,
      mbti: input.mbti
    },
    body
  );
}

export function buildExternalProfileMarkdown(
  profile: NormalizedExternalProfile,
  rawImportPath: string,
  now: string
): string {
  const body = [
    "# bcd Profile",
    "",
    "This profile is a normalized cold-start hint for Codex. It is not a fixed identity model.",
    "",
    "## Summary",
    profile.summary.trim(),
    "",
    "## Choice Patterns",
    markdownList(profile.choicePatterns),
    "",
    "## Tradeoff Signals",
    markdownList(profile.tradeoffSignals),
    "",
    "## Risk Signals",
    markdownList(profile.riskSignals),
    "",
    "## Energy Signals",
    markdownList(profile.energySignals),
    "",
    "## Context Signals",
    markdownList(profile.contextSignals),
    "",
    "## Uncertainty Notes",
    markdownList(profile.uncertaintyNotes)
  ].join("\n");

  return stringifyFrontmatter(
    {
      createdAt: now,
      updatedAt: now,
      profileSource: "external_ai_import",
      rawImportStored: true,
      rawImportPath
    },
    body
  );
}

function markdownList(items: string[]): string {
  const cleaned = items.map((item) => item.trim()).filter(Boolean);
  return cleaned.length ? cleaned.map((item) => `- ${item}`).join("\n") : "- Not enough signal yet.";
}

function predictionModeFromFrontmatter(value: string | undefined): DecisionCard["predictionMode"] {
  return value === "fast" || value === "deep" ? value : undefined;
}

function predictionProcessLines(payload: FeedbackPayload): string[] {
  const lines: string[] = [];
  if (payload.predictionMode) {
    lines.push(`- Mode: ${payload.predictionMode}`);
  }
  if (payload.predictionGate?.reasons.length) {
    lines.push(`- Gate reasons: ${payload.predictionGate.reasons.join(", ")}`);
  }
  if (payload.panelJudgments?.length) {
    lines.push("- Panel judgments:");
    for (const judgment of payload.panelJudgments) {
      lines.push(`  - ${judgment.role}: ${judgment.recommendedOption} (${judgment.confidence})`);
    }
  }
  return lines;
}

export function gatherCandidateCards(cards: DecisionCard[], request: DecisionRequest, limit = 12): DecisionCard[] {
  const category = normalizeLabel(request.category ?? "");
  const requestTags = new Set((request.tags ?? []).map(normalizeLabel).filter(Boolean));

  const categoryAndTag: DecisionCard[] = [];
  const categoryOnly: DecisionCard[] = [];
  const tagOnly: DecisionCard[] = [];
  const recentOnly: DecisionCard[] = [];

  for (const card of cards) {
    const categoryMatches = category !== "" && normalizeLabel(card.category ?? "") === category;
    const tagMatches = card.tags.some((tag) => requestTags.has(normalizeLabel(tag)));

    if (categoryMatches && tagMatches) {
      categoryAndTag.push(card);
    } else if (categoryMatches) {
      categoryOnly.push(card);
    } else if (tagMatches) {
      tagOnly.push(card);
    } else {
      recentOnly.push(card);
    }
  }

  return uniqueCards([
    ...categoryAndTag.sort(compareNewestFirst),
    ...categoryOnly.sort(compareNewestFirst),
    ...tagOnly.sort(compareNewestFirst),
    ...recentOnly.sort(compareNewestFirst)
  ]).slice(0, limit);
}

function compareNewestFirst(left: DecisionCard, right: DecisionCard): number {
  return Date.parse(right.createdAt) - Date.parse(left.createdAt);
}

function uniqueCards(cards: DecisionCard[]): DecisionCard[] {
  const seen = new Set<string>();
  return cards.filter((card) => {
    if (seen.has(card.id)) {
      return false;
    }
    seen.add(card.id);
    return true;
  });
}

function uniqueStrings(values: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const normalized = normalizeLabel(value);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function normalizeLabel(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, "-");
}

function extractTitle(body: string): string | undefined {
  const line = body.split("\n").find((entry) => entry.startsWith("# "));
  return line?.replace(/^#\s+/, "").trim();
}

function extractSummary(body: string): string {
  return body
    .split("\n")
    .map((line) => line.trim())
    .find((line) => line && !line.startsWith("#")) ?? "";
}

function positiveInteger(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : fallback;
}

async function readJsonArray(filePath: string): Promise<unknown[]> {
  try {
    const parsed = JSON.parse(await fs.readFile(filePath, "utf8"));
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}
