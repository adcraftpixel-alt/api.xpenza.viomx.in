"""faqs and support_tickets

Revision ID: a1b2c3d4e5f6
Revises: 4f3116013298
Create Date: 2026-05-27 00:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '4f3116013298'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'faqs',
        sa.Column('id', sa.UUID(as_uuid=False), primary_key=True),
        sa.Column('question', sa.Text, nullable=False),
        sa.Column('answer', sa.Text, nullable=False),
        sa.Column('category', sa.String(100), default='General'),
        sa.Column('order', sa.Integer, default=0),
        sa.Column('is_active', sa.Boolean, default=True, nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime, server_default=sa.text('NOW()')),
    )
    op.create_table(
        'support_tickets',
        sa.Column('id', sa.UUID(as_uuid=False), primary_key=True),
        sa.Column('user_id', sa.UUID(as_uuid=False), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('subject', sa.String(255), nullable=False),
        sa.Column('message', sa.Text, nullable=False),
        sa.Column('category', sa.String(100), default='General'),
        sa.Column('status', sa.String(50), default='open', nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('NOW()')),
    )
    op.create_index('ix_support_tickets_user_id', 'support_tickets', ['user_id'])


def downgrade():
    op.drop_index('ix_support_tickets_user_id', table_name='support_tickets')
    op.drop_table('support_tickets')
    op.drop_table('faqs')
