"""Add Phoenix AI tables: ai_conversations, ai_messages + User AI tier fields

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa


revision = 's9t0u1v2w3x4'
down_revision = 'r8s9t0u1v2w3'
branch_labels = None
depends_on = None


def upgrade():
    # AI Conversations table
    op.create_table(
        'ai_conversations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('conversation_id', sa.String(50), unique=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('title', sa.String(200), nullable=True),
        sa.Column('message_count', sa.Integer(), server_default='0'),
        sa.Column('total_credits_used', sa.Float(), server_default='0.0'),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('last_message_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_ai_conv_conv_id', 'ai_conversations', ['conversation_id'], unique=True)
    op.create_index('ix_ai_conv_user_id', 'ai_conversations', ['user_id'])
    op.create_index('ix_ai_conv_user_last', 'ai_conversations', ['user_id', 'last_message_at'])
    op.create_index('ix_ai_conv_created', 'ai_conversations', ['created_at'])

    # AI Messages table
    op.create_table(
        'ai_messages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('conversation_id', sa.String(50), sa.ForeignKey('ai_conversations.conversation_id'), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('tool_calls', sa.Text(), nullable=True),
        sa.Column('credits_used', sa.Float(), server_default='0.0'),
        sa.Column('model_used', sa.String(50), nullable=True),
        sa.Column('response_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_ai_msg_conv_id', 'ai_messages', ['conversation_id'])
    op.create_index('ix_ai_msg_conv_created', 'ai_messages', ['conversation_id', 'created_at'])

    # User AI tier columns
    op.add_column('users', sa.Column('ai_tier', sa.String(30), server_default='ai_free'))
    op.add_column('users', sa.Column('ai_queries_used_this_month', sa.Integer(), server_default='0'))
    op.add_column('users', sa.Column('ai_month_reset_date', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('users', 'ai_month_reset_date')
    op.drop_column('users', 'ai_queries_used_this_month')
    op.drop_column('users', 'ai_tier')

    op.drop_index('ix_ai_msg_conv_created', table_name='ai_messages')
    op.drop_index('ix_ai_msg_conv_id', table_name='ai_messages')
    op.drop_table('ai_messages')

    op.drop_index('ix_ai_conv_created', table_name='ai_conversations')
    op.drop_index('ix_ai_conv_user_last', table_name='ai_conversations')
    op.drop_index('ix_ai_conv_user_id', table_name='ai_conversations')
    op.drop_index('ix_ai_conv_conv_id', table_name='ai_conversations')
    op.drop_table('ai_conversations')
