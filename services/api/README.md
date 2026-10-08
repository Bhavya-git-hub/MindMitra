# services/api: Backend

FastAPI + Pydantic v2 + SQLAlchemy 2 (async) + Alembic + PostgreSQL + Redis.

**Current state:** the database layer only (models, migration, seed, tests). There are no HTTP
endpoints and no authentication yet; those arrive in later phases.

## Layout

```
app/
  core/             settings (env vars only), field encryption, password hashing
  infrastructure/
    db/             models/, session management, UUIDv7 ids, audit hash chain, seed/
  api/ application/ domain/    reserved for later phases (clean architecture layers)
alembic/            migrations (0001_initial_schema, 0002_tenant_safe_foreign_keys)
tests/              migration, constraint, cascade, security and seed tests against real PostgreSQL
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

Generate a field-encryption key with:
`python -c "from app.core.crypto import generate_key; print(generate_key())"`.

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
