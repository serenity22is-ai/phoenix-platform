"""Add OAuth provider ID columns (Build #82/#83)

Revision ID: z6a7b8c9d0e1
Revises: y5z6a7b8c9d0
Create Date: 2026-02-01
"""
from alembic import op
import sqlalchemy as sa

revision = "z6a7b8c9d0e1"
down_revision = "y5z6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    # Google OAuth (Build #82)
    op.add_column("users", sa.Column("google_id", sa.String(255), nullable=True))
    op.create_index("ix_users_google_id", "users", ["google_id"], unique=True)

    # Microsoft OAuth (Build #83)
    op.add_column("users", sa.Column("microsoft_id", sa.String(255), nullable=True))
    op.create_index("ix_users_microsoft_id", "users", ["microsoft_id"], unique=True)

    # Apple OAuth (Build #83)
    op.add_column("users", sa.Column("apple_id", sa.String(255), nullable=True))
    op.create_index("ix_users_apple_id", "users", ["apple_id"], unique=True)

    # Make password_hash nullable for OAuth-only users (Build #82)
    op.alter_column("users", "password_hash", existing_type=sa.String(256), nullable=True)


def downgrade():
    op.alter_column("users", "password_hash", existing_type=sa.String(256), nullable=False)
    op.drop_index("ix_users_apple_id", table_name="users")
    op.drop_column("users", "apple_id")
    op.drop_index("ix_users_microsoft_id", table_name="users")
    op.drop_column("users", "microsoft_id")
    op.drop_index("ix_users_google_id", table_name="users")
    op.drop_column("users", "google_id")
