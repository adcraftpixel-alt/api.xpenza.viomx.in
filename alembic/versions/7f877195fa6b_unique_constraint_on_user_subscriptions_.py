"""unique constraint on user_subscriptions.user_id

Revision ID: 7f877195fa6b
Revises: f6a7b8c9d0e1
Create Date: 2026-08-13 23:06:31.034981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f877195fa6b'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Defensively remove any duplicate rows first, keeping the most recently
    # created one per user. The app-level "already have a subscription" guard
    # existed before this constraint, so duplicates from the race this
    # constraint closes are unlikely to already exist — but a migration that
    # fails outright on unexpected prod data is worse than this cleanup.
    op.execute("""
        DELETE FROM user_subscriptions a USING user_subscriptions b
        WHERE a.user_id = b.user_id AND a.created_at < b.created_at
    """)
    op.create_unique_constraint(
        "uq_user_subscriptions_user_id", "user_subscriptions", ["user_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_user_subscriptions_user_id", "user_subscriptions", type_="unique",
    )
