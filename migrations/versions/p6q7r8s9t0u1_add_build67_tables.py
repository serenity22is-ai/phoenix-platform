"""Add Build #67 tables: browsing_events + helper_profile extensions

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa


revision = 'p6q7r8s9t0u1'
down_revision = 'o5p6q7r8s9t0'
branch_labels = None
depends_on = None


def upgrade():
    # Browsing Events table
    op.create_table(
        'browsing_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('event_id', sa.String(50), unique=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('node_id', sa.String(50), nullable=True),
        sa.Column('session_id', sa.String(50), nullable=True),
        sa.Column('event_type', sa.String(30), nullable=False),
        sa.Column('url', sa.String(2000), nullable=True),
        sa.Column('domain', sa.String(200), nullable=True),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('event_data', sa.Text(), nullable=True),
        sa.Column('is_processed', sa.Boolean(), server_default='0'),
        sa.Column('processing_result', sa.String(20), nullable=True),
        sa.Column('commercial_value_usd', sa.Float(), server_default='0.0'),
        sa.Column('data_category', sa.String(50), nullable=True),
        sa.Column('quality_score', sa.Integer(), server_default='50'),
        sa.Column('captured_at', sa.DateTime(), nullable=True),
        sa.Column('ingested_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_browsing_evt_event_id', 'browsing_events', ['event_id'], unique=True)
    op.create_index('ix_browsing_evt_node_id', 'browsing_events', ['node_id'])
    op.create_index('ix_browsing_evt_domain', 'browsing_events', ['domain'])
    op.create_index('ix_browsing_evt_user_type', 'browsing_events', ['user_id', 'event_type'])
    op.create_index('ix_browsing_evt_captured', 'browsing_events', ['captured_at'])
    op.create_index('ix_browsing_evt_processed', 'browsing_events', ['is_processed', 'ingested_at'])

    # Add columns to helper_profiles
    op.add_column('helper_profiles', sa.Column('helper_token', sa.String(100), nullable=True))
    op.add_column('helper_profiles', sa.Column('node_id', sa.String(50), nullable=True))
    op.add_column('helper_profiles', sa.Column('last_seen', sa.DateTime(), nullable=True))
    op.create_index('ix_helper_profiles_token', 'helper_profiles', ['helper_token'], unique=True)


def downgrade():
    op.drop_index('ix_helper_profiles_token', table_name='helper_profiles')
    op.drop_column('helper_profiles', 'last_seen')
    op.drop_column('helper_profiles', 'node_id')
    op.drop_column('helper_profiles', 'helper_token')

    op.drop_index('ix_browsing_evt_processed', table_name='browsing_events')
    op.drop_index('ix_browsing_evt_captured', table_name='browsing_events')
    op.drop_index('ix_browsing_evt_user_type', table_name='browsing_events')
    op.drop_index('ix_browsing_evt_domain', table_name='browsing_events')
    op.drop_index('ix_browsing_evt_node_id', table_name='browsing_events')
    op.drop_index('ix_browsing_evt_event_id', table_name='browsing_events')
    op.drop_table('browsing_events')
