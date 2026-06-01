import { describe, expect, it } from "vitest";
import type { DecisionRequest, PredictionGate } from "../shared/types.js";
import {
  GATE_REASONS,
  canAttemptDeep,
  codexTimeoutMs,
  deepEscalationBufferMs,
  evaluatePostFastEscalation,
  evaluatePrePredictionGate,
  withInsufficientDeepBudget
} from "./prediction-gate.js";

const baseRequest: DecisionRequest = {
  question: "Tea or coffee?",
  options: ["Tea", "Coffee"]
};

describe("prediction gate", () => {
  it("keeps ordinary low-signal requests on the fast path with an ordinary below-threshold reason", () => {
    const gate = evaluatePrePredictionGate(baseRequest, "# Profile\nChooses calmly.");

    expect(gate.mode).toBe("fast");
    expect(gate.stage).toBe("fast-only");
    expect(gate.threshold).toBe(70);
    expect(gate.reasons).toContain(GATE_REASONS.ordinaryBelowThreshold);
  });

  it("forces explicit deep requests into pre-gated deep mode", () => {
    const gate = evaluatePrePredictionGate(
      { ...baseRequest, question: "Please use deep analysis: tea or coffee?" },
      "# Profile"
    );

    expect(gate).toMatchObject({ mode: "deep", stage: "pre", score: 100, threshold: 0 });
    expect(gate.reasons).toEqual(
      expect.arrayContaining([GATE_REASONS.explicitDeepRequest, GATE_REASONS.preGateDeep])
    );
    expect(gate.signals.explicitDeepRequest).toBe(true);
  });

  it("routes high-stakes requests to deep at the 50-point threshold", () => {
    const gate = evaluatePrePredictionGate(
      { ...baseRequest, question: "Which surgery option should I choose?", category: "health" },
      "# Profile"
    );

    expect(gate.mode).toBe("deep");
    expect(gate.stage).toBe("pre");
    expect(gate.score).toBeGreaterThanOrEqual(50);
    expect(gate.threshold).toBe(50);
    expect(gate.reasons).toContain(GATE_REASONS.highStakes);
  });

  it("scores complexity exactly and caps it at 25", () => {
    const request: DecisionRequest = {
      question: "Q".repeat(251),
      options: ["A", "B", "C", "D"],
      context: "C".repeat(301),
      tags: ["one", "two", "three"]
    };

    const gate = evaluatePrePredictionGate(request, "# Profile");

    expect(gate.signals.complexityScore).toBe(25);
    expect(gate.score).toBe(25);
    expect(gate.reasons).toContain(GATE_REASONS.complexity);
  });

  it("adds profile conflict signal and reason when profile and context plainly conflict", () => {
    const gate = evaluatePrePredictionGate(
      { ...baseRequest, context: "I usually prefer quiet focus, but this option is a loud nightclub with strangers." },
      "# Profile\n## Choice Pattern\n- Chooses quiet focus.\n## Tradeoff Signals\n- Avoids noisy crowded contexts."
    );

    expect(gate.signals.profileConflict).toBe(true);
    expect(gate.score).toBeGreaterThanOrEqual(25);
    expect(gate.reasons).toContain(GATE_REASONS.profileConflict);
  });

  it("escalates low-confidence fast predictions when deep budget remains", () => {
    const preGate = evaluatePrePredictionGate(baseRequest, "# Profile");
    const gate = evaluatePostFastEscalation(preGate, baseRequest, { chosenOption: "Tea", explanation: "Weak signal.", confidence: "low", usedMemoryIds: [] }, 0, 40_000);

    expect(gate.mode).toBe("deep");
    expect(gate.stage).toBe("post-fast");
    expect(gate.reasons).toEqual(
      expect.arrayContaining([GATE_REASONS.lowFastConfidence, GATE_REASONS.postFastEscalation])
    );
    expect(gate.signals.fastConfidence).toBe("low");
  });

  it("escalates medium-confidence high-stakes fast predictions when budget remains", () => {
    const preGate: PredictionGate = {
      mode: "fast",
      stage: "fast-only",
      score: 50,
      threshold: 50,
      reasons: [GATE_REASONS.highStakes],
      signals: { highStakes: true }
    };

    const gate = evaluatePostFastEscalation(preGate, { ...baseRequest, category: "health" }, { chosenOption: "Tea", explanation: "Mixed signal.", confidence: "medium", usedMemoryIds: [] }, 0, 40_000);

    expect(gate.mode).toBe("deep");
    expect(gate.stage).toBe("post-fast");
    expect(gate.reasons).toEqual(
      expect.arrayContaining([GATE_REASONS.mediumConfidenceHighStakes, GATE_REASONS.postFastEscalation])
    );
  });

  it("records insufficient budget when a pre-gated deep request must fall back to fast", () => {
    const deepGate = evaluatePrePredictionGate(
      { ...baseRequest, question: "Please use deep analysis." },
      "# Profile"
    );
    const preGate = withInsufficientDeepBudget(deepGate, 0, 40_001);

    expect(preGate.mode).toBe("fast");
    expect(preGate.stage).toBe("fast-only");
    expect(preGate.reasons).toContain(GATE_REASONS.insufficientDeepBudget);
  });

  it("skips post-fast escalation and records insufficient budget when remaining budget is too low", () => {
    const preGate = evaluatePrePredictionGate(baseRequest, "# Profile");
    const gate = evaluatePostFastEscalation(preGate, baseRequest, { chosenOption: "Tea", explanation: "Weak signal.", confidence: "low", usedMemoryIds: [] }, 0, 40_001);

    expect(gate.mode).toBe("fast");
    expect(gate.stage).toBe("fast-only");
    expect(gate.reasons).toContain(GATE_REASONS.insufficientDeepBudget);
    expect(gate.reasons).not.toContain(GATE_REASONS.postFastEscalation);
  });

  it("requires Codex timeout plus escalation buffer before attempting deep", () => {
    const required = codexTimeoutMs() + deepEscalationBufferMs();
    expect(canAttemptDeep(0, 170_000 - required)).toBe(true);
    expect(canAttemptDeep(0, 170_000 - required + 1)).toBe(false);
  });
});

