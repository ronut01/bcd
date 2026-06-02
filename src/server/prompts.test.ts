import { describe, expect, it } from "vitest";
import {
  buildDecisionCardPrompt,
  buildExternalAiProfilePrompt,
  buildOptionSuggestionPrompt,
  buildPredictionPrompt,
  buildPredictionWithMemoryPrompt,
  buildDeepPredictionPrompt,
  buildDeepPredictionWithMemoryPrompt,
  buildProfileImportNormalizationPrompt
} from "./prompts.js";

const RAW_SENTINEL = "RAW_IMPORT_SENTINEL_DO_NOT_LEAK";
const normalizedProfile = [
  "# bcd Profile",
  "",
  "## Summary",
  "Protects quiet focus and chooses calm contexts for demanding work."
].join("\n");

describe("external profile import prompts", () => {
  it("asks the user's usual AI for choice-pattern signals without objective advice", () => {
    const prompt = buildExternalAiProfilePrompt();

    expect(prompt).toContain("personal choice mirror");
    expect(prompt).toContain("choice patterns");
    expect(prompt).toContain("what is objectively best");
    expect(prompt).toContain("plain text");
  });

  it("normalizes freeform imported profiles into strict JSON", () => {
    const prompt = buildProfileImportNormalizationPrompt(`${RAW_SENTINEL}: prefers quiet focus.`);

    expect(prompt).toContain("JSON only");
    expect(prompt).toContain('"choicePatterns"');
    expect(prompt).toContain(RAW_SENTINEL);
  });
});

describe("prediction prompt", () => {
  it("keeps the bcd choice-mirror stance", () => {
    const prompt = buildPredictionPrompt(
      "# Profile\n\n- Decision pace: compare tradeoffs",
      {
        question: "Tea or coffee?",
        options: ["Tea", "Coffee"],
        category: "drink",
        tags: ["energy"]
      },
      [],
      { mode: "deep", stage: "pre", score: 100, threshold: 0, reasons: ["pre_gate_deep"], signals: { explicitDeepRequest: true } }
    );

    expect(prompt).toContain("personal choice mirror");
    expect(prompt).toContain("not an objective advisor");
    expect(prompt).toContain("chosenOption must exactly match");
    expect(prompt).toContain("JSON only");
    expect(prompt).not.toContain("objectively best option");
  });

  it("keeps raw import sentinel out of downstream prompts when only normalized profile is supplied", () => {
    const decision = { question: "Work from home or cafe?", options: ["Home", "Cafe"] };
    const feedback = {
      request: decision,
      prediction: {
        chosenOption: "Home",
        explanation: "You would probably choose the quieter option.",
        confidence: "medium" as const,
        usedMemoryIds: []
      },
      actualChoice: "Home",
      reasonTags: ["focus"],
      reasonText: "Deep work mattered."
    };

    const prompts = [
      buildOptionSuggestionPrompt(normalizedProfile, { question: decision.question, context: "Need focus" }),
      buildPredictionPrompt(normalizedProfile, decision, []),
      buildPredictionWithMemoryPrompt(normalizedProfile, decision, []),
      buildDecisionCardPrompt(normalizedProfile, feedback)
    ];

    for (const prompt of prompts) {
      expect(prompt).not.toContain(RAW_SENTINEL);
      expect(prompt).toContain("Protects quiet focus");
    }
  });

  it("covers a synthetic Top-1 cold-start decision fixture", () => {
    const expectedTop1 = "Home desk";
    const prompt = buildPredictionPrompt(
      [
        "# bcd Profile",
        "",
        "## Choice Patterns",
        "- Chooses quiet focus when work quality matters.",
        "## Tradeoff Signals",
        "- Trades novelty away when execution quality is at stake."
      ].join("\n"),
      {
        question: "Where should I work from tomorrow afternoon?",
        options: [expectedTop1, "Busy cafe"],
        context: "I need deep focus for writing and have no meetings after lunch."
      },
      []
    );

    expect(prompt).toContain(expectedTop1);
    expect(prompt).toContain("Busy cafe");
    expect(prompt).toContain("Chooses quiet focus");
    expect(prompt).toContain("chosenOption must exactly match");
    expect(prompt).not.toContain(RAW_SENTINEL);
  });

  it("treats user-authored wording as grounded weak evidence", () => {
    const prompt = buildPredictionPrompt(
      normalizedProfile,
      {
        question: "Should I stay home where I can finally rest, or go out because I guess I should?",
        options: ["Stay home", "Go out"],
        context: "I keep saying I should go out, but the quiet option sounds easier."
      },
      []
    );

    expect(prompt).toContain("user's own wording");
    expect(prompt).toContain("weak signals");
    expect(prompt).toContain("do not overfit");
    expect(prompt).toContain("Stay home");
  });

  it("can select memories and predict in one fast Codex call", () => {
    const prompt = buildPredictionWithMemoryPrompt(
      normalizedProfile,
      { question: "Work from home or cafe?", options: ["Home", "Cafe"] },
      [
        {
          id: "mem_1",
          createdAt: "2026-05-01T00:00:00.000Z",
          tags: ["focus"],
          actualChoice: "Home",
          title: "Home for focus",
          summary: "Chose home for deep work.",
          body: "",
          fileName: "mem_1.md"
        }
      ]
    );

    expect(prompt).toContain("First select relevant prior memories");
    expect(prompt).toContain("memorySelection");
    expect(prompt).toContain("unselected Candidates as ignored");
    expect(prompt).toContain("prediction.usedMemoryIds");
    expect(prompt).toContain("mem_1");
  });

  it("includes existing options when suggesting additional options", () => {
    const prompt = buildOptionSuggestionPrompt(normalizedProfile, {
      question: "What should I do this weekend?",
      options: ["Stay home", "Go hiking"],
      context: "Low energy but wants something memorable."
    });

    expect(prompt).toContain("additional options");
    expect(prompt).toContain("avoid duplicating");
    expect(prompt).toContain("Stay home");
    expect(prompt).toContain("Go hiking");
  });
});

describe("decision card prompt", () => {
  it("asks Codex to generate memory metadata at save time", () => {
    const prompt = buildDecisionCardPrompt("# Profile", {
      request: {
        question: "Tea or coffee?",
        options: ["Tea", "Coffee"]
      },
      prediction: {
        chosenOption: "Tea",
        explanation: "You would probably choose the calmer option.",
        confidence: "medium",
        usedMemoryIds: []
      },
      actualChoice: "Tea",
      reasonTags: [],
      reasonText: "It felt calmer."
    });

    expect(prompt).toContain('"category":"short-slug"');
    expect(prompt).toContain('"tags":["short-slug"]');
    expect(prompt).toContain("Summarize this completed decision");
  });
});


describe("deep prediction prompt", () => {
  it("includes all panel roles and constrains the raw shape to panelJudgments plus synthesis", () => {
    const prompt = buildDeepPredictionPrompt(
      "# Profile\nProtects quiet focus.",
      { question: "Choose work location", options: ["Home desk", "Cafe"], context: "Need focus" },
      [],
      { mode: "deep", stage: "pre", score: 100, threshold: 0, reasons: ["pre_gate_deep"], signals: { explicitDeepRequest: true } }
    );

    expect(prompt).toContain("value_taste_fit");
    expect(prompt).toContain("practicality_cost");
    expect(prompt).toContain("risk_regret");
    expect(prompt).toContain("panelJudgments");
    expect(prompt).toContain("synthesis");
    expect(prompt).toContain("No extra keys");
  });

  it("requires every recommendation field to exactly match a confirmed option", () => {
    const prompt = buildDeepPredictionPrompt("# Profile", {
      question: "Where work?",
      options: ["Home desk", "Cafe"]
    }, [], { mode: "deep", stage: "pre", score: 100, threshold: 0, reasons: ["pre_gate_deep"], signals: { explicitDeepRequest: true } });

    expect(prompt).toContain("recommendedOption");
    expect(prompt).toContain("synthesis.chosenOption");
    expect(prompt).toContain("exactly match");
    expect(prompt).toContain("Home desk");
    expect(prompt).toContain("Cafe");
  });

  it("asks for concise role outputs to protect latency", () => {
    const prompt = buildDeepPredictionPrompt("# Profile", {
      question: "Where work?",
      options: ["Home desk", "Cafe"]
    }, [], { mode: "deep", stage: "pre", score: 100, threshold: 0, reasons: ["pre_gate_deep"], signals: { explicitDeepRequest: true } });

    expect(prompt.toLowerCase()).toContain("concise");
    expect(prompt.toLowerCase()).toContain("short");
  });

  it("can select memories and run the deep panel in one Codex call", () => {
    const prompt = buildDeepPredictionWithMemoryPrompt(
      normalizedProfile,
      { question: "Where work?", options: ["Home desk", "Cafe"] },
      [
        {
          id: "mem_1",
          createdAt: "2026-05-01T00:00:00.000Z",
          tags: ["focus"],
          actualChoice: "Home desk",
          title: "Home desk for focus",
          summary: "Chose the quiet home desk.",
          body: "",
          fileName: "mem_1.md"
        }
      ],
      { mode: "deep", stage: "pre", score: 100, threshold: 0, reasons: ["pre_gate_deep"], signals: { explicitDeepRequest: true } }
    );

    expect(prompt).toContain("memorySelection");
    expect(prompt).toContain("unselected Candidates as ignored");
    expect(prompt).toContain("panelJudgments");
    expect(prompt).toContain("synthesis.usedMemoryIds");
    expect(prompt).toContain("mem_1");
  });
});
