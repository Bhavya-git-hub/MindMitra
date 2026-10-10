"""Referrals from teachers, therapist triage, and requests students send their teachers.

The teacher learns only a status. The student is told nothing about who raised a referral. A
referral needs a real teaching and enrolment link, and one therapist handles it at a time.
"""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import AlertSeverity, AlertSource, AuditOutcome, UserRole
from tests.api_world import Actor, Builder, World
from tests.student_helpers import Session, new_student, new_therapist, sign_in
from tests.teacher_helpers import School, another_teacher, school

pytestmark = pytest.mark.asyncio

TEACHER_VIEW_KEYS = {
    "id", "student_id", "student_name", "course_id", "course_code", "course_title", "category",
    "category_label", "urgency", "urgency_label", "note", "status", "status_label", "created_at",
    "message",
}  # fmt: skip


def referral_body(s: School, student: Actor, **kw: object) -> dict[str, object]:
    return {
        "student_id": str(student.user_id),
        "course_id": str(s.course_id),
        "category": "wellbeing_concern",
        "urgency": "routine",
        "note": "Has seemed withdrawn in class for two weeks.",
        **kw,
    }


async def refer(s: School, student: Actor, **kw: object) -> httpx.Response:
    return await s.teacher.post("/teacher/referrals", referral_body(s, student, **kw))


async def notifications(db: AsyncSession, user: uuid.UUID) -> list[m.Notification]:
    return list(await db.scalars(select(m.Notification).where(m.Notification.user_id == user)))


# ---- raising a referral ---------------------------------------------------------------------


async def test_a_teacher_refers_a_student_in_their_class(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=3, data=False)
    r = await refer(s, s.students[0])
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == TEACHER_VIEW_KEYS
    assert body["status"] == "received" and body["status_label"].startswith("Received")
    assert body["note"].startswith("Has seemed withdrawn")
    listed = (await s.teacher.get("/teacher/referrals")).json()
    assert [x["id"] for x in listed] == [body["id"]]
    assert (await s.teacher.get(f"/teacher/referrals/{body['id']}")).json()["id"] == body["id"]
    counts = (await s.teacher.get("/teacher/dashboard")).json()["referrals"]
    assert counts == {"received": 1, "in_progress": 0, "closed": 0}


async def test_the_note_is_stored_encrypted(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    from sqlalchemy import text

    s = await school(client, api_db, world, students=2, data=False)
    rid = (await refer(s, s.students[0])).json()["id"]
    raw = await api_db.scalar(
        text("SELECT note::text FROM safety.referrals WHERE id = :i"), {"i": rid}
    )
    assert raw is not None and "withdrawn" not in raw


async def test_a_referral_needs_a_real_teaching_and_enrolment_link(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    mine = await school(client, api_db, world, students=3, data=False)
    other = await school(client, api_db, world, students=3, data=False)
    outsider_in_dept = await new_student(client, api_db, world)  # not enrolled in any class
    b_student = await new_student(client, api_db, world, other_tenant=True)

    cases = [
        refer(mine, other.students[0]),  # enrolled in a class this teacher does not teach
        refer(mine, outsider_in_dept.actor),  # not enrolled anywhere
        refer(mine, b_student.actor),  # another institution
        mine.teacher.post(
            "/teacher/referrals",
            referral_body(other, mine.students[0]),  # class not theirs
        ),
        refer(mine, Actor(uuid.uuid4(), world.inst_a, "x@x", UserRole.STUDENT)),  # no such person
    ]
    for pending in cases:
        r = await pending
        assert r.status_code == 404, r.text
    assert (await mine.teacher.get("/teacher/referrals")).json() == []


async def test_a_dropped_student_cannot_be_referred(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    from app.infrastructure.db.enums import EnrollmentStatus

    s = await school(client, api_db, world, students=2, data=False)
    row = await api_db.scalar(
        select(m.CourseEnrollment).where(m.CourseEnrollment.student_id == s.students[0].user_id)
    )
    assert row is not None
    row.status = EnrollmentStatus.DROPPED
    await api_db.commit()
    assert (await refer(s, s.students[0])).status_code == 404


async def test_the_database_itself_refuses_a_referral_without_a_link(
    api_db: AsyncSession, client: httpx.AsyncClient, world: World
) -> None:
    from sqlalchemy.exc import IntegrityError

    mine = await school(client, api_db, world, students=2, data=False)
    other = await school(client, api_db, world, students=2, data=False)
    from app.infrastructure.db.enums import ReferralCategory, ReferralUrgency

    api_db.add(
        m.Referral(
            institution_id=world.inst_a,
            teacher_id=mine.teacher.id,
            student_id=other.students[0].user_id,  # not enrolled in mine.course_id
            course_id=mine.course_id,
            category=ReferralCategory.WELLBEING_CONCERN,
            urgency=ReferralUrgency.ROUTINE,
        )
    )
    with pytest.raises(IntegrityError):
        await api_db.flush()
    await api_db.rollback()


async def test_one_live_referral_per_student_until_it_is_closed(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=2, data=False)
    assert (await refer(s, s.students[0])).status_code == 201
    assert (await refer(s, s.students[0])).status_code == 409
    assert (await refer(s, s.students[1])).status_code == 201


async def test_input_is_validated(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=1, data=False)
    assert (await refer(s, s.students[0], note="x" * 1001)).status_code == 422
    assert (await refer(s, s.students[0], category="depression")).status_code == 422
    assert (await refer(s, s.students[0], urgency="whenever")).status_code == 422
    assert (await refer(s, s.students[0], note=None)).status_code == 201


async def test_there_is_a_daily_limit(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=11, data=False)
    for p in s.students[:10]:
        assert (await refer(s, p)).status_code == 201
    assert (await refer(s, s.students[10])).status_code == 409


async def test_a_safety_concern_also_raises_a_high_priority_alert(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=2, data=False)
    rid = (await refer(s, s.students[0], category="safety_concern", urgency="urgent")).json()["id"]
    alert = await api_db.scalar(select(m.RiskAlert).where(m.RiskAlert.source_id == uuid.UUID(rid)))
    assert alert is not None and alert.source is AlertSource.FACULTY_REFERRAL
    assert alert.severity is AlertSeverity.HIGH and alert.requires_human
    assert alert.excerpt is None  # the teacher's words stay with the referral
    plain = await refer(s, s.students[1])
    assert (
        await api_db.scalar(
            select(m.RiskAlert).where(m.RiskAlert.source_id == uuid.UUID(plain.json()["id"]))
        )
        is None
    )


async def test_the_audit_log_records_the_referral_without_its_note(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=1, data=False)
    await refer(s, s.students[0])
    row = await api_db.scalar(
        select(m.AuditLog).where(
            m.AuditLog.actor_id == s.teacher.id, m.AuditLog.action == "referral.create"
        )
    )
    assert row is not None and row.subject_student_id == s.students[0].user_id
    assert row.details == {"category": "wellbeing_concern", "urgency": "routine", "has_note": True}


async def test_another_teacher_cannot_see_or_open_my_referral(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=1, data=False)
    rid = (await refer(s, s.students[0])).json()["id"]
    colleague = await another_teacher(client, api_db, world, s.dept_id)
    assert (await colleague.get(f"/teacher/referrals/{rid}")).status_code == 404
    assert (await colleague.get("/teacher/referrals")).json() == []


# ---- therapist triage -----------------------------------------------------------------------


async def verified_therapist(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> Session:
    t, _ = await new_therapist(client, api_db, world)
    return t


async def test_triage_queue_shows_unassigned_students_and_my_own_only(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=3, data=False)
    mine, theirs = (
        await verified_therapist(client, api_db, world),
        await verified_therapist(client, api_db, world),
    )
    b = Builder(api_db, world.password)
    await b.care_link(world.inst_a, s.students[0], mine.actor)
    await b.care_link(world.inst_a, s.students[1], theirs.actor)
    await api_db.commit()  # students[2] has no care team
    for p in s.students:
        assert (await refer(s, p)).status_code == 201

    ours = {str(p.user_id) for p in s.students}

    async def visible(t: Session) -> set[str]:
        # the queue is shared by everyone, so look only at this test's students
        return {r["student_id"] for r in (await t.get("/therapist/referrals")).json()} & ours

    assert await visible(mine) == {str(s.students[0].user_id), str(s.students[2].user_id)}
    assert await visible(theirs) == {str(s.students[1].user_id), str(s.students[2].user_id)}
    row = next(
        r for r in (await mine.get("/therapist/referrals")).json()
        if r["student_id"] == str(s.students[0].user_id)
    )  # fmt: skip
    assert row["on_my_team"] is True and row["teacher_name"] and row["department_name"]
    other = next(
        r for r in (await theirs.get("/therapist/referrals")).json()
        if r["student_id"] == str(s.students[1].user_id)
    )  # fmt: skip
    assert (await mine.get(f"/therapist/referrals/{other['id']}")).status_code == 404
    assert (await mine.post(f"/therapist/referrals/{other['id']}/claim")).status_code == 404


async def test_an_unverified_therapist_cannot_triage(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=1, data=False)
    rid = (await refer(s, s.students[0])).json()["id"]
    pending, _ = await new_therapist(client, api_db, world, verified=False)
    assert (await pending.get("/therapist/referrals")).status_code == 403
    assert (await pending.post(f"/therapist/referrals/{rid}/claim")).status_code == 403


async def test_claim_notifies_the_student_neutrally_and_close_records_the_outcome(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=1, data=False)
    rid = (await refer(s, s.students[0], note="Secret observation.")).json()["id"]
    therapist = await verified_therapist(client, api_db, world)

    claimed = await therapist.post(f"/therapist/referrals/{rid}/claim")
    assert claimed.status_code == 200 and claimed.json()["status"] == "in_progress"
    assert claimed.json()["claimed_by_me"] is True
    assert (await therapist.post(f"/therapist/referrals/{rid}/claim")).status_code == 409

    ping = await notifications(api_db, s.students[0].user_id)
    mine = [n for n in ping if n.title.startswith("The wellbeing team")]
    assert len(mine) == 1 and mine[0].payload == {}
    blob = (mine[0].title + str(mine[0].payload)).lower()
    for leak in ("teacher", "referral", "secret", s.teacher.actor.email):
        assert leak not in blob

    seen = (await s.teacher.get(f"/teacher/referrals/{rid}")).json()
    assert seen["status"] == "in_progress" and seen["status_label"] == "With the wellbeing team"
    assert set(seen) == TEACHER_VIEW_KEYS  # no therapist, no outcome, no timestamps of handling

    closed = await therapist.post(
        f"/therapist/referrals/{rid}/close", {"outcome": "contacted_student"}
    )
    assert closed.status_code == 200 and closed.json()["outcome"] == "contacted_student"
    seen = (await s.teacher.get(f"/teacher/referrals/{rid}")).json()
    assert seen["status"] == "closed" and set(seen) == TEACHER_VIEW_KEYS
    assert "contacted" not in str(seen)
    assert (
        await therapist.post(f"/therapist/referrals/{rid}/close", {"outcome": "no_action_needed"})
    ).status_code == 409
    # closed, so the teacher can refer again
    assert (await refer(s, s.students[0])).status_code == 201


async def test_only_the_therapist_who_claimed_it_can_close_it(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=1, data=False)
    rid = (await refer(s, s.students[0])).json()["id"]
    first, second = (
        await verified_therapist(client, api_db, world),
        await verified_therapist(client, api_db, world),
    )
    assert (
        await first.post(f"/therapist/referrals/{rid}/close", {"outcome": "no_action_needed"})
    ).status_code == 409
    assert (await first.post(f"/therapist/referrals/{rid}/claim")).status_code == 200
    assert (await second.post(f"/therapist/referrals/{rid}/claim")).status_code == 404
    assert (
        await second.post(f"/therapist/referrals/{rid}/close", {"outcome": "no_action_needed"})
    ).status_code == 404
    assert rid not in {r["id"] for r in (await second.get("/therapist/referrals")).json()}
    assert (
        await first.post(f"/therapist/referrals/{rid}/close", {"outcome": "nonsense"})
    ).status_code == 422


async def test_other_institutions_therapist_sees_nothing(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=1, data=False)
    rid = (await refer(s, s.students[0])).json()["id"]
    b_therapist = await sign_in(client, world.b_therapist, world.password)
    assert rid not in {r["id"] for r in (await b_therapist.get("/therapist/referrals")).json()}
    assert (await b_therapist.get(f"/therapist/referrals/{rid}")).status_code == 404
    assert (await b_therapist.post(f"/therapist/referrals/{rid}/claim")).status_code == 404


# ---- students asking a teacher for help -----------------------------------------------------


def ask_body(s: School, **kw: object) -> dict[str, object]:
    return {
        "course_id": str(s.course_id),
        "teacher_id": str(s.teacher.id),
        "topic": "extension",
        "message": "Could I have two more days for the essay?",
        **kw,
    }


async def test_a_student_sees_only_their_own_courses_and_teachers(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=2, data=False)
    other = await school(client, api_db, world, students=1, data=False)
    student = await sign_in(client, s.students[0], world.password)
    options = (await student.get("/me/teacher-support/options")).json()
    assert [o["course_id"] for o in options] == [str(s.course_id)]
    assert [t["teacher_id"] for t in options[0]["teachers"]] == [str(s.teacher.id)]
    assert str(other.course_id) not in str(options)


async def test_a_student_asks_their_teacher_and_the_teacher_answers(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=2, data=False)
    student = await sign_in(client, s.students[0], world.password)
    r = await student.post("/me/teacher-support", ask_body(s))
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["status"] == "open" and r.json()["topic_label"]

    inbox = (await s.teacher.get("/teacher/support-requests")).json()
    assert [x["id"] for x in inbox] == [rid]
    assert inbox[0]["message"].startswith("Could I have") and inbox[0]["student_name"]
    assert (await s.teacher.get("/teacher/dashboard")).json()["new_support_requests"] == 1
    assert any(
        n.title.startswith("A student has asked") for n in await notifications(api_db, s.teacher.id)
    )

    seen = await s.teacher.post(f"/teacher/support-requests/{rid}/acknowledge")
    assert seen.status_code == 200 and seen.json()["status"] == "acknowledged"
    assert (await s.teacher.post(f"/teacher/support-requests/{rid}/acknowledge")).status_code == 409
    assert any(
        n.title.startswith("Your teacher has seen")
        for n in await notifications(api_db, s.students[0].user_id)
    )
    assert (await s.teacher.post(f"/teacher/support-requests/{rid}/close")).json()[
        "status"
    ] == "closed"
    assert (await s.teacher.get("/teacher/support-requests")).json() == []
    assert len((await s.teacher.get("/teacher/support-requests?status=closed")).json()) == 1


async def test_a_student_can_withdraw_and_the_teacher_no_longer_sees_it(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=2, data=False)
    student = await sign_in(client, s.students[0], world.password)
    rid = (await student.post("/me/teacher-support", ask_body(s))).json()["id"]
    assert (await student.post("/me/teacher-support", ask_body(s))).status_code == 409
    assert (await student.post(f"/me/teacher-support/{rid}/withdraw")).json()[
        "status"
    ] == "withdrawn"
    assert (await s.teacher.get("/teacher/support-requests")).json() == []
    assert (await student.post(f"/me/teacher-support/{rid}/withdraw")).status_code == 409
    assert (await student.post("/me/teacher-support", ask_body(s))).status_code == 201


async def test_requests_must_name_a_real_teacher_of_a_course_the_student_is_in(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=2, data=False)
    other = await school(client, api_db, world, students=1, data=False)
    student = await sign_in(client, s.students[0], world.password)
    for body in (
        ask_body(other),  # a course the student is not in
        ask_body(s, teacher_id=str(other.teacher.id)),  # a teacher who does not teach it
        ask_body(s, teacher_id=str(uuid.uuid4())),
        ask_body(s, course_id=str(uuid.uuid4())),
    ):
        assert (await student.post("/me/teacher-support", body)).status_code == 404
    assert (await student.post("/me/teacher-support", ask_body(s, topic="rant"))).status_code == 422
    assert (
        await student.post("/me/teacher-support", ask_body(s, message="x" * 601))
    ).status_code == 422
    assert (await student.get("/me/teacher-support")).json() == []


async def test_only_the_named_teacher_and_the_student_can_act_on_a_request(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await school(client, api_db, world, students=2, data=False)
    student = await sign_in(client, s.students[0], world.password)
    rid = (await student.post("/me/teacher-support", ask_body(s))).json()["id"]
    colleague = await another_teacher(client, api_db, world, s.dept_id)
    classmate = await sign_in(client, s.students[1], world.password)
    assert (await colleague.get("/teacher/support-requests")).json() == []
    assert (await colleague.post(f"/teacher/support-requests/{rid}/acknowledge")).status_code == 404
    assert (await colleague.post(f"/teacher/support-requests/{rid}/close")).status_code == 404
    assert (await classmate.post(f"/me/teacher-support/{rid}/withdraw")).status_code == 404
    assert (await classmate.get("/me/teacher-support")).json() == []
    audit = await api_db.scalar(
        select(m.AuditLog).where(
            m.AuditLog.actor_id == colleague.id, m.AuditLog.outcome == AuditOutcome.DENIED
        )
    )
    assert audit is not None
