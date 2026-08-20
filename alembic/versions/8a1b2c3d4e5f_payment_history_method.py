"""add method column to payment_history (for billing history detail view)

Revision ID: 8a1b2c3d4e5f
Revises: 7f877195fa6b
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa

revision = '8a1b2c3d4e5f'
down_revision = '7f877195fa6b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'payment_history',
        sa.Column('method', sa.String(30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('payment_history', 'method')
