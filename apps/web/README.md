# apps/web — Frontend

Next.js (App Router) + TypeScript (strict) + Tailwind CSS + shadcn/ui.

Planned structure (Phase 1+):

```
src/
  app/
    (public)/      landing, login, crisis resources
    (student)/     dashboard, check-ins, journal, AI companion, appointments
    (therapist)/   caseload, sessions, notes, escalations
    (faculty)/     aggregate wellness insights, referral form
    (admin)/       users, roles, institution settings, audit logs
  components/      shared UI (shadcn/ui primitives in components/ui)
  lib/             typed API client, auth helpers, utils
tests/             unit (Vitest + Testing Library) and e2e (Playwright)
```

Not scaffolded yet: dependencies are installed when Phase 1 starts.
