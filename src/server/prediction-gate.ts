import type { DecisionRequest, PredictionGate, PredictionResult } from "../shared/types.js";

export const PRE_GATE_HIGH_STAKES_THRESHOLD = 50;
export const PRE_GATE_ORDINARY_THRESHOLD = 70;
export const HIGH_STAKES_WEIGHT = 50;
export const PROFILE_CONFLICT_WEIGHT = 25;
export const COMPLEXITY_MAX = 25;

export const GATE_REASONS = {
  explicitDeepRequest: "explicit_deep_request",
  highStakes: "high_stakes",
  complexity: "complexity",
  profileConflict: "profile_conflict",
  lowFastConfidence: "low_fast_confidence",
  mediumConfidenceHighStakes: "medium_confidence_high_stakes",
  insufficientDeepBudget: "insufficient_deep_budget",
  ordinaryBelowThreshold: "ordinary_below_threshold",
  preGateDeep: "pre_gate_deep",
  postFastEscalation: "post_fast_escalation"
} as const;

export type GateReason = (typeof GATE_REASONS)[keyof typeof GATE_REASONS];

const DEFAULT_ROUTE_BUDGET_MS = 170_000;
const DEFAULT_CODEX_TIMEOUT_MS = 120_000;
const DEFAULT_DEEP_BUFFER_MS = 10_000;

const EXPLICIT_DEEP_PATTERNS = [
  /\bdeep(?:er|ly)?\s+(?:mode|analysis|review|judg(?:e|ment)|think|consideration)\b/i,
  /\bgo\s+deep\b/i,
  /\bmore\s+deeply\b/i,
  /\bcarefully\b/i,
  /\bthoroughly\b/i,
  /검토/u,
  /깊게/u,
  /회의/u,
  /신중(?:하게)?/u,
  /자세히/u
];

const HIGH_STAKES_TERMS = [
  "money",
  "expensive",
  "costly",
  "career",
  "job",
  "resign",
  "quit",
  "relationship",
  "marriage",
  "move",
  "relocate",
  "long-term",
  "long term",
  "irreversible",
  "contract",
  "investment",
  "health",
  "medical",
  "college",
  "school",
  "돈",
  "비싼",
  "투자",
  "구매",
  "커리어",
  "직장",
  "이직",
  "퇴사",
  "관계",
  "결혼",
  "이사",
  "장기",
  "되돌릴",
  "계약",
  "건강",
  "병원",
  "학교"
];

export function evaluatePrePredictionGate(request: DecisionRequest, profileMarkdown = ""): PredictionGate {
  const explicitDeepRequest = hasExplicitDeepRequest(request);
  const highStakes = hasHighStakesSignal(request);
  const complexityScore = calculateComplexityScore(request);
  const profileConflict = hasProfileConflictSignal(request, profileMarkdown);
  const threshold = explicitDeepRequest ? 0 : highStakes ? PRE_GATE_HIGH_STAKES_THRESHOLD : PRE_GATE_ORDINARY_THRESHOLD;
  const reasons: string[] = [];

  if (explicitDeepRequest) {
    reasons.push(GATE_REASONS.explicitDeepRequest, GATE_REASONS.preGateDeep);
    return {
      mode: "deep",
      stage: "pre",
      score: 100,
      threshold,
      reasons,
      signals: {
        explicitDeepRequest: true,
        highStakes,
        complexityScore,
        profileConflict
      }
    };
  }

  let score = 0;
  if (highStakes) {
    score += HIGH_STAKES_WEIGHT;
    reasons.push(GATE_REASONS.highStakes);
  }
  if (complexityScore > 0) {
    score += complexityScore;
    reasons.push(GATE_REASONS.complexity);
  }
  if (profileConflict) {
    score += PROFILE_CONFLICT_WEIGHT;
    reasons.push(GATE_REASONS.profileConflict);
  }

  const deep = score >= threshold;
  if (deep) {
    reasons.push(GATE_REASONS.preGateDeep);
  } else if (!highStakes) {
    reasons.push(GATE_REASONS.ordinaryBelowThreshold);
  }

  return {
    mode: deep ? "deep" : "fast",
    stage: deep ? "pre" : "fast-only",
    score,
    threshold,
    reasons: uniqueReasons(reasons),
    signals: {
      explicitDeepRequest: false,
      highStakes,
      complexityScore,
      profileConflict
    }
  };
}

export function evaluatePostFastEscalation(
  baseGate: PredictionGate,
  request: DecisionRequest,
  fastPrediction: PredictionResult,
  routeStartedAt: number,
  now = Date.now()
): PredictionGate {
  const highStakes = baseGate.signals.highStakes ?? hasHighStakesSignal(request);
  const shouldEscalateLowConfidence = fastPrediction.confidence === "low";
  const shouldEscalateHighStakes = highStakes && fastPrediction.confidence !== "high";
  const remainingBudgetMs = remainingRouteBudgetMs(routeStartedAt, now);
  const elapsedMs = Math.max(0, now - routeStartedAt);
  const baseReasons = baseGate.reasons.filter((reason) => reason !== GATE_REASONS.ordinaryBelowThreshold);
  const escalationReasons: string[] = [];

  if (shouldEscalateLowConfidence) {
    escalationReasons.push(GATE_REASONS.lowFastConfidence);
  }
  if (shouldEscalateHighStakes && fastPrediction.confidence === "medium") {
    escalationReasons.push(GATE_REASONS.mediumConfidenceHighStakes);
  }

  if (escalationReasons.length === 0) {
    return {
      ...baseGate,
      mode: "fast",
      stage: "fast-only",
      reasons: uniqueReasons(baseGate.reasons.length ? baseGate.reasons : [GATE_REASONS.ordinaryBelowThreshold]),
      signals: {
        ...baseGate.signals,
        highStakes,
        fastConfidence: fastPrediction.confidence,
        elapsedMs,
        remainingBudgetMs
      }
    };
  }

  if (!canAttemptDeep(routeStartedAt, now)) {
    return {
      ...baseGate,
      mode: "fast",
      stage: "fast-only",
      reasons: uniqueReasons([...baseReasons, ...escalationReasons, GATE_REASONS.insufficientDeepBudget]),
      signals: {
        ...baseGate.signals,
        highStakes,
        fastConfidence: fastPrediction.confidence,
        elapsedMs,
        remainingBudgetMs
      }
    };
  }

  return {
    ...baseGate,
    mode: "deep",
    stage: "post-fast",
    score: Math.max(baseGate.score, baseGate.threshold),
    reasons: uniqueReasons([...baseReasons, ...escalationReasons, GATE_REASONS.postFastEscalation]),
    signals: {
      ...baseGate.signals,
      highStakes,
      fastConfidence: fastPrediction.confidence,
      elapsedMs,
      remainingBudgetMs
    }
  };
}

export function withInsufficientDeepBudget(gate: PredictionGate, routeStartedAt: number, now = Date.now()): PredictionGate {
  return {
    ...gate,
    mode: "fast",
    stage: "fast-only",
    reasons: uniqueReasons([...gate.reasons, GATE_REASONS.insufficientDeepBudget]),
    signals: {
      ...gate.signals,
      elapsedMs: Math.max(0, now - routeStartedAt),
      remainingBudgetMs: remainingRouteBudgetMs(routeStartedAt, now)
    }
  };
}

export function canAttemptDeep(routeStartedAt: number, now = Date.now()): boolean {
  return remainingRouteBudgetMs(routeStartedAt, now) >= codexTimeoutMs() + deepEscalationBufferMs();
}

export function remainingRouteBudgetMs(routeStartedAt: number, now = Date.now()): number {
  return Math.max(0, predictRouteBudgetMs() - Math.max(0, now - routeStartedAt));
}

export function predictRouteBudgetMs(): number {
  return positiveEnvNumber("BCD_PREDICT_ROUTE_BUDGET_MS", DEFAULT_ROUTE_BUDGET_MS);
}

export function codexTimeoutMs(): number {
  return positiveEnvNumber("BCD_CODEX_TIMEOUT_MS", DEFAULT_CODEX_TIMEOUT_MS);
}

export function deepEscalationBufferMs(): number {
  return positiveEnvNumber("BCD_DEEP_ESCALATION_BUFFER_MS", DEFAULT_DEEP_BUFFER_MS);
}

export function calculateComplexityScore(request: DecisionRequest): number {
  let score = 0;
  if (request.options.length >= 4) {
    score += 10;
  }
  if ((request.context?.length ?? 0) > 300) {
    score += 5;
  }
  if (request.question.length > 250) {
    score += 5;
  }
  if ((request.tags?.length ?? 0) >= 3) {
    score += 5;
  }
  return Math.min(score, COMPLEXITY_MAX);
}

export function hasHighStakesSignal(request: DecisionRequest): boolean {
  const haystack = requestText(request);
  return HIGH_STAKES_TERMS.some((term) => haystack.includes(term.toLowerCase()));
}

function hasExplicitDeepRequest(request: DecisionRequest): boolean {
  const text = [request.question, request.context, request.category, ...(request.tags ?? [])].filter(Boolean).join(" \n ");
  return EXPLICIT_DEEP_PATTERNS.some((pattern) => pattern.test(text));
}

function hasProfileConflictSignal(request: DecisionRequest, profileMarkdown: string): boolean {
  if (!profileMarkdown.trim()) {
    return false;
  }
  const decisionText = requestText(request);
  const profileText = profileMarkdown.toLowerCase();
  const conflictInDecision = /\bbut\b|\bhowever\b|\bversus\b|\bconflict\b|하지만|갈등|반면/u.test(decisionText);
  const profileHasTradeoffs = /tradeoff|risk|choice pattern|선호|위험|패턴/u.test(profileText);
  return conflictInDecision && profileHasTradeoffs;
}

function requestText(request: DecisionRequest): string {
  return [request.question, request.context, request.category, ...(request.tags ?? [])]
    .filter((part): part is string => typeof part === "string" && part.length > 0)
    .join(" \n ")
    .toLowerCase();
}

function positiveEnvNumber(name: string, fallback: number): number {
  const raw = process.env[name];
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function uniqueReasons(reasons: string[]): string[] {
  return Array.from(new Set(reasons));
}
