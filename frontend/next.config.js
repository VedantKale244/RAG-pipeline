/** @type {import('next').NextConfig} */
const backendUrl = (process.env.BACKEND_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

const nextConfig = {
  reactStrictMode: true,
  // Keep API and SSE calls same-origin in the browser. Set BACKEND_URL on the
  // frontend server for container or production deployments; it is never sent
  // to the browser.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
