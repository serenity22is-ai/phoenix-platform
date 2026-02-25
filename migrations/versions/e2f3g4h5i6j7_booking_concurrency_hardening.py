"""Booking concurrency hardening — prevent duplicate bookings and overselling

Revision ID: e2f3g4h5i6j7
Revises: d1e2f3g4h5i6
Create Date: 2026-02-12

Phase 1: Adds database-level guards for concurrent booking:
1. UniqueConstraint on bookings(deal_id, payment_id) — prevents duplicate bookings
2. Deal.deal_status + claimed_by + claimed_at — prevents overselling
3. Payment.status 'fulfillment_triggered' — prevents double fulfillment trigger
"""
from alembic import op
import sqlalchemy as sa

revision = 'e2f3g4h5i6j7'
down_revision = 'd1e2f3g4h5i6'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add deal claiming columns to deals table
    with op.batch_alter_table('deals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('deal_status', sa.String(20), server_default='available', nullable=True))
        batch_op.add_column(sa.Column('claimed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
        batch_op.add_column(sa.Column('claimed_at', sa.DateTime(), nullable=True))
        batch_op.create_index('ix_deals_deal_status', ['deal_status'])

    # 2. Set existing deals to 'available'
    op.execute("UPDATE deals SET deal_status = 'available' WHERE deal_status IS NULL")

    # 3. Add unique constraint on bookings(deal_id, payment_id)
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_booking_deal_payment', ['deal_id', 'payment_id'])


def downgrade():
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        batch_op.drop_constraint('uq_booking_deal_payment', type_='unique')

    with op.batch_alter_table('deals', schema=None) as batch_op:
        batch_op.drop_index('ix_deals_deal_status')
        batch_op.drop_column('claimed_at')
        batch_op.drop_column('claimed_by')
        batch_op.drop_column('deal_status')
