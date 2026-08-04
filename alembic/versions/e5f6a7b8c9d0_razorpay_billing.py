"""add razorpay columns to billing tables (INR recurring auto-pay)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── billing_plans.razorpay_plan_id ──────────────────────────────────────
    op.add_column(
        'billing_plans',
        sa.Column('razorpay_plan_id', sa.String(255), nullable=True),
    )

    # ── user_subscriptions: gateway-agnostic recurring fields ───────────────
    op.add_column(
        'user_subscriptions',
        sa.Column('razorpay_subscription_id', sa.String(255), nullable=True),
    )
    op.add_column(
        'user_subscriptions',
        sa.Column('gateway', sa.String(20), nullable=False,
                  server_default='razorpay'),
    )
    op.add_column(
        'user_subscriptions',
        sa.Column('trial_end', sa.DateTime(), nullable=True),
    )
    op.create_unique_constraint(
        'uq_user_subscriptions_razorpay_subscription_id',
        'user_subscriptions', ['razorpay_subscription_id'],
    )

    # ── payment_history: razorpay ids + gateway ─────────────────────────────
    op.add_column(
        'payment_history',
        sa.Column('razorpay_invoice_id', sa.String(255), nullable=True),
    )
    op.add_column(
        'payment_history',
        sa.Column('razorpay_payment_id', sa.String(255), nullable=True),
    )
    op.add_column(
        'payment_history',
        sa.Column('gateway', sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('payment_history', 'gateway')
    op.drop_column('payment_history', 'razorpay_payment_id')
    op.drop_column('payment_history', 'razorpay_invoice_id')

    op.drop_constraint(
        'uq_user_subscriptions_razorpay_subscription_id',
        'user_subscriptions', type_='unique',
    )
    op.drop_column('user_subscriptions', 'trial_end')
    op.drop_column('user_subscriptions', 'gateway')
    op.drop_column('user_subscriptions', 'razorpay_subscription_id')

    op.drop_column('billing_plans', 'razorpay_plan_id')
