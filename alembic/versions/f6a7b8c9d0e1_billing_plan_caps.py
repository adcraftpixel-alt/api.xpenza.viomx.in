"""add caps json to billing_plans (Control Hub plan enforcement)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('billing_plans', sa.Column('caps', JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column('billing_plans', 'caps')
