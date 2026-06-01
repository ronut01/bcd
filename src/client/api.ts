import type {
  BootstrapState,
  CodexConnectionStatus,
  DecisionCard,
  DecisionRequest,
  ExternalProfileImportRequest,
  ExternalProfileImportResponse,
  FeedbackPayload,
  OnboardingInput,
  OptionSuggestion,
  PredictionResponse
} from "../shared/types.js";

export async function getBootstrap(): Promise<BootstrapState> {
  return fetchJson("/api/bootstrap");
}

export async function saveOnboarding(input: OnboardingInput): Promise<{ profileMarkdown: string }> {
  return fetchJson("/api/onboarding", {
    method: "POST",
    body: JSON.stringify(input)
  }, 15_000);
}

export async function getProfileImportPrompt(): Promise<{ prompt: string }> {
  return fetchJson("/api/profile-import/prompt");
}

export async function saveProfileImport(input: ExternalProfileImportRequest): Promise<ExternalProfileImportResponse> {
  return fetchJson("/api/profile-import", {
    method: "POST",
    body: JSON.stringify(input)
  }, 180_000);
}

export async function clearRawProfileImport(): Promise<{ cleared: true; rawImportPath: null; profileMarkdown: string | null }> {
  return fetchJson("/api/profile-import/raw", {
    method: "DELETE"
  });
}

export async function checkCodexConnection(): Promise<CodexConnectionStatus> {
  return fetchJson("/api/codex/check", {
    method: "POST",
    body: JSON.stringify({})
  }, 75_000);
}

export async function suggestOptions(input: Pick<DecisionRequest, "question" | "context">): Promise<OptionSuggestion> {
  return fetchJson("/api/options/suggest", {
    method: "POST",
    body: JSON.stringify(input)
  }, 150_000);
}

export async function predictChoice(request: DecisionRequest): Promise<PredictionResponse> {
  return fetchJson("/api/predict", {
    method: "POST",
    body: JSON.stringify({ request, confirmedOptions: true })
  }, 180_000);
}

export async function saveFeedback(payload: FeedbackPayload): Promise<{ saved: true; feedbackId: string; cardStatus: string }> {
  return fetchJson("/api/feedback", {
    method: "POST",
    body: JSON.stringify(payload)
  }, 15_000);
}

export async function listMemories(): Promise<{ memories: DecisionCard[] }> {
  return fetchJson("/api/memories");
}

async function fetchJson<T>(url: string, init?: RequestInit, timeoutMs = 30_000): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const response = await fetch(url, {
    ...init,
    signal: controller.signal,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  }).catch((error: unknown) => {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("Request timed out. Check that the local bcd server is still running.");
    }
    throw error;
  }).finally(() => window.clearTimeout(timeout));

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = payload?.details ? `${payload.error}\n${payload.details}` : payload?.error ?? "Request failed";
    throw new Error(error);
  }
  return payload as T;
}
