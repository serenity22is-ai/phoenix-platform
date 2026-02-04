"""Add proxy portal tables

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-01-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'h8i9j0k1l2m3'
down_revision = 'g7h8i9j0k1l2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'proxy_sessions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('country_code', sa.String(5), nullable=False),
        sa.Column('target_site', sa.String(200), nullable=True),
        sa.Column('proxy_host', sa.String(200), nullable=False),
        sa.Column('proxy_port', sa.String(10), nullable=False),
        sa.Column('proxy_username', sa.String(200), nullable=False),
        sa.Column('proxy_password', sa.String(200), nullable=False),
        sa.Column('protocol', sa.String(10), server_default='socks5'),
        sa.Column('status', sa.String(20), server_default='active', index=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
    )
    op.create_index(
        'ix_proxy_sessions_user_status',
        'proxy_sessions',
        ['user_id', 'status'],
    )


def downgrade():
    op.drop_index('ix_proxy_sessions_user_status', table_name='proxy_sessions')
    op.drop_table('proxy_sessions')
