"""Add search history and price tracking tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-01-29 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # --- search_history ---
    op.create_table(
        'search_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('origin', sa.String(length=10), nullable=False),
        sa.Column('destination', sa.String(length=10), nullable=False),
        sa.Column('departure_date', sa.Date(), nullable=False),
        sa.Column('return_date', sa.Date(), nullable=True),
        sa.Column('cabin_class', sa.String(length=20), server_default='economy', nullable=True),
        sa.Column('results_count', sa.Integer(), server_default='0', nullable=True),
        sa.Column('best_price_usd', sa.Float(), nullable=True),
        sa.Column('best_market', sa.String(length=2), nullable=True),
        sa.Column('us_price_usd', sa.Float(), nullable=True),
        sa.Column('max_savings_usd', sa.Float(), nullable=True),
        sa.Column('max_savings_percent', sa.Float(), nullable=True),
        sa.Column('search_method', sa.String(length=20), nullable=True),
        sa.Column('search_duration_ms', sa.Integer(), nullable=True),
        sa.Column('markets_searched', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_search_history_user_id', 'search_history', ['user_id'])
    op.create_index('ix_search_history_origin', 'search_history', ['origin'])
    op.create_index('ix_search_history_destination', 'search_history', ['destination'])

    # --- price_history ---
    op.create_table(
        'price_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('origin', sa.String(length=10), nullable=False),
        sa.Column('destination', sa.String(length=10), nullable=False),
        sa.Column('departure_date', sa.Date(), nullable=False),
        sa.Column('cabin_class', sa.String(length=20), server_default='economy', nullable=True),
        sa.Column('market', sa.String(length=2), nullable=False),
        sa.Column('price_usd', sa.Float(), nullable=False),
        sa.Column('price_local', sa.Float(), nullable=True),
        sa.Column('local_currency', sa.String(length=3), nullable=True),
        sa.Column('airline', sa.String(length=50), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=True),
        sa.Column('recorded_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_price_history_origin', 'price_history', ['origin'])
    op.create_index('ix_price_history_destination', 'price_history', ['destination'])
    op.create_index('ix_price_history_departure_date', 'price_history', ['departure_date'])
    op.create_index('ix_price_history_market', 'price_history', ['market'])
    op.create_index('ix_price_history_recorded_at', 'price_history', ['recorded_at'])
    op.create_index(
        'ix_price_history_route_date',
        'price_history',
        ['origin', 'destination', 'departure_date', 'market'],
    )


def downgrade():
    op.drop_table('price_history')
    op.drop_table('search_history')
