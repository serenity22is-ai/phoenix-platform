"""Add airline intelligence tables

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-01-29

Adds:
- airline_clients: Airline SaaS subscribers
- airline_api_keys: API key auth for airline endpoints
- airline_reports: Generated intelligence reports
- airline_alerts: Competitive pricing/demand alerts
- ancillary_snapshots: Persistent bag/seat/upgrade pricing data
- competitor_pricing: Materialized daily competitive view
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    # -- airline_clients --
    op.create_table('airline_clients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.String(50), nullable=False),
        sa.Column('iata_code', sa.String(3), nullable=False),
        sa.Column('airline_name', sa.String(200), nullable=False),
        sa.Column('contact_email', sa.String(255), nullable=False),
        sa.Column('contact_name', sa.String(100), nullable=True),
        sa.Column('subscription_tier', sa.String(30), nullable=False, server_default='basic'),
        sa.Column('monthly_fee_usd', sa.Float(), nullable=False),
        sa.Column('routes_subscribed', sa.Text(), nullable=True),
        sa.Column('data_scopes', sa.Text(), nullable=True),
        sa.Column('competitor_airlines', sa.Text(), nullable=True),
        sa.Column('markets_subscribed', sa.Text(), nullable=True),
        sa.Column('contract_start', sa.Date(), nullable=True),
        sa.Column('contract_end', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('api_calls_this_month', sa.Integer(), server_default='0'),
        sa.Column('api_calls_total', sa.Integer(), server_default='0'),
        sa.Column('reports_generated', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('activated_at', sa.DateTime(), nullable=True),
        sa.Column('suspended_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_airline_clients_client_id', 'airline_clients', ['client_id'], unique=True)
    op.create_index('ix_airline_clients_iata_code', 'airline_clients', ['iata_code'])

    # -- airline_api_keys --
    op.create_table('airline_api_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('key_prefix', sa.String(8), nullable=False),
        sa.Column('key_hash', sa.String(128), nullable=False),
        sa.Column('label', sa.String(100), nullable=True),
        sa.Column('scopes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('total_requests', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['airline_clients.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_airline_api_keys_client_id', 'airline_api_keys', ['client_id'])

    # -- airline_reports --
    op.create_table('airline_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('report_id', sa.String(50), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('report_type', sa.String(30), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('report_data', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('routes_analyzed', sa.Integer(), nullable=True),
        sa.Column('markets_analyzed', sa.Integer(), nullable=True),
        sa.Column('data_points', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), server_default='generating'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('generated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['airline_clients.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_airline_reports_report_id', 'airline_reports', ['report_id'], unique=True)
    op.create_index('ix_airline_reports_client_id', 'airline_reports', ['client_id'])
    op.create_index('ix_airline_reports_report_type', 'airline_reports', ['report_type'])
    op.create_index('ix_airline_reports_status', 'airline_reports', ['status'])
    op.create_index('ix_airline_reports_generated_at', 'airline_reports', ['generated_at'])

    # -- airline_alerts --
    op.create_table('airline_alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('alert_id', sa.String(50), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('alert_type', sa.String(30), nullable=False),
        sa.Column('route_pattern', sa.String(50), nullable=True),
        sa.Column('competitor_iata', sa.String(3), nullable=True),
        sa.Column('market', sa.String(2), nullable=True),
        sa.Column('price_change_pct', sa.Float(), nullable=True),
        sa.Column('price_change_usd', sa.Float(), nullable=True),
        sa.Column('demand_change_pct', sa.Float(), nullable=True),
        sa.Column('notify_email', sa.Boolean(), server_default='true'),
        sa.Column('notify_webhook', sa.String(500), nullable=True),
        sa.Column('notify_sse', sa.Boolean(), server_default='true'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('last_triggered', sa.DateTime(), nullable=True),
        sa.Column('trigger_count', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['airline_clients.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_airline_alerts_alert_id', 'airline_alerts', ['alert_id'], unique=True)
    op.create_index('ix_airline_alerts_client_id', 'airline_alerts', ['client_id'])
    op.create_index('ix_airline_alerts_alert_type', 'airline_alerts', ['alert_type'])

    # -- ancillary_snapshots --
    op.create_table('ancillary_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('origin', sa.String(10), nullable=False),
        sa.Column('destination', sa.String(10), nullable=False),
        sa.Column('departure_date', sa.Date(), nullable=False),
        sa.Column('market', sa.String(2), nullable=False),
        sa.Column('airline', sa.String(50), nullable=True),
        sa.Column('checked_bag_1_price_local', sa.Float(), nullable=True),
        sa.Column('checked_bag_1_price_usd', sa.Float(), nullable=True),
        sa.Column('checked_bag_2_price_local', sa.Float(), nullable=True),
        sa.Column('checked_bag_2_price_usd', sa.Float(), nullable=True),
        sa.Column('carry_on_included', sa.Boolean(), nullable=True),
        sa.Column('checked_bag_weight_kg', sa.Integer(), nullable=True),
        sa.Column('checked_bag_count_included', sa.Integer(), nullable=True),
        sa.Column('seat_selection_min_price_local', sa.Float(), nullable=True),
        sa.Column('seat_selection_max_price_local', sa.Float(), nullable=True),
        sa.Column('seat_selection_min_price_usd', sa.Float(), nullable=True),
        sa.Column('seat_selection_max_price_usd', sa.Float(), nullable=True),
        sa.Column('upgrade_to_premium_economy_usd', sa.Float(), nullable=True),
        sa.Column('upgrade_to_business_usd', sa.Float(), nullable=True),
        sa.Column('local_currency', sa.String(3), nullable=True),
        sa.Column('source', sa.String(20), nullable=True),
        sa.Column('data_quality', sa.String(20), nullable=True),
        sa.Column('recorded_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ancillary_route_date_market', 'ancillary_snapshots',
                    ['origin', 'destination', 'departure_date', 'market'])
    op.create_index('ix_ancillary_snapshots_airline', 'ancillary_snapshots', ['airline'])
    op.create_index('ix_ancillary_snapshots_recorded_at', 'ancillary_snapshots', ['recorded_at'])

    # -- competitor_pricing --
    op.create_table('competitor_pricing',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('origin', sa.String(10), nullable=False),
        sa.Column('destination', sa.String(10), nullable=False),
        sa.Column('market', sa.String(2), nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('airline_iata', sa.String(3), nullable=False),
        sa.Column('avg_price_usd', sa.Float(), nullable=False),
        sa.Column('min_price_usd', sa.Float(), nullable=True),
        sa.Column('max_price_usd', sa.Float(), nullable=True),
        sa.Column('sample_count', sa.Integer(), nullable=True),
        sa.Column('market_rank', sa.Integer(), nullable=True),
        sa.Column('price_vs_market_avg_pct', sa.Float(), nullable=True),
        sa.Column('calculated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_competitor_route_date_airline', 'competitor_pricing',
                    ['origin', 'destination', 'snapshot_date', 'airline_iata'])
    op.create_index('ix_competitor_pricing_calculated_at', 'competitor_pricing', ['calculated_at'])


def downgrade():
    op.drop_index('ix_competitor_pricing_calculated_at', 'competitor_pricing')
    op.drop_index('ix_competitor_route_date_airline', 'competitor_pricing')
    op.drop_table('competitor_pricing')

    op.drop_index('ix_ancillary_snapshots_recorded_at', 'ancillary_snapshots')
    op.drop_index('ix_ancillary_snapshots_airline', 'ancillary_snapshots')
    op.drop_index('ix_ancillary_route_date_market', 'ancillary_snapshots')
    op.drop_table('ancillary_snapshots')

    op.drop_index('ix_airline_alerts_alert_type', 'airline_alerts')
    op.drop_index('ix_airline_alerts_client_id', 'airline_alerts')
    op.drop_index('ix_airline_alerts_alert_id', 'airline_alerts')
    op.drop_table('airline_alerts')

    op.drop_index('ix_airline_reports_generated_at', 'airline_reports')
    op.drop_index('ix_airline_reports_status', 'airline_reports')
    op.drop_index('ix_airline_reports_report_type', 'airline_reports')
    op.drop_index('ix_airline_reports_client_id', 'airline_reports')
    op.drop_index('ix_airline_reports_report_id', 'airline_reports')
    op.drop_table('airline_reports')

    op.drop_index('ix_airline_api_keys_client_id', 'airline_api_keys')
    op.drop_table('airline_api_keys')

    op.drop_index('ix_airline_clients_iata_code', 'airline_clients')
    op.drop_index('ix_airline_clients_client_id', 'airline_clients')
    op.drop_table('airline_clients')
