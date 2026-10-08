# MindMitra Architecture

Status: Proposed (Phase 0). Changes require an ADR in `docs/adr/` (see CLAUDE.md rule 1).

## 1. Purpose and principles

MindMitra helps college students look after their wellbeing and connects them to human
support, while giving therapists better tools and institutions privacy-safe insight.

Guiding principles:

1. **Safety first.** Crisis signals always reach a human. AI never diagnoses or prescribes.
2. **Privacy by design.** Least privilege, data minimisation, field-level encryption for
   clinical data, audit everything sensitive.
3. **Human in the loop.** AI assists students and therapists; humans decide.
4. **Modular, clean architecture.** Independent web, API and ML units with explicit contracts.
5. **Incremental delivery.** Built phase by phase (see `DEVELOPMENT_ROADMAP.md`).

## 2. Roles and capabilities

| Role | Can do | Can never see |
|------|--------|---------------|
| **Student** | Mood check-ins, private journal, AI wellness companion, self-help resources, book/attend therapist appointments, manage consent, request help, view own data, export/delete own data | Other students' data |
| **Therapist** | View assigned caseload, appointments, write confidential session notes, see a student's shared check-in trends and AI risk signals (with consent/policy), handle crisis escalations, refer | Students not assigned to them; other therapists' notes (unless supervising policy) |
| **Teacher / Faculty** | Submit a concern referral about a student, see aggregate de-identified wellness trends for their cohorts (k-anonymity threshold), see referral status (acknowledged / in progress, no clinical detail), access wellness resources | Therapy notes, journals, AI conversations, individual check-ins, risk scores, diagnoses, appointment details |
| **Administrator** | Manage users, roles, institution settings, therapist assignments, crisis contacts, view audit logs and system health, institution-wide aggregate analytics | Clinical content (session notes, journals, AI conversations) |

Access is enforced by **RBAC + relationship-based checks + consent**:
role says what kind of action is possible; relationship (e.g. therapist assigned to student)
and consent (student shared check-ins with therapist) decide whether it applies to a given record.

## 3. High-level system view

```
                    ┌───────────────────────────────┐
  Browser  ───────► │  CloudFront + WAF             │
                    └──────────────┬────────────────┘
                                   │
                    ┌──────────────▼────────────────┐
                    │  apps/web  (Next.js)           │  SSR + client UI, role portals
                    └──────────────┬────────────────┘
                                   │ HTTPS (JWT, httpOnly cookies)
                    ┌──────────────▼────────────────┐
                    │  services/api  (FastAPI)       │  auth, RBAC, domain logic,
                    │                                │  audit, escalation workflow
                    └───┬──────────┬──────────┬─────┘
                        │          │          │ internal token, private network
              ┌─────────▼──┐  ┌────▼─────┐  ┌─▼──────────────────────┐
              │ PostgreSQL │  │  Redis   │  │ services/ml (FastAPI)  │
              │  (RDS)     │  │ (cache,  │  │ sentiment, risk signal,│
              │            │  │ sessions,│  │ crisis detection,      │
              │            │  │ rate lim,│  │ companion LLM, safety  │
              │            │  │ queues)  │  │ layer                  │
              └────────────┘  └────┬─────┘  └────────────────────────┘
                                   │
                        ┌──────────▼─────────┐
                        │ Background workers │  notifications, escalation
                        │ (API codebase)     │  timers, ML batch jobs, exports
                        └────────────────────┘
```

- The browser only talks to `web` and `api`. `ml` is never publicly reachable.
- Workers share the API codebase and run as a separate process (Redis-backed queue,
  e.g. ARQ or Celery; decision deferred to Phase 4 via ADR).

## 4. Repository structure

```
mindmitra/
├── CLAUDE.md                  permanent rules
├── ARCHITECTURE.md            this file
├── DEVELOPMENT_ROADMAP.md     phased plan
├── docker-compose.yml         local Postgres + Redis (apps added in Phase 1)
├── .env.example               placeholder env vars
├── apps/
│   └── web/                   Next.js frontend
├── services/
│   ├── api/                   FastAPI backend (clean architecture)
│   └── ml/                    ML inference + training + safety
├── packages/
│   └── contracts/             OpenAPI spec + generated TS types
├── infra/
│   ├── docker/                shared Docker assets
│   └── terraform/             AWS IaC
├── data/synthetic/            synthetic data generators (no real data)
├── scripts/                   dev tooling
├── docs/adr/                  architecture decision records
└── .github/workflows/         CI
```

## 5. Component design

### 5.1 Frontend: `apps/web`

- **Next.js App Router**, TypeScript `strict`, Tailwind CSS, shadcn/ui (Radix primitives).
- **Route groups per role**: `(public)`, `(student)`, `(therapist)`, `(faculty)`, `(admin)`.
  Middleware checks the session role and redirects; the API remains the real enforcement point.
- **Data access**: a single typed API client generated from the backend OpenAPI spec
  (`packages/contracts`). TanStack Query for client-side caching where needed.
- **Forms**: React Hook Form + Zod.
- **Auth**: httpOnly, Secure, SameSite cookies holding short-lived access token + rotating
  refresh token; no tokens in `localStorage`.
- **Safety UX**: a persistent "Get help now" entry point; AI surfaces always display a
  limitations notice; crisis flow is a dedicated, fast, low-JS page.
- **Accessibility**: WCAG 2.1 AA, calm palette, reduced-motion support.
- **Testing**: Vitest + Testing Library (unit), Playwright (e2e incl. role-access checks).

### 5.2 Backend: `services/api`

Clean architecture layers:

```
api/             Routers, Pydantic request/response schemas, dependencies (current_user, require_permission)
application/     Use cases: e.g. SubmitCheckIn, BookAppointment, WriteSessionNote, RaiseEscalation
domain/          Entities, value objects, enums, authorization policies, repository interfaces, domain events
infrastructure/  SQLAlchemy models + repositories, Redis, ML client, email/SMS, KMS encryption, storage
core/            Settings (pydantic-settings), security (JWT, Argon2), logging, audit, errors
```

Rules:

- Every router depends on `get_current_user` and an explicit `require_permission(...)` /
  policy check. Public endpoints use an explicit `public_endpoint` marker and are listed in
  tests.
- Authorization lives in `domain/policies/` (e.g. `can_read_session_note(actor, note)`), so it is
  unit-testable without HTTP.
- Domain events (e.g. `CrisisSignalDetected`) are dispatched to handlers that enqueue
  background jobs.
- Async SQLAlchemy 2.x, Alembic migrations, Pydantic v2.
- Rate limiting and idempotency keys via Redis.
- OpenAPI exported to `packages/contracts` in CI.

### 5.3 ML service: `services/ml`

Internal FastAPI service, authenticated by a service token over the private network.

| Capability | Approach | Output (never a diagnosis) |
|------------|----------|-----------------------------|
| Check-in sentiment / mood trend | scikit-learn baseline (TF-IDF + logistic regression), later fine-tuned Transformer | sentiment score, trend direction |
| Wellbeing risk signal | Gradient-boosted / logistic model over check-in features (sleep, mood, stress, engagement) | `low / moderate / elevated` *support-need signal* + top contributing factors + confidence |
| Crisis language detection | Fine-tuned Transformer classifier (e.g. DistilBERT/RoBERTa family) **plus** deterministic keyword/regex rules | `crisis_flag`, matched category, `requires_human: true` |
| AI wellness companion | Hosted or open LLM behind a strict system prompt + guardrails (provider decided via ADR in Phase 6) | Supportive, non-clinical responses, resource suggestions |

**Safety layer (`safety/`)** wraps every model:

1. Crisis rules run first and independently of models; any hit forces `requires_human`.
2. Output wording guard blocks diagnostic/medication language.
3. Every response includes `disclaimer` and `model_version` fields.
4. If a model fails or times out, the service returns a safe fallback (rules-only crisis
   check, no score) and an error flag; it never returns "no risk" by default.

**MLOps**: training pipelines in `training/`, experiments tracked (MLflow), artifacts in
S3, model cards per model, evaluation includes subgroup fairness checks and a crisis-recall
floor that blocks promotion if missed.

### 5.4 Data stores

- **PostgreSQL 16** (AWS RDS): system of record. Row-level ownership columns on every
  student-scoped table. Clinical fields encrypted at the application layer
  (envelope encryption with AWS KMS data keys).
- **Redis 7** (ElastiCache): sessions/refresh-token denylist, rate limiting, caching,
  background job queue, short-lived escalation timers.
- **S3**: ML artifacts, exports (encrypted, short-lived pre-signed URLs).

## 6. Data model (initial outline)

Core entities (details finalised in Phase 1–3 migrations):

- `institution`, `department`, `cohort`
- `user` (id, email, role, institution_id, status, mfa) and role profiles:
  `student_profile`, `therapist_profile`, `faculty_profile`, `admin_profile`
- `therapist_assignment` (therapist ↔ student, active window)
- `consent` (student, scope e.g. `share_checkins_with_therapist`, granted_at, revoked_at)
- `checkin` (student, mood, stress, sleep, energy, free_text_encrypted, created_at)
- `journal_entry` (student, body_encrypted, private by default; never shared without consent)
- `companion_conversation`, `companion_message` (encrypted, retention-limited)
- `ml_signal` (student, type, value band, factors, model_version, created_at)
- `appointment` (student, therapist, slot, status, mode)
- `session_note` (appointment, therapist, body_encrypted) **Clinical-Confidential**
- `referral` (from faculty, student, reason category, free text encrypted, status)
- `escalation` (student, source, severity, status, assigned_to, timeline)
- `notification`, `audit_log` (actor, action, resource, resource_id, timestamp, ip hash)

### Data classification

| Class | Examples | Controls |
|-------|----------|----------|
| Public | resource articles, helplines | none |
| Internal | institution config | auth required |
| Personal | name, email, cohort | RBAC, TLS, encrypted at rest |
| Sensitive | check-ins, journals, AI chats, ML signals, referrals | RBAC + relationship + consent, field encryption for free text, audit on read |
| Clinical-Confidential | session notes, escalation clinical details | authoring therapist only (+ supervisor policy), field encryption, audit on every access |

### Visibility matrix (summary)

| Data | Student (self) | Assigned therapist | Teacher | Admin |
|------|----------------|--------------------|---------|-------|
| Check-ins | ✅ | ✅ with consent | ❌ (aggregate only, k≥10) | ❌ (aggregate only) |
| Journal | ✅ | ❌ unless student shares an entry | ❌ | ❌ |
| AI companion chat | ✅ | ❌ (crisis excerpts only via escalation) | ❌ | ❌ |
| ML signals | ✅ with explanation | ✅ | ❌ | ❌ |
| Session notes | ❌ by default (policy-configurable) | ✅ author | ❌ | ❌ |
| Referral status | ❌ / ✅ (configurable) | ✅ | ✅ status only | ✅ metadata |
| Escalations | ✅ own status | ✅ | ❌ | ✅ metadata, not content |
| Audit log | ❌ | ❌ | ❌ | ✅ |

This matrix is enforced in `domain/policies` and covered by an authorization test matrix.

## 7. Key workflows

### 7.1 Authentication & authorization
1. Email + password (Argon2id) with optional/required MFA (TOTP) per role; institution SSO
   (SAML/OIDC) planned later.
2. API issues short-lived access JWT + rotating refresh token in httpOnly cookies.
3. Each request: `get_current_user` → load role & institution → policy check for the
   resource → audit if Sensitive/Clinical.

### 7.2 Daily check-in → insight
Student submits check-in → API stores it → enqueues ML scoring → ML returns sentiment +
support-need signal (+ crisis check on free text) → API stores `ml_signal` → student sees a
gentle, explained insight and resources; assigned therapist sees trend (with consent).

### 7.3 Crisis escalation (human-support workflow)
```
Signal source (check-in text, companion chat, journal opt-in scan, faculty referral, "Get help" button)
   │
   ▼
Crisis detection (rules ALWAYS + model)  ── any positive ──►  Escalation created (severity)
   │                                                                │
   │                                    ┌───────────────────────────┼──────────────────────┐
   ▼                                    ▼                           ▼                      ▼
Student immediately sees         On-call therapist notified   Timer: if not acknowledged   Audit log
crisis resources & helplines     (in-app + email/SMS)         in N minutes → escalate to   entry
(no waiting on humans)                                        backup / counselling lead
```
- Never blocked by ML errors (rules-based fallback).
- Teachers are never told clinical details; at most "referral received / being handled".
- Admin configures on-call rotas and helpline numbers per institution.

### 7.4 Faculty referral
Teacher submits concern (category + optional note) → routed to counselling team →
therapist triages → teacher sees only status changes.

### 7.5 Appointments & session notes
Student books available slot → therapist confirms → session → therapist writes encrypted
note, visible only to them (and supervisors by policy).

## 8. Security architecture

- TLS everywhere; HSTS; strict CSP and security headers on web.
- Secrets in AWS Secrets Manager, injected as env vars; `.env` locally (git-ignored).
- KMS-backed envelope encryption for Sensitive free text and Clinical-Confidential fields.
- Input validation via Pydantic/Zod; parameterised queries via SQLAlchemy.
- Rate limiting on auth and AI endpoints; account lockout and anomaly alerts.
- Append-only audit log; admins can read but not modify.
- Logs and traces scrubbed of PII and message bodies.
- Dependency and container scanning in CI; SAST (e.g. Bandit, ESLint security rules).
- Data retention policies per data class; student self-service export and deletion.
- Compliance posture designed toward FERPA / GDPR / India DPDP Act principles (final scope
  depends on deployment region; legal review required before production).

## 9. AI safety & ethics

- Wording: "support-need signal", "patterns", never "diagnosis", "disorder", "you have".
- Every AI surface shows: this is not medical advice, not a diagnosis, how to reach a human.
- Companion LLM: constrained system prompt, refusal of diagnosis/medication requests,
  crisis hand-off, no memory beyond configured retention, output guard.
- Models evaluated for subgroup fairness; crisis recall prioritised over precision.
- Human review of model changes; model cards document limitations.
- Development and CI use synthetic data only.

## 10. Technology stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js (App Router), React, TypeScript (strict), Tailwind CSS, shadcn/ui, TanStack Query, React Hook Form, Zod |
| Frontend tests | Vitest, Testing Library, Playwright |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, asyncpg |
| Auth | JWT (access + rotating refresh), Argon2id, TOTP MFA; SSO later |
| Data | PostgreSQL 16, Redis 7 |
| Background jobs | Redis-backed queue (ARQ or Celery, decided by ADR in Phase 4) |
| Backend tests | pytest, pytest-asyncio, httpx, factory-based synthetic fixtures |
| ML | Python, scikit-learn, PyTorch, Hugging Face Transformers, MLflow |
| Quality | Ruff, mypy, ESLint, Prettier, pre-commit |
| Containers | Docker, docker-compose |
| Cloud (AWS) | ECS Fargate, RDS PostgreSQL, ElastiCache Redis, S3, KMS, Secrets Manager, CloudFront, WAF, ALB, CloudWatch, ECR |
| IaC | Terraform |
| CI/CD | GitHub Actions |
| Observability | Structured JSON logs, OpenTelemetry, CloudWatch, Sentry (PII scrubbed) |

## 11. Environments & deployment

- **local**: docker-compose (Postgres, Redis, then web/api/ml), synthetic seed data.
- **dev / staging**: AWS, synthetic data only.
- **production**: AWS, private subnets for api/ml/db/redis, Multi-AZ RDS, backups, KMS.
- CI: lint → type-check → tests → build images → scan → push to ECR → deploy via Terraform /
  ECS rolling update. Production deploys require manual approval.

## 12. Testing strategy

- Unit tests per layer; domain policies tested exhaustively.
- **Authorization matrix tests**: every endpoint × every role, expected allow/deny.
- **Safety regression tests**: crisis phrases must always escalate; outputs must never
  contain diagnostic/medication language.
- Integration tests against Postgres/Redis containers.
- E2E Playwright flows per role.
- ML evaluation gates (crisis recall floor, fairness checks) before model promotion.

## 13. Open decisions (to be settled by ADR)

1. Background job library (ARQ vs Celery), Phase 4.
2. Companion LLM provider (hosted API vs self-hosted open model), Phase 6.
3. Session-note visibility to students (institution policy), Phase 3.
4. SSO provider support, Phase 9.
5. Target compliance regime and data residency, before production.
