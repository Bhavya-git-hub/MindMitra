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
| `services/ml` | Internal ML inference service: risk signals, sentiment, crisis detection, safety layer |
| `packages/contracts` | Shared API contracts (OpenAPI spec, generated types) |
| `infra` | Docker and AWS (Terraform) infrastructure |
| `data/synthetic` | Synthetic-data generators and fixtures (no real data, ever) |
| `scripts` | Developer scripts |
| `docs` | ADRs and supplementary docs |

## Key documents

- [`CLAUDE.md`](CLAUDE.md): permanent project rules (read first)
- [`ARCHITECTURE.md`](ARCHITECTURE.md): system architecture
- [`DEVELOPMENT_ROADMAP.md`](DEVELOPMENT_ROADMAP.md): phase-by-phase plan

## Status

Phase 0 (foundation). No application features have been implemented yet.
