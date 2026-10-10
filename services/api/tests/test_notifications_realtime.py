"""Notification generation, external delivery with retries, appointment reminders, events that
wait for commit, the real-time hub, and the WebSocket handshake."""

import asyncio
import contextlib
import dataclasses
import datetime as dt
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.api import realtime
from app.api.deps import AppState
from app.application import notifications
from app.application.reminders import send_due_reminders
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AppointmentStatus,
    DeliveryStatus,
    NotificationChannel,
    NotificationType,
    UserStatus,
)
from app.infrastructure.db.ids import uuid7
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.events import Event, queue_event, set_broker
from app.infrastructure.notifications.providers import (
    SUBJECT,
    TEXT,
    DeliveryError,
    InMemoryProvider,
    build_providers,
)
from app.infrastructure.realtime_hub import QUEUE_SIZE, Hub
from tests.api_world import World
from tests.student_helpers import new_student
from tests.therapist_helpers import care_pair, due_appointment

pytestmark = pytest.mark.asyncio


@pytest.fixture
def factory(api_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(api_engine)


@contextlib.asynccontextmanager
async def institution_notifications(
    db: AsyncSession, institution_id: uuid.UUID, **values: object
) -> AsyncIterator[None]:
    """Temporarily change an institution's notification settings."""
    row = await db.scalar(
        select(m.InstitutionSettings).where(m.InstitutionSettings.institution_id == institution_id)
    )
    created = row is None
    if row is None:
        row = m.InstitutionSettings(id=uuid7(), institution_id=institution_id, notifications={})
        db.add(row)
    before = dict(row.notifications or {})
    row.notifications = {**before, **values}
    await db.commit()
    try:
        yield
    finally:
        if created:
            await db.delete(row)
        else:
            row.notifications = before
        await db.commit()


async def _notify(
    factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, inst: uuid.UUID
) -> uuid.UUID:
    async with factory() as db:
        note = await notifications.notify(
            db,
            institution_id=inst,
            user_id=user_id,
            type=NotificationType.SYSTEM,
            title="Something changed",
            payload={"event": "test"},
        )
        await db.commit()
        return note.id


async def _delivery(db: AsyncSession, notification_id: uuid.UUID) -> m.Delivery | None:
    db.expire_all()
    return await db.scalar(select(m.Delivery).where(m.Delivery.notification_id == notification_id))


# ---- notification generation -------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"student_name": "Asha"},  # not an allowed key
        {"appointment_id": "not-a-uuid"},  # identifiers only
        {"event": "Your therapist said hello"},  # free text in the event name
        {"event": ""},
    ],
)
async def test_notification_payloads_hold_ids_and_fixed_words_only(
    api_db: AsyncSession, world: World, payload: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        await notifications.notify(
            api_db,
            institution_id=world.inst_a,
            user_id=world.student.user_id,
            type=NotificationType.SYSTEM,
            title="t",
            payload=payload,
        )
    await api_db.rollback()


@pytest.mark.parametrize("title", ["", "x" * 161])
async def test_notification_titles_are_bounded(
    api_db: AsyncSession, world: World, title: str
) -> None:
    with pytest.raises(ValueError):
        await notifications.notify(
            api_db,
            institution_id=world.inst_a,
            user_id=world.student.user_id,
            type=NotificationType.SYSTEM,
            title=title,
        )
    await api_db.rollback()


async def test_every_communication_event_creates_a_notification(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Booking, confirming, messaging and cancelling each leave a notification for the other
    person, and none of them for the person who acted."""
    pair = await care_pair(client, api_db, world, mood=False)
    appts = (await pair.student.get("/me/appointments")).json()
    first = appts[0]["id"]
    await pair.student.post(f"/me/conversations/{pair.therapist.id}/messages", {"body": "hi"})
    await pair.therapist.patch(f"/appointments/{first}", {"status": "cancelled"})
    api_db.expire_all()

    async def kinds(user_id: uuid.UUID) -> list[tuple[NotificationType, str | None]]:
        rows = await api_db.scalars(
            select(m.Notification)
            .where(m.Notification.user_id == user_id)
            .order_by(m.Notification.created_at)
        )
        return [(n.type, n.payload.get("event")) for n in rows]

    assert await kinds(pair.therapist.id) == [
        (NotificationType.APPOINTMENT_UPDATE, "requested"),
        (NotificationType.NEW_MESSAGE, None),
    ]
    assert await kinds(pair.student.id) == [
        (NotificationType.APPOINTMENT_UPDATE, "confirmed"),
        (NotificationType.APPOINTMENT_UPDATE, "cancelled"),
    ]


async def test_email_deliveries_are_created_only_when_the_institution_switches_email_on(
    api_db: AsyncSession, world: World, factory: async_sessionmaker[AsyncSession]
) -> None:
    off = await _notify(factory, world.other_student.user_id, world.inst_a)
    assert await _delivery(api_db, off) is None
    async with institution_notifications(api_db, world.inst_a, email_enabled=True):
        on = await _notify(factory, world.other_student.user_id, world.inst_a)
    d = await _delivery(api_db, on)
    assert d is not None
    assert d.channel is NotificationChannel.EMAIL and d.status is DeliveryStatus.PENDING
    assert d.user_id == world.other_student.user_id and d.attempts == 0


# ---- external delivery -------------------------------------------------------------------------


@pytest.fixture
async def pending(
    api_db: AsyncSession, world: World, factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[uuid.UUID]:
    """A pending e-mail delivery to a fresh student; yields its notification id."""
    async with institution_notifications(api_db, world.inst_a, email_enabled=True):
        user = world.other_student.user_id
        yield await _notify(factory, user, world.inst_a)


async def test_a_delivery_is_sent_once_with_the_content_free_template(
    api_db: AsyncSession, factory: async_sessionmaker[AsyncSession], pending: uuid.UUID
) -> None:
    provider = InMemoryProvider()
    providers = {NotificationChannel.EMAIL: provider}
    result = await notifications.dispatch_due(factory, providers)
    assert result.sent >= 1
    d = await _delivery(api_db, pending)
    assert d is not None and d.status is DeliveryStatus.SENT and d.sent_at is not None
    sent = [x for x in provider.sent if x.delivery_id == d.id]
    assert len(sent) == 1
    assert sent[0].subject == SUBJECT and sent[0].text == TEXT
    assert "Something changed" not in sent[0].text  # not even the title leaves the app
    await notifications.dispatch_due(factory, providers)
    assert len([x for x in provider.sent if x.delivery_id == d.id]) == 1


async def test_a_temporary_failure_is_retried_later_then_sent(
    api_db: AsyncSession, factory: async_sessionmaker[AsyncSession], pending: uuid.UUID
) -> None:
    provider = InMemoryProvider()
    provider.fail_with = DeliveryError("smtp_timeout", retryable=True)
    providers = {NotificationChannel.EMAIL: provider}
    now = dt.datetime.now(dt.UTC)
    await notifications.dispatch_due(factory, providers, now=now)
    d = await _delivery(api_db, pending)
    assert d is not None and d.status is DeliveryStatus.PENDING
    assert d.attempts == 1 and d.last_error == "smtp_timeout"
    assert d.next_attempt_at == now + notifications.BACKOFF[0]
    provider.fail_with = None
    await notifications.dispatch_due(factory, providers, now=now + dt.timedelta(seconds=30))
    assert [x for x in provider.sent if x.delivery_id == d.id] == []  # not due yet
    await notifications.dispatch_due(factory, providers, now=now + dt.timedelta(minutes=2))
    d = await _delivery(api_db, pending)
    assert d is not None and d.status is DeliveryStatus.SENT and d.attempts == 2
    assert d.last_error is None


async def test_permanent_failures_and_too_many_attempts_give_up(
    api_db: AsyncSession, factory: async_sessionmaker[AsyncSession], pending: uuid.UUID
) -> None:
    provider = InMemoryProvider()
    providers = {NotificationChannel.EMAIL: provider}
    provider.fail_with = DeliveryError("smtp_timeout", retryable=True)
    at = dt.datetime.now(dt.UTC)
    for _ in range(notifications.MAX_ATTEMPTS):
        await notifications.dispatch_due(factory, providers, now=at)
        at += dt.timedelta(hours=3)
    d = await _delivery(api_db, pending)
    assert d is not None and d.status is DeliveryStatus.FAILED
    assert d.attempts == notifications.MAX_ATTEMPTS


async def test_a_permanent_failure_is_not_retried(
    api_db: AsyncSession, factory: async_sessionmaker[AsyncSession], pending: uuid.UUID
) -> None:
    provider = InMemoryProvider()
    provider.fail_with = DeliveryError("address_rejected", retryable=False)
    await notifications.dispatch_due(factory, {NotificationChannel.EMAIL: provider})
    d = await _delivery(api_db, pending)
    assert d is not None and d.status is DeliveryStatus.FAILED and d.attempts == 1
    assert d.last_error == "address_rejected"


async def test_without_a_provider_deliveries_are_recorded_as_skipped(
    api_db: AsyncSession, factory: async_sessionmaker[AsyncSession], pending: uuid.UUID
) -> None:
    assert build_providers("none") == {}
    result = await notifications.dispatch_due(factory, build_providers("none"))
    assert result.skipped >= 1
    d = await _delivery(api_db, pending)
    assert d is not None and d.status is DeliveryStatus.SKIPPED and d.last_error == "no_provider"


async def test_a_suspended_recipient_gets_no_email(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    s = await new_student(client, api_db, world)
    async with institution_notifications(api_db, world.inst_a, email_enabled=True):
        note = await _notify(factory, s.id, world.inst_a)
    user = await api_db.get(m.User, s.id)
    assert user is not None
    user.status = UserStatus.SUSPENDED
    await api_db.commit()
    provider = InMemoryProvider()
    await notifications.dispatch_due(factory, {NotificationChannel.EMAIL: provider})
    d = await _delivery(api_db, note)
    assert d is not None and d.status is DeliveryStatus.SKIPPED
    assert d.last_error == "recipient_inactive"
    assert all(x.delivery_id != d.id for x in provider.sent)


# ---- appointment reminders ---------------------------------------------------------------------


async def _reminders(db: AsyncSession, appointment_id: uuid.UUID) -> list[m.Notification]:
    db.expire_all()
    return list(
        await db.scalars(
            select(m.Notification).where(
                m.Notification.type == NotificationType.APPOINTMENT_REMINDER,
                m.Notification.payload["appointment_id"].astext == str(appointment_id),
            )
        )
    )


async def test_reminders_go_to_both_people_once(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    pair = await care_pair(client, api_db, world, mood=False)
    appt_id = await due_appointment(api_db, pair, starts_in=dt.timedelta(hours=30))
    appt = await api_db.get(m.Appointment, appt_id)
    assert appt is not None
    starts = appt.starts_at
    # nothing is due 30 hours before
    await send_due_reminders(factory)
    assert await _reminders(api_db, appt_id) == []
    # 23 hours before: the 24-hour reminder, to the student and the therapist
    at = starts - dt.timedelta(hours=23)
    await send_due_reminders(factory, now=at)
    await send_due_reminders(factory, now=at + dt.timedelta(minutes=1))  # a second pass: nothing
    first = await _reminders(api_db, appt_id)
    assert {n.user_id for n in first} == {pair.student.id, pair.therapist.id} and len(first) == 2
    assert {n.title for n in first} == {"You have an appointment coming up"}
    # 1 hour before: the 2-hour reminder
    await send_due_reminders(factory, now=starts - dt.timedelta(hours=1))
    assert len(await _reminders(api_db, appt_id)) == 4
    recorded = await api_db.scalars(
        select(m.AppointmentReminder.offset_hours).where(
            m.AppointmentReminder.appointment_id == appt_id
        )
    )
    assert sorted(recorded) == [2, 24]


async def test_a_late_confirmation_gets_one_reminder_not_one_per_offset(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    pair = await care_pair(client, api_db, world, mood=False)
    appt_id = await due_appointment(api_db, pair, starts_in=dt.timedelta(minutes=90))
    await send_due_reminders(factory)
    assert len(await _reminders(api_db, appt_id)) == 2  # one each, though both offsets passed


async def test_moving_an_appointment_gives_the_new_time_its_own_reminders(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    pair = await care_pair(client, api_db, world, mood=False)
    appt_id = await due_appointment(api_db, pair, starts_in=dt.timedelta(minutes=90))
    await send_due_reminders(factory)
    appt = await api_db.get(m.Appointment, appt_id)
    assert appt is not None
    appt.starts_at += dt.timedelta(hours=3)
    appt.ends_at += dt.timedelta(hours=3)
    await api_db.commit()
    await send_due_reminders(factory)
    assert len(await _reminders(api_db, appt_id)) == 4


async def test_no_reminders_for_unconfirmed_or_cancelled_or_when_switched_off(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    pair = await care_pair(client, api_db, world, mood=False)
    requested = await due_appointment(
        api_db, pair, starts_in=dt.timedelta(hours=1), status=AppointmentStatus.REQUESTED
    )
    cancelled = await due_appointment(
        api_db, pair, starts_in=dt.timedelta(hours=3), status=AppointmentStatus.CANCELLED
    )
    confirmed = await due_appointment(api_db, pair, starts_in=dt.timedelta(hours=5))
    async with institution_notifications(api_db, world.inst_a, reminders_enabled=False):
        await send_due_reminders(factory)
    for appt in (requested, cancelled, confirmed):
        assert await _reminders(api_db, appt) == []


# ---- events wait for the commit ----------------------------------------------------------------


@dataclasses.dataclass
class Recorder:
    events: list[tuple[uuid.UUID, Event]] = dataclasses.field(default_factory=list)

    def publish(self, user_id: uuid.UUID, payload: Event) -> None:
        self.events.append((user_id, payload))


@pytest.fixture
def recorder(api_app: FastAPI) -> Iterator[Recorder]:
    rec = Recorder()
    set_broker(rec)
    yield rec
    set_broker(api_app.state.mm.hub)


async def test_events_are_published_after_commit_and_dropped_on_rollback(
    factory: async_sessionmaker[AsyncSession], recorder: Recorder
) -> None:
    user = uuid.uuid4()
    async with factory() as db:
        await db.execute(select(1))  # a use case always has a transaction open
        queue_event(db, user, {"type": "appointment", "event": "x"})
        assert recorder.events == []  # nothing before the commit
        await db.rollback()
        await db.commit()
    assert recorder.events == []
    async with factory() as db:
        queue_event(db, user, {"type": "appointment", "event": "y"})
        await db.commit()
    assert recorder.events == [(user, {"type": "appointment", "event": "y"})]


async def test_a_failed_request_publishes_nothing(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, recorder: Recorder
) -> None:
    pair = await care_pair(client, api_db, world, mood=False)
    recorder.events.clear()
    too_long = "x" * 5000
    r = await pair.student.post(
        f"/me/conversations/{pair.therapist.id}/messages", {"body": too_long}
    )
    assert r.status_code == 422
    assert recorder.events == []


async def test_a_broken_broker_never_fails_the_request(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, api_app: FastAPI
) -> None:
    class Broken:
        def publish(self, user_id: uuid.UUID, payload: Event) -> None:
            raise RuntimeError("socket gone")

    pair = await care_pair(client, api_db, world, mood=False)
    set_broker(Broken())
    try:
        r = await pair.student.post(
            f"/me/conversations/{pair.therapist.id}/messages", {"body": "still sent"}
        )
    finally:
        set_broker(api_app.state.mm.hub)
    assert r.status_code == 201
    count = await api_db.scalar(
        select(func.count()).select_from(m.Message).where(m.Message.student_id == pair.student.id)
    )
    assert count == 1


# ---- the hub -----------------------------------------------------------------------------------


async def test_the_hub_fans_out_per_user_and_limits_connections() -> None:
    hub = Hub(max_per_user=2)
    alice, bob = uuid.uuid4(), uuid.uuid4()
    a1, a2 = hub.register(alice), hub.register(alice)
    assert a1 and a2 and hub.register(alice) is None
    b1 = hub.register(bob)
    assert b1
    hub.publish(alice, {"type": "x"})
    assert a1.queue.qsize() == a2.queue.qsize() == 1 and b1.queue.empty()
    hub.unregister(a1)
    assert hub.connection_count(alice) == 1 and hub.register(alice) is not None


async def test_a_slow_connection_is_marked_rather_than_blocking() -> None:
    hub = Hub()
    user = uuid.uuid4()
    conn = hub.register(user)
    assert conn
    for i in range(QUEUE_SIZE + 5):
        hub.publish(user, {"type": "x", "n": i})
    assert conn.overflowed and conn.queue.qsize() == QUEUE_SIZE


# ---- the WebSocket -----------------------------------------------------------------------------


class FakeSocket:
    def __init__(self, state: AppState, origin: str | None = None) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(mm=state))
        self.headers: dict[str, str] = {} if origin is None else {"origin": origin}
        self.incoming: asyncio.Queue[str | None] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.accepted = False
        self.closed: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        item = await self.incoming.get()
        if item is None:
            raise WebSocketDisconnect()
        return item

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def close(self, code: int = 1000) -> None:
        if self.closed is None:
            self.closed = code

    def say(self, frame: object) -> None:
        self.incoming.put_nowait(json.dumps(frame))


async def _until(check: Any) -> None:
    """Polls a fake socket's outbox (it has no event to wait on), for at most three seconds."""
    async with asyncio.timeout(3):
        while not check():  # noqa: ASYNC110
            await asyncio.sleep(0.01)


def _state(api_app: FastAPI, **settings: object) -> AppState:
    state: AppState = api_app.state.mm
    if settings:
        state = dataclasses.replace(state, settings=state.settings.model_copy(update=settings))
    return state


async def test_the_socket_refuses_a_foreign_origin(api_app: FastAPI) -> None:
    ws = FakeSocket(_state(api_app, cors_origins="https://app.example"), "https://evil.example")
    await realtime.realtime_socket(ws)
    assert ws.closed == realtime.CLOSE_ORIGIN and not ws.accepted


@pytest.mark.parametrize(
    "first",
    [
        {"type": "ping"},  # not an auth frame
        {"type": "auth"},  # no token
        {"type": "auth", "token": "not-a-token"},
        "just text",
    ],
)
async def test_the_socket_needs_a_valid_token_in_the_first_frame(
    api_app: FastAPI, first: object
) -> None:
    ws = FakeSocket(_state(api_app))
    ws.say(first)
    await realtime.realtime_socket(ws)
    assert ws.closed == realtime.CLOSE_UNAUTHENTICATED
    assert {"type": "ready"} not in ws.sent


async def test_the_socket_closes_when_no_token_arrives(
    api_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(realtime, "AUTH_TIMEOUT", 0.05)
    ws = FakeSocket(_state(api_app))
    await realtime.realtime_socket(ws)
    assert ws.closed == realtime.CLOSE_UNAUTHENTICATED


async def test_a_signed_in_socket_gets_only_its_own_events(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, api_app: FastAPI
) -> None:
    state = _state(api_app, cors_origins="https://app.example")
    s = await new_student(client, api_db, world)
    ws = FakeSocket(state, "https://app.example")
    task = asyncio.ensure_future(realtime.realtime_socket(ws))
    ws.say({"type": "auth", "token": s.token})
    await _until(lambda: {"type": "ready"} in ws.sent)
    state.hub.publish(s.id, {"type": "appointment", "appointment_id": "a", "event": "b"})
    state.hub.publish(uuid.uuid4(), {"type": "appointment", "event": "someone else"})
    ws.say({"type": "ping"})
    await _until(lambda: len(ws.sent) >= 3)
    ws.incoming.put_nowait(None)  # the client goes away
    await asyncio.wait_for(task, 3)
    assert ws.sent[0] == {"type": "ready"}
    assert {"type": "appointment", "appointment_id": "a", "event": "b"} in ws.sent
    assert {"type": "pong"} in ws.sent
    assert all(e.get("event") != "someone else" for e in ws.sent)
    assert state.hub.connection_count(s.id) == 0


async def test_too_many_sockets_for_one_person_are_refused(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, api_app: FastAPI
) -> None:
    state = _state(api_app)
    s = await new_student(client, api_db, world)
    held = [state.hub.register(s.id) for _ in range(state.hub.max_per_user)]
    try:
        ws = FakeSocket(state)
        ws.say({"type": "auth", "token": s.token})
        await realtime.realtime_socket(ws)
        assert ws.closed == realtime.CLOSE_TOO_MANY
    finally:
        for conn in held:
            if conn is not None:
                state.hub.unregister(conn)


async def test_signing_out_closes_the_socket(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    api_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(realtime, "REVALIDATE_EVERY", 0.05)
    state = _state(api_app)
    s = await new_student(client, api_db, world)
    ws = FakeSocket(state)
    task = asyncio.ensure_future(realtime.realtime_socket(ws))
    ws.say({"type": "auth", "token": s.token})
    await _until(lambda: {"type": "ready"} in ws.sent)
    assert (await s.post("/auth/logout")).status_code == 204
    await asyncio.wait_for(task, 3)
    assert ws.closed == realtime.CLOSE_UNAUTHENTICATED
    assert state.hub.connection_count(s.id) == 0
