# ADR 0003: Bearer access tokens, cookie-only refresh, and a database session check per request

- Status: Accepted
- Date: 2026-10-09

## Context
SECURITY_ARCHITECTURE.md §3.2 designed the access JWT as an httpOnly cookie protected by a
double-submit CSRF cookie, and a Redis denylist keyed by session id to make logout and
deactivation take effect before the token expires. Redis is not wired into the platform yet, and
cookie-borne access tokens make every unsafe API call depend on CSRF handling being correct.

## Decision
1. The **access token** (EdDSA JWT, 10 minutes) is returned in the login/refresh response body.
   The browser keeps it in memory only and sends it as `Authorization: Bearer`. It is never put
   in a cookie or in web storage, so ordinary API calls cannot be forged cross-site.
2. The **refresh token** (opaque, 256-bit, stored as SHA-256) lives only in an
   `HttpOnly; Secure; SameSite=Strict` cookie named `__Secure-mm_refresh`, scoped to
   `Path=/api/v1/auth`. (`__Host-` would force `Path=/` and send the token on every request.)
   It is single use and rotates on every refresh; replaying a rotated token revokes the session.
3. `/auth/refresh` is the only cookie-authenticated call, so it alone needs CSRF protection: it
   requires `X-CSRF-Token`, whose hash is bound server-side to that refresh token. A random CSRF
   token is returned with each token pair. The CSRF check runs before reuse detection, so a
   cross-site request cannot trigger a revocation.
4. Instead of a Redis denylist, every authenticated request re-checks the session row in
   PostgreSQL: not revoked, within its absolute lifetime, the user still `active` and not
   deleted, and the user's role equal to the token's role. This is one indexed primary-key join.

## Consequences
Logout, password change, suspension and role change take effect on the very next request, not
after up to 10 minutes. An XSS bug could read the in-memory access token (but never the refresh
token); the strict CSP and short lifetime limit that. The per-request database check costs one
query; a cache can replace it later without changing the API. A page reload needs a refresh call
to obtain a new access token, which the frontend's session bootstrap will do.
