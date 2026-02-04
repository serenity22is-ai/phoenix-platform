"""Add CitizenSERP payout tables

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-01-29

Adds:
- node_sessions: Individual node uptime sessions
- node_payout_epochs: Payout period metadata and revenue pool
- node_payouts: Per-node payout records with XRPL tx tracking
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'g7h8i9j0k1l2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    # -- node_sessions --
    op.create_table('node_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.String(50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('duration_minutes', sa.Float(), nullable=True),
        sa.Column('wallet_address', sa.String(100), nullable=False),
        sa.Column('ip_country', sa.String(2), nullable=True),
        sa.Column('xrpl_attestation_tx', sa.String(100), nullable=True),
        sa.Column('attestation_ledger_index', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_node_sessions_session_id', 'node_sessions', ['session_id'], unique=True)
    op.create_index('ix_node_sessions_ip_country', 'node_sessions', ['ip_country'])
    op.create_index('ix_node_sessions_status', 'node_sessions', ['status'])
    op.create_index('ix_node_sessions_user_status', 'node_sessions', ['user_id', 'status'])
    op.create_index('ix_node_sessions_start_end', 'node_sessions', ['start_time', 'end_time'])

    # -- node_payout_epochs --
    op.create_table('node_payout_epochs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('epoch_id', sa.String(50), nullable=False),
        sa.Column('period_start', sa.DateTime(), nullable=False),
        sa.Column('period_end', sa.DateTime(), nullable=False),
        sa.Column('total_revenue_pool_usd', sa.Float(), nullable=False),
        sa.Column('payout_percentage', sa.Float(), nullable=False),
        sa.Column('total_payout_pool_usd', sa.Float(), nullable=False),
        sa.Column('total_node_hours', sa.Float(), nullable=False),
        sa.Column('rate_per_hour_usd', sa.Float(), nullable=False),
        sa.Column('nodes_paid', sa.Integer(), server_default='0'),
        sa.Column('status', sa.String(20), server_default='calculating'),
        sa.Column('distribution_tx_batch', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_node_payout_epochs_epoch_id', 'node_payout_epochs', ['epoch_id'], unique=True)
    op.create_index('ix_node_payout_epochs_status', 'node_payout_epochs', ['status'])

    # -- node_payouts --
    op.create_table('node_payouts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('epoch_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('wallet_address', sa.String(100), nullable=False),
        sa.Column('uptime_hours', sa.Float(), nullable=False),
        sa.Column('payout_amount_rlusd', sa.Float(), nullable=False),
        sa.Column('tx_hash', sa.String(100), nullable=True),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['epoch_id'], ['node_payout_epochs.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_node_payouts_status', 'node_payouts', ['status'])
    op.create_index('ix_node_payouts_epoch_user', 'node_payouts', ['epoch_id', 'user_id'], unique=True)


def downgrade():
    op.drop_index('ix_node_payouts_epoch_user', 'node_payouts')
    op.drop_index('ix_node_payouts_status', 'node_payouts')
    op.drop_table('node_payouts')

    op.drop_index('ix_node_payout_epochs_status', 'node_payout_epochs')
    op.drop_index('ix_node_payout_epochs_epoch_id', 'node_payout_epochs')
    op.drop_table('node_payout_epochs')

    op.drop_index('ix_node_sessions_start_end', 'node_sessions')
    op.drop_index('ix_node_sessions_user_status', 'node_sessions')
    op.drop_index('ix_node_sessions_status', 'node_sessions')
    op.drop_index('ix_node_sessions_ip_country', 'node_sessions')
    op.drop_index('ix_node_sessions_session_id', 'node_sessions')
    op.drop_table('node_sessions')
