# Running MindMitra locally

This guide takes you from a fresh GitHub clone to a running stack in VS Code: PostgreSQL, the
API (port 8000), the internal AI service (port 8001) and the web app (port 3000).

All data is synthetic. Never put real student data into a development database. MindMitra is an
assistive wellness system, not a diagnostic tool.

## 1. Prerequisites

| Tool | Version | Used for |
|------|---------|----------|
| Git | any recent | cloning |
| VS Code | recent | editing and running everything |
| [uv](https://docs.astral.sh/uv/) | recent | Python environments (installs Python 3.12 for you) |
| Node.js | 22 or newer | web app |
| Docker Desktop | recent | PostgreSQL 16 (or a local PostgreSQL 16, see step 3) |
| bash | any | `scripts/e2e/run.sh` only (Git Bash or WSL on Windows) |

Redis is listed in `docker-compose.yml`, but the API does not use it yet, so you can skip it.

Recommended VS Code extensions (the Extensions view, or `code --install-extension <id>`):

- `ms-python.python` and `ms-python.vscode-pylance` (Python)
- `charliermarsh.ruff` (Python lint and format)
- `dbaeumer.vscode-eslint` and `esbenp.prettier-vscode` (web)
- `ms-playwright.playwright` (end-to-end tests, optional)
- `ms-azuretools.vscode-docker` (container view, optional)

## 2. Clone the repository

In VS Code press `Ctrl+Shift+P` (`Cmd+Shift+P` on macOS), run **Git: Clone**, paste
`https://github.com/Bhavya-git-hub/MindMitra.git`, pick a parent folder, then open the cloned
`MindMitra` folder.

Or from a terminal:

```bash
git clone https://github.com/Bhavya-git-hub/MindMitra.git
cd MindMitra
code .
```

Open the **Terminal** menu, then **New Terminal**. The commands below run from the folder shown
in each section.

## 3. Start PostgreSQL

**Option A: Docker (recommended).** Copy the root template and set the Postgres values (the
password is a placeholder you choose):

```bash
cp .env.example .env
```

Edit `.env`: set `POSTGRES_PASSWORD` and any `change-me` values you need now. Then:

```bash
docker compose up -d postgres
docker compose ps        # postgres should show "running"
```

The container listens on `127.0.0.1:5432`. Its user is a superuser, so the tests can create
their own databases.

**Option B: local PostgreSQL 16.** Create a role that can create databases and an empty database:

```sql
CREATE ROLE mindmitra LOGIN CREATEDB PASSWORD 'choose-a-password';
CREATE DATABASE mindmitra OWNER mindmitra;
```

The migrations create the `btree_gist` extension, which the owner can do on PostgreSQL 13 and
later.

## 4. Create the environment files

Nothing is committed with real values. Each part of the project reads its own `.env` file from
its own folder:

| File | Created from | Read by |
|------|--------------|---------|
| `services/api/.env` | `.env.example` (root) | API and Alembic |
| `services/ml/.env` | `.env.example` (root) | AI service |
| `apps/web/.env.local` | `apps/web/.env.example` | web app |

```bash
cp .env.example services/api/.env
cp .env.example services/ml/.env
cp apps/web/.env.example apps/web/.env.local
```

Then replace every `change-me` and fill in these values:

- `APP_ENV=development` in both `services/api/.env` and `services/ml/.env`.
- `DATABASE_URL` in `services/api/.env`, using the password from step 3. The default template
  assumes user `mindmitra`, database `mindmitra` and port 5432.
- `ML_SERVICE_TOKEN`: the same value in `services/api/.env` and `services/ml/.env`. Use at least
  32 random characters, for example `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- `API_SECRET_KEY`: any long random string.
- `FIELD_ENCRYPTION_KEY` and `JWT_PRIVATE_KEY`: generate them after step 5 (`uv sync`) with the
  commands in `services/api/README.md`, and paste the output into `services/api/.env`.
- `SEED_USER_PASSWORD`: set one, so you know the password for the seeded users.
- `SESSION_SECRET` in `apps/web/.env.local`: at least 32 characters, for example `openssl rand -base64 48`.
- `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` in `apps/web/.env.local` (already the default).

Keep `TEST_DATABASE_URL` commented out unless you want to run the API tests (step 9). `.env`
files are git-ignored, so they will not be committed.

## 5. Install the backend and seed the database

```bash
cd services/api
uv sync                                                    # creates .venv and installs dependencies
uv run --env-file .env alembic upgrade head                # creates schemas and tables
uv run --env-file .env python -m app.infrastructure.db.seed   # synthetic users and data
```

The seed refuses to run twice. To start again, drop and recreate the database, then run the
`alembic upgrade head` and seed commands once more.

`--env-file .env` matters because Alembic reads `DATABASE_URL` from the process environment,
not from the file. The seed also needs `SEED_USER_PASSWORD` from it.

## 6. Start the AI service (port 8001)

The AI service provides the companion and the wellness indicators. Without its trained models,
the indicator endpoints answer 503 and the rest of the app keeps working. Train the models once
(about two minutes):

```bash
cd services/ml
uv sync
uv run python -m training.train
```

The training run also rewrites the committed report under `evaluation/reports/`. Discard those
changes with `git restore evaluation/reports` if you do not plan to commit them.

Then start the service:

```bash
uv run uvicorn app.main:create_app --factory --port 8001
```

It reads `services/ml/.env` itself. Check it with `http://localhost:8001/internal/v1/health`.

## 7. Start the API (port 8000)

In a new terminal:

```bash
cd services/api
uv run --env-file .env uvicorn app.api.main:create_app --factory --reload --port 8000
```

Check it:

- Health: `http://localhost:8000/api/v1/health/live`
- Interactive API docs (development only): `http://localhost:8000/docs`

To send appointment reminders and e-mail deliveries, also run the scheduler in a third terminal,
or set `SCHEDULER_ENABLED=true` in `services/api/.env`:

```bash
cd services/api
uv run --env-file .env python -m app.workers.scheduler
```

## 8. Start the web app (port 3000)

In a new terminal:

```bash
cd apps/web
npm ci
npm run dev
```

Open `http://localhost:3000`. Sign in with a seeded e-mail and the `SEED_USER_PASSWORD` you set.
To find the e-mails, run this against the database (for Docker, `docker compose exec postgres
psql -U mindmitra -d mindmitra`):

```sql
SELECT role, email FROM iam.users ORDER BY role, email LIMIT 8;
```

Seeded addresses end in `@synthetic.example`.

## 9. Run the tests and checks

Tests need a database user that can create databases. Use the same credentials as `DATABASE_URL`,
but point at the `postgres` database. Uncomment `TEST_DATABASE_URL` in `services/api/.env` to
set it, or export it in the terminal.

**API**

```bash
cd services/api
uv run --env-file .env pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

`mypy` currently reports 4 errors in `alembic/env.py` that predate the recommendation work.

**AI service**

```bash
cd services/ml
uv run pytest -q
uv run ruff check . && uv run mypy
```

**Web app**

```bash
cd apps/web
npm run check        # lint, typecheck, format check and unit tests
npm run build        # production build
```

**End-to-end (real API, real database, browser)**

The e2e runner needs an empty, throwaway database. From the repository root, in bash:

```bash
docker compose exec postgres psql -U mindmitra -d postgres -c "CREATE DATABASE mm_e2e;"
cd apps/web && npx playwright install chromium && cd ../..
E2E_DATABASE_URL=postgresql+asyncpg://mindmitra:YOUR_PASSWORD@localhost:5432/mm_e2e scripts/e2e/run.sh
```

The script trains small models into a temporary folder, generates fresh secrets for the run,
starts the AI service and the API, builds the web app and runs Playwright. It needs `uv`, Node
22 or newer, and bash. If you already have Chrome or Chromium, set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to its path instead of installing the Playwright browser.

## 10. Daily loop

Use one VS Code terminal per running process:

1. `docker compose up -d postgres`
2. API: `cd services/api`, then the `uvicorn` command from step 7
3. AI service: `cd services/ml`, then the `uvicorn` command from step 6
4. Web: `cd apps/web`, then `npm run dev`

Split the terminal (the split icon in the terminal toolbar) to keep them side by side.

## 11. VS Code tips

- Open the repository root, not a subfolder. It holds three projects, each with its own
  dependencies: `apps/web` (Node), `services/api` and `services/ml` (Python).
- Each Python service has its own `.venv` created by `uv sync`. Select the matching one with
  **Python: Select Interpreter**: `services/api/.venv/bin/python` for the API, or
  `services/ml/.venv/bin/python` for the AI service. On Windows the path is `.venv\Scripts\python.exe`.
- Ruff, ESLint and Prettier read the config files in each folder (`pyproject.toml`,
  `eslint.config.mjs`, Prettier settings), so the editor and the command line agree.

## 12. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ConnectionRefusedError` on port 5432 | PostgreSQL is not running. Run `docker compose up -d postgres`, or start your local server. |
| `DATABASE_URL is not set` or `TEST_DATABASE_URL is not set` | Run through `uv run --env-file .env ...` from `services/api`. |
| Indicator endpoints return 503 | Train the models (step 6) and check that `ML_SERVICE_TOKEN` matches in both `.env` files. |
| Web app says `SESSION_SECRET` is invalid | Use at least 32 characters in `apps/web/.env.local`, then restart `npm run dev`. |
| `seed refused` | The seed has already run. Recreate the database and repeat step 5. |
| Browser calls to the API are blocked by CORS | `CORS_ORIGINS` in `services/api/.env` must include `http://localhost:3000`. |
| Port already in use | Stop the other process, or pick another port and update `NEXT_PUBLIC_API_BASE_URL` and `CORS_ORIGINS` to match. |
| `scripts/e2e/run.sh` fails on Windows | Run it from Git Bash or WSL. |

More detail: `services/api/README.md`, `services/ml/README.md`, `apps/web/README.md`, and the
architecture notes in `docs/`.
