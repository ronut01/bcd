import { useEffect, useMemo, useState } from "react";
import type { JSX } from "react";
import type {
  BootstrapState,
  CodexConnectionStatus,
  DecisionCard,
  DecisionRequest,
  FeedbackPayload,
  OnboardingInput,
  PreferenceAnswer,
  PredictionResponse,
  SuggestedOption
} from "../shared/types.js";
import {
  checkCodexConnection,
  clearRawProfileImport,
  getProfileImportPrompt,
  getBootstrap,
  listMemories,
  predictChoice,
  saveFeedback,
  saveOnboarding,
  saveProfileImport,
  suggestOptions
} from "./api.js";

type View = "decision" | "profile" | "memories";

const MBTI_TYPES = [
  "INTJ",
  "INTP",
  "ENTJ",
  "ENTP",
  "INFJ",
  "INFP",
  "ENFJ",
  "ENFP",
  "ISTJ",
  "ISFJ",
  "ESTJ",
  "ESFJ",
  "ISTP",
  "ISFP",
  "ESTP",
  "ESFP"
];

const REASON_TAGS = ["comfort", "novelty", "time", "money", "energy", "people", "growth", "simplicity"];

const PREFERENCE_PROMPTS = [
  {
    id: "decision_pace",
    label: "Decision pace",
    type: "select",
    options: ["I decide quickly when it feels right", "I compare a few concrete tradeoffs", "I need time to sit with it"]
  },
  {
    id: "risk",
    label: "Risk posture",
    type: "select",
    options: ["Prefer the familiar", "Accept risk for meaningful upside", "Seek novelty when the cost is low"]
  },
  {
    id: "energy",
    label: "Energy signal",
    type: "select",
    options: ["Protect calm and routine", "Follow curiosity and momentum", "Balance energy with obligation"]
  },
  {
    id: "tradeoff",
    label: "Typical tradeoff",
    type: "text",
    placeholder: "Example: I often choose convenience over savings on busy weekdays."
  },
  {
    id: "recent_good_choice",
    label: "Recent satisfying choice",
    type: "text",
    placeholder: "A choice that felt like you, and why."
  }
] as const;

export function App(): JSX.Element {
  const [bootstrap, setBootstrap] = useState<BootstrapState | null>(null);
  const [view, setView] = useState<View>("decision");
  const [codexReady, setCodexReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshBootstrap = async () => {
    setBootstrap(await getBootstrap());
  };

  useEffect(() => {
    refreshBootstrap().catch((caught: Error) => setError(caught.message));
  }, []);

  if (error && !bootstrap) {
    return <ShellError error={error} />;
  }

  if (!bootstrap) {
    return <div className="loading">Loading bcd...</div>;
  }

  if (!bootstrap.hasProfile && !codexReady) {
    return (
      <main className="app-shell narrow">
        <Header bootstrap={bootstrap} />
        <CodexConnect onReady={() => setCodexReady(true)} />
      </main>
    );
  }

  if (!bootstrap.hasProfile) {
    return (
      <main className="app-shell narrow">
        <Header bootstrap={bootstrap} />
        <Onboarding
          onComplete={async () => {
            await refreshBootstrap();
            setView("decision");
          }}
        />
      </main>
    );
  }

  return (
    <main className="app-shell">
      <Header bootstrap={bootstrap} view={view} onViewChange={setView} />
      {view === "decision" && <DecisionFlow onMemoryChanged={refreshBootstrap} />}
      {view === "profile" && (
        <ProfileView
          markdown={bootstrap.profileMarkdown ?? ""}
          dataDir={bootstrap.dataDir}
          hasRawProfileImport={bootstrap.hasRawProfileImport}
          rawProfileImportPath={bootstrap.rawProfileImportPath}
          onProfileChanged={refreshBootstrap}
        />
      )}
      {view === "memories" && <MemoryList />}
    </main>
  );
}

function CodexConnect({ onReady }: { onReady: () => void }): JSX.Element {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<CodexConnectionStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runCheck = async () => {
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const result = await checkCodexConnection();
      setStatus(result);
      if (!result.ok) {
        setError(result.details ?? "Codex CLI connection check failed.");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel connect-panel">
      <div className="section-heading">
        <p className="eyebrow">Step 1</p>
        <h2>Connect Codex CLI first</h2>
      </div>
      <p className="muted">
        bcd uses Codex CLI for option suggestions, memory selection, and choice prediction. Confirm the local CLI works before creating the first profile.
      </p>
      <div className="connect-actions">
        <button className="primary" disabled={busy} onClick={runCheck}>
          {busy ? "Checking Codex CLI..." : "Check Codex CLI"}
        </button>
        {status?.ok && (
          <button className="secondary" onClick={onReady}>
            Continue to profile
          </button>
        )}
      </div>
      {status?.ok && (
        <div className="success-box">
          <strong>Codex CLI is connected.</strong>
          <span>{status.version}</span>
        </div>
      )}
      {error && <ErrorBox error={error} />}
      <p className="path-line">Command: {status?.command ?? "codex"}</p>
    </section>
  );
}

function Header({
  bootstrap,
  view,
  onViewChange
}: {
  bootstrap: BootstrapState;
  view?: View;
  onViewChange?: (view: View) => void;
}): JSX.Element {
  return (
    <header className="topbar">
      <div className="brand-block">
        <p className="brand-mark">bcd</p>
        <p className="brand-note">A new choice. A future memory.</p>
      </div>
      <div className="status-grid">
        <span>{bootstrap.memoryCount} memories</span>
        <span>{bootstrap.dataDir}</span>
      </div>
      {view && onViewChange && (
        <nav className="tabs" aria-label="Main views">
          <button className={view === "decision" ? "active" : ""} onClick={() => onViewChange("decision")}>
            Decide
          </button>
          <button className={view === "profile" ? "active" : ""} onClick={() => onViewChange("profile")}>
            Profile
          </button>
          <button className={view === "memories" ? "active" : ""} onClick={() => onViewChange("memories")}>
            Memories
          </button>
        </nav>
      )}
    </header>
  );
}

function Onboarding({ onComplete }: { onComplete: () => Promise<void> }): JSX.Element {
  const [mode, setMode] = useState<"import" | "manual">("import");
  const [prompt, setPrompt] = useState("");
  const [rawImport, setRawImport] = useState("");
  const [rawStorageConsent, setRawStorageConsent] = useState(false);
  const [copied, setCopied] = useState(false);
  const [mbti, setMbti] = useState("INFP");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const answeredCount = PREFERENCE_PROMPTS.filter((item) => (answers[item.id] ?? "").trim()).length;

  useEffect(() => {
    getProfileImportPrompt()
      .then((result) => setPrompt(result.prompt))
      .catch((caught: Error) => setError(caught.message));
  }, []);

  const copyPrompt = async () => {
    setError(null);
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
    } catch {
      setError("Copy failed. Select and copy the prompt manually.");
    }
  };

  const submitImport = async () => {
    if (!rawImport.trim()) {
      setError("Paste the answer from your AI before saving.");
      return;
    }
    if (!rawStorageConsent) {
      setError("Confirm that bcd may store the raw pasted answer locally under ~/.bcd.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await saveProfileImport({ rawImport, rawStorageConsent: true });
      await onComplete();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const submitManual = async () => {
    if (answeredCount < 3) {
      setError("Answer at least three preference questions before saving.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const preferences: PreferenceAnswer[] = PREFERENCE_PROMPTS.map((item) => ({
        id: item.id,
        label: item.label,
        answer: answers[item.id] ?? ""
      })).filter((answer) => answer.answer.trim());
      const input: OnboardingInput = { mbti, preferences };
      await saveOnboarding(input);
      await onComplete();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  if (mode === "manual") {
    return (
      <section className="panel">
        <div className="section-heading row-heading">
          <div>
            <p className="eyebrow">Manual fallback</p>
            <h2>Create your lightweight profile</h2>
          </div>
          <button className="secondary compact" onClick={() => setMode("import")}>
            Use AI import
          </button>
        </div>
        <label className="field">
          <span>MBTI cold-start hint</span>
          <select value={mbti} onChange={(event) => setMbti(event.target.value)}>
            {MBTI_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <div className="question-grid">
          {PREFERENCE_PROMPTS.map((item) => (
            <label className="field" key={item.id}>
              <span>{item.label}</span>
              {item.type === "select" ? (
                <select
                  value={answers[item.id] ?? ""}
                  onChange={(event) => setAnswers({ ...answers, [item.id]: event.target.value })}
                >
                  <option value="">Choose one</option>
                  {item.options.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              ) : (
                <textarea
                  rows={3}
                  placeholder={item.placeholder}
                  value={answers[item.id] ?? ""}
                  onChange={(event) => setAnswers({ ...answers, [item.id]: event.target.value })}
                />
              )}
            </label>
          ))}
        </div>
        <p className="muted">{answeredCount}/3 required preference answers completed.</p>
        {error && <ErrorBox error={error} />}
        <button className="primary" disabled={busy || answeredCount < 3} onClick={submitManual}>
          {busy ? "Saving..." : "Save manual profile"}
        </button>
      </section>
    );
  }

  return (
    <section className="panel">
      <div className="section-heading row-heading">
        <div>
          <p className="eyebrow">Recommended cold start</p>
          <h2>Import a profile from your usual AI</h2>
        </div>
        <button className="secondary compact" onClick={() => setMode("manual")}>
          Manual fallback
        </button>
      </div>
      <p className="muted">
        Copy this prompt into the AI you already use, then paste its answer below. bcd will normalize it locally through Codex and use only the normalized profile for predictions.
      </p>
      <label className="field">
        <span>Prompt to copy</span>
        <textarea className="prompt-box" rows={8} value={prompt} readOnly />
      </label>
      <button className="secondary" disabled={!prompt} onClick={() => void copyPrompt()}>
        {copied ? "Prompt copied" : "Copy prompt"}
      </button>
      <label className="field import-answer">
        <span>Paste the AI answer</span>
        <textarea
          rows={9}
          placeholder="Paste the profile your AI returned. You can edit or remove anything before saving."
          value={rawImport}
          onChange={(event) => setRawImport(event.target.value)}
        />
      </label>
      <label className="consent-row">
        <input
          type="checkbox"
          checked={rawStorageConsent}
          onChange={(event) => setRawStorageConsent(event.target.checked)}
        />
        <span>
          I understand bcd will store this raw pasted answer locally under ~/.bcd, alongside the normalized profile. I can clear the raw import later.
        </span>
      </label>
      {error && <ErrorBox error={error} />}
      <button className="primary" disabled={busy || !rawImport.trim() || !rawStorageConsent} onClick={submitImport}>
        {busy ? "Normalizing with Codex..." : "Save imported profile"}
      </button>
    </section>
  );
}

function DecisionFlow({ onMemoryChanged }: { onMemoryChanged: () => Promise<void> }): JSX.Element {
  const [question, setQuestion] = useState("");
  const [context, setContext] = useState("");
  const [contextOpen, setContextOpen] = useState(false);
  const [options, setOptions] = useState(["", ""]);
  const [suggested, setSuggested] = useState<SuggestedOption[] | null>(null);
  const [predictionResponse, setPredictionResponse] = useState<PredictionResponse | null>(null);
  const [busy, setBusy] = useState<"suggest" | "predict" | "feedback" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedbackSaved, setFeedbackSaved] = useState(false);

  const request = useMemo<DecisionRequest>(
    () => ({
      question,
      options: options.map((option) => option.trim()).filter(Boolean),
      context: context.trim() || undefined
    }),
    [context, options, question]
  );

  const canPredict = request.question.trim() && request.options.length >= 2;

  const updateOption = (index: number, value: string) => {
    const next = [...options];
    next[index] = value;
    setOptions(next);
  };

  const addOption = () => {
    setOptions([...options, ""]);
  };

  const runSuggestion = async () => {
    setBusy("suggest");
    setError(null);
    setPredictionResponse(null);
    try {
      const result = await suggestOptions({ question, context });
      setSuggested(result.options);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  };

  const useSuggestedOptions = () => {
    if (!suggested) {
      return;
    }
    setOptions(suggested.map((option) => option.label));
  };

  const runPrediction = async () => {
    setBusy("predict");
    setError(null);
    setPredictionResponse(null);
    setFeedbackSaved(false);
    try {
      setPredictionResponse(await predictChoice(request));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  };

  const submitFeedback = async (payload: FeedbackPayload) => {
    setBusy("feedback");
    setError(null);
    try {
      await saveFeedback(payload);
      setFeedbackSaved(true);
      await onMemoryChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="decision-layout">
      <div className="journal-entry">
        <div className="entry-heading">
          <p className="eyebrow">Decide</p>
          <h2>What choice are you holding?</h2>
          <p>Capture the moment honestly. You can always reflect more later.</p>
        </div>
        <label className="field question-field">
          <span>What is the question?</span>
          <textarea
            rows={4}
            maxLength={500}
            value={question}
            onChange={(event) => {
              setQuestion(event.target.value);
            }}
            placeholder="Write your question or choice here..."
          />
          <small>{question.length} / 500</small>
        </label>
        <div className="option-list">
          {options.map((option, index) => (
            <label className="field option-field" key={index}>
              <span>{optionLabel(index)}</span>
              <input
                maxLength={200}
                value={option}
                onChange={(event) => updateOption(index, event.target.value)}
                placeholder={`Enter ${optionLabel(index).toLowerCase()}...`}
              />
              <small>{option.length} / 200</small>
            </label>
          ))}
        </div>
        <button className="add-option" onClick={addOption} type="button">
          <span aria-hidden="true">+</span>
          <strong>Add option</strong>
          <small>Add another possible path</small>
        </button>
        <button className="context-toggle" onClick={() => setContextOpen(!contextOpen)} type="button">
          <span aria-hidden="true">{contextOpen ? "-" : "+"}</span>
          <strong>Add a little context</strong>
          <small>Optional background, feelings, or details.</small>
        </button>
        {contextOpen && (
          <label className="field context-field">
            <span>Context note</span>
            <textarea
              rows={4}
              value={context}
              onChange={(event) => setContext(event.target.value)}
              placeholder="Anything that matters today: constraints, mood, time, people, tradeoffs."
            />
          </label>
        )}
        {suggested && (
          <div className="suggestion-strip">
            <div>
              <strong>Codex suggested {suggested.length} options.</strong>
              <p>{suggested.map((option) => option.label).join(" / ")}</p>
            </div>
            <button className="secondary compact" onClick={useSuggestedOptions}>
              Use suggestions
            </button>
          </div>
        )}
        {error && <ErrorBox error={error} />}
        <div className="action-row">
          <button className="secondary" disabled={!question.trim() || busy === "suggest"} onClick={runSuggestion}>
            {busy === "suggest" ? "Asking Codex..." : "Suggest options"}
          </button>
          <button className="primary" disabled={!canPredict || busy === "predict"} onClick={runPrediction}>
            {busy === "predict" ? "Reflecting..." : "Reflect my choice"}
          </button>
        </div>
      </div>

      <div className="reflection-panel">
        <ResultView
          busy={busy}
          request={request}
          response={predictionResponse}
          feedbackSaved={feedbackSaved}
          onFeedback={submitFeedback}
        />
      </div>
    </section>
  );
}

function ResultView({
  busy,
  request,
  response,
  feedbackSaved,
  onFeedback
}: {
  busy: string | null;
  request: DecisionRequest;
  response: PredictionResponse | null;
  feedbackSaved: boolean;
  onFeedback: (payload: FeedbackPayload) => Promise<void>;
}): JSX.Element {
  const [actualChoice, setActualChoice] = useState("");
  const [reasonTags, setReasonTags] = useState<string[]>([]);
  const [reasonText, setReasonText] = useState("");

  useEffect(() => {
    setActualChoice("");
    setReasonTags([]);
    setReasonText("");
  }, [response]);

  if (!response) {
    return (
      <div className="empty-result">
        <div className="empty-icon" aria-hidden="true" />
        <h2>Your reflection will appear here</h2>
        <p>After you reflect, this space will hold your insight and the memory it becomes.</p>
        <div className="reflection-metrics">
          <span>Memory</span>
          <strong>--</strong>
          <span>Confidence</span>
          <strong>--</strong>
        </div>
        <p className="quiet-note">Your reflections live here. Revisit them anytime.</p>
      </div>
    );
  }

  const { prediction, memorySelection, candidateMemoryCount, mode, gate, panelJudgments } = response;

  return (
    <div className="result-stack">
      <p className="eyebrow">Prediction</p>
      <h2>You would probably choose {prediction.chosenOption}</h2>
      <p className="result-copy">{prediction.explanation}</p>
      <div className="meta-row">
        <span>Confidence: {prediction.confidence}</span>
        <span>Mode: {mode}</span>
        <span>{prediction.usedMemoryIds.length} used memories</span>
        <span>{candidateMemoryCount} candidates gathered</span>
      </div>
      {mode === "deep" && panelJudgments?.length ? (
        <div className="selection-note">
          <strong>Deep panel used</strong>
          <ul>
            {panelJudgments.map((judgment) => (
              <li key={judgment.role}>
                <span>{panelRoleLabel(judgment.role)}: </span>
                <strong>{judgment.recommendedOption}</strong>
                <span> ({judgment.confidence}) — {judgment.rationale}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {memorySelection.reasoning && <p className="selection-note">{memorySelection.reasoning}</p>}
      <div className="feedback-box">
        <h3>What did you actually choose?</h3>
        <label className="field">
          <span>Actual choice</span>
          <select value={actualChoice} onChange={(event) => setActualChoice(event.target.value)}>
            <option value="">Choose one</option>
            {request.options.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <div className="tag-picker">
          {REASON_TAGS.map((tag) => (
            <label key={tag}>
              <input
                type="checkbox"
                checked={reasonTags.includes(tag)}
                onChange={(event) => {
                  setReasonTags(
                    event.target.checked ? [...reasonTags, tag] : reasonTags.filter((entry) => entry !== tag)
                  );
                }}
              />
              <span>{tag}</span>
            </label>
          ))}
        </div>
        <label className="field">
          <span>Short reason</span>
          <textarea rows={3} value={reasonText} onChange={(event) => setReasonText(event.target.value)} />
        </label>
        <button
          className="primary"
          disabled={!actualChoice || busy === "feedback"}
          onClick={() =>
            onFeedback({
              request,
              prediction,
              actualChoice,
              reasonTags,
              reasonText: reasonText.trim() || undefined,
              predictionMode: mode,
              predictionGate: gate,
              panelJudgments
            })
          }
        >
          {busy === "feedback" ? "Saving..." : "Save feedback"}
        </button>
        {feedbackSaved && (
          <p className="success">Feedback saved. Decision card generation is running in the background.</p>
        )}
      </div>
    </div>
  );
}

function panelRoleLabel(role: string): string {
  switch (role) {
    case "value_taste_fit":
      return "Value/taste fit";
    case "practicality_cost":
      return "Practicality/cost";
    case "risk_regret":
      return "Risk/regret";
    default:
      return role;
  }
}

function ProfileView({
  markdown,
  dataDir,
  hasRawProfileImport,
  rawProfileImportPath,
  onProfileChanged
}: {
  markdown: string;
  dataDir: string;
  hasRawProfileImport: boolean;
  rawProfileImportPath: string | null;
  onProfileChanged: () => Promise<void>;
}): JSX.Element {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearRaw = async () => {
    setBusy(true);
    setError(null);
    try {
      await clearRawProfileImport();
      await onProfileChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <div className="section-heading row-heading">
        <div>
          <p className="eyebrow">Profile</p>
          <h2>Local profile</h2>
        </div>
        {hasRawProfileImport && (
          <button className="secondary compact" disabled={busy} onClick={() => void clearRaw()}>
            {busy ? "Clearing..." : "Clear raw import"}
          </button>
        )}
      </div>
      <p className="path-line">{dataDir}/profile.md</p>
      {hasRawProfileImport ? (
        <p className="success-box">
          <strong>Raw external-AI import is stored locally.</strong>
          <span>{rawProfileImportPath}</span>
        </p>
      ) : (
        <p className="muted">No raw external-AI import is currently stored.</p>
      )}
      {error && <ErrorBox error={error} />}
      <pre className="markdown-preview">{markdown}</pre>
    </section>
  );
}

function MemoryList(): JSX.Element {
  const [memories, setMemories] = useState<DecisionCard[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    const result = await listMemories();
    setMemories(result.memories);
  };

  useEffect(() => {
    refresh().catch((caught: Error) => setError(caught.message));
  }, []);

  return (
    <section className="panel">
      <div className="section-heading row-heading">
        <div>
          <p className="eyebrow">Memory</p>
          <h2>Decision cards</h2>
        </div>
        <button className="secondary compact" onClick={() => refresh().catch((caught: Error) => setError(caught.message))}>
          Refresh
        </button>
      </div>
      {error && <ErrorBox error={error} />}
      {memories.length === 0 ? (
        <p className="muted">No decision cards yet. Save feedback after a prediction to create one.</p>
      ) : (
        <div className="memory-list">
          {memories.map((memory) => (
            <article className="memory-card" key={memory.id}>
              <div className="memory-card-top">
                <h3>{memory.title}</h3>
                <span>{new Date(memory.createdAt).toLocaleString()}</span>
              </div>
              <p>{memory.summary}</p>
              <div className="meta-row">
                {memory.category && <span>{memory.category}</span>}
                <span>Actual: {memory.actualChoice}</span>
                {memory.predictedChoice && <span>Predicted: {memory.predictedChoice}</span>}
              </div>
              <div className="tag-row">
                {memory.tags.map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function ShellError({ error }: { error: string }): JSX.Element {
  return (
    <main className="app-shell narrow">
      <ErrorBox error={error} />
    </main>
  );
}

function ErrorBox({ error }: { error: string }): JSX.Element {
  return <pre className="error-box">{error}</pre>;
}

function optionLabel(index: number): string {
  const letter = String.fromCharCode(65 + index);
  return `Option ${letter}`;
}
