"""Add browsing_tier columns to commercial_accounts (Build #70)

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa


revision = 'r8s9t0u1v2w3'
down_revision = 'q7r8s9t0u1v2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('commercial_accounts', sa.Column('browsing_tier', sa.String(30), server_default='browsing_free'))
    op.add_column('commercial_accounts', sa.Column('browsing_events_used_this_month', sa.Integer(), server_default='0'))
    op.add_column('commercial_accounts', sa.Column('browsing_month_reset_date', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('commercial_accounts', 'browsing_month_reset_date')
    op.drop_column('commercial_accounts', 'browsing_events_used_this_month')
    op.drop_column('commercial_accounts', 'browsing_tier')
