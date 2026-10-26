/** @type {import('next').NextConfig} */
const apiUrl = process.env.API_INTERNAL_URL || "http://localhost:8010";

const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  // A API é servida pela mesma origem (proxy), o que permite cookies SameSite=Strict.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiUrl}/api/:path*` },
      { source: "/health/:path*", destination: `${apiUrl}/health/:path*` },
    ];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
