"""Messaging, consent, privacy history, data export, and asking for support."""

import datetime as dt
import json
import uuid

import httpx
import pytest
from sqlalchemy import Text, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AlertCategory,
    AlertSeverity,
    AlertSource,
    AlertStatus,
    AuditOutcome,
    ConsentScope,
    CrisisContactKind,
    NotificationType,
)
from app.infrastructure.db.ids import uuid7
from tests.api_world import World
from tests.student_helpers import Session, new_student, new_therapist

pytestmark = pytest.mark.asyncio


async def _on_care_team(
    client: httpx.AsyncClient, db: AsyncSession, world: World
) -> tuple[Session, Session]:
    """A fresh student whose first appointment the (fresh) therapist has confirmed."""
    s = await new_student(client, db, world)
    t, slots = await new_therapist(client, db, world)
    appt = (await s.post("/me/appointments", {"availability_id": str(slots[0])})).json()
    assert (
        await t.patch(f"/appointments/{appt['id']}", {"status": "confirmed"})
    ).status_code == 200
    return s, t


# ---- messages -------------------------------------------------------------------------------


async def test_cannot_message_a_therapist_who_is_not_on_my_care_team(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    t, _ = await new_therapist(client, api_db, world)
    assert (await s.get("/me/conversations")).json() == []
    r = await s.post(f"/me/conversations/{t.id}/messages", {"body": "hello?"})
    assert r.status_code == 404
    assert (await s.get(f"/me/conversations/{t.id}/messages")).status_code == 404
    assert (
        await api_db.scalar(
            select(func.count()).select_from(m.Message).where(m.Message.student_id == s.id)
        )
        == 0
    )


async def test_conversation_between_student_and_their_therapist(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, t = await _on_care_team(client, api_db, world)
    convs = (await s.get("/me/conversations")).json()
    assert [c["other_id"] for c in convs] == [str(t.id)] and convs[0]["active"] is True
    assert convs[0]["unread_count"] == 0 and convs[0]["last_message_at"] is None

    cid = str(uuid.uuid4())
    sent = await s.post(
        f"/me/conversations/{t.id}/messages",
        {"body": " Hi, thanks for the slot ", "client_msg_id": cid},
    )
    assert sent.status_code == 201, sent.text
    out = sent.json()
    assert out["message"]["body"] == "Hi, thanks for the slot" and out["message"]["mine"] is True
    assert out["support"] is None
    again = await s.post(
        f"/me/conversations/{t.id}/messages",
        {"body": "Hi, thanks for the slot", "client_msg_id": cid},
    )
    assert again.json()["message"]["id"] == out["message"]["id"]  # a retry is not a second message

    # a reply from the therapist arrives unread
    api_db.add(
        m.Message(
            id=uuid7(),
            institution_id=world.inst_a,
            student_id=s.id,
            therapist_id=t.id,
            sender_id=t.id,
            body="See you Thursday.",
        )
    )
    await api_db.commit()
    convs = (await s.get("/me/conversations")).json()
    assert convs[0]["unread_count"] == 1 and convs[0]["last_message_preview"] == "See you Thursday."
    msgs = (await s.get(f"/me/conversations/{t.id}/messages")).json()
    assert [(x["body"], x["mine"]) for x in msgs] == [
        ("Hi, thanks for the slot", True),
        ("See you Thursday.", False),
    ]
    assert (await s.post(f"/me/conversations/{t.id}/read")).json() == {"marked_read": 1}
    assert (await s.get("/me/conversations")).json()[0]["unread_count"] == 0

    therapist_note = await api_db.scalar(
        select(m.Notification).where(
            m.Notification.user_id == t.id, m.Notification.type == NotificationType.NEW_MESSAGE
        )
    )
    assert therapist_note is not None and "Hi" not in str(therapist_note.payload)


async def test_message_validation_and_encryption(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, t = await _on_care_team(client, api_db, world)
    for body in ("", "   ", "x" * 4001):
        assert (
            await s.post(f"/me/conversations/{t.id}/messages", {"body": body})
        ).status_code == 422
    await s.post(f"/me/conversations/{t.id}/messages", {"body": "a confidential sentence"})
    raw = await api_db.scalar(
        text("SELECT body FROM comm.messages WHERE student_id = :s"), {"s": s.id}
    )
    assert raw is not None and b"confidential" not in bytes(raw)
    in_audit = await api_db.scalar(
        select(func.count())
        .select_from(m.AuditLog)
        .where(cast(m.AuditLog.details, Text).contains("confidential"))
    )
    assert in_audit == 0  # message text never reaches the audit log


async def test_a_message_that_mentions_self_harm_surfaces_support_information(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, t = await _on_care_team(client, api_db, world)
    r = await s.post(
        f"/me/conversations/{t.id}/messages", {"body": "I keep thinking I want to die"}
    )
    assert r.status_code == 201 and r.json()["support"]["help_path"] == "/student/emergency"
    row = await api_db.scalar(select(m.Message).where(m.Message.student_id == s.id))
    assert row is not None and row.crisis_checked_at is not None


async def test_other_students_and_other_institutions_cannot_read_a_conversation(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, t = await _on_care_team(client, api_db, world)
    await s.post(f"/me/conversations/{t.id}/messages", {"body": "private"})
    neighbour = await new_student(client, api_db, world)
    outsider = await new_student(client, api_db, world, other_tenant=True)
    for intruder in (neighbour, outsider):
        assert (await intruder.get(f"/me/conversations/{t.id}/messages")).status_code == 404
        assert (
            await intruder.post(f"/me/conversations/{t.id}/messages", {"body": "hi"})
        ).status_code == 404
        assert (await intruder.post(f"/me/conversations/{t.id}/read")).status_code == 404
        assert (await intruder.get("/me/conversations")).json() == []
    # a student cannot "message" another student either
    assert (
        await neighbour.post(f"/me/conversations/{s.id}/messages", {"body": "hi"})
    ).status_code == 404


async def test_conversation_closes_when_the_care_team_link_ends(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, t = await _on_care_team(client, api_db, world)
    await s.post(f"/me/conversations/{t.id}/messages", {"body": "before"})
    link = await api_db.scalar(select(m.CareTeamMember).where(m.CareTeamMember.student_id == s.id))
    assert link is not None
    link.ends_at = link.starts_at.replace(year=link.starts_at.year + 50)  # ends far in the future
    await api_db.commit()
    assert (
        await s.post(f"/me/conversations/{t.id}/messages", {"body": "still open"})
    ).status_code == 201
    link.ends_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    link.starts_at = link.ends_at - dt.timedelta(days=1)
    await api_db.commit()
    assert (
        await s.post(f"/me/conversations/{t.id}/messages", {"body": "after"})
    ).status_code == 404
    convs = (await s.get("/me/conversations")).json()
    assert convs[0]["active"] is False  # listed, but closed: no reading or writing either
    assert (await s.get(f"/me/conversations/{t.id}/messages")).status_code == 404


# ---- consent --------------------------------------------------------------------------------


async def test_consent_list_covers_every_scope_in_plain_language(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    items = (await s.get("/me/consents")).json()
    assert {i["scope"] for i in items} == {c.value for c in ConsentScope}
    assert all(i["title"] and i["description"] for i in items)
    assert all(i["granted"] is False for i in items)  # a fresh account has granted nothing


async def test_granting_and_revoking_sharing_consent_changes_what_the_therapist_can_see(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, t = await _on_care_team(client, api_db, world)
    await s.post("/me/check-ins", {"mood_score": 4, "note": "private note"})
    assert (await t.get(f"/students/{s.id}/mood-entries")).status_code == 403

    granted = await s.put("/me/consents/share_mood_with_care_team", {"granted": True})
    assert granted.status_code == 200 and granted.json()["granted"] is True
    assert (
        await s.put("/me/consents/share_mood_with_care_team", {"granted": True})
    ).status_code == 200  # idempotent
    shared = await t.get(f"/students/{s.id}/mood-entries")
    assert shared.status_code == 200 and shared.json()[0]["mood_score"] == 4
    assert "note" not in shared.json()[0]  # the private note is never shared

    revoked = await s.put("/me/consents/share_mood_with_care_team", {"granted": False})
    assert revoked.json()["granted"] is False
    assert (await t.get(f"/students/{s.id}/mood-entries")).status_code == 403  # immediate

    rows = list(await api_db.scalars(select(m.Consent).where(m.Consent.user_id == s.id)))
    assert len(rows) == 1 and rows[0].revoked_at is not None  # history kept, not deleted
    again = await s.put("/me/consents/share_mood_with_care_team", {"granted": True})
    assert again.json()["granted"] is True
    assert (
        await api_db.scalar(
            select(func.count()).select_from(m.Consent).where(m.Consent.user_id == s.id)
        )
        == 2
    )
    events = list(
        await api_db.scalars(
            select(m.AuditLog.action).where(
                m.AuditLog.actor_id == s.id, m.AuditLog.action.like("consent.%")
            )
        )
    )
    assert events.count("consent.grant") == 2 and events.count("consent.revoke") == 1


async def test_required_consent_cannot_be_withdrawn_here(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    assert (await s.put("/me/consents/terms_and_privacy", {"granted": True})).status_code == 200
    r = await s.put("/me/consents/terms_and_privacy", {"granted": False})
    assert r.status_code == 409
    assert (await s.put("/me/consents/not_a_scope", {"granted": True})).status_code == 422


async def test_consents_are_per_person(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    a = await new_student(client, api_db, world)
    b = await new_student(client, api_db, world)
    await a.put("/me/consents/email_notifications", {"granted": True})
    mine = {i["scope"]: i["granted"] for i in (await b.get("/me/consents")).json()}
    assert mine["email_notifications"] is False


# ---- who looked at my data ------------------------------------------------------------------


async def test_access_history_shows_roles_not_people_and_only_other_peoples_reads(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, t = await _on_care_team(client, api_db, world)
    await s.put("/me/consents/share_mood_with_care_team", {"granted": True})
    await s.post("/me/check-ins", {"mood_score": 3})
    await s.get("/me/wellness/mood-entries")  # my own read: not listed
    assert (await t.get(f"/students/{s.id}/mood-entries")).status_code == 200
    # a denied attempt (another therapist, no link) must not appear either
    other, _ = await new_therapist(client, api_db, world)
    assert (await other.get(f"/students/{s.id}/mood-entries")).status_code == 404

    events = (await s.get("/me/privacy/access-history")).json()
    reads = [e for e in events if e["action"] == "mood_entry.list"]
    assert len(reads) == 1 and reads[0]["actor_role"] == "therapist"
    assert set(reads[0]) == {"occurred_at", "actor_role", "action", "resource_type"}
    assert str(t.id) not in json.dumps(events) and str(other.id) not in json.dumps(events)
    assert all(e["actor_role"] != "student" for e in events)


async def test_access_history_is_private(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, t = await _on_care_team(client, api_db, world)
    await s.put("/me/consents/share_mood_with_care_team", {"granted": True})
    await t.get(f"/students/{s.id}/mood-entries")
    stranger = await new_student(client, api_db, world)
    assert (await stranger.get("/me/privacy/access-history")).json() == []


# ---- export ---------------------------------------------------------------------------------


async def test_export_is_a_complete_copy_of_my_own_data_only(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    other = await new_student(client, api_db, world)
    await s.post("/me/check-ins", {"mood_score": 2, "note": "my own words", "stress_level": 4})
    await s.post("/me/goals", {"title": "Sleep earlier", "category": "sleep"})
    await other.post("/me/check-ins", {"mood_score": 5, "note": "somebody else's words"})

    r = await s.get("/me/privacy/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"
    data = r.json()
    assert data["mood_entries"][0]["note"] == "my own words"
    assert data["goals"][0]["title"] == "Sleep earlier"
    assert data["stress_entries"][0]["perceived_stress_level"] == 4
    assert "somebody else" not in r.text
    assert data["profile"]["email"] == s.actor.email


async def test_export_never_includes_therapy_notes(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """The seeded student has notes written about them by their therapist."""
    s = Session(client, world.student, "")
    from tests.api_helpers import token_for

    s.token = await token_for(client, world.student, world.password)
    bodies = [
        n.body
        for n in await api_db.scalars(
            select(m.TherapyNote)
            .join(m.TherapySession, m.TherapySession.id == m.TherapyNote.session_id)
            .where(m.TherapySession.student_id == world.student.user_id)
        )
    ]
    assert bodies
    r = await s.get("/me/privacy/export")
    assert r.status_code == 200
    assert not any(b in r.text for b in bodies)
    assert "therapy" not in set(r.json())


# ---- asking for a person to reach out -------------------------------------------------------


async def test_support_request_creates_a_human_followed_alert(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, t = await _on_care_team(client, api_db, world)
    r = await s.post("/me/support-requests", {"message": "I'd like someone to call me"})
    assert r.status_code == 201, r.text
    out = r.json()
    assert (
        out["status"] == "open"
        and out["already_open"] is False
        and out["reaches_care_team"] is True
    )
    alert = await api_db.get(m.RiskAlert, out["id"])
    assert alert is not None
    assert alert.student_id == s.id and alert.assigned_to == t.id
    assert alert.source is AlertSource.HELP_BUTTON and alert.requires_human is True
    assert alert.category is AlertCategory.ACUTE_DISTRESS and alert.severity is AlertSeverity.HIGH
    assert alert.status is AlertStatus.OPEN and alert.sla_ack_due_at is not None
    assert alert.excerpt == "I'd like someone to call me"
    note = await api_db.scalar(
        select(m.Notification).where(
            m.Notification.user_id == t.id, m.Notification.type == NotificationType.RISK_ALERT
        )
    )
    assert note is not None and "call me" not in str(note.payload)


async def test_repeated_taps_do_not_flood_the_team(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    first = (await s.post("/me/support-requests", {})).json()
    second = (await s.post("/me/support-requests", {"message": "again"})).json()
    assert second["already_open"] is True and second["id"] == first["id"]
    assert (
        first["reaches_care_team"] is False
    )  # no therapist yet: still raised for the on-call team
    count = await api_db.scalar(
        select(func.count()).select_from(m.RiskAlert).where(m.RiskAlert.student_id == s.id)
    )
    assert count == 1
    assert (await s.post("/me/support-requests", {"message": "x" * 1001})).status_code == 422


async def test_safety_resources_are_national_plus_my_institution(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    api_db.add(
        m.CrisisContact(
            id=uuid7(),
            institution_id=world.inst_b,
            label="Other College counselling line",
            kind=CrisisContactKind.CAMPUS,
            phone="000-OTHER",
        )
    )
    api_db.add(
        m.CrisisContact(
            id=uuid7(),
            institution_id=world.inst_a,
            label="Retired contact",
            kind=CrisisContactKind.CAMPUS,
            phone="000-OLD",
            is_active=False,
        )
    )
    await api_db.commit()
    s = await new_student(client, api_db, world)
    labels = [c["label"] for c in (await s.get("/me/safety/resources")).json()]
    assert "National emergency number" in labels
    assert "Synthetic Institute counselling centre" in labels
    assert "Other College counselling line" not in labels
    assert "Retired contact" not in labels
    outsider = await new_student(client, api_db, world, other_tenant=True)
    theirs = [c["label"] for c in (await outsider.get("/me/safety/resources")).json()]
    assert "Other College counselling line" in theirs
    assert "Synthetic Institute counselling centre" not in theirs


async def test_support_requests_are_audited_without_content(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await s.post("/me/support-requests", {"message": "very sensitive text"})
    rows = list(
        await api_db.scalars(
            select(m.AuditLog).where(
                m.AuditLog.actor_id == s.id, m.AuditLog.action == "support_request.create"
            )
        )
    )
    assert len(rows) == 1 and rows[0].outcome is AuditOutcome.ALLOWED
    assert "sensitive" not in json.dumps(rows[0].details)
