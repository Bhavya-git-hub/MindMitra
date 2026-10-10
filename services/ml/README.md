# services/ml: internal AI service

Internal only: called by `services/api`, never by browsers. It runs the wellness companion
behind a safety layer ([ADR 0010](../../docs/adr/0010-ai-wellness-companion-and-safety-layer.md)).
It is stateless and keeps no text: nothing a student writes is stored, logged or measured here.

```
app/          FastAPI app, settings, service-token auth
app/companion topics, prompt templates, context window, orchestrator
app/providers LLMProvider interface: Anthropic (HTTPS) and an offline fake
safety/       crisis rules (shared with the API), input guard, output guard, fixed replies
model_cards/  what each part is for, how it was tested, and its limits
tests/        unit tests and safety suites (tests/suites/*.yaml), synthetic data only
training/     reserved for trained models (none yet)
```

## Endpoints

| Method & path | Auth | Purpose |
|---------------|------|---------|
| `GET /internal/v1/health` | none | Liveness only |
| `GET /internal/v1/models` | service token | Model, prompt and crisis-rules versions |
| `POST /internal/v1/companion/respond` | service token | `{message, history}` to `{kind, reply, crisis, topic, flags, model_version}` |

The service token is an HS256 JWT (`aud=mindmitra-ml`, `iss=mindmitra-api`, at most five
minutes) signed with `ML_SERVICE_TOKEN`, the same secret the API has.

## Run it

```bash
cd services/ml
uv sync
APP_ENV=development ML_SERVICE_TOKEN=<32+ random characters> LLM_PROVIDER=fake \
  uv run uvicorn app.main:create_app --factory --port 8001
```

Then point the API at it with `ML_SERVICE_URL=http://localhost:8001` and the same
`ML_SERVICE_TOKEN`. To use a real model, set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`
in the environment (never in a file that is committed). `ANTHROPIC_MODEL` picks the model.

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```

No reply is a diagnosis. Every message and every draft passes through `safety/`, and a crisis
is never answered by the model.
