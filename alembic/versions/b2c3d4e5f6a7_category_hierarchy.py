"""add category hierarchy (parent_id + level)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'categories',
        sa.Column('parent_id', sa.UUID(as_uuid=False), nullable=True),
    )
    op.add_column(
        'categories',
        sa.Column('level', sa.SmallInteger(), nullable=False, server_default='0'),
    )
    op.create_foreign_key(
        'fk_categories_parent_id',
        'categories', 'categories',
        ['parent_id'], ['id'],
        ondelete='CASCADE',
    )
    op.create_index('ix_categories_parent_id', 'categories', ['parent_id'])


def downgrade() -> None:
    op.drop_index('ix_categories_parent_id', table_name='categories')
    op.drop_constraint('fk_categories_parent_id', 'categories', type_='foreignkey')
    op.drop_column('categories', 'level')
    op.drop_column('categories', 'parent_id')
