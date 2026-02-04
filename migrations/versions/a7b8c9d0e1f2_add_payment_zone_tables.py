"""Add payment zone compatibility tables (Build #85)

Revision ID: a7b8c9d0e1f2
Revises: z6a7b8c9d0e1
Create Date: 2026-02-01
"""
from alembic import op
import sqlalchemy as sa

revision = "a7b8c9d0e1f2"
down_revision = "z6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    # Payment Zone Rules - compatibility matrix
    op.create_table(
        "payment_zone_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_type", sa.String(20), nullable=False, index=True),
        sa.Column("issuing_country", sa.String(2), nullable=False, index=True),
        sa.Column("merchant_country", sa.String(2), nullable=False, index=True),
        sa.Column("acceptance_level", sa.String(10), nullable=False, server_default="high"),
        sa.Column("vertical", sa.String(20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_pzr_lookup",
        "payment_zone_rules",
        ["payment_type", "issuing_country", "merchant_country", "is_active"],
    )

    # Payment Interop Groups - country clusters with shared payment infra
    op.create_table(
        "payment_interop_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_code", sa.String(30), unique=True, nullable=False, index=True),
        sa.Column("group_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("countries", sa.Text(), nullable=False),
        sa.Column("payment_types", sa.Text(), nullable=False),
        sa.Column("default_acceptance", sa.String(10), server_default="high"),
        sa.Column("is_active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # Add payment_compatibility column to deal tables
    op.add_column("deals", sa.Column("payment_compatibility", sa.Text(), nullable=True))
    op.add_column("hotel_deals", sa.Column("payment_compatibility", sa.Text(), nullable=True))
    op.add_column("cruise_deals", sa.Column("payment_compatibility", sa.Text(), nullable=True))
    op.add_column("rental_deals", sa.Column("payment_compatibility", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("rental_deals", "payment_compatibility")
    op.drop_column("cruise_deals", "payment_compatibility")
    op.drop_column("hotel_deals", "payment_compatibility")
    op.drop_column("deals", "payment_compatibility")
    op.drop_table("payment_interop_groups")
    op.drop_index("idx_pzr_lookup", table_name="payment_zone_rules")
    op.drop_table("payment_zone_rules")
