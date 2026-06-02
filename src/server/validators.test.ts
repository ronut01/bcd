import { describe, expect, it } from "vitest";
import {
  validateDeepPrediction,
  validateDeepPredictionWithMemorySelection,
  validateNormalizedExternalProfile,
  validatePrediction,
  validatePredictionWithMemorySelection
} from "./validators.js";

describe("normalized external profile validator", () => {
  it("accepts a complete normalized profile", () => {
    expect(validateNormalizedExternalProfile(validProfile()).choicePatterns).toEqual([
      "Chooses quiet focus when work quality matters."
    ]);
  });

  it("rejects missing required sections", () => {
    expect(() => validateNormalizedExternalProfile({ ...validProfile(), riskSignals: undefined })).toThrow(
      "riskSignals must be an array"
    );
  });

  it("rejects empty signal arrays", () => {
    expect(() => validateNormalizedExternalProfile({ ...validProfile(), choicePatterns: [] })).toThrow(
      "choicePatterns must contain at least one item"
    );
  });
});

describe("deep prediction validator", () => {
  it("accepts exactly three required role judgments and a valid synthesis", () => {
    const validated = validateDeepPrediction(validDeepPrediction(), ["Home desk", "Cafe"], new Set(["mem_1"]));

    expect(validated.panelJudgments.map((judgment) => judgment.role)).toEqual([
      "value_taste_fit",
      "practicality_cost",
      "risk_regret"
    ]);
    expect(validated.synthesis.chosenOption).toBe("Home desk");
    expect(validated.synthesis.usedMemoryIds).toEqual(["mem_1"]);
  });

  it("rejects a missing role judgment", () => {
    const raw = validDeepPrediction();
    raw.panelJudgments = raw.panelJudgments.filter((judgment) => judgment.role !== "risk_regret");

    expect(() => validateDeepPrediction(raw, ["Home desk", "Cafe"], new Set(["mem_1"]))).toThrow(/risk_regret|exactly three/i);
  });

  it("rejects duplicate role judgments", () => {
    const raw = validDeepPrediction();
    raw.panelJudgments[2] = { ...raw.panelJudgments[0] };

    expect(() => validateDeepPrediction(raw, ["Home desk", "Cafe"], new Set(["mem_1"]))).toThrow(/duplicate|risk_regret|exactly three/i);
  });

  it("rejects unknown roles", () => {
    const raw = validDeepPrediction();
    raw.panelJudgments[0].role = "objective_advisor";

    expect(() => validateDeepPrediction(raw, ["Home desk", "Cafe"], new Set(["mem_1"]))).toThrow(/role/i);
  });

  it("rejects role recommendations that do not exactly match confirmed options", () => {
    const raw = validDeepPrediction();
    raw.panelJudgments[0].recommendedOption = "Library";

    expect(() => validateDeepPrediction(raw, ["Home desk", "Cafe"], new Set(["mem_1"]))).toThrow(/recommendedOption|option/i);
  });

  it("rejects synthesis choices that do not exactly match confirmed options", () => {
    const raw = validDeepPrediction();
    raw.synthesis.chosenOption = "Library";

    expect(() => validateDeepPrediction(raw, ["Home desk", "Cafe"], new Set(["mem_1"]))).toThrow(/chosenOption|option/i);
  });

  it("rejects invalid confidence values in role or synthesis output", () => {
    const invalidRole = validDeepPrediction();
    invalidRole.panelJudgments[0].confidence = "certain";
    expect(() => validateDeepPrediction(invalidRole, ["Home desk", "Cafe"], new Set(["mem_1"]))).toThrow(/confidence/i);

    const invalidSynthesis = validDeepPrediction();
    invalidSynthesis.synthesis.confidence = "certain";
    expect(() => validateDeepPrediction(invalidSynthesis, ["Home desk", "Cafe"], new Set(["mem_1"]))).toThrow(/confidence/i);
  });

  it("rejects non-array and empty concerns", () => {
    const nonArray = validDeepPrediction();
    nonArray.panelJudgments[0].concerns = "none";
    expect(() => validateDeepPrediction(nonArray, ["Home desk", "Cafe"], new Set(["mem_1"]))).toThrow(/concerns/i);

    const empty = validDeepPrediction();
    empty.panelJudgments[0].concerns = [];
    expect(() => validateDeepPrediction(empty, ["Home desk", "Cafe"], new Set(["mem_1"]))).toThrow(/concerns/i);
  });

  it("rejects usedMemoryIds outside the allowed memory set", () => {
    const raw = validDeepPrediction();
    raw.synthesis.usedMemoryIds = ["mem_2"];

    expect(() => validateDeepPrediction(raw, ["Home desk", "Cafe"], new Set(["mem_1"]))).toThrow(/usedMemoryIds|memory/i);
  });

  it("rejects extra top-level raw deep keys", () => {
    const raw = { ...validDeepPrediction(), objectiveAdvice: "Pick the best one." };

    expect(() => validateDeepPrediction(raw, ["Home desk", "Cafe"], new Set(["mem_1"]))).toThrow(/only panelJudgments and synthesis|extra|keys|schema/i);
  });
});

describe("fast prediction validator", () => {
  it("keeps existing fast-path validation behavior", () => {
    expect(
      validatePrediction(
        { chosenOption: "Tea", explanation: "Calmer ritual.", confidence: "medium", usedMemoryIds: ["mem_1", "mem_2"] },
        ["Tea", "Coffee"],
        new Set(["mem_1"])
      )
    ).toEqual({ chosenOption: "Tea", explanation: "Calmer ritual.", confidence: "medium", usedMemoryIds: ["mem_1"] });

    expect(() =>
      validatePrediction(
        { chosenOption: "Juice", explanation: "", confidence: "certain", usedMemoryIds: [] },
        ["Tea", "Coffee"],
        new Set()
      )
    ).toThrow();
  });

  it("validates combined memory selection plus fast prediction output", () => {
    const validated = validatePredictionWithMemorySelection(
      {
        memorySelection: { selectedMemoryIds: ["mem_1", "mem_2"], reasoning: "Quiet focus memory is relevant." },
        prediction: {
          chosenOption: "Tea",
          explanation: "Calmer ritual.",
          confidence: "medium",
          usedMemoryIds: ["mem_1", "mem_2"]
        }
      },
      ["Tea", "Coffee"],
      new Set(["mem_1"])
    );

    expect(validated.memorySelection.selectedMemoryIds).toEqual(["mem_1"]);
    expect(validated.prediction.usedMemoryIds).toEqual(["mem_1"]);
  });
});

describe("combined deep prediction validator", () => {
  it("requires synthesis memories to be selected memories", () => {
    const raw = {
      memorySelection: { selectedMemoryIds: ["mem_1"], reasoning: "Relevant." },
      ...validDeepPrediction()
    };

    expect(validateDeepPredictionWithMemorySelection(raw, ["Home desk", "Cafe"], new Set(["mem_1"]))).toMatchObject({
      memorySelection: { selectedMemoryIds: ["mem_1"] },
      synthesis: { usedMemoryIds: ["mem_1"] }
    });

    raw.memorySelection.selectedMemoryIds = [];
    expect(() => validateDeepPredictionWithMemorySelection(raw, ["Home desk", "Cafe"], new Set(["mem_1"]))).toThrow(
      /usedMemoryIds|memory/i
    );
  });
});

function validDeepPrediction() {
  return {
    panelJudgments: [
      {
        role: "value_taste_fit",
        recommendedOption: "Home desk",
        rationale: "It best matches the user's quiet-focus pattern.",
        confidence: "high",
        concerns: ["May feel routine."]
      },
      {
        role: "practicality_cost",
        recommendedOption: "Home desk",
        rationale: "It avoids travel time and setup cost.",
        confidence: "medium",
        concerns: ["Requires avoiding home distractions."]
      },
      {
        role: "risk_regret",
        recommendedOption: "Home desk",
        rationale: "It minimizes regret around lost focus.",
        confidence: "medium",
        concerns: ["Less novelty."]
      }
    ],
    synthesis: {
      chosenOption: "Home desk",
      explanation: "The panels converge on quiet focus over novelty.",
      confidence: "high",
      usedMemoryIds: ["mem_1"]
    }
  };
}

function validProfile() {
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
