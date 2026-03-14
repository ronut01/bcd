(function () {
  const ACTIVE_USER_KEY = "bcd.activeUserId";
  const LLM_STORAGE_KEY = "bcd.llmSettings";
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
  let onboardingQuestionnaire = null;
  let latestPrediction = null;
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

    $("setup-metric-user").textContent = userId;
    $("setup-metric-signals").textContent = String(profile.signal_count || 0);
    $("setup-metric-notes").textContent = String(recentState.length);
    $("setup-user-name").textContent = profile.display_name;
    $("setup-user-id").textContent = profile.user_id;
    $("setup-user-summary").textContent = profile.profile_summary;
    renderChipRow("signal-summary", [
      `${profile.pending_signal_count} pending`,
      `${Math.max((profile.signal_count || 0) - (profile.pending_signal_count || 0), 0)} reviewed`,
      `${profile.history_count} decisions`,
    ], "No signals");
    renderSimpleList("stable-highlights", extractStableHighlights(profile), "No stable highlights yet.");
    renderSimpleList(
      "recent-summary-list",
      [
        ...(profile.latest_snapshot?.short_term_preference_notes || []),
        ...(profile.latest_snapshot?.drift_markers || []),
        ...Object.values(card.recent_summary || {}).flatMap((value) => Array.isArray(value) ? value : []),
      ].slice(0, 6),
      "No recent-state highlights yet.",
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
    title.textContent = profile ? `${profile.display_name} (${profile.user_id})` : userId;
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

  function createOptionRow(value = "") {
    const optionList = $("option-list");
    if (!optionList) return;
    const row = document.createElement("div");
    row.className = "option-row";
    row.innerHTML = `
      <input type="text" value="${escapeAttribute(value)}" placeholder="Candidate option" />
      <button class="danger" type="button">Remove</button>
    `;
    row.querySelector("button").addEventListener("click", () => {
      if (optionList.children.length > 2) {
        row.remove();
      } else {
        setStatus("At least two options are required.", true);
      }
    });
    optionList.appendChild(row);
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

  function resetPredictionForm() {
    if (page !== "predict") return;
    $("user-id").value = getActiveUserId();
    $("category").value = "food";
    $("prompt").value = "Pick dinner after a tiring rainy evening.";
    $("time_of_day").value = "night";
    $("energy").value = "low";
    $("weather").value = "rainy";
    $("with").value = "alone";
    $("mood").value = "";
    $("budget").value = "";
    $("urgency").value = "";
    $("prediction-mode").value = "hybrid";
    $("reason-text").value = "";
    $("reason-tags").value = "";
    $("preference-shift-note").value = "";
    $("context-updates").value = "";
    document.querySelectorAll("#failure-reason-list input").forEach((node) => {
      node.checked = false;
    });
    $("option-list").innerHTML = "";
    DEFAULT_OPTIONS.forEach(createOptionRow);
    $("feedback-panel").classList.add("hidden");
    closePredictionModal();
    $("prediction-empty").classList.remove("hidden");
    $("prediction-content").classList.add("hidden");
    latestPrediction = null;
    $("metric-mode").textContent = "hybrid";
  }

  function getContextPayload() {
    const fields = ["time_of_day", "energy", "weather", "with", "mood", "budget", "urgency"];
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

  function renderPrediction(prediction) {
    latestPrediction = prediction;
    $("prediction-empty").classList.add("hidden");
    $("prediction-content").classList.remove("hidden");
    $("feedback-panel").classList.remove("hidden");
    openPredictionModal();
    $("predicted-option-text").textContent = prediction.predicted_option_text;
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
    $("audit-confidence-label").textContent = prediction.decision_audit.confidence_label;
    $("audit-margin").textContent = `margin vs runner-up: ${Math.round(prediction.decision_audit.margin_vs_runner_up * 100)} pts`;
    $("audit-context").textContent = Object.entries(prediction.decision_audit.active_context || {})
      .map(([key, value]) => `${key}=${value}`)
      .join(" | ") || "No active context";
    renderEvidenceList("audit-decisive-factors", prediction.decision_audit.decisive_factors, "No decisive factors were captured.");
    renderEvidenceList("audit-watchouts", prediction.decision_audit.watchouts, "No specific watchouts were captured.");
    renderEvidenceList("audit-adaptation-signals", prediction.decision_audit.adaptation_signals, "No adaptation signals were active.");

    const rankList = $("rank-list");
    rankList.innerHTML = "";
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
        <details class="top-gap-sm">
          <summary class="summary-trigger">Detailed breakdown</summary>
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
      banner.classList.add("hidden");
      return;
    }
    try {
      const profile = await fetchProfileBundle(userId);
      $("metric-user").textContent = userId;
      $("predict-user-name").textContent = profile.display_name;
      $("predict-user-id").textContent = profile.user_id;
      $("predict-user-summary").textContent = profile.profile_summary;
      $("user-id").value = userId;
      emptyState.classList.add("hidden");
      workspace.classList.remove("hidden");
      banner.classList.remove("hidden");
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
        const payload = await request("/profiles/bootstrap-sample", { method: "POST" });
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
    setSetupStep(setupState.step);
  }

  function wirePredictPage() {
    renderFailureReasonOptions();
    loadSavedLlmSettings();
    wireLlmButtons();
    resetPredictionForm();
    $("add-option-button").addEventListener("click", () => createOptionRow(""));
    $("reset-button").addEventListener("click", resetPredictionForm);
    $("close-prediction-button").addEventListener("click", closePredictionModal);
    $("edit-prediction-button").addEventListener("click", closePredictionModal);
    $("prediction-modal-backdrop").addEventListener("click", closePredictionModal);

    $("predict-button").addEventListener("click", async () => {
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
    });

    $("feedback-button").addEventListener("click", async () => {
      if (!latestPrediction) {
        setStatus("Run a prediction before saving feedback.", true);
        return;
      }
      try {
        setStatus("Saving feedback...");
        let contextUpdates = {};
        const rawContextUpdates = $("context-updates").value.trim();
        if (rawContextUpdates) {
          contextUpdates = JSON.parse(rawContextUpdates);
        }
        await request(`/decisions/${encodeURIComponent(latestPrediction.request_id)}/feedback`, {
          method: "POST",
          body: JSON.stringify({
            actual_option_id: $("actual-option").value,
            reason_text: $("reason-text").value.trim() || null,
            reason_tags: csvValues($("reason-tags").value),
            failure_reasons: getSelectedFailureReasons(),
            context_updates: contextUpdates,
            preference_shift_note: $("preference-shift-note").value.trim() || null,
          }),
        });
        setStatus("Feedback saved. If the recent state needs adjustment, update it on the setup page.");
      } catch (error) {
        setStatus(error.message, true);
      }
    });
  }

  async function init() {
    try {
      ensureErrorModal();
      if (page === "setup") {
        await loadOnboardingQuestionnaire();
        wireSetupPage();
        if (getActiveUserId()) {
          await hydrateReviewSummary();
        }
      }
      if (page === "predict") {
        wirePredictPage();
        await hydratePredictWorkspace();
      }
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  init();
})();
