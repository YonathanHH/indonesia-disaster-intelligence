/** @type {import('next').NextConfig} */
const nextConfig = {
  // "standalone" output is only needed for the Docker image. It writes
  // symlinked node_modules under .next/standalone, which `next dev` cannot
  // clean up on Windows (EINVAL on readlink), so only enable it for Docker
  // builds: `STANDALONE_OUTPUT=1 npm run build`.
  output: process.env.STANDALONE_OUTPUT ? "standalone" : undefined,
  env: { NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000" }
};
export default nextConfig;
