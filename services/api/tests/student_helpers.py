"""Arrange helpers for the student-portal API tests.

Mutating tests get their own freshly created people, so they never disturb the shared cast in
``api_world`` that the authorization matrix relies on.
"""

import datetime as dt
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import SessionMode, UserRole
from app.infrastructure.db.ids import uuid7
from tests.api_helpers import call, login
from tests.api_world import Actor, Builder, World


class Session:
    """An actor plus a ready-to-use token and tiny request helpers."""

    def __init__(self, client: httpx.AsyncClient, actor: Actor, token: str) -> None:
        self.client = client
        self.actor = actor
        self.token = token

    @property
    def id(self) -> uuid.UUID:
        return self.actor.user_id

    async def get(self, path: str, **kw: Any) -> httpx.Response:
        return await call(self.client, "GET", path, token=self.token, **kw)

    async def post(self, path: str, json: Any = None) -> httpx.Response:
        return await call(self.client, "POST", path, token=self.token, json=json)

    async def put(self, path: str, json: Any = None) -> httpx.Response:
        return await call(self.client, "PUT", path, token=self.token, json=json)

    async def patch(self, path: str, json: Any = None) -> httpx.Response:
        return await call(self.client, "PATCH", path, token=self.token, json=json)

    async def delete(self, path: str) -> httpx.Response:
        return await call(self.client, "DELETE", path, token=self.token)


async def sign_in(client: httpx.AsyncClient, actor: Actor, password: str) -> Session:
    r = await login(client, actor.email, password)
    assert r.status_code == 200, r.text
    return Session(client, actor, r.json()["access_token"])


async def new_student(
    client: httpx.AsyncClient, db: AsyncSession, world: World, *, other_tenant: bool = False
) -> Session:
    b = Builder(db, world.password)
    if other_tenant:
        actor = await b.user(world.inst_b, UserRole.STUDENT, department_id=await _dept_b(db, world))
    else:
        actor = await b.user(world.inst_a, UserRole.STUDENT, department_id=world.dept_a)
    await db.commit()
    return await sign_in(client, actor, world.password)


async def _dept_b(db: AsyncSession, world: World) -> uuid.UUID:
    dept = await db.scalar(
        select(m.Department.id).where(m.Department.institution_id == world.inst_b)
    )
    assert dept is not None
    return dept


async def new_therapist(
    client: httpx.AsyncClient,
    db: AsyncSession,
    world: World,
    *,
    slots: int = 3,
    first_slot_in: dt.timedelta = dt.timedelta(days=3),
    other_tenant: bool = False,
    accepting: bool = True,
    verified: bool = True,
) -> tuple[Session, list[uuid.UUID]]:
    """A therapist with ``slots`` hour-long open slots, one per day from ``first_slot_in``."""
    inst = world.inst_b if other_tenant else world.inst_a
    actor = await Builder(db, world.password).user(inst, UserRole.THERAPIST, verified=verified)
    therapist = await db.get(m.Therapist, actor.user_id)
    assert therapist is not None
    therapist.accepting_new_students = accepting
    therapist.specialties = ["anxiety", "exam stress"]
    therapist.languages = ["English"]
    therapist.bio = "Synthetic bio for tests."
    start = (dt.datetime.now(dt.UTC) + first_slot_in).replace(minute=0, second=0, microsecond=0)
    ids: list[uuid.UUID] = []
    for i in range(slots):
        slot = m.TherapistAvailability(
            id=uuid7(),
            institution_id=inst,
            therapist_id=actor.user_id,
            starts_at=start + dt.timedelta(days=i),
            ends_at=start + dt.timedelta(days=i, hours=1),
            mode=SessionMode.VIDEO,
        )
        db.add(slot)
        ids.append(slot.id)
    await db.commit()
    return await sign_in(client, actor, world.password), ids


def local_time_iso(base: dt.datetime) -> str:
    return base.astimezone(dt.UTC).isoformat()


def sleep_body(
    hours: float = 7.5, quality: int = 4, *, wake: dt.datetime | None = None
) -> dict[str, Any]:
    wake = wake or dt.datetime.now(dt.UTC).replace(hour=6, minute=30, second=0, microsecond=0)
    if wake > dt.datetime.now(dt.UTC):
        wake -= dt.timedelta(days=1)
    bed = wake - dt.timedelta(hours=hours)
    return {"bedtime": bed.isoformat(), "wake_time": wake.isoformat(), "quality": quality}
