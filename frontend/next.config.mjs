/** @type {import('next').NextConfig} */

// `instrumentation.ts` starts the FastAPI backend alongside `next dev`, and the
// dev server is the only thing that needs to forward to it: in a deployment,
// Vercel's top-level rewrites route /api/v1/* straight to the api service.
const backendUrl = (
  process.env.BACKEND_INTERNAL_URL ||
  `http://127.0.0.1:${process.env.BACKEND_PORT || "8000"}`
).replace(/\/$/, "");

const nextConfig = {
  // "standalone" output is only needed for the Docker image. It writes
  // symlinked node_modules under .next/standalone, which `next dev` cannot
  // clean up on Windows (EINVAL on readlink), so only enable it for Docker
  // builds: `STANDALONE_OUTPUT=1 npm run build`.
  output: process.env.STANDALONE_OUTPUT ? "standalone" : undefined,

  experimental: {
    instrumentationHook: true,
  },

  async rewrites() {
    // Never baked into a production build: a function that proxies to
    // 127.0.0.1:8000 would point at itself.
    if (process.env.NODE_ENV === "production") return [];
    return [{ source: "/api/v1/:path*", destination: `${backendUrl}/api/v1/:path*` }];
  },
};

export default nextConfig;
