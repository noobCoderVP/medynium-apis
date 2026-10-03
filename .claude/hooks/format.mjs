// PostToolUse: format edited Python files with ruff.
import { execFileSync } from "node:child_process";

let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  const file = JSON.parse(raw).tool_input?.file_path ?? "";
  if (!file.endsWith(".py")) return;
  try {
    execFileSync(".venv/Scripts/ruff.exe", ["format", file], { stdio: "ignore" });
  } catch {
    // Formatting is best effort; `poe check` is the gate.
  }
});
