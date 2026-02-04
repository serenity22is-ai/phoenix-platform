"""Add dispute resolution tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-01-29 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    # --- disputes ---
    op.create_table(
        'disputes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dispute_id', sa.String(length=50), nullable=False),
        sa.Column('p2p_transaction_id', sa.Integer(), nullable=True),
        sa.Column('opened_by_user_id', sa.Integer(), nullable=True),
        sa.Column('assigned_admin_id', sa.Integer(), nullable=True),
        sa.Column('reason', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('evidence_urls', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=30), server_default='opened', nullable=False),
        sa.Column('resolution_type', sa.String(length=30), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('refund_amount_rlusd', sa.Float(), nullable=True),
        sa.Column('refund_tx_hash', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['p2p_transaction_id'], ['p2p_transactions.id']),
        sa.ForeignKeyConstraint(['opened_by_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['assigned_admin_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_disputes_dispute_id', 'disputes', ['dispute_id'], unique=True)
    op.create_index('ix_disputes_p2p_transaction_id', 'disputes', ['p2p_transaction_id'])
    op.create_index('ix_disputes_opened_by_user_id', 'disputes', ['opened_by_user_id'])
    op.create_index('ix_disputes_status', 'disputes', ['status'])

    # --- dispute_messages ---
    op.create_table(
        'dispute_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dispute_id', sa.Integer(), nullable=False),
        sa.Column('sender_id', sa.Integer(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('is_admin', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('attachment_url', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['dispute_id'], ['disputes.id']),
        sa.ForeignKeyConstraint(['sender_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_dispute_messages_dispute_id', 'dispute_messages', ['dispute_id'])


def downgrade():
    op.drop_table('dispute_messages')
    op.drop_table('disputes')
