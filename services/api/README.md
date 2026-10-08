# services/api — Backend

FastAPI + Pydantic v2 + SQLAlchemy 2 (async) + Alembic + PostgreSQL + Redis.

Clean architecture layers (dependencies point inward):

```
app/
  api/             HTTP routers, request/response schemas, auth dependencies
  application/     use cases / services (orchestrate domain + infrastructure)
  domain/          entities, value objects, policies (authorization), repository interfaces
  infrastructure/  SQLAlchemy models & repositories, Redis, ML client, email, encryption
  core/            settings, security (JWT, hashing), logging, audit
alembic/           migrations
tests/             unit, integration, authorization matrix tests
```

Not scaffolded yet: dependencies are installed when Phase 1 starts.
