# apps/web: Frontend

Next.js 16 (App Router) · React 19 · TypeScript (strict) · Tailwind CSS 4 · shadcn/ui (Radix) ·
react-hook-form + zod · Recharts · Vitest + Testing Library + axe · Playwright.

**Current state:** the frontend foundation. Design system, application shell, authentication
(connected to the real API), the four role portals with protected routes and role-based
redirects, and the shared building blocks. The portal pages are placeholders (overview and
account); the real dashboards come in later phases.

## Quick start

```bash
cp .env.example .env.local          # then set SESSION_SECRET (32+ random chars)
npm install
npm run dev                         # http://localhost:3000, needs the API on NEXT_PUBLIC_API_BASE_URL
```

| Variable                   | Where   | Purpose                                                                          |
| -------------------------- | ------- | -------------------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_BASE_URL` | browser | Base URL of the API, e.g. `http://localhost:8000`. Also allowed in the CSP.      |
| `API_INTERNAL_URL`         | server  | Optional: how the web server reaches the API (defaults to the public URL).       |
| `SESSION_SECRET`           | server  | Signs the portal-pass cookie. At least 32 characters. Never sent to the browser. |
| `ENABLE_DESIGN_SYSTEM`     | server  | `true` to serve `/design-system` in production (always on in development).       |

Values are validated lazily in `src/lib/env.ts`; nothing is hard-coded.

## Commands

```bash
npm run lint          # ESLint (flat config, next + typescript rules, no-explicit-any)
npm run typecheck     # tsc --noEmit
npm run format:check  # Prettier
npm test              # Vitest: unit + component + accessibility (axe) + colour-contrast tests
npm run check         # all of the above
npm run build         # production build
```

### End-to-end tests (real API, real database)

```bash
# An EMPTY throwaway PostgreSQL database with the btree_gist extension:
E2E_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/mm_e2e ../../scripts/e2e/run.sh
```

`scripts/e2e/run.sh` migrates and seeds the database (synthetic data), starts the API, builds
and starts this app, and runs Playwright with fresh random secrets that never touch disk. It
covers sign-in for all four roles, sign-out (including cross-tab and refresh-token replay),
protected routes, the full role-redirect matrix, `next=` safety, cookie and storage hygiene,
mobile navigation, reflow at 320px, and axe scans in light and dark mode. Set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to use a pre-installed Chromium.

## Structure

```
src/
  app/
    (auth)/        login, register, verify-email, forgot-password, reset-password
    (public)/help  crisis and help page (server-rendered, no login needed)
    (student)/student     (therapist)/therapist     (teacher)/teacher     (admin)/admin
                   each: layout (AuthGate + AppShell), page, account/, loading.tsx, error.tsx
    api/session    sets/clears the signed portal-pass cookie (the only route handler)
    design-system  living style guide
  proxy.ts         role redirects from the portal pass + per-request CSP nonce
  components/      ui/ (shadcn), layout/, states/, cards/, charts/, forms/, safety/, auth/, providers/
  lib/             api/ (typed client), auth/ (roles, route rules, pass, session manager), env, csp ...
tests/unit/        Vitest        e2e/   Playwright
```

## How authentication works

See [ADR 0004](../../docs/adr/0004-frontend-session-handling-and-route-protection.md) and
[ADR 0003](../../docs/adr/0003-access-token-transport-and-session-checks.md).

1. `POST /auth/login` returns a short-lived access token (kept **in memory only**) and a CSRF
   token; the refresh token arrives as an HttpOnly cookie the page can never read.
2. Only the CSRF token is stored (`localStorage["mm.csrf"]`). On reload the app calls
   `/auth/refresh` with it, which rotates the refresh token and returns a new access token.
3. Requests that get a 401 refresh once and retry. Refreshes are serialised across calls and tabs.
4. `/api/session` asks the API who the token belongs to and sets a signed HttpOnly cookie with
   that role. `src/proxy.ts` uses it to redirect before rendering; `AuthGate` then checks the
   real session. **The API is the only enforcement point**; both frontend layers are UX.

Signed out visitors to a portal go to `/login?next=…`; each role is sent home from other
portals; `next` is only honoured inside the person's own portal.

## Design system

Open `/design-system` in development. Tokens live in `src/app/globals.css` (light and dark);
never hard-code colours in components. Every text and boundary pair is verified against WCAG
2.1 AA by `tests/unit/design-tokens.test.ts`, so change a token and its test together.

Conventions: calm and warm, no alarm reds for anything ML-related, plain language, status never
conveyed by colour alone, visible solid focus ring, reduced-motion respected, one `<h1>` per
page, a skip link on every page.

## Adding a page to a portal

1. Add the page under `src/app/(role)/role/…`; it inherits the guard and shell from the layout.
2. Add it to `src/lib/navigation.ts` (remove `soon: true`). `tests/unit/navigation.test.ts`
   fails if a menu item links to a page that does not exist.
3. Fetch data through the session's API client (`useAuth().manager.api`), validate with a zod
   schema, and use `loading.tsx` / `error.tsx` for states.
4. Never put sensitive data in URLs, `localStorage` or logs.

## Known gaps

- Terms of use and privacy notice pages do not exist yet; the sign-up checkbox names them in
  plain text without links.
- `/help` lists no phone numbers on purpose: an institution's own crisis contacts will be
  configured per institution and rendered there.
- No i18n, TanStack Query or generated OpenAPI client yet (see `docs/ARCHITECTURE.md` section 2).
