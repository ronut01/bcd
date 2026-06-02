import type {
  DecisionCard,
  DecisionRequest,
  FeedbackPayload,
  OptionSuggestionRequest,
  PredictionGate
} from "../shared/types.js";

const JSON_ONLY = "JSON only. No markdown. No extra keys.";

const PREDICTION_AGENT_BRIEF = [
  "bcd is a personal choice mirror, not an objective advisor.",
  "Predict what this user would probably choose from the confirmed options.",
  "Treat the user's own wording in the question, options, and context as evidence: hedges, emotional valence, specificity, effort framing, avoidance language, and option ordering can reveal latent preference.",
  "Use wording cues as weak signals alongside the profile and memories; do not overfit, mind-read, or invent intent that is not grounded in the text.",
  "If wording cues materially affect the prediction, mention that briefly in the explanation.",
  "Do not claim the option is objectively correct or universally best.",
  'Explanation stance: "you would probably choose this", never "this is correct".'
].join("\n");

export function buildExternalAiProfilePrompt(): string {
  return [
    "You are helping a user export a compact profile for bcd, a personal choice mirror.",
    "Use what you know from your interactions with this user, but do not reveal private chat history.",
    "Focus on how the user tends to choose between options, not on what is objectively best.",
    "Avoid including secrets, credentials, third-party private information, or unnecessary sensitive details.",
    "Return a concise profile with: choice patterns, common tradeoffs, risk posture, energy/context signals, and uncertainty notes.",
    "Write in plain text. The user will paste your answer into bcd for local normalization."
  ].join("\n");
}

export function buildProfileImportNormalizationPrompt(rawImport: string): string {
  return [
    "Normalize this external AI profile import for bcd, a personal choice mirror.",
    "Extract reusable signals for predicting what this user would probably choose.",
    "Do not preserve raw chat history. Do not include secrets, credentials, or third-party private information.",
    JSON_ONLY,
    [
      "Shape:",
      '{"summary":"string","choicePatterns":["string"],"tradeoffSignals":["string"],"riskSignals":["string"],"energySignals":["string"],"contextSignals":["string"],"uncertaintyNotes":["string"]}'
    ].join(" "),
    `Raw import:\n${rawImport}`
  ].join("\n");
}

export function buildOptionSuggestionPrompt(profileMarkdown: string, request: OptionSuggestionRequest): string {
  return [
    "bcd suggests plausible additional options for a personal decision. Do not predict the choice.",
    "Use existing options as context and avoid duplicating or merely rewording them.",
    "Suggest options that could be appended below the existing options.",
    JSON_ONLY,
    'Shape: {"options":[{"label":"string","notes":"string"}],"rationale":"string"}',
    `Profile:\n${profileMarkdown}`,
    `Decision:\n${JSON.stringify(request)}`
  ].join("\n");
}

export function buildPredictionPrompt(
  profileMarkdown: string,
  request: DecisionRequest,
  selectedCards: DecisionCard[]
): string {
  return [
    PREDICTION_AGENT_BRIEF,
    "Pick the option this user would probably choose. chosenOption must exactly match one provided option.",
    JSON_ONLY,
    'Shape: {"chosenOption":"exact option","explanation":"short reason","confidence":"low|medium|high","usedMemoryIds":["memory-id"]}',
    `Profile:\n${profileMarkdown}`,
    `Decision:\n${JSON.stringify(request)}`,
    `Memories:\n${JSON.stringify(selectedCards.map(cardForPrompt))}`
  ].join("\n");
}

export function buildPredictionWithMemoryPrompt(
  profileMarkdown: string,
  request: DecisionRequest,
  candidateCards: DecisionCard[]
): string {
  return [
    PREDICTION_AGENT_BRIEF,
    "First select relevant prior memories from Candidates. Select none if weak.",
    "Then pick the option this user would probably choose. chosenOption must exactly match one provided option.",
    "After memorySelection, treat unselected Candidates as ignored; do not use weak memories as prediction evidence.",
    "prediction.usedMemoryIds must only contain ids from memorySelection.selectedMemoryIds.",
    JSON_ONLY,
    'Shape: {"memorySelection":{"selectedMemoryIds":["memory-id"],"reasoning":"short reason"},"prediction":{"chosenOption":"exact option","explanation":"short reason","confidence":"low|medium|high","usedMemoryIds":["memory-id"]}}',
    `Profile:\n${profileMarkdown}`,
    `Decision:\n${JSON.stringify(request)}`,
    `Candidates:\n${JSON.stringify(candidateCards.map(cardForPrompt))}`
  ].join("\n");
}

export function buildDeepPredictionPrompt(
  profileMarkdown: string,
  request: DecisionRequest,
  selectedCards: DecisionCard[],
  gate: PredictionGate
): string {
  return [
    PREDICTION_AGENT_BRIEF,
    "Use a concise three-role panel before synthesizing the final prediction. These are panel judgments inside one response, not independent processes.",
    "Role value_taste_fit: judge which option best matches the user's preferences, values, profile, and taste.",
    "Role practicality_cost: judge feasibility, effort, time, money, and execution friction.",
    "Role risk_regret: judge downside, reversibility, future regret, and hidden risks.",
    "Synthesis: compare the panel judgments and pick the one option this user would probably choose.",
    "Every recommendedOption and synthesis.chosenOption must exactly match one provided option.",
    "Keep every rationale and concern concise to protect request latency.",
    JSON_ONLY,
    'Shape: {"panelJudgments":[{"role":"value_taste_fit","recommendedOption":"exact option","rationale":"short reason","confidence":"low|medium|high","concerns":["short concern"]},{"role":"practicality_cost","recommendedOption":"exact option","rationale":"short reason","confidence":"low|medium|high","concerns":["short concern"]},{"role":"risk_regret","recommendedOption":"exact option","rationale":"short reason","confidence":"low|medium|high","concerns":["short concern"]}],"synthesis":{"chosenOption":"exact option","explanation":"short reason using the panel judgments","confidence":"low|medium|high","usedMemoryIds":["memory-id"]}}',
    `Deep-mode gate:\n${JSON.stringify(redactGateForPrompt(gate))}`,
    `Profile:\n${profileMarkdown}`,
    `Decision:\n${JSON.stringify(request)}`,
    `Memories:\n${JSON.stringify(selectedCards.map(cardForPrompt))}`
  ].join("\n");
}

export function buildDeepPredictionWithMemoryPrompt(
  profileMarkdown: string,
  request: DecisionRequest,
  candidateCards: DecisionCard[],
  gate: PredictionGate
): string {
  return [
    PREDICTION_AGENT_BRIEF,
    "First select relevant prior memories from Candidates. Select none if weak.",
    "After memorySelection, treat unselected Candidates as ignored; do not use weak memories as prediction evidence.",
    "Use a concise three-role panel before synthesizing the final prediction. These are panel judgments inside one response, not independent processes.",
    "Role value_taste_fit: judge which option best matches the user's preferences, values, profile, taste, and wording cues.",
    "Role practicality_cost: judge feasibility, effort, time, money, and execution friction.",
    "Role risk_regret: judge downside, reversibility, future regret, and hidden risks.",
    "Synthesis: compare the panel judgments and pick the one option this user would probably choose.",
    "Every recommendedOption and synthesis.chosenOption must exactly match one provided option.",
    "synthesis.usedMemoryIds must only contain ids from memorySelection.selectedMemoryIds.",
    "Keep every rationale and concern concise to protect request latency.",
    JSON_ONLY,
    'Shape: {"memorySelection":{"selectedMemoryIds":["memory-id"],"reasoning":"short reason"},"panelJudgments":[{"role":"value_taste_fit","recommendedOption":"exact option","rationale":"short reason","confidence":"low|medium|high","concerns":["short concern"]},{"role":"practicality_cost","recommendedOption":"exact option","rationale":"short reason","confidence":"low|medium|high","concerns":["short concern"]},{"role":"risk_regret","recommendedOption":"exact option","rationale":"short reason","confidence":"low|medium|high","concerns":["short concern"]}],"synthesis":{"chosenOption":"exact option","explanation":"short reason using the panel judgments","confidence":"low|medium|high","usedMemoryIds":["memory-id"]}}',
    `Deep-mode gate:\n${JSON.stringify(redactGateForPrompt(gate))}`,
    `Profile:\n${profileMarkdown}`,
    `Decision:\n${JSON.stringify(request)}`,
    `Candidates:\n${JSON.stringify(candidateCards.map(cardForPrompt))}`
  ].join("\n");
}

export function buildDecisionCardPrompt(profileMarkdown: string, feedback: FeedbackPayload): string {
  return [
    "Summarize this completed decision as a reusable bcd memory. Explain pattern, not correctness.",
    "If predictionMode/predictionGate/panelJudgments are present, use them only as compact evidence about how the prediction was made.",
    JSON_ONLY,
    'Shape: {"title":"string","summary":"string","category":"short-slug","tags":["short-slug"],"choicePattern":"string","contextSignals":["string"]}',
    `Profile:\n${profileMarkdown}`,
    `Feedback:\n${JSON.stringify(feedback)}`
  ].join("\n");
}

function cardForPrompt(card: DecisionCard) {
  return {
    id: card.id,
    createdAt: card.createdAt,
    category: card.category,
    tags: card.tags,
    question: card.question,
    actualChoice: card.actualChoice,
    predictionMode: card.predictionMode,
    summary: card.summary
  };
}

function redactGateForPrompt(gate: PredictionGate) {
  return {
    mode: gate.mode,
    stage: gate.stage,
    score: gate.score,
    threshold: gate.threshold,
    reasons: gate.reasons,
    signals: gate.signals
  };
}
