"""Prepare a disposable database for the web end-to-end tests.

Run from services/api (`uv run python ../../scripts/e2e/prepare_backend.py <out.json>`) with
DATABASE_URL pointing at an EMPTY throwaway database and SEED_USER_PASSWORD set. It migrates the
schema, loads the synthetic seed, and writes one active user per role (email only) to <out.json>.
The password is never written to disk: the e2e run passes it through the environment.

Refuses to run unless APP_ENV is development or test.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROLES = ("student", "therapist", "teacher", "administrator")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    if os.environ.get("APP_ENV") not in {"development", "test"}:
        print("Refusing to run: APP_ENV must be development or test", file=sys.stderr)
        return 2
    if not os.environ.get("SEED_USER_PASSWORD"):
        print("SEED_USER_PASSWORD must be set", file=sys.stderr)
        return 2

    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    subprocess.run([sys.executable, "-m", "app.infrastructure.db.seed"], check=True)

    users = asyncio.run(_pick_users())
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(users, indent=2) + "\n")
    print(f"wrote {out}: {', '.join(f'{r}={u}' for r, u in users.items())}")
    return 0


async def _pick_users() -> dict[str, str]:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "select distinct on (role) role, email from iam.users "
                        "where status = 'active' and deleted_at is null order by role, email"
                    )
                )
            ).all()
    finally:
        await engine.dispose()
    users = {role: email for role, email in rows}
    missing = [r for r in ROLES if r not in users]
    if missing:
        raise SystemExit(f"seed produced no active user for: {missing}")
    return {r: users[r] for r in ROLES}


if __name__ == "__main__":
    raise SystemExit(main())
