"""
Database Models — SQLAlchemy ORM for persistent storage.

Replaces file-based JSON stores (ConfigStore, UsageTracker, BillingManager)
when STORAGE_BACKEND=db is set. File-based stores remain the default for
development and backward compatibility.

Tables:
    agencies       — Agency configuration (replaces .agency_configs/*.json)
    usage_records  — Usage metering per agency per month
    subscriptions  — Stripe subscription state
    audit_entries  — Compliance audit trail (optional DB alternative to JSONL)

MYSTES KYRIOS LLC — Confidential.
"""

import os

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def init_db(app):
    """Initialize database with the Flask app if STORAGE_BACKEND=db."""
    database_url = os.environ.get("DATABASE_URL", "sqlite:///anastasia.db")

    # Render uses postgres:// but SQLAlchemy needs postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    db.init_app(app)
    with app.app_context():
        db.create_all()


class Agency(db.Model):
    """Agency configuration — replaces ConfigStore JSON files."""
    __tablename__ = "agencies"

    id = db.Column(db.Integer, primary_key=True)
    key_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    api_key_prefix = db.Column(db.String(10))
    company_name = db.Column(db.String(200))
    contact_email = db.Column(db.String(200))
    tier = db.Column(db.String(20), default="starter")
    is_active = db.Column(db.Boolean, default=True)
    config_json = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    usage_records = db.relationship("UsageRecord", backref="agency", lazy="dynamic")
    subscription = db.relationship("Subscription", backref="agency", uselist=False)

    def __repr__(self):
        return f"<Agency {self.key_hash[:8]}... {self.company_name or 'unnamed'}>"


class UsageRecord(db.Model):
    """Usage tracking — replaces UsageTracker JSON files."""
    __tablename__ = "usage_records"

    id = db.Column(db.Integer, primary_key=True)
    key_hash = db.Column(db.String(64), db.ForeignKey("agencies.key_hash"), nullable=False, index=True)
    period = db.Column(db.String(7), nullable=False, index=True)  # "2026-03"
    ai_requests = db.Column(db.Integer, default=0)
    searches = db.Column(db.Integer, default=0)
    bookings = db.Column(db.Integer, default=0)
    documents = db.Column(db.Integer, default=0)
    errors = db.Column(db.Integer, default=0)
    ai_input_tokens = db.Column(db.Integer, default=0)
    ai_output_tokens = db.Column(db.Integer, default=0)
    first_request_at = db.Column(db.Float, nullable=True)
    last_request_at = db.Column(db.Float, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("key_hash", "period", name="uq_usage_key_period"),
    )

    def to_dict(self):
        return {
            "key_hash": self.key_hash,
            "period": self.period,
            "ai_requests": self.ai_requests,
            "searches": self.searches,
            "bookings": self.bookings,
            "documents": self.documents,
            "errors": self.errors,
            "ai_input_tokens": self.ai_input_tokens,
            "ai_output_tokens": self.ai_output_tokens,
            "first_request_at": self.first_request_at,
            "last_request_at": self.last_request_at,
        }


class Subscription(db.Model):
    """Billing subscriptions — replaces BillingManager JSON files."""
    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    key_hash = db.Column(db.String(64), db.ForeignKey("agencies.key_hash"), unique=True, nullable=False)
    plan_id = db.Column(db.String(30), default="pro")
    pricing_level = db.Column(db.String(20), default="retail")
    status = db.Column(db.String(20), default="active")
    email = db.Column(db.String(200))
    agency_name = db.Column(db.String(200))
    stripe_customer_id = db.Column(db.String(100), unique=True, nullable=True)
    stripe_subscription_id = db.Column(db.String(100), unique=True, nullable=True)
    committed_agencies = db.Column(db.Integer, default=0)
    per_agency_rate = db.Column(db.Float, nullable=True)
    tier_label = db.Column(db.String(30), nullable=True)
    current_period_start = db.Column(db.Float, nullable=True)
    current_period_end = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def to_dict(self):
        return {
            "key_hash": self.key_hash,
            "plan_id": self.plan_id,
            "pricing_level": self.pricing_level,
            "status": self.status,
            "email": self.email,
            "agency_name": self.agency_name,
            "stripe_customer_id": self.stripe_customer_id,
            "stripe_subscription_id": self.stripe_subscription_id,
            "committed_agencies": self.committed_agencies,
            "per_agency_rate": self.per_agency_rate,
            "tier_label": self.tier_label,
            "current_period_start": self.current_period_start,
            "current_period_end": self.current_period_end,
        }


class AuditEntry(db.Model):
    """Audit trail — optional DB alternative to JSONL files."""
    __tablename__ = "audit_entries"

    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.String(36), unique=True, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now(), index=True)
    key_hash = db.Column(db.String(64), index=True, nullable=True)
    actor = db.Column(db.String(100))
    action = db.Column(db.String(50), index=True)
    resource = db.Column(db.String(200))
    details_json = db.Column(db.JSON)
    prev_hash = db.Column(db.String(64))
    entry_hash = db.Column(db.String(64))


# ====================================================================
# Network Profile System (Build #S2 — Credential Network)
# ====================================================================


class ProviderProfile(db.Model):
    """Public-facing profile card for an APAi subscriber on the network.

    Every APAi subscriber gets one. Displays their credentials (metadata only,
    never raw secrets), terms summary, and network stats. Other subscribers
    browse these in the directory and request connections.
    """
    __tablename__ = "provider_profiles"

    id = db.Column(db.Integer, primary_key=True)
    key_hash = db.Column(db.String(64), db.ForeignKey("agencies.key_hash"),
                         unique=True, nullable=False, index=True)

    # Display
    display_name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    logo_url = db.Column(db.String(500), nullable=True)
    website_url = db.Column(db.String(500), nullable=True)
    contact_email = db.Column(db.String(200), nullable=True)

    # APAi tier (denormalized for directory filtering)
    apai_tier = db.Column(db.String(20), default="pro")  # pro/enterprise/scale

    # Credential summary (JSON array of credential metadata)
    # [{"type":"gds","system":"amadeus","markets":["US","DE"],"airlines":"ALL"}, ...]
    credentials_summary_json = db.Column(db.JSON, default=list)

    # Network stats (auto-updated)
    network_join_date = db.Column(db.DateTime, server_default=db.func.now())
    total_connections = db.Column(db.Integer, default=0)
    total_bookings_routed = db.Column(db.Integer, default=0)
    avg_response_time_ms = db.Column(db.Float, nullable=True)
    uptime_pct = db.Column(db.Float, default=100.0)
    reputation_score = db.Column(db.Float, default=5.0)  # 1.0-5.0 data-driven

    # Visibility
    is_visible = db.Column(db.Boolean, default=True)  # can hide from directory
    is_accepting_connections = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(),
                           onupdate=db.func.now())

    agency = db.relationship("Agency", backref=db.backref("provider_profile",
                                                           uselist=False))

    def to_dict(self, include_stats=True):
        d = {
            "id": self.id,
            "display_name": self.display_name,
            "description": self.description,
            "logo_url": self.logo_url,
            "website_url": self.website_url,
            "apai_tier": self.apai_tier,
            "credentials_summary": self.credentials_summary_json or [],
            "is_accepting_connections": self.is_accepting_connections,
            "network_join_date": self.network_join_date.isoformat()
                if self.network_join_date else None,
        }
        if include_stats:
            d.update({
                "total_connections": self.total_connections,
                "total_bookings_routed": self.total_bookings_routed,
                "avg_response_time_ms": self.avg_response_time_ms,
                "uptime_pct": round(self.uptime_pct, 1) if self.uptime_pct else None,
                "reputation_score": round(self.reputation_score, 1)
                    if self.reputation_score else None,
            })
        return d


class RoutingTermsCard(db.Model):
    """Machine-readable routing terms that ANASTASiA executes on.

    Each credential listing from a provider has its own terms card with 5 sections:
    Pricing, Coverage, Limits, Relationship, Arbitrage.
    Every field is typed so ANASTASiA can evaluate them programmatically at routing time.
    """
    __tablename__ = "routing_terms_cards"

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("provider_profiles.id"),
                           nullable=False, index=True)

    # Which credential this terms card applies to
    credential_label = db.Column(db.String(100), nullable=False)  # "Amadeus GDS — EU"
    credential_type = db.Column(db.String(30), nullable=False)  # gds/ndc/direct_booking_bridge/hotel/car
    provider_system = db.Column(db.String(50), nullable=False)  # amadeus/sabre/duffel/liteapi/etc.

    # --- Section 1: Pricing ---
    per_query_fee_usd = db.Column(db.Float, default=0.0)  # $/query
    revenue_split_router_pct = db.Column(db.Float, default=70.0)  # % to router (OTA bringing sale)
    revenue_split_host_pct = db.Column(db.Float, default=30.0)  # % to host (credential owner)
    min_booking_value_usd = db.Column(db.Float, nullable=True)  # skip if ticket below
    min_margin_usd = db.Column(db.Float, nullable=True)  # won't route if spread too thin
    pricing_currency = db.Column(db.String(3), default="USD")

    # --- Section 2: Coverage ---
    markets_included_json = db.Column(db.JSON, default=list)  # ["US","GB","DE"]
    markets_excluded_json = db.Column(db.JSON, default=list)  # ["RU","BY"]
    airlines_included_json = db.Column(db.JSON, default=list)  # ["LH","BA"] or ["ALL"]
    airlines_excluded_json = db.Column(db.JSON, default=list)  # ["FR","W6"]
    cabin_classes_json = db.Column(db.JSON, default=list)  # ["economy","business"]
    trip_types_json = db.Column(db.JSON, default=list)  # ["one-way","round-trip"]

    # --- Section 3: Operational Limits ---
    max_queries_per_day = db.Column(db.Integer, nullable=True)
    max_queries_per_hour = db.Column(db.Integer, nullable=True)
    max_bookings_per_day = db.Column(db.Integer, nullable=True)
    available_hours_utc = db.Column(db.String(20), default="00:00-23:59")
    response_time_sla_sec = db.Column(db.Float, default=8.0)
    auto_pause_error_rate_pct = db.Column(db.Float, default=15.0)

    # --- Section 4: Relationship ---
    is_exclusive = db.Column(db.Boolean, default=False)
    min_monthly_volume = db.Column(db.Integer, nullable=True)
    notice_period_days = db.Column(db.Integer, default=30)
    trial_period_days = db.Column(db.Integer, default=0)
    auto_renew = db.Column(db.Boolean, default=True)

    # --- Section 5: Arbitrage Permissions ---
    allow_pos_arbitrage = db.Column(db.Boolean, default=True)
    markup_cap_pct = db.Column(db.Float, nullable=True)  # None = no cap
    price_visibility = db.Column(db.String(15), default="blind")  # blind/transparent

    # Status
    is_published = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(),
                           onupdate=db.func.now())

    profile = db.relationship("ProviderProfile",
                              backref=db.backref("terms_cards", lazy="dynamic"))

    def to_dict(self):
        return {
            "id": self.id,
            "credential_label": self.credential_label,
            "credential_type": self.credential_type,
            "provider_system": self.provider_system,
            "pricing": {
                "per_query_fee_usd": self.per_query_fee_usd,
                "revenue_split": {
                    "router_pct": self.revenue_split_router_pct,
                    "host_pct": self.revenue_split_host_pct,
                },
                "min_booking_value_usd": self.min_booking_value_usd,
                "min_margin_usd": self.min_margin_usd,
                "currency": self.pricing_currency,
            },
            "coverage": {
                "markets_included": self.markets_included_json or [],
                "markets_excluded": self.markets_excluded_json or [],
                "airlines_included": self.airlines_included_json or [],
                "airlines_excluded": self.airlines_excluded_json or [],
                "cabin_classes": self.cabin_classes_json or [],
                "trip_types": self.trip_types_json or [],
            },
            "limits": {
                "max_queries_per_day": self.max_queries_per_day,
                "max_queries_per_hour": self.max_queries_per_hour,
                "max_bookings_per_day": self.max_bookings_per_day,
                "available_hours_utc": self.available_hours_utc,
                "response_time_sla_sec": self.response_time_sla_sec,
                "auto_pause_error_rate_pct": self.auto_pause_error_rate_pct,
            },
            "relationship": {
                "is_exclusive": self.is_exclusive,
                "min_monthly_volume": self.min_monthly_volume,
                "notice_period_days": self.notice_period_days,
                "trial_period_days": self.trial_period_days,
                "auto_renew": self.auto_renew,
            },
            "arbitrage": {
                "allow_pos_arbitrage": self.allow_pos_arbitrage,
                "markup_cap_pct": self.markup_cap_pct,
                "price_visibility": self.price_visibility,
            },
            "is_published": self.is_published,
        }


class NetworkConnection(db.Model):
    """Active connection between two APAi subscribers.

    The requester wants to route through the provider's credentials.
    Once accepted, ANASTASiA can route searches/bookings through this connection
    using the agreed terms card.
    """
    __tablename__ = "network_connections"

    id = db.Column(db.Integer, primary_key=True)

    # Who is connecting to whom
    requester_key_hash = db.Column(db.String(64), db.ForeignKey("agencies.key_hash"),
                                   nullable=False, index=True)
    provider_key_hash = db.Column(db.String(64), db.ForeignKey("agencies.key_hash"),
                                  nullable=False, index=True)

    # Which terms card governs this connection
    terms_card_id = db.Column(db.Integer, db.ForeignKey("routing_terms_cards.id"),
                              nullable=True)

    # Status: pending/active/paused/disconnected
    status = db.Column(db.String(20), default="pending", index=True)

    # Per-connection overrides (provider can customize terms per connection)
    custom_query_fee_usd = db.Column(db.Float, nullable=True)  # overrides card default
    custom_router_pct = db.Column(db.Float, nullable=True)
    custom_host_pct = db.Column(db.Float, nullable=True)

    # Stats (auto-updated)
    queries_this_month = db.Column(db.Integer, default=0)
    bookings_this_month = db.Column(db.Integer, default=0)
    revenue_earned_this_month_usd = db.Column(db.Float, default=0.0)
    revenue_paid_this_month_usd = db.Column(db.Float, default=0.0)
    total_queries_lifetime = db.Column(db.Integer, default=0)
    total_bookings_lifetime = db.Column(db.Integer, default=0)
    avg_response_time_ms = db.Column(db.Float, nullable=True)
    error_count_this_month = db.Column(db.Integer, default=0)

    # Health: green/yellow/red (auto-calculated)
    health = db.Column(db.String(10), default="green")

    # Trial tracking
    trial_ends_at = db.Column(db.DateTime, nullable=True)

    # Timestamps
    requested_at = db.Column(db.DateTime, server_default=db.func.now())
    accepted_at = db.Column(db.DateTime, nullable=True)
    paused_at = db.Column(db.DateTime, nullable=True)
    disconnected_at = db.Column(db.DateTime, nullable=True)

    # Message from requester
    request_message = db.Column(db.Text, nullable=True)

    terms_card = db.relationship("RoutingTermsCard")
    requester = db.relationship("Agency", foreign_keys=[requester_key_hash])
    provider = db.relationship("Agency", foreign_keys=[provider_key_hash])

    __table_args__ = (
        db.UniqueConstraint("requester_key_hash", "provider_key_hash",
                            name="uq_connection_pair"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "requester_key_hash": self.requester_key_hash[:8] + "...",
            "provider_key_hash": self.provider_key_hash[:8] + "...",
            "terms_card_id": self.terms_card_id,
            "status": self.status,
            "health": self.health,
            "stats": {
                "queries_this_month": self.queries_this_month,
                "bookings_this_month": self.bookings_this_month,
                "revenue_earned_this_month_usd": round(
                    self.revenue_earned_this_month_usd, 2),
                "revenue_paid_this_month_usd": round(
                    self.revenue_paid_this_month_usd, 2),
                "total_queries_lifetime": self.total_queries_lifetime,
                "total_bookings_lifetime": self.total_bookings_lifetime,
                "avg_response_time_ms": self.avg_response_time_ms,
                "error_count_this_month": self.error_count_this_month,
            },
            "requested_at": self.requested_at.isoformat()
                if self.requested_at else None,
            "accepted_at": self.accepted_at.isoformat()
                if self.accepted_at else None,
        }


class RoutingEvent(db.Model):
    """Immutable ledger of every routing event — the transaction audit trail.

    Every time ANASTASiA routes a search or booking through the network,
    it's logged here. Serves as the source of truth for billing, disputes,
    and analytics.
    """
    __tablename__ = "routing_events"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(36), unique=True, nullable=False, index=True)
    connection_id = db.Column(db.Integer, db.ForeignKey("network_connections.id"),
                              nullable=False, index=True)

    # Event type: search/booking/failure/timeout
    event_type = db.Column(db.String(20), nullable=False, index=True)

    # Participants
    router_key_hash = db.Column(db.String(64), nullable=False, index=True)
    host_key_hash = db.Column(db.String(64), nullable=False, index=True)

    # Financial (null for searches unless per-query fee applies)
    query_fee_usd = db.Column(db.Float, default=0.0)
    transaction_amount_usd = db.Column(db.Float, nullable=True)  # booking value
    router_amount_usd = db.Column(db.Float, nullable=True)
    host_amount_usd = db.Column(db.Float, nullable=True)

    # Routing metadata
    credential_type = db.Column(db.String(30), nullable=True)
    provider_system = db.Column(db.String(50), nullable=True)
    route_origin = db.Column(db.String(10), nullable=True)  # IATA
    route_destination = db.Column(db.String(10), nullable=True)  # IATA
    market_code = db.Column(db.String(5), nullable=True)

    # Performance
    response_time_ms = db.Column(db.Integer, nullable=True)
    success = db.Column(db.Boolean, default=True)
    error_message = db.Column(db.Text, nullable=True)

    # Immutable timestamp
    created_at = db.Column(db.DateTime, server_default=db.func.now(), index=True)

    connection = db.relationship("NetworkConnection",
                                 backref=db.backref("routing_events", lazy="dynamic"))

    def to_dict(self):
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "connection_id": self.connection_id,
            "query_fee_usd": round(self.query_fee_usd, 4),
            "transaction_amount_usd": round(self.transaction_amount_usd, 2)
                if self.transaction_amount_usd else None,
            "router_amount_usd": round(self.router_amount_usd, 2)
                if self.router_amount_usd else None,
            "host_amount_usd": round(self.host_amount_usd, 2)
                if self.host_amount_usd else None,
            "credential_type": self.credential_type,
            "route": f"{self.route_origin}-{self.route_destination}"
                if self.route_origin else None,
            "response_time_ms": self.response_time_ms,
            "success": self.success,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TerminalSession(db.Model):
    """ANASTASiA Terminal session — persists conversation context per developer.

    Each developer on an APAi subscriber's team gets their own terminal sessions.
    Sessions track query usage for billing and maintain conversation context
    so ANASTASiA remembers what the developer was working on.
    """
    __tablename__ = "terminal_sessions"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(36), unique=True, nullable=False, index=True)
    key_hash = db.Column(db.String(64), db.ForeignKey("agencies.key_hash"),
                         nullable=False, index=True)

    # Developer identity (for team seat tracking)
    developer_email = db.Column(db.String(200), nullable=True)
    developer_name = db.Column(db.String(200), nullable=True)

    # Session state
    title = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(15), default="active")  # active/closed
    message_count = db.Column(db.Integer, default=0)
    queries_used = db.Column(db.Integer, default=0)  # billed queries in this session

    # Context (serialized conversation for resumption)
    context_json = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    last_active_at = db.Column(db.DateTime, server_default=db.func.now())
    closed_at = db.Column(db.DateTime, nullable=True)

    agency = db.relationship("Agency",
                             backref=db.backref("terminal_sessions", lazy="dynamic"))

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "title": self.title,
            "status": self.status,
            "developer_email": self.developer_email,
            "message_count": self.message_count,
            "queries_used": self.queries_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_active_at": self.last_active_at.isoformat()
                if self.last_active_at else None,
        }


class CustomModule(db.Model):
    """Custom SDK module built and deployed via ANASTASiA Terminal.

    Tracks the lifecycle: draft → audit → sandbox → deployed → published.
    ANASTASiA audits code for security, compatibility, and performance
    before allowing production deployment.
    """
    __tablename__ = "custom_modules"

    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.String(36), unique=True, nullable=False, index=True)
    key_hash = db.Column(db.String(64), db.ForeignKey("agencies.key_hash"),
                         nullable=False, index=True)

    # Module metadata
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    version = db.Column(db.String(20), default="0.1.0")
    module_type = db.Column(db.String(30), default="feature")
    # Types: feature/vertical/integration/report/webhook/ui_component

    # Lifecycle: draft → auditing → sandbox → deployed → published / rejected
    status = db.Column(db.String(20), default="draft", index=True)

    # Audit results (populated by ANASTASiA)
    audit_result_json = db.Column(db.JSON, nullable=True)
    # {"security": "pass", "compatibility": "pass", "performance": "warn",
    #  "issues": [...], "audited_at": "...", "audited_by": "anastasia"}

    # Deployment
    deployed_at = db.Column(db.DateTime, nullable=True)
    deploy_error = db.Column(db.Text, nullable=True)
    rollback_available = db.Column(db.Boolean, default=False)

    # Marketplace (optional)
    is_marketplace_listed = db.Column(db.Boolean, default=False)
    marketplace_description = db.Column(db.Text, nullable=True)
    marketplace_installs = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(),
                           onupdate=db.func.now())

    agency = db.relationship("Agency",
                             backref=db.backref("custom_modules", lazy="dynamic"))

    def to_dict(self):
        return {
            "module_id": self.module_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "module_type": self.module_type,
            "status": self.status,
            "audit_result": self.audit_result_json,
            "is_marketplace_listed": self.is_marketplace_listed,
            "marketplace_installs": self.marketplace_installs,
            "deployed_at": self.deployed_at.isoformat()
                if self.deployed_at else None,
            "created_at": self.created_at.isoformat()
                if self.created_at else None,
        }
