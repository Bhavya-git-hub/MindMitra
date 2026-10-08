"""org schema: tenants, structure, role profiles and care-team relationships."""

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import (
    Base,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_col,
    fk_uuid,
)
from app.infrastructure.db.enums import AdminLevel, CareRole, EnrollmentStatus


class Institution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "institutions"
    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]*$'", name="slug_format"),
        {"schema": "org"},
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    region: Mapped[str] = mapped_column(String(40), nullable=False, server_default="ap-south-1")
    email_domains: Mapped[list[str]] = mapped_column(
        ARRAY(String(255)), nullable=False, server_default=text("'{}'")
    )
    # True for institutions populated by the seed system. Production code refuses to seed.
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class Department(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("institution_id", "code", name="uq_departments_institution_code"),
        UniqueConstraint("id", "institution_id", name="uq_departments_id_institution"),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        {"schema": "org"},
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)


class Course(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("department_id", "code", "term", name="uq_courses_department_code_term"),
        CheckConstraint("credits BETWEEN 0 AND 30", name="credits_range"),
        Index("ix_courses_department_term", "department_id", "term"),
        {"schema": "org"},
    )

    department_id: Mapped[uuid.UUID] = fk_uuid("org.departments.id", ondelete="RESTRICT")
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    term: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "2026-autumn"
    credits: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("3"))


def _dept_fk(table: str) -> ForeignKeyConstraint:
    """The department must belong to the same institution as the profile."""
    return ForeignKeyConstraint(
        ["department_id", "institution_id"],
        ["org.departments.id", "org.departments.institution_id"],
        ondelete="RESTRICT",
        name=f"fk_{table}_department_institution",
    )


def _profile_fk(role: str) -> tuple[ForeignKeyConstraint, CheckConstraint]:
    """A profile row may only reference a user whose role matches the profile type."""
    return (
        ForeignKeyConstraint(
            ["user_id", "role", "institution_id"],
            ["iam.users.id", "iam.users.role", "iam.users.institution_id"],
            ondelete="CASCADE",
            name=f"fk_{role}s_user_role",
        ),
        CheckConstraint(f"role = '{role}'", name="role_matches"),
    )


class Student(TimestampMixin, Base):
    __tablename__ = "students"
    __table_args__ = (
        *_profile_fk("student"),
        _dept_fk("students"),
        UniqueConstraint("institution_id", "student_number", name="uq_students_institution_number"),
        CheckConstraint("enrollment_year BETWEEN 1990 AND 2100", name="enrollment_year_range"),
        CheckConstraint("year_of_study BETWEEN 1 AND 8", name="year_of_study_range"),
        Index("ix_students_department_id", "department_id"),
        {"schema": "org"},
    )

    user_id: Mapped[uuid.UUID] = fk_uuid("iam.users.id", ondelete="CASCADE", primary_key=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default="student")
    institution_id: Mapped[uuid.UUID] = fk_uuid("org.institutions.id", ondelete="RESTRICT")
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    student_number: Mapped[str] = mapped_column(String(40), nullable=False)
    enrollment_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    year_of_study: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pronouns: Mapped[str | None] = mapped_column(String(40), nullable=True)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, server_default="en")


class Teacher(TimestampMixin, Base):
    __tablename__ = "teachers"
    __table_args__ = (
        *_profile_fk("teacher"),
        _dept_fk("teachers"),
        UniqueConstraint(
            "institution_id", "employee_number", name="uq_teachers_institution_number"
        ),
        Index("ix_teachers_department_id", "department_id"),
        {"schema": "org"},
    )

    user_id: Mapped[uuid.UUID] = fk_uuid("iam.users.id", ondelete="CASCADE", primary_key=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default="teacher")
    institution_id: Mapped[uuid.UUID] = fk_uuid("org.institutions.id", ondelete="RESTRICT")
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    employee_number: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Therapist(TimestampMixin, Base):
    __tablename__ = "therapists"
    __table_args__ = (
        *_profile_fk("therapist"),
        UniqueConstraint(
            "institution_id", "licence_number", name="uq_therapists_institution_licence"
        ),
        CheckConstraint("max_caseload BETWEEN 1 AND 500", name="max_caseload_range"),
        {"schema": "org"},
    )

    user_id: Mapped[uuid.UUID] = fk_uuid("iam.users.id", ondelete="CASCADE", primary_key=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default="therapist")
    institution_id: Mapped[uuid.UUID] = fk_uuid("org.institutions.id", ondelete="RESTRICT")
    licence_number: Mapped[str] = mapped_column(String(60), nullable=False)
    specialties: Mapped[list[str]] = mapped_column(
        ARRAY(String(80)), nullable=False, server_default=text("'{}'")
    )
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, server_default=text("'{}'")
    )
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepting_new_students: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    max_caseload: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("40")
    )


class Administrator(TimestampMixin, Base):
    __tablename__ = "administrators"
    __table_args__ = (
        *_profile_fk("administrator"),
        Index("ix_administrators_institution_id", "institution_id"),
        {"schema": "org"},
    )

    user_id: Mapped[uuid.UUID] = fk_uuid("iam.users.id", ondelete="CASCADE", primary_key=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default="administrator")
    institution_id: Mapped[uuid.UUID] = fk_uuid("org.institutions.id", ondelete="RESTRICT")
    admin_level: Mapped[AdminLevel] = mapped_column(
        enum_col(AdminLevel, "admin_level"),
        nullable=False,
        server_default=AdminLevel.INSTITUTION_ADMIN.value,
    )


class CourseEnrollment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "course_enrollments"
    __table_args__ = (
        UniqueConstraint("course_id", "student_id", name="uq_course_enrollments_course_student"),
        Index("ix_course_enrollments_student_id", "student_id"),
        {"schema": "org"},
    )

    course_id: Mapped[uuid.UUID] = fk_uuid("org.courses.id", ondelete="CASCADE")
    student_id: Mapped[uuid.UUID] = fk_uuid("org.students.user_id", ondelete="CASCADE")
    status: Mapped[EnrollmentStatus] = mapped_column(
        enum_col(EnrollmentStatus, "enrollment_status"),
        nullable=False,
        server_default=EnrollmentStatus.ENROLLED.value,
    )


class CourseTeacher(TimestampMixin, Base):
    __tablename__ = "course_teachers"
    __table_args__ = (Index("ix_course_teachers_teacher_id", "teacher_id"), {"schema": "org"})

    course_id: Mapped[uuid.UUID] = fk_uuid("org.courses.id", ondelete="CASCADE", primary_key=True)
    teacher_id: Mapped[uuid.UUID] = fk_uuid(
        "org.teachers.user_id", ondelete="CASCADE", primary_key=True
    )


class CareTeamMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Therapist-student relationship. The backbone of relationship-based authorization."""

    __tablename__ = "care_team_members"
    __table_args__ = (
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="period_valid"),
        # At most one *active* primary therapist per student.
        Index(
            "uq_care_team_active_primary",
            "student_id",
            unique=True,
            postgresql_where=text("role = 'primary' AND ends_at IS NULL"),
        ),
        # A therapist is assigned to a student at most once at a time.
        Index(
            "uq_care_team_active_pair",
            "student_id",
            "therapist_id",
            unique=True,
            postgresql_where=text("ends_at IS NULL"),
        ),
        Index(
            "ix_care_team_therapist_active",
            "therapist_id",
            postgresql_where=text("ends_at IS NULL"),
        ),
        {"schema": "org"},
    )

    student_id: Mapped[uuid.UUID] = fk_uuid("org.students.user_id", ondelete="CASCADE")
    therapist_id: Mapped[uuid.UUID] = fk_uuid("org.therapists.user_id", ondelete="RESTRICT")
    role: Mapped[CareRole] = mapped_column(
        enum_col(CareRole, "care_role"), nullable=False, server_default=CareRole.PRIMARY.value
    )
    starts_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ends_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
