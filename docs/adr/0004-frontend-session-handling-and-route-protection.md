# ADR 0004: Frontend session handling, layered route protection and CSP

- Status: Accepted
- Date: 2026-10-09

## Context

ADR 0003 fixed the API's token model: a 10-minute access token returned in the response body,
a single-use refresh token in an `HttpOnly; Secure; SameSite=Strict` cookie scoped to
`/api/v1/auth`, and a CSRF token that authorises only `/auth/refresh`. The web app now needs to
use that model for sign-in, sign-out, reloads, role-based portals (`/student`, `/therapist`,
`/teacher`, `/admin`) and a strict Content-Security-Policy, without a flash of the wrong portal
and without adding a second source of truth for who a person is.

## Decision

1. **The browser talks to the API directly** through one typed client (`src/lib/api`). The
   access token lives in memory and is sent as `Authorization: Bearer`. Responses are validated
   with zod, errors are RFC 9457 problems parsed into `ApiError`, and a 401 triggers one refresh
   and one retry. The web server is not a general API proxy; its only route handler is
   `/api/session` (point 4).
2. **The CSRF token is kept in `localStorage` (`mm.csrf`)** so that a page reload can call
   `/auth/refresh` and get a new access token. It is useless without the HttpOnly refresh
   cookie. This is a deliberate tradeoff: script running in our origin could read it, but such
   script could equally call `/auth/refresh` itself (the cookie is same-site), so keeping the
   CSRF token in memory would not stop an XSS session theft. The defences against XSS are the
   nonce-based CSP (point 6), the short access lifetime, refresh-token rotation with reuse
   detection, and no sensitive data in the DOM, URLs or storage. Nothing else is ever stored.
3. **Refreshes are serialised.** Refresh tokens are single use, so concurrent refreshes would
   revoke the session. Calls in one tab share a single in-flight promise, tabs are serialised
   with a Web Lock, and a 401 caused by a token another request already replaced simply retries.
   Signing out in one tab signs out all tabs (BroadcastChannel). Only a 4xx (except 429) from
   `/auth/refresh` ends the session; being offline or a 5xx does not sign anyone out.
4. **A signed "portal pass" cookie drives redirects.** The proxy cannot see the in-memory access
   token, and waiting for client code would flash the wrong page. After sign-in the browser asks
   `/api/session`, which forwards the Bearer token to the API's `/me` and sets an HttpOnly,
   HMAC-signed cookie holding only the role the API reported (`SESSION_SECRET`,
   `__Host-mm_portal` in production). It is an optimistic hint, not authority: it is cleared on
   sign-out, a forged or expired pass is ignored, and a stale but valid pass only lets the page
   shell load (see point 5).
5. **Three layers, one authority.** (a) `src/proxy.ts` redirects using the pass (signed-out
   visitors to `/login?next=…`, each role away from other portals, signed-in people away from
   guest pages). (b) `AuthGate` in every portal layout waits for the real session and redirects
   on mismatch; it also clears a stale pass so `/login` cannot bounce back and forth. (c) The API
   authorizes every request and is the only enforcement point. `next=` is honoured only for
   paths inside the person's own portal (`safeNext`), which rules out open redirects. After an
   explicit sign-out no `next=` is added.
6. **CSP with a per-request nonce** (`script-src 'self' 'nonce-…' 'strict-dynamic'`,
   `connect-src 'self' <api origin>`, `frame-ancestors 'none'`, `object-src 'none'`). A nonce
   requires dynamic rendering, so every page is rendered per request (no static HTML caching;
   static assets are still cached). `style-src` allows `'unsafe-inline'` because component
   libraries set `style` attributes, which nonces cannot cover; scripts are the XSS vector that
   matters here.
7. **Design system.** Tailwind v4 with CSS-variable tokens in `globals.css`, hand-authored
   shadcn/ui components on the unified `radix-ui` package, a self-hosted font (no third-party
   font requests), light and dark themes. Every text and boundary colour pair is checked against
   WCAG 2.1 AA by `tests/unit/design-tokens.test.ts`. Charts expose their data as a hidden table
   and are not keyboard-focusable themselves.
8. **Route groups** are `(student)`, `(therapist)`, `(teacher)`, `(admin)` (not `(faculty)`), to
   match the API role `teacher`. The `administrator` role is served at `/admin`.

## Alternatives considered

- _Auth.js / a BFF that owns the session cookie:_ duplicates the API's session model and
  revocation checks, and adds a second place to get logout wrong.
- _Access token in an HttpOnly cookie:_ rejected in ADR 0003 (CSRF on every call).
- _Decode the JWT in the proxy:_ the token is not available on navigation requests, and the
  proxy would need the API's public key and its own revocation logic.
- _Access or refresh token in `localStorage`:_ rejected; both would be readable by any script.

## Consequences

Reloads cost one refresh round trip before a portal renders (a short "Checking your session"
state). Pages cannot be statically cached. `SESSION_SECRET` is a new required server secret
(at least 32 characters, never exposed to the browser). The CSRF-in-`localStorage` tradeoff is
visible and documented rather than hidden. Because the proxy trusts only a signed hint and the
API trusts only its own tokens, a mistake in either guard cannot grant access to data.
