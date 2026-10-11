# MindMitra

AI-assisted, privacy-preserving student wellness and therapist support platform for colleges.

> MindMitra is an assistive wellness tool. It does **not** diagnose mental-health conditions,
> prescribe medication, or replace licensed professionals. If you are in crisis, contact your
> local emergency number or campus counselling service immediately.

## Repository layout

| Path | Purpose |
|------|---------|
| `apps/web` | Next.js + TypeScript + Tailwind + shadcn/ui frontend (all four role portals) |
| `services/api` | FastAPI backend: auth, RBAC, domain logic, PostgreSQL, Redis |
| `services/ml` | Internal AI service: the wellness companion behind a safety layer (crisis rules, input and output guards); risk signals later |
| `packages/contracts` | Shared API contracts (OpenAPI spec, generated types) |
| `infra` | Docker and AWS (Terraform) infrastructure |
| `data/synthetic` | Synthetic-data generators and fixtures (no real data, ever) |
| `scripts` | Developer scripts |
| `docs` | ADRs and supplementary docs |

## Key documents

- [`CLAUDE.md`](CLAUDE.md): permanent project rules (read first)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): full technical architecture (16 areas + risks)
- [`docs/SAFETY_SYSTEM.md`](docs/SAFETY_SYSTEM.md): risk levels, escalation, consent and logging rules, known gaps. The safety system is not a replacement for emergency services or qualified professionals
- [`docs/DATABASE_DESIGN.md`](docs/DATABASE_DESIGN.md), [`docs/API_DESIGN.md`](docs/API_DESIGN.md), [`docs/SECURITY_ARCHITECTURE.md`](docs/SECURITY_ARCHITECTURE.md), [`docs/AI_ML_ARCHITECTURE.md`](docs/AI_ML_ARCHITECTURE.md), [`docs/USER_FLOWS.md`](docs/USER_FLOWS.md)
- [`DEVELOPMENT_ROADMAP.md`](DEVELOPMENT_ROADMAP.md): phase-by-phase plan

## Status

Phase 0 (foundation and architecture design). No application code has been written yet.
