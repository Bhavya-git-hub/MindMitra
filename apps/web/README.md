# apps/web: Frontend

Next.js 16 (App Router) · React 19 · TypeScript (strict) · Tailwind CSS 4 · shadcn/ui (Radix) ·
react-hook-form + zod · Recharts · Vitest + Testing Library + axe · Playwright.

**Current state:** the frontend foundation. Design system, application shell, authentication
(connected to the real API), the four role portals with protected routes and role-based
redirects, and the shared building blocks. The student and therapist portals are built; the
teacher and administrator portals are still placeholders (overview and account).

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
                   the student portal has 20 screens and the therapist portal 12 (see below)
    api/session    sets/clears the signed portal-pass cookie (the only route handler)
    design-system  living style guide
  proxy.ts         role redirects from the portal pass + per-request CSP nonce
  components/      ui/ (shadcn), layout/, states/, cards/, charts/, forms/, safety/, auth/, providers/,
                   student/ (one file of views per area)
  lib/             api/ (typed client, student-api.ts + zod schemas), hooks/ (useQuery), auth/ (roles,
                   route rules, pass, session manager), format, sleep, trend-data, env, csp ...
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

## Student portal

| Area                  | Pages (under `/student`)                                                          | Data                                                                                                                               |
| --------------------- | --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Dashboard             | `/`                                                                               | `GET /me/dashboard`: today's mood, stress and sleep, wellbeing check, next appointment, 7-day trends, suggestions, check-in status |
| Check-in and tracking | `/check-in`, `/mood`, `/stress`, `/sleep`                                         | `POST /me/check-ins`, stress and sleep entries                                                                                     |
| Wellness              | `/wellness`, `/trends`, `/assessment`, `/goals`, `/recommendations`               | summary, trends (7/30/90 days), WHO-5 check, goals, rule-based suggestions                                                         |
| Companion             | `/assistant`                                                                      | Entry point only. The companion is not built; the page says so and links to what works                                             |
| Care                  | `/therapists`, `/therapists/[id]`, `/appointments`, `/messages`, `/messages/[id]` | directory, slots, booking, cancellation, one-to-one messages                                                                       |
| Library               | `/resources`, `/resources/[id]`                                                   | published resources                                                                                                                |
| Privacy and safety    | `/privacy`, `/privacy/consent`, `/emergency`                                      | access history, export, consent switches, crisis contacts, "ask someone to reach out"                                              |

Rules the views follow: no student ids in URLs or API paths (only `/me/...`; route ids are
checked as UUIDs before they reach a path); every number comes from the API (the only fixed
text is wording and the 1-5 labels); empty and error states say what happened and what to do
next; scores are never shown without their label; the support prompt is information, not
detection; links and phone numbers from the API are only rendered when they are `http(s)` or
dialable. Data loading uses the small `useQuery` hook in `src/lib/hooks`.

## Therapist portal

| Area                      | Pages (under `/therapist`)       | Data                                                                                                                         |
| ------------------------- | -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Dashboard                 | `/`                              | `GET /therapist/dashboard`: status, caseload, today, waiting requests, alerts, follow-ups, unread messages                   |
| Profile and status        | `/profile`                       | profile, licence details and verification status; submit for verification                                                    |
| Schedule                  | `/availability`, `/appointments` | bookable times; confirm, decline, cancel, mark no-show, start a session                                                      |
| Students                  | `/students`, `/students/[id]`    | caseload and the authorized profile: trends and wellbeing checks (only what the student shares), recommendations, follow-ups |
| Sessions and notes        | `/sessions`, `/sessions/[id]`    | start and close sessions; private, versioned notes only the author can read                                                  |
| Safety and follow-through | `/alerts`, `/follow-ups`         | acknowledge, start, resolve alerts with a fixed outcome; private reminders                                                   |
| Messages                  | `/messages`, `/messages/[id]`    | the same conversations API as students, under the therapist routes                                                           |

Every page that touches students is wrapped in `RequireVerified`, which shows why it is closed
instead of the data. That is a courtesy: the API answers `403` or `404` for the same requests
whatever the interface shows. Note text is only ever held in component state and sent in the
body of one `PUT`; it is never put in a URL, `localStorage` or a log.

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
- `/help` (public, works signed out) lists no phone numbers on purpose. Signed-in students see
  their institution's contacts at `/student/emergency`; the seeded contacts are demo data and
  must be replaced and verified before go-live.
- The AI companion has no conversation screen yet (Phase 6).
- Teacher and administrator portals are still the placeholder overview. There is no screen for
  administrators to verify therapists yet; the API exists (`/admin/therapists`).
- No i18n, TanStack Query or generated OpenAPI client yet (see `docs/ARCHITECTURE.md` section 2).
