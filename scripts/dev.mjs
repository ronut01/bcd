import { spawn } from "node:child_process";
import path from "node:path";
import process from "node:process";

const root = process.cwd();
const binSuffix = process.platform === "win32" ? ".cmd" : "";
const bin = (name) => path.join(root, "node_modules", ".bin", `${name}${binSuffix}`);

const children = [
  spawn(bin("tsx"), ["watch", "src/server/index.ts"], {
    cwd: root,
    stdio: "inherit",
    env: { ...process.env, BCD_PORT: process.env.BCD_PORT ?? "3737" }
  }),
  spawn(bin("vite"), ["--host", "127.0.0.1"], {
    cwd: root,
    stdio: "inherit",
    env: process.env
  })
];

console.log("bcd dev server");
console.log("API: http://127.0.0.1:3737");
console.log("GUI: http://127.0.0.1:5173");

const shutdown = (signal) => {
  for (const child of children) {
    child.kill(signal);
  }
};

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));

for (const child of children) {
  child.on("exit", (code, signal) => {
    if (signal) {
      return;
    }
    if (code && code !== 0) {
      shutdown("SIGTERM");
      process.exit(code);
    }
  });
}
