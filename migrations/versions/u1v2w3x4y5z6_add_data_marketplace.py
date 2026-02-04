"""Add Data Marketplace tables: data_products, data_subscriptions, data_exports, data_webhooks, data_usage_records + commercial_accounts columns

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa


revision = 'u1v2w3x4y5z6'
down_revision = 't0u1v2w3x4y5'
branch_labels = None
depends_on = None


def upgrade():
    # Data Products table
    op.create_table(
        'data_products',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('product_id', sa.String(80), unique=True, nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('data_source_config', sa.Text(), nullable=False),
        sa.Column('delivery_formats', sa.Text(), nullable=False),
        sa.Column('pricing_model', sa.String(30), nullable=False),
        sa.Column('credit_cost_per_query', sa.Float(), server_default='1.0'),
        sa.Column('min_tier', sa.String(30), server_default='data_free'),
        sa.Column('sample_limit', sa.Integer(), server_default='10'),
        sa.Column('available_fields', sa.Text(), nullable=True),
        sa.Column('supported_filters', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_data_prod_product_id', 'data_products', ['product_id'], unique=True)
    op.create_index('ix_data_prod_category', 'data_products', ['category'])

    # Data Subscriptions table
    op.create_table(
        'data_subscriptions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('subscription_id', sa.String(50), unique=True, nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('commercial_accounts.id'), nullable=False),
        sa.Column('tier', sa.String(30), nullable=False, server_default='data_free'),
        sa.Column('selected_products', sa.Text(), nullable=True),
        sa.Column('addons', sa.Text(), nullable=True),
        sa.Column('queries_used_this_period', sa.Integer(), server_default='0'),
        sa.Column('period_start', sa.DateTime(), nullable=True),
        sa.Column('period_end', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(20), server_default='active'),
        sa.Column('monthly_price_usd', sa.Float(), server_default='0.0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_data_sub_sub_id', 'data_subscriptions', ['subscription_id'], unique=True)
    op.create_index('ix_data_sub_account_status', 'data_subscriptions', ['account_id', 'status'])

    # Data Exports table
    op.create_table(
        'data_exports',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('export_id', sa.String(50), unique=True, nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('commercial_accounts.id'), nullable=False),
        sa.Column('product_id', sa.String(80), nullable=False),
        sa.Column('format', sa.String(10), nullable=False, server_default='csv'),
        sa.Column('filters', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('total_records', sa.Integer(), nullable=True),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('download_url', sa.String(500), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_data_exp_export_id', 'data_exports', ['export_id'], unique=True)
    op.create_index('ix_data_exp_account', 'data_exports', ['account_id'])
    op.create_index('ix_data_exp_status', 'data_exports', ['status'])

    # Data Webhooks table
    op.create_table(
        'data_webhooks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('webhook_id', sa.String(50), unique=True, nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('commercial_accounts.id'), nullable=False),
        sa.Column('product_id', sa.String(80), nullable=False),
        sa.Column('callback_url', sa.String(500), nullable=False),
        sa.Column('secret', sa.String(128), nullable=False),
        sa.Column('filters', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('consecutive_failures', sa.Integer(), server_default='0'),
        sa.Column('last_delivery_at', sa.DateTime(), nullable=True),
        sa.Column('last_delivery_status', sa.Integer(), nullable=True),
        sa.Column('total_deliveries', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_data_wh_webhook_id', 'data_webhooks', ['webhook_id'], unique=True)
    op.create_index('ix_data_wh_account', 'data_webhooks', ['account_id'])

    # Data Usage Records table
    op.create_table(
        'data_usage_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('commercial_accounts.id'), nullable=False),
        sa.Column('product_id', sa.String(80), nullable=False),
        sa.Column('query_type', sa.String(20), nullable=False),
        sa.Column('records_returned', sa.Integer(), server_default='0'),
        sa.Column('credits_consumed', sa.Float(), server_default='0.0'),
        sa.Column('filters_used', sa.Text(), nullable=True),
        sa.Column('response_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_data_usage_account_product', 'data_usage_records', ['account_id', 'product_id'])
    op.create_index('ix_data_usage_created', 'data_usage_records', ['created_at'])

    # Commercial Accounts columns
    op.add_column('commercial_accounts', sa.Column('data_marketplace_tier', sa.String(30), server_default='data_free'))
    op.add_column('commercial_accounts', sa.Column('data_queries_used_this_month', sa.Integer(), server_default='0'))
    op.add_column('commercial_accounts', sa.Column('data_month_reset_date', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('commercial_accounts', 'data_month_reset_date')
    op.drop_column('commercial_accounts', 'data_queries_used_this_month')
    op.drop_column('commercial_accounts', 'data_marketplace_tier')

    op.drop_index('ix_data_usage_created', table_name='data_usage_records')
    op.drop_index('ix_data_usage_account_product', table_name='data_usage_records')
    op.drop_table('data_usage_records')

    op.drop_index('ix_data_wh_account', table_name='data_webhooks')
    op.drop_index('ix_data_wh_webhook_id', table_name='data_webhooks')
    op.drop_table('data_webhooks')

    op.drop_index('ix_data_exp_status', table_name='data_exports')
    op.drop_index('ix_data_exp_account', table_name='data_exports')
    op.drop_index('ix_data_exp_export_id', table_name='data_exports')
    op.drop_table('data_exports')

    op.drop_index('ix_data_sub_account_status', table_name='data_subscriptions')
    op.drop_index('ix_data_sub_sub_id', table_name='data_subscriptions')
    op.drop_table('data_subscriptions')

    op.drop_index('ix_data_prod_category', table_name='data_products')
    op.drop_index('ix_data_prod_product_id', table_name='data_products')
    op.drop_table('data_products')
