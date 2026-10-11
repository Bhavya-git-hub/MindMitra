"""safety events

``safety.safety_events``: what the safety system did about a HIGH or IMMEDIATE concern (level,
kind of concern, source, detector, rules version, whether a person was asked and on what
basis, the alert, and the pause on suggestions). No text and no link to what was written.
A unique ``(id, institution_id)`` on ``risk_alerts`` lets an event point at an alert of its own
institution only. See ADR 0013.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-11 11:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0012'
down_revision: str | None = '0011'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint('uq_risk_alerts_link_tenant', 'risk_alerts', ['id', 'institution_id'], schema='safety')
    op.create_table('safety_events',
    sa.Column('student_id', sa.UUID(), nullable=False),
    sa.Column('source', sa.Enum('check_in', 'companion', 'message', name='safety_event_source', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('risk_level', sa.Enum('low', 'moderate', 'high', 'immediate', name='risk_level', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('concern', sa.Enum('suicidal_language', 'self_harm_language', 'harm_to_others', 'unsafe_situation', 'acute_distress', 'distress_language', 'concern_for_other', 'low_mood_today', 'high_stress_today', 'sustained_low_mood', name='safety_concern', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('detector', sa.Enum('rules', 'classifier', 'behaviour', name='safety_detector', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('rules_version', sa.String(length=80), nullable=True),
    sa.Column('escalated', sa.Boolean(), nullable=False),
    sa.Column('basis', sa.Enum('consent', 'vital_interest', 'care_team_message', 'companion_notice', 'no_consent', 'not_needed', name='escalation_basis', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('alert_id', sa.UUID(), nullable=True),
    sa.Column('recommendations_paused', sa.Boolean(), nullable=False),
    sa.Column('hold_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("NOT escalated OR basis IN ('consent','vital_interest','care_team_message','companion_notice')", name=op.f('ck_safety_events_escalated_needs_basis')),
    sa.CheckConstraint("risk_level IN ('high','immediate')", name=op.f('ck_safety_events_only_high_or_immediate')),
    sa.CheckConstraint('alert_id IS NULL OR escalated', name=op.f('ck_safety_events_alert_only_when_escalated')),
    sa.CheckConstraint('recommendations_paused = (hold_until IS NOT NULL)', name=op.f('ck_safety_events_hold_until_when_paused')),
    sa.ForeignKeyConstraint(['alert_id', 'institution_id'], ['safety.risk_alerts.id', 'safety.risk_alerts.institution_id'], name=op.f('fk_safety_events_alert_id_institution_id_risk_alerts'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_safety_events_institution_id_institutions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id', 'institution_id'], ['org.students.user_id', 'org.students.institution_id'], name=op.f('fk_safety_events_student_id_institution_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_safety_events')),
    schema='safety'
    )
    op.create_index('ix_safety_events_created', 'safety_events', ['created_at'], unique=False, schema='safety')
    op.create_index('ix_safety_events_alert_id', 'safety_events', ['alert_id'], unique=False, schema='safety', postgresql_where=sa.text('alert_id IS NOT NULL'))
    op.create_index(op.f('ix_safety_events_institution_id'), 'safety_events', ['institution_id'], unique=False, schema='safety')
    op.create_index('ix_safety_events_student_created', 'safety_events', ['student_id', sa.literal_column('created_at DESC')], unique=False, schema='safety')
    op.execute(
        "CREATE TRIGGER safety_events_set_updated_at BEFORE UPDATE ON safety.safety_events "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )


def downgrade() -> None:
    op.drop_index('ix_safety_events_student_created', table_name='safety_events', schema='safety')
    op.drop_index(op.f('ix_safety_events_institution_id'), table_name='safety_events', schema='safety')
    op.drop_index('ix_safety_events_alert_id', table_name='safety_events', schema='safety')
    op.drop_index('ix_safety_events_created', table_name='safety_events', schema='safety')
    op.drop_table('safety_events', schema='safety')
    op.drop_constraint('uq_risk_alerts_link_tenant', 'risk_alerts', schema='safety', type_='unique')
