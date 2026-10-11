"""Prepare a disposable database for the web end-to-end tests.

Run from services/api (`uv run python ../../scripts/e2e/prepare_backend.py <out.json>`) with
DATABASE_URL pointing at an EMPTY throwaway database and SEED_USER_PASSWORD set. It migrates the
schema, loads the synthetic seed, and writes one active user per role (email only) to <out.json>.
For the therapist portal it also writes a verified therapist who has a student on their care team
(with a confirmed appointment that is due to start, so a session can be run, and three open
times weeks ahead for the booking, moving and live-update tests), and a therapist who is still
waiting for verification. For the teacher portal it makes sure the signed-in student is
enrolled in a class the signed-in teacher teaches, and clears any live referral or request between
them, so the referral and "ask a teacher" flows can run from a clean slate.
The password is never written to disk: the e2e run passes it through the environment.

Refuses to run unless APP_ENV is development or test.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROLES = ("student", "therapist", "teacher", "administrator")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    if os.environ.get("APP_ENV") not in {"development", "test"}:
        print("Refusing to run: APP_ENV must be development or test", file=sys.stderr)
        return 2
    if not os.environ.get("SEED_USER_PASSWORD"):
        print("SEED_USER_PASSWORD must be set", file=sys.stderr)
        return 2

    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    subprocess.run([sys.executable, "-m", "app.infrastructure.db.seed"], check=True)

    users = asyncio.run(_pick_users())
    users.update(asyncio.run(_prepare_therapist_portal()))
    users.update(asyncio.run(_prepare_teacher_portal(users["teacher"], users["student"])))
    users["crisis_student"] = asyncio.run(_pick_crisis_student(users["student"], users["care_student"]))
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(users, indent=2) + "\n")
    print(f"wrote {out}: {', '.join(f'{r}={u}' for r, u in users.items())}")
    return 0


async def _pick_users() -> dict[str, str]:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "select distinct on (role) role, email from iam.users "
                        "where status = 'active' and deleted_at is null order by role, email"
                    )
                )
            ).all()
    finally:
        await engine.dispose()
    users = {role: email for role, email in rows}
    missing = [r for r in ROLES if r not in users]
    if missing:
        raise SystemExit(f"seed produced no active user for: {missing}")
    return {r: users[r] for r in ROLES}


async def _pick_crisis_student(student_email: str, care_student_email: str) -> str:
    """A student no other test signs in as. A crisis check-in pauses that student's suggestions
    for 72 hours, so it must not be the shared student-portal or care-team student."""
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as conn:
            email = (
                await conn.execute(
                    text(
                        "select u.email from iam.users u join org.students s on s.user_id = u.id "
                        "where u.role = 'student' and u.status = 'active' and u.deleted_at is null "
                        "  and u.email not in (:a, :b) order by u.email limit 1"
                    ),
                    {"a": student_email, "b": care_student_email},
                )
            ).scalar_one_or_none()
    finally:
        await engine.dispose()
    if email is None:
        raise SystemExit("seed has no spare student for the crisis test")
    return str(email)


async def _prepare_therapist_portal() -> dict[str, str]:
    """A verified therapist with a care-team student and a session that can start now, plus an
    unverified therapist. Synthetic data only; nothing here is a secret."""
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            pair = (
                await conn.execute(
                    text(
                        "select t.user_id, tu.email, t.institution_id, c.student_id, su.full_name, "
                        "su.email "
                        "from org.therapists t "
                        "join iam.users tu on tu.id = t.user_id "
                        "join org.care_team_members c on c.therapist_id = t.user_id "
                        "  and c.ends_at is null "
                        "join iam.users su on su.id = c.student_id "
                        "where t.verification_status = 'verified' and tu.status = 'active' "
                        "  and tu.deleted_at is null and su.status = 'active' "
                        # Not the student the student-portal tests use (it has a booking cap).
                        "  and su.id <> (select id from iam.users where role = 'student' "
                        "    and status = 'active' and deleted_at is null "
                        "    order by email limit 1) "
                        "order by tu.email, su.email limit 1"
                    )
                )
            ).first()
            if pair is None:
                raise SystemExit("seed has no verified therapist with a care-team student")
            therapist_id, therapist_email, institution_id, student_id, student_name, student_email = (
                pair
            )
            # The communication tests book with this pair: clear the student's other future
            # bookings (so the booking cap cannot get in the way) and give the therapist three
            # open times at an hour nothing else uses.
            await conn.execute(
                text(
                    "update therapy.appointments set status = 'cancelled', cancelled_at = now() "
                    "where student_id = :s and status in ('requested', 'confirmed') "
                    "and starts_at > now() + interval '2 hours'"
                ),
                {"s": student_id},
            )
            await conn.execute(
                text(
                    "insert into therapy.therapist_availability "
                    "(id, institution_id, therapist_id, starts_at, ends_at, mode) "
                    "select gen_random_uuid(), :i, :t, d, d + interval '50 minutes', 'video' "
                    "from (select date_trunc('day', now()) + make_interval(days => n, hours => 3) d "
                    "      from generate_series(20, 22) n) days "
                    "on conflict do nothing"
                ),
                {"i": institution_id, "t": therapist_id},
            )
            # Free the next hour for this pair, then add a confirmed appointment about to begin.
            await conn.execute(
                text(
                    "update therapy.appointments set status = 'cancelled', cancelled_at = now() "
                    "where status in ('requested', 'confirmed') "
                    "and (therapist_id = :t or student_id = :s) "
                    "and tstzrange(starts_at, ends_at) && "
                    "tstzrange(now() - interval '1 hour', now() + interval '2 hours')"
                ),
                {"t": therapist_id, "s": student_id},
            )
            await conn.execute(
                text(
                    "insert into therapy.appointments "
                    "(id, institution_id, student_id, therapist_id, starts_at, ends_at, mode, status) "
                    "values (gen_random_uuid(), :i, :s, :t, now() + interval '2 minutes', "
                    "now() + interval '52 minutes', 'video', 'confirmed')"
                ),
                {"i": institution_id, "s": student_id, "t": therapist_id},
            )
            pending = (
                await conn.execute(
                    text(
                        "select u.email from org.therapists t join iam.users u on u.id = t.user_id "
                        "where t.verification_status = 'pending' and u.status = 'active' "
                        "order by u.email limit 1"
                    )
                )
            ).scalar_one_or_none()
            if pending is None:
                raise SystemExit("seed has no therapist waiting for verification")
    finally:
        await engine.dispose()
    return {
        "therapist": therapist_email,
        "therapist_id": str(therapist_id),
        "care_student": student_email,
        "care_student_id": str(student_id),
        "care_student_name": student_name,
        "pending_therapist": pending,
    }


async def _prepare_teacher_portal(teacher_email: str, student_email: str) -> dict[str, str]:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "select t.user_id, t.institution_id, c.id, c.code, c.title, "
                        "  s.user_id, coalesce(s.preferred_name, su.full_name), tu.full_name "
                        "from iam.users tu join org.teachers t on t.user_id = tu.id "
                        "join org.course_teachers ct on ct.teacher_id = t.user_id "
                        "join org.courses c on c.id = ct.course_id, "
                        "  iam.users su join org.students s on s.user_id = su.id "
                        "where tu.email = :te and su.email = :se "
                        "order by c.code limit 1"
                    ),
                    {"te": teacher_email, "se": student_email},
                )
            ).first()
            if row is None:
                raise SystemExit("seed has no class for the e2e teacher")
            teacher_id, institution_id, course_id, code, title, student_id, display, teacher_name = row
            await conn.execute(
                text(
                    "insert into org.course_enrollments (id, institution_id, course_id, student_id, status) "
                    "values (gen_random_uuid(), :i, :c, :s, 'enrolled') "
                    "on conflict (course_id, student_id) do update set status = 'enrolled'"
                ),
                {"i": institution_id, "c": course_id, "s": student_id},
            )
            await conn.execute(
                text(
                    "delete from safety.referrals where teacher_id = :t and student_id = :s"
                ),
                {"t": teacher_id, "s": student_id},
            )
            await conn.execute(
                text(
                    "delete from safety.teacher_support_requests "
                    "where teacher_id = :t and student_id = :s"
                ),
                {"t": teacher_id, "s": student_id},
            )
    finally:
        await engine.dispose()
    return {
        "teacher_course_code": code,
        "teacher_course_title": title,
        "teacher_student_name": display,
        "teacher_full_name": teacher_name,
    }


if __name__ == "__main__":
    raise SystemExit(main())
