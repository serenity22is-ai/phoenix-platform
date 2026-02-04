"""Add vertical-specific price record tables (Build #66)

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa


revision = 'o5p6q7r8s9t0'
down_revision = 'n4o5p6q7r8s9'
branch_labels = None
depends_on = None


def upgrade():
    # Flight Price Records
    op.create_table(
        'flight_price_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('task_id', sa.String(50), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('market', sa.String(5), nullable=False),
        sa.Column('origin', sa.String(10), nullable=False),
        sa.Column('destination', sa.String(10), nullable=False),
        sa.Column('departure_date', sa.Date(), nullable=False),
        sa.Column('return_date', sa.Date(), nullable=True),
        sa.Column('airline', sa.String(100), nullable=True),
        sa.Column('price_usd', sa.Float(), nullable=False),
        sa.Column('price_local', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(5), nullable=True),
        sa.Column('stops', sa.Integer(), server_default='0'),
        sa.Column('duration_minutes', sa.Integer(), nullable=True),
        sa.Column('cabin_class', sa.String(20), server_default='economy'),
        sa.Column('observed_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_flight_pr_task', 'flight_price_records', ['task_id'])
    op.create_index('ix_flight_pr_user', 'flight_price_records', ['user_id'])
    op.create_index('ix_flight_pr_market', 'flight_price_records', ['market'])
    op.create_index('ix_flight_pr_origin', 'flight_price_records', ['origin'])
    op.create_index('ix_flight_pr_dest', 'flight_price_records', ['destination'])
    op.create_index('ix_flight_pr_dep_date', 'flight_price_records', ['departure_date'])
    op.create_index('ix_flight_pr_airline', 'flight_price_records', ['airline'])
    op.create_index('ix_flight_pr_observed', 'flight_price_records', ['observed_at'])
    op.create_index('ix_flight_pr_route_date', 'flight_price_records', ['origin', 'destination', 'departure_date'])
    op.create_index('ix_flight_pr_market_route', 'flight_price_records', ['market', 'origin', 'destination'])

    # Hotel Price Records
    op.create_table(
        'hotel_price_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('task_id', sa.String(50), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('market', sa.String(5), nullable=False),
        sa.Column('hotel_name', sa.String(300), nullable=False),
        sa.Column('location', sa.String(200), nullable=True),
        sa.Column('checkin_date', sa.Date(), nullable=True),
        sa.Column('checkout_date', sa.Date(), nullable=True),
        sa.Column('price_per_night_usd', sa.Float(), nullable=False),
        sa.Column('price_per_night_local', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(5), nullable=True),
        sa.Column('rating', sa.Float(), nullable=True),
        sa.Column('star_rating', sa.Integer(), nullable=True),
        sa.Column('amenities', sa.Text(), nullable=True),
        sa.Column('source_platform', sa.String(100), nullable=True),
        sa.Column('observed_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_hotel_pr_task', 'hotel_price_records', ['task_id'])
    op.create_index('ix_hotel_pr_user', 'hotel_price_records', ['user_id'])
    op.create_index('ix_hotel_pr_market', 'hotel_price_records', ['market'])
    op.create_index('ix_hotel_pr_name', 'hotel_price_records', ['hotel_name'])
    op.create_index('ix_hotel_pr_observed', 'hotel_price_records', ['observed_at'])
    op.create_index('ix_hotel_pr_name_market', 'hotel_price_records', ['hotel_name', 'market'])
    op.create_index('ix_hotel_pr_location', 'hotel_price_records', ['location'])

    # Cruise Price Records
    op.create_table(
        'cruise_price_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('task_id', sa.String(50), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('market', sa.String(5), nullable=False),
        sa.Column('cruise_line', sa.String(100), nullable=False),
        sa.Column('ship_name', sa.String(200), nullable=True),
        sa.Column('itinerary', sa.String(500), nullable=True),
        sa.Column('departure_port', sa.String(100), nullable=True),
        sa.Column('departure_date', sa.Date(), nullable=True),
        sa.Column('duration_nights', sa.Integer(), nullable=True),
        sa.Column('cabin_type', sa.String(50), nullable=True),
        sa.Column('price_usd', sa.Float(), nullable=False),
        sa.Column('price_local', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(5), nullable=True),
        sa.Column('price_per_night_usd', sa.Float(), nullable=True),
        sa.Column('observed_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_cruise_pr_task', 'cruise_price_records', ['task_id'])
    op.create_index('ix_cruise_pr_user', 'cruise_price_records', ['user_id'])
    op.create_index('ix_cruise_pr_market', 'cruise_price_records', ['market'])
    op.create_index('ix_cruise_pr_line', 'cruise_price_records', ['cruise_line'])
    op.create_index('ix_cruise_pr_port', 'cruise_price_records', ['departure_port'])
    op.create_index('ix_cruise_pr_dep_date', 'cruise_price_records', ['departure_date'])
    op.create_index('ix_cruise_pr_observed', 'cruise_price_records', ['observed_at'])
    op.create_index('ix_cruise_pr_line_market', 'cruise_price_records', ['cruise_line', 'market'])
    op.create_index('ix_cruise_pr_port_date', 'cruise_price_records', ['departure_port', 'departure_date'])

    # Product Price Records
    op.create_table(
        'product_price_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('task_id', sa.String(50), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('market', sa.String(5), nullable=False),
        sa.Column('product_title', sa.String(500), nullable=False),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('seller', sa.String(200), nullable=True),
        sa.Column('platform', sa.String(100), nullable=True),
        sa.Column('price_usd', sa.Float(), nullable=False),
        sa.Column('price_local', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(5), nullable=True),
        sa.Column('rating', sa.Float(), nullable=True),
        sa.Column('availability', sa.String(50), nullable=True),
        sa.Column('product_url', sa.String(500), nullable=True),
        sa.Column('is_ecommerce', sa.Boolean(), server_default='0'),
        sa.Column('shipping_estimate_usd', sa.Float(), nullable=True),
        sa.Column('landed_cost_usd', sa.Float(), nullable=True),
        sa.Column('observed_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_product_pr_task', 'product_price_records', ['task_id'])
    op.create_index('ix_product_pr_user', 'product_price_records', ['user_id'])
    op.create_index('ix_product_pr_market', 'product_price_records', ['market'])
    op.create_index('ix_product_pr_category', 'product_price_records', ['category'])
    op.create_index('ix_product_pr_platform', 'product_price_records', ['platform'])
    op.create_index('ix_product_pr_observed', 'product_price_records', ['observed_at'])
    op.create_index('ix_product_pr_cat_market', 'product_price_records', ['category', 'market'])
    op.create_index('ix_product_pr_plat_market', 'product_price_records', ['platform', 'market'])

    # Marketplace Listing Records
    op.create_table(
        'marketplace_listing_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('task_id', sa.String(50), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('market', sa.String(5), nullable=False),
        sa.Column('listing_title', sa.String(500), nullable=False),
        sa.Column('price_usd', sa.Float(), nullable=False),
        sa.Column('price_local', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(5), nullable=True),
        sa.Column('location', sa.String(200), nullable=True),
        sa.Column('seller_name', sa.String(200), nullable=True),
        sa.Column('condition', sa.String(50), nullable=True),
        sa.Column('listing_url', sa.String(500), nullable=True),
        sa.Column('image_url', sa.String(500), nullable=True),
        sa.Column('is_bargain', sa.Boolean(), server_default='0'),
        sa.Column('pct_of_median', sa.Float(), nullable=True),
        sa.Column('observed_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_mktplace_pr_task', 'marketplace_listing_records', ['task_id'])
    op.create_index('ix_mktplace_pr_user', 'marketplace_listing_records', ['user_id'])
    op.create_index('ix_mktplace_pr_market', 'marketplace_listing_records', ['market'])
    op.create_index('ix_mktplace_pr_location', 'marketplace_listing_records', ['location'])
    op.create_index('ix_mktplace_pr_bargain', 'marketplace_listing_records', ['is_bargain'])
    op.create_index('ix_mktplace_pr_observed', 'marketplace_listing_records', ['observed_at'])
    op.create_index('ix_mktplace_pr_market_loc', 'marketplace_listing_records', ['market', 'location'])
    op.create_index('ix_mktplace_pr_bargain_obs', 'marketplace_listing_records', ['is_bargain', 'observed_at'])


def downgrade():
    op.drop_index('ix_mktplace_pr_bargain_obs', table_name='marketplace_listing_records')
    op.drop_index('ix_mktplace_pr_market_loc', table_name='marketplace_listing_records')
    op.drop_index('ix_mktplace_pr_observed', table_name='marketplace_listing_records')
    op.drop_index('ix_mktplace_pr_bargain', table_name='marketplace_listing_records')
    op.drop_index('ix_mktplace_pr_location', table_name='marketplace_listing_records')
    op.drop_index('ix_mktplace_pr_market', table_name='marketplace_listing_records')
    op.drop_index('ix_mktplace_pr_user', table_name='marketplace_listing_records')
    op.drop_index('ix_mktplace_pr_task', table_name='marketplace_listing_records')
    op.drop_table('marketplace_listing_records')

    op.drop_index('ix_product_pr_plat_market', table_name='product_price_records')
    op.drop_index('ix_product_pr_cat_market', table_name='product_price_records')
    op.drop_index('ix_product_pr_observed', table_name='product_price_records')
    op.drop_index('ix_product_pr_platform', table_name='product_price_records')
    op.drop_index('ix_product_pr_category', table_name='product_price_records')
    op.drop_index('ix_product_pr_market', table_name='product_price_records')
    op.drop_index('ix_product_pr_user', table_name='product_price_records')
    op.drop_index('ix_product_pr_task', table_name='product_price_records')
    op.drop_table('product_price_records')

    op.drop_index('ix_cruise_pr_port_date', table_name='cruise_price_records')
    op.drop_index('ix_cruise_pr_line_market', table_name='cruise_price_records')
    op.drop_index('ix_cruise_pr_observed', table_name='cruise_price_records')
    op.drop_index('ix_cruise_pr_dep_date', table_name='cruise_price_records')
    op.drop_index('ix_cruise_pr_port', table_name='cruise_price_records')
    op.drop_index('ix_cruise_pr_line', table_name='cruise_price_records')
    op.drop_index('ix_cruise_pr_market', table_name='cruise_price_records')
    op.drop_index('ix_cruise_pr_user', table_name='cruise_price_records')
    op.drop_index('ix_cruise_pr_task', table_name='cruise_price_records')
    op.drop_table('cruise_price_records')

    op.drop_index('ix_hotel_pr_location', table_name='hotel_price_records')
    op.drop_index('ix_hotel_pr_name_market', table_name='hotel_price_records')
    op.drop_index('ix_hotel_pr_observed', table_name='hotel_price_records')
    op.drop_index('ix_hotel_pr_name', table_name='hotel_price_records')
    op.drop_index('ix_hotel_pr_market', table_name='hotel_price_records')
    op.drop_index('ix_hotel_pr_user', table_name='hotel_price_records')
    op.drop_index('ix_hotel_pr_task', table_name='hotel_price_records')
    op.drop_table('hotel_price_records')

    op.drop_index('ix_flight_pr_market_route', table_name='flight_price_records')
    op.drop_index('ix_flight_pr_route_date', table_name='flight_price_records')
    op.drop_index('ix_flight_pr_observed', table_name='flight_price_records')
    op.drop_index('ix_flight_pr_airline', table_name='flight_price_records')
    op.drop_index('ix_flight_pr_dep_date', table_name='flight_price_records')
    op.drop_index('ix_flight_pr_dest', table_name='flight_price_records')
    op.drop_index('ix_flight_pr_origin', table_name='flight_price_records')
    op.drop_index('ix_flight_pr_market', table_name='flight_price_records')
    op.drop_index('ix_flight_pr_user', table_name='flight_price_records')
    op.drop_index('ix_flight_pr_task', table_name='flight_price_records')
    op.drop_table('flight_price_records')
