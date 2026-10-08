"""initial schema: all bounded-context schemas, tables, constraints, indexes, audit triggers

Revision ID: 0001
Revises: 
Create Date: 2026-10-08 18:08:51.341569
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMAS = (
    "iam", "org", "wellness", "therapy", "comm", "ai", "safety", "consent", "notify", "audit",
)


def upgrade() -> None:
    # --- extensions and schemas -------------------------------------------------------
    # btree_gist is required for the no-overlap exclusion constraints on scheduling tables.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    op.create_table('institutions',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('region', sa.String(length=40), server_default='ap-south-1', nullable=False),
    sa.Column('email_domains', postgresql.ARRAY(sa.String(length=255)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(name) <> ''", name=op.f('ck_institutions_name_not_blank')),
    sa.CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]*$'", name=op.f('ck_institutions_slug_format')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_institutions')),
    sa.UniqueConstraint('slug', name=op.f('uq_institutions_slug')),
    schema='org'
    )
    op.create_table('audit_logs',
    sa.Column('seq', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('actor_role', sa.Enum('student', 'therapist', 'teacher', 'administrator', name='audit_actor_role', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('action', sa.String(length=80), nullable=False),
    sa.Column('resource_type', sa.String(length=60), nullable=True),
    sa.Column('resource_id', sa.UUID(), nullable=True),
    sa.Column('subject_student_id', sa.UUID(), nullable=True),
    sa.Column('outcome', sa.Enum('allowed', 'denied', 'error', name='audit_outcome', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('reason', sa.String(length=200), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('ip_hash', sa.String(length=64), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('prev_hash', sa.String(length=64), nullable=True),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("btrim(action) <> ''", name=op.f('ck_audit_logs_action_not_blank')),
    sa.CheckConstraint("hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_audit_logs_hash_is_sha256_hex')),
    sa.CheckConstraint("jsonb_typeof(details) = 'object'", name=op.f('ck_audit_logs_details_is_object')),
    sa.CheckConstraint("prev_hash IS NULL OR prev_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_audit_logs_prev_hash_is_sha256_hex')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_audit_logs_institution_id_institutions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs')),
    schema='audit'
    )
    op.create_index('ix_audit_logs_actor_occurred', 'audit_logs', ['actor_id', sa.literal_column('occurred_at DESC')], unique=False, schema='audit')
    op.create_index(op.f('ix_audit_logs_institution_id'), 'audit_logs', ['institution_id'], unique=False, schema='audit')
    op.create_index('ix_audit_logs_institution_occurred', 'audit_logs', ['institution_id', sa.literal_column('occurred_at DESC')], unique=False, schema='audit')
    op.create_index('ix_audit_logs_institution_seq', 'audit_logs', ['institution_id', 'seq'], unique=True, schema='audit')
    op.create_index('ix_audit_logs_resource', 'audit_logs', ['resource_type', 'resource_id'], unique=False, schema='audit')
    op.create_index('ix_audit_logs_subject_occurred', 'audit_logs', ['subject_student_id', sa.literal_column('occurred_at DESC')], unique=False, schema='audit')
    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('role', sa.Enum('student', 'therapist', 'teacher', 'administrator', name='user_role', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('invited', 'active', 'suspended', 'deactivated', name='user_status', native_enum=False, create_constraint=True, length=32), server_default='invited', nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("btrim(full_name) <> ''", name=op.f('ck_users_full_name_not_blank')),
    sa.CheckConstraint("position('@' in email) > 1", name=op.f('ck_users_email_has_at')),
    sa.CheckConstraint('email = lower(email)', name=op.f('ck_users_email_lowercase')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_users_institution_id_institutions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('id', 'role', 'institution_id', name='uq_users_id_role_institution'),
    sa.UniqueConstraint('institution_id', 'email', name='uq_users_institution_email'),
    schema='iam'
    )
    op.create_index(op.f('ix_users_institution_id'), 'users', ['institution_id'], unique=False, schema='iam')
    op.create_index('ix_users_institution_role_status', 'users', ['institution_id', 'role', 'status'], unique=False, schema='iam')
    op.create_table('departments',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(name) <> ''", name=op.f('ck_departments_name_not_blank')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_departments_institution_id_institutions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_departments')),
    sa.UniqueConstraint('id', 'institution_id', name='uq_departments_id_institution'),
    sa.UniqueConstraint('institution_id', 'code', name='uq_departments_institution_code'),
    schema='org'
    )
    op.create_index(op.f('ix_departments_institution_id'), 'departments', ['institution_id'], unique=False, schema='org')
    op.create_table('consents',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('scope', sa.Enum('terms_and_privacy', 'share_mood_with_care_team', 'share_assessments_with_care_team', 'share_ai_signals_with_care_team', 'journal_safety_scanning', 'ai_companion_history', 'anonymous_aggregate_research', 'email_notifications', 'sms_notifications', name='consent_scope', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('policy_version', sa.String(length=40), nullable=False),
    sa.Column('source', sa.String(length=40), server_default='web', nullable=False),
    sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(policy_version) <> ''", name=op.f('ck_consents_policy_version_not_blank')),
    sa.CheckConstraint('revoked_at IS NULL OR revoked_at >= granted_at', name=op.f('ck_consents_revoked_after_granted')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_consents_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['iam.users.id'], name=op.f('fk_consents_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_consents')),
    schema='consent'
    )
    op.create_index(op.f('ix_consents_institution_id'), 'consents', ['institution_id'], unique=False, schema='consent')
    op.create_index('ix_consents_user_scope_granted', 'consents', ['user_id', 'scope', sa.literal_column('granted_at DESC')], unique=False, schema='consent')
    op.create_index('uq_consents_active_user_scope', 'consents', ['user_id', 'scope'], unique=True, schema='consent', postgresql_where=sa.text('revoked_at IS NULL'))
    op.create_table('credentials',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('password_changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('failed_attempts', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("password_hash LIKE '$argon2id$%'", name=op.f('ck_credentials_password_hash_is_argon2id')),
    sa.CheckConstraint('failed_attempts >= 0', name=op.f('ck_credentials_failed_attempts_non_negative')),
    sa.ForeignKeyConstraint(['user_id'], ['iam.users.id'], name=op.f('fk_credentials_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_credentials')),
    schema='iam'
    )
    op.create_table('notifications',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('type', sa.Enum('appointment_reminder', 'appointment_update', 'new_message', 'risk_alert', 'recommendation', 'goal_reminder', 'system', name='notification_type', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('priority', sa.Enum('low', 'normal', 'high', 'critical', name='notification_priority', native_enum=False, create_constraint=True, length=32), server_default='normal', nullable=False),
    sa.Column('channel', sa.Enum('in_app', 'email', 'sms', 'push', name='notification_channel', native_enum=False, create_constraint=True, length=32), server_default='in_app', nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('attempts', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name=op.f('ck_notifications_payload_is_object')),
    sa.CheckConstraint('attempts >= 0', name=op.f('ck_notifications_attempts_non_negative')),
    sa.CheckConstraint('read_at IS NULL OR read_at >= created_at', name=op.f('ck_notifications_read_after_created')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_notifications_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['iam.users.id'], name=op.f('fk_notifications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications')),
    schema='notify'
    )
    op.create_index(op.f('ix_notifications_institution_id'), 'notifications', ['institution_id'], unique=False, schema='notify')
    op.create_index('ix_notifications_user_created', 'notifications', ['user_id', sa.literal_column('created_at DESC')], unique=False, schema='notify')
    op.create_index('ix_notifications_user_unread', 'notifications', ['user_id', sa.literal_column('created_at DESC')], unique=False, schema='notify', postgresql_where=sa.text('read_at IS NULL'))
    op.create_table('administrators',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.String(length=32), server_default='administrator', nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('admin_level', sa.Enum('institution_admin', 'platform_admin', name='admin_level', native_enum=False, create_constraint=True, length=32), server_default='institution_admin', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role = 'administrator'", name=op.f('ck_administrators_role_matches')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_administrators_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id', 'role', 'institution_id'], ['iam.users.id', 'iam.users.role', 'iam.users.institution_id'], name='fk_administrators_user_role', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['iam.users.id'], name=op.f('fk_administrators_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_administrators')),
    schema='org'
    )
    op.create_table('courses',
    sa.Column('department_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('term', sa.String(length=20), nullable=False),
    sa.Column('credits', sa.SmallInteger(), server_default=sa.text('3'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('credits BETWEEN 0 AND 30', name=op.f('ck_courses_credits_range')),
    sa.ForeignKeyConstraint(['department_id'], ['org.departments.id'], name=op.f('fk_courses_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_courses_institution_id_institutions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_courses')),
    sa.UniqueConstraint('department_id', 'code', 'term', name='uq_courses_department_code_term'),
    schema='org'
    )
    op.create_index('ix_courses_department_term', 'courses', ['department_id', 'term'], unique=False, schema='org')
    op.create_index(op.f('ix_courses_institution_id'), 'courses', ['institution_id'], unique=False, schema='org')
    op.create_table('students',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.String(length=32), server_default='student', nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('department_id', sa.UUID(), nullable=False),
    sa.Column('student_number', sa.String(length=40), nullable=False),
    sa.Column('enrollment_year', sa.SmallInteger(), nullable=False),
    sa.Column('year_of_study', sa.SmallInteger(), nullable=False),
    sa.Column('preferred_name', sa.String(length=100), nullable=True),
    sa.Column('pronouns', sa.String(length=40), nullable=True),
    sa.Column('locale', sa.String(length=10), server_default='en', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role = 'student'", name=op.f('ck_students_role_matches')),
    sa.CheckConstraint('enrollment_year BETWEEN 1990 AND 2100', name=op.f('ck_students_enrollment_year_range')),
    sa.CheckConstraint('year_of_study BETWEEN 1 AND 8', name=op.f('ck_students_year_of_study_range')),
    sa.ForeignKeyConstraint(['department_id', 'institution_id'], ['org.departments.id', 'org.departments.institution_id'], name='fk_students_department_institution', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_students_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id', 'role', 'institution_id'], ['iam.users.id', 'iam.users.role', 'iam.users.institution_id'], name='fk_students_user_role', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['iam.users.id'], name=op.f('fk_students_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_students')),
    sa.UniqueConstraint('institution_id', 'student_number', name='uq_students_institution_number'),
    schema='org'
    )
    op.create_index('ix_students_department_id', 'students', ['department_id'], unique=False, schema='org')
    op.create_table('teachers',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.String(length=32), server_default='teacher', nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('department_id', sa.UUID(), nullable=False),
    sa.Column('employee_number', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role = 'teacher'", name=op.f('ck_teachers_role_matches')),
    sa.ForeignKeyConstraint(['department_id', 'institution_id'], ['org.departments.id', 'org.departments.institution_id'], name='fk_teachers_department_institution', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_teachers_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id', 'role', 'institution_id'], ['iam.users.id', 'iam.users.role', 'iam.users.institution_id'], name='fk_teachers_user_role', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['iam.users.id'], name=op.f('fk_teachers_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_teachers')),
    sa.UniqueConstraint('institution_id', 'employee_number', name='uq_teachers_institution_number'),
    schema='org'
    )
    op.create_index('ix_teachers_department_id', 'teachers', ['department_id'], unique=False, schema='org')
    op.create_table('therapists',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.String(length=32), server_default='therapist', nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('licence_number', sa.String(length=60), nullable=False),
    sa.Column('specialties', postgresql.ARRAY(sa.String(length=80)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('languages', postgresql.ARRAY(sa.String(length=40)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('bio', sa.Text(), nullable=True),
    sa.Column('accepting_new_students', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('max_caseload', sa.SmallInteger(), server_default=sa.text('40'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role = 'therapist'", name=op.f('ck_therapists_role_matches')),
    sa.CheckConstraint('max_caseload BETWEEN 1 AND 500', name=op.f('ck_therapists_max_caseload_range')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_therapists_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id', 'role', 'institution_id'], ['iam.users.id', 'iam.users.role', 'iam.users.institution_id'], name='fk_therapists_user_role', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['iam.users.id'], name=op.f('fk_therapists_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_therapists')),
    sa.UniqueConstraint('institution_id', 'licence_number', name='uq_therapists_institution_licence'),
    schema='org'
    )
    op.create_table('resources',
    sa.Column('institution_id', sa.UUID(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('summary', sa.String(length=500), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('url', sa.String(length=500), nullable=True),
    sa.Column('resource_type', sa.Enum('article', 'video', 'exercise', 'audio', 'service', name='resource_type', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('tags', postgresql.ARRAY(sa.String(length=40)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('language', sa.String(length=10), server_default='en', nullable=False),
    sa.Column('duration_minutes', sa.SmallInteger(), nullable=True),
    sa.Column('is_published', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('reviewed_by', sa.UUID(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(title) <> ''", name=op.f('ck_resources_title_not_blank')),
    sa.CheckConstraint('NOT is_published OR reviewed_at IS NOT NULL', name=op.f('ck_resources_published_requires_review')),
    sa.CheckConstraint('duration_minutes IS NULL OR duration_minutes > 0', name=op.f('ck_resources_duration_positive')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_resources_institution_id_institutions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewed_by'], ['iam.users.id'], name=op.f('fk_resources_reviewed_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resources')),
    schema='wellness'
    )
    op.create_index(op.f('ix_resources_institution_id'), 'resources', ['institution_id'], unique=False, schema='wellness')
    op.create_index('ix_resources_published_type', 'resources', ['is_published', 'resource_type'], unique=False, schema='wellness')
    op.create_index('ix_resources_tags', 'resources', ['tags'], unique=False, schema='wellness', postgresql_using='gin')
    op.create_table('ai_conversations',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.Enum('active', 'ended', 'crisis_handoff', name='ai_conversation_status', native_enum=False, create_constraint=True, length=32), server_default='active', nullable=False),
    sa.Column('model_version', sa.String(length=80), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('ended_at IS NULL OR ended_at >= started_at', name=op.f('ck_ai_conversations_ended_after_started')),
    sa.CheckConstraint('expires_at IS NULL OR expires_at > started_at', name=op.f('ck_ai_conversations_expires_after_start')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_ai_conversations_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id'], ['org.students.user_id'], name=op.f('fk_ai_conversations_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_conversations')),
    schema='ai'
    )
    op.create_index('ix_ai_conversations_expires_at', 'ai_conversations', ['expires_at'], unique=False, schema='ai', postgresql_where=sa.text('expires_at IS NOT NULL'))
    op.create_index(op.f('ix_ai_conversations_institution_id'), 'ai_conversations', ['institution_id'], unique=False, schema='ai')
    op.create_index('ix_ai_conversations_student_started', 'ai_conversations', ['student_id', sa.literal_column('started_at DESC')], unique=False, schema='ai')
    op.create_table('recommendations',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('resource_id', sa.UUID(), nullable=True),
    sa.Column('source', sa.Enum('rule', 'model', 'therapist', name='recommendation_source', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('pending', 'viewed', 'dismissed', 'completed', name='recommendation_status', native_enum=False, create_constraint=True, length=32), server_default='pending', nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=True),
    sa.Column('model_version', sa.String(length=80), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(title) <> ''", name=op.f('ck_recommendations_title_not_blank')),
    sa.CheckConstraint("source <> 'model' OR model_version IS NOT NULL", name=op.f('ck_recommendations_model_source_has_version')),
    sa.CheckConstraint('confidence IS NULL OR confidence BETWEEN 0 AND 1', name=op.f('ck_recommendations_confidence_range')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_recommendations_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['resource_id'], ['wellness.resources.id'], name=op.f('fk_recommendations_resource_id_resources'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['student_id'], ['org.students.user_id'], name=op.f('fk_recommendations_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recommendations')),
    schema='ai'
    )
    op.create_index(op.f('ix_recommendations_institution_id'), 'recommendations', ['institution_id'], unique=False, schema='ai')
    op.create_index('ix_recommendations_resource_id', 'recommendations', ['resource_id'], unique=False, schema='ai')
    op.create_index('ix_recommendations_student_status', 'recommendations', ['student_id', 'status'], unique=False, schema='ai')
    op.create_table('messages',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('therapist_id', sa.UUID(), nullable=False),
    sa.Column('sender_id', sa.UUID(), nullable=False),
    sa.Column('body', sa.LargeBinary(), nullable=False),
    sa.Column('client_msg_id', sa.UUID(), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('crisis_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('read_at IS NULL OR read_at >= created_at', name=op.f('ck_messages_read_after_created')),
    sa.CheckConstraint('sender_id IN (student_id, therapist_id)', name=op.f('ck_messages_sender_is_participant')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_messages_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['sender_id'], ['iam.users.id'], name='fk_messages_sender_id_users', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id'], ['org.students.user_id'], name='fk_messages_student_id_students', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['therapist_id'], ['org.therapists.user_id'], name='fk_messages_therapist_id_therapists', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages')),
    sa.UniqueConstraint('sender_id', 'client_msg_id', name='uq_messages_sender_client_msg'),
    schema='comm'
    )
    op.create_index('ix_messages_conversation_created', 'messages', ['student_id', 'therapist_id', 'created_at'], unique=False, schema='comm')
    op.create_index(op.f('ix_messages_institution_id'), 'messages', ['institution_id'], unique=False, schema='comm')
    op.create_index('ix_messages_unread', 'messages', ['therapist_id', 'student_id'], unique=False, schema='comm', postgresql_where=sa.text('read_at IS NULL'))
    op.create_table('care_team_members',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('therapist_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.Enum('primary', 'secondary', name='care_role', native_enum=False, create_constraint=True, length=32), server_default='primary', nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('ends_at IS NULL OR ends_at > starts_at', name=op.f('ck_care_team_members_period_valid')),
    sa.ForeignKeyConstraint(['student_id'], ['org.students.user_id'], name=op.f('fk_care_team_members_student_id_students'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['therapist_id'], ['org.therapists.user_id'], name=op.f('fk_care_team_members_therapist_id_therapists'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_care_team_members')),
    schema='org'
    )
    op.create_index('ix_care_team_therapist_active', 'care_team_members', ['therapist_id'], unique=False, schema='org', postgresql_where=sa.text('ends_at IS NULL'))
    op.create_index('uq_care_team_active_pair', 'care_team_members', ['student_id', 'therapist_id'], unique=True, schema='org', postgresql_where=sa.text('ends_at IS NULL'))
    op.create_index('uq_care_team_active_primary', 'care_team_members', ['student_id'], unique=True, schema='org', postgresql_where=sa.text("role = 'primary' AND ends_at IS NULL"))
    op.create_table('course_enrollments',
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.Enum('enrolled', 'dropped', 'completed', name='enrollment_status', native_enum=False, create_constraint=True, length=32), server_default='enrolled', nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['org.courses.id'], name=op.f('fk_course_enrollments_course_id_courses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['student_id'], ['org.students.user_id'], name=op.f('fk_course_enrollments_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_course_enrollments')),
    sa.UniqueConstraint('course_id', 'student_id', name='uq_course_enrollments_course_student'),
    schema='org'
    )
    op.create_index('ix_course_enrollments_student_id', 'course_enrollments', ['student_id'], unique=False, schema='org')
    op.create_table('course_teachers',
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('teacher_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['org.courses.id'], name=op.f('fk_course_teachers_course_id_courses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['teacher_id'], ['org.teachers.user_id'], name=op.f('fk_course_teachers_teacher_id_teachers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('course_id', 'teacher_id', name=op.f('pk_course_teachers')),
    schema='org'
    )
    op.create_table('risk_alerts',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('assigned_to', sa.UUID(), nullable=True),
    sa.Column('source', sa.Enum('mood_entry', 'journal', 'ai_chat', 'message', 'help_button', 'faculty_referral', 'model', 'therapist', name='alert_source', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('source_type', sa.String(length=60), nullable=True),
    sa.Column('source_id', sa.UUID(), nullable=True),
    sa.Column('detector', sa.Enum('rules', 'classifier', 'human', name='alert_detector', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('category', sa.Enum('self_harm_language', 'suicidal_language', 'harm_to_others', 'unsafe_situation', 'acute_distress', 'sustained_low_wellbeing', 'engagement_drop', name='alert_category', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('severity', sa.Enum('low', 'moderate', 'high', 'imminent', name='alert_severity', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('open', 'acknowledged', 'escalated', 'in_progress', 'resolved', 'dismissed', name='alert_status', native_enum=False, create_constraint=True, length=32), server_default='open', nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=True),
    sa.Column('model_version', sa.String(length=80), nullable=True),
    sa.Column('requires_human', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('excerpt', sa.LargeBinary(), nullable=True),
    sa.Column('sla_ack_due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('outcome', sa.String(length=60), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status IN ('resolved','dismissed')) = (resolved_at IS NOT NULL)", name=op.f('ck_risk_alerts_resolved_at_matches_status')),
    sa.CheckConstraint("severity NOT IN ('high','imminent') OR sla_ack_due_at IS NOT NULL", name=op.f('ck_risk_alerts_high_severity_has_sla')),
    sa.CheckConstraint("status = 'open' OR status = 'dismissed' OR acknowledged_at IS NOT NULL", name=op.f('ck_risk_alerts_acknowledged_before_progress')),
    sa.CheckConstraint('(source_type IS NULL) = (source_id IS NULL)', name=op.f('ck_risk_alerts_source_ref_complete')),
    sa.CheckConstraint('confidence IS NULL OR confidence BETWEEN 0 AND 1', name=op.f('ck_risk_alerts_confidence_range')),
    sa.CheckConstraint('requires_human', name=op.f('ck_risk_alerts_always_requires_human')),
    sa.ForeignKeyConstraint(['assigned_to'], ['org.therapists.user_id'], name=op.f('fk_risk_alerts_assigned_to_therapists'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_risk_alerts_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id'], ['org.students.user_id'], name=op.f('fk_risk_alerts_student_id_students'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_risk_alerts')),
    schema='safety'
    )
    op.create_index('ix_risk_alerts_assigned_status', 'risk_alerts', ['assigned_to', 'status'], unique=False, schema='safety')
    op.create_index(op.f('ix_risk_alerts_institution_id'), 'risk_alerts', ['institution_id'], unique=False, schema='safety')
    op.create_index('ix_risk_alerts_open_sla', 'risk_alerts', ['institution_id', 'sla_ack_due_at'], unique=False, schema='safety', postgresql_where=sa.text("status IN ('open','escalated')"))
    op.create_index('ix_risk_alerts_student_created', 'risk_alerts', ['student_id', sa.literal_column('created_at DESC')], unique=False, schema='safety')
    op.create_table('therapist_availability',
    sa.Column('therapist_id', sa.UUID(), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('mode', sa.Enum('video', 'in_person', 'phone', name='availability_mode', native_enum=False, create_constraint=True, length=32), server_default='video', nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    postgresql.ExcludeConstraint((sa.column('therapist_id'), '='), (sa.text('tstzrange(starts_at, ends_at)'), '&&'), using='gist', name='ex_therapist_availability_no_overlap'),
    sa.CheckConstraint('ends_at > starts_at', name=op.f('ck_therapist_availability_slot_valid')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_therapist_availability_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['therapist_id'], ['org.therapists.user_id'], name=op.f('fk_therapist_availability_therapist_id_therapists'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_therapist_availability')),
    sa.UniqueConstraint('id', 'therapist_id', name='uq_therapist_availability_id_therapist'),
    schema='therapy'
    )
    op.create_index(op.f('ix_therapist_availability_institution_id'), 'therapist_availability', ['institution_id'], unique=False, schema='therapy')
    op.create_index('ix_therapist_availability_therapist_starts', 'therapist_availability', ['therapist_id', 'starts_at'], unique=False, schema='therapy')
    op.create_table('journal_entries',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.LargeBinary(), nullable=True),
    sa.Column('body', sa.LargeBinary(), nullable=False),
    sa.Column('mood_tag', sa.String(length=40), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_journal_entries_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id'], ['org.students.user_id'], name=op.f('fk_journal_entries_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_journal_entries')),
    schema='wellness'
    )
    op.create_index(op.f('ix_journal_entries_institution_id'), 'journal_entries', ['institution_id'], unique=False, schema='wellness')
    op.create_index('ix_journal_entries_student_created', 'journal_entries', ['student_id', sa.literal_column('created_at DESC')], unique=False, schema='wellness')
    op.create_table('mood_entries',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('mood_score', sa.SmallInteger(), nullable=False),
    sa.Column('energy_level', sa.SmallInteger(), nullable=True),
    sa.Column('emotions', postgresql.ARRAY(sa.String(length=40)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('note', sa.LargeBinary(), nullable=True),
    sa.Column('logged_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('energy_level IS NULL OR energy_level BETWEEN 1 AND 5', name=op.f('ck_mood_entries_energy_range')),
    sa.CheckConstraint('mood_score BETWEEN 1 AND 5', name=op.f('ck_mood_entries_mood_score_range')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_mood_entries_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id'], ['org.students.user_id'], name=op.f('fk_mood_entries_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mood_entries')),
    schema='wellness'
    )
    op.create_index(op.f('ix_mood_entries_institution_id'), 'mood_entries', ['institution_id'], unique=False, schema='wellness')
    op.create_index('ix_mood_entries_student_logged_at', 'mood_entries', ['student_id', sa.literal_column('logged_at DESC')], unique=False, schema='wellness')
    op.create_table('sleep_entries',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('sleep_date', sa.Date(), nullable=False),
    sa.Column('bedtime', sa.DateTime(timezone=True), nullable=False),
    sa.Column('wake_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('duration_minutes', sa.SmallInteger(), nullable=False),
    sa.Column('quality', sa.SmallInteger(), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('duration_minutes BETWEEN 0 AND 1440', name=op.f('ck_sleep_entries_duration_range')),
    sa.CheckConstraint('quality BETWEEN 1 AND 5', name=op.f('ck_sleep_entries_quality_range')),
    sa.CheckConstraint('wake_time > bedtime', name=op.f('ck_sleep_entries_wake_after_bedtime')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_sleep_entries_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id'], ['org.students.user_id'], name=op.f('fk_sleep_entries_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sleep_entries')),
    sa.UniqueConstraint('student_id', 'sleep_date', name='uq_sleep_entries_student_date'),
    schema='wellness'
    )
    op.create_index(op.f('ix_sleep_entries_institution_id'), 'sleep_entries', ['institution_id'], unique=False, schema='wellness')
    op.create_index('ix_sleep_entries_student_date', 'sleep_entries', ['student_id', sa.literal_column('sleep_date DESC')], unique=False, schema='wellness')
    op.create_table('stress_assessments',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('scale', sa.String(length=60), nullable=False),
    sa.Column('score', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('max_score', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('perceived_stress_level', sa.SmallInteger(), nullable=False),
    sa.Column('stressors', postgresql.ARRAY(sa.String(length=60)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('max_score > 0', name=op.f('ck_stress_assessments_max_score_positive')),
    sa.CheckConstraint('perceived_stress_level BETWEEN 1 AND 5', name=op.f('ck_stress_assessments_stress_level_range')),
    sa.CheckConstraint('score >= 0 AND score <= max_score', name=op.f('ck_stress_assessments_score_within_max')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_stress_assessments_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id'], ['org.students.user_id'], name=op.f('fk_stress_assessments_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stress_assessments')),
    schema='wellness'
    )
    op.create_index(op.f('ix_stress_assessments_institution_id'), 'stress_assessments', ['institution_id'], unique=False, schema='wellness')
    op.create_index('ix_stress_assessments_student_completed', 'stress_assessments', ['student_id', sa.literal_column('completed_at DESC')], unique=False, schema='wellness')
    op.create_table('wellness_assessments',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('instrument', sa.String(length=60), nullable=False),
    sa.Column('instrument_version', sa.String(length=20), server_default='1', nullable=False),
    sa.Column('score', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('max_score', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('responses', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('max_score > 0', name=op.f('ck_wellness_assessments_max_score_positive')),
    sa.CheckConstraint('score >= 0 AND score <= max_score', name=op.f('ck_wellness_assessments_score_within_max')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_wellness_assessments_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id'], ['org.students.user_id'], name=op.f('fk_wellness_assessments_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_wellness_assessments')),
    schema='wellness'
    )
    op.create_index(op.f('ix_wellness_assessments_institution_id'), 'wellness_assessments', ['institution_id'], unique=False, schema='wellness')
    op.create_index('ix_wellness_assessments_student_completed', 'wellness_assessments', ['student_id', sa.literal_column('completed_at DESC')], unique=False, schema='wellness')
    op.create_table('wellness_goals',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('category', sa.Enum('sleep', 'movement', 'mindfulness', 'social', 'academic_balance', 'nutrition', 'other', name='goal_category', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('active', 'completed', 'paused', 'abandoned', name='goal_status', native_enum=False, create_constraint=True, length=32), server_default='active', nullable=False),
    sa.Column('target_value', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('current_value', sa.Numeric(precision=10, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('unit', sa.String(length=30), nullable=True),
    sa.Column('start_date', sa.Date(), server_default=sa.text('CURRENT_DATE'), nullable=False),
    sa.Column('target_date', sa.Date(), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'completed') = (completed_at IS NOT NULL)", name=op.f('ck_wellness_goals_completed_at_matches_status')),
    sa.CheckConstraint("btrim(title) <> ''", name=op.f('ck_wellness_goals_title_not_blank')),
    sa.CheckConstraint('current_value >= 0', name=op.f('ck_wellness_goals_current_non_negative')),
    sa.CheckConstraint('target_date IS NULL OR target_date >= start_date', name=op.f('ck_wellness_goals_target_after_start')),
    sa.CheckConstraint('target_value IS NULL OR target_value > 0', name=op.f('ck_wellness_goals_target_positive')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_wellness_goals_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id'], ['org.students.user_id'], name=op.f('fk_wellness_goals_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_wellness_goals')),
    schema='wellness'
    )
    op.create_index(op.f('ix_wellness_goals_institution_id'), 'wellness_goals', ['institution_id'], unique=False, schema='wellness')
    op.create_index('ix_wellness_goals_student_status', 'wellness_goals', ['student_id', 'status'], unique=False, schema='wellness')
    op.create_table('ai_messages',
    sa.Column('conversation_id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('role', sa.Enum('user', 'assistant', name='ai_message_role', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('content', sa.LargeBinary(), nullable=False),
    sa.Column('crisis_flag', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('safety_flags', postgresql.ARRAY(sa.String(length=40)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('token_count', sa.Integer(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('seq >= 1', name=op.f('ck_ai_messages_seq_positive')),
    sa.CheckConstraint('token_count IS NULL OR token_count >= 0', name=op.f('ck_ai_messages_token_count_non_negative')),
    sa.ForeignKeyConstraint(['conversation_id'], ['ai.ai_conversations.id'], name=op.f('fk_ai_messages_conversation_id_ai_conversations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_messages')),
    sa.UniqueConstraint('conversation_id', 'seq', name='uq_ai_messages_conversation_seq'),
    schema='ai'
    )
    op.create_table('appointments',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('therapist_id', sa.UUID(), nullable=False),
    sa.Column('availability_id', sa.UUID(), nullable=True),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('mode', sa.Enum('video', 'in_person', 'phone', name='appointment_mode', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('requested', 'confirmed', 'completed', 'cancelled', 'no_show', name='appointment_status', native_enum=False, create_constraint=True, length=32), server_default='requested', nullable=False),
    sa.Column('reason', sa.LargeBinary(), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    postgresql.ExcludeConstraint((sa.column('student_id'), '='), (sa.text('tstzrange(starts_at, ends_at)'), '&&'), where=sa.text("status IN ('requested','confirmed')"), using='gist', name='ex_appointments_student_no_overlap'),
    postgresql.ExcludeConstraint((sa.column('therapist_id'), '='), (sa.text('tstzrange(starts_at, ends_at)'), '&&'), where=sa.text("status IN ('requested','confirmed')"), using='gist', name='ex_appointments_therapist_no_overlap'),
    sa.CheckConstraint("(status = 'cancelled') = (cancelled_at IS NOT NULL)", name=op.f('ck_appointments_cancelled_at_matches_status')),
    sa.CheckConstraint('ends_at > starts_at', name=op.f('ck_appointments_period_valid')),
    sa.CheckConstraint('student_id <> therapist_id', name=op.f('ck_appointments_distinct_parties')),
    sa.ForeignKeyConstraint(['availability_id', 'therapist_id'], ['therapy.therapist_availability.id', 'therapy.therapist_availability.therapist_id'], name='fk_appointments_availability_therapist', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cancelled_by'], ['iam.users.id'], name=op.f('fk_appointments_cancelled_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_appointments_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id'], ['org.students.user_id'], name=op.f('fk_appointments_student_id_students'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['therapist_id'], ['org.therapists.user_id'], name='fk_appointments_therapist_id_therapists', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_appointments')),
    sa.UniqueConstraint('id', 'student_id', 'therapist_id', name='uq_appointments_id_parties'),
    schema='therapy'
    )
    op.create_index(op.f('ix_appointments_institution_id'), 'appointments', ['institution_id'], unique=False, schema='therapy')
    op.create_index('ix_appointments_student_starts', 'appointments', ['student_id', sa.literal_column('starts_at DESC')], unique=False, schema='therapy')
    op.create_index('ix_appointments_therapist_starts', 'appointments', ['therapist_id', sa.literal_column('starts_at DESC')], unique=False, schema='therapy')
    op.create_index('uq_appointments_live_slot', 'appointments', ['availability_id'], unique=True, schema='therapy', postgresql_where=sa.text("status IN ('requested','confirmed') AND availability_id IS NOT NULL"))
    op.create_table('journal_shares',
    sa.Column('entry_id', sa.UUID(), nullable=False),
    sa.Column('therapist_id', sa.UUID(), nullable=False),
    sa.Column('shared_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('revoked_at IS NULL OR revoked_at >= shared_at', name=op.f('ck_journal_shares_revoked_after_shared')),
    sa.ForeignKeyConstraint(['entry_id'], ['wellness.journal_entries.id'], name=op.f('fk_journal_shares_entry_id_journal_entries'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['therapist_id'], ['org.therapists.user_id'], name=op.f('fk_journal_shares_therapist_id_therapists'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_journal_shares')),
    sa.UniqueConstraint('entry_id', 'therapist_id', name='uq_journal_shares_entry_therapist'),
    schema='wellness'
    )
    op.create_index('ix_journal_shares_therapist_id', 'journal_shares', ['therapist_id'], unique=False, schema='wellness')
    op.create_table('therapy_sessions',
    sa.Column('appointment_id', sa.UUID(), nullable=False),
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('therapist_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.Enum('scheduled', 'in_progress', 'completed', 'abandoned', name='therapy_session_status', native_enum=False, create_constraint=True, length=32), server_default='scheduled', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('video_meeting_ref', sa.String(length=120), nullable=True),
    sa.Column('duration_minutes', sa.SmallInteger(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'completed') = (ended_at IS NOT NULL)", name=op.f('ck_therapy_sessions_ended_at_matches_status')),
    sa.CheckConstraint('ended_at IS NULL OR ended_at >= started_at', name=op.f('ck_therapy_sessions_ended_after_started')),
    sa.ForeignKeyConstraint(['appointment_id', 'student_id', 'therapist_id'], ['therapy.appointments.id', 'therapy.appointments.student_id', 'therapy.appointments.therapist_id'], name='fk_therapy_sessions_appointment_parties', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_therapy_sessions_institution_id_institutions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_therapy_sessions')),
    sa.UniqueConstraint('appointment_id', name='uq_therapy_sessions_appointment_id'),
    sa.UniqueConstraint('id', 'therapist_id', name='uq_therapy_sessions_id_therapist'),
    schema='therapy'
    )
    op.create_index(op.f('ix_therapy_sessions_institution_id'), 'therapy_sessions', ['institution_id'], unique=False, schema='therapy')
    op.create_index('ix_therapy_sessions_student_id', 'therapy_sessions', ['student_id'], unique=False, schema='therapy')
    op.create_index('ix_therapy_sessions_therapist_started', 'therapy_sessions', ['therapist_id', sa.literal_column('started_at DESC')], unique=False, schema='therapy')
    op.create_table('therapy_notes',
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('author_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.SmallInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('body', sa.LargeBinary(), nullable=False),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('version >= 1', name=op.f('ck_therapy_notes_version_positive')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_therapy_notes_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id', 'author_id'], ['therapy.therapy_sessions.id', 'therapy.therapy_sessions.therapist_id'], name='fk_therapy_notes_session_author', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_therapy_notes')),
    sa.UniqueConstraint('session_id', 'version', name='uq_therapy_notes_session_version'),
    schema='therapy'
    )
    op.create_index('ix_therapy_notes_author_created', 'therapy_notes', ['author_id', sa.literal_column('created_at DESC')], unique=False, schema='therapy')
    op.create_index(op.f('ix_therapy_notes_institution_id'), 'therapy_notes', ['institution_id'], unique=False, schema='therapy')

    # --- foreign-key support indexes -----------------------------------------------------
    op.create_index("ix_course_teachers_teacher_id", "course_teachers", ["teacher_id"], schema="org")
    op.create_index("ix_administrators_institution_id", "administrators", ["institution_id"], schema="org")
    op.create_index(
        "ix_appointments_cancelled_by", "appointments", ["cancelled_by"], schema="therapy",
        postgresql_where=sa.text("cancelled_by IS NOT NULL"),
    )
    op.create_index(
        "ix_resources_reviewed_by", "resources", ["reviewed_by"], schema="wellness",
        postgresql_where=sa.text("reviewed_by IS NOT NULL"),
    )

    # --- audit immutability -----------------------------------------------------------
    op.execute(
        """
        CREATE FUNCTION audit.reject_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit.audit_logs is append-only (% not permitted)', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_logs_no_update_delete BEFORE UPDATE OR DELETE ON audit.audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION audit.reject_mutation()"
    )
    op.execute(
        "CREATE TRIGGER audit_logs_no_truncate BEFORE TRUNCATE ON audit.audit_logs "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit.reject_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_truncate ON audit.audit_logs")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update_delete ON audit.audit_logs")
    op.drop_index("ix_resources_reviewed_by", table_name="resources", schema="wellness")
    op.drop_index("ix_appointments_cancelled_by", table_name="appointments", schema="therapy")
    op.drop_index("ix_administrators_institution_id", table_name="administrators", schema="org")
    op.drop_index("ix_course_teachers_teacher_id", table_name="course_teachers", schema="org")
    op.drop_index(op.f('ix_therapy_notes_institution_id'), table_name='therapy_notes', schema='therapy')
    op.drop_index('ix_therapy_notes_author_created', table_name='therapy_notes', schema='therapy')
    op.drop_table('therapy_notes', schema='therapy')
    op.drop_index('ix_therapy_sessions_therapist_started', table_name='therapy_sessions', schema='therapy')
    op.drop_index('ix_therapy_sessions_student_id', table_name='therapy_sessions', schema='therapy')
    op.drop_index(op.f('ix_therapy_sessions_institution_id'), table_name='therapy_sessions', schema='therapy')
    op.drop_table('therapy_sessions', schema='therapy')
    op.drop_index('ix_journal_shares_therapist_id', table_name='journal_shares', schema='wellness')
    op.drop_table('journal_shares', schema='wellness')
    op.drop_index('uq_appointments_live_slot', table_name='appointments', schema='therapy', postgresql_where=sa.text("status IN ('requested','confirmed') AND availability_id IS NOT NULL"))
    op.drop_index('ix_appointments_therapist_starts', table_name='appointments', schema='therapy')
    op.drop_index('ix_appointments_student_starts', table_name='appointments', schema='therapy')
    op.drop_index(op.f('ix_appointments_institution_id'), table_name='appointments', schema='therapy')
    op.drop_table('appointments', schema='therapy')
    op.drop_table('ai_messages', schema='ai')
    op.drop_index('ix_wellness_goals_student_status', table_name='wellness_goals', schema='wellness')
    op.drop_index(op.f('ix_wellness_goals_institution_id'), table_name='wellness_goals', schema='wellness')
    op.drop_table('wellness_goals', schema='wellness')
    op.drop_index('ix_wellness_assessments_student_completed', table_name='wellness_assessments', schema='wellness')
    op.drop_index(op.f('ix_wellness_assessments_institution_id'), table_name='wellness_assessments', schema='wellness')
    op.drop_table('wellness_assessments', schema='wellness')
    op.drop_index('ix_stress_assessments_student_completed', table_name='stress_assessments', schema='wellness')
    op.drop_index(op.f('ix_stress_assessments_institution_id'), table_name='stress_assessments', schema='wellness')
    op.drop_table('stress_assessments', schema='wellness')
    op.drop_index('ix_sleep_entries_student_date', table_name='sleep_entries', schema='wellness')
    op.drop_index(op.f('ix_sleep_entries_institution_id'), table_name='sleep_entries', schema='wellness')
    op.drop_table('sleep_entries', schema='wellness')
    op.drop_index('ix_mood_entries_student_logged_at', table_name='mood_entries', schema='wellness')
    op.drop_index(op.f('ix_mood_entries_institution_id'), table_name='mood_entries', schema='wellness')
    op.drop_table('mood_entries', schema='wellness')
    op.drop_index('ix_journal_entries_student_created', table_name='journal_entries', schema='wellness')
    op.drop_index(op.f('ix_journal_entries_institution_id'), table_name='journal_entries', schema='wellness')
    op.drop_table('journal_entries', schema='wellness')
    op.drop_index('ix_therapist_availability_therapist_starts', table_name='therapist_availability', schema='therapy')
    op.drop_index(op.f('ix_therapist_availability_institution_id'), table_name='therapist_availability', schema='therapy')
    op.drop_table('therapist_availability', schema='therapy')
    op.drop_index('ix_risk_alerts_student_created', table_name='risk_alerts', schema='safety')
    op.drop_index('ix_risk_alerts_open_sla', table_name='risk_alerts', schema='safety', postgresql_where=sa.text("status IN ('open','escalated')"))
    op.drop_index(op.f('ix_risk_alerts_institution_id'), table_name='risk_alerts', schema='safety')
    op.drop_index('ix_risk_alerts_assigned_status', table_name='risk_alerts', schema='safety')
    op.drop_table('risk_alerts', schema='safety')
    op.drop_table('course_teachers', schema='org')
    op.drop_index('ix_course_enrollments_student_id', table_name='course_enrollments', schema='org')
    op.drop_table('course_enrollments', schema='org')
    op.drop_index('uq_care_team_active_primary', table_name='care_team_members', schema='org', postgresql_where=sa.text("role = 'primary' AND ends_at IS NULL"))
    op.drop_index('uq_care_team_active_pair', table_name='care_team_members', schema='org', postgresql_where=sa.text('ends_at IS NULL'))
    op.drop_index('ix_care_team_therapist_active', table_name='care_team_members', schema='org', postgresql_where=sa.text('ends_at IS NULL'))
    op.drop_table('care_team_members', schema='org')
    op.drop_index('ix_messages_unread', table_name='messages', schema='comm', postgresql_where=sa.text('read_at IS NULL'))
    op.drop_index(op.f('ix_messages_institution_id'), table_name='messages', schema='comm')
    op.drop_index('ix_messages_conversation_created', table_name='messages', schema='comm')
    op.drop_table('messages', schema='comm')
    op.drop_index('ix_recommendations_student_status', table_name='recommendations', schema='ai')
    op.drop_index('ix_recommendations_resource_id', table_name='recommendations', schema='ai')
    op.drop_index(op.f('ix_recommendations_institution_id'), table_name='recommendations', schema='ai')
    op.drop_table('recommendations', schema='ai')
    op.drop_index('ix_ai_conversations_student_started', table_name='ai_conversations', schema='ai')
    op.drop_index(op.f('ix_ai_conversations_institution_id'), table_name='ai_conversations', schema='ai')
    op.drop_index('ix_ai_conversations_expires_at', table_name='ai_conversations', schema='ai', postgresql_where=sa.text('expires_at IS NOT NULL'))
    op.drop_table('ai_conversations', schema='ai')
    op.drop_index('ix_resources_tags', table_name='resources', schema='wellness', postgresql_using='gin')
    op.drop_index('ix_resources_published_type', table_name='resources', schema='wellness')
    op.drop_index(op.f('ix_resources_institution_id'), table_name='resources', schema='wellness')
    op.drop_table('resources', schema='wellness')
    op.drop_table('therapists', schema='org')
    op.drop_index('ix_teachers_department_id', table_name='teachers', schema='org')
    op.drop_table('teachers', schema='org')
    op.drop_index('ix_students_department_id', table_name='students', schema='org')
    op.drop_table('students', schema='org')
    op.drop_index(op.f('ix_courses_institution_id'), table_name='courses', schema='org')
    op.drop_index('ix_courses_department_term', table_name='courses', schema='org')
    op.drop_table('courses', schema='org')
    op.drop_table('administrators', schema='org')
    op.drop_index('ix_notifications_user_unread', table_name='notifications', schema='notify', postgresql_where=sa.text('read_at IS NULL'))
    op.drop_index('ix_notifications_user_created', table_name='notifications', schema='notify')
    op.drop_index(op.f('ix_notifications_institution_id'), table_name='notifications', schema='notify')
    op.drop_table('notifications', schema='notify')
    op.drop_table('credentials', schema='iam')
    op.drop_index('uq_consents_active_user_scope', table_name='consents', schema='consent', postgresql_where=sa.text('revoked_at IS NULL'))
    op.drop_index('ix_consents_user_scope_granted', table_name='consents', schema='consent')
    op.drop_index(op.f('ix_consents_institution_id'), table_name='consents', schema='consent')
    op.drop_table('consents', schema='consent')
    op.drop_index(op.f('ix_departments_institution_id'), table_name='departments', schema='org')
    op.drop_table('departments', schema='org')
    op.drop_index('ix_users_institution_role_status', table_name='users', schema='iam')
    op.drop_index(op.f('ix_users_institution_id'), table_name='users', schema='iam')
    op.drop_table('users', schema='iam')
    op.drop_index('ix_audit_logs_subject_occurred', table_name='audit_logs', schema='audit')
    op.drop_index('ix_audit_logs_resource', table_name='audit_logs', schema='audit')
    op.drop_index('ix_audit_logs_institution_seq', table_name='audit_logs', schema='audit')
    op.drop_index('ix_audit_logs_institution_occurred', table_name='audit_logs', schema='audit')
    op.drop_index(op.f('ix_audit_logs_institution_id'), table_name='audit_logs', schema='audit')
    op.drop_index('ix_audit_logs_actor_occurred', table_name='audit_logs', schema='audit')
    op.drop_table('audit_logs', schema='audit')
    op.drop_table('institutions', schema='org')
    op.execute("DROP FUNCTION IF EXISTS audit.reject_mutation()")
    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema}")
    # btree_gist is left installed: other databases/objects on the server may depend on it.
