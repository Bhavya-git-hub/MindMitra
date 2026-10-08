"""CLI: ``python -m app.infrastructure.db.seed [--students N] [--seed N]``.

Run ``alembic upgrade head`` first. The login password for all synthetic users is read
from SEED_USER_PASSWORD, or generated randomly and printed once.
"""

import argparse
import asyncio
import os

from app.infrastructure.db.seed.generator import SeedConfig, SeedRefused, seed_database
from app.infrastructure.db.session import create_engine, create_session_factory


async def _run(cfg: SeedConfig) -> int:
    engine = create_engine()
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            try:
                result = await seed_database(session, cfg)
            except SeedRefused as exc:
                print(f"seed refused: {exc}")
                return 1
    finally:
        await engine.dispose()
    print("Seeded synthetic data:")
    for name, n in sorted(result.counts.items()):
        print(f"  {name:<24}{n:>7}")
    if cfg.password is None:
        print(f"\nPassword for all synthetic users (shown once): {result.password}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Seed synthetic development data")
    p.add_argument("--students", type=int, default=120)
    p.add_argument("--teachers", type=int, default=8)
    p.add_argument("--therapists", type=int, default=6)
    p.add_argument("--seed", type=int, default=20261008)
    args = p.parse_args()
    cfg = SeedConfig(
        students=args.students,
        teachers=args.teachers,
        therapists=args.therapists,
        seed=args.seed,
        password=os.environ.get("SEED_USER_PASSWORD"),
    )
    raise SystemExit(asyncio.run(_run(cfg)))


if __name__ == "__main__":
    main()
