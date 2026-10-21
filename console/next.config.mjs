/** @type {import('next').NextConfig} */
const api = process.env.CAIRN_API_URL || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  devIndicators: false,
  async rewrites() {
    // One origin for the console: the API, PAP gateway, widget and demo store are proxied.
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
      { source: "/pap/:path*", destination: `${api}/pap/:path*` },
      { source: "/v1/:path*", destination: `${api}/v1/:path*` },
      { source: "/demo/:path*", destination: `${api}/demo/:path*` },
      { source: "/widget.js", destination: `${api}/widget.js` },
      { source: "/healthz", destination: `${api}/healthz` },
    ];
  },
};

export default nextConfig;
