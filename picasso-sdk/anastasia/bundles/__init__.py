"""
Bundle Engine — Vacation package compositor for ANASTASiA.

Combines selections from multiple verticals (flights, hotels, cars, activities)
into a single bookable bundle with unified pricing. The bundle engine applies
customer-specific markup rules and calculates total savings.

Bundle Flow:
    1. User searches via SearchDispatcher → results per vertical
    2. User selects items from each vertical (flight, hotel, car, etc.)
    3. BundleBuilder combines selections → Bundle with total pricing
    4. Pricing rules apply markup per customer/tier
    5. Bundle submitted for booking → each item routed to its vertical

Pricing Model:
    - Each item has a base price (what the provider charges us)
    - Customer markup rules apply on top (per-tier, per-vertical, or flat)
    - Bundle discount can reduce total (e.g., 5% off when booking 3+ items)
    - Final price = sum of marked-up items - bundle discount

ALL pricing calculations are deterministic — ZERO AI tokens consumed.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger("anastasia.bundles")


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class BundleItem:
    """
    A single item selected for inclusion in a bundle.

    Each item references a specific search result from a vertical.
    """
    item_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    vertical: str = ""            # "flights", "hotels", "cars", "activities"
    provider: str = ""            # API source (e.g., "picasso", "liteapi")
    description: str = ""         # Human-readable summary
    base_price_usd: float = 0.0  # What the provider charges us (cost)
    retail_price_usd: float = 0.0  # What consumer would pay elsewhere
    markup_usd: float = 0.0      # Our markup (calculated by pricing rules)
    final_price_usd: float = 0.0 # base_price + markup = what customer pays
    savings_usd: float = 0.0     # retail_price - final_price
    # Vertical-specific data (flight details, hotel info, etc.)
    details: Dict[str, Any] = field(default_factory=dict)
    # Reference back to the search result
    search_result_id: Optional[str] = None
    # Booking metadata
    booking_reference: Optional[str] = None
    booking_status: str = "pending"  # pending, confirmed, failed, cancelled

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "vertical": self.vertical,
            "provider": self.provider,
            "description": self.description,
            "base_price_usd": self.base_price_usd,
            "retail_price_usd": self.retail_price_usd,
            "markup_usd": self.markup_usd,
            "final_price_usd": self.final_price_usd,
            "savings_usd": self.savings_usd,
            "details": self.details,
            "search_result_id": self.search_result_id,
            "booking_reference": self.booking_reference,
            "booking_status": self.booking_status,
        }


@dataclass
class PricingRules:
    """
    Customer-specific pricing rules applied to bundles.

    These rules determine markup percentages per vertical, bundle
    discounts for multi-item bookings, and floor/ceiling prices.
    """
    # Markup as percentage of savings (default per pyramid model)
    markup_pct_by_vertical: Dict[str, float] = field(default_factory=lambda: {
        "flights": 0.35,     # 35% of savings for consumer
        "hotels": 0.35,
        "cars": 0.30,
        "activities": 0.25,
    })
    # Override: flat markup in USD (takes precedence if set)
    flat_markup_usd: Optional[float] = None
    # Bundle discount: percentage off total when booking N+ items
    bundle_discount_pct: float = 0.0
    bundle_discount_min_items: int = 3   # Minimum items for discount
    # Floor and ceiling per item
    min_markup_usd: float = 3.0
    max_markup_usd: float = 50.0
    # Tier (affects default markup percentages)
    tier: str = "consumer"

    def get_markup_pct(self, vertical: str) -> float:
        """Get the markup percentage for a specific vertical."""
        return self.markup_pct_by_vertical.get(vertical, 0.35)

    def to_dict(self) -> dict:
        return {
            "markup_pct_by_vertical": dict(self.markup_pct_by_vertical),
            "flat_markup_usd": self.flat_markup_usd,
            "bundle_discount_pct": self.bundle_discount_pct,
            "bundle_discount_min_items": self.bundle_discount_min_items,
            "min_markup_usd": self.min_markup_usd,
            "max_markup_usd": self.max_markup_usd,
            "tier": self.tier,
        }


# Default pricing rules by tier (align with pyramid model)
TIER_PRICING_RULES = {
    "consumer": PricingRules(
        markup_pct_by_vertical={
            "flights": 0.50, "hotels": 0.50, "cars": 0.45, "activities": 0.40,
        },
        tier="consumer",
    ),
    "b2b": PricingRules(
        markup_pct_by_vertical={
            "flights": 0.25, "hotels": 0.25, "cars": 0.20, "activities": 0.15,
        },
        bundle_discount_pct=0.05,
        tier="b2b",
    ),
    "starter": PricingRules(
        markup_pct_by_vertical={
            "flights": 0.20, "hotels": 0.20, "cars": 0.15, "activities": 0.10,
        },
        bundle_discount_pct=0.05,
        tier="starter",
    ),
    "pro": PricingRules(
        markup_pct_by_vertical={
            "flights": 0.10, "hotels": 0.10, "cars": 0.08, "activities": 0.05,
        },
        bundle_discount_pct=0.07,
        tier="pro",
    ),
    "enterprise": PricingRules(
        markup_pct_by_vertical={
            "flights": 0.05, "hotels": 0.05, "cars": 0.04, "activities": 0.03,
        },
        bundle_discount_pct=0.10,
        tier="enterprise",
    ),
}


@dataclass
class Bundle:
    """
    A vacation package combining items from multiple verticals.

    The bundle tracks total pricing, per-item breakdowns, and
    overall savings vs retail.
    """
    bundle_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    agency_id: str = ""
    items: List[BundleItem] = field(default_factory=list)
    pricing_rules: PricingRules = field(default_factory=PricingRules)
    # Totals (calculated by apply_pricing)
    subtotal_usd: float = 0.0          # Sum of item final prices
    bundle_discount_usd: float = 0.0   # Discount for multi-item booking
    total_price_usd: float = 0.0       # subtotal - discount
    total_savings_usd: float = 0.0     # What customer saves vs retail
    total_retail_usd: float = 0.0      # What retail would cost
    total_base_usd: float = 0.0        # Our cost (sum of base prices)
    total_markup_usd: float = 0.0      # Our total markup
    # Metadata
    status: str = "draft"              # draft, priced, submitted, confirmed, cancelled
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "bundle_id": self.bundle_id,
            "agency_id": self.agency_id,
            "items": [item.to_dict() for item in self.items],
            "pricing_rules": self.pricing_rules.to_dict(),
            "subtotal_usd": round(self.subtotal_usd, 2),
            "bundle_discount_usd": round(self.bundle_discount_usd, 2),
            "total_price_usd": round(self.total_price_usd, 2),
            "total_savings_usd": round(self.total_savings_usd, 2),
            "total_retail_usd": round(self.total_retail_usd, 2),
            "total_base_usd": round(self.total_base_usd, 2),
            "total_markup_usd": round(self.total_markup_usd, 2),
            "item_count": len(self.items),
            "verticals": list({item.vertical for item in self.items}),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# Bundle Builder
# ---------------------------------------------------------------------------

class BundleBuilder:
    """
    Composes and prices vacation bundles from cross-vertical selections.

    Usage::

        builder = BundleBuilder(event_bus)

        # Create a bundle
        bundle = builder.create_bundle(agency_id="agency_123")

        # Add items from different verticals
        builder.add_item(bundle.bundle_id, BundleItem(
            vertical="flights",
            provider="picasso",
            description="JFK→LHR roundtrip",
            base_price_usd=450,
            retail_price_usd=650,
        ))
        builder.add_item(bundle.bundle_id, BundleItem(
            vertical="hotels",
            provider="liteapi",
            description="Hilton London 3 nights",
            base_price_usd=320,
            retail_price_usd=480,
        ))

        # Apply pricing rules and get final bundle
        priced = builder.apply_pricing(
            bundle.bundle_id,
            PricingRules(tier="b2b"),
        )

        print(priced.total_price_usd)    # 835.00
        print(priced.total_savings_usd)  # 295.00
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self._event_bus = event_bus
        self._bundles: Dict[str, Bundle] = {}

    def create_bundle(
        self,
        agency_id: str = "",
        pricing_rules: Optional[PricingRules] = None,
    ) -> Bundle:
        """Create a new empty bundle."""
        bundle = Bundle(
            agency_id=agency_id,
            pricing_rules=pricing_rules or PricingRules(),
        )
        self._bundles[bundle.bundle_id] = bundle
        logger.info("Bundle created: %s (agency=%s)", bundle.bundle_id, agency_id)
        return bundle

    def get_bundle(self, bundle_id: str) -> Optional[Bundle]:
        """Get a bundle by ID."""
        return self._bundles.get(bundle_id)

    def add_item(self, bundle_id: str, item: BundleItem) -> Optional[Bundle]:
        """
        Add an item to a bundle.

        Args:
            bundle_id: The bundle to add to.
            item: The BundleItem to add.

        Returns:
            Updated Bundle, or None if bundle not found.
        """
        bundle = self._bundles.get(bundle_id)
        if not bundle:
            logger.warning("Bundle %s not found", bundle_id)
            return None

        bundle.items.append(item)
        bundle.updated_at = time.time()
        bundle.status = "draft"

        logger.info(
            "Added %s item to bundle %s: %s ($%.2f base)",
            item.vertical, bundle_id, item.description, item.base_price_usd,
        )
        return bundle

    def remove_item(self, bundle_id: str, item_id: str) -> Optional[Bundle]:
        """Remove an item from a bundle by item_id."""
        bundle = self._bundles.get(bundle_id)
        if not bundle:
            return None

        bundle.items = [i for i in bundle.items if i.item_id != item_id]
        bundle.updated_at = time.time()
        bundle.status = "draft"
        return bundle

    def apply_pricing(
        self,
        bundle_id: str,
        rules: Optional[PricingRules] = None,
    ) -> Optional[Bundle]:
        """
        Apply pricing rules to calculate final bundle pricing.

        For each item:
        1. Calculate savings = retail_price - base_price
        2. Apply markup = savings * markup_pct (clamped to min/max)
        3. Final price = base_price + markup

        Then for the bundle:
        4. Subtotal = sum of final prices
        5. Bundle discount = subtotal * discount_pct (if enough items)
        6. Total = subtotal - discount

        Args:
            bundle_id: The bundle to price.
            rules: Optional pricing rules override. If None, uses the
                   bundle's existing rules.

        Returns:
            Priced Bundle, or None if bundle not found.
        """
        bundle = self._bundles.get(bundle_id)
        if not bundle:
            return None

        if rules:
            bundle.pricing_rules = rules

        pr = bundle.pricing_rules

        # Price each item
        for item in bundle.items:
            savings = max(item.retail_price_usd - item.base_price_usd, 0)

            if pr.flat_markup_usd is not None:
                markup = pr.flat_markup_usd
            else:
                markup_pct = pr.get_markup_pct(item.vertical)
                markup = savings * markup_pct

            # Clamp to floor/ceiling
            markup = max(pr.min_markup_usd, min(markup, pr.max_markup_usd))

            item.markup_usd = round(markup, 2)
            item.final_price_usd = round(item.base_price_usd + markup, 2)
            item.savings_usd = round(
                item.retail_price_usd - item.final_price_usd, 0,
            )

        # Calculate bundle totals
        bundle.subtotal_usd = sum(i.final_price_usd for i in bundle.items)
        bundle.total_retail_usd = sum(i.retail_price_usd for i in bundle.items)
        bundle.total_base_usd = sum(i.base_price_usd for i in bundle.items)
        bundle.total_markup_usd = sum(i.markup_usd for i in bundle.items)

        # Bundle discount
        if (
            pr.bundle_discount_pct > 0
            and len(bundle.items) >= pr.bundle_discount_min_items
        ):
            bundle.bundle_discount_usd = round(
                bundle.subtotal_usd * pr.bundle_discount_pct, 2,
            )
        else:
            bundle.bundle_discount_usd = 0.0

        bundle.total_price_usd = round(
            bundle.subtotal_usd - bundle.bundle_discount_usd, 2,
        )
        bundle.total_savings_usd = round(
            bundle.total_retail_usd - bundle.total_price_usd, 2,
        )

        bundle.status = "priced"
        bundle.updated_at = time.time()

        logger.info(
            "Bundle %s priced: %d items, $%.2f total (saves $%.2f vs retail)",
            bundle_id, len(bundle.items),
            bundle.total_price_usd, bundle.total_savings_usd,
        )

        return bundle

    def apply_tier_pricing(
        self,
        bundle_id: str,
        tier: str,
    ) -> Optional[Bundle]:
        """
        Convenience method: apply pricing rules for a specific tier.

        Uses the TIER_PRICING_RULES defaults for the given tier.

        Args:
            bundle_id: The bundle to price.
            tier: One of "consumer", "b2b", "starter", "pro", "enterprise".

        Returns:
            Priced Bundle, or None if bundle not found.
        """
        rules = TIER_PRICING_RULES.get(tier)
        if not rules:
            logger.warning("Unknown tier '%s', falling back to consumer", tier)
            rules = TIER_PRICING_RULES["consumer"]

        return self.apply_pricing(bundle_id, rules)

    def delete_bundle(self, bundle_id: str) -> bool:
        """Delete a bundle."""
        if bundle_id in self._bundles:
            del self._bundles[bundle_id]
            return True
        return False

    def list_bundles(
        self,
        agency_id: Optional[str] = None,
    ) -> List[Bundle]:
        """List all bundles, optionally filtered by agency."""
        bundles = list(self._bundles.values())
        if agency_id:
            bundles = [b for b in bundles if b.agency_id == agency_id]
        return bundles

    def get_stats(self) -> Dict[str, Any]:
        """Return bundle builder statistics."""
        all_bundles = list(self._bundles.values())
        priced = [b for b in all_bundles if b.status == "priced"]
        return {
            "total_bundles": len(all_bundles),
            "priced_bundles": len(priced),
            "total_items": sum(len(b.items) for b in all_bundles),
            "total_value_usd": sum(b.total_price_usd for b in priced),
            "total_savings_usd": sum(b.total_savings_usd for b in priced),
        }


__all__ = [
    "BundleItem",
    "PricingRules",
    "Bundle",
    "BundleBuilder",
    "TIER_PRICING_RULES",
]
