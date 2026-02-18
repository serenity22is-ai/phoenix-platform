"""Add hotel deal columns to deals and bookings tables

Revision ID: d1e2f3g4h5i6
Revises: c0d1e2f3g4h5
Create Date: 2026-02-11

Phase 1: Hotel Booking Frontend - extend Deal model for hotels
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1e2f3g4h5i6'
down_revision = 'c0d1e2f3g4h5'
branch_labels = None
depends_on = None


def upgrade():
    # Deal table: deal type discriminator + hotel-specific columns
    op.add_column('deals', sa.Column('deal_type', sa.String(20), server_default='flight', nullable=True))
    op.add_column('deals', sa.Column('hotel_name', sa.String(300), nullable=True))
    op.add_column('deals', sa.Column('hotel_id', sa.String(50), nullable=True))
    op.add_column('deals', sa.Column('hotel_offer_id', sa.String(100), nullable=True))
    op.add_column('deals', sa.Column('city_code', sa.String(10), nullable=True))
    op.add_column('deals', sa.Column('city_name', sa.String(100), nullable=True))
    op.add_column('deals', sa.Column('check_in_date', sa.Date(), nullable=True))
    op.add_column('deals', sa.Column('check_out_date', sa.Date(), nullable=True))
    op.add_column('deals', sa.Column('nights', sa.Integer(), nullable=True))
    op.add_column('deals', sa.Column('rooms', sa.Integer(), nullable=True))
    op.add_column('deals', sa.Column('adults', sa.Integer(), nullable=True))
    op.add_column('deals', sa.Column('room_type', sa.String(50), nullable=True))
    op.add_column('deals', sa.Column('bed_type', sa.String(50), nullable=True))
    op.add_column('deals', sa.Column('star_rating', sa.Integer(), nullable=True))
    op.add_column('deals', sa.Column('price_per_night_usd', sa.Float(), nullable=True))
    op.add_column('deals', sa.Column('price_total_usd', sa.Float(), nullable=True))
    op.add_column('deals', sa.Column('amenities', sa.Text(), nullable=True))
    op.add_column('deals', sa.Column('cancellation_policy', sa.Text(), nullable=True))
    op.add_column('deals', sa.Column('room_description', sa.Text(), nullable=True))

    op.create_index('ix_deals_deal_type', 'deals', ['deal_type'])
    op.create_index('ix_deals_city_code', 'deals', ['city_code'])
    op.create_index('ix_deals_check_in_date', 'deals', ['check_in_date'])

    # Booking table: hotel-specific columns
    op.add_column('bookings', sa.Column('guest_title', sa.String(10), nullable=True))
    op.add_column('bookings', sa.Column('check_in_date', sa.Date(), nullable=True))
    op.add_column('bookings', sa.Column('check_out_date', sa.Date(), nullable=True))
    op.add_column('bookings', sa.Column('special_requests', sa.Text(), nullable=True))
    op.add_column('bookings', sa.Column('hotel_confirmation_id', sa.String(100), nullable=True))
    op.add_column('bookings', sa.Column('provider_reference', sa.String(100), nullable=True))


def downgrade():
    # Bookings
    op.drop_column('bookings', 'provider_reference')
    op.drop_column('bookings', 'hotel_confirmation_id')
    op.drop_column('bookings', 'special_requests')
    op.drop_column('bookings', 'check_out_date')
    op.drop_column('bookings', 'check_in_date')
    op.drop_column('bookings', 'guest_title')

    # Deals
    op.drop_index('ix_deals_check_in_date', 'deals')
    op.drop_index('ix_deals_city_code', 'deals')
    op.drop_index('ix_deals_deal_type', 'deals')
    op.drop_column('deals', 'room_description')
    op.drop_column('deals', 'cancellation_policy')
    op.drop_column('deals', 'amenities')
    op.drop_column('deals', 'price_total_usd')
    op.drop_column('deals', 'price_per_night_usd')
    op.drop_column('deals', 'star_rating')
    op.drop_column('deals', 'bed_type')
    op.drop_column('deals', 'room_type')
    op.drop_column('deals', 'adults')
    op.drop_column('deals', 'rooms')
    op.drop_column('deals', 'nights')
    op.drop_column('deals', 'check_out_date')
    op.drop_column('deals', 'check_in_date')
    op.drop_column('deals', 'city_name')
    op.drop_column('deals', 'city_code')
    op.drop_column('deals', 'hotel_offer_id')
    op.drop_column('deals', 'hotel_id')
    op.drop_column('deals', 'hotel_name')
    op.drop_column('deals', 'deal_type')
