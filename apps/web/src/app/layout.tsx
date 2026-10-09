import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import * as React from "react";

import { Providers } from "@/components/providers/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "MindMitra", template: "%s · MindMitra" },
  description: "A calm, private place for student wellbeing and the people who support it.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f6f2" },
    { media: "(prefers-color-scheme: dark)", color: "#12181d" },
  ],
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // Reading the per-request nonce set by src/proxy.ts makes every page dynamically rendered,
  // which a nonce-based Content-Security-Policy requires.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers nonce={nonce}>{children}</Providers>
      </body>
    </html>
  );
}
