"""
Pricing Engine — Configurable per-agency pricing models.

Each OTA gets to define how they mark up fares. The engine takes raw
Redbox search results and applies the agency's pricing rules to produce
consumer-facing prices.

Supports multiple pricing strategies:
- Flat fee per ticket
- Percentage of base fare
- Percentage of total fare (including taxes)
- Savings-split model (ANASTASIA model: split the savings between agency and consumer)
- Tiered by cabin class
- Combined (base markup + per-ticket fee)

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PricingModel:
    """
    Defines how an agency marks up fares.

    One PricingModel per agency. Configured via admin API, stored in
    agency config.
    """

    # Pricing strategy constants
    FLAT_FEE = "flat_fee"               # Fixed dollar amount per ticket
    PERCENT_BASE = "percent_base"       # Percentage of base fare (before tax)
    PERCENT_TOTAL = "percent_total"     # Percentage of total fare (after tax)
    SAVINGS_SPLIT = "savings_split"     # Split savings vs benchmark price
    TIERED = "tiered"                   # Different rules per cabin class

    VALID_STRATEGIES = {FLAT_FEE, PERCENT_BASE, PERCENT_TOTAL, SAVINGS_SPLIT, TIERED}

    def __init__(
        self,
        strategy: str = "percent_total",
        markup_percent: float = 10.0,
        markup_flat: float = 0.0,
        min_markup: float = 0.0,
        max_markup: float = 999.0,
        savings_split_percent: float = 50.0,
        benchmark_source: str = "google",
        cabin_tiers: Optional[dict] = None,
        display_currency: str = "USD",
        round_to: int = 2,
    ):
        """
        Args:
            strategy: Pricing strategy (see VALID_STRATEGIES)
            markup_percent: Percentage markup (for percent_base/percent_total)
            markup_flat: Flat fee per ticket in USD (for flat_fee, or added on top)
            min_markup: Minimum markup per ticket in USD
            max_markup: Maximum markup per ticket in USD
            savings_split_percent: Agency's share of savings (for savings_split)
            benchmark_source: Price benchmark for savings_split ("google" or "published")
            cabin_tiers: Per-cabin overrides {"ECONOMY": {"percent": 10}, "BUSINESS": {"percent": 5}}
            display_currency: Currency to display prices in
            round_to: Decimal places for rounding
        """
        if strategy not in self.VALID_STRATEGIES:
            raise ValueError(f"Invalid strategy: {strategy}. Must be one of {self.VALID_STRATEGIES}")

        self.strategy = strategy
        self.markup_percent = markup_percent
        self.markup_flat = markup_flat
        self.min_markup = min_markup
        self.max_markup = max_markup
        self.savings_split_percent = savings_split_percent
        self.benchmark_source = benchmark_source
        self.cabin_tiers = cabin_tiers or {}
        self.display_currency = display_currency
        self.round_to = round_to

    def calculate(
        self,
        base_fare: float,
        tax: float,
        ticket_fee: float = 0.0,
        cabin_class: str = "ECONOMY",
        benchmark_price: Optional[float] = None,
    ) -> dict:
        """
        Calculate consumer-facing price from raw fare components.

        Args:
            base_fare: Base fare before taxes (per passenger)
            tax: Tax amount
            ticket_fee: Additional ticketing fee
            cabin_class: Cabin class for tiered pricing
            benchmark_price: Consumer benchmark price (for savings_split)

        Returns:
            {
                "cost_price": float,          # What the agency pays (Redbox fare)
                "consumer_price": float,       # What the consumer sees
                "agency_markup": float,        # Agency's margin
                "savings_vs_benchmark": float, # Consumer savings vs benchmark (if applicable)
                "savings_percent": float,      # Savings as percentage
                "breakdown": {
                    "base_fare": float,
                    "tax": float,
                    "ticket_fee": float,
                    "markup": float,
                }
            }
        """
        cost_price = base_fare + tax + ticket_fee

        if self.strategy == self.FLAT_FEE:
            markup = self.markup_flat

        elif self.strategy == self.PERCENT_BASE:
            pct = self._get_percent(cabin_class)
            markup = base_fare * (pct / 100.0) + self.markup_flat

        elif self.strategy == self.PERCENT_TOTAL:
            pct = self._get_percent(cabin_class)
            markup = cost_price * (pct / 100.0) + self.markup_flat

        elif self.strategy == self.SAVINGS_SPLIT:
            if benchmark_price and benchmark_price > cost_price:
                total_savings = benchmark_price - cost_price
                markup = total_savings * (self.savings_split_percent / 100.0)
            else:
                # No savings — fall back to flat fee or minimum
                markup = self.markup_flat

        elif self.strategy == self.TIERED:
            pct = self._get_percent(cabin_class)
            markup = cost_price * (pct / 100.0) + self.markup_flat

        else:
            markup = 0.0

        # Apply min/max bounds
        markup = max(self.min_markup, min(self.max_markup, markup))
        markup = round(markup, self.round_to)

        consumer_price = round(cost_price + markup, self.round_to)

        # Calculate savings vs benchmark
        savings = 0.0
        savings_pct = 0.0
        if benchmark_price and benchmark_price > consumer_price:
            savings = round(benchmark_price - consumer_price, self.round_to)
            savings_pct = round((savings / benchmark_price) * 100, 1)

        return {
            "cost_price": round(cost_price, self.round_to),
            "consumer_price": consumer_price,
            "agency_markup": markup,
            "savings_vs_benchmark": savings,
            "savings_percent": savings_pct,
            "currency": self.display_currency,
            "breakdown": {
                "base_fare": round(base_fare, self.round_to),
                "tax": round(tax, self.round_to),
                "ticket_fee": round(ticket_fee, self.round_to),
                "markup": markup,
            },
        }

    def _get_percent(self, cabin_class: str) -> float:
        """Get markup percentage, with cabin-tier override if configured."""
        if cabin_class in self.cabin_tiers:
            return self.cabin_tiers[cabin_class].get("percent", self.markup_percent)
        return self.markup_percent

    def to_dict(self) -> dict:
        """Serialize pricing model to dict (for storage/API)."""
        return {
            "strategy": self.strategy,
            "markup_percent": self.markup_percent,
            "markup_flat": self.markup_flat,
            "min_markup": self.min_markup,
            "max_markup": self.max_markup,
            "savings_split_percent": self.savings_split_percent,
            "benchmark_source": self.benchmark_source,
            "cabin_tiers": self.cabin_tiers,
            "display_currency": self.display_currency,
            "round_to": self.round_to,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PricingModel":
        """Deserialize pricing model from dict."""
        return cls(**{k: v for k, v in data.items() if k in cls.__init__.__code__.co_varnames})


def apply_pricing_to_results(flights: list, pricing: PricingModel, benchmark_prices: Optional[dict] = None) -> list:
    """
    Apply agency pricing to a list of flight search results.

    Args:
        flights: List of parsed flight dicts from RedboxClient.search_flights()
        pricing: Agency's PricingModel
        benchmark_prices: Optional dict mapping fare_id -> benchmark consumer price

    Returns:
        Same flight list with added pricing fields on each flight
    """
    benchmark_prices = benchmark_prices or {}
    priced = []

    for flight in flights:
        base_fare = flight.get("base_fare", 0)
        tax = flight.get("tax", 0)
        ticket_fee = flight.get("ticket_fee", 0)
        cabin = flight.get("cabin_class", "ECONOMY")
        fare_id = flight.get("fare_id", "")

        benchmark = benchmark_prices.get(fare_id)

        price_info = pricing.calculate(
            base_fare=base_fare,
            tax=tax,
            ticket_fee=ticket_fee,
            cabin_class=cabin,
            benchmark_price=benchmark,
        )

        # Add pricing to flight result
        enriched = dict(flight)
        enriched["consumer_price"] = price_info["consumer_price"]
        enriched["agency_markup"] = price_info["agency_markup"]
        enriched["cost_price"] = price_info["cost_price"]
        enriched["savings_vs_benchmark"] = price_info["savings_vs_benchmark"]
        enriched["savings_percent"] = price_info["savings_percent"]
        enriched["price_currency"] = price_info["currency"]
        enriched["price_breakdown"] = price_info["breakdown"]

        priced.append(enriched)

    return priced
