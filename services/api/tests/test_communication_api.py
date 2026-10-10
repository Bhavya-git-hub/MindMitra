"""The therapist communication system through the API: booking under contention, double-booking
prevention, rescheduling, cancellation with reasons, who may reach what, live messaging events
and the notification inbox."""

import asyncio
import datetime as dt
import uuid
from collections.abc import Iterator
from urllib.parse import urlencode

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AppointmentStatus,
    CancellationReason,
    NotificationType,
    SessionMode,
)
from app.infrastructure.db.ids import uuid7
from app.infrastructure.events import Event, set_broker
from app.infrastructure.realtime_hub import Connection, Hub
from tests.api_world import World
from tests.student_helpers import Session, new_student, new_therapist, sign_in
from tests.therapist_helpers import care_pair, due_appointment, end_care_link

pytestmark = pytest.mark.asyncio


@pytest.fixture
def hub(api_app: FastAPI) -> Iterator[Hub]:
    """The API's real-time hub, wired as the event broker for this test."""
    h: Hub = api_app.state.mm.hub
    set_broker(h)
    yield h
    set_broker(h)


def drain(conn: Connection) -> list[Event]:
    out: list[Event] = []
    while not conn.queue.empty():
        out.append(conn.queue.get_nowait())
    return out


async def notifications_for(
    db: AsyncSession, user_id: uuid.UUID, appointment_id: uuid.UUID
) -> list[m.Notification]:
    db.expire_all()
    rows = await db.scalars(
        select(m.Notification)
        .where(
            m.Notification.user_id == user_id,
            m.Notification.payload["appointment_id"].astext == str(appointment_id),
        )
        .order_by(m.Notification.created_at)
    )
    return list(rows)


async def book(s: Session, slot: uuid.UUID) -> dict[str, object]:
    r = await s.post("/me/appointments", {"availability_id": str(slot)})
    assert r.status_code == 201, r.text
    body: dict[str, object] = r.json()
    return body


# ---- booking and double-booking prevention ---------------------------------------------------


async def test_two_students_racing_for_one_slot_get_exactly_one_booking(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t, slots = await new_therapist(client, api_db, world)
    a = await new_student(client, api_db, world)
    b = await new_student(client, api_db, world)
    body = {"availability_id": str(slots[0])}
    ra, rb = await asyncio.gather(
        a.post("/me/appointments", body), b.post("/me/appointments", body)
    )
    assert sorted([ra.status_code, rb.status_code]) == [201, 409]
    live = await api_db.scalar(
        select(func.count())
        .select_from(m.Appointment)
        .where(
            m.Appointment.availability_id == slots[0],
            m.Appointment.status.in_([AppointmentStatus.REQUESTED, AppointmentStatus.CONFIRMED]),
        )
    )
    assert live == 1


async def test_a_booking_shows_its_new_fields_and_tells_the_therapist(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, hub: Hub
) -> None:
    t, slots = await new_therapist(client, api_db, world)
    s = await new_student(client, api_db, world)
    conn = hub.register(t.id)
    assert conn is not None
    try:
        appt = await book(s, slots[0])
        assert appt["can_reschedule"] is True and appt["reschedule_count"] == 0
        assert appt["session_status"] is None and appt["cancel_reason"] is None
        events = drain(conn)
    finally:
        hub.unregister(conn)
    kinds = {e["type"] for e in events}
    assert kinds == {"notification", "appointment"}
    assert {"type": "appointment", "appointment_id": appt["id"], "event": "requested"} in events
    notes = await notifications_for(api_db, t.id, uuid.UUID(str(appt["id"])))
    assert [n.type for n in notes] == [NotificationType.APPOINTMENT_UPDATE]


async def test_rescheduling_cannot_take_a_time_another_student_holds(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t, slots = await new_therapist(client, api_db, world)
    a = await new_student(client, api_db, world)
    b = await new_student(client, api_db, world)
    await book(a, slots[0])
    mine = await book(b, slots[1])
    r = await b.post(
        f"/me/appointments/{mine['id']}/reschedule", {"availability_id": str(slots[0])}
    )
    assert r.status_code == 409
    row = await api_db.get(m.Appointment, uuid.UUID(str(mine["id"])))
    assert row is not None and row.availability_id == slots[1] and row.reschedule_count == 0


async def test_rescheduling_cannot_double_book_the_student(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    # Both therapists' slots start at the same hours, so slot 0 of one overlaps slot 0 of the other.
    t1, slots1 = await new_therapist(client, api_db, world)
    t2, slots2 = await new_therapist(client, api_db, world)
    s = await new_student(client, api_db, world)
    await book(s, slots1[0])
    other = await book(s, slots2[1])
    r = await s.post(
        f"/me/appointments/{other['id']}/reschedule", {"availability_id": str(slots2[0])}
    )
    assert r.status_code == 409
    assert "already have an appointment" in r.json()["detail"]


async def test_a_therapist_cannot_be_double_booked_by_a_direct_insert(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """The database refuses overlap even if a bug skipped the use case."""
    pair = await care_pair(client, api_db, world, mood=False)
    other = await new_student(client, api_db, world)
    first = await api_db.get(m.Appointment, await due_appointment(api_db, pair))
    assert first is not None
    api_db.add(
        m.Appointment(
            id=uuid7(),
            institution_id=first.institution_id,
            student_id=other.id,
            therapist_id=pair.therapist.id,
            starts_at=first.starts_at + dt.timedelta(minutes=10),
            ends_at=first.ends_at + dt.timedelta(minutes=10),
            mode=SessionMode.VIDEO,
            status=AppointmentStatus.REQUESTED,
        )
    )
    with pytest.raises(Exception, match="ex_appointments_therapist_no_overlap"):
        await api_db.commit()
    await api_db.rollback()


# ---- rescheduling -----------------------------------------------------------------------------


async def test_a_student_reschedule_frees_the_old_time_and_asks_the_therapist_again(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, hub: Hub
) -> None:
    t, slots = await new_therapist(client, api_db, world)
    s = await new_student(client, api_db, world)
    appt = await book(s, slots[0])
    assert (
        await t.patch(f"/appointments/{appt['id']}", {"status": "confirmed"})
    ).status_code == 200
    conn = hub.register(t.id)
    assert conn is not None
    try:
        r = await s.post(
            f"/me/appointments/{appt['id']}/reschedule", {"availability_id": str(slots[1])}
        )
        events = drain(conn)
    finally:
        hub.unregister(conn)
    assert r.status_code == 200, r.text
    moved = r.json()
    assert moved["status"] == "requested"  # the therapist confirms the new time
    assert moved["reschedule_count"] == 1 and moved["rescheduled_at"] is not None
    slot1 = await api_db.get(m.TherapistAvailability, slots[1])
    assert slot1 is not None and moved["starts_at"].startswith(slot1.starts_at.strftime("%Y-%m-%d"))
    open_ids = [x["id"] for x in (await s.get(f"/therapists/{t.id}/slots")).json()]
    assert str(slots[0]) in open_ids and str(slots[1]) not in open_ids
    assert {
        "type": "appointment",
        "appointment_id": appt["id"],
        "event": "rescheduled_by_student",
    } in events
    notes = await notifications_for(api_db, t.id, uuid.UUID(str(appt["id"])))
    assert notes[-1].payload["event"] == "rescheduled_by_student"
    listed = (await t.get("/therapist/appointments")).json()
    row = next(x for x in listed if x["id"] == appt["id"])
    assert row["reschedule_count"] == 1 and row["status"] == "requested"


async def test_a_therapist_reschedule_keeps_the_confirmation_and_tells_the_student(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t, slots = await new_therapist(client, api_db, world)
    s = await new_student(client, api_db, world)
    appt = await book(s, slots[0])
    await t.patch(f"/appointments/{appt['id']}", {"status": "confirmed"})
    r = await t.post(
        f"/therapist/appointments/{appt['id']}/reschedule", {"availability_id": str(slots[2])}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed" and r.json()["reschedule_count"] == 1
    assert r.json()["student_name"]
    notes = await notifications_for(api_db, s.id, uuid.UUID(str(appt["id"])))
    assert notes[-1].title == "Your therapist moved your appointment"
    assert notes[-1].payload == {"appointment_id": appt["id"], "event": "rescheduled_by_therapist"}
    mine = (await s.get("/me/appointments")).json()
    assert next(x for x in mine if x["id"] == appt["id"])["reschedule_count"] == 1


async def test_reschedule_rules(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t, slots = await new_therapist(client, api_db, world, slots=6)
    other_t, other_slots = await new_therapist(client, api_db, world)
    s = await new_student(client, api_db, world)
    appt = await book(s, slots[0])
    path = f"/me/appointments/{appt['id']}/reschedule"
    # the same time, another therapist's time, a time that does not exist
    assert (await s.post(path, {"availability_id": str(slots[0])})).status_code == 422
    assert (await s.post(path, {"availability_id": str(other_slots[0])})).status_code == 404
    assert (await s.post(path, {"availability_id": str(uuid.uuid4())})).status_code == 404
    # a time too soon
    soon = m.TherapistAvailability(
        id=uuid7(),
        institution_id=world.inst_a,
        therapist_id=t.id,
        starts_at=dt.datetime.now(dt.UTC) + dt.timedelta(minutes=30),
        ends_at=dt.datetime.now(dt.UTC) + dt.timedelta(minutes=80),
        mode=SessionMode.VIDEO,
    )
    api_db.add(soon)
    await api_db.commit()
    assert (await s.post(path, {"availability_id": str(soon.id)})).status_code == 422
    # three moves, then no more
    for slot in slots[1:4]:
        assert (await s.post(path, {"availability_id": str(slot)})).status_code == 200
    r = await s.post(path, {"availability_id": str(slots[4])})
    assert r.status_code == 409 and "cancel it and book a new one" in r.json()["detail"]
    listed = next(x for x in (await s.get("/me/appointments")).json() if x["id"] == appt["id"])
    assert listed["can_reschedule"] is False and listed["can_cancel"] is True
    # a cancelled appointment cannot be moved
    await s.patch(f"/me/appointments/{appt['id']}", {"status": "cancelled"})
    assert (await s.post(path, {"availability_id": str(slots[5])})).status_code == 409


async def test_a_past_appointment_cannot_be_moved(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world, mood=False)
    appt = await due_appointment(api_db, pair, starts_in=-dt.timedelta(hours=2))
    slots = (await pair.student.get(f"/therapists/{pair.therapist.id}/slots")).json()
    r = await pair.therapist.post(
        f"/therapist/appointments/{appt}/reschedule", {"availability_id": slots[0]["id"]}
    )
    assert r.status_code == 409


# ---- cancellation -----------------------------------------------------------------------------


async def test_a_student_can_cancel_with_a_reason(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, hub: Hub
) -> None:
    t, slots = await new_therapist(client, api_db, world)
    s = await new_student(client, api_db, world)
    appt = await book(s, slots[0])
    conn = hub.register(t.id)
    assert conn is not None
    try:
        r = await s.patch(
            f"/me/appointments/{appt['id']}", {"status": "cancelled", "reason": "feeling_better"}
        )
        events = drain(conn)
    finally:
        hub.unregister(conn)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled" and r.json()["cancel_reason"] == "feeling_better"
    assert r.json()["can_reschedule"] is False
    row = await api_db.get(m.Appointment, uuid.UUID(str(appt["id"])))
    assert row is not None and row.cancel_reason is CancellationReason.FEELING_BETTER
    notes = await notifications_for(api_db, t.id, row.id)
    assert notes[-1].payload["event"] == "cancelled_by_student"
    assert "feeling" not in notes[-1].title.lower()  # the reason stays out of the notification
    assert any(e.get("event") == "cancelled_by_student" for e in events)


async def test_a_reason_is_optional_and_must_come_from_the_list(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t, slots = await new_therapist(client, api_db, world)
    s = await new_student(client, api_db, world)
    a1 = await book(s, slots[0])
    bad = await s.patch(
        f"/me/appointments/{a1['id']}", {"status": "cancelled", "reason": "I hate this"}
    )
    assert bad.status_code == 422
    ok = await s.patch(f"/me/appointments/{a1['id']}", {"status": "cancelled"})
    assert ok.status_code == 200 and ok.json()["cancel_reason"] is None


async def test_a_therapist_can_cancel_with_a_reason_and_the_student_is_told(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t, slots = await new_therapist(client, api_db, world)
    s = await new_student(client, api_db, world)
    appt = await book(s, slots[0])
    wrong = await t.patch(
        f"/appointments/{appt['id']}",
        {"status": "confirmed", "cancel_reason": "therapist_unavailable"},
    )
    assert wrong.status_code == 422  # a reason only goes with cancelling
    r = await t.patch(
        f"/appointments/{appt['id']}",
        {"status": "cancelled", "cancel_reason": "therapist_unavailable"},
    )
    assert r.status_code == 200, r.text
    mine = next(x for x in (await s.get("/me/appointments")).json() if x["id"] == appt["id"])
    assert mine["status"] == "cancelled" and mine["cancel_reason"] == "therapist_unavailable"
    notes = await notifications_for(api_db, s.id, uuid.UUID(str(appt["id"])))
    assert notes[-1].payload["event"] == "cancelled"


# ---- session status ---------------------------------------------------------------------------


async def test_the_student_sees_the_session_start_and_finish(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, hub: Hub
) -> None:
    pair = await care_pair(client, api_db, world, mood=False)
    appt = await due_appointment(api_db, pair)
    conn = hub.register(pair.student.id)
    assert conn is not None
    try:
        r = await pair.therapist.post(f"/therapist/appointments/{appt}/session")
        assert r.status_code == 201
        mine = (await pair.student.get("/me/appointments")).json()
        assert next(x for x in mine if x["id"] == str(appt))["session_status"] == "in_progress"
        done = await pair.therapist.patch(
            f"/therapist/sessions/{r.json()['id']}", {"status": "completed"}
        )
        assert done.status_code == 200
        events = drain(conn)
    finally:
        hub.unregister(conn)
    mine = (await pair.student.get("/me/appointments")).json()
    row = next(x for x in mine if x["id"] == str(appt))
    assert row["session_status"] == "completed" and row["status"] == "completed"
    notes = await notifications_for(api_db, pair.student.id, appt)
    assert notes[-1].payload["event"] == "session_started"
    assert [e["event"] for e in events if e["type"] == "appointment"] == [
        "session_started",
        "session_completed",
    ]


# ---- authorization ----------------------------------------------------------------------------


async def test_teachers_and_administrators_cannot_reach_conversations_or_appointments(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world, mood=False)
    await pair.student.post(f"/me/conversations/{pair.therapist.id}/messages", {"body": "private"})
    appt = (await pair.student.get("/me/appointments")).json()[0]["id"]
    slot = (await pair.student.get(f"/therapists/{pair.therapist.id}/slots")).json()[0]["id"]
    for actor in (world.teacher, world.admin):
        who = await sign_in(client, actor, world.password)
        for other in (pair.student.id, pair.therapist.id):
            assert (await who.get(f"/me/conversations/{other}/messages")).status_code == 403
            assert (
                await who.post(f"/me/conversations/{other}/messages", {"body": "x"})
            ).status_code == 403
            assert (await who.post(f"/me/conversations/{other}/read")).status_code == 403
        assert (await who.get("/me/conversations")).status_code == 403
        assert (
            await who.post(f"/me/appointments/{appt}/reschedule", {"availability_id": slot})
        ).status_code == 403
        assert (
            await who.post(f"/therapist/appointments/{appt}/reschedule", {"availability_id": slot})
        ).status_code == 403
        assert (
            await who.patch(f"/me/appointments/{appt}", {"status": "cancelled"})
        ).status_code == 403


async def test_only_the_two_people_in_an_appointment_can_move_it(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t, slots = await new_therapist(client, api_db, world)
    s = await new_student(client, api_db, world)
    appt = await book(s, slots[0])
    stranger = await new_student(client, api_db, world)
    other_t, _ = await new_therapist(client, api_db, world)
    outsider_t, _ = await new_therapist(client, api_db, world, other_tenant=True)
    body = {"availability_id": str(slots[1])}
    assert (
        await stranger.post(f"/me/appointments/{appt['id']}/reschedule", body)
    ).status_code == 404
    for therapist in (other_t, outsider_t):
        assert (
            await therapist.post(f"/therapist/appointments/{appt['id']}/reschedule", body)
        ).status_code == 404
    unverified, _ = await new_therapist(client, api_db, world, verified=False, slots=0)
    assert (
        await unverified.post(f"/therapist/appointments/{appt['id']}/reschedule", body)
    ).status_code == 403
    row = await api_db.get(m.Appointment, uuid.UUID(str(appt["id"])))
    assert row is not None and row.reschedule_count == 0


# ---- messaging ---------------------------------------------------------------------------------


async def test_a_message_reaches_the_other_persons_open_tabs_as_ids_only(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, hub: Hub
) -> None:
    pair = await care_pair(client, api_db, world, mood=False)
    to_t = hub.register(pair.therapist.id)
    to_s = hub.register(pair.student.id)
    bystander = hub.register(world.other_student.user_id)
    assert to_t and to_s and bystander
    try:
        r = await pair.student.post(
            f"/me/conversations/{pair.therapist.id}/messages", {"body": "a very private line"}
        )
        assert r.status_code == 201
        msg_id = r.json()["message"]["id"]
        therapist_events = drain(to_t)
        student_events = drain(to_s)
        assert drain(bystander) == []
        read = await pair.therapist.post(f"/me/conversations/{pair.student.id}/read")
        assert read.json()["marked_read"] == 1
        receipts = drain(to_s)
    finally:
        for c in (to_t, to_s, bystander):
            hub.unregister(c)
    assert {
        "type": "message",
        "with": str(pair.student.id),
        "message_id": msg_id,
    } in therapist_events
    assert any(e["type"] == "notification" for e in therapist_events)
    assert student_events == [
        {"type": "message", "with": str(pair.therapist.id), "message_id": msg_id}
    ]
    assert receipts == [{"type": "message_read", "with": str(pair.therapist.id)}]
    assert "private" not in repr(therapist_events + student_events + receipts)


async def test_conversation_history_after_the_care_team_ends(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world, mood=False)
    await pair.student.post(f"/me/conversations/{pair.therapist.id}/messages", {"body": "one"})
    await pair.therapist.post(f"/me/conversations/{pair.student.id}/messages", {"body": "two"})
    await end_care_link(api_db, pair)
    history = await pair.student.get(f"/me/conversations/{pair.therapist.id}/messages")
    assert history.status_code == 200
    assert [x["body"] for x in history.json()] == ["one", "two"]
    assert [x["mine"] for x in history.json()] == [True, False]
    assert (
        await pair.student.post(f"/me/conversations/{pair.therapist.id}/messages", {"body": "3"})
    ).status_code == 404
    assert (
        await pair.therapist.get(f"/me/conversations/{pair.student.id}/messages")
    ).status_code == 404
    # a student with no history with a therapist still finds nothing there
    s2 = await new_student(client, api_db, world)
    assert (await s2.get(f"/me/conversations/{pair.therapist.id}/messages")).status_code == 404


# ---- the notification inbox --------------------------------------------------------------------


async def test_the_inbox_is_private_and_can_be_marked_read(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, hub: Hub
) -> None:
    pair = await care_pair(client, api_db, world, mood=False)
    for _ in range(2):
        await pair.student.post(f"/me/conversations/{pair.therapist.id}/messages", {"body": "hi"})
    box = (await pair.therapist.get("/me/notifications")).json()
    assert box["unread"] >= 2
    newest = box["items"][0]
    assert newest["type"] == "new_message" and newest["read_at"] is None
    assert set(newest["payload"]) == {"message_id"}
    assert (await pair.therapist.get("/me/notifications/unread-count")).json()["unread"] == box[
        "unread"
    ]
    only_unread = (await pair.therapist.get("/me/notifications?unread=true")).json()
    assert all(x["read_at"] is None for x in only_unread["items"])

    # nobody else can mark it read, whatever their role
    for intruder in (
        pair.student,
        await sign_in(client, world.teacher, world.password),
        await sign_in(client, world.admin, world.password),
    ):
        assert (await intruder.post(f"/me/notifications/{newest['id']}/read")).status_code == 404
        mine = (await intruder.get("/me/notifications")).json()["items"]
        assert newest["id"] not in [x["id"] for x in mine]

    conn = hub.register(pair.therapist.id)
    assert conn is not None
    try:
        assert (
            await pair.therapist.post(f"/me/notifications/{newest['id']}/read")
        ).status_code == 204
        after = (await pair.therapist.get("/me/notifications/unread-count")).json()["unread"]
        assert after == box["unread"] - 1
        cleared = await pair.therapist.post("/me/notifications/read-all")
        assert cleared.json()["marked_read"] == after
        assert (await pair.therapist.get("/me/notifications/unread-count")).json()["unread"] == 0
        events = drain(conn)
    finally:
        hub.unregister(conn)
    assert [e["type"] for e in events] == ["notifications_read", "notifications_read"]


async def test_notification_paging_and_limits(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world, mood=False)
    for i in range(3):
        await pair.student.post(f"/me/conversations/{pair.therapist.id}/messages", {"body": f"{i}"})
    first = (await pair.therapist.get("/me/notifications?limit=2")).json()["items"]
    assert len(first) == 2
    rest = (
        await pair.therapist.get(
            "/me/notifications?" + urlencode({"limit": 2, "before": first[-1]["created_at"]})
        )
    ).json()["items"]
    assert rest and rest[0]["id"] not in {x["id"] for x in first}
    too_many = await pair.therapist.get("/me/notifications?limit=101")
    assert too_many.status_code == 422


async def test_teachers_get_their_own_notifications_too(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    teacher = await sign_in(client, world.teacher, world.password)
    r = await teacher.get("/me/notifications")
    assert r.status_code == 200
    assert all(set(x["payload"]) <= {"request_id", "event"} for x in r.json()["items"])
