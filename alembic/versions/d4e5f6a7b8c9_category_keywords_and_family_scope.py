"""add category keywords table + family_group_id on categories

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── categories.family_group_id (NULL = personal, set = shared family tree) ──
    op.add_column(
        'categories',
        sa.Column('family_group_id', sa.UUID(as_uuid=False), nullable=True),
    )
    op.create_foreign_key(
        'fk_categories_family_group_id',
        'categories', 'family_groups',
        ['family_group_id'], ['id'],
        ondelete='CASCADE',
    )
    op.create_index('ix_categories_family_group_id', 'categories', ['family_group_id'])

    # ── category_keywords (data-driven aliases for the hybrid categorizer) ──────
    op.create_table(
        'category_keywords',
        sa.Column('id', sa.UUID(as_uuid=False), primary_key=True),
        sa.Column('category_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('keyword', sa.String(100), nullable=False),
        sa.Column('lang', sa.String(10), nullable=True),
        sa.Column('source', sa.String(20), nullable=False, server_default='seed'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_category_keywords_category_id', 'category_keywords', ['category_id'])
    op.create_index('ix_category_keywords_keyword', 'category_keywords', ['keyword'])


def downgrade() -> None:
    op.drop_index('ix_category_keywords_keyword', table_name='category_keywords')
    op.drop_index('ix_category_keywords_category_id', table_name='category_keywords')
    op.drop_table('category_keywords')

    op.drop_index('ix_categories_family_group_id', table_name='categories')
    op.drop_constraint('fk_categories_family_group_id', 'categories', type_='foreignkey')
    op.drop_column('categories', 'family_group_id')
