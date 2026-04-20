"""Catch-up stamp: Builds #199-237 models synced via db.create_all()

All 50+ models added in builds #167-237 are created by db.create_all() in
the Dockerfile CMD. This migration serves as a revision chain marker so
Alembic knows the schema is current.

Tables covered (created by SQLAlchemy model metadata, not this migration):
  - trip_bundles, bundle_items (Build #208)
  - feature_flags, system_settings (Build #95)
  - subscriptions (Build #167)
  - ai_sessions (Build #167)
  - rewards_accounts, points_transactions, point_gifts, points_escrow (Build #167)
  - trip_plans, trip_members, trip_items, trip_carts, trip_cart_assignments (Build #167)
  - trip_parties, trip_guests (Build #221)
  - itinerary_items, itinerary_votes, item_comments (Build #222-224)
  - trip_announcements, ticket_tiers, trip_guest_infos (Build #225-227)
  - shared_carts (Build #229)
  - trip_posts, trip_photos (Build #230)
  - user_follows, profile_reviews (Build #231-232)
  - referral_clicks, conversion_events (Build #233)
  - workspaces, workspace_members, travel_policies, booking_approvals (Build #235-237)
  - trip_receipts (Build #237)
  - friendships, collections, saved_items (Build #167)
  - local_businesses (Build #167)
  - consumer_referrals, social_shares, google_reviews, referral_cards (Build #170)
  - cross_sell_events (Build #167)
  - template_deployments (Build #194)
  - device_tokens, webhook_events (Build #211)
  - apai_instance_keys (Build #194)
  - booking_failures, system_metrics (Build #211)
  - external_booking_imports, arbitrage_checks, hot_routes (Build #234)
  - invite_links (Build #219)

New User columns (added by create_all if not present):
  - no_fx_fee_card, nickname (Build #220)

Revision ID: bb199237
Revises: f3g4h5i6j7k8, aa184186b2b1
Create Date: 2026-04-19
"""

from alembic import op
import sqlalchemy as sa

revision = 'bb199237'
down_revision = ('f3g4h5i6j7k8', 'aa184186b2b1')
branch_labels = None
depends_on = None


def upgrade():
    # All tables are created by db.create_all() in the Dockerfile CMD.
    # This migration exists only to advance the Alembic revision chain.
    #
    # On a fresh database: flask db upgrade runs all prior migrations,
    # then db.create_all() fills in any tables not covered by migrations.
    #
    # On an existing database: this is a no-op stamp.
    pass


def downgrade():
    # No-op — tables managed by db.create_all() and model metadata.
    pass
