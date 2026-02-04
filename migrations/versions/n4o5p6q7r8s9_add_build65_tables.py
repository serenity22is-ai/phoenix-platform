"""Add Build #65 tables: node_data_extractions + ad_intelligence_records

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa


revision = 'n4o5p6q7r8s9'
down_revision = 'm3n4o5p6q7r8'
branch_labels = None
depends_on = None


def upgrade():
    # Node Data Extraction tracking
    op.create_table(
        'node_data_extractions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('node_sessions.id'), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('task_id', sa.String(50), nullable=False),
        sa.Column('task_type', sa.String(50), nullable=False),
        sa.Column('data_category', sa.String(50), nullable=False),
        sa.Column('records_extracted', sa.Integer(), server_default='0'),
        sa.Column('data_points', sa.Integer(), server_default='0'),
        sa.Column('data_size_bytes', sa.Integer(), server_default='0'),
        sa.Column('commercial_value_usd', sa.Float(), server_default='0.0'),
        sa.Column('payout_multiplier', sa.Float(), server_default='1.0'),
        sa.Column('payout_earned_rlusd', sa.Float(), server_default='0.0'),
        sa.Column('quality_score', sa.Integer(), server_default='50'),
        sa.Column('extraction_metadata', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_node_data_ext_session', 'node_data_extractions', ['session_id'])
    op.create_index('ix_node_data_ext_user', 'node_data_extractions', ['user_id'])
    op.create_index('ix_node_data_ext_task', 'node_data_extractions', ['task_id'])
    op.create_index('ix_node_data_ext_task_type', 'node_data_extractions', ['task_type'])
    op.create_index('ix_node_data_ext_category', 'node_data_extractions', ['data_category'])
    op.create_index('ix_node_data_ext_user_category', 'node_data_extractions', ['user_id', 'data_category'])
    op.create_index('ix_node_data_ext_created', 'node_data_extractions', ['created_at'])

    # Ad Intelligence Records
    op.create_table(
        'ad_intelligence_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('record_id', sa.String(50), unique=True, nullable=False),
        sa.Column('task_id', sa.String(50), nullable=False),
        sa.Column('node_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('market', sa.String(5), nullable=False),
        sa.Column('source_url', sa.String(500), nullable=True),
        sa.Column('advertiser', sa.String(200), nullable=True),
        sa.Column('ad_network', sa.String(100), nullable=True),
        sa.Column('ad_format', sa.String(50), nullable=True),
        sa.Column('ad_position', sa.String(50), nullable=True),
        sa.Column('ad_text', sa.Text(), nullable=True),
        sa.Column('ad_destination_url', sa.String(500), nullable=True),
        sa.Column('ad_image_hash', sa.String(64), nullable=True),
        sa.Column('estimated_bid_usd', sa.Float(), nullable=True),
        sa.Column('targeting_keywords', sa.Text(), nullable=True),
        sa.Column('targeting_demographics', sa.Text(), nullable=True),
        sa.Column('targeting_geo', sa.String(50), nullable=True),
        sa.Column('vertical', sa.String(50), nullable=True),
        sa.Column('sub_vertical', sa.String(50), nullable=True),
        sa.Column('commercial_value_usd', sa.Float(), server_default='0.0'),
        sa.Column('is_sold', sa.Boolean(), server_default='0'),
        sa.Column('confidence_score', sa.Float(), server_default='0.5'),
        sa.Column('observed_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_ad_intel_record_id', 'ad_intelligence_records', ['record_id'], unique=True)
    op.create_index('ix_ad_intel_task_id', 'ad_intelligence_records', ['task_id'])
    op.create_index('ix_ad_intel_node_user', 'ad_intelligence_records', ['node_user_id'])
    op.create_index('ix_ad_intel_market', 'ad_intelligence_records', ['market'])
    op.create_index('ix_ad_intel_advertiser', 'ad_intelligence_records', ['advertiser'])
    op.create_index('ix_ad_intel_ad_network', 'ad_intelligence_records', ['ad_network'])
    op.create_index('ix_ad_intel_vertical', 'ad_intelligence_records', ['vertical'])
    op.create_index('ix_ad_intel_observed', 'ad_intelligence_records', ['observed_at'])
    op.create_index('ix_ad_intel_advertiser_market', 'ad_intelligence_records', ['advertiser', 'market'])
    op.create_index('ix_ad_intel_vertical_observed', 'ad_intelligence_records', ['vertical', 'observed_at'])
    op.create_index('ix_ad_intel_network_observed', 'ad_intelligence_records', ['ad_network', 'observed_at'])


def downgrade():
    op.drop_index('ix_ad_intel_network_observed', table_name='ad_intelligence_records')
    op.drop_index('ix_ad_intel_vertical_observed', table_name='ad_intelligence_records')
    op.drop_index('ix_ad_intel_advertiser_market', table_name='ad_intelligence_records')
    op.drop_index('ix_ad_intel_observed', table_name='ad_intelligence_records')
    op.drop_index('ix_ad_intel_vertical', table_name='ad_intelligence_records')
    op.drop_index('ix_ad_intel_ad_network', table_name='ad_intelligence_records')
    op.drop_index('ix_ad_intel_advertiser', table_name='ad_intelligence_records')
    op.drop_index('ix_ad_intel_market', table_name='ad_intelligence_records')
    op.drop_index('ix_ad_intel_node_user', table_name='ad_intelligence_records')
    op.drop_index('ix_ad_intel_task_id', table_name='ad_intelligence_records')
    op.drop_index('ix_ad_intel_record_id', table_name='ad_intelligence_records')
    op.drop_table('ad_intelligence_records')

    op.drop_index('ix_node_data_ext_created', table_name='node_data_extractions')
    op.drop_index('ix_node_data_ext_user_category', table_name='node_data_extractions')
    op.drop_index('ix_node_data_ext_category', table_name='node_data_extractions')
    op.drop_index('ix_node_data_ext_task_type', table_name='node_data_extractions')
    op.drop_index('ix_node_data_ext_task', table_name='node_data_extractions')
    op.drop_index('ix_node_data_ext_user', table_name='node_data_extractions')
    op.drop_index('ix_node_data_ext_session', table_name='node_data_extractions')
    op.drop_table('node_data_extractions')
