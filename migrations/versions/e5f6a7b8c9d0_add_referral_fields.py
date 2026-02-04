"""Add referral fields to users and commercial_accounts

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-01-29

Adds:
- commercial_accounts.referral_code (unique, indexed)
- commercial_accounts.total_referred_users
- commercial_accounts.total_referred_helpers
- users.referred_by_account_id (FK → commercial_accounts.id)
- users.referral_code_used
- users.is_helper_node
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    # Commercial accounts — referral code and counters
    op.add_column('commercial_accounts',
                  sa.Column('referral_code', sa.String(20), nullable=True))
    op.add_column('commercial_accounts',
                  sa.Column('total_referred_users', sa.Integer(), server_default='0'))
    op.add_column('commercial_accounts',
                  sa.Column('total_referred_helpers', sa.Integer(), server_default='0'))
    op.create_unique_constraint('uq_commercial_accounts_referral_code',
                                'commercial_accounts', ['referral_code'])
    op.create_index('ix_commercial_accounts_referral_code',
                    'commercial_accounts', ['referral_code'])

    # Users — referral attribution
    op.add_column('users',
                  sa.Column('referred_by_account_id', sa.Integer(), nullable=True))
    op.add_column('users',
                  sa.Column('referral_code_used', sa.String(20), nullable=True))
    op.add_column('users',
                  sa.Column('is_helper_node', sa.Boolean(), server_default='false'))
    op.create_foreign_key('fk_users_referred_by_account',
                          'users', 'commercial_accounts',
                          ['referred_by_account_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_users_referred_by_account', 'users', type_='foreignkey')
    op.drop_column('users', 'is_helper_node')
    op.drop_column('users', 'referral_code_used')
    op.drop_column('users', 'referred_by_account_id')

    op.drop_index('ix_commercial_accounts_referral_code', 'commercial_accounts')
    op.drop_constraint('uq_commercial_accounts_referral_code', 'commercial_accounts',
                       type_='unique')
    op.drop_column('commercial_accounts', 'total_referred_helpers')
    op.drop_column('commercial_accounts', 'total_referred_users')
    op.drop_column('commercial_accounts', 'referral_code')
