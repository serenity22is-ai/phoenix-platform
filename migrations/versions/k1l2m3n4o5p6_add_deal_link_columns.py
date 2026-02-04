"""Add deal link columns to private_market_deals for P2P shareable links

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa


revision = 'k1l2m3n4o5p6'
down_revision = 'j0k1l2m3n4o5'
branch_labels = None
depends_on = None


def upgrade():
    # Make seller_wallet nullable (seller provides wallet on link acceptance)
    op.alter_column('private_market_deals', 'seller_wallet',
                    existing_type=sa.String(100),
                    nullable=True)

    # Add link columns
    op.add_column('private_market_deals', sa.Column('link_token', sa.String(64), nullable=True))
    op.add_column('private_market_deals', sa.Column('seller_email', sa.String(256), nullable=True))
    op.add_column('private_market_deals', sa.Column('seller_name', sa.String(200), nullable=True))
    op.add_column('private_market_deals', sa.Column('link_expires_at', sa.DateTime(), nullable=True))
    op.add_column('private_market_deals', sa.Column('seller_accepted_at', sa.DateTime(), nullable=True))
    op.add_column('private_market_deals', sa.Column('link_viewed_at', sa.DateTime(), nullable=True))

    # Unique index on link_token for fast public lookups
    op.create_index('ix_private_deals_link_token', 'private_market_deals', ['link_token'], unique=True)


def downgrade():
    op.drop_index('ix_private_deals_link_token', table_name='private_market_deals')
    op.drop_column('private_market_deals', 'link_viewed_at')
    op.drop_column('private_market_deals', 'seller_accepted_at')
    op.drop_column('private_market_deals', 'link_expires_at')
    op.drop_column('private_market_deals', 'seller_name')
    op.drop_column('private_market_deals', 'seller_email')
    op.drop_column('private_market_deals', 'link_token')

    op.alter_column('private_market_deals', 'seller_wallet',
                    existing_type=sa.String(100),
                    nullable=False)
