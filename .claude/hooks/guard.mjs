// PreToolUse: block hand edits to generated or secret files.
let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  const file = (JSON.parse(raw).tool_input?.file_path ?? "").replace(/\\/g, "/");
  const blocked = [/docs\/api\/openapi\.json$/, /(^|\/)\.env(\.[^/]+)?$/, /\.(pem|p8|key)$/];
  if (blocked.some((r) => r.test(file)) && !file.endsWith(".env.example")) {
    console.error(`Blocked: ${file} is generated or secret. Run "poetry run poe openapi", or edit .env yourself.`);
    process.exit(2);
  }
});
