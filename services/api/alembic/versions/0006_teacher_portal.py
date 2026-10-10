"""teacher portal

Referrals a teacher raises for a student they teach (``safety.referrals``) and requests a
student makes to one of their own teachers (``safety.teacher_support_requests``). Both are tied
to a real teaching or enrolment link by composite foreign keys, which is why ``org.course_teachers``
and ``org.course_enrollments`` gain a unique constraint that includes ``institution_id``.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-10 09:30:17.157880
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The new tables' foreign keys point at these, so they come first.
    op.create_unique_constraint('uq_course_enrollments_link_tenant', 'course_enrollments', ['course_id', 'student_id', 'institution_id'], schema='org')
    op.create_unique_constraint('uq_course_teachers_link_tenant', 'course_teachers', ['course_id', 'teacher_id', 'institution_id'], schema='org')
    op.create_table('referrals',
    sa.Column('teacher_id', sa.UUID(), nullable=False),
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('category', sa.Enum('academic_distress', 'behaviour_change', 'wellbeing_concern', 'safety_concern', name='referral_category', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('urgency', sa.Enum('routine', 'soon', 'urgent', name='referral_urgency', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('note', sa.LargeBinary(), nullable=True),
    sa.Column('status', sa.Enum('received', 'in_progress', 'closed', name='referral_status', native_enum=False, create_constraint=True, length=32), server_default='received', nullable=False),
    sa.Column('claimed_by', sa.UUID(), nullable=True),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('outcome', sa.Enum('contacted_student', 'student_declined', 'already_supported', 'referred_elsewhere', 'no_action_needed', name='referral_outcome', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'closed') = (closed_at IS NOT NULL)", name=op.f('ck_referrals_closed_at_matches_status')),
    sa.CheckConstraint("(status = 'closed') = (outcome IS NOT NULL)", name=op.f('ck_referrals_outcome_when_closed')),
    sa.CheckConstraint("(status = 'received') = (claimed_by IS NULL)", name=op.f('ck_referrals_claimed_unless_received')),
    sa.ForeignKeyConstraint(['claimed_by', 'institution_id'], ['org.therapists.user_id', 'org.therapists.institution_id'], name=op.f('fk_referrals_claimed_by_institution_id_therapists'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['course_id', 'student_id', 'institution_id'], ['org.course_enrollments.course_id', 'org.course_enrollments.student_id', 'org.course_enrollments.institution_id'], name='fk_referrals_course_student_tenant', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['course_id', 'teacher_id', 'institution_id'], ['org.course_teachers.course_id', 'org.course_teachers.teacher_id', 'org.course_teachers.institution_id'], name='fk_referrals_course_teacher_tenant', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_referrals_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id', 'institution_id'], ['org.students.user_id', 'org.students.institution_id'], name=op.f('fk_referrals_student_id_institution_id_students'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['teacher_id', 'institution_id'], ['org.teachers.user_id', 'org.teachers.institution_id'], name=op.f('fk_referrals_teacher_id_institution_id_teachers'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_referrals')),
    schema='safety'
    )
    op.create_index('ix_referrals_claimed_by', 'referrals', ['claimed_by'], unique=False, schema='safety', postgresql_where=sa.text('claimed_by IS NOT NULL'))
    op.create_index(op.f('ix_referrals_institution_id'), 'referrals', ['institution_id'], unique=False, schema='safety')
    op.create_index('ix_referrals_open_queue', 'referrals', ['institution_id', 'urgency', 'created_at'], unique=False, schema='safety', postgresql_where=sa.text("status <> 'closed'"))
    op.create_index('ix_referrals_course_id', 'referrals', ['course_id'], unique=False, schema='safety')
    op.create_index('ix_referrals_teacher_id', 'referrals', ['teacher_id'], unique=False, schema='safety')
    op.create_index('ix_referrals_student_id', 'referrals', ['student_id'], unique=False, schema='safety')
    op.create_index('uq_referrals_live_teacher_student', 'referrals', ['teacher_id', 'student_id'], unique=True, schema='safety', postgresql_where=sa.text("status <> 'closed'"))
    op.create_table('teacher_support_requests',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('teacher_id', sa.UUID(), nullable=False),
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('topic', sa.Enum('academic_support', 'workload', 'extension', 'wellbeing_chat', 'other', name='teacher_support_topic', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('message', sa.LargeBinary(), nullable=True),
    sa.Column('status', sa.Enum('open', 'acknowledged', 'closed', 'withdrawn', name='teacher_support_status', native_enum=False, create_constraint=True, length=32), server_default='open', nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status IN ('closed','withdrawn')) = (closed_at IS NOT NULL)", name=op.f('ck_teacher_support_requests_closed_at_matches_status')),
    sa.CheckConstraint("status <> 'acknowledged' OR acknowledged_at IS NOT NULL", name=op.f('ck_teacher_support_requests_acknowledged_at_when_acknowledged')),
    sa.ForeignKeyConstraint(['course_id', 'student_id', 'institution_id'], ['org.course_enrollments.course_id', 'org.course_enrollments.student_id', 'org.course_enrollments.institution_id'], name='fk_teacher_support_course_student_tenant', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['course_id', 'teacher_id', 'institution_id'], ['org.course_teachers.course_id', 'org.course_teachers.teacher_id', 'org.course_teachers.institution_id'], name='fk_teacher_support_course_teacher_tenant', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_teacher_support_requests_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id', 'institution_id'], ['org.students.user_id', 'org.students.institution_id'], name=op.f('fk_teacher_support_requests_student_id_institution_id_students'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['teacher_id', 'institution_id'], ['org.teachers.user_id', 'org.teachers.institution_id'], name=op.f('fk_teacher_support_requests_teacher_id_institution_id_teachers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_teacher_support_requests')),
    schema='safety'
    )
    op.create_index(op.f('ix_teacher_support_requests_institution_id'), 'teacher_support_requests', ['institution_id'], unique=False, schema='safety')
    op.create_index('ix_teacher_support_course_id', 'teacher_support_requests', ['course_id'], unique=False, schema='safety')
    op.create_index('ix_teacher_support_student_created', 'teacher_support_requests', ['student_id', sa.literal_column('created_at DESC')], unique=False, schema='safety')
    op.create_index('ix_teacher_support_teacher_status', 'teacher_support_requests', ['teacher_id', 'status', sa.literal_column('created_at DESC')], unique=False, schema='safety')
    op.create_index('uq_teacher_support_live', 'teacher_support_requests', ['student_id', 'teacher_id', 'course_id'], unique=True, schema='safety', postgresql_where=sa.text("status IN ('open','acknowledged')"))

    for table in ("referrals", "teacher_support_requests"):  # updated_at is kept by the database (0002)
        op.execute(
            f"CREATE TRIGGER {table}_set_updated_at BEFORE UPDATE ON safety.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
        )


def downgrade() -> None:
    op.drop_index('uq_teacher_support_live', table_name='teacher_support_requests', schema='safety', postgresql_where=sa.text("status IN ('open','acknowledged')"))
    op.drop_index('ix_teacher_support_teacher_status', table_name='teacher_support_requests', schema='safety')
    op.drop_index('ix_teacher_support_course_id', table_name='teacher_support_requests', schema='safety')
    op.drop_index('ix_teacher_support_student_created', table_name='teacher_support_requests', schema='safety')
    op.drop_index(op.f('ix_teacher_support_requests_institution_id'), table_name='teacher_support_requests', schema='safety')
    op.drop_table('teacher_support_requests', schema='safety')
    op.drop_index('uq_referrals_live_teacher_student', table_name='referrals', schema='safety', postgresql_where=sa.text("status <> 'closed'"))
    op.drop_index('ix_referrals_teacher_id', table_name='referrals', schema='safety')
    op.drop_index('ix_referrals_course_id', table_name='referrals', schema='safety')
    op.drop_index('ix_referrals_student_id', table_name='referrals', schema='safety')
    op.drop_index('ix_referrals_open_queue', table_name='referrals', schema='safety', postgresql_where=sa.text("status <> 'closed'"))
    op.drop_index(op.f('ix_referrals_institution_id'), table_name='referrals', schema='safety')
    op.drop_index('ix_referrals_claimed_by', table_name='referrals', schema='safety', postgresql_where=sa.text('claimed_by IS NOT NULL'))
    op.drop_table('referrals', schema='safety')
    op.drop_constraint('uq_course_teachers_link_tenant', 'course_teachers', schema='org', type_='unique')
    op.drop_constraint('uq_course_enrollments_link_tenant', 'course_enrollments', schema='org', type_='unique')
