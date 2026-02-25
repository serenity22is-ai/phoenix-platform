"""Add stripe_customer_id to users table for saved payment methods

Revision ID: f3g4h5i6j7k8
Revises: e2f3g4h5i6j7
Create Date: 2026-02-12

Phase 1 Payment Cleanup:
- Adds stripe_customer_id column to users table
- Stripe Customers are created lazily on first checkout
- Enables saved payment methods via setup_future_usage
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3g4h5i6j7k8'
down_revision = 'e2f3g4h5i6j7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('stripe_customer_id', sa.String(100), nullable=True))
        batch_op.create_index('ix_users_stripe_customer_id', ['stripe_customer_id'], unique=True)


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index('ix_users_stripe_customer_id')
        batch_op.drop_column('stripe_customer_id')
