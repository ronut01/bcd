import { spawnSync } from "node:child_process";
import path from "node:path";

const vitestBin = path.join("node_modules", ".bin", process.platform === "win32" ? "vitest.cmd" : "vitest");
const targets = [
  "src/server/index.test.ts",
  "src/server/prompts.test.ts",
  "src/server/storage.test.ts",
  "src/server/codex.test.ts",
  "src/server/validators.test.ts"
];

const result = spawnSync(vitestBin, ["run", ...targets], {
  stdio: "inherit",
  env: {
    ...process.env,
    BCD_SYNTHETIC_PROFILE_IMPORT_EVAL: "1"
  }
});

if (result.error) {
  console.error(result.error.message);
  process.exitCode = 1;
} else if (result.status !== 0) {
  process.exitCode = result.status ?? 1;
} else {
  console.log("profile-import-synthetic-eval passed");
}
