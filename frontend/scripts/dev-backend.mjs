#!/usr/bin/env node
// Starts the FastAPI backend for Next.js dev.
//
// Imported by `frontend/instrumentation.ts` (so `next dev` brings the API up
// automatically) and runnable on its own:
//
//   node frontend/scripts/dev-backend.mjs
//
// Picks backend/.venv python when present, otherwise falls back to system python.
//
// Node builtins are imported lazily with `webpackIgnore` so Next's instrumentation
// bundle does not try to resolve `node:*` for the edge runtime.

let deps = null;

async function init() {
  if (deps) return deps;

  const [{ existsSync }, childProcess, path] = await Promise.all([
    import(/* webpackIgnore: true */ "node:fs"),
    import(/* webpackIgnore: true */ "node:child_process"),
    import(/* webpackIgnore: true */ "node:path"),
  ]);

  const repoRoot = findRepoRoot(existsSync, path, process.cwd());
  deps = {
    existsSync,
    spawn: childProcess.spawn,
    spawnSync: childProcess.spawnSync,
    path,
    repoRoot,
    backendDir: path.join(repoRoot, "backend"),
  };
  return deps;
}

function findRepoRoot(existsSync, path, start) {
  let dir = start;
  for (;;) {
    if (existsSync(path.join(dir, "backend", "app", "main.py"))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) return start;
    dir = parent;
  }
}

export const backendPort = process.env.BACKEND_PORT || "8000";
export const backendUrl =
  process.env.BACKEND_INTERNAL_URL || `http://127.0.0.1:${backendPort}`;

let child = null;
let shuttingDown = false;
let startPromise = null;
let spawnError = null;

function resolveCommand(cmd) {
  const { existsSync, spawnSync, path } = deps;
  if (path.isAbsolute(cmd)) return existsSync(cmd) ? cmd : null;

  if (process.platform === "win32") {
    const result = spawnSync("where", [cmd], { encoding: "utf8" });
    if (result.status !== 0) return null;
    const lines = (result.stdout || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    // Skip Microsoft Store aliases: they are stubs without project deps.
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

function canRunBackend(exe) {
  const { spawnSync, backendDir } = deps;
  return (
    spawnSync(exe, ["-c", "from app.main import app"], {
      cwd: backendDir,
      stdio: "ignore",
      env: { ...process.env, PYTHONPATH: backendDir },
    }).status === 0
  );
}

function findPython() {
  const { path, backendDir } = deps;
  const candidates =
    process.platform === "win32"
      ? [
          path.join(backendDir, ".venv", "Scripts", "python.exe"),
          "python",
          "python3",
        ]
      : [
          path.join(backendDir, ".venv", "bin", "python"),
          "python3",
          "python",
        ];

  const seen = new Set();
  for (const candidate of candidates) {
    const exe = resolveCommand(candidate);
    if (!exe || seen.has(exe)) continue;
    seen.add(exe);
    if (canRunBackend(exe)) return exe;
  }
  return null;
}

export async function isBackendUp(timeoutMs = 800) {
  try {
    const res = await fetch(`${backendUrl}/api/v1/status`, {
      signal: AbortSignal.timeout(timeoutMs),
    });
    return res.ok;
  } catch {
    return false;
  }
}

function stopChild() {
  if (!child) return;
  const pid = child.pid;
  child = null;
  if (shuttingDown) return;
  shuttingDown = true;
  console.log("[dev] stopping backend");

  if (process.platform === "win32") {
    // uvicorn --reload forks a worker; /T kills the whole tree.
    deps.spawnSync("taskkill", ["/pid", String(pid), "/T", "/F"], { stdio: "ignore" });
  } else {
    // Keep the backend in the same process group as Next so a terminal
    // Ctrl+C reaches it directly; this covers Next exiting without cleanup.
    try {
      process.kill(pid, "SIGTERM");
    } catch {
      // already gone
    }
  }
}

async function waitForBackend() {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    if (spawnError) throw spawnError;
    if (child === null) throw new Error("backend exited before becoming ready");
    if (await isBackendUp(1000)) return;
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  throw new Error("backend did not become ready within 120s");
}

async function startBackendOnce({ quiet = false } = {}) {
  await init();
  const { existsSync, spawn, path, backendDir } = deps;

  if (await isBackendUp()) {
    if (!quiet) console.log(`[dev] reusing backend at ${backendUrl}`);
    return { reused: true, stop: () => {} };
  }

  const python = findPython();
  if (!python) {
    throw new Error(
      "No Python with backend dependencies found. Create backend/.venv and run: " +
        "pip install -r backend/requirements.txt"
    );
  }

  if (!existsSync(path.join(backendDir, ".env"))) {
    console.warn(
      "[dev] backend/.env missing — copy backend/.env.example to backend/.env first."
    );
  }

  if (!quiet) {
    console.log(`[dev] starting backend on ${backendUrl} (${python})`);
  }

  spawnError = null;
  shuttingDown = false;
  child = spawn(
    python,
    ["-m", "uvicorn", "app.main:app", "--reload", "--port", backendPort],
    {
      cwd: backendDir,
      stdio: "inherit",
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      detached: false,
    }
  );

  child.on("error", (err) => {
    spawnError = err;
    console.error(`[dev] backend failed to spawn: ${err.message}`);
  });
  child.on("exit", (code, signal) => {
    if (!shuttingDown && code !== 0 && code !== null) {
      console.error(
        `[dev] backend exited (code ${code}${signal ? `, signal ${signal}` : ""})`
      );
    }
    child = null;
  });

  try {
    await waitForBackend();
  } catch (err) {
    stopChild();
    throw err;
  }
  if (!quiet) console.log(`[dev] backend ready at ${backendUrl}`);
  return { reused: false, stop: stopChild };
}

export function startBackend(opts = {}) {
  if (!startPromise) {
    startPromise = startBackendOnce(opts).catch((err) => {
      startPromise = null;
      throw err;
    });
  }
  return startPromise;
}

export function stopBackend() {
  stopChild();
}

// Direct execution keeps the process alive until Ctrl+C.
const isDirect = Boolean(process.argv[1]?.endsWith("dev-backend.mjs"));

if (isDirect) {
  startBackend()
    .then(() => {
      const shutdown = () => {
        stopBackend();
        process.exit(0);
      };
      process.on("SIGINT", shutdown);
      process.on("SIGTERM", shutdown);
      process.on("exit", stopBackend);
    })
    .catch((err) => {
      console.error(`[dev] ${err.message}`);
      process.exit(1);
    });
}
