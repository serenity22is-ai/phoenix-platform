"""
ANASTASIA — AI Flight Booking Agent + OTA Platform by MYSTES KYRIOS LLC.

Components:
    BookingAgent     — Conversational AI booking agent (Claude-powered)
    AssistAgent      — Unified assistant (booking + integration + admin)
    PricingModel     — Configurable per-agency pricing engine
    AgencyConfig     — Per-tenant configuration (pricing, display, branding)
    ConfigStore      — Persistent agency config storage
    AdminAuth        — Admin authentication for code mutations
    AuditLog         — Agent action audit trail
    AutoHealDaemon   — Background health monitor + auto-fix
    BillingManager   — Stripe subscriptions + usage metering
    UsageTracker     — Per-agency usage counters
    OnboardingManager— Self-service agency signup
    AnalyticsEngine  — Usage dashboards + business intelligence
    ErrorTracker     — Error rate tracking + classification
    TOOL_DEFINITIONS — Claude function calling tool schemas
    KNOWLEDGE_BASE   — AI system prompt (Redbox API expertise)
    create_app       — Flask API factory
    generate_api_key — Mint new agency API keys

MYSTES KYRIOS LLC — Confidential.
"""

from .orchestrator import BookingAgent
from .assist import AssistAgent
from .tools import TOOL_DEFINITIONS
from .knowledge_base import KNOWLEDGE_BASE
from .pricing import PricingModel, apply_pricing_to_results
from .config import AgencyConfig, ConfigStore
from .security import AdminAuth, AuditLog, ActionType, generate_admin_token, hash_token
from .daemon import AutoHealDaemon
from .billing import (
    BillingManager, UsageTracker, BillingPlan, PLANS,
    PARTNER_VOLUME_TIERS, get_partner_rate, get_partner_quote,
)
from .onboarding import OnboardingManager
from .analytics import AnalyticsEngine, ErrorTracker
from .api import create_app, generate_api_key

__all__ = [
    "BookingAgent",
    "AssistAgent",
    "TOOL_DEFINITIONS",
    "KNOWLEDGE_BASE",
    "PricingModel",
    "apply_pricing_to_results",
    "AgencyConfig",
    "ConfigStore",
    "AdminAuth",
    "AuditLog",
    "ActionType",
    "generate_admin_token",
    "hash_token",
    "AutoHealDaemon",
    "BillingManager",
    "UsageTracker",
    "BillingPlan",
    "PLANS",
    "PARTNER_VOLUME_TIERS",
    "get_partner_rate",
    "get_partner_quote",
    "OnboardingManager",
    "AnalyticsEngine",
    "ErrorTracker",
    "create_app",
    "generate_api_key",
]
