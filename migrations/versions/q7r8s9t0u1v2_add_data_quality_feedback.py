"""Add data_quality_feedback table (Build #69)

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa


revision = 'q7r8s9t0u1v2'
down_revision = 'p6q7r8s9t0u1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'data_quality_feedback',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('feedback_id', sa.String(50), unique=True, nullable=False),
        sa.Column('event_id', sa.String(50), sa.ForeignKey('browsing_events.event_id'), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('node_id', sa.String(50), nullable=True),
        sa.Column('rating', sa.String(10), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_dqf_feedback_id', 'data_quality_feedback', ['feedback_id'], unique=True)
    op.create_index('ix_dqf_event_id', 'data_quality_feedback', ['event_id'])
    op.create_index('ix_dqf_account_id', 'data_quality_feedback', ['account_id'])
    op.create_index('ix_dqf_node_id', 'data_quality_feedback', ['node_id'])
    op.create_index('ix_dqf_node_rating', 'data_quality_feedback', ['node_id', 'rating'])


def downgrade():
    op.drop_index('ix_dqf_node_rating', table_name='data_quality_feedback')
    op.drop_index('ix_dqf_node_id', table_name='data_quality_feedback')
    op.drop_index('ix_dqf_account_id', table_name='data_quality_feedback')
    op.drop_index('ix_dqf_event_id', table_name='data_quality_feedback')
    op.drop_index('ix_dqf_feedback_id', table_name='data_quality_feedback')
    op.drop_table('data_quality_feedback')
