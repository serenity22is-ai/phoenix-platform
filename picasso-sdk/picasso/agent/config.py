"""
Agency Configuration — Per-tenant settings for OTA customization.

Each agency (OTA) that uses our product gets a configuration profile
that controls how their instance behaves: pricing, display, branding,
feature flags, and access controls.

Used by:
- Tier 2 (AI + SDK): Pricing applied to structured search results
- Tier 3 (Full OTA): Pricing + display + branding for white-label template

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import time
from typing import Optional

from .pricing import PricingModel

logger = logging.getLogger(__name__)


class AgencyConfig:
    """
    Complete configuration for one agency/OTA tenant.
    """

    def __init__(
        self,
        # Identity
        agency_id: str = "",
        branch: str = "",
        agency_name: str = "",
        agency_slug: str = "",       # URL-safe identifier (e.g., "acme-travel")

        # Cockpit credentials
        cockpit_username: str = "",
        cockpit_password: str = "",
        totp_secret: str = "",
        session_token: str = "",

        # Pricing
        pricing: Optional[dict] = None,

        # Display settings
        display: Optional[dict] = None,

        # Branding
        branding: Optional[dict] = None,

        # Feature flags
        features: Optional[dict] = None,

        # Access control
        tier: str = "tier2",          # tier1 (SDK), tier2 (AI+SDK), tier3 (full OTA)
        active: bool = True,
        created_at: Optional[float] = None,
    ):
        self.agency_id = agency_id
        self.branch = branch
        self.agency_name = agency_name
        self.agency_slug = agency_slug

        self.cockpit_username = cockpit_username
        self.cockpit_password = cockpit_password
        self.totp_secret = totp_secret
        self.session_token = session_token

        # Pricing model
        self.pricing = PricingModel.from_dict(pricing) if pricing else PricingModel()

        # Display settings — what the OTA's users see
        self.display = {
            "results_per_page": 20,
            "default_sort": "price",           # price, duration, departure, arrival
            "show_baggage": True,
            "show_fare_family": True,
            "show_fare_rules_link": True,
            "show_seatmap_link": True,
            "show_gds_source": False,           # Most OTAs hide this
            "show_savings": True,               # Show "You save $X" badge
            "show_benchmark_price": True,       # Show crossed-out "was $X" price
            "cabin_classes_enabled": ["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"],
            "max_passengers": 9,
            "currency_symbol": "$",
            "date_format": "MMM DD, YYYY",      # Display format for dates
            "time_format": "12h",               # 12h or 24h
        }
        if display:
            self.display.update(display)

        # Branding — OTA's visual identity (Tier 3)
        self.branding = {
            "company_name": agency_name or "Travel Agency",
            "logo_url": "",
            "favicon_url": "",
            "primary_color": "#1a1a2e",         # Dark navy (MYSTES default)
            "accent_color": "#6366f1",          # Indigo
            "heading_font": "Cinzel",           # Serif for headings
            "body_font": "Outfit",              # Sans-serif for body
            "footer_text": "",
            "support_email": "",
            "support_phone": "",
        }
        if branding:
            self.branding.update(branding)

        # Feature flags — what capabilities are enabled
        self.features = {
            "ai_chat": True,                    # Conversational AI booking
            "structured_search": True,          # Form-based search API
            "booking_enabled": True,            # Can create bookings (vs search-only)
            "document_generation": True,        # Generate PDF docs
            "seatmap": True,                    # Seatmap lookup
            "multi_city": False,                # Multi-city search
            "price_alerts": False,              # Price monitoring (future)
            "booking_management": True,         # Search/view existing bookings
            "max_daily_searches": 0,            # 0 = unlimited
            "max_daily_bookings": 0,            # 0 = unlimited
        }
        if features:
            self.features.update(features)

        self.tier = tier
        self.active = active
        self.created_at = created_at or time.time()

    def to_dict(self, include_secrets: bool = False) -> dict:
        """Serialize to dict. Secrets excluded by default."""
        d = {
            "agency_id": self.agency_id,
            "branch": self.branch,
            "agency_name": self.agency_name,
            "agency_slug": self.agency_slug,
            "pricing": self.pricing.to_dict(),
            "display": self.display,
            "branding": self.branding,
            "features": self.features,
            "tier": self.tier,
            "active": self.active,
            "created_at": self.created_at,
        }
        if include_secrets:
            d["cockpit_username"] = self.cockpit_username
            d["cockpit_password"] = self.cockpit_password
            d["totp_secret"] = self.totp_secret
            d["session_token"] = self.session_token
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "AgencyConfig":
        """Deserialize from dict."""
        return cls(**{k: v for k, v in data.items()
                      if k in cls.__init__.__code__.co_varnames})

    def get_admin_view(self) -> dict:
        """What the OTA admin sees — everything except Cockpit credentials."""
        d = self.to_dict(include_secrets=False)
        d.pop("cockpit_username", None)
        d.pop("cockpit_password", None)
        d.pop("totp_secret", None)
        d.pop("session_token", None)
        return d

    def get_public_view(self) -> dict:
        """What end-users can see — branding and display only."""
        return {
            "agency_name": self.agency_name,
            "branding": self.branding,
            "display": {k: v for k, v in self.display.items()
                        if k not in ("max_passengers",)},
            "features": {
                "ai_chat": self.features["ai_chat"],
                "seatmap": self.features["seatmap"],
                "booking_enabled": self.features["booking_enabled"],
            },
        }


class ConfigStore:
    """
    Persistent storage for agency configurations.

    File-based for now (JSON). Can be swapped for database-backed
    storage in production.
    """

    def __init__(self, config_dir: str = ".agency_configs"):
        self.config_dir = config_dir
        os.makedirs(config_dir, exist_ok=True)

    def _path(self, key_hash: str) -> str:
        return os.path.join(self.config_dir, f"{key_hash}.json")

    def get(self, key_hash: str) -> Optional[AgencyConfig]:
        """Load agency config by API key hash."""
        path = self._path(key_hash)
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            return AgencyConfig.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load config for {key_hash[:8]}: {e}")
            return None

    def save(self, key_hash: str, config: AgencyConfig):
        """Save agency config."""
        path = self._path(key_hash)
        with open(path, "w") as f:
            json.dump(config.to_dict(include_secrets=True), f, indent=2)

    def delete(self, key_hash: str):
        """Delete agency config."""
        path = self._path(key_hash)
        if os.path.exists(path):
            os.remove(path)

    def list_all(self) -> list:
        """List all agency configs (without secrets)."""
        configs = []
        for fname in os.listdir(self.config_dir):
            if fname.endswith(".json"):
                key_hash = fname[:-5]
                config = self.get(key_hash)
                if config:
                    configs.append({
                        "key_hash": key_hash,
                        **config.to_dict(include_secrets=False),
                    })
        return configs
