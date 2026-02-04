"""Add geographic zone columns to helper_profiles and node_sessions

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa


revision = 'j0k1l2m3n4o5'
down_revision = 'i9j0k1l2m3n4'
branch_labels = None
depends_on = None


def upgrade():
    # Add zone_code to helper_profiles
    op.add_column('helper_profiles', sa.Column('zone_code', sa.String(10), nullable=True))
    op.create_index('ix_helper_profiles_zone_code', 'helper_profiles', ['zone_code'])

    # Add ip_zone to node_sessions
    op.add_column('node_sessions', sa.Column('ip_zone', sa.String(10), nullable=True))
    op.create_index('ix_node_sessions_ip_zone', 'node_sessions', ['ip_zone'])


def downgrade():
    op.drop_index('ix_node_sessions_ip_zone', 'node_sessions')
    op.drop_column('node_sessions', 'ip_zone')

    op.drop_index('ix_helper_profiles_zone_code', 'helper_profiles')
    op.drop_column('helper_profiles', 'zone_code')
