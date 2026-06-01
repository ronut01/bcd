const baseUrl = process.env.BCD_E2E_BASE_URL ?? "http://127.0.0.1:3940";
const runCodex = process.env.BCD_E2E_CODEX !== "0";

const decisionRequest = {
  question: "Where should I work from tomorrow afternoon?",
  context: "I need deep focus for writing, but I also want a little change of scenery. I have no meetings after lunch.",
  options: ["Home desk", "Quiet cafe"]
};

const profile = {
  mbti: "INTJ",
  preferences: [
    {
      id: "decision_pace",
      label: "Decision pace",
      answer: "I compare a few concrete tradeoffs"
    },
    {
      id: "risk",
      label: "Risk posture",
      answer: "Accept risk for meaningful upside"
    },
    {
      id: "energy",
      label: "Energy signal",
      answer: "Protect calm and routine"
    },
    {
      id: "tradeoff",
      label: "Typical tradeoff",
      answer: "I often choose predictable focus over social novelty when work quality matters."
    }
  ]
};

async function main() {
  const startedAt = Date.now();
  const firstBootstrap = await request("GET", "/api/bootstrap");
  assert(firstBootstrap.hasProfile === false, "empty bootstrap should not have a profile");

  if (runCodex) {
    const codex = await request("POST", "/api/codex/check", {});
    assert(codex.ok === true, `Codex connection failed: ${codex.details ?? "unknown error"}`);
    console.log(`codex: ${codex.version}`);
  }

  const invalid = await request("POST", "/api/onboarding", {
    mbti: "INTJ",
    preferences: profile.preferences.slice(0, 2)
  }, false);
  assert(invalid.status === 400, "invalid onboarding should return 400");

  const onboarding = await request("POST", "/api/onboarding", profile);
  assert(onboarding.profileMarkdown.includes('mbti: "INTJ"'), "profile markdown should include MBTI");

  const secondBootstrap = await request("GET", "/api/bootstrap");
  assert(secondBootstrap.hasProfile === true, "bootstrap should see saved profile");

  if (runCodex) {
    const suggestion = await request("POST", "/api/options/suggest", {
      question: decisionRequest.question,
      context: decisionRequest.context
    });
    assert(Array.isArray(suggestion.options) && suggestion.options.length >= 2, "Codex should suggest at least two options");

    const prediction = await request("POST", "/api/predict", {
      request: decisionRequest,
      confirmedOptions: true
    });
    assert(decisionRequest.options.includes(prediction.prediction.chosenOption), "prediction must match a confirmed option");
    assert(typeof prediction.prediction.explanation === "string", "prediction should include explanation");

    const feedback = await request("POST", "/api/feedback", {
      request: decisionRequest,
      prediction: prediction.prediction,
      actualChoice: prediction.prediction.chosenOption,
      reasonTags: ["focus", "energy"],
      reasonText: "Smoke test feedback for the real Codex path."
    });
    assert(feedback.saved === true && feedback.cardStatus === "queued", "feedback should be queued quickly");
  }

  console.log(`smoke-e2e passed in ${Date.now() - startedAt}ms`);
}

async function request(method, path, body, parseSuccessOnly = true) {
  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok && parseSuccessOnly) {
    throw new Error(`${method} ${path} failed: ${response.status} ${JSON.stringify(payload)}`);
  }
  return parseSuccessOnly ? payload : { status: response.status, payload };
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
