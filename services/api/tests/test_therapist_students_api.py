"""The therapist's caseload: who they may see, what a student has chosen to share."""

import datetime as dt

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import AppointmentStatus, NotificationType
from tests.api_world import World
from tests.student_helpers import new_student, new_therapist
from tests.therapist_helpers import (
    care_pair,
    due_appointment,
    end_care_link,
    fresh_therapist,
    make_alert,
)

pytestmark = pytest.mark.asyncio

ANSWERS = {f"q{i}": 4 for i in range(1, 6)}


async def test_caseload_lists_only_my_students_with_what_needs_attention(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    stranger = await new_student(client, api_db, world)
    await make_alert(api_db, pair)

    rows = (await pair.therapist.get("/therapist/students")).json()
    assert [r["student_id"] for r in rows] == [str(pair.student.id)]
    row = rows[0]
    assert row["care_role"] == "primary" and row["open_alerts"] == 1
    assert row["next_appointment_at"] is not None
    assert row["sharing"] == {"mood": True, "assessments": False}
    assert str(stranger.id) not in str(rows)
    # contact details and student numbers are not part of the caseload
    assert not {"email", "student_number", "phone"} & row.keys()


async def test_another_therapist_has_an_empty_caseload(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    await care_pair(client, api_db, world)
    other = await fresh_therapist(client, api_db, world)
    assert (await other.get("/therapist/students")).json() == []


async def test_student_profile_shows_context_and_what_is_shared(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world, assessments=False)
    await pair.student.post(
        "/me/check-ins", {"mood_score": 2, "note": "PRIVATE-NOTE", "stress_level": 4}
    )
    await pair.student.post("/me/wellness/assessments", {"responses": ANSWERS})

    r = await pair.therapist.get(f"/therapist/students/{pair.student.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["department"] and body["year_of_study"] == 2
    assert body["sharing"] == {"mood": True, "assessments": False}
    assert body["latest_mood"]["score"] == 2
    assert body["latest_assessment"] is None  # not shared
    assert len(body["upcoming_appointments"]) == 1
    assert "PRIVATE-NOTE" not in r.text  # a check-in's private note is never shared
    assert not {"email", "student_number"} & body.keys()

    await pair.student.put("/me/consents/share_assessments_with_care_team", {"granted": True})
    body = (await pair.therapist.get(f"/therapist/students/{pair.student.id}")).json()
    assert body["latest_assessment"]["max_score"] == 25


async def test_profile_without_consent_hides_check_ins_but_still_shows_the_relationship(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world, mood=False)
    await pair.student.post("/me/check-ins", {"mood_score": 1})
    body = (await pair.therapist.get(f"/therapist/students/{pair.student.id}")).json()
    assert body["sharing"] == {"mood": False, "assessments": False}
    assert body["latest_mood"] is None and body["latest_assessment"] is None
    assert len(body["upcoming_appointments"]) == 1


async def test_trends_need_consent_and_follow_it_the_moment_it_changes(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world, mood=False)
    await pair.student.post("/me/check-ins", {"mood_score": 5, "stress_level": 1})
    path = f"/therapist/students/{pair.student.id}/trends?days=14"
    assert (await pair.therapist.get(path)).status_code == 403

    await pair.student.put("/me/consents/share_mood_with_care_team", {"granted": True})
    r = await pair.therapist.get(path)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["days"] == 14 and len(body["points"]) == 14
    assert body["points"][-1]["mood"] == 5 and body["points"][-1]["stress"] == 1
    assert "not a diagnosis" in body["disclaimer"]

    await pair.student.put("/me/consents/share_mood_with_care_team", {"granted": False})
    assert (await pair.therapist.get(path)).status_code == 403


@pytest.mark.parametrize("days", [0, 6, 91])
async def test_trend_range_is_validated(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, days: int
) -> None:
    pair = await care_pair(client, api_db, world)
    r = await pair.therapist.get(f"/therapist/students/{pair.student.id}/trends?days={days}")
    assert r.status_code == 422


async def test_assessments_have_their_own_consent(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world, mood=True, assessments=False)
    await pair.student.post("/me/wellness/assessments", {"responses": ANSWERS})
    path = f"/therapist/students/{pair.student.id}/assessments"
    assert (await pair.therapist.get(path)).status_code == 403  # mood consent is not enough

    await pair.student.put("/me/consents/share_assessments_with_care_team", {"granted": True})
    r = await pair.therapist.get(path)
    assert r.status_code == 200 and r.json()[0]["score"] == 20
    assert "responses" not in r.json()[0]  # item-level answers are never shared


async def test_students_outside_my_care_team_look_like_they_do_not_exist(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world, assessments=True)
    other = await fresh_therapist(client, api_db, world)
    b_therapist = await fresh_therapist(client, api_db, world, other_tenant=True)
    for who in (other, b_therapist):
        for suffix in ("", "/trends", "/assessments", "/recommendations"):
            r = await who.get(f"/therapist/students/{pair.student.id}{suffix}")
            assert r.status_code == 404, (suffix, r.text)
        r = await who.post(
            f"/therapist/students/{pair.student.id}/recommendations",
            {"title": "Walk outside", "rationale": "A short walk can help."},
        )
        assert r.status_code == 404
    random = await who.get("/therapist/students/00000000-0000-0000-0000-000000000099")
    assert random.status_code == 404  # same answer as for a real student: no way to probe ids


async def test_ending_the_care_team_link_closes_every_student_route(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world, assessments=True)
    await end_care_link(api_db, pair)
    assert (await pair.therapist.get("/therapist/students")).json() == []
    for suffix in ("", "/trends", "/assessments", "/recommendations"):
        assert (
            await pair.therapist.get(f"/therapist/students/{pair.student.id}{suffix}")
        ).status_code == 404


async def test_profile_and_trend_reads_are_audited_without_content(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    await pair.student.post("/me/check-ins", {"mood_score": 3, "note": "AUDIT-LEAK-CHECK"})
    await pair.therapist.get(f"/therapist/students/{pair.student.id}")
    await pair.therapist.get(f"/therapist/students/{pair.student.id}/trends")
    events = list(
        await api_db.scalars(
            select(m.AuditLog).where(
                m.AuditLog.actor_id == pair.therapist.id,
                m.AuditLog.subject_student_id == pair.student.id,
            )
        )
    )
    assert {"student.read", "wellness_trend.read"} <= {e.action for e in events}
    assert "AUDIT-LEAK-CHECK" not in str([e.details for e in events])


# ---- appointments --------------------------------------------------------------------------


async def test_requests_show_the_reason_and_confirming_notifies_the_student(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    t, slots = await new_therapist(client, api_db, world)
    appt = (
        await s.post(
            "/me/appointments", {"availability_id": str(slots[0]), "reason": "Exam worries"}
        )
    ).json()
    requests = (await t.get("/therapist/appointments?scope=requests")).json()
    assert [(r["id"], r["reason"], r["status"]) for r in requests] == [
        (appt["id"], "Exam worries", "requested")
    ]
    assert requests[0]["student_name"]
    assert (await t.get("/therapist/appointments?scope=upcoming")).json() == []

    assert (
        await t.patch(f"/appointments/{appt['id']}", {"status": "confirmed"})
    ).status_code == 200
    assert (await t.get("/therapist/appointments?scope=requests")).json() == []
    assert [r["id"] for r in (await t.get("/therapist/appointments?scope=upcoming")).json()] == [
        appt["id"]
    ]
    note = await api_db.scalar(
        select(m.Notification).where(
            m.Notification.user_id == s.id,
            m.Notification.type == NotificationType.APPOINTMENT_UPDATE,
        )
    )
    assert note is not None
    assert note.payload == {"appointment_id": appt["id"], "event": "confirmed"}  # ids only
    assert "Exam" not in str(note.payload)


async def test_declining_a_request_frees_the_slot_and_tells_the_student(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    t, slots = await new_therapist(client, api_db, world)
    appt = (await s.post("/me/appointments", {"availability_id": str(slots[0])})).json()
    assert (
        await t.patch(f"/appointments/{appt['id']}", {"status": "cancelled"})
    ).status_code == 200
    assert (await s.get("/me/appointments")).json()[0]["status"] == "cancelled"
    open_slots = {x["id"] for x in (await s.get(f"/therapists/{t.id}/slots")).json()}
    assert str(slots[0]) in open_slots
    # a student whose request was declined is not on the care team
    assert (await t.get("/therapist/students")).json() == []
    # and cannot be moved to a state the machine does not allow
    r = await t.patch(f"/appointments/{appt['id']}", {"status": "confirmed"})
    assert r.status_code == 409


async def test_appointment_scopes_and_filters(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    past = await due_appointment(
        api_db, pair, starts_in=dt.timedelta(days=-3), status=AppointmentStatus.COMPLETED
    )
    ids_past = {
        a["id"] for a in (await pair.therapist.get("/therapist/appointments?scope=past")).json()
    }
    assert str(past) in ids_past
    done = (await pair.therapist.get("/therapist/appointments?status=completed")).json()
    assert [a["id"] for a in done] == [str(past)]
    assert (await pair.therapist.get("/therapist/appointments?scope=nope")).status_code == 422
    assert (await pair.therapist.get("/therapist/appointments?limit=0")).status_code == 422


async def test_therapist_cannot_manage_another_therapists_appointment(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    t, slots = await new_therapist(client, api_db, world)
    other = await fresh_therapist(client, api_db, world)
    appt = (await s.post("/me/appointments", {"availability_id": str(slots[0])})).json()
    r = await other.patch(f"/appointments/{appt['id']}", {"status": "confirmed"})
    assert r.status_code in (403, 404)
    assert (await other.get("/therapist/appointments")).json() == []
    row = await api_db.get(m.Appointment, appt["id"])
    await api_db.refresh(row)
    assert row is not None and row.status is AppointmentStatus.REQUESTED


# ---- dashboard -----------------------------------------------------------------------------


async def test_dashboard_summarises_the_day(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    s2 = await new_student(client, api_db, world)
    slot = (await pair.therapist.get("/therapist/availability")).json()
    assert len(slot) >= 2
    await s2.post("/me/appointments", {"availability_id": slot[1]["id"]})
    await due_appointment(api_db, pair, starts_in=dt.timedelta(minutes=1))
    await make_alert(api_db, pair)
    await pair.student.post(f"/me/conversations/{pair.therapist.id}/messages", {"body": "hello"})

    d = (await pair.therapist.get("/therapist/dashboard")).json()
    assert d["verification_status"] == "verified" and d["can_see_students"] is True
    assert d["caseload"] == 1 and d["pending_requests"] == 1
    assert d["alerts_by_severity"]["moderate"] == 1 and d["alerts_overdue"] == 0
    assert d["unread_messages"] == 1
    assert d["next_appointment"]["student_id"] == str(pair.student.id)
    assert {"mood", "note", "body"}.isdisjoint(str(d).lower().split("'"))  # counts only


async def test_dashboards_are_per_therapist(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    await care_pair(client, api_db, world)
    other = await fresh_therapist(client, api_db, world)
    d = (await other.get("/therapist/dashboard")).json()
    assert d["caseload"] == 0 and d["pending_requests"] == 0 and d["next_appointment"] is None
    assert sum(d["alerts_by_severity"].values()) == 0
