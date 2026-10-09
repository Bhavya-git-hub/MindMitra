# MindMitra Development Roadmap

We build phase by phase (CLAUDE.md rules 16–17). Each phase has a goal, scope, and exit
criteria. A phase starts only when the previous one meets its exit criteria or the owner
says otherwise. Each phase ends with tests run and passing (rule 20).

---

## Phase 0: Foundation ✅ (current)

**Goal:** agree on rules, architecture and plan before writing features.

- [x] `CLAUDE.md` permanent rules
- [x] Monorepo structure (`apps/web`, `services/api`, `services/ml`, `packages`, `infra`, `data`, `docs`)
- [x] `DEVELOPMENT_ROADMAP.md`, ADRs 0001–0002
- [x] Full architecture design in `docs/`: ARCHITECTURE, DATABASE_DESIGN, API_DESIGN,
      SECURITY_ARCHITECTURE, AI_ML_ARCHITECTURE, USER_FLOWS (with Mermaid diagrams and risk register)
- [x] `.env.example`, `.gitignore`, local `docker-compose.yml` (Postgres + Redis)

**Exit:** owner reviews and approves architecture and roadmap.

---

## Phase 1: Project scaffolding & developer experience

**Goal:** every module builds, lints, type-checks and runs a trivial test locally and in CI.

- Next.js app scaffold (TypeScript strict, Tailwind, shadcn/ui init, ESLint, Prettier, Vitest)
- FastAPI app scaffold with clean-architecture folders, typed settings, structured logging,
  `/health` (explicitly public), Ruff, mypy, pytest
- ML service scaffold (FastAPI, internal token auth, `/health`), pytest
- Dockerfiles for web, api, ml; docker-compose runs the full stack
- Alembic initialised; PostgreSQL + Redis connectivity checks
- GitHub Actions: lint, type-check, test for each module; pre-commit hooks
- Synthetic data generator skeleton (`data/synthetic`)

**Exit:** `docker compose up` brings up all services healthy; CI green.

---

## Phase 2: Identity, roles & authorization core

**Goal:** secure foundation every later feature depends on.

- Data model: institution, user, role profiles, therapist assignment, consent, audit log
  (**done early** in the database-layer work; see `docs/DATABASE_DESIGN.md` section 0)
- Registration/invite flows (admin invites therapists/faculty; students via institution email)
  (**done**: API)
- Login, logout, refresh rotation, Argon2id (**done**); optional TOTP MFA (to do)
- Central policy layer (`domain/auth/policies.py`) and `require_permission` dependency (**done**)
- Audit logging for Sensitive/Clinical access and every denial (**done**)
- Rate limiting on auth endpoints (**done** in-process; Redis-backed later)
- Frontend: auth pages, role-based route groups and layouts, session handling (to do)
- Admin: basic user & role management UI (API **done**; UI to do)
- **Authorization matrix test suite** (every endpoint × every role) (**done**; see
  `services/api/tests/test_rbac_api.py`)
- PostgreSQL row-level security policies as a second tenant guard (to do)

**Exit:** four roles can log in to their own portal; cross-role access denied and tested.

---

## Phase 3: Student wellness core & therapist workflows

**Goal:** core non-AI value for students and therapists.

- Student: mood/stress/sleep check-ins, private encrypted journal, resource library,
  consent management, own-data export/delete request
- Therapist: caseload view, availability, appointment booking/confirmation
- Encrypted session notes (Clinical-Confidential), visible to author only
- Field-level encryption service (KMS-compatible, local key for dev)
- Visibility-matrix tests (teachers and admins cannot read clinical/sensitive content)
- ADR: session-note visibility policy

**Exit:** student ↔ therapist booking and note-taking work end-to-end with synthetic data.

---

## Phase 4: Safety & crisis escalation (rules-based)

**Goal:** a reliable human-support escalation workflow **before** any ML is added.

- Persistent "Get help now" entry point and crisis resource page (institution-configurable)
- Deterministic crisis keyword/regex detector (safety layer) on check-in free text
- Escalation entity, severity levels, on-call rota, notifications (in-app + email; SMS later)
- Acknowledgement timers with automatic escalation to backup
- Background worker (ADR: ARQ vs Celery)
- Faculty referral form + status-only visibility for faculty
- Safety regression tests (crisis phrases always escalate, fail-safe on errors)

**Exit:** a crisis phrase in synthetic data always produces resources for the student and a
notified, auditable escalation, even with workers degraded.

---

## Phase 5: ML service: assistive insights

**Goal:** add AI assistance behind the safety layer.

- Synthetic training datasets + generators; data documentation
- Sentiment baseline (scikit-learn), then Transformer fine-tune (PyTorch + HF)
- Support-need signal model over check-in features with explanations
- Transformer crisis classifier combined with rules (rules still always run)
- Output wording guard, disclaimers, `model_version` on every response
- Model cards, MLflow tracking, evaluation gates (crisis recall floor, fairness checks)
- API integration via typed client, timeouts and safe fallbacks
- Student-facing explained insights; therapist-facing trends (with consent)

**Exit:** ML outputs appear only through the safety layer, with tests proving no diagnostic
language and fail-safe behaviour.

---

## Phase 6: AI wellness companion

**Goal:** supportive conversational companion that routes to humans.

- ADR: LLM provider/hosting and data-processing terms
- Guardrailed system prompt, refusal of diagnosis/medication requests
- Real-time crisis detection on every message → escalation workflow
- Retention limits, encryption, student-controlled deletion
- Clear "I'm an AI, not a therapist" messaging and hand-off to booking
- Red-team test suite of unsafe prompts

**Exit:** companion passes the safety red-team suite; crisis messages escalate every time.

---

## Phase 7: Faculty & admin insights

**Goal:** privacy-preserving institutional insight.

- Aggregate, de-identified cohort wellness trends with k-anonymity threshold (k ≥ 10)
- Admin analytics: usage, escalation response times, system health
- Audit log viewer, institution settings, helpline configuration
- Tests proving small cohorts are suppressed and no individual data leaks

**Exit:** faculty/admin dashboards show only aggregate data; leakage tests pass.

---

## Phase 8: AWS infrastructure & deployment

**Goal:** production-grade, secure cloud deployment.

- Terraform: VPC, ECS Fargate, RDS (Multi-AZ), ElastiCache, S3, KMS, Secrets Manager,
  ECR, ALB, CloudFront, WAF, CloudWatch
- CI/CD: build, scan, push, deploy to dev → staging → prod (manual approval)
- Backups, restore drill, observability (OpenTelemetry, alerts), PII-scrubbed error tracking

**Exit:** staging environment running on AWS from CI with synthetic data.

---

## Phase 9: Hardening & launch readiness

- Security review, penetration test, dependency/container scanning clean
- Accessibility audit (WCAG 2.1 AA), performance and load tests
- Privacy review: retention, export/deletion, consent flows; compliance/legal review
- Clinical advisor review of safety wording and escalation workflow
- SSO (SAML/OIDC) for institutions, documentation, runbooks, on-call guide

**Exit:** sign-off from owner, security, privacy and clinical reviewers.

---

## Cross-cutting, every phase

- Tests for every important feature; authorization and safety tests never skipped
- Docs and ADRs updated alongside code
- Synthetic data only outside production
- No secrets in code; env vars only
