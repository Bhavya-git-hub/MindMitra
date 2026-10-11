"""The AI wellness companion, as the API runs it (ADR 0010).

    student -> API: ownership, switches, crisis rules, limits -> AI service (safety layer,
    model, safety layer) -> API: escalation, storage -> student

What the API owns, so it holds whatever the AI service does:

- **Crisis first.** The API's own copy of the crisis rules runs on every message before
  anything else, including the rate limits. A crisis is answered here with a fixed reply and
  the institution's crisis contacts, the model is never asked, and a person is alerted
  through the safety workflow (``safety_workflow``, ADR 0013), which also pauses normal
  suggestions. Open companion alerts are not duplicated: a later, more urgent
  message raises the existing alert instead. The AI service runs the same rules (and, later, a
  classifier); if it reports a crisis the API missed, the same escalation happens.
- **Fail safe.** If the AI service is not configured, down or slow, the student gets a fixed
  "try again" reply; crisis handling above does not depend on it.
- **Private.** Conversations belong to the student alone (``can_read_ai_conversation``).
  Messages are encrypted at rest. Alerts carry the category and severity, never the text. The
  AI service receives only this conversation's recent text, never a name or id.
- **Retention.** A conversation expires 24 hours after its last message, or 90 days with the
  student's "Keep my AI companion history" consent; ``sweep_expired`` deletes it. A student
  can delete a conversation at once.
- **Limits.** Per-minute (in process) and per-day (from the database) limits per student;
  an institution can switch the companion off and set the daily limit, and deployment can
  switch it off everywhere.
"""

import dataclasses
import datetime as dt
import logging
import uuid
from typing import Final

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit import SlidingWindowRateLimiter
from app.application import institution_settings, safety_workflow
from app.application.access import NotFound, enforce, has_active_consent
from app.application.auth.errors import Conflict
from app.application.errors import InvalidInput
from app.application.safety import crisis_contacts
from app.application.safety_workflow import EscalationStatus
from app.application.timeutil import now_utc
from app.core.config import Settings
from app.domain.auth.policies import Principal, can_read_ai_conversation
from app.domain.safety import crisis_rules
from app.domain.safety.classifier import CLASSIFIER, SafetyAssessment
from app.domain.safety.risk import Concern, RiskLevel, Source
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AIConversationStatus,
    AIMessageRole,
    AIReplyKind,
    AuditOutcome,
    ConsentScope,
    UserRole,
)
from app.infrastructure.db.ids import uuid7
from app.infrastructure.ml_client import (
    CompanionClient,
    CompanionReply,
    CompanionUnavailable,
    HistoryTurn,
)

log = logging.getLogger("mindmitra.companion")

MAX_MESSAGE: Final = 2000
HISTORY_SENT: Final = 24  # the AI service trims further to its own context budget
RETENTION_DEFAULT: Final = dt.timedelta(hours=24)
RETENTION_WITH_HISTORY: Final = dt.timedelta(days=90)
DAY: Final = dt.timedelta(hours=24)
# While a reply is on its way, a second message in the same conversation waits.
REPLY_PENDING: Final = dt.timedelta(seconds=60)
MAX_LIST: Final = 100

DISCLAIMER: Final = (
    "I'm an AI wellness companion, not a therapist. I can't diagnose or give medical advice, "
    "and I can make mistakes. If you're in danger, use Get help now."
)

ALERT_TITLE: Final = safety_workflow.ALERT_TITLE

# ---- fixed crisis replies (written once, reviewed, never generated) --------------------------

_CRISIS_OPENING = {
    "abuse_or_unsafe_situation": (
        "Thank you for telling me. No one has the right to hurt or threaten you, and it is not "
        "your fault. Your safety comes first."
    ),
    "harm_to_others": (
        "It sounds like things feel really intense right now. If you can, step away from the "
        "situation and talk to someone now."
    ),
}
_CRISIS_DEFAULT_OPENING = (
    "I'm really glad you told me. What you're going through matters, and you deserve support "
    "from a person right now, not from an AI."
)
_CRISIS_CONTACTS = (
    "Please reach out to one of the contacts below. If you or anyone else is in immediate "
    "danger, call your local emergency number now."
)
_TOLD_CARE_TEAM = "I've let your counsellor know, so a person can reach out to you."
_TOLD_TEAM = "I've let your institution's counselling team know, so a person can reach out to you."
_ALREADY_TOLD = "Your counsellor or the counselling team already knows and will reach out."
_NOT_TOLD = (
    "I couldn't reach the counselling team just now, so please contact one of the people below "
    "yourself."
)
_THIRD_PERSON = (
    "It sounds like you're worried about someone. If they might be in danger, contact "
    "emergency services or campus support for them now. The contacts below can help, and "
    "Get help now has guidance on supporting someone."
)


# The companion's openings are keyed by the crisis rules' own category names.
_RULE_CATEGORY: Final = {
    Concern.UNSAFE_SITUATION: "abuse_or_unsafe_situation",
    Concern.HARM_TO_OTHERS: "harm_to_others",
}


def _rule_category(found: SafetyAssessment) -> str | None:
    return _RULE_CATEGORY.get(found.concern) if found.concern else None


def crisis_reply(
    category: str | None, *, told_care_team: bool, already_open: bool, failed: bool = False
) -> str:
    opening = _CRISIS_OPENING.get(category or "", _CRISIS_DEFAULT_OPENING)
    if failed:
        told = _NOT_TOLD
    elif already_open:
        told = _ALREADY_TOLD
    else:
        told = _TOLD_CARE_TEAM if told_care_team else _TOLD_TEAM
    return f"{opening} {_CRISIS_CONTACTS} {told}"


UNAVAILABLE_REPLY: Final = (
    "I'm having trouble replying right now. Please try again in a little while. If you need "
    "to talk to someone now, use Get help now, or book a counsellor from Talk to a therapist."
)


# ---- errors ---------------------------------------------------------------------------------


class CompanionOff(Exception):
    """The companion is switched off or not set up (answered with 503)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CompanionLimited(Exception):
    """Too many messages (answered with 429 and Retry-After)."""

    def __init__(self, retry_after: int, daily: bool) -> None:
        super().__init__("daily limit" if daily else "per-minute limit")
        self.retry_after = retry_after
        self.daily = daily


# ---- results --------------------------------------------------------------------------------


@dataclasses.dataclass
class Availability:
    available: bool
    reason: str | None  # "switched_off" | "not_configured"
    daily_limit: int
    remaining_today: int
    keeps_history: bool
    retention_hours: int


@dataclasses.dataclass
class Support:
    """Shown with a reply: crisis contacts, and whether a person was alerted."""

    level: str  # "crisis" (a person was alerted) | "gentle" (contacts offered)
    escalated: bool
    care_team_notified: bool
    about_someone_else: bool
    contacts: list[m.CrisisContact]


@dataclasses.dataclass
class Exchange:
    conversation: m.AIConversation
    message: m.AIMessage
    reply: m.AIMessage
    support: Support | None


# ---- helpers --------------------------------------------------------------------------------


def _authorize(actor: Principal, conv: m.AIConversation, action: str) -> None:
    enforce(
        can_read_ai_conversation(
            actor, owner_student_id=conv.student_id, institution_id=conv.institution_id
        ),
        action=action,
        resource_type="ai_conversation",
        resource_id=conv.id,
    )


def _live(conv: m.AIConversation, now: dt.datetime) -> bool:
    return conv.deleted_at is None and (conv.expires_at is None or conv.expires_at > now)


async def _own(
    db: AsyncSession, actor: Principal, conv_id: uuid.UUID, action: str, *, lock: bool = False
) -> m.AIConversation:
    conv = await db.get(m.AIConversation, conv_id, with_for_update=lock)
    if conv is None:
        raise NotFound
    _authorize(actor, conv, action)
    if not _live(conv, now_utc()):
        raise NotFound
    return conv


async def _retention(db: AsyncSession, actor: Principal) -> dt.timedelta:
    keeps = await has_active_consent(
        db, user_id=actor.user_id, scope=ConsentScope.AI_COMPANION_HISTORY
    )
    return RETENTION_WITH_HISTORY if keeps else RETENTION_DEFAULT


async def _sent_today(db: AsyncSession, actor: Principal, now: dt.datetime) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(m.AIMessage)
        .join(m.AIConversation, m.AIConversation.id == m.AIMessage.conversation_id)
        .where(
            m.AIConversation.student_id == actor.user_id,
            m.AIConversation.institution_id == actor.institution_id,
            m.AIMessage.role == AIMessageRole.USER,
            m.AIMessage.crisis_flag.is_(False),
            m.AIMessage.created_at > now - DAY,
        )
    )
    return int(count or 0)


async def _switches(
    db: AsyncSession, actor: Principal, settings: Settings
) -> tuple[bool, str | None, int]:
    safety = (await institution_settings.load(db, actor.institution_id)).safety
    if not settings.companion_enabled or not safety.companion_enabled:
        return False, "switched_off", safety.companion_daily_messages
    return True, None, safety.companion_daily_messages


async def _audit(
    db: AsyncSession,
    actor: Principal,
    action: str,
    conv_id: uuid.UUID,
    **details: str | int | bool,
) -> None:
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.STUDENT,
        action=action,
        outcome=AuditOutcome.ALLOWED,
        resource_type="ai_conversation",
        resource_id=conv_id,
        subject_student_id=actor.user_id,
        details=details,
    )


# ---- use cases ------------------------------------------------------------------------------


async def availability(
    db: AsyncSession, actor: Principal, settings: Settings, *, configured: bool
) -> Availability:
    on, reason, limit = await _switches(db, actor, settings)
    if on and not configured:
        on, reason = False, "not_configured"
    retention = await _retention(db, actor)
    used = await _sent_today(db, actor, now_utc())
    return Availability(
        available=on,
        reason=reason,
        daily_limit=limit,
        remaining_today=max(limit - used, 0),
        keeps_history=retention == RETENTION_WITH_HISTORY,
        retention_hours=int(retention.total_seconds() // 3600),
    )


async def list_conversations(
    db: AsyncSession, actor: Principal, limit: int
) -> list[m.AIConversation]:
    now = now_utc()
    rows = list(
        await db.scalars(
            select(m.AIConversation)
            .where(
                m.AIConversation.student_id == actor.user_id,
                m.AIConversation.institution_id == actor.institution_id,
                m.AIConversation.deleted_at.is_(None),
                (m.AIConversation.expires_at.is_(None)) | (m.AIConversation.expires_at > now),
            )
            .order_by(
                func.coalesce(m.AIConversation.last_message_at, m.AIConversation.started_at).desc()
            )
            .limit(min(limit, MAX_LIST))
        )
    )
    for conv in rows:  # defence in depth: the query is already scoped to the caller
        _authorize(actor, conv, "ai_conversation.list")
    return rows


async def start_conversation(
    db: AsyncSession, actor: Principal, settings: Settings, *, configured: bool
) -> m.AIConversation:
    on, reason, _ = await _switches(db, actor, settings)
    if not on or not configured:
        raise CompanionOff(reason or "not_configured")
    now = now_utc()
    conv = m.AIConversation(
        id=uuid7(),
        institution_id=actor.institution_id,
        student_id=actor.user_id,
        status=AIConversationStatus.ACTIVE,
        started_at=now,
        last_message_at=None,
        expires_at=now + await _retention(db, actor),
    )
    db.add(conv)
    await db.flush()
    await _audit(db, actor, "ai_conversation.create", conv.id)
    await db.commit()
    return conv


async def get_conversation(
    db: AsyncSession, actor: Principal, conv_id: uuid.UUID
) -> tuple[m.AIConversation, list[m.AIMessage]]:
    conv = await _own(db, actor, conv_id, "ai_conversation.read")
    messages = list(
        await db.scalars(
            select(m.AIMessage)
            .where(m.AIMessage.conversation_id == conv.id)
            .order_by(m.AIMessage.seq)
        )
    )
    return conv, messages


async def delete_conversation(db: AsyncSession, actor: Principal, conv_id: uuid.UUID) -> None:
    """Deletes the conversation and its messages at once. Any alert it raised stays with the
    care team (safety records follow the clinical retention policy) and never held its text."""
    conv = await _own(db, actor, conv_id, "ai_conversation.delete")
    await db.execute(delete(m.AIConversation).where(m.AIConversation.id == conv.id))
    await _audit(db, actor, "ai_conversation.delete", conv.id)
    await db.commit()


async def _history(db: AsyncSession, conv_id: uuid.UUID, before_seq: int) -> list[HistoryTurn]:
    """Recent turns for the AI service, without crisis exchanges or "try again" replies."""
    rows = list(
        await db.scalars(
            select(m.AIMessage)
            .where(m.AIMessage.conversation_id == conv_id, m.AIMessage.seq < before_seq)
            .order_by(m.AIMessage.seq.desc())
            .limit(HISTORY_SENT)
        )
    )
    rows.reverse()
    out: list[HistoryTurn] = []
    for msg in rows:
        if msg.crisis_flag or msg.reply_kind in (AIReplyKind.CRISIS, AIReplyKind.UNAVAILABLE):
            continue
        out.append(
            HistoryTurn("user", msg.content)
            if msg.role is AIMessageRole.USER
            else HistoryTurn("assistant", msg.content)
        )
    return out


@dataclasses.dataclass(frozen=True)
class _Escalated:
    already_open: bool
    care_team_notified: bool
    failed: bool


async def _escalate(
    db: AsyncSession,
    actor: Principal,
    conv: m.AIConversation,
    found: SafetyAssessment,
    *,
    model_version: str | None,
    now: dt.datetime,
) -> _Escalated:
    """Hand a crisis to the safety workflow: an alert (or the open one raised again), the
    pause on suggestions and the safety event. The caller commits."""
    try:
        outcome = await safety_workflow.WORKFLOW.handle(
            db,
            actor,
            found,
            source=Source.COMPANION,
            now=now,
            source_type="ai_conversation",
            source_id=conv.id,
            model_version=model_version,
        )
    except Exception:
        log.exception("the safety workflow failed for a companion crisis")
        outcome = None
    escalation = outcome.escalation if outcome else None
    already = escalation is not None and escalation.status is EscalationStatus.ALREADY_OPEN
    failed = escalation is None or not escalation.requested
    await _audit(
        db,
        actor,
        "ai_conversation.crisis",
        conv.id,
        category=(found.concern.value if found.concern else "acute_distress"),
        severity=found.alert_severity or "high",
        alert="failed" if failed else ("existing" if already else "new"),
    )
    return _Escalated(already, escalation is not None and escalation.care_team_notified, failed)


async def _next_seq(db: AsyncSession, conv_id: uuid.UUID) -> tuple[int, m.AIMessage | None]:
    last = await db.scalar(
        select(m.AIMessage)
        .where(m.AIMessage.conversation_id == conv_id)
        .order_by(m.AIMessage.seq.desc())
        .limit(1)
    )
    return (last.seq + 1 if last else 1), last


async def send_message(
    db: AsyncSession,
    actor: Principal,
    conv_id: uuid.UUID,
    body: str,
    *,
    settings: Settings,
    client: CompanionClient | None,
    limiter: SlidingWindowRateLimiter,
) -> Exchange:
    text = body.strip()
    if not text:
        raise InvalidInput("Please write a message first.")
    if len(text) > MAX_MESSAGE:
        raise InvalidInput(f"Messages can be up to {MAX_MESSAGE} characters.")

    # 1. Ownership, then the API's own crisis rules, before any switch or limit.
    conv = await _own(db, actor, conv_id, "ai_conversation.message", lock=True)
    found = CLASSIFIER.assess_text(text)
    crisis = found.level.at_least(RiskLevel.HIGH)
    on, reason, daily_limit = await _switches(db, actor, settings)
    if not crisis:
        if not on or client is None:
            raise CompanionOff(reason or "not_configured")
        wait = limiter.hit(str(actor.user_id))
        if wait is not None:
            raise CompanionLimited(max(int(wait) + 1, 1), daily=False)
        now = now_utc()
        if await _sent_today(db, actor, now) >= daily_limit:
            raise CompanionLimited(3600, daily=True)

    now = now_utc()
    seq, last = await _next_seq(db, conv.id)
    if (
        last is not None
        and last.role is AIMessageRole.USER
        and last.created_at > now - REPLY_PENDING
    ):
        raise Conflict("Please wait for the reply to your last message.")

    retention = await _retention(db, actor)
    message = m.AIMessage(
        id=uuid7(),
        conversation_id=conv.id,
        seq=seq,
        role=AIMessageRole.USER,
        content=text,
        crisis_flag=crisis,
        safety_flags=["crisis_rules"] if crisis else [],
        created_at=now,
    )
    db.add(message)
    conv.last_message_at = now
    conv.expires_at = now + retention

    # 2. A crisis is answered here and handed to a person; the model is never asked.
    if crisis:
        done = await _escalate(
            db, actor, conv, found, model_version=crisis_rules.rules_version(), now=now
        )
        reply = _reply(
            conv,
            seq + 1,
            AIReplyKind.CRISIS,
            crisis_reply(
                _rule_category(found),
                told_care_team=done.care_team_notified,
                already_open=done.already_open,
                failed=done.failed,
            ),
            ["crisis_rules"],
        )
        conv.status = AIConversationStatus.CRISIS_HANDOFF
        db.add(reply)
        await db.commit()
        contacts = await crisis_contacts(db, actor)
        return Exchange(
            conv,
            message,
            reply,
            Support("crisis", not done.failed, done.care_team_notified, False, contacts),
        )

    # 3. Commit the student's message, then ask the AI service outside the transaction.
    await db.flush()
    history = await _history(db, conv.id, seq)
    await db.commit()
    assert client is not None
    result: CompanionReply | None
    try:
        result = await client.respond(text, history)
    except CompanionUnavailable:
        result = None

    # 4. Store the reply; escalate if the AI service saw a crisis the rules here did not.
    conv = await _own(db, actor, conv_id, "ai_conversation.message", lock=True)
    now = now_utc()
    support: Support | None = None
    if result is None:
        reply = _reply(
            conv, seq + 1, AIReplyKind.UNAVAILABLE, UNAVAILABLE_REPLY, ["ml_unavailable"]
        )
    elif result.crisis.action == "escalate" or result.kind == "crisis":
        message.crisis_flag = True
        message.safety_flags = ["crisis_service"]
        reported = CLASSIFIER.from_ai_service(
            action="escalate",
            category=result.crisis.category,
            severity=result.crisis.severity,
            classifier="classifier" in result.flags,
        )
        done = await _escalate(
            db, actor, conv, reported, model_version=result.model_version, now=now
        )
        reply = _reply(
            conv,
            seq + 1,
            AIReplyKind.CRISIS,
            crisis_reply(
                result.crisis.category,
                told_care_team=done.care_team_notified,
                already_open=done.already_open,
                failed=done.failed,
            ),
            ["crisis_service"],
        )
        conv.status = AIConversationStatus.CRISIS_HANDOFF
        support = Support("crisis", not done.failed, done.care_team_notified, False, [])
    else:
        flags = [f[:40] for f in result.flags][:10]
        gentle = result.crisis.action == "review" or found.level.at_least(RiskLevel.MODERATE)
        if gentle:
            flags.append("support_resources")
        reply = _reply(
            conv, seq + 1, AIReplyKind(result.kind), result.reply or UNAVAILABLE_REPLY, flags
        )
        conv.model_version = result.model_version
        if gentle:
            support = Support(
                "gentle", False, False, result.crisis.third_person or found.about_someone_else, []
            )
            if support.about_someone_else:
                reply.content = f"{_THIRD_PERSON} {reply.content}"
    conv.last_message_at = now
    db.add(reply)
    await db.commit()
    if support is not None:
        support.contacts = await crisis_contacts(db, actor)
    return Exchange(conv, message, reply, support)


def _reply(
    conv: m.AIConversation, seq: int, kind: AIReplyKind, content: str, flags: list[str]
) -> m.AIMessage:
    # created_at is set here (not left to the database) so the reply can be returned after
    # the commit without another query.
    return m.AIMessage(
        created_at=now_utc(),
        id=uuid7(),
        conversation_id=conv.id,
        seq=seq,
        role=AIMessageRole.ASSISTANT,
        content=content,
        reply_kind=kind,
        crisis_flag=kind is AIReplyKind.CRISIS,
        safety_flags=flags,
    )


async def sweep_expired(db: AsyncSession, now: dt.datetime | None = None) -> int:
    """Hard-deletes conversations past their retention (messages go with them)."""
    result = await db.execute(
        delete(m.AIConversation).where(
            m.AIConversation.expires_at.is_not(None),
            m.AIConversation.expires_at <= (now or now_utc()),
        )
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)
