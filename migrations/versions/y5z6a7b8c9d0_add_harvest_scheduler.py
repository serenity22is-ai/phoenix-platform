"""Add harvest scheduler tables (Build #79)

Revision ID: y5z6a7b8c9d0
Revises: x4y5z6a7b8c9
Create Date: 2026-01-30
"""
from alembic import op
import sqlalchemy as sa

revision = "y5z6a7b8c9d0"
down_revision = "x4y5z6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    # --- harvest_executions ---
    op.create_table(
        "harvest_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.String(30), unique=True, nullable=False),
        sa.Column("execution_type", sa.String(30), nullable=False),
        sa.Column("vertical", sa.String(20), nullable=True),
        sa.Column("zones_targeted", sa.Text(), nullable=True),
        sa.Column("tasks_generated", sa.Integer(), server_default="0"),
        sa.Column("tasks_dispatched", sa.Integer(), server_default="0"),
        sa.Column("tasks_completed", sa.Integer(), server_default="0"),
        sa.Column("tasks_failed", sa.Integer(), server_default="0"),
        sa.Column("observations_collected", sa.Integer(), server_default="0"),
        sa.Column("total_payout_usd", sa.Float(), server_default="0.0"),
        sa.Column("avg_quality_score", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_harvest_executions_batch_id", "harvest_executions", ["batch_id"])
    op.create_index("ix_harvest_executions_execution_type", "harvest_executions", ["execution_type"])
    op.create_index(
        "ix_harvest_executions_type_created",
        "harvest_executions",
        ["execution_type", "created_at"],
    )

    # --- standing_orders ---
    op.create_table(
        "standing_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.String(30), unique=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("vertical", sa.String(20), nullable=False),
        sa.Column("filters", sa.Text(), nullable=True),
        sa.Column("zone_ids", sa.Text(), nullable=True),
        sa.Column("refresh_interval_hours", sa.Integer(), server_default="6"),
        sa.Column("max_tasks_per_cycle", sa.Integer(), server_default="10"),
        sa.Column("price_per_observation_usd", sa.Float(), server_default="0.01"),
        sa.Column("max_spend_per_day_usd", sa.Float(), server_default="50.0"),
        sa.Column("is_active", sa.Boolean(), server_default="1"),
        sa.Column("last_executed_at", sa.DateTime(), nullable=True),
        sa.Column("total_observations_delivered", sa.Integer(), server_default="0"),
        sa.Column("total_spent_usd", sa.Float(), server_default="0.0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["account_id"], ["commercial_accounts.id"]),
    )
    op.create_index("ix_standing_orders_order_id", "standing_orders", ["order_id"])
    op.create_index("ix_standing_orders_account_id", "standing_orders", ["account_id"])
    op.create_index("ix_standing_orders_vertical", "standing_orders", ["vertical"])
    op.create_index(
        "ix_standing_orders_active_vertical",
        "standing_orders",
        ["is_active", "vertical"],
    )

    # --- harvest_budgets ---
    op.create_table(
        "harvest_budgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("zone_id", sa.String(30), nullable=False),
        sa.Column("vertical", sa.String(20), nullable=False),
        sa.Column("max_tasks_per_hour", sa.Integer(), server_default="20"),
        sa.Column("max_tasks_per_day", sa.Integer(), server_default="200"),
        sa.Column("tasks_this_hour", sa.Integer(), server_default="0"),
        sa.Column("tasks_today", sa.Integer(), server_default="0"),
        sa.Column("hour_reset_at", sa.DateTime(), nullable=True),
        sa.Column("day_reset_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("zone_id", "vertical", name="uq_harvest_budget_zone_vertical"),
    )
    op.create_index("ix_harvest_budgets_zone_id", "harvest_budgets", ["zone_id"])
    op.create_index("ix_harvest_budgets_vertical", "harvest_budgets", ["vertical"])
    op.create_index(
        "ix_harvest_budgets_zone_vertical",
        "harvest_budgets",
        ["zone_id", "vertical"],
    )


def downgrade():
    op.drop_table("harvest_budgets")
    op.drop_table("standing_orders")
    op.drop_table("harvest_executions")
