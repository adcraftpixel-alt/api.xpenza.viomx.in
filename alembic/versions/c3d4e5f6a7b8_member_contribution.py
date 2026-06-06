"""add contribution to family_group_members

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'family_group_members',
        sa.Column('contribution', sa.Numeric(12, 2),
                  nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('family_group_members', 'contribution')
