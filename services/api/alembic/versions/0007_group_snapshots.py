"""group snapshots

Stored group figures for closed windows (``wellness.group_snapshots``). A row is written the first
time anyone reads a class, department or institution window after its last week closes, and it
is deleted when a member's consent or account status changes. Holds only what the API already
returns; see ``app.application.cohort_stats.frozen``.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-10 10:55:38.072170
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('group_snapshots',
    sa.Column('view', sa.String(length=30), nullable=False),
    sa.Column('group_kind', sa.String(length=20), nullable=False),
    sa.Column('group_id', sa.UUID(), nullable=False),
    sa.Column('last_week', sa.Date(), nullable=False),
    sa.Column('weeks', sa.SmallInteger(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("group_kind IN ('class', 'department', 'institution')", name=op.f('ck_group_snapshots_group_kind_known')),
    sa.CheckConstraint("view IN ('figures', 'mood_summary')", name=op.f('ck_group_snapshots_view_known')),
    sa.CheckConstraint('weeks > 0', name=op.f('ck_group_snapshots_weeks_positive')),
    sa.ForeignKeyConstraint(['institution_id'], ['org.institutions.id'], name=op.f('fk_group_snapshots_institution_id_institutions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_group_snapshots')),
    sa.UniqueConstraint('group_id', 'institution_id', 'view', 'group_kind', 'last_week', 'weeks', name='uq_group_snapshots_window'),
    schema='wellness'
    )
    op.create_index(op.f('ix_group_snapshots_institution_id'), 'group_snapshots', ['institution_id'], unique=False, schema='wellness')
    op.execute(
        "CREATE TRIGGER group_snapshots_set_updated_at BEFORE UPDATE ON wellness.group_snapshots "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_group_snapshots_institution_id'), table_name='group_snapshots', schema='wellness')
    op.drop_table('group_snapshots', schema='wellness')
