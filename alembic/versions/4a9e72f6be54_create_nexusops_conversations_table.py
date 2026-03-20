"""create nexusops_conversations table

Revision ID: 4a9e72f6be54
Revises: 
Create Date: 2026-03-20 12:30:56.699035

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a9e72f6be54'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'nexusops_conversations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('full_history', sa.JSON(), nullable=True),
        sa.Column('conversational_history', sa.JSON(), nullable=True),
        sa.Column('total_conversational_messages', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index(op.f('ix_nexusops_conversations_session_id'), 'nexusops_conversations', ['session_id'], unique=True)
    op.create_index(op.f('ix_nexusops_conversations_user_id'), 'nexusops_conversations', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_nexusops_conversations_user_id'), table_name='nexusops_conversations')
    op.drop_index(op.f('ix_nexusops_conversations_session_id'), table_name='nexusops_conversations')
    op.drop_table('nexusops_conversations')
