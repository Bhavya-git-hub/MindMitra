/**
 * Content-Security-Policy builder. A fresh nonce per request allows Next.js's own scripts and
 * nothing else (`strict-dynamic`); styles allow inline because component libraries set style
 * attributes, which nonces cannot cover. The API origin is the only external connect target,
 * over HTTP(S) and over WebSocket for real-time updates.
 */

export interface CspOptions {
  nonce: string;
  apiOrigin: string;
  isDev: boolean;
}

/** The WebSocket origin that matches an http(s) origin: https → wss, http → ws. */
export function socketOrigin(httpOrigin: string): string {
  return httpOrigin.replace(/^http/, "ws");
}

export function buildCsp({ nonce, apiOrigin, isDev }: CspOptions): string {
  const directives = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src 'self' ${apiOrigin} ${socketOrigin(apiOrigin)}${isDev ? " ws: wss:" : ""}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ];
  if (!isDev) directives.push("upgrade-insecure-requests");
  return directives.join("; ");
}

export function generateNonce(): string {
  return btoa(crypto.randomUUID());
}
