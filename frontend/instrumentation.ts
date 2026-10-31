/**
 * Next.js runs this once when the dev server starts.
 *
 * It brings up the FastAPI backend so `npm run dev` in frontend/ is the only
 * command needed. Production (`next build` / `next start`) never runs this.
 */
type DevBackendModule = {
  startBackend: (opts?: { quiet?: boolean }) => Promise<{
    reused: boolean;
    stop: () => void;
  }>;
  stopBackend: () => void;
};

const globalState = globalThis as typeof globalThis & {
  __bmkgDevBackendStarted?: boolean;
};

export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  if (process.env.NODE_ENV !== "development") return;
  if (process.env.DEV_BACKEND === "0") return;
  if (globalState.__bmkgDevBackendStarted) return;
  globalState.__bmkgDevBackendStarted = true;

  // @ts-ignore - plain Node ESM helper, not part of the TypeScript app graph
  const backend = (await import("./scripts/dev-backend.mjs")) as DevBackendModule;

  // Register cleanup before the (possibly slow) startup so an interrupted
  // boot still tears down the API process.
  const shutdown = () => backend.stopBackend();
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  process.on("exit", shutdown);

  try {
    await backend.startBackend();
  } catch (err) {
    console.error(`[dev] backend failed to start: ${(err as Error).message}`);
    console.error("[dev] UI will still run; start the API with `npm run dev:backend`.");
    return;
  }
}
