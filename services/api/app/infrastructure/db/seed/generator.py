"""Synthetic development data generator.

Everything produced here is fictional: names come from Faker, emails use the reserved
``.example`` TLD, free text comes from fixed non-clinical pools, and the institution is
flagged ``is_synthetic``. The generator is deterministic for a given ``seed``/``as_of``.
It never runs when APP_ENV=production.
"""

import dataclasses
import datetime as dt
import random
import uuid
from decimal import Decimal

from faker import Faker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AdminLevel,
    AIConversationStatus,
    AIMessageRole,
    AlertCategory,
    AlertDetector,
    AlertSeverity,
    AlertSource,
    AlertStatus,
    AppointmentStatus,
    AuditOutcome,
    CareRole,
    ConsentScope,
    GoalCategory,
    GoalStatus,
    NotificationChannel,
    NotificationPriority,
    NotificationType,
    RecommendationSource,
    RecommendationStatus,
    ResourceType,
    SessionMode,
    TherapySessionStatus,
    UserRole,
    UserStatus,
)
from app.infrastructure.db.ids import uuid7
from app.infrastructure.db.seed import content as c

INSTITUTION_SLUG = "synthetic-institute"
POLICY_VERSION = "2026-10-01"
UTC = dt.UTC


class SeedRefused(RuntimeError):
    """Raised when seeding is unsafe (production, or data already present)."""


@dataclasses.dataclass(frozen=True)
class SeedConfig:
    students: int = 120
    teachers: int = 8
    therapists: int = 6
    history_days: int = 45
    future_days: int = 14
    seed: int = 20261008
    as_of: dt.datetime = dataclasses.field(
        default_factory=lambda: dt.datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    )
    password: str | None = None  # None -> a random password is generated


@dataclasses.dataclass
class SeedResult:
    institution_id: uuid.UUID
    password: str
    counts: dict[str, int]


def _utc(d: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(d.year, d.month, d.day, hour, minute, tzinfo=UTC)


async def seed_database(session: AsyncSession, cfg: SeedConfig | None = None) -> SeedResult:
    cfg = cfg or SeedConfig()
    if get_settings().is_production:
        raise SeedRefused("refusing to seed synthetic data when APP_ENV=production")
    exists = await session.scalar(
        select(m.Institution.id).where(m.Institution.slug == INSTITUTION_SLUG)
    )
    if exists:
        raise SeedRefused(
            f"institution '{INSTITUTION_SLUG}' already exists; recreate the database "
            "(alembic downgrade base && alembic upgrade head) to reseed"
        )
    if cfg.therapists < 1 or cfg.students < 1 or cfg.teachers < 1:
        raise SeedRefused("need at least one student, teacher and therapist")

    import secrets

    password = cfg.password or secrets.token_urlsafe(18)
    rng = random.Random(cfg.seed)
    fake = Faker("en_IN")
    Faker.seed(cfg.seed)
    counts: dict[str, int] = {}

    def bump(name: str, n: int = 1) -> None:
        counts[name] = counts.get(name, 0) + n

    now = cfg.as_of
    today = now.date()
    start_day = today - dt.timedelta(days=cfg.history_days)

    # -- institution & structure ---------------------------------------------------
    inst = m.Institution(
        id=uuid7(),
        name="Synthetic Institute of Technology",
        slug=INSTITUTION_SLUG,
        email_domains=["synthetic.example"],
        is_synthetic=True,
    )
    session.add(inst)
    await session.flush()
    iid = inst.id

    depts: list[m.Department] = []
    for name, code in c.DEPARTMENTS:
        depts.append(m.Department(id=uuid7(), institution_id=iid, name=name, code=code))
    session.add_all(depts)
    await session.flush()
    bump("departments", len(depts))

    courses: list[m.Course] = []
    term = f"{today.year}-autumn"
    for d in depts:
        for i, tpl in enumerate(c.COURSE_TITLES, start=1):
            courses.append(
                m.Course(
                    id=uuid7(),
                    institution_id=iid,
                    department_id=d.id,
                    code=f"{d.code}{100 * i + 1}",
                    title=tpl.format(d=d.name),
                    term=term,
                    credits=rng.choice([2, 3, 4]),
                )
            )
    session.add_all(courses)
    await session.flush()
    bump("courses", len(courses))
    courses_by_dept: dict[uuid.UUID, list[m.Course]] = {}
    for crs in courses:
        courses_by_dept.setdefault(crs.department_id, []).append(crs)

    # -- users ----------------------------------------------------------------------
    used_emails: set[str] = set()

    def make_user(role: UserRole, domain: str) -> m.User:
        while True:
            name = fake.name()
            local = "".join(
                ch for ch in name.lower().replace(" ", ".") if ch.isalnum() or ch == "."
            )
            email = f"{local}.{rng.randint(10, 99)}@{domain}"
            if email not in used_emails:
                used_emails.add(email)
                break
        u = m.User(
            id=uuid7(),
            institution_id=iid,
            email=email,
            full_name=name,
            role=role,
            status=UserStatus.ACTIVE,
            last_login_at=now - dt.timedelta(hours=rng.randint(1, 400)),
        )
        u.credential = m.Credential(password_hash=hash_password(password))
        return u

    admin_users = [make_user(UserRole.ADMINISTRATOR, "staff.synthetic.example") for _ in range(2)]
    teacher_users = [
        make_user(UserRole.TEACHER, "staff.synthetic.example") for _ in range(cfg.teachers)
    ]
    therapist_users = [
        make_user(UserRole.THERAPIST, "care.synthetic.example") for _ in range(cfg.therapists)
    ]
    student_users = [
        make_user(UserRole.STUDENT, "students.synthetic.example") for _ in range(cfg.students)
    ]
    # a couple of non-active accounts for realism
    student_users[-1].status = UserStatus.INVITED
    student_users[-1].last_login_at = None
    all_users = admin_users + teacher_users + therapist_users + student_users
    session.add_all(all_users)
    await session.flush()
    bump("users", len(all_users))

    session.add_all(
        m.Administrator(
            user_id=u.id,
            institution_id=iid,
            admin_level=AdminLevel.INSTITUTION_ADMIN,
        )
        for u in admin_users
    )
    teachers = [
        m.Teacher(
            user_id=u.id,
            institution_id=iid,
            department_id=depts[i % len(depts)].id,
            employee_number=f"SYN-E{i + 1:04d}",
            title=rng.choice(["Assistant Professor", "Associate Professor", "Lecturer"]),
        )
        for i, u in enumerate(teacher_users)
    ]
    therapists = [
        m.Therapist(
            user_id=u.id,
            institution_id=iid,
            licence_number=f"SYN-LIC-{i + 1:04d}",
            specialties=rng.sample(c.SPECIALTIES, k=3),
            languages=["English", *rng.sample(c.LANGUAGES[1:], k=rng.randint(1, 2))],
            bio="Synthetic profile for development.",
            accepting_new_students=i % 5 != 4,
            max_caseload=rng.choice([25, 30, 40]),
        )
        for i, u in enumerate(therapist_users)
    ]
    students: list[m.Student] = []
    for i, u in enumerate(student_users):
        dept = depts[i % len(depts)]
        yos = rng.randint(1, 4)
        students.append(
            m.Student(
                user_id=u.id,
                institution_id=iid,
                department_id=dept.id,
                student_number=f"SYN-S{today.year}{i + 1:05d}",
                enrollment_year=today.year - yos + 1,
                year_of_study=yos,
                preferred_name=u.full_name.split()[0],
                pronouns=rng.choice([None, "she/her", "he/him", "they/them"]),
                locale=rng.choice(["en", "en", "hi"]),
            )
        )
    session.add_all(teachers)
    session.add_all(therapists)
    session.add_all(students)
    await session.flush()
    bump("administrators", len(admin_users))
    bump("teachers", len(teachers))
    bump("therapists", len(therapists))
    bump("students", len(students))

    # course teaching & enrollment
    ct = []
    for tch in teachers:
        for crs in courses_by_dept[tch.department_id][:2]:
            ct.append(m.CourseTeacher(course_id=crs.id, teacher_id=tch.user_id))
    session.add_all(ct)
    enrolls = []
    for s in students:
        own = courses_by_dept[s.department_id]
        picks = set(rng.sample(own, k=min(len(own), rng.randint(2, 3))))
        other = rng.choice(courses)
        picks.add(other)
        for crs in picks:
            enrolls.append(m.CourseEnrollment(course_id=crs.id, student_id=s.user_id))
    session.add_all(enrolls)
    await session.flush()
    bump("course_teachers", len(ct))
    bump("course_enrollments", len(enrolls))

    # -- care teams -------------------------------------------------------------------
    care_pairs: list[tuple[m.Student, m.Therapist]] = []
    load = {t.user_id: 0 for t in therapists}
    for i, s in enumerate(students[:-1]):
        if rng.random() > 0.65:
            continue
        candidates = [t for t in therapists if load[t.user_id] < min(t.max_caseload, 28)]
        if not candidates:
            break
        t = candidates[i % len(candidates)]
        load[t.user_id] += 1
        care_pairs.append((s, t))
    session.add_all(
        m.CareTeamMember(
            student_id=s.user_id,
            therapist_id=t.user_id,
            role=CareRole.PRIMARY,
            starts_at=now - dt.timedelta(days=rng.randint(30, 120)),
        )
        for s, t in care_pairs
    )
    await session.flush()
    bump("care_team_members", len(care_pairs))
    care_of = {s.user_id: t for s, t in care_pairs}

    # -- consents ---------------------------------------------------------------------
    consents: list[m.Consent] = []
    for u in all_users:
        consents.append(_consent(iid, u.id, ConsentScope.TERMS_AND_PRIVACY, now, rng))
    for s in students:
        sid = s.user_id
        if sid in care_of and rng.random() < 0.8:
            consents.append(_consent(iid, sid, ConsentScope.SHARE_MOOD_WITH_CARE_TEAM, now, rng))
            if rng.random() < 0.6:
                consents.append(
                    _consent(iid, sid, ConsentScope.SHARE_ASSESSMENTS_WITH_CARE_TEAM, now, rng)
                )
        if rng.random() < 0.3:
            consents.append(_consent(iid, sid, ConsentScope.JOURNAL_SAFETY_SCANNING, now, rng))
        if rng.random() < 0.2:
            consents.append(_consent(iid, sid, ConsentScope.EMAIL_NOTIFICATIONS, now, rng))
        if rng.random() < 0.15:  # a granted-then-revoked history row
            g = now - dt.timedelta(days=rng.randint(20, 60))
            consents.append(
                m.Consent(
                    institution_id=iid,
                    user_id=sid,
                    scope=ConsentScope.ANONYMOUS_AGGREGATE_RESEARCH,
                    policy_version=POLICY_VERSION,
                    granted_at=g,
                    revoked_at=g + dt.timedelta(days=rng.randint(1, 15)),
                )
            )
    session.add_all(consents)
    await session.flush()
    bump("consents", len(consents))

    # -- resources & recommendations ------------------------------------------------------
    reviewer = admin_users[0]
    resources: list[m.Resource] = []
    for idx, (title, summary, rtype, tags, minutes) in enumerate(c.RESOURCES):
        published = not title.startswith("Draft:")
        resources.append(
            m.Resource(
                institution_id=None if idx % 3 == 0 else iid,
                title=title,
                summary=summary,
                body=f"Synthetic body text for '{title}'.",
                resource_type=ResourceType(rtype),
                tags=tags,
                duration_minutes=minutes,
                is_published=published,
                reviewed_by=reviewer.id if published else None,
                reviewed_at=now - dt.timedelta(days=rng.randint(10, 90)) if published else None,
            )
        )
    session.add_all(resources)
    await session.flush()
    bump("resources", len(resources))
    published_resources = [r for r in resources if r.is_published]

    # -- per-student wellness data ----------------------------------------------------------
    moods, sleeps, wassess, sassess, goals, journals, shares, recs = [], [], [], [], [], [], [], []
    for s in students:
        base = rng.uniform(2.4, 4.2)
        level = base
        for offset in range(cfg.history_days):
            day = start_day + dt.timedelta(days=offset)
            # a mild dip in the middle of the period stands in for exam season
            exam = 1 if 18 <= offset <= 26 else 0
            level = 0.8 * level + 0.2 * base + rng.gauss(0, 0.35) - 0.25 * exam
            if rng.random() < 0.72:
                score = max(1, min(5, round(level)))
                logged = _utc(day, rng.randint(7, 22), rng.randint(0, 59))
                moods.append(
                    m.MoodEntry(
                        institution_id=iid,
                        student_id=s.user_id,
                        mood_score=score,
                        energy_level=max(1, min(5, score + rng.choice([-1, 0, 0, 1]))),
                        emotions=rng.sample(c.EMOTIONS, k=rng.randint(1, 3)),
                        note=rng.choice(c.MOOD_NOTES) if rng.random() < 0.3 else None,
                        logged_at=logged,
                        created_at=logged,
                        updated_at=logged,
                    )
                )
            if rng.random() < 0.8:
                bed_h = rng.choice([22, 23, 23, 0, 1])
                bed = _utc(day - dt.timedelta(days=1), 22) + dt.timedelta(
                    hours=bed_h - 22 if bed_h >= 22 else bed_h + 2
                )
                minutes = int(max(240, min(600, rng.gauss(405 + 20 * (level - 3), 55))))
                wake = bed + dt.timedelta(minutes=minutes)
                sleeps.append(
                    m.SleepEntry(
                        institution_id=iid,
                        student_id=s.user_id,
                        sleep_date=day,
                        bedtime=bed,
                        wake_time=wake,
                        duration_minutes=minutes,
                        quality=max(1, min(5, round(level + rng.gauss(0, 0.6)))),
                    )
                )
        for wk in range(0, cfg.history_days, 7):
            when = _utc(start_day + dt.timedelta(days=wk + rng.randint(0, 3)), rng.randint(9, 20))
            if when > now:
                continue
            ws = max(0, min(25, round(base * 5 + rng.gauss(0, 2.5))))
            wassess.append(
                m.WellnessAssessment(
                    institution_id=iid,
                    student_id=s.user_id,
                    instrument="wellbeing_index_5",
                    instrument_version="1",
                    score=Decimal(ws),
                    max_score=Decimal(25),
                    responses={f"q{i}": rng.randint(0, 5) for i in range(1, 6)},
                    completed_at=when,
                    created_at=when,
                    updated_at=when,
                )
            )
        for wk in range(0, cfg.history_days, 14):
            when = _utc(start_day + dt.timedelta(days=wk + rng.randint(0, 5)), rng.randint(9, 20))
            if when > now:
                continue
            ss = max(0, min(40, round((5 - base) * 8 + rng.gauss(8, 4))))
            sassess.append(
                m.StressAssessment(
                    institution_id=iid,
                    student_id=s.user_id,
                    scale="perceived_stress_10",
                    score=Decimal(ss),
                    max_score=Decimal(40),
                    perceived_stress_level=max(1, min(5, 1 + ss // 9)),
                    stressors=rng.sample(c.STRESSORS, k=rng.randint(1, 3)),
                    completed_at=when,
                    created_at=when,
                    updated_at=when,
                )
            )
        for _ in range(rng.choice([0, 0, 1, 2, 3])):
            title, cat, unit, target = rng.choice(c.GOAL_TEMPLATES)
            started = today - dt.timedelta(days=rng.randint(5, 40))
            goal_status = rng.choices(
                [GoalStatus.ACTIVE, GoalStatus.COMPLETED, GoalStatus.PAUSED], [6, 2, 1]
            )[0]
            done = goal_status is GoalStatus.COMPLETED
            goals.append(
                m.WellnessGoal(
                    institution_id=iid,
                    student_id=s.user_id,
                    title=title,
                    category=GoalCategory(cat),
                    status=goal_status,
                    target_value=Decimal(target),
                    current_value=Decimal(target if done else rng.randint(0, target)),
                    unit=unit,
                    start_date=started,
                    target_date=started + dt.timedelta(days=rng.randint(14, 60)),
                    completed_at=_utc(started + dt.timedelta(days=rng.randint(5, 30)), 18)
                    if done
                    else None,
                )
            )
        if rng.random() < 0.4:
            for _ in range(rng.randint(1, 5)):
                created = _utc(
                    start_day + dt.timedelta(days=rng.randint(0, cfg.history_days - 1)),
                    rng.randint(8, 23),
                )
                entry = m.JournalEntry(
                    id=uuid7(),
                    institution_id=iid,
                    student_id=s.user_id,
                    title=rng.choice(c.JOURNAL_TITLES) if rng.random() < 0.7 else None,
                    body=rng.choice(c.JOURNAL_BODIES),
                    mood_tag=rng.choice(c.EMOTIONS),
                    created_at=created,
                    updated_at=created,
                )
                journals.append(entry)
                th = care_of.get(s.user_id)
                if th and rng.random() < 0.15:
                    shares.append(
                        m.JournalShare(
                            entry_id=entry.id,
                            therapist_id=th.user_id,
                            shared_at=created + dt.timedelta(hours=2),
                        )
                    )
        for res in rng.sample(published_resources, k=rng.choice([0, 1, 2, 3])):
            recs.append(
                m.Recommendation(
                    institution_id=iid,
                    student_id=s.user_id,
                    resource_id=res.id,
                    source=RecommendationSource.MODEL,
                    model_version="synthetic-recommender-0.1",
                    status=rng.choice(list(RecommendationStatus)),
                    title=res.title,
                    rationale=(
                        "Suggested based on your recent check-ins. "
                        "It's an optional idea, not advice."
                    ),
                    confidence=Decimal(str(round(rng.uniform(0.55, 0.92), 3))),
                    expires_at=now + dt.timedelta(days=14),
                )
            )
    for rows in (moods, sleeps, wassess, sassess, goals, journals):
        session.add_all(rows)
    await session.flush()
    session.add_all(shares)
    session.add_all(recs)
    await session.flush()
    for name, n in (
        ("mood_entries", len(moods)),
        ("sleep_entries", len(sleeps)),
        ("wellness_assessments", len(wassess)),
        ("stress_assessments", len(sassess)),
        ("wellness_goals", len(goals)),
        ("journal_entries", len(journals)),
        ("journal_shares", len(shares)),
        ("recommendations", len(recs)),
    ):
        bump(name, n)

    # -- therapist availability, appointments, sessions, notes --------------------------------
    slots: dict[tuple[uuid.UUID, dt.date, int], m.TherapistAvailability] = {}
    for t in therapists:
        for off in range(-cfg.history_days, cfg.future_days + 1):
            day = today + dt.timedelta(days=off)
            if day.weekday() >= 5:
                continue
            for hour in range(10, 16):
                a = m.TherapistAvailability(
                    id=uuid7(),
                    institution_id=iid,
                    therapist_id=t.user_id,
                    starts_at=_utc(day, hour),
                    ends_at=_utc(day, hour + 1),
                    mode=rng.choice([SessionMode.VIDEO, SessionMode.VIDEO, SessionMode.IN_PERSON]),
                )
                slots[(t.user_id, day, hour)] = a
    session.add_all(slots.values())
    await session.flush()
    bump("therapist_availability", len(slots))

    regular: dict[uuid.UUID, tuple[int, int]] = {}
    taken: dict[uuid.UUID, set[tuple[int, int]]] = {t.user_id: set() for t in therapists}
    appts: list[m.Appointment] = []
    sessions_: list[m.TherapySession] = []
    notes: list[m.TherapyNote] = []
    free_pool = {t.user_id: [(wd, h) for wd in range(5) for h in range(10, 16)] for t in therapists}
    for s, t in care_pairs:
        pool = [p for p in free_pool[t.user_id] if p not in taken[t.user_id]]
        if not pool:
            continue
        choice = rng.choice(pool)
        taken[t.user_id].add(choice)
        regular[s.user_id] = choice
    used_slot_ids: set[uuid.UUID] = set()
    for s, t in care_pairs:
        if s.user_id not in regular:
            continue
        wd, hour = regular[s.user_id]
        for week in range(-(cfg.history_days // 7), 3):
            anchor = today + dt.timedelta(weeks=week)
            day = anchor - dt.timedelta(days=anchor.weekday()) + dt.timedelta(days=wd)
            slot = slots.get((t.user_id, day, hour))
            if slot is None or slot.id in used_slot_ids or rng.random() < 0.15:
                continue
            used_slot_ids.add(slot.id)
            past = slot.ends_at <= now
            if past:
                ap_status = rng.choices(
                    [
                        AppointmentStatus.COMPLETED,
                        AppointmentStatus.NO_SHOW,
                        AppointmentStatus.CANCELLED,
                    ],
                    [14, 1, 2],
                )[0]
            else:
                ap_status = rng.choice(
                    [
                        AppointmentStatus.CONFIRMED,
                        AppointmentStatus.CONFIRMED,
                        AppointmentStatus.REQUESTED,
                    ]
                )
            created = slot.starts_at - dt.timedelta(days=rng.randint(2, 9))
            ap = m.Appointment(
                id=uuid7(),
                institution_id=iid,
                student_id=s.user_id,
                therapist_id=t.user_id,
                availability_id=slot.id,
                starts_at=slot.starts_at,
                ends_at=slot.ends_at,
                mode=slot.mode,
                status=ap_status,
                reason="Regular check-in (synthetic)" if rng.random() < 0.6 else None,
                cancelled_at=created + dt.timedelta(days=1)
                if ap_status is AppointmentStatus.CANCELLED
                else None,
                cancelled_by=s.user_id if ap_status is AppointmentStatus.CANCELLED else None,
                created_at=created,
                updated_at=created,
            )
            appts.append(ap)
            if ap_status is AppointmentStatus.COMPLETED:
                dur = 50
                sess = m.TherapySession(
                    id=uuid7(),
                    institution_id=iid,
                    appointment_id=ap.id,
                    student_id=s.user_id,
                    therapist_id=t.user_id,
                    status=TherapySessionStatus.COMPLETED,
                    started_at=slot.starts_at,
                    ended_at=slot.starts_at + dt.timedelta(minutes=dur),
                    duration_minutes=dur,
                    video_meeting_ref=f"synthetic-{uuid7().hex[:12]}"
                    if slot.mode is SessionMode.VIDEO
                    else None,
                )
                sessions_.append(sess)
                v1 = m.TherapyNote(
                    institution_id=iid,
                    session_id=sess.id,
                    author_id=t.user_id,
                    version=1,
                    body=rng.choice(c.THERAPY_NOTE_SNIPPETS),
                    created_at=sess.ended_at,
                    updated_at=sess.ended_at,
                )
                notes.append(v1)
                if rng.random() < 0.2:
                    later = slot.starts_at + dt.timedelta(minutes=dur, hours=3)
                    notes.append(
                        m.TherapyNote(
                            institution_id=iid,
                            session_id=sess.id,
                            author_id=t.user_id,
                            version=2,
                            body=v1.body + " Addendum: follow-up planned (synthetic).",
                            created_at=later,
                            updated_at=later,
                        )
                    )
    session.add_all(appts)
    await session.flush()
    session.add_all(sessions_)
    await session.flush()
    session.add_all(notes)
    await session.flush()
    bump("appointments", len(appts))
    bump("therapy_sessions", len(sessions_))
    bump("therapy_notes", len(notes))

    # -- messaging ---------------------------------------------------------------------------
    msgs = []
    for s, t in care_pairs:
        t0 = now - dt.timedelta(days=rng.randint(2, 30))
        for k in range(rng.choice([0, 2, 4, 6])):
            from_student = k % 2 == 0
            created = t0 + dt.timedelta(hours=3 * k + rng.randint(0, 2))
            if created > now:
                break
            msgs.append(
                m.Message(
                    institution_id=iid,
                    student_id=s.user_id,
                    therapist_id=t.user_id,
                    sender_id=s.user_id if from_student else t.user_id,
                    body=rng.choice(c.MESSAGES_STUDENT if from_student else c.MESSAGES_THERAPIST),
                    client_msg_id=uuid7(),
                    crisis_checked_at=created if from_student else None,
                    read_at=created + dt.timedelta(minutes=rng.randint(5, 300)) if k < 4 else None,
                    created_at=created,
                    updated_at=created,
                )
            )
    session.add_all(msgs)
    await session.flush()
    bump("messages", len(msgs))

    # -- AI companion --------------------------------------------------------------------------
    convs, aimsgs = [], []
    for s in students:
        if rng.random() > 0.4:
            continue
        for _ in range(rng.randint(1, 2)):
            started = now - dt.timedelta(days=rng.randint(1, 30), hours=rng.randint(0, 20))
            conv = m.AIConversation(
                id=uuid7(),
                institution_id=iid,
                student_id=s.user_id,
                started_at=started,
                ended_at=started + dt.timedelta(minutes=rng.randint(5, 40)),
                status=AIConversationStatus.ENDED,
                model_version="synthetic-companion-0.1",
                expires_at=started + dt.timedelta(days=30),
                created_at=started,
                updated_at=started,
            )
            convs.append(conv)
            for seq in range(1, rng.choice([4, 6, 8]) + 1):
                user_turn = seq % 2 == 1
                ts = started + dt.timedelta(minutes=seq)
                aimsgs.append(
                    m.AIMessage(
                        conversation_id=conv.id,
                        seq=seq,
                        role=AIMessageRole.USER if user_turn else AIMessageRole.ASSISTANT,
                        content=rng.choice(
                            c.AI_USER_PROMPTS if user_turn else c.AI_ASSISTANT_REPLIES
                        ),
                        token_count=rng.randint(20, 160),
                        created_at=ts,
                        updated_at=ts,
                    )
                )
    session.add_all(convs)
    await session.flush()
    session.add_all(aimsgs)
    await session.flush()
    bump("ai_conversations", len(convs))
    bump("ai_messages", len(aimsgs))

    # -- risk alerts (synthetic fixtures for the escalation workflow) -----------------------------
    alerts = []
    scenarios = [
        (
            AlertSeverity.LOW,
            AlertStatus.RESOLVED,
            AlertCategory.SUSTAINED_LOW_WELLBEING,
            AlertDetector.CLASSIFIER,
        ),
        (
            AlertSeverity.MODERATE,
            AlertStatus.RESOLVED,
            AlertCategory.ENGAGEMENT_DROP,
            AlertDetector.CLASSIFIER,
        ),
        (
            AlertSeverity.MODERATE,
            AlertStatus.IN_PROGRESS,
            AlertCategory.ACUTE_DISTRESS,
            AlertDetector.RULES,
        ),
        (
            AlertSeverity.HIGH,
            AlertStatus.ACKNOWLEDGED,
            AlertCategory.ACUTE_DISTRESS,
            AlertDetector.RULES,
        ),
        (
            AlertSeverity.HIGH,
            AlertStatus.OPEN,
            AlertCategory.SELF_HARM_LANGUAGE,
            AlertDetector.RULES,
        ),
        (
            AlertSeverity.IMMINENT,
            AlertStatus.RESOLVED,
            AlertCategory.SUICIDAL_LANGUAGE,
            AlertDetector.RULES,
        ),
        (
            AlertSeverity.LOW,
            AlertStatus.DISMISSED,
            AlertCategory.ENGAGEMENT_DROP,
            AlertDetector.CLASSIFIER,
        ),
    ]
    alert_pool = [stu for stu, _ in care_pairs] or students
    for i, (sev, st, cat, det) in enumerate(scenarios):
        stu = alert_pool[(i * 7) % len(alert_pool)]
        created = now - dt.timedelta(hours=rng.randint(2, 24 * 20))
        th = care_of.get(stu.user_id)
        ack = created + dt.timedelta(minutes=rng.randint(2, 9))
        needs_ack = st not in (AlertStatus.OPEN, AlertStatus.DISMISSED)
        done = st in (AlertStatus.RESOLVED, AlertStatus.DISMISSED)
        alerts.append(
            m.RiskAlert(
                institution_id=iid,
                student_id=stu.user_id,
                assigned_to=th.user_id if th else None,
                source=AlertSource.MODEL
                if det is AlertDetector.CLASSIFIER
                else AlertSource.MOOD_ENTRY,
                detector=det,
                category=cat,
                severity=sev,
                status=st,
                confidence=Decimal(str(round(rng.uniform(0.6, 0.97), 3)))
                if det is AlertDetector.CLASSIFIER
                else None,
                model_version="synthetic-detector-0.1" if det is AlertDetector.CLASSIFIER else None,
                excerpt=c.CRISIS_FIXTURE_EXCERPT,
                sla_ack_due_at=created + dt.timedelta(minutes=10)
                if sev in (AlertSeverity.HIGH, AlertSeverity.IMMINENT)
                else None,
                acknowledged_at=ack if needs_ack else None,
                resolved_at=ack + dt.timedelta(hours=2) if done else None,
                outcome="follow_up_booked" if st is AlertStatus.RESOLVED else None,
                created_at=created,
                updated_at=created,
            )
        )
    session.add_all(alerts)
    await session.flush()
    bump("risk_alerts", len(alerts))

    # -- notifications ---------------------------------------------------------------------------
    notifs = []
    for ap in appts:
        if ap.status in (AppointmentStatus.CONFIRMED, AppointmentStatus.REQUESTED):
            notifs.append(
                m.Notification(
                    institution_id=iid,
                    user_id=ap.student_id,
                    type=NotificationType.APPOINTMENT_REMINDER,
                    priority=NotificationPriority.HIGH,
                    channel=NotificationChannel.IN_APP,
                    title="You have an upcoming appointment",
                    payload={"appointment_id": str(ap.id)},
                    sent_at=ap.starts_at - dt.timedelta(hours=24)
                    if ap.starts_at - dt.timedelta(hours=24) <= now
                    else None,
                )
            )
    for alert in alerts:
        if alert.assigned_to and alert.status is AlertStatus.OPEN:
            notifs.append(
                m.Notification(
                    institution_id=iid,
                    user_id=alert.assigned_to,
                    type=NotificationType.RISK_ALERT,
                    priority=NotificationPriority.CRITICAL,
                    channel=NotificationChannel.IN_APP,
                    title="A student may need support. Open the queue.",
                    payload={"alert_id": str(alert.id), "severity": alert.severity.value},
                    sent_at=now,
                )
            )
    for rec in recs[:40]:
        notifs.append(
            m.Notification(
                institution_id=iid,
                user_id=rec.student_id,
                type=NotificationType.RECOMMENDATION,
                priority=NotificationPriority.LOW,
                channel=NotificationChannel.IN_APP,
                title="New idea for you",
                payload={"recommendation_id": str(rec.id)},
                created_at=now - dt.timedelta(hours=2),
                updated_at=now - dt.timedelta(hours=2),
                read_at=now if rng.random() < 0.4 else None,
            )
        )
    session.add_all(notifs)
    await session.flush()
    bump("notifications", len(notifs))

    # -- audit trail (a realistic slice of access events) ------------------------------------------
    n_audit = 0
    for ap in appts[:25]:
        if ap.status is AppointmentStatus.COMPLETED:
            await append_audit_event(
                session,
                institution_id=iid,
                action="therapy_note.read",
                outcome=AuditOutcome.ALLOWED,
                actor_id=ap.therapist_id,
                actor_role=UserRole.THERAPIST,
                resource_type="therapy_session",
                resource_id=ap.id,
                subject_student_id=ap.student_id,
                request_id=f"seed-{n_audit}",
                occurred_at=ap.ends_at + dt.timedelta(hours=1),
            )
            n_audit += 1
    for teacher in teacher_users[:2]:
        victim = students[0]
        await append_audit_event(
            session,
            institution_id=iid,
            action="therapy_note.read",
            outcome=AuditOutcome.DENIED,
            actor_id=teacher.id,
            actor_role=UserRole.TEACHER,
            resource_type="therapy_session",
            subject_student_id=victim.user_id,
            reason="role_not_permitted",
            request_id=f"seed-{n_audit}",
            occurred_at=now - dt.timedelta(hours=n_audit),
        )
        n_audit += 1
    bump("audit_logs", n_audit)

    await session.commit()
    return SeedResult(institution_id=iid, password=password, counts=counts)


def _consent(
    iid: uuid.UUID, uid: uuid.UUID, scope: ConsentScope, now: dt.datetime, rng: random.Random
) -> m.Consent:
    return m.Consent(
        institution_id=iid,
        user_id=uid,
        scope=scope,
        policy_version=POLICY_VERSION,
        granted_at=now - dt.timedelta(days=rng.randint(1, 90)),
    )
