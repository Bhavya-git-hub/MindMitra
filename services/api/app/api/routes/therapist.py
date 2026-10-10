"""The therapist portal: profile, verification, availability, caseload, sessions, notes, alerts.

Three layers guard every route: the permission here, the "verified and on my care team"
check in the use case, and (for wellbeing data) the student's consent. Students, teachers and
administrators hold none of these permissions, so they are refused before any record is read.
Messaging is the shared ``/me/conversations`` API, which a verified therapist also holds.
"""

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import app_state, get_db, require_permission
from app.api.schemas import teacher as ts
from app.api.schemas import therapist as s
from app.api.schemas.indicators import IndicatorsOut, indicators_out
from app.api.zone import Zone
from app.application import (
    follow_ups,
    referrals,
    rescheduling,
    risk_alerts,
    therapist_appointments,
    therapist_dashboard,
    therapist_profile,
    therapist_recommendations,
    therapist_students,
    therapy_sessions,
)
from app.application.errors import InvalidInput
from app.application.timeutil import now_utc
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal
from app.infrastructure.db.enums import (
    AppointmentStatus,
    FollowUpKind,
    FollowUpStatus,
    ReferralStatus,
    SessionMode,
    TherapySessionStatus,
)

router = APIRouter(prefix="/therapist", tags=["therapist"])
Db = Annotated[AsyncSession, Depends(get_db)]


def _guard(permission: Permission) -> Any:
    return Depends(require_permission(permission))


Own = Annotated[Principal, _guard(Permission.THERAPIST_PROFILE_MANAGE)]
Students = Annotated[Principal, _guard(Permission.STUDENT_READ_ASSIGNED)]
Wellbeing = Annotated[Principal, _guard(Permission.WELLNESS_READ_ASSIGNED)]
Appointments = Annotated[Principal, _guard(Permission.APPOINTMENT_MANAGE)]
Sessions = Annotated[Principal, _guard(Permission.SESSION_MANAGE)]
NoteReader = Annotated[Principal, _guard(Permission.THERAPY_NOTE_READ)]
NoteWriter = Annotated[Principal, _guard(Permission.THERAPY_NOTE_WRITE)]
Alerts = Annotated[Principal, _guard(Permission.RISK_ALERT_MANAGE)]
FollowUps = Annotated[Principal, _guard(Permission.FOLLOW_UP_MANAGE)]
Triage = Annotated[Principal, _guard(Permission.REFERRAL_TRIAGE)]
Recommenders = Annotated[Principal, _guard(Permission.RECOMMENDATION_CREATE_ASSIGNED)]
Limit = Annotated[int, Query(ge=1, le=200)]


# ---- dashboard, profile, verification -------------------------------------------------------


@router.get("/dashboard")
async def dashboard(db: Db, principal: Own, zone: Zone) -> s.DashboardOut:
    return s.dashboard_out(await therapist_dashboard.build(db, principal, zone))


@router.get("/profile")
async def get_profile(db: Db, principal: Own) -> s.ProfileOut:
    return s.profile_out(*await therapist_profile.get_profile(db, principal))


@router.patch("/profile")
async def update_profile(body: s.ProfileIn, db: Db, principal: Own) -> s.ProfileOut:
    result = await therapist_profile.update_profile(
        db,
        principal,
        bio=body.bio,
        specialties=body.specialties,
        languages=body.languages,
        accepting_new_students=body.accepting_new_students,
        max_caseload=body.max_caseload,
    )
    return s.profile_out(*result)


@router.post("/verification")
async def submit_verification(body: s.VerificationIn, db: Db, principal: Own) -> s.ProfileOut:
    await therapist_profile.submit_verification(
        db,
        principal,
        licence_number=body.licence_number,
        licence_body=body.licence_body,
        licence_expires_on=body.licence_expires_on,
    )
    return s.profile_out(*await therapist_profile.get_profile(db, principal))


# ---- availability ---------------------------------------------------------------------------


@router.get("/availability")
async def availability(
    db: Db,
    principal: Own,
    start: Annotated[dt.datetime | None, Query(alias="from")] = None,
    end: Annotated[dt.datetime | None, Query(alias="to")] = None,
) -> list[s.SlotOut]:
    now = now_utc()
    first = start or now - dt.timedelta(days=1)
    last = end or now + dt.timedelta(days=60)
    if first.tzinfo is None or last.tzinfo is None:
        raise InvalidInput("Please include a time zone with from and to.")
    if last <= first or last - first > dt.timedelta(days=130):
        raise InvalidInput("Choose a range of up to about four months.")
    rows = await therapist_profile.list_availability(db, principal, start=first, end=last)
    return [s.slot_out(r) for r in rows]


@router.post("/availability", status_code=201)
async def add_availability(body: s.AvailabilityIn, db: Db, principal: Own) -> list[s.SlotOut]:
    created = await therapist_profile.add_availability(
        db,
        principal,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        mode=SessionMode(body.mode),
        repeat_weeks=body.repeat_weeks,
    )
    return [
        s.SlotOut(
            id=c.id,
            starts_at=c.starts_at,
            ends_at=c.ends_at,
            mode=c.mode.value,
            booked=False,
            appointment_id=None,
            appointment_status=None,
        )
        for c in created
    ]


@router.delete("/availability/{slot_id}", status_code=204)
async def remove_availability(slot_id: uuid.UUID, db: Db, principal: Own) -> Response:
    await therapist_profile.remove_availability(db, principal, slot_id)
    return Response(status_code=204)


# ---- appointments (confirming, declining and cancelling use PATCH /appointments/{id}) -------


@router.get("/appointments")
async def appointments(
    db: Db,
    principal: Appointments,
    scope: Annotated[therapist_appointments.Scope, Query()] = "all",
    status: AppointmentStatus | None = None,
    limit: Limit = 100,
) -> list[s.TherapistAppointmentOut]:
    rows = await therapist_appointments.list_appointments(
        db, principal, scope=scope, status=status, limit=limit
    )
    return [s.appointment_row_out(r) for r in rows]


@router.post("/appointments/{appointment_id}/reschedule")
async def reschedule_appointment(
    appointment_id: uuid.UUID, body: s.RescheduleIn, db: Db, principal: Appointments
) -> s.TherapistAppointmentOut:
    """Move to another of the therapist's own open times; the student is told."""
    view = await rescheduling.reschedule(db, principal, appointment_id, body.availability_id)
    rows = await therapist_appointments.rows_for(
        db, principal, [(view.appointment, view.therapist_name)]
    )
    return s.appointment_row_out(rows[0])


# ---- students -------------------------------------------------------------------------------


@router.get("/students")
async def caseload(db: Db, principal: Students) -> list[s.CaseloadStudentOut]:
    return [s.caseload_out(r) for r in await therapist_students.caseload(db, principal)]


@router.get("/students/{student_id}")
async def student_profile(
    student_id: uuid.UUID, db: Db, principal: Students
) -> s.StudentProfileOut:
    profile = await therapist_students.profile(db, principal, student_id)
    return s.student_profile_out(profile)


@router.get("/students/{student_id}/trends")
async def student_trends(
    student_id: uuid.UUID,
    db: Db,
    principal: Wellbeing,
    zone: Zone,
    days: Annotated[int, Query(ge=7, le=90)] = 30,
) -> s.TrendsOut:
    series = await therapist_students.trends(db, principal, student_id, days, zone)
    return s.trends_out(days, series)


@router.get("/students/{student_id}/indicators")
async def student_indicators(
    student_id: uuid.UUID, request: Request, db: Db, principal: Wellbeing, zone: Zone
) -> IndicatorsOut:
    """Needs the care link and the student's ``share_ai_signals_with_care_team`` consent."""
    client = app_state(request).indicators
    return indicators_out(
        await therapist_students.indicators(db, principal, student_id, zone, client)
    )


@router.get("/students/{student_id}/assessments")
async def student_assessments(
    student_id: uuid.UUID,
    db: Db,
    principal: Wellbeing,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[s.AssessmentOut]:
    rows = await therapist_students.assessments(db, principal, student_id, limit)
    return [s.assessment_out(r) for r in rows]


@router.get("/students/{student_id}/recommendations")
async def student_recommendations(
    student_id: uuid.UUID, db: Db, principal: Recommenders
) -> list[s.MadeRecommendationOut]:
    rows = await therapist_recommendations.list_made(db, principal, student_id)
    return [s.made_out(r) for r in rows]


@router.post("/students/{student_id}/recommendations", status_code=201)
async def recommend(
    student_id: uuid.UUID, body: s.RecommendationIn, db: Db, principal: Recommenders
) -> s.MadeRecommendationOut:
    made = await therapist_recommendations.create(
        db,
        principal,
        student_id,
        title=body.title,
        rationale=body.rationale,
        resource_id=body.resource_id,
    )
    return s.made_out(made)


# ---- sessions and notes ---------------------------------------------------------------------


@router.get("/sessions")
async def list_sessions(
    db: Db,
    principal: Sessions,
    status: TherapySessionStatus | None = None,
    limit: Limit = 50,
) -> list[s.SessionOut]:
    rows = await therapy_sessions.list_sessions(db, principal, status, limit)
    return [s.session_out(r) for r in rows]


@router.post("/appointments/{appointment_id}/session", status_code=201)
async def start_session(appointment_id: uuid.UUID, db: Db, principal: Sessions) -> s.SessionOut:
    return s.session_out(await therapy_sessions.start_session(db, principal, appointment_id))


@router.patch("/sessions/{session_id}")
async def finish_session(
    session_id: uuid.UUID, body: s.SessionFinishIn, db: Db, principal: Sessions
) -> s.SessionOut:
    view = await therapy_sessions.finish_session(
        db, principal, session_id, TherapySessionStatus(body.status)
    )
    return s.session_out(view)


@router.get("/sessions/{session_id}/note")
async def get_note(
    session_id: uuid.UUID,
    db: Db,
    principal: NoteReader,
    response: Response,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> s.NoteOut | None:
    response.headers["Cache-Control"] = "no-store, private"
    view = await therapy_sessions.get_note(db, principal, session_id, version)
    return s.note_out(view) if view else None


@router.put("/sessions/{session_id}/note")
async def save_note(
    session_id: uuid.UUID, body: s.NoteIn, db: Db, principal: NoteWriter, response: Response
) -> s.NoteOut:
    response.headers["Cache-Control"] = "no-store, private"
    return s.note_out(await therapy_sessions.save_note(db, principal, session_id, body.body))


# ---- risk alerts ----------------------------------------------------------------------------


@router.get("/alerts")
async def list_alerts(
    db: Db, principal: Alerts, closed: bool = False, limit: Limit = 50
) -> list[s.AlertOut]:
    rows = await risk_alerts.list_alerts(db, principal, closed=closed, limit=limit)
    return [s.alert_out(r) for r in rows]


@router.patch("/alerts/{alert_id}")
async def act_on_alert(
    alert_id: uuid.UUID, body: s.AlertActionIn, db: Db, principal: Alerts
) -> s.AlertOut:
    view = await risk_alerts.act_on_alert(db, principal, alert_id, body.action, body.outcome)
    return s.alert_out(view)


# ---- follow-ups -----------------------------------------------------------------------------


@router.get("/follow-ups")
async def list_follow_ups(
    db: Db,
    principal: FollowUps,
    zone: Zone,
    status: FollowUpStatus | None = None,
    student_id: uuid.UUID | None = None,
    limit: Limit = 100,
) -> list[s.FollowUpOut]:
    rows = await follow_ups.list_follow_ups(
        db, principal, status=status, student_id=student_id, zone=zone, limit=limit
    )
    return [s.follow_up_out(r) for r in rows]


@router.post("/follow-ups", status_code=201)
async def create_follow_up(
    body: s.FollowUpIn, db: Db, principal: FollowUps, zone: Zone
) -> s.FollowUpOut:
    view = await follow_ups.create_follow_up(
        db,
        principal,
        student_id=body.student_id,
        kind=FollowUpKind(body.kind),
        due_on=body.due_on,
        note=body.note,
        session_id=body.session_id,
        zone=zone,
    )
    return s.follow_up_out(view)


@router.patch("/follow-ups/{follow_up_id}")
async def update_follow_up(
    follow_up_id: uuid.UUID, body: s.FollowUpPatchIn, db: Db, principal: FollowUps, zone: Zone
) -> s.FollowUpOut:
    view = await follow_ups.update_follow_up(
        db,
        principal,
        follow_up_id,
        status=FollowUpStatus(body.status) if body.status else None,
        due_on=body.due_on,
        note=body.note,
        zone=zone,
    )
    return s.follow_up_out(view)


# ---- referrals from teachers ----------------------------------------------------------------


@router.get("/referrals")
async def list_referrals(
    db: Db, principal: Triage, status: ReferralStatus | None = None
) -> list[ts.TriageReferralOut]:
    """Open referrals about students on this therapist's care team or with nobody yet."""
    rows = await referrals.queue(db, principal, status)
    return [ts.triage_out(v, principal.user_id) for v in rows]


@router.get("/referrals/{referral_id}")
async def get_referral(referral_id: uuid.UUID, db: Db, principal: Triage) -> ts.TriageReferralOut:
    return ts.triage_out(
        await referrals.get_for_triage(db, principal, referral_id), principal.user_id
    )


@router.post("/referrals/{referral_id}/claim")
async def claim_referral(referral_id: uuid.UUID, db: Db, principal: Triage) -> ts.TriageReferralOut:
    return ts.triage_out(await referrals.claim(db, principal, referral_id), principal.user_id)


@router.post("/referrals/{referral_id}/close")
async def close_referral(
    referral_id: uuid.UUID, body: ts.CloseIn, db: Db, principal: Triage
) -> ts.TriageReferralOut:
    return ts.triage_out(
        await referrals.close(db, principal, referral_id, body.outcome), principal.user_id
    )
