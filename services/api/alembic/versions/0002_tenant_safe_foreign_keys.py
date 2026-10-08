"""tenant-safe composite foreign keys, constraint fixes, index fixes, updated_at trigger

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08 19:00:00

Review fixes (no new features):

* Every tenant-scoped child row can now only reference a parent in its *own* institution:
  ``(child_id, institution_id)`` composite foreign keys replace the single-column ones.
  Four join tables gained an ``institution_id`` column (backfilled from their parent).
* ``risk_alerts``: an ``escalated`` alert no longer needs an acknowledgement (the old check
  made automatic escalation impossible); ``assigned_to`` is RESTRICT, not SET NULL, which
  would have tried to null the tenant column.
* ``sleep_entries``: duration must agree with bedtime/wake time.
* Profile tables (students, teachers, therapists, administrators) had both a plain
  ``user_id -> users`` FK and the stronger composite ``(user_id, role, institution_id)`` FK;
  the redundant plain one is dropped.
* Foreign keys that were only backed by *partial* indexes now have a full index.
* Redundant single-column ``institution_id`` indexes dropped where a composite index leads
  with the same column.
* ``public.set_updated_at()`` trigger: ``updated_at`` is maintained by the database, not only
  by the ORM, so raw SQL and other writers cannot leave it stale.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = ("iam", "org", "wellness", "therapy", "comm", "ai", "safety", "consent", "notify")

# (schema, table, column, target "schema.table", target column, old fk name, new fk name,
#  old ondelete, new ondelete)
_S = ("org.students", "user_id")
_T = ("org.therapists", "user_id")
_U = ("iam.users", "id")
_TENANT_FKS: list[tuple[str, str, str, str, str, str, str, str, str]] = [
    ("ai", "ai_conversations", "student_id", *_S, "fk_ai_conversations_student_id_students", "fk_ai_conversations_student_id_institution_id_students", "CASCADE", "CASCADE"),
    ("ai", "recommendations", "student_id", *_S, "fk_recommendations_student_id_students", "fk_recommendations_student_id_institution_id_students", "CASCADE", "CASCADE"),
    ("comm", "messages", "student_id", *_S, "fk_messages_student_id_students", "fk_messages_student_id_institution_id_students", "RESTRICT", "RESTRICT"),
    ("comm", "messages", "therapist_id", *_T, "fk_messages_therapist_id_therapists", "fk_messages_therapist_id_institution_id_therapists", "RESTRICT", "RESTRICT"),
    ("consent", "consents", "user_id", *_U, "fk_consents_user_id_users", "fk_consents_user_id_institution_id_users", "CASCADE", "CASCADE"),
    ("notify", "notifications", "user_id", *_U, "fk_notifications_user_id_users", "fk_notifications_user_id_institution_id_users", "CASCADE", "CASCADE"),
    ("org", "care_team_members", "student_id", *_S, "fk_care_team_members_student_id_students", "fk_care_team_members_student_id_institution_id_students", "CASCADE", "CASCADE"),
    ("org", "care_team_members", "therapist_id", *_T, "fk_care_team_members_therapist_id_therapists", "fk_care_team_members_therapist_id_institution_id_therapists", "RESTRICT", "RESTRICT"),
    ("org", "course_enrollments", "student_id", *_S, "fk_course_enrollments_student_id_students", "fk_course_enrollments_student_id_institution_id_students", "CASCADE", "CASCADE"),
    ("org", "course_enrollments", "course_id", "org.courses", "id", "fk_course_enrollments_course_id_courses", "fk_course_enrollments_course_id_institution_id_courses", "CASCADE", "CASCADE"),
    ("org", "course_teachers", "teacher_id", "org.teachers", "user_id", "fk_course_teachers_teacher_id_teachers", "fk_course_teachers_teacher_id_institution_id_teachers", "CASCADE", "CASCADE"),
    ("org", "course_teachers", "course_id", "org.courses", "id", "fk_course_teachers_course_id_courses", "fk_course_teachers_course_id_institution_id_courses", "CASCADE", "CASCADE"),
    ("org", "courses", "department_id", "org.departments", "id", "fk_courses_department_id_departments", "fk_courses_department_institution", "RESTRICT", "RESTRICT"),
    ("safety", "risk_alerts", "student_id", *_S, "fk_risk_alerts_student_id_students", "fk_risk_alerts_student_id_institution_id_students", "RESTRICT", "RESTRICT"),
    ("safety", "risk_alerts", "assigned_to", *_T, "fk_risk_alerts_assigned_to_therapists", "fk_risk_alerts_assigned_to_institution_id_therapists", "SET NULL", "RESTRICT"),
    ("therapy", "appointments", "student_id", *_S, "fk_appointments_student_id_students", "fk_appointments_student_id_institution_id_students", "RESTRICT", "RESTRICT"),
    ("therapy", "appointments", "therapist_id", *_T, "fk_appointments_therapist_id_therapists", "fk_appointments_therapist_id_institution_id_therapists", "RESTRICT", "RESTRICT"),
    ("therapy", "therapist_availability", "therapist_id", *_T, "fk_therapist_availability_therapist_id_therapists", "fk_therapist_availability_therapist_id_institution_id_therapists", "RESTRICT", "RESTRICT"),
    ("wellness", "journal_entries", "student_id", *_S, "fk_journal_entries_student_id_students", "fk_journal_entries_student_id_institution_id_students", "CASCADE", "CASCADE"),
    ("wellness", "journal_shares", "entry_id", "wellness.journal_entries", "id", "fk_journal_shares_entry_id_journal_entries", "fk_journal_shares_entry_id_institution_id_journal_entries", "CASCADE", "CASCADE"),
    ("wellness", "journal_shares", "therapist_id", *_T, "fk_journal_shares_therapist_id_therapists", "fk_journal_shares_therapist_id_institution_id_therapists", "CASCADE", "CASCADE"),
    ("wellness", "mood_entries", "student_id", *_S, "fk_mood_entries_student_id_students", "fk_mood_entries_student_id_institution_id_students", "CASCADE", "CASCADE"),
    ("wellness", "sleep_entries", "student_id", *_S, "fk_sleep_entries_student_id_students", "fk_sleep_entries_student_id_institution_id_students", "CASCADE", "CASCADE"),
    ("wellness", "stress_assessments", "student_id", *_S, "fk_stress_assessments_student_id_students", "fk_stress_assessments_student_id_institution_id_students", "CASCADE", "CASCADE"),
    ("wellness", "wellness_assessments", "student_id", *_S, "fk_wellness_assessments_student_id_students", "fk_wellness_assessments_student_id_institution_id_students", "CASCADE", "CASCADE"),
    ("wellness", "wellness_goals", "student_id", *_S, "fk_wellness_goals_student_id_students", "fk_wellness_goals_student_id_institution_id_students", "CASCADE", "CASCADE"),
]  # fmt: skip

# Join tables that gain institution_id: (schema, table, backfill SQL).
_NEW_TENANT_COLUMNS: list[tuple[str, str, str]] = [
    (
        "org",
        "care_team_members",
        "UPDATE org.care_team_members t SET institution_id = p.institution_id "
        "FROM org.students p WHERE p.user_id = t.student_id",
    ),
    (
        "org",
        "course_enrollments",
        "UPDATE org.course_enrollments t SET institution_id = p.institution_id "
        "FROM org.courses p WHERE p.id = t.course_id",
    ),
    (
        "org",
        "course_teachers",
        "UPDATE org.course_teachers t SET institution_id = p.institution_id "
        "FROM org.courses p WHERE p.id = t.course_id",
    ),
    (
        "wellness",
        "journal_shares",
        "UPDATE wellness.journal_shares t SET institution_id = p.institution_id "
        "FROM wellness.journal_entries p WHERE p.id = t.entry_id",
    ),
]

# (schema, table, constraint name, columns): composite FK targets.
_NEW_UNIQUES: list[tuple[str, str, str, list[str]]] = [
    ("iam", "users", "uq_users_id_institution", ["id", "institution_id"]),
    ("org", "courses", "uq_courses_id_institution", ["id", "institution_id"]),
    ("org", "students", "uq_students_user_institution", ["user_id", "institution_id"]),
    ("org", "teachers", "uq_teachers_user_institution", ["user_id", "institution_id"]),
    ("org", "therapists", "uq_therapists_user_institution", ["user_id", "institution_id"]),
    ("wellness", "journal_entries", "uq_journal_entries_id_institution", ["id", "institution_id"]),
    (
        "therapy",
        "appointments",
        "uq_appointments_id_parties_tenant",
        ["id", "student_id", "therapist_id", "institution_id"],
    ),
    (
        "therapy",
        "therapy_sessions",
        "uq_therapy_sessions_id_therapist_tenant",
        ["id", "therapist_id", "institution_id"],
    ),
]

_OLD_UNIQUES: list[tuple[str, str, str, list[str]]] = [
    ("therapy", "appointments", "uq_appointments_id_parties", ["id", "student_id", "therapist_id"]),
    ("therapy", "therapy_sessions", "uq_therapy_sessions_id_therapist", ["id", "therapist_id"]),
]

_PROFILE_TABLES = ("students", "teachers", "therapists", "administrators")

_SESSION_FK = "fk_therapy_sessions_appointment_parties"
_NOTE_FK = "fk_therapy_notes_session_author"


def _drop_fk(schema: str, table: str, name: str) -> None:
    op.drop_constraint(op.f(name), table, schema=schema, type_="foreignkey")


def _create_fk(
    schema: str,
    table: str,
    name: str,
    cols: list[str],
    target: str,
    target_cols: list[str],
    ondelete: str,
) -> None:
    target_schema, target_table = target.split(".")
    op.create_foreign_key(
        op.f(name),
        table,
        target_table,
        cols,
        target_cols,
        source_schema=schema,
        referent_schema=target_schema,
        ondelete=ondelete,
    )


def _tables_with_updated_at() -> list[tuple[str, str]]:
    rows = op.get_bind().execute(
        sa.text(
            "SELECT table_schema, table_name FROM information_schema.columns "
            "WHERE column_name = 'updated_at' AND table_schema = ANY(:schemas) "
            "ORDER BY 1, 2"
        ),
        {"schemas": list(SCHEMAS)},
    )
    return [(r[0], r[1]) for r in rows]


def upgrade() -> None:
    # 1. institution_id on join tables: add nullable, backfill from the parent, then NOT NULL.
    for schema, table, backfill in _NEW_TENANT_COLUMNS:
        op.add_column(
            table, sa.Column("institution_id", sa.UUID(), nullable=True), schema=schema
        )
        op.execute(backfill)
        op.alter_column(table, "institution_id", nullable=False, schema=schema)
        op.create_foreign_key(
            op.f(f"fk_{table}_institution_id_institutions"),
            table,
            "institutions",
            ["institution_id"],
            ["id"],
            source_schema=schema,
            referent_schema="org",
            ondelete="RESTRICT",
        )
        op.create_index(op.f(f"ix_{table}_institution_id"), table, ["institution_id"], schema=schema)

    # 2. Drop single-column foreign keys and the unique constraints they depend on.
    _drop_fk("therapy", "therapy_notes", _NOTE_FK)
    _drop_fk("therapy", "therapy_sessions", _SESSION_FK)
    for schema, table, col, _tt, _tc, old_fk, _new_fk, _od, _nd in _TENANT_FKS:
        _drop_fk(schema, table, old_fk)
    for schema, table, name, _cols in _OLD_UNIQUES:
        op.drop_constraint(name, table, schema=schema, type_="unique")

    for table in _PROFILE_TABLES:
        _drop_fk("org", table, f"fk_{table}_user_id_users")

    # 3. New unique constraints (targets of the composite foreign keys).
    for schema, table, name, cols in _NEW_UNIQUES:
        op.create_unique_constraint(name, table, cols, schema=schema)

    # 4. Composite foreign keys.
    for schema, table, col, target, tcol, _old_fk, new_fk, _od, new_od in _TENANT_FKS:
        _create_fk(schema, table, new_fk, [col, "institution_id"], target, [tcol, "institution_id"], new_od)
    _create_fk(
        "therapy",
        "therapy_sessions",
        _SESSION_FK,
        ["appointment_id", "student_id", "therapist_id", "institution_id"],
        "therapy.appointments",
        ["id", "student_id", "therapist_id", "institution_id"],
        "RESTRICT",
    )
    _create_fk(
        "therapy",
        "therapy_notes",
        _NOTE_FK,
        ["session_id", "author_id", "institution_id"],
        "therapy.therapy_sessions",
        ["id", "therapist_id", "institution_id"],
        "RESTRICT",
    )

    # 5. Indexes: full indexes for FKs previously backed only by partial ones; drop redundant.
    op.drop_index("ix_care_team_therapist_active", table_name="care_team_members", schema="org")
    op.create_index("ix_care_team_members_student_id", "care_team_members", ["student_id"], schema="org")
    op.create_index("ix_care_team_members_therapist_id", "care_team_members", ["therapist_id"], schema="org")
    op.create_index("ix_messages_therapist_id", "messages", ["therapist_id"], schema="comm")
    op.create_index(
        "ix_appointments_availability_id",
        "appointments",
        ["availability_id"],
        schema="therapy",
        postgresql_where=sa.text("availability_id IS NOT NULL"),
    )
    op.drop_index("ix_users_institution_id", table_name="users", schema="iam")
    op.drop_index("ix_departments_institution_id", table_name="departments", schema="org")
    op.drop_index("ix_audit_logs_institution_id", table_name="audit_logs", schema="audit")

    # 6. Check constraints.
    op.drop_constraint(
        op.f("ck_risk_alerts_acknowledged_before_progress"), "risk_alerts", schema="safety", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_risk_alerts_acknowledged_before_progress"),
        "risk_alerts",
        "status IN ('open','escalated','dismissed') OR acknowledged_at IS NOT NULL",
        schema="safety",
    )
    op.create_check_constraint(
        op.f("ck_sleep_entries_duration_matches_times"),
        "sleep_entries",
        "abs(duration_minutes - extract(epoch FROM (wake_time - bedtime)) / 60) <= 1",
        schema="wellness",
    )

    # 7. updated_at maintained by the database.
    op.execute(
        """
        CREATE FUNCTION public.set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at := clock_timestamp();
            RETURN NEW;
        END;
        $$
        """
    )
    for schema, table in _tables_with_updated_at():
        op.execute(
            f"CREATE TRIGGER {table}_set_updated_at BEFORE UPDATE ON {schema}.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
        )


def downgrade() -> None:
    for schema, table in _tables_with_updated_at():
        op.execute(f"DROP TRIGGER IF EXISTS {table}_set_updated_at ON {schema}.{table}")
    op.execute("DROP FUNCTION IF EXISTS public.set_updated_at()")

    op.drop_constraint(
        op.f("ck_sleep_entries_duration_matches_times"), "sleep_entries", schema="wellness", type_="check"
    )
    op.drop_constraint(
        op.f("ck_risk_alerts_acknowledged_before_progress"), "risk_alerts", schema="safety", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_risk_alerts_acknowledged_before_progress"),
        "risk_alerts",
        "status = 'open' OR status = 'dismissed' OR acknowledged_at IS NOT NULL",
        schema="safety",
    )

    op.create_index("ix_audit_logs_institution_id", "audit_logs", ["institution_id"], schema="audit")
    op.create_index("ix_departments_institution_id", "departments", ["institution_id"], schema="org")
    op.create_index("ix_users_institution_id", "users", ["institution_id"], schema="iam")
    op.drop_index("ix_appointments_availability_id", table_name="appointments", schema="therapy")
    op.drop_index("ix_messages_therapist_id", table_name="messages", schema="comm")
    op.drop_index("ix_care_team_members_therapist_id", table_name="care_team_members", schema="org")
    op.drop_index("ix_care_team_members_student_id", table_name="care_team_members", schema="org")
    op.create_index(
        "ix_care_team_therapist_active",
        "care_team_members",
        ["therapist_id"],
        schema="org",
        postgresql_where=sa.text("ends_at IS NULL"),
    )

    _drop_fk("therapy", "therapy_notes", _NOTE_FK)
    _drop_fk("therapy", "therapy_sessions", _SESSION_FK)
    for schema, table, _col, _tt, _tc, _old_fk, new_fk, _od, _nd in _TENANT_FKS:
        _drop_fk(schema, table, new_fk)
    for schema, table, name, _cols in _NEW_UNIQUES:
        op.drop_constraint(name, table, schema=schema, type_="unique")
    for schema, table, name, cols in _OLD_UNIQUES:
        op.create_unique_constraint(name, table, cols, schema=schema)

    for schema, table, col, target, tcol, old_fk, _new_fk, old_od, _nd in _TENANT_FKS:
        _create_fk(schema, table, old_fk, [col], target, [tcol], old_od)
    _create_fk(
        "therapy",
        "therapy_sessions",
        _SESSION_FK,
        ["appointment_id", "student_id", "therapist_id"],
        "therapy.appointments",
        ["id", "student_id", "therapist_id"],
        "RESTRICT",
    )
    _create_fk(
        "therapy",
        "therapy_notes",
        _NOTE_FK,
        ["session_id", "author_id"],
        "therapy.therapy_sessions",
        ["id", "therapist_id"],
        "RESTRICT",
    )

    for table in _PROFILE_TABLES:
        _create_fk("org", table, f"fk_{table}_user_id_users", ["user_id"], "iam.users", ["id"], "CASCADE")
    for schema, table, _backfill in _NEW_TENANT_COLUMNS:
        op.drop_column(table, "institution_id", schema=schema)  # drops its FK and index
