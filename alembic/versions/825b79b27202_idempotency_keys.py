"""idempotency_keys table (prevents duplicate expenses on client retry)

Also merges the two pre-existing unmerged heads (8a1b2c3d4e5f, cf30fd85e22b).

Revision ID: 825b79b27202
Revises: 8a1b2c3d4e5f, cf30fd85e22b
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '825b79b27202'
down_revision: Union[str, Sequence[str], None] = ('8a1b2c3d4e5f', 'cf30fd85e22b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'idempotency_keys',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('endpoint', sa.String(length=100), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('response_json', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', 'endpoint', 'key', name='uq_idempotency_key'),
    )
    op.create_index('idx_idempotency_lookup', 'idempotency_keys', ['user_id', 'endpoint', 'key'])


def downgrade() -> None:
    op.drop_index('idx_idempotency_lookup', table_name='idempotency_keys')
    op.drop_table('idempotency_keys')
