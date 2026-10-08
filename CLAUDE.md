# CLAUDE.md — MindMitra Permanent Project Rules

This file holds the rules every contributor (human or AI) must follow when working on
MindMitra. Read it before every task. When this file conflicts with a one-off instruction,
stop and ask the project owner before proceeding.

## 1. What MindMitra is

MindMitra is an AI-assisted, privacy-preserving **student wellness and therapist support
platform** for colleges. It has four roles: **Student, Therapist, Teacher/Faculty,
Administrator**.

MindMitra is an **assistive wellness system**. It is **not** a diagnostic tool, **not** a
medical device, and **not** a replacement for licensed mental-health professionals.

## 2. Engineering rules (non-negotiable)

1. **Never rewrite the architecture without explaining why.** Any change to the structure
   described in `ARCHITECTURE.md` needs a written rationale (an ADR in `docs/adr/`) before
   code changes land.
2. **Never create duplicate functionality.** Search the codebase before adding a module,
   util, component, endpoint or model. Extend what exists.
3. **Never expose private therapy data to teachers.** Teachers see only aggregate,
   de-identified or explicitly student-consented, non-clinical information.
4. **Never expose private student data to unauthorized users.** Enforce role- and
   relationship-based access on every read and write.
5. **Never claim that AI diagnoses mental-health conditions.**
6. **AI is an assistive wellness system, not a therapist replacement.**
7. **Use synthetic data for development.** Real student data never enters dev, test, CI,
   notebooks, fixtures, seed scripts or logs.
8. **Use environment variables for secrets.** Load them via typed settings
   (`pydantic-settings` on the backend, validated env on the frontend).
9. **Never hardcode API keys**, passwords, tokens, connection strings or private URLs.
   Only `.env.example` files with placeholder values are committed.
10. **Every backend endpoint must have authorization.** No endpoint ships without an explicit
    auth dependency and permission check. Public endpoints (health, login) must be
    explicitly marked as public and reviewed.
11. **Every important feature must have tests.** Authorization rules, data-visibility rules,
    crisis escalation and ML safety wrappers are always "important".
12. **Use TypeScript strictly on the frontend.** `strict: true`, no `any` without a
    justified `// eslint-disable` comment.
13. **Use Python type hints on the backend and ML code.** Code must pass `mypy --strict`
    (or the configured mypy profile).
14. **Follow clean architecture principles.** Dependencies point inward:
    `api → application (services/use cases) → domain`; infrastructure implements domain
    interfaces. Domain code never imports frameworks.
15. **Keep frontend, backend, ML and infrastructure modular.** Each lives in its own top-level
    directory with its own dependencies, tests and Dockerfile. Cross-module contracts go
    through documented APIs/schemas in `packages/` or OpenAPI.
16. **Do not implement everything at once.**
17. **Work phase-by-phase** following `DEVELOPMENT_ROADMAP.md`. Do not start a phase until the
    previous phase's exit criteria are met or the owner says otherwise.
18. **Before modifying existing code, inspect the relevant files** (and their tests).
19. **Do not delete working functionality unless explicitly instructed.**
20. **After each major implementation, run tests and fix errors** before reporting done.

## 3. Mental-health safety rules

- **Do not diagnose users.** No output, label, UI copy, API field or log may state or imply
  a diagnosis (e.g. "you have depression"). Use wellness language: "signals", "patterns",
  "check-in score", "may benefit from talking to someone".
- **Do not prescribe medication** or give dosage, medication or treatment advice.
- **Do not replace therapists.** AI features route students toward human support; they never
  position themselves as therapy.
- **Do not present ML predictions as medical diagnoses.** Every ML output shown to a human
  carries: what it is (a statistical estimate), its limitations, and a pointer to human help.
- **Crisis indicators must trigger a human-support escalation workflow.** Detection of
  self-harm, suicide or imminent-danger language must:
  1. immediately show the student crisis resources (helplines, campus emergency contacts),
  2. create an escalation record and notify the on-call therapist / counselling team,
  3. never be silently suppressed by a model confidence threshold, feature flag or error,
  4. fail **safe**: if the classifier is unavailable, fall back to keyword rules and still
     surface resources.
- **Clearly communicate limitations of AI** in the UI wherever AI output appears.
- **Protect confidential therapy information.** Session notes are visible only to the
  authoring therapist (and supervising clinicians where policy allows). Admins manage
  accounts, not clinical content.

## 4. Data & privacy rules

- Data classification (see `ARCHITECTURE.md §6`): **Public, Internal, Personal, Sensitive,
  Clinical-Confidential**. Clinical-Confidential data is encrypted at the field level.
- Principle of least privilege and data minimisation everywhere.
- Never log message bodies, journal text, therapy notes, or PII. Log IDs and event types.
- Every access to Sensitive or Clinical-Confidential data writes an audit log entry.
- Student consent is explicit, granular, revocable and recorded.
- ML training uses synthetic or properly consented, de-identified data only.

## 5. Coding conventions

### Frontend (`apps/web`)
- Next.js App Router, TypeScript strict, Tailwind CSS, shadcn/ui.
- Server Components by default; Client Components only when interactivity requires.
- API calls go through a single typed API client (generated from OpenAPI where possible).
- Route groups per role: `(student)`, `(therapist)`, `(faculty)`, `(admin)`.
- Accessible by default (WCAG 2.1 AA), calm and non-alarming visual language.

### Backend (`services/api`)
- FastAPI + Pydantic v2 + SQLAlchemy 2.x (async) + Alembic + PostgreSQL + Redis.
- Layout: `api/` (routers), `application/` (services/use cases), `domain/` (entities,
  policies, interfaces), `infrastructure/` (db, cache, external clients), `core/`
  (config, security, logging).
- Authorization through a central policy layer (`domain/policies`), not ad-hoc checks.
- Tests with pytest; authorization tests for every endpoint.

### ML (`services/ml`)
- Python, scikit-learn, PyTorch, Hugging Face Transformers.
- Served behind its own internal API; the backend is its only caller.
- Every model has a model card in `services/ml/model_cards/`.
- All predictions pass through the safety layer (`safety/`) before leaving the service.

### Infrastructure (`infra/`)
- Docker for every service; `docker-compose` for local dev.
- AWS via Terraform (`infra/terraform`). No credentials in the repo.

## 6. Workflow rules

- Small, reviewable changes. One concern per PR.
- Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`).
- Update `ARCHITECTURE.md` / `DEVELOPMENT_ROADMAP.md` when a change affects them.
- Record significant decisions as ADRs in `docs/adr/`.
- Do not add dependencies without need; justify new ones in the PR description.
- Run lint, type-check and tests locally before declaring work complete.

## 7. Definition of done

A task is done when: code follows these rules, types check, lint passes, tests (including
authorization and safety tests where relevant) pass, docs are updated, and no secrets or
real personal data were introduced.
