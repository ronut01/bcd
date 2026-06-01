export type Confidence = "low" | "medium" | "high";

export interface PreferenceAnswer {
  id: string;
  label: string;
  answer: string;
}

export interface OnboardingInput {
  mbti: string;
  preferences: PreferenceAnswer[];
}

export interface ExternalProfileImportRequest {
  rawImport: string;
  rawStorageConsent: true;
}

export interface ExternalProfileImportResponse {
  profileMarkdown: string;
  rawImportPath: string | null;
}

export interface NormalizedExternalProfile {
  summary: string;
  choicePatterns: string[];
  tradeoffSignals: string[];
  riskSignals: string[];
  energySignals: string[];
  contextSignals: string[];
  uncertaintyNotes: string[];
}

export interface DecisionRequest {
  question: string;
  options: string[];
  context?: string;
  category?: string;
  tags?: string[];
}

export interface SuggestedOption {
  label: string;
  notes?: string;
}

export interface OptionSuggestion {
  options: SuggestedOption[];
  rationale?: string;
}

export interface MemorySelection {
  selectedMemoryIds: string[];
  reasoning: string;
}

export interface PredictionResult {
  chosenOption: string;
  explanation: string;
  confidence: Confidence;
  usedMemoryIds: string[];
}

export type PredictionMode = "fast" | "deep";
export type PredictionGateStage = "pre" | "post-fast" | "fast-only";
export type PanelJudgmentRole = "value_taste_fit" | "practicality_cost" | "risk_regret";

export interface PredictionGate {
  mode: PredictionMode;
  stage: PredictionGateStage;
  score: number;
  threshold: number;
  reasons: string[];
  signals: {
    explicitDeepRequest?: boolean;
    highStakes?: boolean;
    complexityScore?: number;
    profileConflict?: boolean;
    fastConfidence?: Confidence;
    elapsedMs?: number;
    remainingBudgetMs?: number;
  };
}

export interface PanelJudgment {
  role: PanelJudgmentRole;
  recommendedOption: string;
  rationale: string;
  confidence: Confidence;
  concerns: string[];
}

export interface DeepPredictionResult {
  panelJudgments: PanelJudgment[];
  synthesis: PredictionResult;
}

export interface PredictionResponse {
  prediction: PredictionResult;
  memorySelection: MemorySelection;
  candidateMemoryCount: number;
  mode: PredictionMode;
  gate: PredictionGate;
  panelJudgments?: PanelJudgment[];
}

export interface FeedbackPayload {
  request: DecisionRequest;
  prediction: PredictionResult;
  actualChoice: string;
  reasonTags: string[];
  reasonText?: string;
  predictionMode?: PredictionMode;
  predictionGate?: PredictionGate;
  panelJudgments?: PanelJudgment[];
}

export interface DecisionCard {
  id: string;
  createdAt: string;
  category?: string;
  tags: string[];
  question?: string;
  actualChoice: string;
  predictedChoice?: string;
  predictionMode?: PredictionMode;
  title: string;
  summary: string;
  body: string;
  fileName: string;
}

export interface DecisionCardDraft {
  title: string;
  summary: string;
  category: string;
  tags: string[];
  choicePattern: string;
  contextSignals: string[];
}

export interface BootstrapState {
  hasProfile: boolean;
  profileMarkdown: string | null;
  memoryCount: number;
  dataDir: string;
  hasRawProfileImport: boolean;
  rawProfileImportPath: string | null;
}

export interface CodexConnectionStatus {
  ok: boolean;
  checkedAt: string;
  command: string;
  version?: string;
  details?: string;
}

export interface ApiErrorResponse {
  error: string;
  details?: string;
}
