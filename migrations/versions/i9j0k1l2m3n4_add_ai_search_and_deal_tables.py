"""Add AI search and private market deal tables

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-01-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'i9j0k1l2m3n4'
down_revision = 'h8i9j0k1l2m3'
branch_labels = None
depends_on = None


def upgrade():
    # AI Search Queries
    op.create_table(
        'ai_search_queries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('query_text', sa.Text(), nullable=False),
        sa.Column('market', sa.String(5), nullable=True),
        sa.Column('providers_queried', sa.Text(), nullable=True),
        sa.Column('best_provider', sa.String(50), nullable=True),
        sa.Column('best_model', sa.String(100), nullable=True),
        sa.Column('best_response', sa.Text(), nullable=True),
        sa.Column('all_responses', sa.Text(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), server_default='0'),
        sa.Column('response_time_ms', sa.Integer(), server_default='0'),
        sa.Column('credits_used', sa.Float(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        'ix_ai_search_user_created',
        'ai_search_queries',
        ['user_id', 'created_at'],
    )

    # User AI Providers (BYOAI)
    op.create_table(
        'user_ai_providers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('provider_key', sa.String(50), nullable=False),
        sa.Column('api_key_encrypted', sa.String(500), nullable=True),
        sa.Column('custom_model', sa.String(200), nullable=True),
        sa.Column('custom_endpoint', sa.String(500), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        'uq_user_ai_provider',
        'user_ai_providers',
        ['user_id', 'provider_key'],
        unique=True,
    )

    # Private Market Deals
    op.create_table(
        'private_market_deals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('buyer_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('seller_wallet', sa.String(100), nullable=False),
        sa.Column('item_description', sa.Text(), nullable=False),
        sa.Column('agreed_price_rlusd', sa.Float(), nullable=False),
        sa.Column('market', sa.String(5), nullable=True),
        sa.Column('deal_type', sa.String(20), server_default='goods'),
        sa.Column('escrow_tx_hash', sa.String(200), nullable=True),
        sa.Column('escrow_sequence', sa.Integer(), nullable=True),
        sa.Column('escrow_condition', sa.String(500), nullable=True),
        sa.Column('escrow_fulfillment', sa.String(500), nullable=True),
        sa.Column('escrow_fee_rlusd', sa.Float(), server_default='0'),
        sa.Column('ai_fair_value_estimate', sa.Float(), nullable=True),
        sa.Column('risk_score', sa.Integer(), server_default='5'),
        sa.Column('status', sa.String(20), server_default='draft', index=True),
        sa.Column('delivery_deadline', sa.DateTime(), nullable=True),
        sa.Column('dispute_window_end', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
    op.create_index(
        'ix_private_deals_buyer_status',
        'private_market_deals',
        ['buyer_id', 'status'],
    )


def downgrade():
    op.drop_index('ix_private_deals_buyer_status', table_name='private_market_deals')
    op.drop_table('private_market_deals')
    op.drop_index('uq_user_ai_provider', table_name='user_ai_providers')
    op.drop_table('user_ai_providers')
    op.drop_index('ix_ai_search_user_created', table_name='ai_search_queries')
    op.drop_table('ai_search_queries')
