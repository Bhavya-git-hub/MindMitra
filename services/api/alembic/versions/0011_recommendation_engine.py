"""recommendation engine

What the recommendation engine knew when it made a suggestion (``recommendations``: idea, area,
relevance, format, tags, reasons, engine version), the student's "helpful" or "not helpful" on
each (``recommendation_feedback``), and their preferences (``recommendation_preferences``).
See ADR 0012.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-11 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = '0011'
down_revision: str | None = '0010'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('recommendations', sa.Column('intervention_key', sa.String(length=60), nullable=True), schema='ai')
    op.add_column('recommendations', sa.Column('problem_area', sa.String(length=30), nullable=True), schema='ai')
    op.add_column('recommendations', sa.Column('relevance', sa.Numeric(precision=4, scale=3), nullable=True), schema='ai')
    op.add_column('recommendations', sa.Column('resource_format', sa.String(length=32), nullable=True), schema='ai')
    op.add_column('recommendations', sa.Column('tags', postgresql.ARRAY(sa.String(length=40)), server_default=sa.text("'{}'"), nullable=False), schema='ai')
    op.add_column('recommendations', sa.Column('reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='ai')
    op.add_column('recommendations', sa.Column('engine_version', sa.String(length=80), nullable=True), schema='ai')
    op.create_check_constraint(
        op.f('ck_recommendations_relevance_range'), 'recommendations',
        'relevance IS NULL OR relevance BETWEEN 0 AND 1', schema='ai',
    )
    op.create_check_constraint(
        op.f('ck_recommendations_problem_area_known'), 'recommendations',
        "problem_area IS NULL OR problem_area IN ('academic_burnout', 'career_anxiety', "
        "'social_isolation', 'sleep_disruption', 'stress', 'mood', 'engagement')",
        schema='ai',
    )
    op.create_unique_constraint('uq_recommendations_link_tenant', 'recommendations', ['id', 'student_id', 'institution_id'], schema='ai')
    op.create_index('ix_recommendations_student_created', 'recommendations', ['student_id', 'created_at'], unique=False, schema='ai')

    op.create_table('recommendation_feedback',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('recommendation_id', sa.UUID(), nullable=False),
    sa.Column('rating', sa.Enum('helpful', 'not_helpful', name='feedback_rating', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('reason', sa.Enum('not_relevant', 'wrong_format', 'too_long', 'already_doing_this', 'not_now', name='feedback_reason', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("reason IS NULL OR rating = 'not_helpful'", name=op.f('ck_recommendation_feedback_reason_only_when_not_helpful')),
    sa.ForeignKeyConstraint(['recommendation_id', 'student_id', 'institution_id'], ['ai.recommendations.id', 'ai.recommendations.student_id', 'ai.recommendations.institution_id'], name=op.f('fk_recommendation_feedback_recommendation_id_recommendations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_recommendation_feedback_institution_id_institutions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recommendation_feedback')),
    sa.UniqueConstraint('recommendation_id', name='uq_recommendation_feedback_recommendation'),
    schema='ai'
    )
    op.create_index(op.f('ix_recommendation_feedback_institution_id'), 'recommendation_feedback', ['institution_id'], unique=False, schema='ai')
    op.create_index('ix_recommendation_feedback_student_updated', 'recommendation_feedback', ['student_id', 'updated_at'], unique=False, schema='ai')

    op.create_table('recommendation_preferences',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('preferred_formats', postgresql.ARRAY(sa.String(length=20)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('max_minutes', sa.SmallInteger(), nullable=True),
    sa.Column('muted_areas', postgresql.ARRAY(sa.String(length=30)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('use_indicators', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('max_minutes IS NULL OR max_minutes BETWEEN 1 AND 180', name=op.f('ck_recommendation_preferences_max_minutes_range')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_recommendation_preferences_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id', 'institution_id'], ['org.students.user_id', 'org.students.institution_id'], name=op.f('fk_recommendation_preferences_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('student_id', name=op.f('pk_recommendation_preferences')),
    schema='ai'
    )
    op.create_index(op.f('ix_recommendation_preferences_institution_id'), 'recommendation_preferences', ['institution_id'], unique=False, schema='ai')

    for table in ('recommendation_feedback', 'recommendation_preferences'):
        op.execute(
            f"CREATE TRIGGER {table}_set_updated_at BEFORE UPDATE ON ai.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
        )


def downgrade() -> None:
    op.drop_index(op.f('ix_recommendation_preferences_institution_id'), table_name='recommendation_preferences', schema='ai')
    op.drop_table('recommendation_preferences', schema='ai')
    op.drop_index('ix_recommendation_feedback_student_updated', table_name='recommendation_feedback', schema='ai')
    op.drop_index(op.f('ix_recommendation_feedback_institution_id'), table_name='recommendation_feedback', schema='ai')
    op.drop_table('recommendation_feedback', schema='ai')
    op.drop_index('ix_recommendations_student_created', table_name='recommendations', schema='ai')
    op.drop_constraint('uq_recommendations_link_tenant', 'recommendations', schema='ai', type_='unique')
    op.drop_constraint(op.f('ck_recommendations_problem_area_known'), 'recommendations', schema='ai', type_='check')
    op.drop_constraint(op.f('ck_recommendations_relevance_range'), 'recommendations', schema='ai', type_='check')
    for column in ('engine_version', 'reasons', 'tags', 'resource_format', 'relevance', 'problem_area', 'intervention_key'):
        op.drop_column('recommendations', column, schema='ai')
