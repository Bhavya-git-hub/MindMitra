# services/api: Backend

FastAPI + Pydantic v2 + SQLAlchemy 2 (async) + Alembic + PostgreSQL + Redis.

**Current state:** the database layer plus authentication and role-based authorization:
registration, login, logout, refresh-token rotation, password reset, account setup, role and
permission guards, resource policies, and the first protected endpoints for each role. See
[`docs/SECURITY_ARCHITECTURE.md`](../../docs/SECURITY_ARCHITECTURE.md) section 0 and
[`docs/API_DESIGN.md`](../../docs/API_DESIGN.md) section 0 for exactly what is built.

## Layout

```
app/
  api/              FastAPI app factory (main.py), routes/, guards and auth dependencies (deps.py),
                    problem responses, rate limiter
  application/      use cases: auth/ (login, refresh, reset ...), care, insights, admin, and the
                    student portal: student_wellness, goals, recommendations, directory, booking,
                    messaging, privacy, safety; therapist portal: therapist_access,
                    therapist_profile, therapist_students, therapist_appointments, therapy_sessions
                    (notes), risk_alerts, follow_ups, therapist_recommendations, therapist_dashboard; teacher portal: teacher_portal, cohort_stats,
                    referrals, teacher_support
  domain/auth/      roles and permissions, resource policies, password policy (no framework code)
  domain/wellness/  pure rules: WHO-5 scoring, indicators, recommendation rules, support prompt,
                    cohort (group-privacy thresholds) and cohort_report
  core/             settings (env vars only), JWT signing, field encryption, password hashing
  infrastructure/
    db/             models/, session management, UUIDv7 ids, audit hash chain, seed/
alembic/            migrations (0001_initial_schema, 0002_tenant_safe_foreign_keys, 0003_auth_sessions, 0004_crisis_contacts, 0005_therapist_portal, 0006_teacher_portal, 0007_group_snapshots)
tests/              database tests, plus auth and cross-role authorization tests through the API,
                    all against real PostgreSQL
```

## Database quick start

Requires Python 3.12+ and PostgreSQL 16 (with the `btree_gist` extension, included in standard
builds and the official Docker image).

```bash
cp ../../.env.example .env        # edit values; .env is git-ignored
uv sync                           # or: pip install -e . plus the dev group
alembic upgrade head              # create schemas, tables, constraints, audit triggers
python -m app.infrastructure.db.seed   # synthetic data (development only)
```

Generate the two keys (put them in `.env`, never commit them):

```bash
python -c "from app.core.crypto import generate_key; print(generate_key())"   # FIELD_ENCRYPTION_KEY
python -c "from app.core.access_tokens import generate_private_key_pem as g; import base64; print(base64.b64encode(g().encode()).decode())"   # JWT_PRIVATE_KEY
```

## Running the API

```bash
uvicorn app.api.main:create_app --factory --reload   # http://localhost:8000/docs (development only)
```

Sign in with `POST /api/v1/auth/login` using a seeded e-mail and the seed password. The response
carries a short-lived access token (send it as `Authorization: Bearer ...`) and sets the refresh
cookie. In development, e-mailed links (verification, reset, account setup) go to an in-memory
outbox; the app refuses to start in staging or production until a real sender is configured.

The seed creates one fictional institution (about 15,000 rows for 120 students). All users share
one password: set `SEED_USER_PASSWORD`, or a random one is generated and printed once. The seed
refuses to run when `APP_ENV=production` or if it has already run; to reseed, recreate the
database (`alembic downgrade base && alembic upgrade head`).

## Tests and checks

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://USER:PASS@localhost:5432/postgres
pytest            # creates and drops its own temporary databases
ruff check . && ruff format --check .
mypy
alembic check     # fails if models and migrations drift (needs DATABASE_URL)
```

Some tests (simulating audit tampering, creating a temporary role) need a superuser test role and
skip otherwise. See [`docs/DATABASE_DESIGN.md`](../../docs/DATABASE_DESIGN.md) section 0 for what is
built and how it differs from the original design.
