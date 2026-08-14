"""hub_synced_at on user_subscriptions

Revision ID: cf30fd85e22b
Revises: 7f877195fa6b
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf30fd85e22b'
down_revision: Union[str, None] = '7f877195fa6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_subscriptions",
        sa.Column("hub_synced_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_subscriptions", "hub_synced_at")
