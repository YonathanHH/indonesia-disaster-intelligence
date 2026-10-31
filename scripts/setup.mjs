#!/usr/bin/env node
// One-shot local setup: create backend/.venv (Python 3.12+) with the API
// requirements, then install the frontend dependencies with npm.
import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";

const root = process.cwd();
const backendDir = path.join(root, "backend");
const isWindows = process.platform === "win32";

function resolveCommand(cmd) {
  if (path.isAbsolute(cmd)) return existsSync(cmd) ? cmd : null;

  if (isWindows) {
    const result = spawnSync("where", [cmd], { encoding: "utf8" });
    if (result.status !== 0) return null;
    const lines = (result.stdout || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    // Skip Microsoft Store aliases: they are stubs, not real interpreters.
    return (
      lines.find(
        (candidate) =>
          !candidate.toLowerCase().includes("\\windowsapps\\") &&
          existsSync(candidate)
      ) || null
    );
  }

  const result = spawnSync("sh", ["-c", `command -v ${cmd}`], {
    encoding: "utf8",
  });
  if (result.status !== 0) return null;
  const candidate = (result.stdout || "").trim().split(/\r?\n/)[0];
  return candidate && existsSync(candidate) ? candidate : null;
}

function isPython312Plus(exe) {
  return (
    spawnSync(
      exe,
      [
        "-c",
        "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)",
      ],
      { stdio: "ignore" }
    ).status === 0
  );
}

function findBasePython() {
  const candidates = isWindows ? ["python", "python3"] : ["python3", "python"];
  for (const cmd of candidates) {
    const exe = resolveCommand(cmd);
    if (exe && isPython312Plus(exe)) return exe;
  }
  return null;
}

function run(command, args, opts = {}) {
  console.log(`> ${command} ${args.join(" ")}`);
  const result = spawnSync(command, args, { stdio: "inherit", ...opts });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

const venvPython = isWindows
  ? path.join(backendDir, ".venv", "Scripts", "python.exe")
  : path.join(backendDir, ".venv", "bin", "python");

if (!existsSync(venvPython)) {
  const base = findBasePython();
  if (!base) {
    console.error(
      "Python 3.12+ not found. Install it (or put a real python on PATH), then rerun `npm run setup`."
    );
    process.exit(1);
  }
  console.log(`Creating backend/.venv with ${base}`);
  run(base, ["-m", "venv", path.join(backendDir, ".venv")]);
}

run(venvPython, [
  "-m",
  "pip",
  "install",
  "--disable-pip-version-check",
  "-r",
  path.join(backendDir, "requirements.txt"),
]);

const npmCli = process.env.npm_execpath;
if (npmCli) {
  run(process.execPath, [npmCli, "--prefix", "frontend", "install"]);
} else {
  run("npm", ["--prefix", "frontend", "install"], { shell: isWindows });
}

console.log("\nSetup complete. Run `npm run dev`.");
