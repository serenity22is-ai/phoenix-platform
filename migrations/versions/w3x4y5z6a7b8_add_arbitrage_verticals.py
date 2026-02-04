"""Add Universal Arbitrage Vertical deal tables (Build #76)

- hotel_deals: Hotel arbitrage deals
- cruise_deals: Cruise arbitrage deals
- rental_deals: Car rental arbitrage deals
- vacation_package_deals: Bundled vacation package deals

Revision ID: w3x4y5z6a7b8
Revises: v1w2x3y4z5a6
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa


revision = 'w3x4y5z6a7b8'
down_revision = 'v1w2x3y4z5a6'
branch_labels = None
depends_on = None


def upgrade():
    # --- hotel_deals ---
    op.create_table('hotel_deals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('hotel_deal_id', sa.String(20), nullable=False, unique=True, index=True),
        sa.Column('hotel_name', sa.String(300), index=True),
        sa.Column('hotel_chain', sa.String(100)),
        sa.Column('city', sa.String(100), index=True),
        sa.Column('country', sa.String(2), index=True),
        sa.Column('star_rating', sa.Integer()),
        sa.Column('guest_rating', sa.Float()),
        sa.Column('check_in', sa.Date(), index=True),
        sa.Column('check_out', sa.Date()),
        sa.Column('nights', sa.Integer()),
        sa.Column('room_type', sa.String(50), server_default='standard'),
        sa.Column('guests', sa.Integer(), server_default='2'),
        sa.Column('amenities', sa.Text()),
        sa.Column('source_url', sa.String(500)),
        sa.Column('home_market', sa.String(2)),
        sa.Column('home_price_usd', sa.Float()),
        sa.Column('arbitrage_market', sa.String(2)),
        sa.Column('arbitrage_price_usd', sa.Float()),
        sa.Column('arbitrage_price_local', sa.Float()),
        sa.Column('arbitrage_currency', sa.String(3)),
        sa.Column('price_per_night_home', sa.Float()),
        sa.Column('price_per_night_arb', sa.Float()),
        sa.Column('gross_savings_usd', sa.Float()),
        sa.Column('platform_fee_usd', sa.Float()),
        sa.Column('user_savings_usd', sa.Float()),
        sa.Column('savings_percent', sa.Float()),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('expires_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
    )

    # --- cruise_deals ---
    op.create_table('cruise_deals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('cruise_deal_id', sa.String(20), nullable=False, unique=True, index=True),
        sa.Column('cruise_line', sa.String(100), index=True),
        sa.Column('ship_name', sa.String(200)),
        sa.Column('departure_port', sa.String(100), index=True),
        sa.Column('itinerary', sa.Text()),
        sa.Column('departure_date', sa.Date(), index=True),
        sa.Column('return_date', sa.Date()),
        sa.Column('duration_nights', sa.Integer()),
        sa.Column('cabin_category', sa.String(30), server_default='inside'),
        sa.Column('deck', sa.String(20)),
        sa.Column('source_url', sa.String(500)),
        sa.Column('home_market', sa.String(2)),
        sa.Column('home_price_usd', sa.Float()),
        sa.Column('arbitrage_market', sa.String(2)),
        sa.Column('arbitrage_price_usd', sa.Float()),
        sa.Column('arbitrage_price_local', sa.Float()),
        sa.Column('arbitrage_currency', sa.String(3)),
        sa.Column('price_per_night_home', sa.Float()),
        sa.Column('price_per_night_arb', sa.Float()),
        sa.Column('gross_savings_usd', sa.Float()),
        sa.Column('platform_fee_usd', sa.Float()),
        sa.Column('user_savings_usd', sa.Float()),
        sa.Column('savings_percent', sa.Float()),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('expires_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
    )

    # --- rental_deals ---
    op.create_table('rental_deals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('rental_deal_id', sa.String(20), nullable=False, unique=True, index=True),
        sa.Column('rental_company', sa.String(100), index=True),
        sa.Column('pickup_location', sa.String(200), index=True),
        sa.Column('dropoff_location', sa.String(200)),
        sa.Column('pickup_date', sa.Date(), index=True),
        sa.Column('dropoff_date', sa.Date()),
        sa.Column('rental_days', sa.Integer()),
        sa.Column('vehicle_class', sa.String(30), server_default='economy'),
        sa.Column('vehicle_example', sa.String(100)),
        sa.Column('source_url', sa.String(500)),
        sa.Column('home_market', sa.String(2)),
        sa.Column('home_price_usd', sa.Float()),
        sa.Column('arbitrage_market', sa.String(2)),
        sa.Column('arbitrage_price_usd', sa.Float()),
        sa.Column('arbitrage_price_local', sa.Float()),
        sa.Column('arbitrage_currency', sa.String(3)),
        sa.Column('price_per_day_home', sa.Float()),
        sa.Column('price_per_day_arb', sa.Float()),
        sa.Column('gross_savings_usd', sa.Float()),
        sa.Column('platform_fee_usd', sa.Float()),
        sa.Column('user_savings_usd', sa.Float()),
        sa.Column('savings_percent', sa.Float()),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('expires_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
    )

    # --- vacation_package_deals ---
    op.create_table('vacation_package_deals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('package_deal_id', sa.String(20), nullable=False, unique=True, index=True),
        sa.Column('package_type', sa.String(30), server_default='flight_hotel'),
        sa.Column('destination_city', sa.String(100), index=True),
        sa.Column('origin_city', sa.String(100)),
        sa.Column('start_date', sa.Date(), index=True),
        sa.Column('end_date', sa.Date()),
        sa.Column('nights', sa.Integer()),
        sa.Column('components', sa.Text()),
        sa.Column('flight_deal_id', sa.String(20)),
        sa.Column('hotel_deal_id', sa.String(20)),
        sa.Column('rental_deal_id', sa.String(20)),
        sa.Column('cruise_deal_id', sa.String(20)),
        sa.Column('home_total_usd', sa.Float()),
        sa.Column('arbitrage_total_usd', sa.Float()),
        sa.Column('gross_savings_usd', sa.Float()),
        sa.Column('platform_fee_usd', sa.Float()),
        sa.Column('user_savings_usd', sa.Float()),
        sa.Column('savings_percent', sa.Float()),
        sa.Column('bundle_discount_usd', sa.Float()),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('expires_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
    )


def downgrade():
    op.drop_table('vacation_package_deals')
    op.drop_table('rental_deals')
    op.drop_table('cruise_deals')
    op.drop_table('hotel_deals')
