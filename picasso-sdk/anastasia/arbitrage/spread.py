"""
Spread Calculator — POS arbitrage spread and fee computation.

The spread is the difference between the US retail price (what Google/airlines
charge US customers) and the foreign POS price (what the same flight costs
through a non-US point of sale). KYRIOS captures a percentage of this spread
as a service fee, passing the remainder as savings to the customer.

Economics:
    US retail price (SerpAPI baseline):    $1,400
    Foreign POS price (proxy search):      $  800
    Spread:                                $  600
    Service fee (Guest 50%):               $  300
    Customer pays:                         $1,100
    Customer saves vs Google:              $  300 (21%)

Fee tiers from payments.py:get_fee_percent() — SOLE SOURCE OF TRUTH:
    Guest=50%, Free=45%, Travel+=35%, B2B Starter=25%, Growth=20%, Volume=15%
    $3 minimum fee. NO MAXIMUM CAP.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# $3 minimum fee, NO maximum cap (corrected 4+ times — NEVER add a cap)
MINIMUM_FEE_USD = 3.00


# Default FX fee buffer for standard credit cards (2.5%)
# No-FX-fee cards (Chase Sapphire, Capital One, etc.) = 0%
DEFAULT_FX_FEE_PERCENT = 0.025


@dataclass
class SpreadResult:
    """Result of a POS arbitrage spread calculation."""

    us_retail_price: float       # SerpAPI baseline (US price ceiling)
    foreign_pos_price: float     # Cheapest foreign POS price
    foreign_market: str          # ISO code of cheapest POS market (e.g., "DK")
    spread: float                # us_retail - foreign_pos
    fee_percent: float           # User's fee tier (0.50, 0.45, etc.)
    service_fee: float           # spread * fee_percent (min $3)
    customer_price: float        # foreign_pos + service_fee
    customer_savings: float      # us_retail - customer_price
    savings_percent: float       # customer_savings / us_retail * 100
    has_arbitrage: bool          # True if spread > 0 and worth pursuing

    @property
    def kyrios_revenue(self) -> float:
        """Net revenue to KYRIOS (service fee minus Stripe costs)."""
        # Stripe: 2.9% + $0.30
        stripe_fee = self.service_fee * 0.029 + 0.30
        return max(0, self.service_fee - stripe_fee)

    def fx_adjusted(self, fx_fee_percent: float = DEFAULT_FX_FEE_PERCENT) -> dict:
        """Return FX-aware pricing for display.

        The customer books on a foreign airline site, paying in local currency.
        Their credit card applies an FX fee on the foreign_pos_price portion.
        The service fee is charged by MYSTES in USD (no FX).

        Args:
            fx_fee_percent: Card FX fee (0.025 = 2.5% default, 0.0 = no-FX card)
        """
        fx_fee_usd = self.foreign_pos_price * fx_fee_percent
        price_after_fx = self.customer_price + fx_fee_usd
        savings_after_fx = self.us_retail_price - price_after_fx
        savings_pct_after_fx = (
            (savings_after_fx / self.us_retail_price * 100)
            if self.us_retail_price > 0 else 0.0
        )
        return {
            "fx_fee_percent": fx_fee_percent,
            "fx_fee_usd": round(fx_fee_usd, 2),
            "price_after_fx": round(price_after_fx, 2),
            "savings_after_fx": round(savings_after_fx, 2),
            "savings_percent_after_fx": round(savings_pct_after_fx, 1),
            "has_savings_after_fx": savings_after_fx > 0,
        }

    def to_display(self, fx_fee_percent: float = DEFAULT_FX_FEE_PERCENT) -> dict:
        """Return safe display data (no POS market codes — airline compliance).

        Includes FX-aware pricing by default with 2.5% standard card buffer.
        Pass fx_fee_percent=0.0 for no-FX-fee card users.
        """
        fx = self.fx_adjusted(fx_fee_percent)
        return {
            "google_price": round(self.us_retail_price, 2),
            "mystes_price": round(self.customer_price, 2),
            "you_save": round(self.customer_savings, 2),
            "savings_percent": round(self.savings_percent, 1),
            "service_fee": round(self.service_fee, 2),
            "has_savings": self.has_arbitrage and self.customer_savings > 0,
            # FX-aware fields
            "fx_fee_usd": fx["fx_fee_usd"],
            "price_after_fx": fx["price_after_fx"],
            "savings_after_fx": fx["savings_after_fx"],
            "savings_percent_after_fx": fx["savings_percent_after_fx"],
            "has_savings_after_fx": fx["has_savings_after_fx"],
            "no_fx_fee_price": round(self.customer_price, 2),
            "no_fx_fee_savings": round(self.customer_savings, 2),
        }

    def to_internal(self) -> dict:
        """Return full internal data (includes POS market — admin only)."""
        return {
            "us_retail_price": self.us_retail_price,
            "foreign_pos_price": self.foreign_pos_price,
            "foreign_market": self.foreign_market,
            "spread": self.spread,
            "fee_percent": self.fee_percent,
            "service_fee": self.service_fee,
            "customer_price": self.customer_price,
            "customer_savings": self.customer_savings,
            "savings_percent": self.savings_percent,
            "kyrios_revenue": self.kyrios_revenue,
            "has_arbitrage": self.has_arbitrage,
        }


class SpreadCalculator:
    """
    Calculates POS arbitrage spreads and service fees.

    This is the core pricing engine for MYSTES. It takes a US retail price
    and a foreign POS price, computes the spread, applies the user's fee
    tier, and returns what the customer pays.
    """

    def calculate(
        self,
        us_retail_price: float,
        foreign_pos_price: float,
        foreign_market: str,
        fee_percent: float,
    ) -> SpreadResult:
        """Calculate spread and pricing for a POS arbitrage opportunity.

        Args:
            us_retail_price: US retail price from SerpAPI (ceiling)
            foreign_pos_price: Foreign POS price from proxy search
            foreign_market: ISO code of foreign POS market
            fee_percent: User's fee tier from get_fee_percent()

        Returns:
            SpreadResult with full pricing breakdown
        """
        spread = us_retail_price - foreign_pos_price

        if spread <= 0:
            # No arbitrage opportunity
            return SpreadResult(
                us_retail_price=us_retail_price,
                foreign_pos_price=foreign_pos_price,
                foreign_market=foreign_market,
                spread=0.0,
                fee_percent=fee_percent,
                service_fee=0.0,
                customer_price=foreign_pos_price,
                customer_savings=0.0,
                savings_percent=0.0,
                has_arbitrage=False,
            )

        # Calculate service fee: spread * fee_percent, minimum $3
        raw_fee = spread * fee_percent
        service_fee = max(raw_fee, MINIMUM_FEE_USD)

        # Customer pays: foreign POS price + service fee
        customer_price = foreign_pos_price + service_fee

        # Customer savings vs US retail
        customer_savings = us_retail_price - customer_price
        savings_percent = (
            (customer_savings / us_retail_price * 100)
            if us_retail_price > 0
            else 0.0
        )

        # Only flag as arbitrage if customer actually saves money
        has_arbitrage = customer_savings > 0

        return SpreadResult(
            us_retail_price=us_retail_price,
            foreign_pos_price=foreign_pos_price,
            foreign_market=foreign_market,
            spread=spread,
            fee_percent=fee_percent,
            service_fee=service_fee,
            customer_price=customer_price,
            customer_savings=customer_savings,
            savings_percent=savings_percent,
            has_arbitrage=has_arbitrage,
        )

    def calculate_multi_market(
        self,
        us_retail_price: float,
        market_prices: dict,
        fee_percent: float,
    ) -> Optional[SpreadResult]:
        """Calculate spread across multiple POS markets, return best.

        Args:
            us_retail_price: US retail price from SerpAPI
            market_prices: {market_code: price_usd} from proxy searches
            fee_percent: User's fee tier

        Returns:
            Best SpreadResult (highest customer savings), or None if no arbitrage
        """
        if not market_prices:
            return None

        best: Optional[SpreadResult] = None

        for market, price in market_prices.items():
            result = self.calculate(us_retail_price, price, market, fee_percent)
            if result.has_arbitrage:
                if best is None or result.customer_savings > best.customer_savings:
                    best = result

        return best


__all__ = ["SpreadCalculator", "SpreadResult", "MINIMUM_FEE_USD", "DEFAULT_FX_FEE_PERCENT"]
