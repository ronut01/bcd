import type {
  DeepPredictionResult,
  DecisionCardDraft,
  MemorySelection,
  NormalizedExternalProfile,
  OptionSuggestion,
  PanelJudgment,
  PanelJudgmentRole,
  PredictionResult,
  SuggestedOption
} from "../shared/types.js";

const PANEL_ROLES: PanelJudgmentRole[] = ["value_taste_fit", "practicality_cost", "risk_regret"];

export function validateOptionSuggestion(value: unknown): OptionSuggestion {
  const object = asObject(value, "option suggestion");
  const rawOptions = asArray(object.options, "options");
  const options: SuggestedOption[] = rawOptions.map((entry) => {
    const option = asObject(entry, "option");
    return {
      label: asNonEmptyString(option.label, "option.label"),
      notes: optionalString(option.notes)
    };
  });
  if (options.length < 2) {
    throw new Error("Codex must suggest at least two options");
  }
  return {
    options,
    rationale: optionalString(object.rationale)
  };
}

export function validateMemorySelection(value: unknown, allowedIds: Set<string>): MemorySelection {
  const object = asObject(value, "memory selection");
  const selectedMemoryIds = asArray(object.selectedMemoryIds, "selectedMemoryIds")
    .map((entry) => asNonEmptyString(entry, "memory id"))
    .filter((id) => allowedIds.has(id));
  return {
    selectedMemoryIds,
    reasoning: asNonEmptyString(object.reasoning ?? "No relevant prior memory selected.", "reasoning")
  };
}

export function validatePrediction(value: unknown, options: string[], allowedMemoryIds: Set<string>): PredictionResult {
  const object = asObject(value, "prediction");
  const chosenOption = asNonEmptyString(object.chosenOption, "chosenOption");
  if (!options.includes(chosenOption)) {
    throw new Error("chosenOption must exactly match one of the confirmed options");
  }
  const confidence = validateConfidence(object.confidence, "confidence");
  return {
    chosenOption,
    explanation: asNonEmptyString(object.explanation, "explanation"),
    confidence,
    usedMemoryIds: asArray(object.usedMemoryIds, "usedMemoryIds")
      .map((entry) => asNonEmptyString(entry, "usedMemoryIds[]"))
      .filter((id) => allowedMemoryIds.has(id))
  };
}

export function validateDeepPrediction(value: unknown, options: string[], allowedMemoryIds: Set<string>): DeepPredictionResult {
  const object = asObject(value, "deep prediction");
  const keys = Object.keys(object).sort();
  if (keys.join(",") !== "panelJudgments,synthesis") {
    throw new Error("deep prediction must contain only panelJudgments and synthesis");
  }

  const panelJudgments = validatePanelJudgments(object.panelJudgments, options);
  const synthesis = validateStrictPrediction(asObject(object.synthesis, "synthesis"), options, allowedMemoryIds, "synthesis");

  return { panelJudgments, synthesis };
}

export function validateDecisionCardDraft(value: unknown): DecisionCardDraft {
  const object = asObject(value, "decision card");
  return {
    title: asNonEmptyString(object.title, "title"),
    summary: asNonEmptyString(object.summary, "summary"),
    category: asNonEmptyString(object.category, "category"),
    tags: asArray(object.tags, "tags").map((entry) => asNonEmptyString(entry, "tag")),
    choicePattern: asNonEmptyString(object.choicePattern, "choicePattern"),
    contextSignals: asArray(object.contextSignals, "contextSignals").map((entry) =>
      asNonEmptyString(entry, "context signal")
    )
  };
}

export function validateNormalizedExternalProfile(value: unknown): NormalizedExternalProfile {
  const object = asObject(value, "normalized external profile");
  const profile = {
    summary: asNonEmptyString(object.summary, "summary"),
    choicePatterns: nonEmptyStringArray(object.choicePatterns, "choicePatterns"),
    tradeoffSignals: nonEmptyStringArray(object.tradeoffSignals, "tradeoffSignals"),
    riskSignals: nonEmptyStringArray(object.riskSignals, "riskSignals"),
    energySignals: nonEmptyStringArray(object.energySignals, "energySignals"),
    contextSignals: nonEmptyStringArray(object.contextSignals, "contextSignals"),
    uncertaintyNotes: nonEmptyStringArray(object.uncertaintyNotes, "uncertaintyNotes")
  };
  return profile;
}

function validatePanelJudgments(value: unknown, options: string[]): PanelJudgment[] {
  const entries = asArray(value, "panelJudgments");
  if (entries.length !== PANEL_ROLES.length) {
    throw new Error("panelJudgments must contain exactly three role judgments");
  }

  const seen = new Set<PanelJudgmentRole>();
  const judgments = entries.map((entry) => {
    const object = asObject(entry, "panel judgment");
    const role = validatePanelRole(object.role);
    if (seen.has(role)) {
      throw new Error(`duplicate panel judgment role: ${role}`);
    }
    seen.add(role);
    const recommendedOption = asNonEmptyString(object.recommendedOption, "recommendedOption");
    if (!options.includes(recommendedOption)) {
      throw new Error("recommendedOption must exactly match one of the confirmed options");
    }
    return {
      role,
      recommendedOption,
      rationale: asNonEmptyString(object.rationale, "rationale"),
      confidence: validateConfidence(object.confidence, "confidence"),
      concerns: nonEmptyStringArray(object.concerns, "concerns")
    };
  });

  for (const role of PANEL_ROLES) {
    if (!seen.has(role)) {
      throw new Error(`missing panel judgment role: ${role}`);
    }
  }

  return judgments;
}

function validateStrictPrediction(
  object: Record<string, unknown>,
  options: string[],
  allowedMemoryIds: Set<string>,
  label: string
): PredictionResult {
  const chosenOption = asNonEmptyString(object.chosenOption, `${label}.chosenOption`);
  if (!options.includes(chosenOption)) {
    throw new Error(`${label}.chosenOption must exactly match one of the confirmed options`);
  }
  const usedMemoryIds = asArray(object.usedMemoryIds, `${label}.usedMemoryIds`).map((entry) =>
    asNonEmptyString(entry, `${label}.usedMemoryIds[]`)
  );
  const invalidMemoryId = usedMemoryIds.find((id) => !allowedMemoryIds.has(id));
  if (invalidMemoryId) {
    throw new Error(`${label}.usedMemoryIds contains unknown memory id: ${invalidMemoryId}`);
  }

  return {
    chosenOption,
    explanation: asNonEmptyString(object.explanation, `${label}.explanation`),
    confidence: validateConfidence(object.confidence, `${label}.confidence`),
    usedMemoryIds
  };
}

function validatePanelRole(value: unknown): PanelJudgmentRole {
  const role = asNonEmptyString(value, "role");
  if (PANEL_ROLES.includes(role as PanelJudgmentRole)) {
    return role as PanelJudgmentRole;
  }
  throw new Error("role must be value_taste_fit, practicality_cost, or risk_regret");
}

function validateConfidence(value: unknown, label: string): PredictionResult["confidence"] {
  const confidence = asNonEmptyString(value, label);
  if (!["low", "medium", "high"].includes(confidence)) {
    throw new Error(`${label} must be low, medium, or high`);
  }
  return confidence as PredictionResult["confidence"];
}

function asObject(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function asArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array`);
  }
  return value;
}

function nonEmptyStringArray(value: unknown, label: string): string[] {
  const items = asArray(value, label).map((entry) => asNonEmptyString(entry, `${label}[]`));
  if (items.length === 0) {
    throw new Error(`${label} must contain at least one item`);
  }
  return items;
}

function asNonEmptyString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value.trim();
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}
