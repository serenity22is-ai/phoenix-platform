"""Add TravelerProfile table

Revision ID: c0d1e2f3g4h5
Revises: b8c9d0e1f2g3
Create Date: 2026-02-06

Build #100: Saved traveler profiles for IATA/APIS compliant booking
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c0d1e2f3g4h5'
down_revision = 'b8c9d0e1f2g3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('traveler_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),

        # Required identity fields
        sa.Column('title', sa.String(length=10), nullable=True),
        sa.Column('first_name', sa.String(length=100), nullable=False),
        sa.Column('middle_name', sa.String(length=100), nullable=True),
        sa.Column('last_name', sa.String(length=100), nullable=False),
        sa.Column('date_of_birth', sa.Date(), nullable=True),
        sa.Column('gender', sa.String(length=1), nullable=True),
        sa.Column('passenger_type', sa.String(length=10), nullable=True),

        # Contact
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('phone_country_code', sa.String(length=5), nullable=True),

        # Travel document (APIS)
        sa.Column('passport_number', sa.String(length=20), nullable=True),
        sa.Column('passport_expiry', sa.Date(), nullable=True),
        sa.Column('passport_country', sa.String(length=3), nullable=True),
        sa.Column('nationality', sa.String(length=3), nullable=True),

        # US-specific (TSA)
        sa.Column('redress_number', sa.String(length=20), nullable=True),
        sa.Column('known_traveler_number', sa.String(length=25), nullable=True),

        # Preferences
        sa.Column('seat_preference', sa.String(length=20), nullable=True),
        sa.Column('meal_preference', sa.String(length=20), nullable=True),
        sa.Column('special_assistance', sa.Text(), nullable=True),
        sa.Column('frequent_flyer_numbers', sa.Text(), nullable=True),

        # Emergency contact
        sa.Column('emergency_contact_name', sa.String(length=100), nullable=True),
        sa.Column('emergency_contact_phone', sa.String(length=30), nullable=True),
        sa.Column('emergency_contact_relation', sa.String(length=50), nullable=True),

        # Status
        sa.Column('is_primary', sa.Boolean(), nullable=True, default=False),
        sa.Column('is_active', sa.Boolean(), nullable=True, default=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),

        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_traveler_profiles_user_id'), 'traveler_profiles', ['user_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_traveler_profiles_user_id'), table_name='traveler_profiles')
    op.drop_table('traveler_profiles')
