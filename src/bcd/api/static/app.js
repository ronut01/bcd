(function () {
  const ACTIVE_USER_KEY = "bcd.activeUserId";
  const LLM_STORAGE_KEY = "bcd.llmSettings";
  const DEFAULT_SIGNATURE_SAMPLE_ID = "alex_chen";
  const DEFAULT_OPTIONS = ["Warm noodle soup", "Greasy burger", "Raw salad"];
  const FAILURE_REASON_OPTIONS = [
    { id: "stable_profile_wrong", label: "Stable profile was wrong" },
    { id: "recent_state_not_captured", label: "Recent state was not captured" },
    { id: "context_missing", label: "Important context was missing" },
    { id: "similar_memory_missing", label: "Relevant past memory was missing" },
    { id: "option_wording_misleading", label: "Option wording was misleading" },
    { id: "spontaneous_change", label: "The choice was a spontaneous exception" },
  ];

  const page = document.body.dataset.page;
  const urlParams = new URLSearchParams(window.location.search);
  let onboardingQuestionnaire = null;
  let latestPrediction = null;
  let latestPredictionPayload = null;
  let latestPostFeedbackPrediction = null;
  let optionSuggestions = [];
  let showcase = { personas: [], scenarios: [] };
  const setupState = {
    step: getActiveUserId() ? 3 : 1,
    source: null,
    onboardingAnswers: {},
    onboardingIndex: 0,
    preview: null,
  };

  function $(id) {
    return document.getElementById(id);
  }

  function setStatus(message, error = false) {
    const node = page === "setup" ? $("setup-status") : $("predict-status");
    if (!node) return;
    node.textContent = message;
    node.classList.toggle("error", error);
    if (error) {
      showErrorModal(message);
    }
  }

  function getActiveUserId() {
    return window.localStorage.getItem(ACTIVE_USER_KEY) || "";
  }

  function setActiveUserId(userId) {
    if (userId) {
      window.localStorage.setItem(ACTIVE_USER_KEY, userId);
    } else {
      window.localStorage.removeItem(ACTIVE_USER_KEY);
    }
  }

  function applyUrlStateOverrides() {
    const userId = (urlParams.get("user_id") || "").trim();
    if (userId) {
      setActiveUserId(userId);
    }
  }

  function getUrlOptionOverrides() {
    const repeated = urlParams.getAll("option").map((value) => value.trim()).filter(Boolean);
    if (repeated.length) {
      return repeated;
    }
    return (urlParams.get("options") || "")
      .split("|")
      .map((value) => value.trim())
      .filter(Boolean);
  }

  function applyPredictUrlOverrides() {
    if (page !== "predict") return;
    const fieldMap = {
      category: "category",
      prompt: "prompt",
      mode: "prediction-mode",
      time_of_day: "time_of_day",
      energy: "energy",
      weather: "weather",
      with: "with",
      budget: "budget",
      urgency: "urgency",
    };
    Object.entries(fieldMap).forEach(([param, fieldId]) => {
      const value = (urlParams.get(param) || "").trim();
      if (value && $(fieldId)) {
        $(fieldId).value = value;
      }
    });
    const options = getUrlOptionOverrides();
    if (options.length && $("option-list")) {
      $("option-list").innerHTML = "";
      options.slice(0, 5).forEach((optionText) => createOptionRow(optionText));
    }
  }

  async function request(path, options = {}) {
    const isFormData = options.body instanceof FormData;
    const response = await fetch(path, {
      ...(isFormData ? {} : { headers: { "Content-Type": "application/json" } }),
      ...options,
    });
    if (!response.ok) {
      let detail = "";
      try {
        const payload = await response.json();
        detail = payload.detail || JSON.stringify(payload);
      } catch (_) {
        detail = await response.text();
      }
      throw new Error(detail || `Request failed with ${response.status}`);
    }
    return response.json();
  }

  function loadSavedLlmSettings() {
    try {
      const raw = window.localStorage.getItem(LLM_STORAGE_KEY);
      if (!raw) return;
      const config = JSON.parse(raw);
      if ($("llm-api-key")) $("llm-api-key").value = config.api_key || "";
      if ($("llm-base-url")) $("llm-base-url").value = config.base_url || "https://api.openai.com/v1";
      if ($("llm-model")) $("llm-model").value = config.model || "gpt-4.1-mini";
    } catch (_) {
      window.localStorage.removeItem(LLM_STORAGE_KEY);
    }
  }

  function ensureErrorModal() {
    if (document.getElementById("global-error-modal")) return;
    const wrapper = document.createElement("div");
    wrapper.id = "global-error-modal";
    wrapper.className = "modal-overlay hidden";
    wrapper.innerHTML = `
      <div class="modal-backdrop" id="global-error-backdrop"></div>
      <div class="modal-sheet modal-sheet-sm">
        <div class="modal-header">
          <div>
            <span class="section-tag">Attention</span>
            <h2>Something needs your input</h2>
          </div>
          <div class="button-row inline">
            <button class="secondary" id="global-error-close" type="button">Close</button>
          </div>
        </div>
        <div class="list-card top-gap">
          <p class="help" id="global-error-message"></p>
        </div>
      </div>
    `;
    document.body.appendChild(wrapper);
    document.getElementById("global-error-backdrop").addEventListener("click", closeErrorModal);
    document.getElementById("global-error-close").addEventListener("click", closeErrorModal);
  }

  function showErrorModal(message) {
    ensureErrorModal();
    $("global-error-message").textContent = message;
    $("global-error-modal").classList.remove("hidden");
    document.body.classList.add("modal-open");
  }

  function closeErrorModal() {
    const modal = $("global-error-modal");
    if (!modal) return;
    modal.classList.add("hidden");
    if ($("prediction-modal")?.classList.contains("hidden")) {
      document.body.classList.remove("modal-open");
    }
  }

  function getLlmConfig() {
    const apiKeyNode = $("llm-api-key");
    if (!apiKeyNode) return null;
    const apiKey = apiKeyNode.value.trim();
    if (!apiKey) return null;
    return {
      api_key: apiKey,
      base_url: $("llm-base-url").value.trim() || "https://api.openai.com/v1",
      model: $("llm-model").value.trim() || "gpt-4.1-mini",
      timeout_seconds: 30,
    };
  }

  function wireLlmButtons() {
    const saveButton = $("save-llm-settings-button");
    const clearButton = $("clear-llm-settings-button");
    if (!saveButton || !clearButton) return;
    saveButton.addEventListener("click", () => {
      const config = getLlmConfig();
      if (!config) {
        setStatus("Enter an API key first if you want to save LLM settings.", true);
        return;
      }
      window.localStorage.setItem(LLM_STORAGE_KEY, JSON.stringify(config));
      setStatus("Saved LLM settings in this browser.");
    });
    clearButton.addEventListener("click", () => {
      window.localStorage.removeItem(LLM_STORAGE_KEY);
      $("llm-api-key").value = "";
      $("llm-base-url").value = "https://api.openai.com/v1";
      $("llm-model").value = "gpt-4.1-mini";
      setStatus("Cleared saved LLM settings for this browser.");
    });
  }

  async function fetchProfileBundle(userId) {
    return request(`/profiles/${encodeURIComponent(userId)}`);
  }

  async function fetchProfileCard(userId) {
    return request(`/profiles/${encodeURIComponent(userId)}/card`);
  }

  async function fetchSignals(userId) {
    return request(`/profiles/${encodeURIComponent(userId)}/signals`);
  }

  async function fetchRecentState(userId) {
    return request(`/profiles/${encodeURIComponent(userId)}/recent-state`);
  }

  async function fetchHistory(userId) {
    return request(`/users/${encodeURIComponent(userId)}/history?limit=5`);
  }

  async function fetchShowcase() {
    return request("/demo/showcase");
  }

  async function bootstrapSampleProfile(sampleId) {
    const query = sampleId ? `?sample_id=${encodeURIComponent(sampleId)}` : "";
    return request(`/profiles/bootstrap-sample${query}`, { method: "POST" });
  }

  function renderChipRow(containerId, values, emptyLabel = "None") {
    const container = $(containerId);
    if (!container) return;
    container.innerHTML = "";
    const normalized = (values || []).filter(Boolean);
    if (!normalized.length) {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = emptyLabel;
      container.appendChild(chip);
      return;
    }
    normalized.forEach((value) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = value;
      container.appendChild(chip);
    });
  }

  function getPersonaBySampleId(sampleId) {
    return (showcase.personas || []).find((item) => item.sample_id === sampleId) || null;
  }

  function getScenarioById(scenarioId) {
    return (showcase.scenarios || []).find((item) => item.scenario_id === scenarioId) || null;
  }

  function getScenarioListForSample(sampleId) {
    return (showcase.scenarios || []).filter((item) => item.sample_id === sampleId);
  }

  function getActivePersona() {
    const activeUserId = getActiveUserId();
    return (showcase.personas || []).find((item) => item.user_id === activeUserId) || null;
  }

  function formatContextSummary(context) {
    const parts = Object.entries(context || {})
      .filter(([, value]) => value !== null && value !== undefined && String(value).trim())
      .map(([key, value]) => `${key}=${value}`);
    return parts.join(" | ") || "none";
  }

  function createPredictUrl({
    sampleId = "",
    userId = "",
    prompt = "",
    category = "",
    mode = "baseline",
    context = {},
    options = [],
    autorun = false,
    focus = "",
  }) {
    const base = new URL("/app/predict", window.location.origin);
    if (sampleId) {
      base.searchParams.set("sample_id", sampleId);
    } else if (userId) {
      base.searchParams.set("user_id", userId);
    }
    if (prompt) base.searchParams.set("prompt", prompt);
    if (category) base.searchParams.set("category", category);
    if (mode) base.searchParams.set("mode", mode);
    Object.entries(context || {}).forEach(([key, value]) => {
      if (value !== null && value !== undefined && String(value).trim()) {
        base.searchParams.set(key, value);
      }
    });
    (options || []).forEach((optionText) => {
      if (optionText && optionText.trim()) {
        base.searchParams.append("option", optionText.trim());
      }
    });
    if (autorun) base.searchParams.set("autorun", "1");
    if (focus) base.searchParams.set("focus", focus);
    return base.toString();
  }

  async function copyTextToClipboard(text, successMessage) {
    if (!text) {
      setStatus("Nothing is ready to copy yet.", true);
      return;
    }
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const helper = document.createElement("textarea");
      helper.value = text;
      helper.setAttribute("readonly", "readonly");
      helper.style.position = "fixed";
      helper.style.left = "-9999px";
      document.body.appendChild(helper);
      helper.select();
      document.execCommand("copy");
      helper.remove();
    }
    setStatus(successMessage);
  }

  function extractStableHighlights(profile) {
    const highlights = [];
    const personality = profile.personality_signals || {};
    const preferences = profile.long_term_preferences || {};
    if (personality.mbti) highlights.push(`MBTI: ${personality.mbti}`);
    (personality.values || []).slice(0, 2).forEach((value) => highlights.push(`Value: ${value}`));
    (personality.decision_style || []).slice(0, 2).forEach((item) => highlights.push(`Style: ${item}`));
    Object.entries(preferences).slice(0, 3).forEach(([key, value]) => {
      if (Array.isArray(value) && value.length) {
        highlights.push(`${key}: ${value.slice(0, 2).join(", ")}`);
      }
    });
    return highlights.slice(0, 6);
  }

  function renderSimpleList(containerId, items, emptyMessage) {
    const container = $(containerId);
    if (!container) return;
    container.innerHTML = "";
    if (!(items || []).length) {
      container.innerHTML = `<div class="signal-item"><div class="mini">${escapeHtml(emptyMessage)}</div></div>`;
      return;
    }
    items.forEach((item) => {
      const node = document.createElement("div");
      node.className = "signal-item";
      node.innerHTML = `<div class="mini">${escapeHtml(item)}</div>`;
      container.appendChild(node);
    });
  }

  function formatInfluenceLabel(key) {
    return key.replaceAll("_", " ");
  }

  function formatSignedScore(value) {
    const rounded = Number(value || 0).toFixed(2);
    return value > 0 ? `+${rounded}` : rounded;
  }

  function renderAgentWorkflow(workflow) {
    const container = $("agent-workflow-list");
    if (!container) return;
    container.innerHTML = "";
    if (!workflow) {
      container.innerHTML = `<div class="signal-item"><div class="mini">No agent workflow details were returned.</div></div>`;
      return;
    }
    [
      workflow.profile_agent,
      workflow.recent_state_agent,
      workflow.memory_agent,
      workflow.choice_reasoning_agent,
      workflow.reflection_agent,
    ].forEach((agent) => {
      const node = document.createElement("div");
      node.className = "signal-item";
      node.innerHTML = `
        <strong>${escapeHtml(agent.agent_name)}</strong>
        <div class="mini">${escapeHtml(agent.focus)}</div>
        <div class="mini top-gap-sm">${escapeHtml(agent.conclusion)}</div>
        <div class="mini top-gap-sm">${escapeHtml((agent.observations || []).join(" | ") || "No observations captured.")}</div>
      `;
      container.appendChild(node);
    });
  }

  function renderInfluenceList(containerId, influence, emptyMessage) {
    const container = $(containerId);
    if (!container) return;
    container.innerHTML = "";
    if (!influence) {
      container.innerHTML = `<div class="signal-item"><div class="mini">${escapeHtml(emptyMessage)}</div></div>`;
      return;
    }
    ["stable_profile", "recent_state", "memory", "context", "llm"].forEach((key) => {
      const node = document.createElement("div");
      node.className = "signal-item";
      node.innerHTML = `
        <strong>${escapeHtml(formatInfluenceLabel(key))}</strong>
        <div class="mini">score: ${formatSignedScore(influence[key] || 0)}</div>
      `;
      container.appendChild(node);
    });
    (influence.dominant_signals || []).forEach((item) => {
      const node = document.createElement("div");
      node.className = "signal-item";
      node.innerHTML = `<div class="mini">${escapeHtml(item)}</div>`;
      container.appendChild(node);
    });
  }

  function renderAgentAgreement(agreement) {
    const summary = $("agent-agreement-summary");
    const chips = $("agent-agreement-chips");
    const list = $("agent-agreement-list");
    if (!summary || !chips || !list) return;
    if (!agreement) {
      summary.textContent = "No agreement summary was returned.";
      chips.innerHTML = "";
      list.innerHTML = `<div class="signal-item"><div class="mini">No agreement signals were returned.</div></div>`;
      return;
    }
    summary.textContent = agreement.summary;
    chips.innerHTML = "";
    [
      `label: ${agreement.overall_label.replaceAll("_", " ")}`,
      `support: ${(agreement.supporting_agents || []).length}`,
      `oppose: ${(agreement.opposing_agents || []).length}`,
      `neutral: ${(agreement.neutral_agents || []).length}`,
    ].forEach((item) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = item;
      chips.appendChild(chip);
    });
    list.innerHTML = "";
    (agreement.signals || []).forEach((signal) => {
      const node = document.createElement("div");
      node.className = "signal-item";
      node.innerHTML = `
        <strong>${escapeHtml(signal.agent_name)}</strong>
        <div class="mini">stance: ${escapeHtml(signal.stance)} | strength: ${formatSignedScore(signal.strength)}</div>
        <div class="mini top-gap-sm">${escapeHtml(signal.rationale)}</div>
      `;
      list.appendChild(node);
    });
    if (!(agreement.signals || []).length) {
      list.innerHTML = `<div class="signal-item"><div class="mini">No agreement signals were returned.</div></div>`;
    }
  }

  function renderModelUpdate(feedback) {
    const summary = $("model-update-summary");
    const panel = $("model-update-panel");
    if (!summary || !panel) return;
    if (!feedback) {
      summary.textContent = "";
      summary.classList.add("hidden");
      panel.classList.add("hidden");
      renderSimpleList("snapshot-delta-list", [], "No snapshot changes yet.");
      renderSimpleList("carry-over-list", [], "No carry-over is active yet.");
      return;
    }
    summary.textContent = feedback.model_update_summary || "Model update recorded.";
    summary.classList.remove("hidden");
    panel.classList.remove("hidden");
    renderSimpleList("snapshot-delta-list", feedback.snapshot_delta || [], "No new snapshot delta was captured.");
    renderSimpleList("carry-over-list", feedback.active_carry_over || [], "No active carry-over was returned.");
  }

  function renderHistorySummary(history) {
    const list = $("history-summary-list");
    if (!list) return;
    list.innerHTML = "";
    if (!(history || []).length) {
      list.innerHTML = `<div class="signal-item"><div class="mini">No recent decisions yet.</div></div>`;
      return;
    }
    history.slice(0, 3).forEach((event) => {
      const predictedId = event.prediction?.predicted_option_id;
      const predictedText = event.options.find((option) => option.option_id === predictedId)?.option_text || "n/a";
      const actualId = event.feedback?.actual_option_id;
      const actualText = event.options.find((option) => option.option_id === actualId)?.option_text || "not recorded";
      const node = document.createElement("div");
      node.className = "signal-item";
      node.innerHTML = `
        <strong>${escapeHtml(event.prompt)}</strong>
        <div class="mini">Predicted: ${escapeHtml(predictedText)}</div>
        <div class="mini">Actual: ${escapeHtml(actualText)}</div>
      `;
      list.appendChild(node);
    });
  }

  function renderSignalEditorMarkup(signal) {
    const currentValue = signal.current_value ?? signal.proposed_value ?? {};
    if (signal.signal_kind === "mbti") {
      return `
        <div class="field top-gap-sm">
          <label>Edit MBTI</label>
          <input data-edit-field="mbti" value="${escapeAttribute(currentValue.mbti || "")}" />
        </div>
      `;
    }
    if (["decision_style", "value", "behavior_note"].includes(signal.signal_kind)) {
      return `
        <div class="field top-gap-sm">
          <label>Edit label</label>
          <input data-edit-field="label" value="${escapeAttribute(currentValue.label || "")}" />
        </div>
      `;
    }
    if (signal.signal_kind === "category_preference") {
      return `
        <div class="grid-2 top-gap-sm">
          <div class="field">
            <label>Preferred keywords</label>
            <input data-edit-field="preferred_keywords" value="${escapeAttribute((currentValue.preferred_keywords || []).join(", "))}" />
          </div>
          <div class="field">
            <label>Avoided keywords</label>
            <input data-edit-field="avoided_keywords" value="${escapeAttribute((currentValue.avoided_keywords || []).join(", "))}" />
          </div>
        </div>
      `;
    }
    if (signal.signal_kind === "context_preference") {
      return `
        <div class="field top-gap-sm">
          <label>Edit context values</label>
          <input data-edit-field="values" value="${escapeAttribute((currentValue.values || []).join(", "))}" />
        </div>
      `;
    }
    return `
      <div class="field top-gap-sm">
        <label>JSON fallback editor</label>
        <textarea data-edit-json>${JSON.stringify(currentValue, null, 2)}</textarea>
      </div>
    `;
  }

  function collectSignalEditValue(signalNode, signal) {
    const currentValue = { ...(signal.current_value ?? signal.proposed_value ?? {}) };
    if (signal.signal_kind === "mbti") {
      return { mbti: signalNode.querySelector("[data-edit-field='mbti']").value.trim() };
    }
    if (["decision_style", "value", "behavior_note"].includes(signal.signal_kind)) {
      return { label: signalNode.querySelector("[data-edit-field='label']").value.trim() };
    }
    if (signal.signal_kind === "category_preference") {
      return {
        category: currentValue.category,
        preferred_keywords: csvValues(signalNode.querySelector("[data-edit-field='preferred_keywords']").value),
        avoided_keywords: csvValues(signalNode.querySelector("[data-edit-field='avoided_keywords']").value),
      };
    }
    if (signal.signal_kind === "context_preference") {
      return {
        context_key: currentValue.context_key,
        values: csvValues(signalNode.querySelector("[data-edit-field='values']").value),
      };
    }
    const jsonEditor = signalNode.querySelector("[data-edit-json]");
    return jsonEditor ? JSON.parse(jsonEditor.value) : currentValue;
  }

  async function reviewSignal(signal, action) {
    const userId = getActiveUserId();
    if (!userId) {
      setStatus("Load a user before reviewing signals.", true);
      return;
    }
    let editedValue = null;
    let reviewNote = "";
    if (action === "edit") {
      const signalNode = document.querySelector(`[data-signal-id="${signal.signal_id}"]`);
      if (!signalNode) {
        throw new Error("Could not find the signal editor on the page.");
      }
      editedValue = collectSignalEditValue(signalNode, signal);
    }
    if (action !== "accept") {
      reviewNote = window.prompt("Optional review note", signal.review_note || "") || "";
    }
    setStatus(`Updating signal '${signal.signal_name}'...`);
    await request(`/profiles/${encodeURIComponent(userId)}/signals/${encodeURIComponent(signal.signal_id)}/review`, {
      method: "POST",
      body: JSON.stringify({
        action,
        edited_value: editedValue,
        review_note: reviewNote || null,
      }),
    });
    await hydrateReviewSummary();
    await hydrateOptionalAdjustments();
    setStatus(`Signal '${signal.signal_name}' updated.`);
  }

  function renderSignalCard(signal) {
      const needsReview = signal.status === "pending";
      const node = document.createElement("div");
      node.className = "signal-item";
      node.dataset.signalId = signal.signal_id;
      node.innerHTML = `
        <strong>${escapeHtml(signal.signal_kind)}: ${escapeHtml(signal.signal_name)}</strong>
        <div class="mini">status: ${escapeHtml(signal.status)} | source: ${escapeHtml(signal.source_type)}</div>
        <div class="mini">${escapeHtml(signal.signal_name)} is currently stored as ${escapeHtml(JSON.stringify(signal.current_value ?? signal.proposed_value))}</div>
        <details class="top-gap-sm">
          <summary class="summary-trigger">${needsReview ? "Review this signal" : "Inspect or edit"}</summary>
          <div class="mini top-gap-sm">evidence: ${escapeHtml(signal.evidence_text)}</div>
          ${signal.review_note ? `<div class="mini">review note: ${escapeHtml(signal.review_note)}</div>` : ""}
          ${renderSignalEditorMarkup(signal)}
          <div class="button-row inline top-gap-sm">
            <button class="secondary" type="button" data-action="accept">Accept</button>
            <button class="secondary" type="button" data-action="edit">Save edit</button>
            <button class="danger" type="button" data-action="reject">Reject</button>
          </div>
        </details>
      `;
      node.querySelectorAll("button[data-action]").forEach((button) => {
        button.addEventListener("click", async () => {
          try {
            await reviewSignal(signal, button.dataset.action);
          } catch (error) {
            setStatus(error.message, true);
          }
        });
      });
      return node;
  }

  function renderSignals(signals) {
    const pendingList = $("pending-signal-list");
    const reviewedList = $("reviewed-signal-list");
    const summaryValues = [
      `${signals.filter((signal) => signal.status === "pending").length} pending`,
      `${signals.filter((signal) => signal.status === "accepted").length} accepted`,
      `${signals.filter((signal) => signal.status === "edited").length} edited`,
    ];
    renderChipRow("signal-summary", summaryValues, "No signals");
    if (!pendingList || !reviewedList) return;
    pendingList.innerHTML = "";
    reviewedList.innerHTML = "";
    if (!signals.length) {
      pendingList.innerHTML = `<div class="signal-item"><div class="mini">No profile signals are available for this user.</div></div>`;
      reviewedList.innerHTML = `<div class="signal-item"><div class="mini">No reviewed signals yet.</div></div>`;
      return;
    }
    const pending = signals.filter((signal) => signal.status === "pending");
    const reviewed = signals.filter((signal) => signal.status !== "pending");
    if (!pending.length) {
      pendingList.innerHTML = `<div class="signal-item"><div class="mini">No pending signals. The review queue is clear.</div></div>`;
    } else {
      pending.forEach((signal) => pendingList.appendChild(renderSignalCard(signal)));
    }
    if (!reviewed.length) {
      reviewedList.innerHTML = `<div class="signal-item"><div class="mini">No reviewed signals yet.</div></div>`;
    } else {
      reviewed.forEach((signal) => reviewedList.appendChild(renderSignalCard(signal)));
    }
  }

  function renderRecentStateNotes(notes) {
    const recentStateList = $("recent-state-list");
    if (!recentStateList) return;
    recentStateList.innerHTML = "";
    if (!notes.length) {
      recentStateList.innerHTML = `<div class="signal-item"><div class="mini">No manual recent-state notes are active.</div></div>`;
      return;
    }

    notes.forEach((note) => {
      const node = document.createElement("div");
      node.className = "signal-item";
      node.innerHTML = `
        <strong>${escapeHtml(note.note_text)}</strong>
        <div class="mini">tags: ${escapeHtml((note.tags || []).join(", ") || "none")}</div>
        <div class="button-row inline top-gap-sm">
          <button class="danger" type="button">Remove</button>
        </div>
      `;
      node.querySelector("button").addEventListener("click", async () => {
        try {
          setStatus("Removing recent-state note...");
          await request(`/profiles/${encodeURIComponent(note.user_id)}/recent-state/${encodeURIComponent(note.note_id)}`, {
            method: "DELETE",
          });
          await hydrateReviewSummary();
          await hydrateOptionalAdjustments();
          setStatus("Recent-state note removed.");
        } catch (error) {
          setStatus(error.message, true);
        }
      });
      recentStateList.appendChild(node);
    });
  }

  async function hydrateReviewSummary() {
    if (page !== "setup") return;
    const userId = getActiveUserId();
    const emptyState = $("setup-review-empty");
    const workspace = $("setup-review-content");
    if (!userId) {
      $("setup-metric-user").textContent = "None";
      $("setup-metric-signals").textContent = "0";
      $("setup-metric-notes").textContent = "0";
      emptyState.classList.remove("hidden");
      workspace.classList.add("hidden");
      renderExistingUserBanner();
      return;
    }
    emptyState.classList.add("hidden");
    workspace.classList.remove("hidden");

    const [profile, card, recentState] = await Promise.all([
      fetchProfileBundle(userId),
      fetchProfileCard(userId),
      fetchRecentState(userId),
    ]);

    $("setup-metric-user").textContent = profile.display_name;
    $("setup-metric-signals").textContent = String(profile.signal_count || 0);
    $("setup-metric-notes").textContent = String(recentState.length);
    $("setup-user-name").textContent = profile.display_name;
    $("setup-user-summary").textContent = profile.profile_summary;
    renderChipRow("signal-summary", [
      `${profile.pending_signal_count} pending`,
      `${Math.max((profile.signal_count || 0) - (profile.pending_signal_count || 0), 0)} reviewed`,
      `${profile.history_count} decisions`,
    ], "No signals");
    renderSimpleList("stable-highlights", card.stable_agent_brief || extractStableHighlights(profile), "No stable highlights yet.");
    renderSimpleList(
      "recent-summary-list",
      card.recent_state_agent_brief || [
        ...(profile.latest_snapshot?.short_term_preference_notes || []),
        ...(profile.latest_snapshot?.drift_markers || []),
      ].slice(0, 6),
      "No recent-state highlights yet.",
    );
    renderSimpleList(
      "reflection-summary-list",
      card.reflection_carry_over_brief || card.recent_summary?.adaptation_signals || [],
      "No feedback carry-over is active yet.",
    );
    renderExistingUserBanner(profile);
  }

  async function hydrateOptionalAdjustments() {
    if (page !== "setup") return;
    const userId = getActiveUserId();
    const emptyState = $("setup-adjustments-empty");
    const workspace = $("setup-adjustments-content");
    if (!userId) {
      emptyState.classList.remove("hidden");
      workspace.classList.add("hidden");
      return;
    }

    emptyState.classList.add("hidden");
    workspace.classList.remove("hidden");

    const [signals, recentState, history, card] = await Promise.all([
      fetchSignals(userId),
      fetchRecentState(userId),
      fetchHistory(userId),
      fetchProfileCard(userId),
    ]);
    $("setup-metric-notes").textContent = String(recentState.length);
    $("profile-card-output").textContent = card.content;
    $("recent-state-summary-output").textContent = JSON.stringify(card.recent_summary || {}, null, 2);
    $("history-output").textContent = JSON.stringify(history, null, 2);
    renderHistorySummary(history);
    renderSignals(signals);
    renderRecentStateNotes(recentState);
  }

  function renderExistingUserBanner(profile = null) {
    const banner = $("setup-existing-user-banner");
    const title = $("existing-user-title");
    if (!banner || !title) return;
    const userId = getActiveUserId();
    if (!userId) {
      banner.classList.add("hidden");
      return;
    }
    banner.classList.remove("hidden");
    title.textContent = profile ? profile.display_name : "Current profile";
  }

  function renderSetupPersonaGallery() {
    const gallery = $("setup-persona-gallery");
    if (!gallery) return;
    gallery.innerHTML = "";
    if (!(showcase.personas || []).length) {
      gallery.innerHTML = `
        <div class="source-card">
          <strong>No bundled personas available.</strong>
          <p class="help">The showcase payload could not be loaded.</p>
        </div>
      `;
      return;
    }
    showcase.personas.forEach((persona) => {
      const scenario = getScenarioById(persona.default_scenario_id);
      const card = document.createElement("div");
      card.className = "source-card showcase-card";
      card.innerHTML = `
        <span class="section-tag">Bundled persona</span>
        <strong>${escapeHtml(persona.display_name)}</strong>
        <div class="mini">${escapeHtml(persona.headline)}</div>
        <p class="help top-gap-sm">${escapeHtml(persona.description)}</p>
        <div class="chip-row top-gap-sm">
          ${(persona.tags || []).map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join("")}
        </div>
        ${scenario ? `<div class="mini top-gap-sm">Signature demo: ${escapeHtml(scenario.title)}</div>` : ""}
        <div class="button-row inline top-gap-sm">
          <button class="secondary" type="button" data-load-persona="${escapeAttribute(persona.sample_id)}">Load persona</button>
          <button class="primary" type="button" data-open-demo="${escapeAttribute(persona.sample_id)}">Open demo</button>
        </div>
      `;
      card.querySelector("[data-load-persona]").addEventListener("click", async () => {
        try {
          setStatus(`Loading demo persona '${persona.display_name}'...`);
          const payload = await bootstrapSampleProfile(persona.sample_id);
          setActiveUserId(payload.user_id);
          await hydrateReviewSummary();
          setSetupStep(3);
          setStatus(`Loaded '${persona.display_name}'. Review the summary or jump into prediction.`);
        } catch (error) {
          setStatus(error.message, true);
        }
      });
      card.querySelector("[data-open-demo]").addEventListener("click", async () => {
        try {
          const payload = await bootstrapSampleProfile(persona.sample_id);
          setActiveUserId(payload.user_id);
          const nextUrl = createPredictUrl({
            sampleId: persona.sample_id,
            userId: payload.user_id,
            prompt: scenario?.prompt || "",
            category: scenario?.category || "food",
            context: scenario?.context || {},
            options: scenario?.options || [],
            mode: "baseline",
            autorun: true,
          });
          window.location.href = nextUrl;
        } catch (error) {
          setStatus(error.message, true);
        }
      });
      gallery.appendChild(card);
    });
  }

  function renderScenarioGallery() {
    const gallery = $("scenario-gallery");
    if (!gallery) return;
    gallery.innerHTML = "";
    const activePersona = getActivePersona();
    const orderedScenarios = [...(showcase.scenarios || [])].sort((left, right) => {
      const leftScore = left.sample_id === activePersona?.sample_id ? 0 : 1;
      const rightScore = right.sample_id === activePersona?.sample_id ? 0 : 1;
      return leftScore - rightScore;
    });
    if (!orderedScenarios.length) {
      gallery.innerHTML = `
        <div class="source-card">
          <strong>No showcase scenarios available.</strong>
          <p class="help">The gallery will appear here when the showcase payload loads.</p>
        </div>
      `;
      return;
    }
    orderedScenarios.forEach((scenario) => {
      const persona = getPersonaBySampleId(scenario.sample_id);
      const card = document.createElement("div");
      card.className = "source-card showcase-card";
      card.innerHTML = `
        <span class="section-tag">${escapeHtml(persona?.display_name || "Bundled persona")}</span>
        <strong>${escapeHtml(scenario.title)}</strong>
        <p class="help top-gap-sm">${escapeHtml(scenario.subtitle || "")}</p>
        <div class="mini top-gap-sm">${escapeHtml(scenario.prompt)}</div>
        <div class="chip-row top-gap-sm">
          <span class="chip">${escapeHtml(scenario.category)}</span>
          <span class="chip">${escapeHtml(formatContextSummary(scenario.context))}</span>
        </div>
        <div class="mini top-gap-sm">Options: ${escapeHtml((scenario.options || []).join(" | "))}</div>
        <div class="button-row inline top-gap-sm">
          <button class="secondary" type="button" data-fill-scenario="${escapeAttribute(scenario.scenario_id)}">Fill</button>
          <button class="primary" type="button" data-run-scenario="${escapeAttribute(scenario.scenario_id)}">Run</button>
        </div>
      `;
      card.querySelector("[data-fill-scenario]").addEventListener("click", async () => {
        try {
          await applyShowcaseScenario(scenario, { autorun: false });
        } catch (error) {
          setStatus(error.message, true);
        }
      });
      card.querySelector("[data-run-scenario]").addEventListener("click", async () => {
        try {
          await applyShowcaseScenario(scenario, { autorun: true });
        } catch (error) {
          setStatus(error.message, true);
        }
      });
      gallery.appendChild(card);
    });
  }

  async function loadOnboardingQuestionnaire() {
    const payload = await request("/profiles/onboarding-questionnaire");
    onboardingQuestionnaire = payload;
    const mbtiSelect = $("onboarding-mbti");
    if (!mbtiSelect) return;

    mbtiSelect.innerHTML = "";
    payload.mbti_options.forEach((mbti) => {
      const option = document.createElement("option");
      option.value = mbti;
      option.textContent = mbti;
      mbtiSelect.appendChild(option);
    });
  }

  function getOnboardingPayload() {
    if (!onboardingQuestionnaire) return null;
    return {
      display_name: $("onboarding-display-name").value.trim(),
      mbti: $("onboarding-mbti").value,
      responses: onboardingQuestionnaire.questions
        .map((question) => ({
          question_id: question.question_id,
          option_id: setupState.onboardingAnswers[question.question_id],
        }))
        .filter((item) => item.option_id),
    };
  }

  async function previewOnboardingProfile(payload = getOnboardingPayload()) {
    if (!payload || !payload.display_name) {
      setStatus("Enter a display name before previewing the profile.", true);
      return null;
    }
    return request("/profiles/onboard/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function escapeAttribute(value) {
    return escapeHtml(value).replaceAll('"', "&quot;");
  }

  function csvValues(value) {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function getCurrentOptionTexts() {
    return Array.from($("option-list").querySelectorAll("input"))
      .map((input) => input.value.trim())
      .filter(Boolean);
  }

  function hasOptionText(optionText) {
    return getCurrentOptionTexts().some((value) => value.toLowerCase() === optionText.trim().toLowerCase());
  }

  function canAddMoreOptions() {
    const optionList = $("option-list");
    return optionList ? optionList.children.length < 5 : false;
  }

  function createOptionRow(value = "") {
    const optionList = $("option-list");
    if (!optionList) return;
    if (optionList.children.length >= 5) {
      setStatus("You can compare up to five options at once.", true);
      return null;
    }
    const row = document.createElement("div");
    row.className = "option-row";
    row.innerHTML = `
      <input type="text" value="${escapeAttribute(value)}" placeholder="Candidate option" />
      <button class="danger" type="button">Remove</button>
    `;
    row.querySelector("input").addEventListener("input", syncOptionSuggestionButtons);
    row.querySelector("button").addEventListener("click", () => {
      if (optionList.children.length > 2) {
        row.remove();
        syncOptionSuggestionButtons();
      } else {
        setStatus("At least two options are required.", true);
      }
    });
    optionList.appendChild(row);
    syncOptionSuggestionButtons();
    return row;
  }

  function clearOptionSuggestions() {
    optionSuggestions = [];
    const panel = $("option-suggestion-panel");
    const list = $("option-suggestion-list");
    if (panel) {
      panel.classList.add("hidden");
    }
    if (list) {
      list.innerHTML = "";
    }
  }

  function syncOptionSuggestionButtons() {
    const addAllButton = $("add-suggestions-button");
    if (addAllButton) {
      const availableCount = optionSuggestions.filter((item) => !hasOptionText(item.option_text)).length;
      addAllButton.disabled = !optionSuggestions.length || availableCount === 0 || !canAddMoreOptions();
      addAllButton.textContent = availableCount > 0 ? "Add top suggestions" : "All added";
    }
    document.querySelectorAll("[data-suggestion-option]").forEach((button) => {
      const optionText = button.dataset.suggestionOption || "";
      const alreadyAdded = hasOptionText(optionText);
      button.disabled = alreadyAdded || !canAddMoreOptions();
      button.textContent = alreadyAdded ? "Added" : "Add";
    });
  }

  function addSuggestedOption(optionText) {
    if (hasOptionText(optionText)) {
      syncOptionSuggestionButtons();
      return false;
    }
    const row = createOptionRow(optionText);
    syncOptionSuggestionButtons();
    return Boolean(row);
  }

  function renderOptionSuggestions(payload) {
    optionSuggestions = payload.suggestions || [];
    const panel = $("option-suggestion-panel");
    const list = $("option-suggestion-list");
    const summary = $("option-suggestion-summary");
    if (!panel || !list || !summary) return;
    list.innerHTML = "";
    summary.textContent = Object.keys(payload.active_context || {}).length
      ? `Generated from the active profile plus context: ${Object.entries(payload.active_context)
        .map(([key, value]) => `${key}=${value}`)
        .join(" | ")}`
      : "Generated from the active profile, recent state, and relevant memories.";

    optionSuggestions.forEach((suggestion) => {
      const card = document.createElement("div");
      card.className = "suggestion-card";
      const chips = (suggestion.source_labels || [])
        .map((label) => `<span class="chip">${escapeHtml(label)}</span>`)
        .join("");
      const evidence = (suggestion.supporting_evidence || [])
        .slice(0, 2)
        .map((item) => `<div class="mini">${escapeHtml(item)}</div>`)
        .join("");
      card.innerHTML = `
        <div class="suggestion-card-header">
          <div>
            <strong>${escapeHtml(suggestion.option_text)}</strong>
            <div class="mini">fit score: ${Math.round((suggestion.confidence || 0) * 100)}%</div>
          </div>
          <button class="secondary" type="button" data-suggestion-option="${escapeAttribute(suggestion.option_text)}">Add</button>
        </div>
        <div class="chip-row">${chips}</div>
        <div class="mini">${escapeHtml(suggestion.rationale)}</div>
        ${evidence}
      `;
      card.querySelector("button").addEventListener("click", () => {
        if (addSuggestedOption(suggestion.option_text)) {
          setStatus(`Added suggested option '${suggestion.option_text}'.`);
        }
      });
      list.appendChild(card);
    });
    panel.classList.toggle("hidden", !optionSuggestions.length);
    syncOptionSuggestionButtons();
  }

  function renderFailureReasonOptions() {
    const container = $("failure-reason-list");
    if (!container) return;
    container.innerHTML = "";
    FAILURE_REASON_OPTIONS.forEach((item) => {
      const row = document.createElement("label");
      row.className = "checkbox-row";
      row.innerHTML = `
        <input type="checkbox" value="${item.id}" />
        <span>${item.label}</span>
      `;
      container.appendChild(row);
    });
  }

  function getSelectedFailureReasons() {
    return Array.from(document.querySelectorAll("#failure-reason-list input:checked")).map((node) => node.value);
  }

  function setFeedbackButtonState(disabled, label) {
    const button = $("feedback-button");
    if (!button) return;
    button.disabled = disabled;
    button.textContent = label;
  }

  function setFeedbackSaveNote(message = "", error = false) {
    const note = $("feedback-save-note");
    if (!note) return;
    note.textContent = message;
    note.classList.toggle("hidden", !message);
    note.classList.toggle("error", Boolean(message) && error);
    note.classList.toggle("success", Boolean(message) && !error);
  }

  function resetFeedbackState({ clearFields = false } = {}) {
    if (clearFields) {
      if ($("actual-option")) $("actual-option").innerHTML = "";
      $("reason-text").value = "";
      $("reason-tags").value = "";
      $("preference-shift-note").value = "";
      $("context-updates").value = "";
      document.querySelectorAll("#failure-reason-list input").forEach((node) => {
        node.checked = false;
      });
    }
    setFeedbackButtonState(false, "Save feedback");
    setFeedbackSaveNote("");
    renderModelUpdate(null);
  }

  function parseContextUpdates() {
    const rawContextUpdates = $("context-updates").value.trim();
    if (!rawContextUpdates) {
      return {};
    }
    let parsed;
    try {
      parsed = JSON.parse(rawContextUpdates);
    } catch (_) {
      throw new Error("Context updates must be valid JSON.");
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error("Context updates must be a JSON object.");
    }
    return parsed;
  }

  function prepareForNextPrediction() {
    latestPrediction = null;
    latestPredictionPayload = null;
    latestPostFeedbackPrediction = null;
    resetFeedbackState({ clearFields: true });
    $("feedback-panel").classList.add("hidden");
    $("feedback-adaptation-panel")?.classList.add("hidden");
    $("prediction-empty").classList.remove("hidden");
    $("prediction-content").classList.add("hidden");
    $("metric-confidence").textContent = "-";
    closePredictionModal();
  }

  function resetPredictionForm() {
    if (page !== "predict") return;
    $("user-id").value = getActiveUserId();
    if ($("user-display-name")) {
      const visibleName = $("predict-user-name")?.textContent || "";
      $("user-display-name").value = visibleName === "-" ? "" : visibleName;
    }
    $("category").value = "food";
    $("prompt").value = "Pick dinner after a tiring rainy evening.";
    $("time_of_day").value = "";
    $("energy").value = "";
    $("weather").value = "";
    $("with").value = "";
    $("budget").value = "";
    $("urgency").value = "";
    $("prediction-mode").value = "baseline";
    $("option-list").innerHTML = "";
    DEFAULT_OPTIONS.forEach(createOptionRow);
    clearOptionSuggestions();
    $("metric-mode").textContent = "baseline";
    prepareForNextPrediction();
  }

  async function ensureSampleLoaded(sampleId) {
    const persona = getPersonaBySampleId(sampleId);
    if (!persona) {
      throw new Error(`Unknown demo persona '${sampleId}'.`);
    }
    if (getActiveUserId() === persona.user_id) {
      return persona.user_id;
    }
    const payload = await bootstrapSampleProfile(sampleId);
    setActiveUserId(payload.user_id);
    if (page === "setup") {
      await hydrateReviewSummary();
      setSetupStep(3);
    }
    if (page === "predict") {
      await hydratePredictWorkspace();
    }
    return payload.user_id;
  }

  function applyScenarioToForm(scenario) {
    if (!scenario) return;
    $("category").value = scenario.category || "custom";
    $("prompt").value = scenario.prompt || "";
    $("time_of_day").value = scenario.context?.time_of_day || "";
    $("energy").value = scenario.context?.energy || "";
    $("weather").value = scenario.context?.weather || "";
    $("with").value = scenario.context?.with || "";
    $("budget").value = scenario.context?.budget || "";
    $("urgency").value = scenario.context?.urgency || "";
    $("prediction-mode").value = "baseline";
    $("metric-mode").textContent = "baseline";
    $("option-list").innerHTML = "";
    (scenario.options || []).forEach((optionText) => createOptionRow(optionText));
    clearOptionSuggestions();
    prepareForNextPrediction();
  }

  async function applyShowcaseScenario(scenario, { autorun = false } = {}) {
    if (!scenario) return;
    if (scenario.sample_id) {
      await ensureSampleLoaded(scenario.sample_id);
    }
    applyScenarioToForm(scenario);
    setStatus(`Loaded showcase scenario '${scenario.title}'.`);
    if (autorun) {
      await runPredictionFromForm();
    }
  }

  function getContextPayload() {
    const fields = ["time_of_day", "energy", "weather", "with", "budget", "urgency"];
    const context = {};
    fields.forEach((key) => {
      const node = $(key);
      if (!node) return;
      const value = node.value.trim();
      if (value) {
        context[key] = value;
      }
    });
    return context;
  }

  function getPredictionPayload() {
    const payload = {
      user_id: $("user-id").value.trim(),
      prompt: $("prompt").value.trim(),
      category: $("category").value.trim(),
      context: getContextPayload(),
      prediction_mode: $("prediction-mode").value,
      options: Array.from($("option-list").querySelectorAll("input"))
        .map((input) => input.value.trim())
        .filter(Boolean)
        .map((optionText) => ({ option_text: optionText })),
    };
    const llmConfig = getLlmConfig();
    if (payload.prediction_mode !== "baseline" && llmConfig) {
      payload.llm_config = llmConfig;
    }
    return payload;
  }

  function getCurrentScenarioLink({ autorun = true, focus = "" } = {}) {
    const payload = getPredictionPayload();
    const activePersona = getActivePersona();
    return createPredictUrl({
      sampleId: activePersona?.sample_id || "",
      userId: activePersona ? "" : payload.user_id,
      prompt: payload.prompt,
      category: payload.category,
      mode: payload.prediction_mode || "baseline",
      context: payload.context,
      options: payload.options.map((item) => item.option_text),
      autorun,
      focus,
    });
  }

  function buildPredictionSummaryText(prediction = latestPrediction) {
    if (!prediction) return "";
    const runnerUp = prediction.ranked_options[1];
    const activeUser = $("predict-user-name")?.textContent || $("user-display-name")?.value || prediction.user_id || "This user";
    const evidence = prediction.explanation_sections.why_this_option.slice(0, 2).join(" | ");
    return [
      `bcd prediction for ${activeUser}:`,
      `Question: ${$("prompt")?.value.trim() || ""}`,
      `Predicted choice: ${prediction.predicted_option_text} (${Math.round(prediction.confidence * 100)}% confidence)`,
      runnerUp ? `Runner-up: ${runnerUp.option_text} (${Math.round(runnerUp.confidence * 100)}%)` : "",
      `Why it won: ${prediction.explanation_sections.top_choice_summary}`,
      evidence ? `Key evidence: ${evidence}` : "",
      `Scenario link: ${getCurrentScenarioLink({ autorun: true, focus: "prediction-content" })}`,
    ]
      .filter(Boolean)
      .join("\n");
  }

  function getRankPosition(prediction, optionText) {
    return prediction.ranked_options.findIndex((item) => item.option_text === optionText);
  }

  function getRankedOptionByText(prediction, optionText) {
    return prediction.ranked_options.find((item) => item.option_text === optionText) || null;
  }

  function renderWinnerComparison(prediction) {
    const runnerUp = prediction.ranked_options[1];
    $("winner-vs-runner-up-title").textContent = runnerUp
      ? `${prediction.predicted_option_text} beat ${runnerUp.option_text}`
      : `${prediction.predicted_option_text} is the only viable fit`;
    $("winner-vs-runner-up-summary").textContent = runnerUp
      ? `The winning margin is ${Math.round(prediction.decision_audit.margin_vs_runner_up * 100)} points. This is the closest realistic alternative the system considered.`
      : "Only one clear fit stood out after combining profile, memory, and recent context.";
    const points = [
      ...prediction.explanation_sections.why_this_option.slice(0, 2),
      ...prediction.explanation_sections.why_other_options_lost.slice(0, 2),
    ].slice(0, 4);
    renderEvidenceList(
      "winner-vs-runner-up-points",
      points,
      "A direct winner-vs-runner-up explanation will appear here.",
    );
  }

  function renderFeedbackAdaptation(beforePrediction, afterPrediction, actualOptionText) {
    const panel = $("feedback-adaptation-panel");
    const summary = $("feedback-adaptation-summary");
    if (!panel || !summary || !actualOptionText) return;
    const beforeRank = getRankPosition(beforePrediction, actualOptionText);
    const afterRank = getRankPosition(afterPrediction, actualOptionText);
    const beforeItem = getRankedOptionByText(beforePrediction, actualOptionText);
    const afterItem = getRankedOptionByText(afterPrediction, actualOptionText);
    const points = [];
    if (beforeRank >= 0 && afterRank >= 0) {
      const movement = beforeRank - afterRank;
      if (movement > 0) {
        points.push(`'${actualOptionText}' moved up from #${beforeRank + 1} to #${afterRank + 1} after the feedback was written into memory.`);
      } else if (movement < 0) {
        points.push(`'${actualOptionText}' moved down from #${beforeRank + 1} to #${afterRank + 1}, showing the new evidence changed the ranking in a non-trivial way.`);
      } else {
        points.push(`'${actualOptionText}' stayed at #${afterRank + 1}, but the stored feedback still updated memory and recent-state signals.`);
      }
    }
    if (beforeItem && afterItem) {
      const confidenceDelta = Math.round((afterItem.confidence - beforeItem.confidence) * 100);
      const deltaLabel = confidenceDelta > 0 ? `+${confidenceDelta}` : `${confidenceDelta}`;
      points.push(`Confidence for '${actualOptionText}' changed by ${deltaLabel} points on the rerun.`);
    }
    if (beforePrediction.predicted_option_text !== afterPrediction.predicted_option_text) {
      points.push(`The predicted winner changed from '${beforePrediction.predicted_option_text}' to '${afterPrediction.predicted_option_text}'.`);
    } else {
      points.push(`The winner stayed '${afterPrediction.predicted_option_text}', but the supporting evidence was refreshed by the new memory and snapshot.`);
    }
    summary.textContent = `After feedback, bcd reran the same scenario and recomputed the ranking with the newly stored memory, updated snapshot, and fresh adaptation signals.`;
    renderEvidenceList("feedback-adaptation-points", points, "No adaptation changes were detected yet.");
    panel.classList.remove("hidden");
  }

  function renderPrediction(prediction) {
    latestPrediction = prediction;
    latestPostFeedbackPrediction = null;
    resetFeedbackState({ clearFields: true });
    $("feedback-adaptation-panel")?.classList.add("hidden");
    $("prediction-empty").classList.add("hidden");
    $("prediction-content").classList.remove("hidden");
    $("feedback-panel").classList.remove("hidden");
    openPredictionModal();
    $("predicted-option-text").textContent = prediction.predicted_option_text;
    $("predicted-option-subtitle").textContent = `${$("predict-user-name")?.textContent || "This user"} under ${formatContextSummary(prediction.decision_audit.active_context || {})}`;
    $("prediction-explanation").textContent = prediction.explanation_sections.top_choice_summary;
    $("strategy-chip").textContent = `strategy: ${prediction.strategy}`;
    $("llm-chip").textContent = `llm used: ${prediction.llm_used ? `yes (${prediction.llm_provider || "configured"})` : "no"}`;
    $("metric-mode").textContent = prediction.strategy;
    $("metric-confidence").textContent = `${Math.round(prediction.confidence * 100)}%`;
    const requestedMode = $("prediction-mode").value;
    const llmWarning = $("llm-warning");
    if (requestedMode !== "baseline" && !prediction.llm_used) {
      llmWarning.textContent = prediction.llm_error
        ? `LLM fallback: ${prediction.llm_error}`
        : "LLM was requested, but the prediction fell back to the baseline ranker.";
      llmWarning.classList.remove("hidden");
    } else {
      llmWarning.textContent = "";
      llmWarning.classList.add("hidden");
    }

    renderEvidenceList("top-choice-evidence", prediction.explanation_sections.why_this_option, "No strong top-choice evidence was returned.");
    renderEvidenceList("recent-state-evidence", prediction.explanation_sections.what_recent_state_mattered, "No recent-state evidence was returned.");
    renderEvidenceList("memory-explanation-list", prediction.explanation_sections.what_memories_mattered, "No memory explanation was returned.");
    renderEvidenceList("why-others-lost-list", prediction.explanation_sections.why_other_options_lost, "No comparison evidence was returned.");
    $("audit-confidence-chip").textContent = `confidence: ${prediction.decision_audit.confidence_label}`;
    $("audit-margin-chip").textContent = `margin: ${Math.round(prediction.decision_audit.margin_vs_runner_up * 100)} pts`;
    $("audit-context-chip").textContent = `context: ${Object.entries(prediction.decision_audit.active_context || {})
      .map(([key, value]) => `${key}=${value}`)
      .join(" | ") || "none"}`;
    renderWinnerComparison(prediction);
    renderEvidenceList("audit-decisive-factors", prediction.decision_audit.decisive_factors, "No decisive factors were captured.");
    renderEvidenceList("audit-watchouts", prediction.decision_audit.watchouts, "No specific watchouts were captured.");
    renderEvidenceList("audit-adaptation-signals", prediction.decision_audit.adaptation_signals, "No adaptation signals were active.");
    renderAgentWorkflow(prediction.agent_workflow);
    renderInfluenceList("top-choice-influence-list", prediction.top_choice_influence, "No influence breakdown was returned.");
    renderAgentAgreement(prediction.agent_agreement);

    const rankList = $("rank-list");
    rankList.innerHTML = "";
    const assessmentMap = new Map((prediction.option_influences || []).map((item) => [item.option_id, item]));
    prediction.ranked_options.forEach((item, index) => {
      const componentGrid = (item.component_scores || [])
        .map(
          (component) => `
            <div class="component-chip">
              <strong>${escapeHtml(component.name)}</strong>
              <div class="mini">weighted score: ${component.weighted_score}</div>
              <div class="mini">${escapeHtml(component.reason)}</div>
            </div>
          `,
        )
        .join("");
      const assessment = assessmentMap.get(item.option_id);
      const influenceChips = assessment
        ? ["stable_profile", "recent_state", "memory", "context", "llm"]
          .map((key) => `<span class="chip">${escapeHtml(formatInfluenceLabel(key))}: ${formatSignedScore(assessment.influence[key] || 0)}</span>`)
          .join("")
        : `<span class="chip">No grouped influence available</span>`;
      const node = document.createElement("div");
      node.className = "rank-item";
      const componentPreview = (item.component_scores || [])
        .slice(0, 2)
        .map((component) => `${component.name}: ${component.weighted_score}`)
        .join(" | ");
      node.innerHTML = `
        <strong>${index + 1}. ${escapeHtml(item.option_text)}</strong>
        <div class="mini">confidence: ${Math.round(item.confidence * 100)}% | raw score: ${item.raw_score}</div>
        <div class="mini">${escapeHtml(item.reason_summary)}</div>
        <div class="mini top-gap-sm">Top scoring factors: ${escapeHtml(componentPreview || "No component details")}</div>
        <div class="chip-row top-gap-sm">${influenceChips}</div>
        <details class="top-gap-sm">
          <summary class="summary-trigger">Detailed breakdown</summary>
          <div class="split-cards top-gap-sm">
            <section>
              <h3>Why choose</h3>
              <div class="mini">${escapeHtml((assessment?.why_choose || []).join(" | ") || "No strong choose case was returned.")}</div>
            </section>
            <section>
              <h3>Why avoid</h3>
              <div class="mini">${escapeHtml((assessment?.why_avoid || []).join(" | ") || "No strong avoid case was returned.")}</div>
            </section>
          </div>
          <div class="component-grid top-gap-sm">${componentGrid || `<div class="component-chip"><div class="mini">No component details.</div></div>`}</div>
          <div class="mini top-gap-sm"><strong>Supporting evidence:</strong> ${escapeHtml((item.supporting_evidence || []).join(" | ") || "none")}</div>
          <div class="mini"><strong>Counter evidence:</strong> ${escapeHtml((item.counter_evidence || []).join(" | ") || "none")}</div>
        </details>
      `;
      rankList.appendChild(node);
    });

    const memoryList = $("memory-list");
    memoryList.innerHTML = "";
    prediction.retrieved_memories.forEach((memory) => {
      const node = document.createElement("div");
      node.className = "memory-item";
      node.innerHTML = `
        <strong>${escapeHtml(memory.chosen_option_text)}</strong>
        <div class="mini">role: ${escapeHtml(memory.memory_role)}</div>
        <div class="mini">${escapeHtml(memory.summary)}</div>
        <div class="mini">retrieval score: ${memory.retrieval_score}</div>
        <div class="mini">why retrieved: ${escapeHtml((memory.why_retrieved || []).join(" | ") || "n/a")}</div>
        <div class="mini">matched terms: ${escapeHtml((memory.matched_terms || []).join(", ") || "none")}</div>
      `;
      memoryList.appendChild(node);
    });
    if (!prediction.retrieved_memories.length) {
      memoryList.innerHTML = `<div class="memory-item"><div class="mini">No supporting memories were returned for this request.</div></div>`;
    }

    const actualOptionSelect = $("actual-option");
    actualOptionSelect.innerHTML = "";
    prediction.ranked_options.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.option_id;
      option.textContent = item.option_text;
      if (item.option_id === prediction.predicted_option_id) {
        option.selected = true;
      }
      actualOptionSelect.appendChild(option);
    });
  }

  function openPredictionModal() {
    const modal = $("prediction-modal");
    if (!modal) return;
    modal.classList.remove("hidden");
    document.body.classList.add("modal-open");
  }

  function closePredictionModal() {
    const modal = $("prediction-modal");
    if (!modal) return;
    modal.classList.add("hidden");
    if ($("global-error-modal")?.classList.contains("hidden")) {
      document.body.classList.remove("modal-open");
    }
  }

  function renderEvidenceList(containerId, items, emptyMessage) {
    const container = $(containerId);
    if (!container) return;
    container.innerHTML = "";
    (items || []).forEach((item) => {
      const node = document.createElement("div");
      node.className = "signal-item";
      node.innerHTML = `<div class="mini">${escapeHtml(item)}</div>`;
      container.appendChild(node);
    });
    if (!(items || []).length) {
      container.innerHTML = `<div class="signal-item"><div class="mini">${escapeHtml(emptyMessage)}</div></div>`;
    }
  }

  async function hydratePredictWorkspace() {
    if (page !== "predict") return;
    const userId = getActiveUserId();
    const emptyState = $("predict-empty-state");
    const workspace = $("predict-workspace");
    const banner = $("predict-user-banner");
    if (!userId) {
      emptyState.classList.remove("hidden");
      workspace.classList.add("hidden");
      $("metric-user").textContent = "None";
      if ($("user-display-name")) $("user-display-name").value = "";
      $("user-id").value = "";
      banner.classList.add("hidden");
      return;
    }
    try {
      const profile = await fetchProfileBundle(userId);
      $("metric-user").textContent = profile.display_name;
      $("predict-user-name").textContent = profile.display_name;
      $("predict-user-summary").textContent = profile.profile_summary;
      $("user-id").value = userId;
      if ($("user-display-name")) $("user-display-name").value = profile.display_name;
      emptyState.classList.add("hidden");
      workspace.classList.remove("hidden");
      banner.classList.remove("hidden");
      renderScenarioGallery();
    } catch (error) {
      emptyState.classList.remove("hidden");
      workspace.classList.add("hidden");
      banner.classList.add("hidden");
      setStatus(`Active user could not be loaded: ${error.message}`, true);
      return;
    }
  }

  function setSetupStep(step) {
    setupState.step = step;
    document.querySelectorAll(".wizard-panel").forEach((panel) => {
      const isActive = panel.id === `setup-step-${step}`;
      panel.classList.toggle("hidden", !isActive);
    });
    document.querySelectorAll("#setup-stepper .wizard-step").forEach((item) => {
      const itemStep = Number(item.dataset.step);
      item.classList.toggle("active", itemStep === step);
      item.classList.toggle("complete", itemStep < step);
    });
  }

  function renderStructuredQuestionCard() {
    if (!onboardingQuestionnaire) return;
    const question = onboardingQuestionnaire.questions[setupState.onboardingIndex];
    if (!question) return;

    const total = onboardingQuestionnaire.questions.length;
    $("onboarding-progress-text").textContent = `Question ${setupState.onboardingIndex + 1} / ${total}`;
    $("onboarding-progress-fill").style.width = `${((setupState.onboardingIndex + 1) / total) * 100}%`;
    $("onboarding-question-label").textContent = question.title || `Question ${setupState.onboardingIndex + 1}`;
    $("onboarding-question-title").textContent = question.prompt;
    $("onboarding-question-prompt").textContent = "Pick the option that feels most natural for this user.";

    const selectedOptionId = setupState.onboardingAnswers[question.question_id] || "";
    const optionList = $("onboarding-option-list");
    optionList.innerHTML = "";
    question.options.forEach((option) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `wizard-option-card${selectedOptionId === option.option_id ? " selected" : ""}`;
      button.innerHTML = `
        <span class="section-tag">${escapeHtml(option.label)}</span>
        <strong>${escapeHtml(option.description)}</strong>
      `;
      button.addEventListener("click", () => {
        setupState.onboardingAnswers[question.question_id] = option.option_id;
        renderStructuredQuestionCard();
      });
      optionList.appendChild(button);
    });

    $("structured-back-button").textContent = setupState.onboardingIndex === 0 ? "Back" : "Previous question";
    $("structured-next-button").textContent = setupState.onboardingIndex === total - 1 ? "Create profile" : "Next question";
  }

  function renderCreateUserStep() {
    $("structured-create-flow").classList.toggle("hidden", setupState.source !== "structured");
    $("import-create-flow").classList.toggle("hidden", setupState.source !== "import");
    if (setupState.source === "structured") {
      $("create-user-title").textContent = "Create user";
      $("create-user-help").textContent = "Answer one question at a time. The profile will be created after the last answer.";
      renderStructuredQuestionCard();
    } else if (setupState.source === "import") {
      $("create-user-title").textContent = "Import user";
      $("create-user-help").textContent = "Upload a ChatGPT export and let the system infer a starter profile.";
    }
  }

  async function handleStructuredNext() {
    if (!onboardingQuestionnaire) {
      setStatus("The questionnaire is still loading.", true);
      return;
    }
    if (!$("onboarding-display-name").value.trim()) {
      setStatus("Enter a display name before continuing.", true);
      return;
    }
    if (!$("onboarding-mbti").value.trim()) {
      setStatus("Choose an MBTI value before continuing.", true);
      return;
    }

    const question = onboardingQuestionnaire.questions[setupState.onboardingIndex];
    if (!setupState.onboardingAnswers[question.question_id]) {
      setStatus("Choose one answer before moving on.", true);
      return;
    }

    const isLastQuestion = setupState.onboardingIndex === onboardingQuestionnaire.questions.length - 1;
    if (!isLastQuestion) {
      setupState.onboardingIndex += 1;
      renderStructuredQuestionCard();
      return;
    }

    const payload = getOnboardingPayload();
    if (!payload || payload.responses.length !== onboardingQuestionnaire.questions.length) {
      setStatus("Complete every onboarding question before creating the profile.", true);
      return;
    }

    try {
      setStatus("Creating profile from structured onboarding answers...");
      setupState.preview = await previewOnboardingProfile(payload);
      const created = await request("/profiles/onboard", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setActiveUserId(created.user_id);
      await hydrateReviewSummary();
      setSetupStep(3);
      setStatus(`Created profile '${created.user_id}'. Review the summary or continue to prediction.`);
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  function wireSetupPage() {
    $("choose-source-sample").addEventListener("click", async () => {
      try {
        setStatus("Loading sample profile...");
        const payload = await bootstrapSampleProfile(DEFAULT_SIGNATURE_SAMPLE_ID);
        setActiveUserId(payload.user_id);
        await hydrateReviewSummary();
        setSetupStep(3);
        setStatus(`Sample profile '${payload.user_id}' is ready. Review the summary or continue to prediction.`);
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    $("choose-source-structured").addEventListener("click", () => {
      setupState.source = "structured";
      setupState.onboardingIndex = 0;
      setupState.onboardingAnswers = {};
      renderCreateUserStep();
      setSetupStep(2);
    });

    $("choose-source-import").addEventListener("click", () => {
      setupState.source = "import";
      renderCreateUserStep();
      setSetupStep(2);
    });

    $("resume-existing-user-button").addEventListener("click", async () => {
      await hydrateReviewSummary();
      setSetupStep(3);
    });

    $("launch-signature-demo-button").addEventListener("click", async () => {
      try {
        const persona = getPersonaBySampleId(DEFAULT_SIGNATURE_SAMPLE_ID) || showcase.personas[0];
        const scenario = getScenarioById(persona?.default_scenario_id);
        if (!persona || !scenario) {
          throw new Error("The signature demo is not available right now.");
        }
        const payload = await bootstrapSampleProfile(persona.sample_id);
        setActiveUserId(payload.user_id);
        window.location.href = createPredictUrl({
          sampleId: persona.sample_id,
          userId: payload.user_id,
          prompt: scenario.prompt,
          category: scenario.category,
          context: scenario.context,
          options: scenario.options,
          mode: "baseline",
          autorun: true,
        });
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    $("structured-back-button").addEventListener("click", () => {
      if (setupState.onboardingIndex === 0) {
        setSetupStep(1);
        return;
      }
      setupState.onboardingIndex -= 1;
      renderStructuredQuestionCard();
    });

    $("structured-next-button").addEventListener("click", handleStructuredNext);

    $("import-back-button").addEventListener("click", () => {
      setSetupStep(1);
    });

    $("import-profile-button").addEventListener("click", async () => {
      try {
        const displayName = $("import-display-name").value.trim();
        const file = $("chatgpt-export-file").files[0];
        if (!displayName || !file) {
          setStatus("Choose a display name and a ChatGPT export file.", true);
          return;
        }
        setStatus("Importing ChatGPT export and inferring a profile...");
        const formData = new FormData();
        formData.append("display_name", displayName);
        formData.append("file", file);
        const payload = await request("/profiles/import-chatgpt-export", {
          method: "POST",
          body: formData,
        });
        setActiveUserId(payload.user_profile.user_id);
        await hydrateReviewSummary();
        setSetupStep(3);
        setStatus(`Imported profile '${payload.user_profile.user_id}' from ${payload.import_stats.conversation_count} conversations.`);
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    $("open-optional-adjustments-button").addEventListener("click", async () => {
      await hydrateOptionalAdjustments();
      setSetupStep(4);
    });

    $("back-to-summary-button").addEventListener("click", async () => {
      await hydrateReviewSummary();
      setSetupStep(3);
    });

    $("restart-setup-button").addEventListener("click", () => {
      setupState.source = null;
      setupState.onboardingAnswers = {};
      setupState.onboardingIndex = 0;
      setupState.preview = null;
      setSetupStep(1);
      setStatus("Choose a new source to create or load a user.");
    });

    $("add-recent-state-note-button").addEventListener("click", async () => {
      try {
        const userId = getActiveUserId();
        const noteText = $("recent-state-note").value.trim();
        if (!userId || !noteText) {
          setStatus("Load a user and enter a recent-state note first.", true);
          return;
        }
        setStatus("Saving recent-state note...");
        await request(`/profiles/${encodeURIComponent(userId)}/recent-state`, {
          method: "POST",
          body: JSON.stringify({ note_text: noteText, tags: [] }),
        });
        $("recent-state-note").value = "";
        await hydrateReviewSummary();
        await hydrateOptionalAdjustments();
        setStatus("Recent-state note saved.");
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    renderExistingUserBanner();
    renderSetupPersonaGallery();
    setSetupStep(setupState.step);
  }

  function wirePredictPage() {
    renderFailureReasonOptions();
    loadSavedLlmSettings();
    wireLlmButtons();
    resetPredictionForm();
    renderScenarioGallery();
    $("add-option-button").addEventListener("click", () => {
      if (createOptionRow("")) {
        setStatus("Added another option slot.");
      }
    });
    $("reset-button").addEventListener("click", resetPredictionForm);
    $("copy-scenario-link-button").addEventListener("click", async () => {
      try {
        await copyTextToClipboard(getCurrentScenarioLink({ autorun: true }), "Copied a runnable scenario link.");
      } catch (error) {
        setStatus(error.message, true);
      }
    });
    $("copy-result-summary-button").addEventListener("click", async () => {
      try {
        await copyTextToClipboard(
          latestPrediction ? buildPredictionSummaryText(latestPrediction) : getCurrentScenarioLink({ autorun: true }),
          latestPrediction ? "Copied the result summary." : "Copied the runnable scenario link.",
        );
      } catch (error) {
        setStatus(error.message, true);
      }
    });
    $("close-prediction-button").addEventListener("click", closePredictionModal);
    $("edit-prediction-button").addEventListener("click", closePredictionModal);
    $("prediction-modal-backdrop").addEventListener("click", closePredictionModal);
    $("copy-result-link-button").addEventListener("click", async () => {
      try {
        await copyTextToClipboard(
          getCurrentScenarioLink({ autorun: true, focus: "prediction-content" }),
          "Copied a rerunnable result link.",
        );
      } catch (error) {
        setStatus(error.message, true);
      }
    });
    $("copy-result-text-button").addEventListener("click", async () => {
      try {
        if (!latestPrediction) {
          setStatus("Run a prediction before copying the result text.", true);
          return;
        }
        await copyTextToClipboard(buildPredictionSummaryText(latestPrediction), "Copied the result text.");
      } catch (error) {
        setStatus(error.message, true);
      }
    });
    $("suggest-options-button").addEventListener("click", async () => {
      try {
        await suggestOptionsFromCurrentForm();
      } catch (error) {
        setStatus(error.message, true);
      }
    });
    $("add-suggestions-button").addEventListener("click", () => {
      let addedCount = 0;
      optionSuggestions.forEach((suggestion) => {
        if (!canAddMoreOptions()) return;
        if (addSuggestedOption(suggestion.option_text)) {
          addedCount += 1;
        }
      });
      if (addedCount) {
        setStatus(`Added ${addedCount} suggested option${addedCount === 1 ? "" : "s"}.`);
      }
      syncOptionSuggestionButtons();
    });
    $("clear-suggestions-button").addEventListener("click", () => {
      clearOptionSuggestions();
      setStatus("Cleared suggested options.");
    });
    ["prompt", "category", "time_of_day", "energy", "weather", "with", "budget", "urgency"].forEach((id) => {
      $(id).addEventListener("input", clearOptionSuggestions);
      $(id).addEventListener("change", clearOptionSuggestions);
    });

    $("predict-button").addEventListener("click", async () => {
      await runPredictionFromForm();
    });

    $("feedback-button").addEventListener("click", async () => {
      if (!latestPrediction) {
        setStatus("Run a prediction before saving feedback.", true);
        return;
      }
      try {
        setFeedbackButtonState(true, "Saving...");
        setFeedbackSaveNote("");
        setStatus("Saving feedback...");
        const feedback = await request(`/decisions/${encodeURIComponent(latestPrediction.request_id)}/feedback`, {
          method: "POST",
          body: JSON.stringify({
            actual_option_id: $("actual-option").value,
            reason_text: $("reason-text").value.trim() || null,
            reason_tags: csvValues($("reason-tags").value),
            failure_reasons: getSelectedFailureReasons(),
            context_updates: parseContextUpdates(),
            preference_shift_note: $("preference-shift-note").value.trim() || null,
          }),
        });
        setFeedbackButtonState(true, "Feedback saved");
        renderModelUpdate(feedback);
        setFeedbackSaveNote(
          `Saved actual choice '${feedback.actual_option_text}'. Memory and profile snapshot were updated.`,
        );
        setStatus("Feedback saved. Future predictions can now adapt to this choice.");
        if (latestPredictionPayload) {
          try {
            const rerunPrediction = await request("/decisions/predict", {
              method: "POST",
              body: JSON.stringify(latestPredictionPayload),
            });
            latestPostFeedbackPrediction = rerunPrediction;
            renderFeedbackAdaptation(latestPrediction, rerunPrediction, feedback.actual_option_text);
          } catch (rerunError) {
            setFeedbackSaveNote(
              `Saved actual choice '${feedback.actual_option_text}', but the automatic rerun failed: ${rerunError.message}`,
              true,
            );
          }
        }
      } catch (error) {
        if (error.message === "Feedback has already been recorded for this prediction.") {
          setFeedbackButtonState(true, "Feedback saved");
          setFeedbackSaveNote("Feedback was already recorded for this prediction.");
          setStatus("Feedback was already recorded for this prediction.");
          return;
        }
        setFeedbackButtonState(false, "Save feedback");
        setFeedbackSaveNote(error.message, true);
        setStatus(error.message, true);
      }
    });
  }

  async function runPredictionFromForm() {
    try {
      const payload = getPredictionPayload();
      if (!payload.user_id || !payload.prompt || payload.options.length < 2) {
        setStatus("Please provide an active user, a prompt, and at least two options.", true);
        return;
      }
      if (payload.prediction_mode !== "baseline" && !payload.llm_config) {
        setStatus("LLM or hybrid mode requires an API key in the LLM settings section.", true);
        return;
      }
      prepareForNextPrediction();
      latestPredictionPayload = JSON.parse(JSON.stringify(payload));
      setStatus("Running prediction...");
      const prediction = await request("/decisions/predict", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      renderPrediction(prediction);
      setStatus(
        prediction.llm_error
          ? `Prediction complete with fallback. Top choice: ${prediction.predicted_option_text}`
          : `Prediction complete. Top choice: ${prediction.predicted_option_text}`,
      );
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function suggestOptionsFromCurrentForm() {
    const payload = {
      user_id: $("user-id").value.trim(),
      prompt: $("prompt").value.trim(),
      category: $("category").value.trim(),
      context: getContextPayload(),
      existing_options: getCurrentOptionTexts(),
      max_suggestions: 4,
    };
    if (!payload.user_id) {
      setStatus("Load a user before requesting suggested options.", true);
      return;
    }
    if (!payload.prompt) {
      setStatus("Enter a question before requesting suggested options.", true);
      return;
    }
    setStatus("Generating personalized option suggestions...");
    const response = await request("/decisions/suggest-options", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderOptionSuggestions(response);
    setStatus("Suggested options are ready. Add the ones that feel realistic for this user.");
  }

  async function saveAutomatedFeedbackIfRequested() {
    if (page !== "predict" || urlParams.get("autofeedback") !== "1" || !latestPrediction) {
      return;
    }
    const actualOptionId =
      (urlParams.get("actual_option_id") || "").trim() || latestPrediction.predicted_option_id;
    if ($("actual-option")) {
      $("actual-option").value = actualOptionId;
    }
    if ($("reason-text")) {
      $("reason-text").value =
        (urlParams.get("reason_text") || "").trim() || "Matches the recent pattern for this user.";
    }
    if ($("reason-tags")) {
      $("reason-tags").value = (urlParams.get("reason_tags") || "recent_state,stable_preference").trim();
    }
    $("feedback-button").click();
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
  }

  function focusDemoSectionFromUrl() {
    if (page !== "predict") return;
    const focusTarget = (urlParams.get("focus") || "").trim();
    if (!focusTarget) return;
    const node = $(focusTarget);
    if (node) {
      node.scrollIntoView({ behavior: "instant", block: "start" });
    }
  }

  async function runPredictAutomationFromUrl() {
    if (page !== "predict") return;
    if (urlParams.get("autosuggest") === "1") {
      await suggestOptionsFromCurrentForm();
    }
    if (urlParams.get("autorun") === "1" && getActiveUserId()) {
      await runPredictionFromForm();
      await saveAutomatedFeedbackIfRequested();
    }
    focusDemoSectionFromUrl();
  }

  async function ensureSampleFromUrlIfNeeded() {
    const sampleId = (urlParams.get("sample_id") || "").trim();
    if (!sampleId) return;
    await ensureSampleLoaded(sampleId);
  }

  async function init() {
    try {
      try {
        showcase = await fetchShowcase();
      } catch (_) {
        showcase = { personas: [], scenarios: [] };
      }
      applyUrlStateOverrides();
      ensureErrorModal();
      if (page === "setup") {
        await loadOnboardingQuestionnaire();
        wireSetupPage();
        if (getActiveUserId()) {
          await hydrateReviewSummary();
          setSetupStep(3);
        }
      }
      if (page === "predict") {
        wirePredictPage();
        await ensureSampleFromUrlIfNeeded();
        await hydratePredictWorkspace();
        applyPredictUrlOverrides();
        await runPredictAutomationFromUrl();
      }
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  init();
})();
