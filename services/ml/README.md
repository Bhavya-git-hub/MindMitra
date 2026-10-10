# services/ml: internal AI service

Internal only: called by `services/api`, never by browsers. It runs the wellness companion
behind a safety layer ([ADR 0010](../../docs/adr/0010-ai-wellness-companion-and-safety-layer.md))
and the wellness-indicator models
([ADR 0011](../../docs/adr/0011-wellness-indicator-models.md)). It is stateless and keeps no
text: nothing a student writes is stored, logged or measured here.

> The indicator models are trained on **synthetic data only**. They are wellness indicators,
> not diagnoses, and no clinical accuracy is claimed. Limitations are in
> [model_cards/wellness-indicators.md](model_cards/wellness-indicators.md) and
> [model_cards/sentiment.md](model_cards/sentiment.md).

```
app/          FastAPI app, settings, service-token auth
app/companion topics, prompt templates, context window, orchestrator
app/providers LLMProvider interface: Anthropic (HTTPS) and an offline fake
safety/       crisis rules (shared with the API), input guard, output guard, fixed replies
data/           synthetic generators: a check-in cohort and a corpus of notes
preprocessing/  daily records, the 31 check-in features, note cleaning, model pipelines
training/       indicator specs, model comparison, sentiment, artifacts, `python -m training.train`
evaluation/     metrics and the report writer; reports/ holds the latest committed results
inference/      verified model loading (registry) and scoring
models/         trained model files and manifest.json (built locally, not committed)
model_cards/    what each part is for, how it was tested, and its limits
tests/          unit tests and safety suites (tests/suites/*.yaml), synthetic data only
```

## Endpoints

| Method & path | Auth | Purpose |
|---------------|------|---------|
| `GET /internal/v1/health` | none | Liveness only |
| `GET /internal/v1/models` | service token | Model, prompt and crisis-rules versions |
| `POST /internal/v1/companion/respond` | service token | `{message, history}` to `{kind, reply, crisis, topic, flags, model_version}` |
| `POST /internal/v1/indicators` | service token | `{window_end, days, notes}` to six indicators, each a band or "not enough data", with model versions and the disclaimer |
| `POST /internal/v1/sentiment` | service token | `{texts}` (up to 50) to a tone label and probabilities per text |

The indicator endpoints answer 503 when the models are missing or fail verification; the
companion keeps working.

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

## Train the indicator models

```bash
cd services/ml
uv run python -m training.train            # about 2 minutes; writes models/ and evaluation/reports/
uv run --group nlp python -m training.train  # also compares a small transformer (needs PyTorch)
uv run python -m training.train --quick --no-transformer --out /tmp/models --reports /tmp/reports
```

The first command reproduces `evaluation/reports/REPORT.md` (seeded). Files in `models/` are
loaded only if they match `models/manifest.json` (SHA-256 and library versions).
`ML_MODEL_DIR` points the service at another directory.

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```

No reply and no indicator is a diagnosis. Every message and every draft passes through `safety/`, and a crisis
is never answered by the model.
