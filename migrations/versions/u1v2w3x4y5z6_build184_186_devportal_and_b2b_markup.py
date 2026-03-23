"""Build #184-186: Dev Portal tables + B2B consumer markup fields

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa

revision = 'u1v2w3x4y5z6'
down_revision = 't0u1v2w3x4y5'
branch_labels = None
depends_on = None


def upgrade():
    # --- Build #184: Dev Portal tables ---

    op.create_table('dev_portal_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.String(64), unique=True, nullable=False),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('company', sa.String(255), nullable=True),
        sa.Column('mystes_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('apai_subscriber', sa.Boolean(), default=False),
        sa.Column('apai_template_config', sa.Text(), nullable=True),
        sa.Column('billing_tier', sa.String(20), default='payg'),
        sa.Column('stripe_customer_id', sa.String(255), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(255), nullable=True),
        sa.Column('subscription_status', sa.String(50), nullable=True),
        sa.Column('queries_used_this_period', sa.Integer(), default=0),
        sa.Column('queries_included', sa.Integer(), default=0),
        sa.Column('period_start', sa.DateTime(), nullable=True),
        sa.Column('period_end', sa.DateTime(), nullable=True),
        sa.Column('total_queries_lifetime', sa.Integer(), default=0),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('is_verified', sa.Boolean(), default=False),
        sa.Column('verification_token', sa.String(255), nullable=True),
        sa.Column('last_login', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_dev_portal_accounts_email', 'dev_portal_accounts', ['email'])

    op.create_table('dev_portal_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('dev_portal_accounts.id'), nullable=False),
        sa.Column('key_prefix', sa.String(20), nullable=False),
        sa.Column('key_hash', sa.String(255), nullable=False),
        sa.Column('label', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('total_requests', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('dev_portal_conversations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('conversation_id', sa.String(64), unique=True, nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('dev_portal_accounts.id'), nullable=False),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('message_count', sa.Integer(), default=0),
        sa.Column('total_tokens_used', sa.Integer(), default=0),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('dev_portal_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('conversation_id', sa.Integer(), sa.ForeignKey('dev_portal_conversations.id'), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('tokens_used', sa.Integer(), default=0),
        sa.Column('model_used', sa.String(50), nullable=True),
        sa.Column('response_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- Build #185: B2B consumer markup fields ---

    with op.batch_alter_table('commercial_accounts') as batch_op:
        batch_op.add_column(sa.Column('consumer_markup_percent', sa.Float(), server_default='0.0'))
        batch_op.add_column(sa.Column('consumer_markup_flat_usd', sa.Float(), server_default='0.0'))
        batch_op.add_column(sa.Column('referral_link_enabled', sa.Boolean(), server_default='1'))


def downgrade():
    with op.batch_alter_table('commercial_accounts') as batch_op:
        batch_op.drop_column('referral_link_enabled')
        batch_op.drop_column('consumer_markup_flat_usd')
        batch_op.drop_column('consumer_markup_percent')

    op.drop_table('dev_portal_messages')
    op.drop_table('dev_portal_conversations')
    op.drop_table('dev_portal_keys')
    op.drop_index('ix_dev_portal_accounts_email', 'dev_portal_accounts')
    op.drop_table('dev_portal_accounts')
