"""Add SERP API tables for residential proxy SERP extraction service

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa


revision = 'm3n4o5p6q7r8'
down_revision = 'l2m3n4o5p6q7'
branch_labels = None
depends_on = None


def upgrade():
    # SERP API query tracking
    op.create_table(
        'serp_api_queries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('commercial_accounts.id'), nullable=False),
        sa.Column('query_id', sa.String(50), unique=True, nullable=False),
        sa.Column('engine', sa.String(30), nullable=False),
        sa.Column('market', sa.String(5), nullable=False),
        sa.Column('query_text', sa.Text(), nullable=False),
        sa.Column('options', sa.Text(), nullable=True),
        sa.Column('credits_used', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('node_id', sa.String(50), nullable=True),
        sa.Column('callback_url', sa.String(500), nullable=True),
        sa.Column('callback_status', sa.String(20), nullable=True),
        sa.Column('response_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_serp_queries_query_id', 'serp_api_queries', ['query_id'], unique=True)
    op.create_index('ix_serp_queries_account_status', 'serp_api_queries', ['account_id', 'status'])
    op.create_index('ix_serp_queries_created', 'serp_api_queries', ['created_at'])

    # SERP API daily usage summaries
    op.create_table(
        'serp_api_usage_summaries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('commercial_accounts.id'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('total_queries', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_credits', sa.Float(), nullable=False, server_default='0'),
        sa.Column('successful_queries', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_queries', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_response_time_ms', sa.Integer(), nullable=True),
        sa.Column('engines_used', sa.Text(), nullable=True),
        sa.Column('markets_used', sa.Text(), nullable=True),
    )
    op.create_index('ix_serp_usage_account_date', 'serp_api_usage_summaries',
                     ['account_id', 'date'], unique=True)

    # Add SERP columns to commercial_accounts
    op.add_column('commercial_accounts', sa.Column('serp_tier', sa.String(20), server_default='serp_free'))
    op.add_column('commercial_accounts', sa.Column('serp_monthly_credits', sa.Integer(), server_default='100'))
    op.add_column('commercial_accounts', sa.Column('serp_credits_used_this_month', sa.Float(), server_default='0'))
    op.add_column('commercial_accounts', sa.Column('serp_month_reset_date', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('commercial_accounts', 'serp_month_reset_date')
    op.drop_column('commercial_accounts', 'serp_credits_used_this_month')
    op.drop_column('commercial_accounts', 'serp_monthly_credits')
    op.drop_column('commercial_accounts', 'serp_tier')

    op.drop_index('ix_serp_usage_account_date', table_name='serp_api_usage_summaries')
    op.drop_table('serp_api_usage_summaries')

    op.drop_index('ix_serp_queries_created', table_name='serp_api_queries')
    op.drop_index('ix_serp_queries_account_status', table_name='serp_api_queries')
    op.drop_index('ix_serp_queries_query_id', table_name='serp_api_queries')
    op.drop_table('serp_api_queries')
