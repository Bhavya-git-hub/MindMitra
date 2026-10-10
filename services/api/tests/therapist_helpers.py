"""Arrange helpers for the therapist-portal API tests.

Every test builds its own therapist and students so the shared cast in ``api_world`` stays
untouched. People are created in the database; everything else goes through the real API.
"""

import dataclasses
import datetime as dt
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AlertCategory,
    AlertDetector,
    AlertSeverity,
    AlertSource,
    AppointmentStatus,
    SessionMode,
    UserRole,
)
from app.infrastructure.db.ids import uuid7
from tests.api_world import Builder, World
from tests.student_helpers import Session, new_student, new_therapist, sign_in


@dataclasses.dataclass
class Pair:
    therapist: Session
    student: Session


async def care_pair(
    client: httpx.AsyncClient,
    db: AsyncSession,
    world: World,
    *,
    mood: bool = True,
    assessments: bool = False,
    therapist: Session | None = None,
) -> Pair:
    """A student on a (verified) therapist's care team through a confirmed first appointment,
    optionally having consented to share check-ins and/or questionnaires."""
    s = await new_student(client, db, world)
    if therapist is None:
        therapist, slots = await new_therapist(client, db, world)
    else:
        slots = [await _open_slot(db, therapist)]
    booked = await s.post("/me/appointments", {"availability_id": str(slots[0])})
    assert booked.status_code == 201, booked.text
    confirmed = await therapist.patch(
        f"/appointments/{booked.json()['id']}", {"status": "confirmed"}
    )
    assert confirmed.status_code == 200, confirmed.text
    if mood:
        assert (
            await s.put("/me/consents/share_mood_with_care_team", {"granted": True})
        ).status_code == 200
    if assessments:
        assert (
            await s.put("/me/consents/share_assessments_with_care_team", {"granted": True})
        ).status_code == 200
    return Pair(therapist, s)


async def _open_slot(db: AsyncSession, therapist: Session) -> uuid.UUID:
    latest = await db.scalar(
        select(m.TherapistAvailability.ends_at)
        .where(m.TherapistAvailability.therapist_id == therapist.id)
        .order_by(m.TherapistAvailability.ends_at.desc())
        .limit(1)
    )
    start = (latest or (dt.datetime.now(dt.UTC) + dt.timedelta(days=3))) + dt.timedelta(days=1)
    slot = m.TherapistAvailability(
        id=uuid7(),
        institution_id=therapist.actor.institution_id,
        therapist_id=therapist.id,
        starts_at=start,
        ends_at=start + dt.timedelta(hours=1),
        mode=SessionMode.VIDEO,
    )
    db.add(slot)
    await db.commit()
    return slot.id


async def due_appointment(
    db: AsyncSession,
    pair: Pair,
    *,
    starts_in: dt.timedelta = dt.timedelta(minutes=5),
    status: AppointmentStatus = AppointmentStatus.CONFIRMED,
) -> uuid.UUID:
    """A confirmed appointment that can be started now (no availability slot needed)."""
    start = dt.datetime.now(dt.UTC) + starts_in
    appt = m.Appointment(
        id=uuid7(),
        institution_id=pair.therapist.actor.institution_id,
        student_id=pair.student.id,
        therapist_id=pair.therapist.id,
        starts_at=start,
        ends_at=start + dt.timedelta(minutes=50),
        mode=SessionMode.VIDEO,
        status=status,
        cancelled_at=dt.datetime.now(dt.UTC) if status is AppointmentStatus.CANCELLED else None,
    )
    db.add(appt)
    await db.commit()
    return appt.id


async def started_session(db: AsyncSession, pair: Pair) -> uuid.UUID:
    appt = await due_appointment(db, pair)
    r = await pair.therapist.post(f"/therapist/appointments/{appt}/session")
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["id"])


async def make_alert(
    db: AsyncSession,
    pair: Pair,
    *,
    severity: AlertSeverity = AlertSeverity.MODERATE,
    assigned: bool = False,
    excerpt: str | None = None,
) -> uuid.UUID:
    now = dt.datetime.now(dt.UTC)
    alert = m.RiskAlert(
        id=uuid7(),
        institution_id=pair.student.actor.institution_id,
        student_id=pair.student.id,
        assigned_to=pair.therapist.id if assigned else None,
        source=AlertSource.HELP_BUTTON,
        detector=AlertDetector.HUMAN,
        category=AlertCategory.ACUTE_DISTRESS,
        severity=severity,
        requires_human=True,
        excerpt=excerpt,
        sla_ack_due_at=now + dt.timedelta(hours=4),
    )
    db.add(alert)
    await db.commit()
    return alert.id


async def fresh_therapist(
    client: httpx.AsyncClient,
    db: AsyncSession,
    world: World,
    *,
    verified: bool = True,
    other_tenant: bool = False,
) -> Session:
    t, _ = await new_therapist(
        client, db, world, slots=0, verified=verified, other_tenant=other_tenant
    )
    return t


async def fresh_admin(
    client: httpx.AsyncClient, db: AsyncSession, world: World, *, other_tenant: bool = False
) -> Session:
    actor = await Builder(db, world.password).user(
        world.inst_b if other_tenant else world.inst_a, UserRole.ADMINISTRATOR
    )
    await db.commit()
    return await sign_in(client, actor, world.password)


async def end_care_link(db: AsyncSession, pair: Pair) -> None:
    """The student leaves the therapist's care team (the link ended a minute ago)."""
    link = await db.scalar(
        select(m.CareTeamMember).where(
            m.CareTeamMember.student_id == pair.student.id,
            m.CareTeamMember.therapist_id == pair.therapist.id,
        )
    )
    assert link is not None
    now = dt.datetime.now(dt.UTC)
    link.starts_at = now - dt.timedelta(hours=1)
    link.ends_at = now - dt.timedelta(minutes=1)
    await db.commit()
