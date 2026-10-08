# ADR 0001: Record architecture decisions

- Status: Accepted
- Date: 2026-10-08

## Context
CLAUDE.md rule 1 requires that architecture is never rewritten without explanation.

## Decision
Every significant architectural decision is recorded as a numbered ADR in `docs/adr/`
(context, decision, consequences). Changes to `docs/ARCHITECTURE.md` reference the ADR that
motivated them.

## Consequences
Decisions are traceable; reversing one requires a new ADR that supersedes it.
