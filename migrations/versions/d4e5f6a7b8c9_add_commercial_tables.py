"""Add commercial account tables

Creates tables for travel agency / OTA onboarding:
- commercial_accounts: Agency profiles with tiered fee rates
- commercial_api_keys: API keys for programmatic access
- commercial_transactions: Completed bookings with fee records

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-01-29 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    # --- commercial_accounts ---
    op.create_table(
        'commercial_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('contact_email', sa.String(length=255), nullable=False),
        sa.Column('contact_name', sa.String(length=100), nullable=True),
        sa.Column('company_website', sa.String(length=255), nullable=True),
        sa.Column('owner_user_id', sa.Integer(), nullable=True),
        sa.Column('current_tier', sa.String(length=20), server_default='starter', nullable=False),
        sa.Column('fee_percent', sa.Float(), server_default='20.0', nullable=False),
        sa.Column('tickets_last_30d', sa.Integer(), server_default='0', nullable=True),
        sa.Column('revenue_last_30d_usd', sa.Float(), server_default='0.0', nullable=True),
        sa.Column('total_tickets', sa.Integer(), server_default='0', nullable=True),
        sa.Column('total_revenue_usd', sa.Float(), server_default='0.0', nullable=True),
        sa.Column('periods_below_threshold', sa.Integer(), server_default='0', nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('p2p_enabled', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('max_daily_searches', sa.Integer(), server_default='500', nullable=True),
        sa.Column('max_concurrent_searches', sa.Integer(), server_default='10', nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('activated_at', sa.DateTime(), nullable=True),
        sa.Column('suspended_at', sa.DateTime(), nullable=True),
        sa.Column('last_tier_review', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_commercial_accounts_account_id', 'commercial_accounts', ['account_id'], unique=True)
    op.create_index('ix_commercial_accounts_owner_user_id', 'commercial_accounts', ['owner_user_id'])

    # --- commercial_api_keys ---
    op.create_table(
        'commercial_api_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('key_prefix', sa.String(length=8), nullable=False),
        sa.Column('key_hash', sa.String(length=128), nullable=False),
        sa.Column('label', sa.String(length=100), server_default='Default', nullable=True),
        sa.Column('scopes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('total_requests', sa.Integer(), server_default='0', nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['commercial_accounts.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_commercial_api_keys_account_id', 'commercial_api_keys', ['account_id'])

    # --- commercial_transactions ---
    op.create_table(
        'commercial_transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('booking_id', sa.Integer(), nullable=True),
        sa.Column('p2p_transaction_id', sa.Integer(), nullable=True),
        sa.Column('retail_price_usd', sa.Float(), nullable=False),
        sa.Column('booked_price_usd', sa.Float(), nullable=False),
        sa.Column('savings_usd', sa.Float(), nullable=False),
        sa.Column('savings_percent', sa.Float(), nullable=True),
        sa.Column('fee_percent_applied', sa.Float(), nullable=False),
        sa.Column('fee_amount_usd', sa.Float(), nullable=False),
        sa.Column('origin', sa.String(length=10), nullable=True),
        sa.Column('destination', sa.String(length=10), nullable=True),
        sa.Column('market_used', sa.String(length=2), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='completed', nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['commercial_accounts.id']),
        sa.ForeignKeyConstraint(['booking_id'], ['bookings.id']),
        sa.ForeignKeyConstraint(['p2p_transaction_id'], ['p2p_transactions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_commercial_transactions_account_id', 'commercial_transactions', ['account_id'])
    op.create_index('ix_commercial_transactions_status', 'commercial_transactions', ['status'])


def downgrade():
    op.drop_table('commercial_transactions')
    op.drop_table('commercial_api_keys')
    op.drop_table('commercial_accounts')
