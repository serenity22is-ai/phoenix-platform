"""Add Node Consent Economy tables (Build #75)

- node_consent_profiles: Per-user consent config and tier state
- node_referrals: Referral tracking with activation/churn
- node_tier_history: Tier change audit trail
- fleet_accounts: Commercial fleet management
- revenue_allocations: Per-booking arbitrage fee allocation ledger
- crypto_conversions: Multi-crypto → XRP/RLUSD conversion records
- User model: XRPL wallet, referral code, KYC columns
- HelperProfile: fleet_id column

Revision ID: v1w2x3y4z5a6
Revises: u1v2w3x4y5z6
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa


revision = 'v1w2x3y4z5a6'
down_revision = 'u1v2w3x4y5z6'
branch_labels = None
depends_on = None


def upgrade():
    # --- User model additions ---
    op.add_column('users', sa.Column('xrpl_wallet_address', sa.String(100), unique=True, nullable=True))
    op.add_column('users', sa.Column('xrpl_wallet_seed_encrypted', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('xrpl_wallet_created_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('node_referral_code', sa.String(20), unique=True, nullable=True))
    op.add_column('users', sa.Column('total_node_referrals', sa.Integer(), server_default='0'))
    op.add_column('users', sa.Column('active_node_referrals', sa.Integer(), server_default='0'))
    op.add_column('users', sa.Column('kyc_status', sa.String(20), server_default='none'))
    op.add_column('users', sa.Column('kyc_verified_at', sa.DateTime(), nullable=True))
    op.create_index('ix_users_referral_code', 'users', ['node_referral_code'], unique=True)

    # --- HelperProfile addition ---
    op.add_column('helper_profiles', sa.Column('fleet_id', sa.String(50), nullable=True))
    op.create_index('ix_helper_profiles_fleet_id', 'helper_profiles', ['fleet_id'])

    # --- NodeConsentProfile ---
    op.create_table(
        'node_consent_profiles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), unique=True, nullable=False),
        sa.Column('node_id', sa.String(50), nullable=True),
        sa.Column('consent_location', sa.Boolean(), server_default='1'),
        sa.Column('consent_search_queries', sa.Boolean(), server_default='0'),
        sa.Column('consent_price_observations', sa.Boolean(), server_default='0'),
        sa.Column('consent_ad_impressions', sa.Boolean(), server_default='0'),
        sa.Column('consent_social_signals', sa.Boolean(), server_default='0'),
        sa.Column('consent_browsing_data', sa.Boolean(), server_default='0'),
        sa.Column('consent_business_data', sa.Boolean(), server_default='0'),
        sa.Column('current_tier', sa.String(20), server_default='bronze'),
        sa.Column('tier_score', sa.Float(), server_default='0.0'),
        sa.Column('data_share_score', sa.Float(), server_default='0.0'),
        sa.Column('referral_score', sa.Float(), server_default='0.0'),
        sa.Column('quality_score', sa.Float(), server_default='0.0'),
        sa.Column('longevity_score', sa.Float(), server_default='0.0'),
        sa.Column('payout_multiplier', sa.Float(), server_default='1.0'),
        sa.Column('arbitrage_fee_discount', sa.Float(), server_default='0.0'),
        sa.Column('phoenix_suite_access', sa.Boolean(), server_default='0'),
        sa.Column('background_service_enabled', sa.Boolean(), server_default='0'),
        sa.Column('background_service_hours_target', sa.Integer(), server_default='8'),
        sa.Column('last_tier_assessment', sa.DateTime(), nullable=True),
        sa.Column('next_tier_threshold', sa.Float(), server_default='25.0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_ncp_user_id', 'node_consent_profiles', ['user_id'], unique=True)
    op.create_index('ix_ncp_tier', 'node_consent_profiles', ['current_tier'])

    # --- NodeReferral ---
    op.create_table(
        'node_referrals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('referral_id', sa.String(50), unique=True, nullable=False),
        sa.Column('referrer_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('referee_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('referral_code', sa.String(20), nullable=False),
        sa.Column('is_activated', sa.Boolean(), server_default='0'),
        sa.Column('activated_at', sa.DateTime(), nullable=True),
        sa.Column('referee_total_earnings', sa.Float(), server_default='0.0'),
        sa.Column('referee_current_tier', sa.String(20), server_default='bronze'),
        sa.Column('referee_sessions_count', sa.Integer(), server_default='0'),
        sa.Column('is_churned', sa.Boolean(), server_default='0'),
        sa.Column('churned_at', sa.DateTime(), nullable=True),
        sa.Column('clawback_applied', sa.Boolean(), server_default='0'),
        sa.Column('activation_bonus_paid', sa.Boolean(), server_default='0'),
        sa.Column('activation_bonus_amount', sa.Float(), server_default='0.50'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_nr_referral_id', 'node_referrals', ['referral_id'], unique=True)
    op.create_index('ix_nr_referrer', 'node_referrals', ['referrer_user_id'])
    op.create_index('ix_nr_referee', 'node_referrals', ['referee_user_id'])
    op.create_index('ix_nr_code', 'node_referrals', ['referral_code'])

    # --- NodeTierHistory ---
    op.create_table(
        'node_tier_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('previous_tier', sa.String(20), nullable=False),
        sa.Column('new_tier', sa.String(20), nullable=False),
        sa.Column('tier_score', sa.Float(), nullable=False),
        sa.Column('data_share_score', sa.Float(), server_default='0.0'),
        sa.Column('referral_score', sa.Float(), server_default='0.0'),
        sa.Column('quality_score', sa.Float(), server_default='0.0'),
        sa.Column('longevity_score', sa.Float(), server_default='0.0'),
        sa.Column('reason', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_nth_user_id', 'node_tier_history', ['user_id'])
    op.create_index('ix_nth_created', 'node_tier_history', ['created_at'])

    # --- FleetAccount ---
    op.create_table(
        'fleet_accounts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('fleet_id', sa.String(50), unique=True, nullable=False),
        sa.Column('commercial_account_id', sa.Integer(), sa.ForeignKey('commercial_accounts.id'), nullable=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('contact_email', sa.String(255), nullable=False),
        sa.Column('max_nodes', sa.Integer(), server_default='100'),
        sa.Column('active_node_count', sa.Integer(), server_default='0'),
        sa.Column('total_node_count', sa.Integer(), server_default='0'),
        sa.Column('arbitrage_rate_discount', sa.Float(), server_default='0.0'),
        sa.Column('data_marketplace_revenue_share', sa.Float(), server_default='0.0'),
        sa.Column('priority_payout', sa.Boolean(), server_default='0'),
        sa.Column('enrollment_key', sa.String(50), unique=True, nullable=False),
        sa.Column('total_earnings_usd', sa.Float(), server_default='0.0'),
        sa.Column('total_data_events', sa.Integer(), server_default='0'),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_fa_fleet_id', 'fleet_accounts', ['fleet_id'], unique=True)
    op.create_index('ix_fa_commercial', 'fleet_accounts', ['commercial_account_id'])
    op.create_index('ix_fa_enrollment', 'fleet_accounts', ['enrollment_key'], unique=True)

    # --- RevenueAllocation ---
    op.create_table(
        'revenue_allocations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('allocation_id', sa.String(50), unique=True, nullable=False),
        sa.Column('deal_id', sa.String(20), sa.ForeignKey('deals.deal_id'), nullable=True),
        sa.Column('booking_id', sa.Integer(), sa.ForeignKey('bookings.id'), nullable=True),
        sa.Column('total_fee_usd', sa.Float(), nullable=False),
        sa.Column('node_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('node_tier', sa.String(20), nullable=True),
        sa.Column('node_share_pct', sa.Float(), server_default='0.0'),
        sa.Column('node_share_usd', sa.Float(), server_default='0.0'),
        sa.Column('referrer_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('referral_share_usd', sa.Float(), server_default='0.0'),
        sa.Column('infra_share_usd', sa.Float(), server_default='0.0'),
        sa.Column('platform_profit_usd', sa.Float(), server_default='0.0'),
        sa.Column('node_payout_status', sa.String(20), server_default='pending'),
        sa.Column('referrer_payout_status', sa.String(20), server_default='na'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_ra_allocation_id', 'revenue_allocations', ['allocation_id'], unique=True)
    op.create_index('ix_ra_deal_id', 'revenue_allocations', ['deal_id'])
    op.create_index('ix_ra_node_user', 'revenue_allocations', ['node_user_id'])
    op.create_index('ix_ra_payout_status', 'revenue_allocations', ['node_payout_status'])

    # --- CryptoConversion ---
    op.create_table(
        'crypto_conversions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('conversion_id', sa.String(50), unique=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('source_currency', sa.String(10), nullable=False),
        sa.Column('source_amount', sa.Float(), nullable=False),
        sa.Column('source_tx_hash', sa.String(200), nullable=True),
        sa.Column('target_currency', sa.String(10), server_default='XRP'),
        sa.Column('target_amount', sa.Float(), nullable=True),
        sa.Column('conversion_rate', sa.Float(), nullable=True),
        sa.Column('convenience_fee_pct', sa.Float(), server_default='0.025'),
        sa.Column('convenience_fee_usd', sa.Float(), server_default='0.0'),
        sa.Column('conversion_vehicle', sa.String(50), server_default="'coinbase'"),
        sa.Column('vehicle_tx_id', sa.String(200), nullable=True),
        sa.Column('status', sa.String(20), server_default='pending_deposit'),
        sa.Column('pre_funded', sa.Boolean(), server_default='0'),
        sa.Column('pre_fund_tx_hash', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_cc_conversion_id', 'crypto_conversions', ['conversion_id'], unique=True)
    op.create_index('ix_cc_user_id', 'crypto_conversions', ['user_id'])
    op.create_index('ix_cc_status', 'crypto_conversions', ['status'])


def downgrade():
    # Drop tables in reverse order
    op.drop_index('ix_cc_status', table_name='crypto_conversions')
    op.drop_index('ix_cc_user_id', table_name='crypto_conversions')
    op.drop_index('ix_cc_conversion_id', table_name='crypto_conversions')
    op.drop_table('crypto_conversions')

    op.drop_index('ix_ra_payout_status', table_name='revenue_allocations')
    op.drop_index('ix_ra_node_user', table_name='revenue_allocations')
    op.drop_index('ix_ra_deal_id', table_name='revenue_allocations')
    op.drop_index('ix_ra_allocation_id', table_name='revenue_allocations')
    op.drop_table('revenue_allocations')

    op.drop_index('ix_fa_enrollment', table_name='fleet_accounts')
    op.drop_index('ix_fa_commercial', table_name='fleet_accounts')
    op.drop_index('ix_fa_fleet_id', table_name='fleet_accounts')
    op.drop_table('fleet_accounts')

    op.drop_index('ix_nth_created', table_name='node_tier_history')
    op.drop_index('ix_nth_user_id', table_name='node_tier_history')
    op.drop_table('node_tier_history')

    op.drop_index('ix_nr_code', table_name='node_referrals')
    op.drop_index('ix_nr_referee', table_name='node_referrals')
    op.drop_index('ix_nr_referrer', table_name='node_referrals')
    op.drop_index('ix_nr_referral_id', table_name='node_referrals')
    op.drop_table('node_referrals')

    op.drop_index('ix_ncp_tier', table_name='node_consent_profiles')
    op.drop_index('ix_ncp_user_id', table_name='node_consent_profiles')
    op.drop_table('node_consent_profiles')

    # Drop HelperProfile addition
    op.drop_index('ix_helper_profiles_fleet_id', table_name='helper_profiles')
    op.drop_column('helper_profiles', 'fleet_id')

    # Drop User additions
    op.drop_index('ix_users_referral_code', table_name='users')
    op.drop_column('users', 'kyc_verified_at')
    op.drop_column('users', 'kyc_status')
    op.drop_column('users', 'active_node_referrals')
    op.drop_column('users', 'total_node_referrals')
    op.drop_column('users', 'node_referral_code')
    op.drop_column('users', 'xrpl_wallet_created_at')
    op.drop_column('users', 'xrpl_wallet_seed_encrypted')
    op.drop_column('users', 'xrpl_wallet_address')
