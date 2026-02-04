"""Add payment ramp network tables (Build #86)

Revision ID: b8c9d0e1f2g3
Revises: a7b8c9d0e1f2
Create Date: 2026-02-01
"""
from alembic import op
import sqlalchemy as sa

revision = "b8c9d0e1f2g3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    # Ramp provider configuration
    op.create_table(
        "ramp_providers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_code", sa.String(30), unique=True, nullable=False, index=True),
        sa.Column("provider_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("widget_base_url", sa.String(500), nullable=True),
        sa.Column("widget_type", sa.String(20), server_default="redirect"),
        sa.Column("supported_countries", sa.Text(), nullable=True),
        sa.Column("supported_fiat_methods", sa.Text(), nullable=True),
        sa.Column("supported_crypto_out", sa.Text(), nullable=True),
        sa.Column("fee_estimate_pct", sa.Float(), server_default="0.0"),
        sa.Column("kyc_required", sa.Boolean(), server_default="1"),
        sa.Column("api_key_env_var", sa.String(50), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="10"),
        sa.Column("is_active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # Virtual card pipeline transactions
    op.create_table(
        "virtual_card_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transaction_id", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        # Inbound crypto
        sa.Column("source_currency", sa.String(10), nullable=True),
        sa.Column("source_amount", sa.Float(), nullable=True),
        sa.Column("source_tx_hash", sa.String(100), nullable=True),
        # USDC settlement
        sa.Column("usdc_amount", sa.Float(), nullable=True),
        sa.Column("usdc_settled_at", sa.DateTime(), nullable=True),
        # Virtual card (Stripe Issuing)
        sa.Column("stripe_card_id", sa.String(100), nullable=True),
        sa.Column("card_funded_amount", sa.Float(), nullable=True),
        sa.Column("card_funded_at", sa.DateTime(), nullable=True),
        # Vendor charge
        sa.Column("merchant_country", sa.String(2), nullable=True),
        sa.Column("merchant_name", sa.String(200), nullable=True),
        sa.Column("charge_amount_usd", sa.Float(), nullable=True),
        sa.Column("charge_currency", sa.String(3), nullable=True),
        sa.Column("charge_amount_local", sa.Float(), nullable=True),
        sa.Column("charged_at", sa.DateTime(), nullable=True),
        # Context
        sa.Column("deal_id", sa.String(50), nullable=True),
        sa.Column("deal_type", sa.String(20), nullable=True),
        sa.Column("purchase_context", sa.String(20), server_default="browsing"),
        # Status + cost
        sa.Column("status", sa.String(30), server_default="initiated", index=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("fx_spread_pct", sa.Float(), nullable=True),
        sa.Column("total_fees_usd", sa.Float(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )

    # User ramp preferences
    op.create_table(
        "user_ramp_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("provider_code", sa.String(30), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="0"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("user_ramp_preferences")
    op.drop_table("virtual_card_transactions")
    op.drop_table("ramp_providers")
