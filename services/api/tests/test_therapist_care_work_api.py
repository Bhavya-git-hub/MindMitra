"""Sessions, notes, risk alerts, follow-ups, recommendations and secure messaging."""

import datetime as dt

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AppointmentStatus,
    NotificationType,
    RecommendationSource,
)
from tests.api_world import World
from tests.student_helpers import new_student
from tests.therapist_helpers import (
    care_pair,
    due_appointment,
    end_care_link,
    fresh_therapist,
    make_alert,
    started_session,
)

pytestmark = pytest.mark.asyncio


# ---- sessions ------------------------------------------------------------------------------


async def test_a_session_is_started_completed_and_closes_the_appointment(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    appt = await due_appointment(api_db, pair)
    r = await pair.therapist.post(f"/therapist/appointments/{appt}/session")
    assert r.status_code == 201, r.text
    session = r.json()
    assert session["status"] == "in_progress" and session["has_note"] is False
    assert session["student_id"] == str(pair.student.id)

    again = await pair.therapist.post(f"/therapist/appointments/{appt}/session")
    assert again.json()["id"] == session["id"]  # starting twice is harmless

    done = await pair.therapist.patch(
        f"/therapist/sessions/{session['id']}", {"status": "completed"}
    )
    assert done.status_code == 200 and done.json()["status"] == "completed"
    assert done.json()["ended_at"] and done.json()["duration_minutes"] is not None
    row = await api_db.get(m.Appointment, appt)
    await api_db.refresh(row)
    assert row is not None and row.status is AppointmentStatus.COMPLETED

    closed = await pair.therapist.patch(
        f"/therapist/sessions/{session['id']}", {"status": "abandoned"}
    )
    assert closed.status_code == 422  # already closed
    listing = (await pair.therapist.get("/therapist/sessions?status=completed")).json()
    assert [x["id"] for x in listing] == [session["id"]]
    assert (await pair.therapist.get("/therapist/appointments?status=completed")).json()[0][
        "session_id"
    ] == session["id"]


async def test_a_session_can_be_abandoned_without_completing_the_appointment(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    sid = await started_session(api_db, pair)
    r = await pair.therapist.patch(f"/therapist/sessions/{sid}", {"status": "abandoned"})
    assert r.status_code == 200 and r.json()["status"] == "abandoned"
    assert (
        await pair.therapist.patch(f"/therapist/sessions/{sid}", {"status": "scheduled"})
    ).status_code == 422


@pytest.mark.parametrize(
    ("starts_in", "status"),
    [
        (dt.timedelta(hours=2), AppointmentStatus.CONFIRMED),  # too early
        (dt.timedelta(days=-3), AppointmentStatus.CONFIRMED),  # long over
        (dt.timedelta(minutes=5), AppointmentStatus.REQUESTED),  # not confirmed
        (dt.timedelta(minutes=5), AppointmentStatus.CANCELLED),
    ],
)
async def test_a_session_only_starts_for_a_confirmed_appointment_that_is_due(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    starts_in: dt.timedelta,
    status: AppointmentStatus,
) -> None:
    pair = await care_pair(client, api_db, world)
    appt = await due_appointment(api_db, pair, starts_in=starts_in, status=status)
    r = await pair.therapist.post(f"/therapist/appointments/{appt}/session")
    assert r.status_code == 422, r.text


async def test_only_the_appointments_therapist_can_start_or_close_its_session(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    other = await fresh_therapist(client, api_db, world)
    sid = await started_session(api_db, pair)
    row = await api_db.get(m.TherapySession, sid)
    assert row is not None
    appt = row.appointment_id
    r = await other.post(f"/therapist/appointments/{appt}/session")
    assert r.status_code in (403, 404)
    assert (
        await other.patch(f"/therapist/sessions/{sid}", {"status": "completed"})
    ).status_code in (403, 404)
    assert (await other.get("/therapist/sessions")).json() == []
    assert (await pair.student.post(f"/therapist/appointments/{appt}/session")).status_code == 403


# ---- notes ---------------------------------------------------------------------------------


async def test_notes_are_versioned_and_each_save_keeps_the_previous_version(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    sid = await started_session(api_db, pair)
    path = f"/therapist/sessions/{sid}/note"
    first = await pair.therapist.get(path)
    assert first.status_code == 200 and first.json() is None  # nothing written yet

    v1 = await pair.therapist.put(path, {"body": "First draft."})
    assert v1.status_code == 200, v1.text
    assert v1.json()["version"] == 1 and v1.json()["latest"] is True
    v2 = await pair.therapist.put(path, {"body": "Second draft."})
    assert v2.json()["version"] == 2 and [v["version"] for v in v2.json()["versions"]] == [1, 2]

    latest = (await pair.therapist.get(path)).json()
    assert latest["body"] == "Second draft." and latest["latest"] is True
    old = (await pair.therapist.get(path + "?version=1")).json()
    assert old["body"] == "First draft." and old["latest"] is False
    assert (await pair.therapist.get(path + "?version=9")).status_code == 404

    rows = list(
        await api_db.scalars(
            select(m.TherapyNote)
            .where(m.TherapyNote.session_id == sid)
            .order_by(m.TherapyNote.version)
        )
    )
    assert [r.body for r in rows] == ["First draft.", "Second draft."]
    assert rows[0].locked_at is not None and rows[1].locked_at is None  # superseded, not edited

    listing = (await pair.therapist.get("/therapist/sessions")).json()
    assert listing[0]["has_note"] is True


async def test_note_content_never_reaches_the_audit_log_or_responses_cache(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    sid = await started_session(api_db, pair)
    secret = "SECRET-CLINICAL-TEXT-7731"
    put = await pair.therapist.put(f"/therapist/sessions/{sid}/note", {"body": secret})
    got = await pair.therapist.get(f"/therapist/sessions/{sid}/note")
    for r in (put, got):
        assert "no-store" in r.headers["cache-control"]
    events = list(await api_db.scalars(select(m.AuditLog).where(m.AuditLog.resource_id == sid)))
    assert {"therapy_note.write", "therapy_note.read"} <= {e.action for e in events}
    assert secret not in str([(e.details, e.reason) for e in events])


@pytest.mark.parametrize("body", ["", "   ", "x" * 20001])
async def test_note_validation(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, body: str
) -> None:
    pair = await care_pair(client, api_db, world)
    sid = await started_session(api_db, pair)
    assert (
        await pair.therapist.put(f"/therapist/sessions/{sid}/note", {"body": body})
    ).status_code == 422


# ---- risk alerts ---------------------------------------------------------------------------


async def test_alerts_follow_a_clear_path_and_are_only_for_my_students(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    other = await fresh_therapist(client, api_db, world)
    alert_id = await make_alert(api_db, pair, excerpt="wants to talk to someone")

    alerts = (await pair.therapist.get("/therapist/alerts")).json()
    assert [a["id"] for a in alerts] == [str(alert_id)]
    a = alerts[0]
    assert a["category_label"] == "Seems very distressed" and a["source_label"] == "Asked for help"
    assert "not a diagnosis" in a["disclaimer"] and a["assigned_to_me"] is False
    assert (await other.get("/therapist/alerts")).json() == []
    url = f"/therapist/alerts/{alert_id}"
    assert (await other.patch(url, {"action": "acknowledge"})).status_code in (403, 404)

    assert (await pair.therapist.patch(url, {"action": "start"})).status_code == 422  # ack first
    ack = await pair.therapist.patch(url, {"action": "acknowledge"})
    assert ack.status_code == 200 and ack.json()["status"] == "acknowledged"
    assert ack.json()["assigned_to_me"] is True  # acknowledging an unassigned alert claims it
    assert (await pair.therapist.patch(url, {"action": "acknowledge"})).status_code == 422
    assert (await pair.therapist.patch(url, {"action": "start"})).json()["status"] == "in_progress"
    assert (
        await pair.therapist.patch(url, {"action": "resolve"})
    ).status_code == 422  # needs outcome
    done = await pair.therapist.patch(url, {"action": "resolve", "outcome": "contacted_student"})
    assert done.json()["status"] == "resolved" and done.json()["outcome"] == "contacted_student"
    assert (await pair.therapist.get("/therapist/alerts")).json() == []
    closed = (await pair.therapist.get("/therapist/alerts?closed=true")).json()
    assert [x["id"] for x in closed] == [str(alert_id)]
    # once claimed, other therapists on the same care team no longer see or act on it
    assert (await other.patch(url, {"action": "acknowledge"})).status_code in (403, 404)


async def test_an_alert_assigned_to_someone_else_is_invisible_even_on_the_same_care_team(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    alert_id = await make_alert(api_db, pair, assigned=True)
    assert len((await pair.therapist.get("/therapist/alerts")).json()) == 1
    other = await fresh_therapist(client, api_db, world)
    await end_care_link(api_db, pair)
    # the link has ended, but the alert is still assigned to this therapist, who must act on it
    assert (
        await pair.therapist.patch(f"/therapist/alerts/{alert_id}", {"action": "acknowledge"})
    ).status_code == 200
    assert (await other.get("/therapist/alerts")).json() == []


async def test_alert_actions_are_audited_without_the_excerpt(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    alert_id = await make_alert(api_db, pair, excerpt="EXCERPT-NOT-FOR-LOGS")
    await pair.therapist.get("/therapist/alerts")
    await pair.therapist.patch(f"/therapist/alerts/{alert_id}", {"action": "acknowledge"})
    events = list(
        await api_db.scalars(select(m.AuditLog).where(m.AuditLog.actor_id == pair.therapist.id))
    )
    assert {"risk_alert.list", "risk_alert.update"} <= {e.action for e in events}
    assert "EXCERPT" not in str([e.details for e in events])


async def test_non_therapists_cannot_see_or_act_on_alerts(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    alert_id = await make_alert(api_db, pair)
    for who in (pair.student,):
        assert (await who.get("/therapist/alerts")).status_code == 403
        assert (
            await who.patch(f"/therapist/alerts/{alert_id}", {"action": "acknowledge"})
        ).status_code == 403


# ---- follow-ups ----------------------------------------------------------------------------


async def test_follow_up_lifecycle(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    due = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    r = await pair.therapist.post(
        "/therapist/follow-ups",
        {
            "student_id": str(pair.student.id),
            "kind": "check_in",
            "due_on": due,
            "note": "Ask about sleep",
        },
    )
    assert r.status_code == 201, r.text
    fu = r.json()
    assert fu["status"] == "open" and fu["overdue"] is False and fu["note"] == "Ask about sleep"

    moved = await pair.therapist.patch(
        f"/therapist/follow-ups/{fu['id']}",
        {"due_on": (dt.date.today() + dt.timedelta(days=5)).isoformat(), "note": "Ask about exams"},
    )
    assert moved.json()["note"] == "Ask about exams"
    done = await pair.therapist.patch(f"/therapist/follow-ups/{fu['id']}", {"status": "done"})
    assert done.json()["status"] == "done" and done.json()["completed_at"]
    reopened = await pair.therapist.patch(f"/therapist/follow-ups/{fu['id']}", {"status": "open"})
    assert reopened.json()["completed_at"] is None

    assert [
        x["id"] for x in (await pair.therapist.get("/therapist/follow-ups?status=open")).json()
    ] == [fu["id"]]
    by_student = f"/therapist/follow-ups?student_id={pair.student.id}"
    assert len((await pair.therapist.get(by_student)).json()) == 1
    d = (await pair.therapist.get("/therapist/dashboard")).json()
    assert d["follow_ups_due_today"] == 0 and d["follow_ups_overdue"] == 0


async def test_overdue_follow_ups_are_flagged(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    fu = (
        await pair.therapist.post(
            "/therapist/follow-ups",
            {
                "student_id": str(pair.student.id),
                "kind": "book_session",
                "due_on": dt.date.today().isoformat(),
            },
        )
    ).json()
    row = await api_db.get(m.FollowUp, fu["id"])
    assert row is not None
    row.due_on = dt.date.today() - dt.timedelta(days=2)
    await api_db.commit()
    listed = (await pair.therapist.get("/therapist/follow-ups")).json()
    assert listed[0]["overdue"] is True
    assert (await pair.therapist.get("/therapist/dashboard")).json()["follow_ups_overdue"] == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"due_on": (dt.date.today() - dt.timedelta(days=5)).isoformat()},
        {"due_on": (dt.date.today() + dt.timedelta(days=500)).isoformat()},
        {"kind": "something-else"},
        {"note": "x" * 1001},
    ],
)
async def test_follow_up_validation(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, patch: dict[str, str]
) -> None:
    pair = await care_pair(client, api_db, world)
    body = {
        "student_id": str(pair.student.id),
        "kind": "check_in",
        "due_on": (dt.date.today() + dt.timedelta(days=2)).isoformat(),
        **patch,
    }
    assert (await pair.therapist.post("/therapist/follow-ups", body)).status_code == 422


async def test_follow_ups_are_private_to_their_therapist_and_tied_to_my_students(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    other = await fresh_therapist(client, api_db, world)
    stranger = await new_student(client, api_db, world)
    due = (dt.date.today() + dt.timedelta(days=2)).isoformat()
    body = {
        "student_id": str(pair.student.id),
        "kind": "referral",
        "due_on": due,
        "note": "FU-PRIVATE",
    }
    fu = (await pair.therapist.post("/therapist/follow-ups", body)).json()

    assert (await other.post("/therapist/follow-ups", body)).status_code == 404  # not their student
    assert (
        await pair.therapist.post("/therapist/follow-ups", {**body, "student_id": str(stranger.id)})
    ).status_code == 404
    assert (await other.get("/therapist/follow-ups")).json() == []
    assert (
        await other.patch(f"/therapist/follow-ups/{fu['id']}", {"status": "done"})
    ).status_code in (403, 404)
    assert (await pair.student.get("/therapist/follow-ups")).status_code == 403
    # a session from a different therapist/student cannot be attached
    foreign = await started_session(api_db, await care_pair(client, api_db, world))
    r = await pair.therapist.post("/therapist/follow-ups", {**body, "session_id": str(foreign)})
    assert r.status_code == 404
    # the student never receives a therapist's follow-up
    export = (await pair.student.get("/me/privacy/export")).text
    assert "FU-PRIVATE" not in export


async def test_follow_ups_disappear_when_the_care_link_ends(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    due = (dt.date.today() + dt.timedelta(days=2)).isoformat()
    await pair.therapist.post(
        "/therapist/follow-ups",
        {"student_id": str(pair.student.id), "kind": "check_in", "due_on": due},
    )
    await end_care_link(api_db, pair)
    assert (await pair.therapist.get("/therapist/follow-ups")).json() == []
    r = await pair.therapist.post(
        "/therapist/follow-ups",
        {"student_id": str(pair.student.id), "kind": "check_in", "due_on": due},
    )
    assert r.status_code == 404


# ---- recommendations -----------------------------------------------------------------------


async def test_a_therapist_recommendation_reaches_the_student_labelled_as_theirs(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    resource = (await pair.therapist.get("/resources")).json()[0]
    r = await pair.therapist.post(
        f"/therapist/students/{pair.student.id}/recommendations",
        {
            "title": "Try a short walk",
            "rationale": "Fresh air before revision.",
            "resource_id": resource["id"],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["resource_title"] == resource["title"]

    mine = (await pair.student.get("/me/recommendations")).json()
    theirs = [x for x in mine if x["source"] == RecommendationSource.THERAPIST.value]
    assert [x["title"] for x in theirs] == ["Try a short walk"]
    assert theirs[0]["resource"]["id"] == resource["id"]
    note = await api_db.scalar(
        select(m.Notification).where(
            m.Notification.user_id == pair.student.id,
            m.Notification.type == NotificationType.RECOMMENDATION,
        )
    )
    assert note is not None and "walk" not in str(note.payload)

    # the student responds; the therapist sees the response but not a refresh of someone else's
    await pair.student.patch(f"/me/recommendations/{theirs[0]['id']}", {"status": "completed"})
    made = (
        await pair.therapist.get(f"/therapist/students/{pair.student.id}/recommendations")
    ).json()
    assert made[0]["status"] == "completed"


async def test_recommendation_limits_and_validation(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    url = f"/therapist/students/{pair.student.id}/recommendations"
    assert (
        await pair.therapist.post(url, {"title": "ab", "rationale": "ok then"})
    ).status_code == 422
    assert (
        await pair.therapist.post(url, {"title": "Fine title", "rationale": "x" * 601})
    ).status_code == 422
    bad = {
        "title": "Fine title",
        "rationale": "A kind reason.",
        "resource_id": "00000000-0000-0000-0000-000000000001",
    }
    assert (await pair.therapist.post(url, bad)).status_code == 404
    for i in range(5):
        ok = await pair.therapist.post(
            url, {"title": f"Idea number {i}", "rationale": "A kind reason."}
        )
        assert ok.status_code == 201
    assert (
        await pair.therapist.post(url, {"title": "One more", "rationale": "Too many."})
    ).status_code == 422


async def test_a_therapist_only_lists_their_own_recommendations(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    second = await care_pair(client, api_db, world)
    url = f"/therapist/students/{pair.student.id}/recommendations"
    await pair.therapist.post(url, {"title": "Mine only", "rationale": "A kind reason."})
    assert (await second.therapist.get(url)).status_code == 404
    assert (
        await pair.student.post(url, {"title": "Self help", "rationale": "A kind reason."})
    ).status_code == 403


# ---- secure messaging ----------------------------------------------------------------------


async def test_therapist_and_student_message_each_other(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    t, s = pair.therapist, pair.student
    sent = await t.post(f"/me/conversations/{s.id}/messages", {"body": "Hello, how was your week?"})
    assert sent.status_code == 201, sent.text
    reply = await s.post(f"/me/conversations/{t.id}/messages", {"body": "Better, thank you."})
    assert reply.status_code == 201

    convs = (await t.get("/me/conversations")).json()
    assert [c["other_id"] for c in convs] == [str(s.id)]
    assert convs[0]["other_name"] and convs[0]["unread_count"] == 1
    msgs = (await t.get(f"/me/conversations/{s.id}/messages")).json()
    assert [x["body"] for x in msgs] == ["Hello, how was your week?", "Better, thank you."]
    assert (await t.post(f"/me/conversations/{s.id}/read")).status_code in (200, 204)
    assert (await t.get("/me/conversations")).json()[0]["unread_count"] == 0

    # message bodies are never part of audit rows
    events = list(await api_db.scalars(select(m.AuditLog).where(m.AuditLog.actor_id == t.id)))
    assert "Hello, how was your week" not in str([e.details for e in events])


async def test_messaging_needs_the_care_team_and_stops_when_it_ends(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    other = await fresh_therapist(client, api_db, world)
    assert (await other.get(f"/me/conversations/{pair.student.id}/messages")).status_code == 404
    assert (
        await other.post(f"/me/conversations/{pair.student.id}/messages", {"body": "hi"})
    ).status_code == 404
    await pair.therapist.post(f"/me/conversations/{pair.student.id}/messages", {"body": "hello"})
    await end_care_link(api_db, pair)
    r = await pair.therapist.post(
        f"/me/conversations/{pair.student.id}/messages", {"body": "again"}
    )
    assert r.status_code in (403, 404)
    assert (await other.get("/me/conversations")).json() == []
