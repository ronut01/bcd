import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import type { DecisionCard, DecisionCardDraft, FeedbackPayload, NormalizedExternalProfile } from "../shared/types.js";
import { BcdStorage, buildExternalProfileMarkdown, buildProfileMarkdown, gatherCandidateCards } from "./storage.js";

const tempRoots: string[] = [];

async function tempRoot(): Promise<string> {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "bcd-test-"));
  tempRoots.push(root);
  return root;
}

afterEach(async () => {
  await Promise.all(tempRoots.splice(0).map((root) => fs.rm(root, { recursive: true, force: true })));
});

describe("profile storage", () => {
  it("stores onboarding as markdown with MBTI frontmatter", () => {
    const markdown = buildProfileMarkdown(
      {
        mbti: "INTJ",
        preferences: [
          { id: "pace", label: "Decision pace", answer: "Compare tradeoffs" },
          { id: "risk", label: "Risk posture", answer: "Low risk" }
        ]
      },
      "2026-05-12T00:00:00.000Z"
    );

    expect(markdown).toContain('mbti: "INTJ"');
    expect(markdown).toContain("- Decision pace: Compare tradeoffs");
  });

  it("stores external profile imports as raw plus normalized local files", async () => {
    const storage = new BcdStorage(await tempRoot());
    const rawImport = "RAW_IMPORT_SENTINEL_DO_NOT_LEAK: chooses quiet focus over novelty.";

    const result = await storage.writeExternalProfileImport(rawImport, normalizedProfile());
    const profileMarkdown = await storage.readProfileMarkdown();
    const rawMarkdown = await fs.readFile(result.rawImportPath, "utf8");

    expect(profileMarkdown).toContain('profileSource: "external_ai_import"');
    expect(profileMarkdown).toContain("Chooses quiet focus when work quality matters.");
    expect(profileMarkdown).not.toContain("RAW_IMPORT_SENTINEL_DO_NOT_LEAK");
    expect(rawMarkdown).toContain("RAW_IMPORT_SENTINEL_DO_NOT_LEAK");
  });

  it("clears raw profile import without deleting the normalized profile", async () => {
    const storage = new BcdStorage(await tempRoot());
    await storage.writeExternalProfileImport("RAW_IMPORT_SENTINEL_DO_NOT_LEAK", normalizedProfile());

    const cleared = await storage.clearRawProfileImport();
    const metadata = await storage.rawProfileImportMetadata();

    expect(metadata.exists).toBe(false);
    expect(cleared.profileMarkdown).toContain('rawImportStored: false');
    expect(cleared.profileMarkdown).toContain("Chooses quiet focus when work quality matters.");
    expect(cleared.profileMarkdown).not.toContain("RAW_IMPORT_SENTINEL_DO_NOT_LEAK");
  });

  it("builds normalized external profile markdown without raw text", () => {
    const markdown = buildExternalProfileMarkdown(
      normalizedProfile(),
      "/tmp/latest-raw.md",
      "2026-05-12T00:00:00.000Z"
    );

    expect(markdown).toContain("## Choice Patterns");
    expect(markdown).toContain("Chooses quiet focus when work quality matters.");
    expect(markdown).not.toContain("# Raw External AI Profile Import");
  });
});

describe("candidate card gathering", () => {
  it("uses category and tag matches before recent fallback", () => {
    const cards: DecisionCard[] = [
      card("recent-unrelated", "2026-05-12T04:00:00.000Z", "travel", ["solo"]),
      card("category-only", "2026-05-12T03:00:00.000Z", "work", ["focus"]),
      card("tag-only", "2026-05-12T02:00:00.000Z", "food", ["energy"]),
      card("category-tag", "2026-05-12T01:00:00.000Z", "work", ["energy"])
    ];

    const gathered = gatherCandidateCards(cards, { question: "Where work?", options: ["A", "B"], category: "work", tags: ["energy"] });

    expect(gathered.map((entry) => entry.id)).toEqual([
      "category-tag",
      "category-only",
      "tag-only",
      "recent-unrelated"
    ]);
  });

  it("falls back to newest memories when request metadata is absent", () => {
    const cards: DecisionCard[] = [
      card("old", "2026-05-12T01:00:00.000Z", "work", ["focus"]),
      card("new", "2026-05-12T04:00:00.000Z", "travel", ["solo"]),
      card("middle", "2026-05-12T03:00:00.000Z", "food", ["energy"])
    ];

    const gathered = gatherCandidateCards(cards, { question: "What should I do?", options: ["A", "B"] });

    expect(gathered.map((entry) => entry.id)).toEqual(["new", "middle", "old"]);
  });
});

describe("decision card storage", () => {
  it("uses Codex draft category and tags when request metadata is absent", async () => {
    const storage = new BcdStorage(await tempRoot());
    const feedback: FeedbackPayload = {
      request: {
        question: "Tea or coffee?",
        options: ["Tea", "Coffee"]
      },
      prediction: {
        chosenOption: "Tea",
        explanation: "You usually choose calmer rituals.",
        confidence: "medium",
        usedMemoryIds: []
      },
      actualChoice: "Tea",
      reasonTags: [],
      reasonText: "It felt quieter."
    };
    const draft: DecisionCardDraft = {
      title: "Tea as the quieter ritual",
      summary: "The user chose tea for a quieter moment.",
      category: "daily-ritual",
      tags: ["calm", "routine"],
      choicePattern: "Chooses quieter rituals when energy is low.",
      contextSignals: ["Wanted calm"]
    };

    const filePath = await storage.writeDecisionCard(feedback, draft);
    const markdown = await fs.readFile(filePath, "utf8");

    expect(markdown).toContain('category: "daily-ritual"');
    expect(markdown).toContain('tags: ["calm","routine"]');
  });
});

describe("debug log retention", () => {
  it("keeps only the configured number of Codex calls", async () => {
    const storage = new BcdStorage(await tempRoot());
    await storage.ensure();
    await fs.writeFile(storage.paths.config, `${JSON.stringify({ debugLogLimit: 2 })}\n`, "utf8");

    await storage.appendDebugLog({ purpose: "one" });
    await storage.appendDebugLog({ purpose: "two" });
    await storage.appendDebugLog({ purpose: "three" });

    const retained = JSON.parse(await fs.readFile(storage.paths.codexLog, "utf8")) as Array<{ purpose: string }>;
    expect(retained.map((entry) => entry.purpose)).toEqual(["two", "three"]);
  });
});

function card(id: string, createdAt: string, category: string, tags: string[]): DecisionCard {
  return {
    id,
    createdAt,
    category,
    tags,
    question: "Question?",
    actualChoice: "A",
    title: id,
    summary: id,
    body: id,
    fileName: `${id}.md`
  };
}

function normalizedProfile(): NormalizedExternalProfile {
  return {
    summary: "A user who protects focus and chooses calm contexts for important work.",
    choicePatterns: ["Chooses quiet focus when work quality matters."],
    tradeoffSignals: ["Trades novelty away when execution quality is at stake."],
    riskSignals: ["Accepts low-risk novelty after obligations are satisfied."],
    energySignals: ["Protects calm routines when energy is limited."],
    contextSignals: ["Work decisions depend on depth, noise, and recovery time."],
    uncertaintyNotes: ["More real decisions will improve confidence."]
  };
}


describe("adaptive prediction metadata storage", () => {
  it("saveFeedbackRecord stores compact deep metadata without raw prompts or profile text", async () => {
    const storage = new BcdStorage(await tempRoot());
    const feedback = feedbackWithDeepMetadata();

    const id = await storage.saveFeedbackRecord(feedback);
    const files = await fs.readdir(storage.paths.feedback);
    const saved = JSON.parse(await fs.readFile(path.join(storage.paths.feedback, files.find((file) => file.includes(id))!), "utf8"));

    expect(saved.predictionMode).toBe("deep");
    expect(saved.predictionGate.reasons).toEqual(["pre_gate_deep"]);
    expect(saved.panelJudgments).toHaveLength(3);
    expect(JSON.stringify(saved)).not.toContain("RAW_IMPORT_SENTINEL_DO_NOT_LEAK");
    expect(JSON.stringify(saved)).not.toContain("Profile:\n");
  });

  it("writeDecisionCard includes compact mode and gate metadata when present", async () => {
    const storage = new BcdStorage(await tempRoot());
    const filePath = await storage.writeDecisionCard(feedbackWithDeepMetadata(), decisionCardDraft());
    const markdown = await fs.readFile(filePath, "utf8");

    expect(markdown).toContain('predictionMode: "deep"');
    expect(markdown).toContain('predictionGateReasons: ["pre_gate_deep"]');
    expect(markdown).toContain("## Prediction Process");
    expect(markdown).toContain("- Mode: deep");
    expect(markdown).toContain("value_taste_fit: Home desk (high)");
    expect(markdown).toContain("practicality_cost: Home desk (medium)");
    expect(markdown).toContain("risk_regret: Home desk (medium)");
    expect(markdown).not.toContain("RAW_IMPORT_SENTINEL_DO_NOT_LEAK");
    expect(markdown).not.toContain("Profile:\n");
  });

  it("writeDecisionCard keeps fast feedback without metadata valid", async () => {
    const storage = new BcdStorage(await tempRoot());
    const filePath = await storage.writeDecisionCard(
      {
        request: { question: "Tea or coffee?", options: ["Tea", "Coffee"] },
        prediction: {
          chosenOption: "Tea",
          explanation: "You usually choose calmer rituals.",
          confidence: "medium",
          usedMemoryIds: []
        },
        actualChoice: "Tea",
        reasonTags: [],
        reasonText: "It felt quieter."
      },
      decisionCardDraft()
    );
    const markdown = await fs.readFile(filePath, "utf8");

    expect(markdown).toContain('predictedChoice: "Tea"');
    expect(markdown).not.toContain("predictionMode");
    expect(markdown).not.toContain("panelJudgmentRoles");
  });
});

function feedbackWithDeepMetadata(): FeedbackPayload {
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
      stage: "pre",
      score: 100,
      threshold: 0,
      reasons: ["pre_gate_deep"],
      signals: { explicitDeepRequest: true }
    },
    panelJudgments: [
      {
        role: "value_taste_fit",
        recommendedOption: "Home desk",
        rationale: "It matches quiet-focus values.",
        confidence: "high",
        concerns: ["Less novelty."]
      },
      {
        role: "practicality_cost",
        recommendedOption: "Home desk",
        rationale: "It avoids commute cost.",
        confidence: "medium",
        concerns: ["Home distractions."]
      },
      {
        role: "risk_regret",
        recommendedOption: "Home desk",
        rationale: "It minimizes lost-focus regret.",
        confidence: "medium",
        concerns: ["May feel routine."]
      }
    ]
  };
}

function decisionCardDraft(): DecisionCardDraft {
  return {
    title: "Home desk for focus",
    summary: "The user chose quiet focus over novelty.",
    category: "work",
    tags: ["focus"],
    choicePattern: "Chooses quiet focus when work quality matters.",
    contextSignals: ["Needed deep work"]
  };
}
