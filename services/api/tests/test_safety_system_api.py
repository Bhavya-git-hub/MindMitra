"""The safety and escalation system through the API (ADR 0013): check-ins, messages and the
companion; who is asked to reach out and on what basis; the pause on suggestions; what is
stored (never the text); fail-safe behaviour; and who can see any of it.

All records are synthetic. The AI service is not involved: crisis handling never needs it.
"""

import datetime as dt
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import safety_workflow
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AIConversationStatus,
    AlertSeverity,
    AlertSource,
    RecommendationSource,
    RecommendationStatus,
)
from app.infrastructure.db.ids import uuid7
from tests.api_world import World
from tests.student_helpers import Session, new_student
from tests.therapist_helpers import care_pair

pytestmark = pytest.mark.asyncio

HIGH_NOTE = "I've been thinking about suicide a lot"
IMMEDIATE_NOTE = "I have a plan to kill myself tonight"
MODERATE_NOTE = "I feel hopeless"
IDIOM_NOTE = "this assignment is killing me"


async def check_in(
    s: Session, note: str | None = None, mood: int = 3, **extra: Any
) -> dict[str, Any]:
    r = await s.post("/me/check-ins", {"mood_score": mood, "note": note, **extra})
    assert r.status_code == 201, r.text
    return dict(r.json())


async def consent(s: Session, granted: bool = True) -> None:
    r = await s.put("/me/consents/journal_safety_scanning", {"granted": granted})
    assert r.status_code == 200, r.text


async def alerts_for(db: AsyncSession, student: Session) -> list[m.RiskAlert]:
    db.expire_all()
    rows = await db.scalars(
        select(m.RiskAlert)
        .where(m.RiskAlert.student_id == student.id)
        .order_by(m.RiskAlert.created_at)
    )
    return list(rows)


async def events_for(db: AsyncSession, student: Session) -> list[m.SafetyEvent]:
    db.expire_all()
    rows = await db.scalars(
        select(m.SafetyEvent)
        .where(m.SafetyEvent.student_id == student.id)
        .order_by(m.SafetyEvent.created_at)
    )
    return list(rows)


async def engine_suggestion(db: AsyncSession, world: World, s: Session) -> None:
    """One open suggestion from the engine and one from a therapist."""
    for source, title in (
        (RecommendationSource.RULE, "Take a short walk"),
        (RecommendationSource.THERAPIST, "Try the breathing exercise we discussed"),
    ):
        db.add(
            m.Recommendation(
                id=uuid7(),
                institution_id=world.inst_a,
                student_id=s.id,
                source=source,
                title=title,
                rationale="Synthetic test suggestion.",
                status=RecommendationStatus.PENDING,
            )
        )
    await db.commit()


async def open_titles(s: Session) -> set[str]:
    r = await s.get("/me/recommendations")
    assert r.status_code == 200, r.text
    return {x["title"] for x in r.json()}


# ---- what the student sees ------------------------------------------------------------------


async def test_a_high_concern_with_consent_asks_a_person_and_pauses_suggestions(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await consent(s)
    await engine_suggestion(api_db, world, s)
    assert await open_titles(s) == {"Take a short walk", "Try the breathing exercise we discussed"}

    out = await check_in(s, HIGH_NOTE)
    safety_out = out["safety"]
    assert safety_out["level"] == "high"
    assert safety_out["escalation"]["status"] == "requested"
    assert safety_out["escalation"]["basis"] == "consent"
    assert safety_out["offer_outreach"] is False
    assert safety_out["emergency_first"] is False
    assert safety_out["recommendations_paused"] is True
    assert safety_out["paused_until"]
    assert safety_out["resources"], "contacts are always shown"
    assert safety_out["resources"][0]["kind"] == "emergency"
    assert safety_out["guidance"]["steps"]
    assert "not an emergency service" in safety_out["disclaimer"]
    assert out["support"] is not None  # the older field stays for older clients

    (alert,) = await alerts_for(api_db, s)
    assert alert.source is AlertSource.MOOD_ENTRY
    assert alert.severity is AlertSeverity.HIGH
    assert alert.excerpt is None and alert.source_id is None  # nothing about what was written

    # Engine suggestions are hidden and none are made; a therapist's suggestion stays.
    assert await open_titles(s) == {"Try the breathing exercise we discussed"}
    r = await s.post("/me/recommendations/refresh")
    assert r.status_code == 200
    assert {x["title"] for x in r.json()} == {"Try the breathing exercise we discussed"}
    history = await s.get("/me/recommendations/history")
    assert len(history.json()) == 2  # the history itself is untouched

    status = (await s.get("/me/safety/status")).json()
    assert status["recommendations_paused"] is True
    assert status["support"]["level"] == "high"
    assert status["support"]["escalation"]["status"] == "requested"
    dashboard = (await s.get("/me/dashboard")).json()
    assert dashboard["safety"]["recommendations_paused"] is True
    assert [x["title"] for x in dashboard["recommendations"]] == [
        "Try the breathing exercise we discussed"
    ]


async def test_a_high_concern_without_consent_asks_nobody_but_offers_help(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await consent(s, granted=False)
    out = await check_in(s, HIGH_NOTE)
    assert out["safety"]["level"] == "high"
    assert out["safety"]["escalation"] == {
        "status": "not_requested",
        "basis": "no_consent",
        "care_team_notified": False,
    }
    assert out["safety"]["offer_outreach"] is True
    assert out["safety"]["recommendations_paused"] is True
    assert await alerts_for(api_db, s) == []
    (event,) = await events_for(api_db, s)
    assert event.escalated is False and event.basis.value == "no_consent"

    # The one-tap request still reaches a person.
    r = await s.post("/me/support-requests", {"message": None})
    assert r.status_code == 201, r.text
    assert len(await alerts_for(api_db, s)) == 1


async def test_immediate_danger_asks_a_person_whatever_the_consent(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await consent(s, granted=False)
    before = dt.datetime.now(dt.UTC)
    out = await check_in(s, IMMEDIATE_NOTE)
    assert out["safety"]["level"] == "immediate"
    assert out["safety"]["emergency_first"] is True
    assert out["safety"]["escalation"]["basis"] == "vital_interest"
    assert out["safety"]["escalation"]["status"] == "requested"
    assert "emergency number" in out["safety"]["guidance"]["steps"][0]
    (alert,) = await alerts_for(api_db, s)
    assert alert.severity is AlertSeverity.IMMINENT
    assert alert.sla_ack_due_at is not None
    assert alert.sla_ack_due_at <= before + dt.timedelta(minutes=6)


async def test_moderate_concern_shows_support_and_stores_nothing(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await consent(s)
    await engine_suggestion(api_db, world, s)
    for out in (await check_in(s, MODERATE_NOTE), await check_in(s, None, mood=1)):
        assert out["safety"]["level"] == "moderate"
        assert out["safety"]["escalation"]["basis"] == "not_needed"
        assert out["safety"]["offer_outreach"] is True
        assert out["safety"]["recommendations_paused"] is False
        assert out["safety"]["resources"]
    assert await alerts_for(api_db, s) == []
    assert await events_for(api_db, s) == []
    assert "Take a short walk" in await open_titles(s)
    assert (await s.get("/me/safety/status")).json()["recommendations_paused"] is False


async def test_everyday_idioms_get_nothing_extra(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await consent(s)
    out = await check_in(s, IDIOM_NOTE, mood=3, stress_level=3)
    assert out["safety"] is None and out["support"] is None
    assert await alerts_for(api_db, s) == []
    assert await events_for(api_db, s) == []


async def test_a_low_week_is_noticed_without_alerting_anyone(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await consent(s)
    now = dt.datetime.now(dt.UTC)
    for d in range(1, 5):
        api_db.add(
            m.MoodEntry(
                id=uuid7(),
                institution_id=world.inst_a,
                student_id=s.id,
                mood_score=2,
                emotions=[],
                logged_at=now - dt.timedelta(days=d),
            )
        )
    await api_db.commit()
    out = await check_in(s, "exams went fine", mood=3)
    assert out["safety"]["level"] == "moderate"
    assert await alerts_for(api_db, s) == []


async def test_repeated_concerns_raise_one_alert_and_make_it_more_urgent(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await consent(s)
    await check_in(s, HIGH_NOTE)
    out = await check_in(s, IMMEDIATE_NOTE)
    assert out["safety"]["escalation"]["status"] == "already_open"
    (alert,) = await alerts_for(api_db, s)
    assert alert.severity is AlertSeverity.IMMINENT
    assert len(await events_for(api_db, s)) == 2


async def test_someone_else_in_danger_gets_guidance_for_helping_them(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await consent(s)
    out = await check_in(s, "my roommate is talking about suicide")
    assert out["safety"]["level"] == "moderate"
    assert out["safety"]["about_someone_else"] is True
    assert "worried about" in out["safety"]["guidance"]["title"].lower()
    assert await alerts_for(api_db, s) == []


# ---- the pause ends -------------------------------------------------------------------------


async def test_a_person_resolving_the_alert_ends_the_pause(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    s = pair.student
    await consent(s)
    await engine_suggestion(api_db, world, s)
    out = await check_in(s, HIGH_NOTE)
    assert out["safety"]["escalation"]["care_team_notified"] is True
    assert out["safety"]["counselling"]["has_care_team"] is True
    assert out["safety"]["counselling"]["message_path"] == "/student/messages"
    (alert,) = await alerts_for(api_db, s)
    assert "Take a short walk" not in await open_titles(s)

    # The therapist sees the alert, with its category and nothing that was written.
    listed = (await pair.therapist.get("/therapist/alerts")).json()
    mine = [a for a in listed if a["id"] == str(alert.id)]
    assert mine and mine[0]["source_label"] == "From a check-in"
    assert HIGH_NOTE not in str(listed)

    resolve = {"action": "resolve", "outcome": "contacted_student"}
    for action in ({"action": "acknowledge"}, resolve):
        r = await pair.therapist.patch(f"/therapist/alerts/{alert.id}", action)
        assert r.status_code == 200, r.text
    assert "Take a short walk" in await open_titles(s)
    assert (await s.get("/me/safety/status")).json()["recommendations_paused"] is False


async def test_the_pause_ends_by_itself_after_its_window(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await consent(s, granted=False)
    await engine_suggestion(api_db, world, s)
    await check_in(s, HIGH_NOTE)
    assert "Take a short walk" not in await open_titles(s)
    await api_db.execute(
        update(m.SafetyEvent)
        .where(m.SafetyEvent.student_id == s.id)
        .values(hold_until=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1))
    )
    await api_db.commit()
    assert "Take a short walk" in await open_titles(s)


# ---- messages and the companion -------------------------------------------------------------


async def test_a_student_message_to_their_therapist_is_checked(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    r = await pair.student.post(
        f"/me/conversations/{pair.therapist.id}/messages", {"body": HIGH_NOTE}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["safety"]["level"] == "high"
    assert body["safety"]["escalation"]["basis"] == "care_team_message"
    assert body["safety"]["escalation"]["status"] == "requested"
    (alert,) = await alerts_for(api_db, pair.student)
    assert alert.source is AlertSource.MESSAGE
    assert alert.source_type == "message" and alert.excerpt is None

    # A therapist's own words are never run through the student checks.
    r = await pair.therapist.post(
        f"/me/conversations/{pair.student.id}/messages",
        {"body": "Some students say they want to die; let's talk about what helps."},
    )
    assert r.status_code == 201, r.text
    assert r.json()["safety"] is None
    assert len(await alerts_for(api_db, pair.student)) == 1


async def test_a_companion_crisis_pauses_suggestions_too(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    # The companion is not configured in tests: a crisis is answered even then (ADR 0010).
    now = dt.datetime.now(dt.UTC)
    conv = m.AIConversation(
        id=uuid7(),
        institution_id=world.inst_a,
        student_id=s.id,
        status=AIConversationStatus.ACTIVE,
        started_at=now,
        expires_at=now + dt.timedelta(days=1),
    )
    api_db.add(conv)
    await api_db.commit()
    r = await s.post(f"/companion/conversations/{conv.id}/messages", {"content": IMMEDIATE_NOTE})
    assert r.status_code == 200, r.text
    assert r.json()["support"]["level"] == "crisis"
    (event,) = await events_for(api_db, s)
    assert event.source.value == "companion"
    assert event.risk_level.value == "immediate"
    assert event.basis.value == "companion_notice" and event.escalated
    assert (await s.get("/me/safety/status")).json()["recommendations_paused"] is True


# ---- minimum necessary logging ---------------------------------------------------------------


async def test_nothing_that_was_written_is_stored_by_the_safety_system(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await consent(s)
    marker = "zebracorn"  # a word that appears nowhere else
    await check_in(s, f"{IMMEDIATE_NOTE} {marker}")
    (event,) = await events_for(api_db, s)
    row = (
        await api_db.execute(
            text("SELECT to_jsonb(e)::text FROM safety.safety_events e WHERE id = :id"),
            {"id": event.id},
        )
    ).scalar_one()
    assert marker not in row and "kill" not in row
    assert "SI-" not in row and "IM-" not in row  # no matched rule ids either
    audit = (
        await api_db.execute(
            text(
                "SELECT coalesce(string_agg(details::text, ' '), '') FROM audit.audit_logs "
                "WHERE subject_student_id = :s"
            ),
            {"s": s.id},
        )
    ).scalar_one()
    assert marker not in audit and "kill" not in audit
    (alert,) = await alerts_for(api_db, s)
    assert alert.excerpt is None


async def test_the_student_can_see_their_own_safety_record_in_the_export(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await consent(s)
    await check_in(s, HIGH_NOTE)
    export = (await s.get("/me/privacy/export")).json()
    (row,) = export["safety_events"]
    assert row["risk_level"] == "high" and row["escalated"] is True
    assert set(row) == {
        "created_at",
        "source",
        "risk_level",
        "concern",
        "escalated",
        "basis",
        "recommendations_paused",
        "hold_until",
    }


async def test_old_events_are_swept(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await consent(s, granted=False)
    await check_in(s, HIGH_NOTE)
    later = dt.datetime.now(dt.UTC) + safety_workflow.EVENT_RETENTION + dt.timedelta(days=1)
    assert await safety_workflow.sweep_safety_events(api_db, later) >= 1
    assert await events_for(api_db, s) == []


# ---- fail safe ------------------------------------------------------------------------------


async def test_if_asking_a_person_fails_the_student_is_told_to_reach_out(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("notification store unavailable")

    monkeypatch.setattr(safety_workflow, "raise_or_reuse", broken)
    s = await new_student(client, api_db, world)
    await consent(s)
    out = await check_in(s, IMMEDIATE_NOTE)
    assert out["mood"]["mood_score"] == 3  # the check-in itself was saved
    assert out["safety"]["level"] == "immediate"
    assert out["safety"]["escalation"]["status"] == "failed"
    assert out["safety"]["offer_outreach"] is True
    assert out["safety"]["resources"]
    assert await alerts_for(api_db, s) == []
    (event,) = await events_for(api_db, s)
    assert event.escalated is False  # recorded honestly
    assert (await s.get("/me/safety/status")).json()["recommendations_paused"] is True


async def test_if_contacts_cannot_be_loaded_the_built_in_entry_is_shown(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("contacts table unavailable")

    monkeypatch.setattr(safety_workflow, "crisis_contacts", broken)
    s = await new_student(client, api_db, world)
    out = await check_in(s, IMMEDIATE_NOTE)
    (only,) = out["safety"]["resources"]
    assert only["id"] is None and only["kind"] == "emergency"
    assert "emergency number" in only["description"]


async def test_if_the_whole_workflow_fails_support_is_still_shown(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("database gone")

    monkeypatch.setattr(safety_workflow.WORKFLOW, "handle", broken)
    s = await new_student(client, api_db, world)
    await consent(s)
    out = await check_in(s, HIGH_NOTE)
    assert out["safety"]["level"] == "high"
    assert out["safety"]["escalation"]["status"] == "failed"
    assert out["safety"]["offer_outreach"] is True
    assert out["safety"]["resources"][0]["kind"] == "emergency"


async def test_no_configured_contacts_still_shows_somewhere_to_turn(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def none(*_: Any, **__: Any) -> list[m.CrisisContact]:
        return []

    monkeypatch.setattr(safety_workflow, "crisis_contacts", none)
    s = await new_student(client, api_db, world)
    out = await check_in(s, MODERATE_NOTE)
    assert [r["label"] for r in out["safety"]["resources"]] == ["Local emergency services"]


# ---- who can see it -------------------------------------------------------------------------


async def test_the_status_is_the_callers_own_and_students_only(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await consent(s, granted=False)
    await check_in(s, HIGH_NOTE)
    other = await new_student(client, api_db, world)
    assert (await other.get("/me/safety/status")).json()["recommendations_paused"] is False

    pair = await care_pair(client, api_db, world)
    for staff in (pair.therapist,):
        r = await staff.get("/me/safety/status")
        assert r.status_code == 403
