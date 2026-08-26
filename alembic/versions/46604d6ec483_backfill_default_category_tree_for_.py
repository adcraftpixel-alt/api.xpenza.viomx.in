"""backfill default category tree for existing tenants

Revision ID: 46604d6ec483
Revises: 825b79b27202
Create Date: 2026-08-26 07:13:23.966620

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = '46604d6ec483'
down_revision: Union[str, None] = '825b79b27202'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Every tenant who registered before category seeding was wired into
    registration (auth/service.py) has zero personal categories, so their
    expenses fall through to the categorizer's "General" fallback with
    nowhere real to land. Seed the default tree — from
    app/api/v1/categories/default_tree.py, the single source of truth also
    used by onboarding and family-group creation — for every user missing
    a personal (family_group_id IS NULL) root category. Idempotent: existing
    roots are matched by name and reused, so it's safe to re-run.
    """
    bind = op.get_bind()
    session = Session(bind=bind)

    from app.api.v1.categories.default_tree import seed_category_tree

    user_ids = [
        row[0] for row in session.execute(
            sa.text("""
                SELECT u.id FROM users u
                WHERE NOT EXISTS (
                    SELECT 1 FROM categories c
                    WHERE c.user_id = u.id
                      AND c.family_group_id IS NULL
                      AND c.parent_id IS NULL
                )
            """)
        ).fetchall()
    ]

    for uid in user_ids:
        seed_category_tree(session, user_id=str(uid), family_group_id=None)


def downgrade() -> None:
    # Data backfill only — no schema change, nothing to structurally revert.
    pass
