"""Add Strategy Learner tables: strategy_observations, strategy_insights + User last_comparison_date

Revision ID: t0u1v2w3x4y5
Revises: s9t0u1v2w3x4
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa


revision = 't0u1v2w3x4y5'
down_revision = 's9t0u1v2w3x4'
branch_labels = None
depends_on = None


def upgrade():
    # Strategy Observations table
    op.create_table(
        'strategy_observations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('observation_id', sa.String(50), unique=True, nullable=False),
        sa.Column('source_type', sa.String(30), nullable=False),
        sa.Column('provider_key', sa.String(50), nullable=True),
        sa.Column('query_category', sa.String(50), nullable=False),
        sa.Column('query_structure', sa.Text(), nullable=True),
        sa.Column('source_sites', sa.Text(), nullable=True),
        sa.Column('strategies_detected', sa.Text(), nullable=True),
        sa.Column('result_count', sa.Integer(), server_default='0'),
        sa.Column('result_quality_score', sa.Float(), server_default='0.0'),
        sa.Column('markets_searched', sa.Text(), nullable=True),
        sa.Column('response_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_strat_obs_obs_id', 'strategy_observations', ['observation_id'], unique=True)
    op.create_index('ix_strat_obs_source', 'strategy_observations', ['source_type'])
    op.create_index('ix_strat_obs_category', 'strategy_observations', ['query_category'])
    op.create_index('ix_strat_obs_created', 'strategy_observations', ['created_at'])

    # Strategy Insights table
    op.create_table(
        'strategy_insights',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('insight_id', sa.String(50), unique=True, nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('insight_type', sa.String(50), nullable=False),
        sa.Column('insight_data', sa.Text(), nullable=False),
        sa.Column('confidence_score', sa.Float(), server_default='0.0'),
        sa.Column('observation_count', sa.Integer(), server_default='0'),
        sa.Column('effectiveness_score', sa.Float(), server_default='0.0'),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_strat_ins_ins_id', 'strategy_insights', ['insight_id'], unique=True)
    op.create_index('ix_strat_ins_category', 'strategy_insights', ['category'])
    op.create_index('ix_strat_ins_type', 'strategy_insights', ['insight_type'])
    op.create_index('ix_strat_ins_active', 'strategy_insights', ['is_active'])

    # User comparison quota column
    op.add_column('users', sa.Column('last_comparison_date', sa.Date(), nullable=True))


def downgrade():
    op.drop_column('users', 'last_comparison_date')

    op.drop_index('ix_strat_ins_active', table_name='strategy_insights')
    op.drop_index('ix_strat_ins_type', table_name='strategy_insights')
    op.drop_index('ix_strat_ins_category', table_name='strategy_insights')
    op.drop_index('ix_strat_ins_ins_id', table_name='strategy_insights')
    op.drop_table('strategy_insights')

    op.drop_index('ix_strat_obs_created', table_name='strategy_observations')
    op.drop_index('ix_strat_obs_category', table_name='strategy_observations')
    op.drop_index('ix_strat_obs_source', table_name='strategy_observations')
    op.drop_index('ix_strat_obs_obs_id', table_name='strategy_observations')
    op.drop_table('strategy_observations')
