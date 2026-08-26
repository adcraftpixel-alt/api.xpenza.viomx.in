"""add missing indexes on categories and category_keywords

Revision ID: 0c8baa752f6d
Revises: 46604d6ec483
Create Date: 2026-08-26 08:43:05.041255

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0c8baa752f6d'
down_revision: Union[str, None] = '46604d6ec483'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """categories.user_id was never indexed in any prior migration, and
    family_group_id/parent_id/category_keywords.category_id/keyword were
    only ever created by migration d4e5f6a7b8c9 + b2c3d4e5f6a7 — which
    silently never applied on environments whose schema came from
    Base.metadata.create_all() instead of `alembic upgrade head`. Every
    category lookup and keyword match (ai_categorizer.py) is scoped by one
    of these columns, so without indexes those queries are full table scans
    that get worse as tenants grow. CONCURRENTLY avoids locking writers.
    """
    with op.get_context().autocommit_block():
        op.create_index(
            'ix_categories_user_id', 'categories', ['user_id'],
            unique=False, postgresql_concurrently=True, if_not_exists=True,
        )
        op.create_index(
            'ix_categories_family_group_id', 'categories', ['family_group_id'],
            unique=False, postgresql_concurrently=True, if_not_exists=True,
        )
        op.create_index(
            'ix_categories_parent_id', 'categories', ['parent_id'],
            unique=False, postgresql_concurrently=True, if_not_exists=True,
        )
        op.create_index(
            'ix_category_keywords_category_id', 'category_keywords', ['category_id'],
            unique=False, postgresql_concurrently=True, if_not_exists=True,
        )
        op.create_index(
            'ix_category_keywords_keyword', 'category_keywords', ['keyword'],
            unique=False, postgresql_concurrently=True, if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index('ix_category_keywords_keyword', table_name='category_keywords',
                      postgresql_concurrently=True, if_exists=True)
        op.drop_index('ix_category_keywords_category_id', table_name='category_keywords',
                      postgresql_concurrently=True, if_exists=True)
        op.drop_index('ix_categories_parent_id', table_name='categories',
                      postgresql_concurrently=True, if_exists=True)
        op.drop_index('ix_categories_family_group_id', table_name='categories',
                      postgresql_concurrently=True, if_exists=True)
        op.drop_index('ix_categories_user_id', table_name='categories',
                      postgresql_concurrently=True, if_exists=True)
