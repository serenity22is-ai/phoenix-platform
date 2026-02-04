"""Add P2P purchasing network tables

Creates tables for the P2P Purchasing Network:
- helper_profiles: Helpers who earn by granting browser access
- user_wallets: XRPL wallets linked to user accounts
- user_cards: Payment cards for helpers (tokenized, no full numbers)
- p2p_transactions: Full lifecycle tracking of P2P purchases
- p2p_escrows: XRPL escrow records for three-party settlement

Revision ID: a1b2c3d4e5f6
Revises: 79966bdfccc1
Create Date: 2026-01-29 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '79966bdfccc1'
branch_labels = None
depends_on = None


def upgrade():
    # --- helper_profiles ---
    op.create_table(
        'helper_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('is_approved', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('is_online', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('country_code', sa.String(length=2), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('timezone', sa.String(length=50), nullable=True),
        sa.Column('google_account_linked', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('total_transactions', sa.Integer(), server_default='0', nullable=False),
        sa.Column('successful_transactions', sa.Integer(), server_default='0', nullable=False),
        sa.Column('failed_transactions', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_earned_rlusd', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('average_rating', sa.Float(), server_default='5.0', nullable=False),
        sa.Column('available_hours_start', sa.Integer(), server_default='0', nullable=False),
        sa.Column('available_hours_end', sa.Integer(), server_default='24', nullable=False),
        sa.Column('max_daily_transactions', sa.Integer(), server_default='10', nullable=False),
        sa.Column('transactions_today', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_active', sa.DateTime(), nullable=True),
        sa.Column('last_transaction', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_helper_profiles_user_id', 'helper_profiles', ['user_id'], unique=True)
    op.create_index('ix_helper_profiles_country_code', 'helper_profiles', ['country_code'])

    # --- user_wallets ---
    op.create_table(
        'user_wallets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('wallet_address', sa.String(length=100), nullable=False),
        sa.Column('wallet_label', sa.String(length=50), server_default='Primary', nullable=True),
        sa.Column('is_primary', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('is_verified', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('verification_tx_hash', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_used', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_wallets_user_id', 'user_wallets', ['user_id'])
    op.create_index('ix_user_wallets_wallet_address', 'user_wallets', ['wallet_address'])

    # --- user_cards ---
    op.create_table(
        'user_cards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('card_label', sa.String(length=50), server_default='Primary Card', nullable=True),
        sa.Column('card_last_four', sa.String(length=4), nullable=True),
        sa.Column('card_brand', sa.String(length=20), nullable=True),
        sa.Column('card_exp_month', sa.Integer(), nullable=True),
        sa.Column('card_exp_year', sa.Integer(), nullable=True),
        sa.Column('stripe_payment_method_id', sa.String(length=100), nullable=True),
        sa.Column('billing_name', sa.String(length=100), nullable=True),
        sa.Column('billing_country', sa.String(length=2), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('is_primary', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_cards_user_id', 'user_cards', ['user_id'])

    # --- p2p_transactions ---
    op.create_table(
        'p2p_transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('transaction_id', sa.String(length=50), nullable=False),
        sa.Column('buyer_id', sa.Integer(), nullable=False),
        sa.Column('helper_id', sa.Integer(), nullable=True),
        sa.Column('origin', sa.String(length=10), nullable=True),
        sa.Column('destination', sa.String(length=10), nullable=True),
        sa.Column('departure_date', sa.Date(), nullable=True),
        sa.Column('airline', sa.String(length=50), nullable=True),
        sa.Column('flight_number', sa.String(length=20), nullable=True),
        sa.Column('us_price_usd', sa.Float(), nullable=True),
        sa.Column('target_price_usd', sa.Float(), nullable=True),
        sa.Column('target_price_local', sa.Float(), nullable=True),
        sa.Column('target_currency', sa.String(length=3), nullable=True),
        sa.Column('target_market', sa.String(length=2), nullable=True),
        sa.Column('savings_usd', sa.Float(), nullable=True),
        sa.Column('escrow_amount_rlusd', sa.Float(), nullable=True),
        sa.Column('helper_reimbursement_rlusd', sa.Float(), nullable=True),
        sa.Column('helper_earning_rlusd', sa.Float(), nullable=True),
        sa.Column('platform_fee_rlusd', sa.Float(), nullable=True),
        sa.Column('escrow_tx_hash', sa.String(length=100), nullable=True),
        sa.Column('escrow_release_tx_hash', sa.String(length=100), nullable=True),
        sa.Column('escrow_sequence', sa.Integer(), nullable=True),
        sa.Column('escrow_verified_by_helper', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('escrow_verified_at', sa.DateTime(), nullable=True),
        sa.Column('confirmation_code', sa.String(length=50), nullable=True),
        sa.Column('passenger_name', sa.String(length=100), nullable=True),
        sa.Column('passenger_email', sa.String(length=255), nullable=True),
        sa.Column('eticket_url', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=30), server_default='requested', nullable=False),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('browser_session_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('matched_at', sa.DateTime(), nullable=True),
        sa.Column('escrow_locked_at', sa.DateTime(), nullable=True),
        sa.Column('purchase_started_at', sa.DateTime(), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['buyer_id'], ['users.id']),
        sa.ForeignKeyConstraint(['helper_id'], ['helper_profiles.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_p2p_transactions_transaction_id', 'p2p_transactions', ['transaction_id'], unique=True)
    op.create_index('ix_p2p_transactions_buyer_id', 'p2p_transactions', ['buyer_id'])
    op.create_index('ix_p2p_transactions_helper_id', 'p2p_transactions', ['helper_id'])
    op.create_index('ix_p2p_transactions_status', 'p2p_transactions', ['status'])

    # --- p2p_escrows ---
    op.create_table(
        'p2p_escrows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('escrow_id', sa.String(length=50), nullable=False),
        sa.Column('p2p_transaction_id', sa.Integer(), nullable=False),
        sa.Column('buyer_address', sa.String(length=100), nullable=True),
        sa.Column('helper_address', sa.String(length=100), nullable=True),
        sa.Column('platform_address', sa.String(length=100), nullable=True),
        sa.Column('total_rlusd', sa.Float(), nullable=True),
        sa.Column('helper_amount_rlusd', sa.Float(), nullable=True),
        sa.Column('platform_amount_rlusd', sa.Float(), nullable=True),
        sa.Column('create_tx_hash', sa.String(length=100), nullable=True),
        sa.Column('create_sequence', sa.Integer(), nullable=True),
        sa.Column('condition', sa.String(length=200), nullable=True),
        sa.Column('fulfillment', sa.String(length=200), nullable=True),
        sa.Column('helper_release_tx_hash', sa.String(length=100), nullable=True),
        sa.Column('platform_release_tx_hash', sa.String(length=100), nullable=True),
        sa.Column('cancel_tx_hash', sa.String(length=100), nullable=True),
        sa.Column('cancel_after', sa.DateTime(), nullable=True),
        sa.Column('finish_after', sa.DateTime(), nullable=True),
        sa.Column('on_chain_verified', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('ledger_index', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.Column('released_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['p2p_transaction_id'], ['p2p_transactions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_p2p_escrows_escrow_id', 'p2p_escrows', ['escrow_id'], unique=True)
    op.create_index('ix_p2p_escrows_p2p_transaction_id', 'p2p_escrows', ['p2p_transaction_id'])
    op.create_index('ix_p2p_escrows_status', 'p2p_escrows', ['status'])


def downgrade():
    op.drop_table('p2p_escrows')
    op.drop_table('p2p_transactions')
    op.drop_table('user_cards')
    op.drop_table('user_wallets')
    op.drop_table('helper_profiles')
