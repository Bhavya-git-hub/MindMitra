#!/usr/bin/env bash
# End-to-end run: real PostgreSQL + real API + the internal AI service (with its offline fake
# model, so no API key is needed) + production build of the web app + Playwright.
#
#   E2E_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/mm_e2e scripts/e2e/run.sh [playwright args]
#
# E2E_DATABASE_URL must point at an EMPTY, disposable database (with the btree_gist extension).
# Requires: uv, Node 22+, and Chromium for Playwright (see apps/web/playwright.config.ts).
# Everything secret is generated fresh for the run and lives only in this process's environment.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
API="$ROOT/services/api"
ML="$ROOT/services/ml"
WEB="$ROOT/apps/web"
API_PORT="${E2E_API_PORT:-8000}"
ML_PORT="${E2E_ML_PORT:-8001}"
WEB_PORT="${E2E_WEB_PORT:-3000}"

: "${E2E_DATABASE_URL:?set E2E_DATABASE_URL to an empty throwaway database}"

export APP_ENV=development
# The API and the AI service share this secret to sign and check service tokens.
ML_SERVICE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
export ML_SERVICE_TOKEN ML_SERVICE_URL="http://localhost:${ML_PORT}" LLM_PROVIDER=fake

cd "$ML"
uv run --quiet uvicorn app.main:create_app --factory --port "$ML_PORT" --log-level warning &
ML_PID=$!
trap 'kill "$ML_PID" 2>/dev/null || true' EXIT

cd "$API"
export DATABASE_URL="$E2E_DATABASE_URL"
FIELD_ENCRYPTION_KEY="$(uv run --quiet python -c 'from app.core.crypto import generate_key; print(generate_key())')"
JWT_PRIVATE_KEY="$(uv run --quiet python -c 'import base64; from app.core.access_tokens import generate_private_key_pem as g; print(base64.b64encode(g().encode()).decode())')"
SEED_USER_PASSWORD="E2e-$(python3 -c 'import secrets; print(secrets.token_urlsafe(14))')"
SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
export FIELD_ENCRYPTION_KEY JWT_PRIVATE_KEY SEED_USER_PASSWORD SESSION_SECRET
export CORS_ORIGINS="http://localhost:${WEB_PORT}"
export AUTH_RATE_LIMIT_PER_MINUTE=1000   # many logins from one IP; the limit itself is unit-tested
export SCHEDULER_ENABLED=true            # reminders and e-mail dispatch run as they would deployed
export NOTIFICATION_EMAIL_PROVIDER=log

uv run --quiet python "$ROOT/scripts/e2e/prepare_backend.py" "$WEB/e2e/.auth/users.json"

uv run --quiet uvicorn app.api.main:create_app --factory --port "$API_PORT" --log-level warning &
API_PID=$!
trap 'kill "$API_PID" "$ML_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  curl -fsS "http://localhost:${API_PORT}/api/v1/health/live" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS "http://localhost:${API_PORT}/api/v1/health/live" >/dev/null || { echo "API did not start" >&2; exit 1; }
for _ in $(seq 1 60); do
  curl -fsS "http://localhost:${ML_PORT}/internal/v1/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS "http://localhost:${ML_PORT}/internal/v1/health" >/dev/null || { echo "AI service did not start" >&2; exit 1; }

cd "$WEB"
export NEXT_PUBLIC_API_BASE_URL="http://localhost:${API_PORT}"
export E2E_PASSWORD="$SEED_USER_PASSWORD"
export E2E_WEB_PORT="$WEB_PORT"
export ENABLE_DESIGN_SYSTEM=true
npm run build
npx playwright test "$@"
