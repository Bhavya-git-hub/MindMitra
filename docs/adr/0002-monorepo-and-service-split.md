# ADR 0002: Monorepo with separate web, api and ml services

- Status: Accepted
- Date: 2026-10-08

## Context
The platform spans a TypeScript frontend, a Python API and Python ML workloads with
heavy dependencies (PyTorch, Transformers) and different scaling needs.

## Decision
One monorepo with three deployable units: `apps/web`, `services/api`, `services/ml`.
The ML service is internal-only and called exclusively by the API.

## Consequences
Clear module boundaries and independent scaling; the API image stays small. Requires an
internal service-to-service auth token and a typed client in the API.
