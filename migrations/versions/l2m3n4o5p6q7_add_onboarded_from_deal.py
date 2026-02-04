"""Add onboarded_from_deal_id to users for seller onboarding attribution

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa


revision = 'l2m3n4o5p6q7'
down_revision = 'k1l2m3n4o5p6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('onboarded_from_deal_id', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('users', 'onboarded_from_deal_id')
