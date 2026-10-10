"""ai companion

How each assistant message was produced (``ai_messages.reply_kind``) and when a companion
conversation last had a message (``ai_conversations.last_message_at``, for retention).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-10 16:05:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('ai_conversations', sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True), schema='ai')
    op.add_column('ai_messages', sa.Column('reply_kind', sa.Enum('reply', 'crisis', 'redirect', 'fallback', 'unavailable', name='ai_reply_kind', native_enum=False, create_constraint=True, length=32), nullable=True), schema='ai')
    # Earlier assistant messages were all ordinary replies.
    op.execute("UPDATE ai.ai_messages SET reply_kind = 'reply' WHERE role = 'assistant'")
    op.execute(
        "UPDATE ai.ai_conversations c SET last_message_at = "
        "(SELECT max(created_at) FROM ai.ai_messages m WHERE m.conversation_id = c.id)"
    )
    op.create_check_constraint(
        op.f('ck_ai_messages_reply_kind_on_assistant'), 'ai_messages',
        "(role = 'assistant') = (reply_kind IS NOT NULL)", schema='ai',
    )


def downgrade() -> None:
    op.drop_constraint(op.f('ck_ai_messages_reply_kind_on_assistant'), 'ai_messages', schema='ai', type_='check')
    op.drop_column('ai_messages', 'reply_kind', schema='ai')
    op.drop_column('ai_conversations', 'last_message_at', schema='ai')
