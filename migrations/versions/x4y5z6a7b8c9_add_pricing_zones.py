"""Add pricing zones, price observations, node location history tables (Build #78)

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-01-30
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "x4y5z6a7b8c9"
down_revision = "w3x4y5z6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    # --- pricing_zones ---
    op.create_table(
        "pricing_zones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("zone_id", sa.String(30), unique=True, nullable=False),
        sa.Column("parent_zone_id", sa.String(30), nullable=True),
        sa.Column("resolution", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=True),
        sa.Column("lat_center", sa.Float(), nullable=True),
        sa.Column("lon_center", sa.Float(), nullable=True),
        sa.Column("radius_km", sa.Float(), nullable=True),
        sa.Column("active_node_count", sa.Integer(), server_default="0"),
        sa.Column("total_observations", sa.Integer(), server_default="0"),
        sa.Column("density_score", sa.Float(), server_default="0.0"),
        sa.Column("avg_price_deviation_pct", sa.Float(), nullable=True),
        sa.Column("is_seeded", sa.Boolean(), server_default="0"),
        sa.Column("is_auto_discovered", sa.Boolean(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["parent_zone_id"], ["pricing_zones.zone_id"]),
    )
    op.create_index("ix_pricing_zones_zone_id", "pricing_zones", ["zone_id"])
    op.create_index("ix_pricing_zones_parent_zone_id", "pricing_zones", ["parent_zone_id"])
    op.create_index("ix_pricing_zones_resolution", "pricing_zones", ["resolution"])
    op.create_index("ix_pricing_zones_country_code", "pricing_zones", ["country_code"])
    op.create_index(
        "ix_pricing_zones_country_resolution",
        "pricing_zones",
        ["country_code", "resolution"],
    )
    op.create_index(
        "ix_pricing_zones_lat_lon",
        "pricing_zones",
        ["lat_center", "lon_center"],
    )

    # --- price_observations ---
    op.create_table(
        "price_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observation_id", sa.String(50), unique=True, nullable=False),
        sa.Column("zone_id", sa.String(30), nullable=True),
        sa.Column("node_id", sa.String(50), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=True),
        sa.Column("vertical", sa.String(20), nullable=True),
        sa.Column("item_key", sa.String(300), nullable=True),
        sa.Column("price_usd", sa.Float(), nullable=True),
        sa.Column("price_local", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(5), nullable=True),
        sa.Column("is_promoted", sa.Boolean(), server_default="0"),
        sa.Column("promotion_type", sa.String(50), nullable=True),
        sa.Column("source_tier", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("observed_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["zone_id"], ["pricing_zones.zone_id"]),
    )
    op.create_index("ix_price_observations_observation_id", "price_observations", ["observation_id"])
    op.create_index("ix_price_observations_zone_id", "price_observations", ["zone_id"])
    op.create_index("ix_price_observations_node_id", "price_observations", ["node_id"])
    op.create_index("ix_price_observations_country_code", "price_observations", ["country_code"])
    op.create_index("ix_price_observations_vertical", "price_observations", ["vertical"])
    op.create_index("ix_price_observations_item_key", "price_observations", ["item_key"])
    op.create_index("ix_price_observations_observed_at", "price_observations", ["observed_at"])
    op.create_index(
        "ix_price_observations_vertical_item",
        "price_observations",
        ["vertical", "item_key"],
    )
    op.create_index(
        "ix_price_observations_zone_observed",
        "price_observations",
        ["zone_id", "observed_at"],
    )
    op.create_index(
        "ix_price_observations_country_vertical",
        "price_observations",
        ["country_code", "vertical"],
    )

    # --- node_location_history ---
    op.create_table(
        "node_location_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.String(50), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("source", sa.String(20), nullable=True),
        sa.Column("resolved_zone_id", sa.String(30), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_node_location_history_node_id", "node_location_history", ["node_id"])
    op.create_index("ix_node_location_history_user_id", "node_location_history", ["user_id"])
    op.create_index("ix_node_location_history_resolved_zone_id", "node_location_history", ["resolved_zone_id"])
    op.create_index("ix_node_location_history_recorded_at", "node_location_history", ["recorded_at"])
    op.create_index(
        "ix_node_location_history_lat_lon",
        "node_location_history",
        ["lat", "lon"],
    )
    op.create_index(
        "ix_node_location_history_node_recorded",
        "node_location_history",
        ["node_id", "recorded_at"],
    )


def downgrade():
    op.drop_table("node_location_history")
    op.drop_table("price_observations")
    op.drop_table("pricing_zones")
