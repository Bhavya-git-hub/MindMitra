"""Therapist directory, booking, cancelling and appointment history for students."""

import datetime as dt

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AppointmentStatus,
    AuditOutcome,
    NotificationType,
    UserStatus,
)
from tests.api_world import World
from tests.student_helpers import new_student, new_therapist

pytestmark = pytest.mark.asyncio


# ---- directory ------------------------------------------------------------------------------


async def test_directory_lists_only_my_institutions_active_therapists(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    mine, _ = await new_therapist(client, api_db, world)
    foreign, _ = await new_therapist(client, api_db, world, other_tenant=True)
    suspended, _ = await new_therapist(client, api_db, world)
    user = await api_db.get(m.User, suspended.id)
    assert user is not None
    user.status = UserStatus.SUSPENDED
    await api_db.commit()

    r = await s.get("/therapists?limit=100")
    assert r.status_code == 200, r.text
    ids = {t["id"] for t in r.json()}
    assert str(mine.id) in ids
    assert str(foreign.id) not in ids
    assert str(suspended.id) not in ids
    assert (await s.get(f"/therapists/{foreign.id}")).status_code == 404
    assert (await s.get(f"/therapists/{suspended.id}")).status_code == 404
    assert (await s.get(f"/therapists/{foreign.id}/slots")).status_code == 404


async def test_directory_exposes_public_profile_fields_only(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    t, _ = await new_therapist(client, api_db, world)
    detail = (await s.get(f"/therapists/{t.id}")).json()
    assert set(detail) == {
        "id", "full_name", "specialties", "languages", "accepting_new_students",
        "next_available_at", "on_my_care_team", "bio",
    }  # fmt: skip
    assert detail["bio"] == "Synthetic bio for tests." and detail["next_available_at"]
    assert "licence" not in (await s.get("/therapists")).text.lower()
    filtered = (
        await s.get("/therapists?specialty=anxiety&language=English&accepting_only=true")
    ).json()
    assert str(t.id) in {x["id"] for x in filtered}
    assert str(t.id) not in {x["id"] for x in (await s.get("/therapists?specialty=nope")).json()}


async def test_slots_hide_the_past_the_booked_and_the_too_soon(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    t, slot_ids = await new_therapist(client, api_db, world, slots=3)
    now = dt.datetime.now(dt.UTC)
    soon = m.TherapistAvailability(
        institution_id=world.inst_a,
        therapist_id=t.id,
        starts_at=now + dt.timedelta(minutes=30),
        ends_at=now + dt.timedelta(minutes=90),
    )
    past = m.TherapistAvailability(
        institution_id=world.inst_a,
        therapist_id=t.id,
        starts_at=now - dt.timedelta(days=2),
        ends_at=now - dt.timedelta(days=2) + dt.timedelta(hours=1),
    )
    api_db.add_all([soon, past])
    await api_db.commit()
    listed = [x["id"] for x in (await s.get(f"/therapists/{t.id}/slots")).json()]
    assert listed == [str(i) for i in slot_ids]

    assert (
        await s.post("/me/appointments", {"availability_id": str(slot_ids[0])})
    ).status_code == 201
    listed = [x["id"] for x in (await s.get(f"/therapists/{t.id}/slots")).json()]
    assert listed == [str(i) for i in slot_ids[1:]]  # a booked slot disappears for everyone


# ---- booking --------------------------------------------------------------------------------


async def test_booking_creates_a_request_everyone_involved_can_see(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    t, slots = await new_therapist(client, api_db, world)
    r = await s.post(
        "/me/appointments", {"availability_id": str(slots[0]), "reason": "Exam pressure"}
    )
    assert r.status_code == 201, r.text
    appt = r.json()
    assert appt["status"] == "requested" and appt["can_cancel"] is True
    assert appt["student_id"] == str(s.id) and appt["therapist_id"] == str(t.id)
    assert appt["reason"] == "Exam pressure" and appt["mode"] == "video"

    mine = (await s.get("/me/appointments")).json()
    assert [a["id"] for a in mine] == [appt["id"]]
    assert [a["id"] for a in (await s.get("/me/appointments?upcoming=true")).json()] == [appt["id"]]
    assert (await s.get("/me/dashboard")).json()["upcoming_appointment"]["id"] == appt["id"]
    theirs = (await t.get("/therapist/appointments")).json()
    assert appt["id"] in {a["id"] for a in theirs}

    note = await api_db.scalar(
        select(m.Notification).where(
            m.Notification.user_id == t.id,
            m.Notification.type == NotificationType.APPOINTMENT_UPDATE,
        )
    )
    assert note is not None and note.payload["appointment_id"] == appt["id"]
    assert "Exam" not in str(note.payload) + note.title  # identifiers only, never the reason
    audited = await api_db.scalar(
        select(func.count())
        .select_from(m.AuditLog)
        .where(m.AuditLog.actor_id == s.id, m.AuditLog.action == "appointment.create")
    )
    assert audited == 1


async def test_reason_is_encrypted_and_private_to_the_parties(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    other = await new_student(client, api_db, world)
    t, slots = await new_therapist(client, api_db, world)
    await s.post(
        "/me/appointments", {"availability_id": str(slots[0]), "reason": "my secret worry"}
    )
    raw = await api_db.scalar(
        text("SELECT reason FROM therapy.appointments WHERE student_id = :s"), {"s": s.id}
    )
    assert raw is not None and b"secret" not in bytes(raw)
    assert (await other.get("/me/appointments")).json() == []


async def test_a_slot_can_only_be_taken_once(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    first = await new_student(client, api_db, world)
    second = await new_student(client, api_db, world)
    _, slots = await new_therapist(client, api_db, world)
    assert (
        await first.post("/me/appointments", {"availability_id": str(slots[0])})
    ).status_code == 201
    r = await second.post("/me/appointments", {"availability_id": str(slots[0])})
    assert r.status_code == 409 and "taken" in r.json()["detail"]
    assert (await second.get("/me/appointments")).json() == []


async def test_a_student_cannot_double_book_themselves(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    t1, slots1 = await new_therapist(client, api_db, world, slots=1)
    t2, slots2 = await new_therapist(client, api_db, world, slots=1)  # same hour, other therapist
    assert (
        await s.post("/me/appointments", {"availability_id": str(slots1[0])})
    ).status_code == 201
    r = await s.post("/me/appointments", {"availability_id": str(slots2[0])})
    assert r.status_code == 409 and "already have an appointment" in r.json()["detail"]
    assert t1.id != t2.id


async def test_booking_limits_and_rules(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    t, slots = await new_therapist(client, api_db, world, slots=5)
    for slot in slots[:3]:
        assert (await s.post("/me/appointments", {"availability_id": str(slot)})).status_code == 201
    r = await s.post("/me/appointments", {"availability_id": str(slots[3])})
    assert r.status_code == 409 and "3 upcoming" in r.json()["detail"]

    too_soon, _ = await new_therapist(
        client, api_db, world, slots=1, first_slot_in=dt.timedelta(minutes=30)
    )
    fresh = await new_student(client, api_db, world)
    soon_slot = await api_db.scalar(
        select(m.TherapistAvailability.id).where(
            m.TherapistAvailability.therapist_id == too_soon.id
        )
    )
    r = await fresh.post("/me/appointments", {"availability_id": str(soon_slot)})
    assert r.status_code == 422 and "too soon" in r.json()["detail"]
    assert (
        await fresh.post("/me/appointments", {"availability_id": "not-a-uuid"})
    ).status_code == 422
    assert (
        await fresh.post(
            "/me/appointments", {"availability_id": str(soon_slot), "reason": "x" * 1001}
        )
    ).status_code == 422
    assert t.id != too_soon.id


async def test_therapists_who_are_full_cannot_be_booked_by_new_students(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    _, slots = await new_therapist(client, api_db, world, accepting=False)
    r = await s.post("/me/appointments", {"availability_id": str(slots[0])})
    assert r.status_code == 403
    denied = await api_db.scalar(
        select(func.count())
        .select_from(m.AuditLog)
        .where(
            m.AuditLog.actor_id == s.id,
            m.AuditLog.action == "appointment.create",
            m.AuditLog.outcome == AuditOutcome.DENIED,
        )
    )
    assert denied == 1


async def test_booking_across_institutions_is_not_found(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    outsider = await new_student(client, api_db, world, other_tenant=True)
    _, slots = await new_therapist(client, api_db, world)
    r = await outsider.post("/me/appointments", {"availability_id": str(slots[0])})
    assert r.status_code == 404


# ---- cancelling and confirming --------------------------------------------------------------


async def test_cancelling_frees_the_slot(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    other = await new_student(client, api_db, world)
    t, slots = await new_therapist(client, api_db, world)
    appt = (await s.post("/me/appointments", {"availability_id": str(slots[0])})).json()
    r = await s.patch(f"/me/appointments/{appt['id']}", {"status": "cancelled"})
    assert (
        r.status_code == 200
        and r.json()["status"] == "cancelled"
        and r.json()["can_cancel"] is False
    )
    assert (await s.get("/me/dashboard")).json()["upcoming_appointment"] is None
    assert (
        await s.patch(f"/me/appointments/{appt['id']}", {"status": "cancelled"})
    ).status_code == 409
    assert (
        await other.post("/me/appointments", {"availability_id": str(slots[0])})
    ).status_code == 201
    row = await api_db.get(m.Appointment, appt["id"], populate_existing=True)
    assert row is not None and row.cancelled_by == s.id and row.cancelled_at is not None
    assert t.id == row.therapist_id


async def test_students_can_only_cancel_their_own_appointments(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    owner = await new_student(client, api_db, world)
    other = await new_student(client, api_db, world)
    outsider = await new_student(client, api_db, world, other_tenant=True)
    _, slots = await new_therapist(client, api_db, world)
    appt = (await owner.post("/me/appointments", {"availability_id": str(slots[0])})).json()
    for intruder in (other, outsider):
        r = await intruder.patch(f"/me/appointments/{appt['id']}", {"status": "cancelled"})
        assert r.status_code == 404
    row = await api_db.get(m.Appointment, appt["id"], populate_existing=True)
    assert row is not None and row.status is AppointmentStatus.REQUESTED
    # the only change a student can make is to cancel
    assert (
        await owner.patch(f"/me/appointments/{appt['id']}", {"status": "confirmed"})
    ).status_code == 422


async def test_a_past_appointment_cannot_be_cancelled(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    t, slots = await new_therapist(client, api_db, world)
    appt = (await s.post("/me/appointments", {"availability_id": str(slots[0])})).json()
    row = await api_db.get(m.Appointment, appt["id"])
    assert row is not None
    row.starts_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
    row.ends_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    await api_db.commit()
    assert (
        await s.patch(f"/me/appointments/{appt['id']}", {"status": "cancelled"})
    ).status_code == 409
    mine = (await s.get("/me/appointments?upcoming=false")).json()
    assert mine[0]["can_cancel"] is False
    assert t.id


async def test_confirming_the_first_appointment_puts_the_student_on_the_care_team(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    t, slots = await new_therapist(client, api_db, world)
    appt = (await s.post("/me/appointments", {"availability_id": str(slots[0])})).json()
    assert (await s.get(f"/therapists/{t.id}")).json()["on_my_care_team"] is False
    assert (await t.get("/students")).json() == []

    assert (
        await t.patch(f"/appointments/{appt['id']}", {"status": "confirmed"})
    ).status_code == 200
    assert (await s.get(f"/therapists/{t.id}")).json()["on_my_care_team"] is True
    assert [x["student_id"] for x in (await t.get("/students")).json()] == [str(s.id)]
    # being on the care team does not by itself share wellbeing data: that needs consent
    assert (await t.get(f"/students/{s.id}/mood-entries")).status_code == 403
