import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Content-Security-Policy is set per request (with a nonce) in src/proxy.ts. The static
  // headers below do not depend on the request.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
          },
          // Authenticated pages and the session endpoint must never be cached.
          { key: "Cache-Control", value: "private, no-store" },
        ],
      },
    ];
  },
};

export default config;
