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
