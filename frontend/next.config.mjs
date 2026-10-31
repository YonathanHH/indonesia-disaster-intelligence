/** @type {import('next').NextConfig} */
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

  // `instrumentation.ts` starts the FastAPI backend alongside `next dev`.
  experimental: {
    instrumentationHook: true,
  },

  // Keep the browser on one origin: /api/v1/* is proxied to FastAPI, so there
  // is no CORS setup and no NEXT_PUBLIC_API_URL to keep in sync.
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendUrl}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
