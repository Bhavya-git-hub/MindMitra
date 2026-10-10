"""The AI companion through the API: normal conversations, crisis escalation (with and without
a care team, with the AI service down, switched off or over the limit), gentle support,
limits, privacy, retention and deletion.

The AI service is replaced by ``FakeCompanion``; the real service has its own tests
(``services/ml/tests``) and the end-to-end run uses both together.
"""

import datetime as dt
import uuid
from collections.abc import AsyncIterator, Sequence

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.main import create_app
from app.api.rate_limit import SlidingWindowRateLimiter
from app.application.auth.delivery import InMemoryTokenOutbox
from app.application.companion import sweep_expired
from app.core.config import get_settings
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AlertCategory,
    AlertDetector,
    AlertSeverity,
    AlertSource,
    AuditOutcome,
    NotificationType,
)
from app.infrastructure.db.ids import uuid7
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.ml_client import (
    CompanionReply,
    CompanionUnavailable,
    HistoryTurn,
    ServiceCrisis,
)
from tests.api_world import World
from tests.student_helpers import Session, new_student, sign_in
from tests.therapist_helpers import care_pair, fresh_admin, fresh_therapist

NONE = ServiceCrisis("none", None, None, (), False)


class FakeCompanion:
    """Stands in for the AI service. ``mode`` decides what it answers."""

    def __init__(self) -> None:
        self.mode = "reply"
        self.calls: list[tuple[str, list[HistoryTurn]]] = []

    async def respond(self, message: str, history: Sequence[HistoryTurn]) -> CompanionReply:
        self.calls.append((message, list(history)))
        if self.mode == "down":
            raise CompanionUnavailable("unreachable")
        if self.mode == "crisis":  # e.g. a classifier caught what the rules did not
            return CompanionReply(
                "crisis",
                None,
                ServiceCrisis("escalate", "self_harm", "high", ("CLF",), False),
                "general",
                ("crisis", "classifier"),
                "fake|p|r",
            )
        crisis = NONE
        if self.mode == "review":
            crisis = ServiceCrisis("review", "distress_signal", "low", ("RV-HOPELESS",), False)
        if self.mode == "third_person":
            crisis = ServiceCrisis("review", "concern_for_other", "low", ("SI-SUICIDE",), True)
        return CompanionReply(
            "reply",
            "That sounds like a lot. What feels most pressing right now?",
            crisis,
            "academic_stress",
            (),
            "fake-companion-1|companion-prompt-x|crisis-rules-x",
        )

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake() -> FakeCompanion:
    return FakeCompanion()


def _app(api_engine: AsyncEngine, fake: FakeCompanion | None, *, per_minute: int = 1000) -> FastAPI:
    get_settings.cache_clear()
    return create_app(
        get_settings(),
        session_factory=create_session_factory(api_engine),
        delivery=InMemoryTokenOutbox(),
        limiter=SlidingWindowRateLimiter(1_000_000),
        companion_client=fake,
        companion_limiter=SlidingWindowRateLimiter(per_minute),
    )


async def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=("203.0.113.20", 50000))
    return httpx.AsyncClient(transport=transport, base_url="https://testserver")


@pytest_asyncio.fixture
async def cc(api_engine: AsyncEngine, fake: FakeCompanion) -> AsyncIterator[httpx.AsyncClient]:
    """A client for an API whose AI service is ``fake``."""
    async with await _client(_app(api_engine, fake)) as c:
        yield c


async def _start(s: Session) -> str:
    r = await s.post("/companion/conversations")
    assert r.status_code == 201, r.text
    conv_id: str = r.json()["id"]
    return conv_id


async def _say(s: Session, conv: str, content: str) -> httpx.Response:
    return await s.post(f"/companion/conversations/{conv}/messages", {"content": content})


async def _alerts(db: AsyncSession, student_id: uuid.UUID) -> list[m.RiskAlert]:
    db.expire_all()
    rows = await db.scalars(
        select(m.RiskAlert)
        .where(m.RiskAlert.student_id == student_id, m.RiskAlert.source == AlertSource.AI_CHAT)
        .order_by(m.RiskAlert.created_at)
    )
    return list(rows)


async def _alert_notifications(db: AsyncSession, user_id: uuid.UUID) -> list[m.Notification]:
    db.expire_all()
    rows = await db.scalars(
        select(m.Notification).where(
            m.Notification.user_id == user_id,
            m.Notification.type == NotificationType.RISK_ALERT,
        )
    )
    return list(rows)


# ---- normal conversations -------------------------------------------------------------------


async def test_a_normal_conversation(
    cc: httpx.AsyncClient, api_db: AsyncSession, world: World, fake: FakeCompanion
) -> None:
    s = await new_student(cc, api_db, world)
    status = (await s.get("/companion/status")).json()
    assert status["available"] is True
    assert status["reason"] is None
    assert "not a therapist" in status["disclaimer"]
    assert status["remaining_today"] == status["daily_limit"] == 100

    conv = await _start(s)
    r = await _say(s, conv, "  Exams next week are stressing me out  ")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["message"]["content"] == "Exams next week are stressing me out"
    assert body["message"]["role"] == "user" and body["message"]["kind"] is None
    assert body["reply"]["role"] == "assistant" and body["reply"]["kind"] == "reply"
    assert body["reply"]["content"].startswith("That sounds like a lot.")
    assert body["reply"]["seq"] == body["message"]["seq"] + 1
    assert body["support"] is None
    assert "not a therapist" in body["disclaimer"]

    await _say(s, conv, "I just can't start")
    message, history = fake.calls[-1]
    assert message == "I just can't start"
    assert [t.role for t in history] == ["user", "assistant"]
    assert history[0].content == "Exams next week are stressing me out"

    detail = (await s.get(f"/companion/conversations/{conv}")).json()
    assert [x["seq"] for x in detail["messages"]] == [1, 2, 3, 4]
    listed = (await s.get("/companion/conversations")).json()
    assert listed[0]["id"] == conv
    assert (await s.get("/me/ai-conversations")).json()[0]["id"] == conv
    assert (await s.get("/companion/status")).json()["remaining_today"] == 98

    # Stored encrypted: the raw column never holds the words.
    raw = await api_db.scalar(
        text("SELECT content FROM ai.ai_messages WHERE conversation_id = :c AND seq = 1"),
        {"c": conv},
    )
    assert raw is not None and "Exams" not in str(raw)
    assert await _alerts(api_db, s.id) == []


async def test_the_ai_service_being_down_gives_a_fixed_reply(
    cc: httpx.AsyncClient, api_db: AsyncSession, world: World, fake: FakeCompanion
) -> None:
    s = await new_student(cc, api_db, world)
    conv = await _start(s)
    fake.mode = "down"
    r = await _say(s, conv, "placements are worrying me")
    assert r.status_code == 200
    assert r.json()["reply"]["kind"] == "unavailable"
    assert "Get help now" in r.json()["reply"]["content"]
    fake.mode = "reply"
    await _say(s, conv, "still there?")
    # The failed exchange is not sent as context.
    assert [t.content for t in fake.calls[-1][1]] == ["placements are worrying me"]


# ---- crisis ---------------------------------------------------------------------------------


async def test_a_crisis_message_alerts_the_care_team_and_never_reaches_the_model(
    cc: httpx.AsyncClient, api_db: AsyncSession, world: World, fake: FakeCompanion
) -> None:
    pair = await care_pair(cc, api_db, world)
    s = await sign_in(cc, pair.student.actor, world.password)
    conv = await _start(s)
    r = await _say(s, conv, "I'm going to kill myself tonight")
    assert r.status_code == 200, r.text
    body = r.json()
    assert fake.calls == []
    assert body["reply"]["kind"] == "crisis"
    assert body["reply"]["show_support"] is True
    assert "counsellor know" in body["reply"]["content"]
    assert body["message"]["show_support"] is False
    support = body["support"]
    assert support["level"] == "crisis" and support["escalated"] is True
    assert support["care_team_notified"] is True
    assert support["contacts"] and all("label" in c for c in support["contacts"])
    assert body["conversation"]["status"] == "crisis_handoff"

    [alert] = await _alerts(api_db, s.id)
    assert alert.assigned_to == pair.therapist.id
    assert alert.category is AlertCategory.SUICIDAL_LANGUAGE
    assert alert.severity is AlertSeverity.IMMINENT
    assert alert.detector is AlertDetector.RULES
    assert alert.source_type == "ai_conversation" and str(alert.source_id) == conv
    assert alert.excerpt is None  # the alert never carries what was written
    assert alert.model_version and alert.model_version.startswith("crisis-rules-")
    assert alert.sla_ack_due_at is not None
    assert alert.sla_ack_due_at - alert.created_at <= dt.timedelta(minutes=5, seconds=5)

    [note] = await _alert_notifications(api_db, pair.therapist.id)
    assert note.title == "A student may need support now"
    assert set(note.payload) == {"alert_id"}

    audit = await api_db.scalar(
        select(m.AuditLog).where(
            m.AuditLog.action == "ai_conversation.crisis",
            m.AuditLog.subject_student_id == s.id,
        )
    )
    assert audit is not None and audit.outcome is AuditOutcome.ALLOWED
    assert "kill" not in str(audit.details)

    # Reloading the conversation still shows the crisis reply with its contacts flag.
    detail = (await s.get(f"/companion/conversations/{conv}")).json()
    assert [x["kind"] for x in detail["messages"]] == [None, "crisis"]
    assert detail["messages"][1]["show_support"] is True


async def test_with_no_care_team_the_whole_counselling_team_is_alerted(
    cc: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    on_team = await fresh_therapist(cc, api_db, world)
    unverified = await fresh_therapist(cc, api_db, world, verified=False)
    elsewhere = await fresh_therapist(cc, api_db, world, other_tenant=True)
    s = await new_student(cc, api_db, world)
    conv = await _start(s)
    r = await _say(s, conv, "I don't feel safe at home")
    body = r.json()
    assert body["support"]["care_team_notified"] is False
    assert "counselling team know" in body["reply"]["content"]

    [alert] = await _alerts(api_db, s.id)
    alert_id = str(alert.id)
    assert alert.assigned_to is None
    assert alert.category is AlertCategory.UNSAFE_SITUATION
    assert len(await _alert_notifications(api_db, on_team.id)) == 1
    assert await _alert_notifications(api_db, unverified.id) == []
    assert await _alert_notifications(api_db, elsewhere.id) == []

    # Any verified therapist at the institution sees it; the first to acknowledge takes it.
    listed = (await on_team.get("/therapist/alerts")).json()
    assert alert_id in {a["id"] for a in listed}
    ack = await on_team.patch(f"/therapist/alerts/{alert_id}", {"action": "acknowledge"})
    assert ack.status_code == 200, ack.text
    assert ack.json()["assigned_to_me"] is True
    other = await fresh_therapist(cc, api_db, world)
    assert alert_id not in {a["id"] for a in (await other.get("/therapist/alerts")).json()}
    assert (await elsewhere.get("/therapist/alerts")).json() == []


async def test_repeated_crisis_messages_raise_one_alert_and_escalate_it(
    cc: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    team = await fresh_therapist(cc, api_db, world)
    s = await new_student(cc, api_db, world)
    conv = await _start(s)
    await _say(s, conv, "I want to hurt my roommate")
    [alert] = await _alerts(api_db, s.id)
    assert alert.severity is AlertSeverity.MODERATE
    r = await _say(s, conv, "I can't go on")
    assert "already knows" in r.json()["reply"]["content"]
    assert len(await _alerts(api_db, s.id)) == 1
    await _say(s, conv, "I have saved up pills and I want to die")
    [alert] = await _alerts(api_db, s.id)
    assert alert.severity is AlertSeverity.IMMINENT
    assert len(await _alert_notifications(api_db, team.id)) == 2  # first alert, then raised


async def test_a_crisis_the_ai_service_finds_is_escalated_too(
    cc: httpx.AsyncClient, api_db: AsyncSession, world: World, fake: FakeCompanion
) -> None:
    s = await new_student(cc, api_db, world)
    conv = await _start(s)
    fake.mode = "crisis"
    r = await _say(s, conv, "everything is too much and I have a plan")
    body = r.json()
    assert body["reply"]["kind"] == "crisis"
    assert body["support"]["level"] == "crisis" and body["support"]["contacts"]
    [alert] = await _alerts(api_db, s.id)
    assert alert.detector is AlertDetector.CLASSIFIER
    assert alert.category is AlertCategory.SELF_HARM_LANGUAGE
    detail = (await s.get(f"/companion/conversations/{conv}")).json()
    assert detail["messages"][0]["kind"] is None
    # The flagged message is kept out of later context.
    fake.mode = "reply"
    await _say(s, conv, "ok")
    assert fake.calls[-1][1] == []


async def test_crisis_handling_does_not_depend_on_the_ai_service(
    client: httpx.AsyncClient, cc: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """``client`` talks to an API with no AI service configured at all."""
    s = await new_student(cc, api_db, world)
    conv = await _start(s)
    no_ml = await sign_in(client, s.actor, world.password)
    assert (await no_ml.get("/companion/status")).json()["reason"] == "not_configured"
    assert (await no_ml.post("/companion/conversations")).status_code == 503
    assert (await _say(no_ml, conv, "exams")).status_code == 503
    r = await _say(no_ml, conv, "I want to end my life")
    assert r.status_code == 200
    assert r.json()["reply"]["kind"] == "crisis"
    assert len(await _alerts(api_db, s.id)) == 1


async def test_crisis_gets_through_when_switched_off_or_over_the_limit(
    api_engine: AsyncEngine, api_db: AsyncSession, world: World, fake: FakeCompanion
) -> None:
    async with await _client(_app(api_engine, fake, per_minute=1)) as c:
        s = await new_student(c, api_db, world)
        conv = await _start(s)
        assert (await _say(s, conv, "first")).status_code == 200
        limited = await _say(s, conv, "second")
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) >= 1
        assert "quickly" in limited.json()["detail"]
        r = await _say(s, conv, "please call someone")
        assert r.status_code == 200 and r.json()["reply"]["kind"] == "crisis"


# ---- gentle support -------------------------------------------------------------------------


async def test_low_moments_offer_contacts_without_an_alert(
    cc: httpx.AsyncClient, api_db: AsyncSession, world: World, fake: FakeCompanion
) -> None:
    s = await new_student(cc, api_db, world)
    conv = await _start(s)
    fake.mode = "review"
    r = await _say(s, conv, "I feel so hopeless about everything")
    body = r.json()
    assert body["reply"]["kind"] == "reply"
    assert body["reply"]["show_support"] is True
    assert body["support"]["level"] == "gentle"
    assert body["support"]["escalated"] is False
    assert body["support"]["contacts"]
    assert await _alerts(api_db, s.id) == []


async def test_worry_about_someone_else_gets_guidance_not_an_alert(
    cc: httpx.AsyncClient, api_db: AsyncSession, world: World, fake: FakeCompanion
) -> None:
    s = await new_student(cc, api_db, world)
    conv = await _start(s)
    fake.mode = "third_person"
    r = await _say(s, conv, "my friend is suicidal, what do I do")
    body = r.json()
    assert body["support"]["about_someone_else"] is True
    assert body["reply"]["content"].startswith("It sounds like you're worried about someone.")
    assert await _alerts(api_db, s.id) == []


# ---- limits and switches --------------------------------------------------------------------


async def test_the_daily_limit(cc: httpx.AsyncClient, api_db: AsyncSession, world: World) -> None:
    s = await new_student(cc, api_db, world)
    conv = await _start(s)
    now = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
    for seq in range(1, 201, 2):  # 100 earlier exchanges today
        api_db.add_all(
            [
                m.AIMessage(
                    id=uuid7(),
                    conversation_id=uuid.UUID(conv),
                    seq=seq,
                    role="user",
                    content="earlier",
                    created_at=now,
                ),
                m.AIMessage(
                    id=uuid7(),
                    conversation_id=uuid.UUID(conv),
                    seq=seq + 1,
                    role="assistant",
                    content="reply",
                    reply_kind="reply",
                    created_at=now,
                ),
            ]
        )
    await api_db.commit()
    assert (await s.get("/companion/status")).json()["remaining_today"] == 0
    r = await _say(s, conv, "one more")
    assert r.status_code == 429
    assert "today's message limit" in r.json()["detail"]
    assert (await _say(s, conv, "I want to die")).json()["reply"]["kind"] == "crisis"


async def test_an_institution_can_switch_the_companion_off(
    cc: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    admin = await fresh_admin(cc, api_db, world)
    s = await new_student(cc, api_db, world)
    conv = await _start(s)
    r = await admin.patch("/admin/settings/safety", {"companion_enabled": False})
    assert r.status_code == 200, r.text
    assert r.json()["values"]["companion_enabled"] is False
    try:
        status = (await s.get("/companion/status")).json()
        assert status["available"] is False and status["reason"] == "switched_off"
        assert (await s.post("/companion/conversations")).status_code == 503
        off = await _say(s, conv, "hello")
        assert off.status_code == 503
        assert off.json()["detail"] == "The companion has been switched off."
        assert (await _say(s, conv, "I want to kill myself")).status_code == 200
        bad = await admin.patch("/admin/settings/safety", {"companion_daily_messages": 5})
        assert bad.status_code == 422
    finally:
        await admin.patch("/admin/settings/safety", {"companion_enabled": True})


async def test_deployment_can_switch_the_companion_off_everywhere(
    api_engine: AsyncEngine,
    api_db: AsyncSession,
    world: World,
    fake: FakeCompanion,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPANION_ENABLED", "false")
    async with await _client(_app(api_engine, fake)) as c:
        s = await new_student(c, api_db, world)
        assert (await s.get("/companion/status")).json()["reason"] == "switched_off"
        assert (await s.post("/companion/conversations")).status_code == 503


async def test_one_message_at_a_time(
    cc: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(cc, api_db, world)
    conv = await _start(s)
    api_db.add(
        m.AIMessage(
            id=uuid7(),
            conversation_id=uuid.UUID(conv),
            seq=1,
            role="user",
            content="waiting",
            created_at=dt.datetime.now(dt.UTC),
        )
    )
    await api_db.commit()
    r = await _say(s, conv, "hello?")
    assert r.status_code == 409


@pytest.mark.parametrize("content", ["", "   ", "x" * 2001])
async def test_invalid_messages(
    cc: httpx.AsyncClient, api_db: AsyncSession, world: World, content: str
) -> None:
    s = await new_student(cc, api_db, world)
    conv = await _start(s)
    assert (await _say(s, conv, content)).status_code == 422


# ---- privacy --------------------------------------------------------------------------------


async def test_only_the_owner_can_reach_a_conversation(
    cc: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    owner = await new_student(cc, api_db, world)
    conv = await _start(owner)
    await _say(owner, conv, "private exam worries")
    other = await new_student(cc, api_db, world)
    foreign = await new_student(cc, api_db, world, other_tenant=True)
    for intruder in (other, foreign):
        assert (await intruder.get(f"/companion/conversations/{conv}")).status_code == 404
        assert (await _say(intruder, conv, "hi")).status_code == 404
        assert (await intruder.delete(f"/companion/conversations/{conv}")).status_code == 404
        assert conv not in {
            c["id"] for c in (await intruder.get("/companion/conversations")).json()
        }

    therapist = await fresh_therapist(cc, api_db, world)
    admin = await fresh_admin(cc, api_db, world)
    teacher = await sign_in(cc, world.teacher, world.password)
    for staff in (therapist, admin, teacher):
        assert (await staff.get("/companion/status")).status_code == 403
        assert (await staff.get("/companion/conversations")).status_code == 403
        assert (await staff.post("/companion/conversations")).status_code == 403
        assert (await staff.get(f"/companion/conversations/{conv}")).status_code == 403
        assert (await _say(staff, conv, "hi")).status_code == 403
        assert (await staff.delete(f"/companion/conversations/{conv}")).status_code == 403


async def test_deleting_removes_the_conversation_but_keeps_the_alert(
    cc: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(cc, api_db, world)
    conv = await _start(s)
    await _say(s, conv, "I want to die")
    assert (await s.delete(f"/companion/conversations/{conv}")).status_code == 204
    assert (await s.get(f"/companion/conversations/{conv}")).status_code == 404
    left = await api_db.scalar(
        select(func.count())
        .select_from(m.AIMessage)
        .where(m.AIMessage.conversation_id == uuid.UUID(conv))
    )
    assert left == 0
    assert len(await _alerts(api_db, s.id)) == 1


async def test_retention_follows_the_history_consent(
    cc: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(cc, api_db, world)
    status = (await s.get("/companion/status")).json()
    assert status["keeps_history"] is False and status["retention_hours"] == 24
    short = (await s.post("/companion/conversations")).json()
    expires = dt.datetime.fromisoformat(short["expires_at"])
    assert dt.timedelta(hours=23) < expires - dt.datetime.now(dt.UTC) <= dt.timedelta(hours=24)

    assert (await s.put("/me/consents/ai_companion_history", {"granted": True})).status_code == 200
    assert (await s.get("/companion/status")).json()["retention_hours"] == 90 * 24
    long = (await s.post("/companion/conversations")).json()
    expires = dt.datetime.fromisoformat(long["expires_at"])
    assert expires - dt.datetime.now(dt.UTC) > dt.timedelta(days=89)

    # Past its retention, a conversation is gone from view at once and deleted by the sweep.
    await api_db.execute(
        update(m.AIConversation)
        .where(m.AIConversation.id == uuid.UUID(short["id"]))
        .values(
            started_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=2),
            expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1),
        )
    )
    await api_db.commit()
    assert (await s.get(f"/companion/conversations/{short['id']}")).status_code == 404
    assert short["id"] not in {c["id"] for c in (await s.get("/companion/conversations")).json()}
    assert await sweep_expired(api_db) >= 1
    assert await api_db.get(m.AIConversation, uuid.UUID(short["id"])) is None
    assert await api_db.get(m.AIConversation, uuid.UUID(long["id"])) is not None
