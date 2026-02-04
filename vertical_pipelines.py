"""
PHOENIX Multi-Vertical Processing Pipelines

Processes CitizenSERP task results into structured arbitrage data for
each vertical: flights, hotels, products, and marketplace.

Each pipeline:
1. Takes raw extraction data from CitizenSERP nodes
2. Normalizes prices (currency conversion, tax estimation, shipping)
3. Detects cross-market arbitrage opportunities
4. Records intelligence data for future queries
5. Returns actionable results to the user

Verticals:
    flights:     Price comparison across markets for same route
    hotels:      Nightly rate comparison by market for same property/area
    products:    Product price + shipping + duty = landed cost by market
    marketplace: Listing discovery + fair value assessment across markets
    cruises:     Cruise package comparison per-person-per-night across markets
    ecommerce:   Broad e-commerce product comparison with landed cost
    digital:     Digital goods/software regional price comparison
    transfers:   Ground transportation (cars, taxis, shuttles) via Amadeus + SERP

Fee Engine:
    arbitrage:      % of savings (25% standard, reduced by rewards tiers)
    private_market: Flat $1.50 + 1% of deal value

Usage:
    from vertical_pipelines import pipeline_manager

    # Process flight search results from multiple markets
    result = pipeline_manager.process_flight_results(task_results)

    # Process hotel results
    result = pipeline_manager.process_hotel_results(task_results)
"""

import logging
import re
import string
import time
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median, mean
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# Price Normalizer — Currency + Cost Normalization
# ============================================================

class PriceNormalizer:
    """
    Handles currency conversion and landed-cost estimation.

    Uses cached exchange rates with lazy import from main.py's currency
    helpers when available. Falls back to a built-in rate table for
    offline / test environments.

    All duty and tax estimates are APPROXIMATIONS based on average rates.
    Real duty rates depend on HS classification, trade agreements,
    product category, and declared value. These estimates exist to give
    users a rough landed-cost comparison, not customs-grade accuracy.
    """

    # Built-in fallback exchange rates (to USD).
    # Updated periodically; the lazy-imported live rates take priority.
    _FALLBACK_RATES_TO_USD = {
        "USD": 1.0,
        "EUR": 1.08,
        "GBP": 1.26,
        "JPY": 0.0067,
        "CNY": 0.14,
        "KRW": 0.00075,
        "INR": 0.012,
        "CAD": 0.74,
        "AUD": 0.65,
        "SGD": 0.74,
        "THB": 0.028,
        "MXN": 0.058,
        "BRL": 0.20,
        "AED": 0.27,
        "TRY": 0.031,
        "SEK": 0.095,
        "NOK": 0.093,
        "DKK": 0.145,
        "CHF": 1.12,
        "NZD": 0.61,
        "HKD": 0.13,
        "TWD": 0.031,
        "MYR": 0.22,
        "PHP": 0.018,
        "IDR": 0.000063,
        "VND": 0.000041,
        "ZAR": 0.055,
        "PLN": 0.25,
        "CZK": 0.044,
        "HUF": 0.0027,
        "CLP": 0.0011,
        "COP": 0.00025,
        "ARS": 0.0011,
        "EGP": 0.020,
        "SAR": 0.27,
        "QAR": 0.27,
        "KWD": 3.26,
        "BHD": 2.65,
        "ILS": 0.28,
    }

    # Approximate average import duty rates by destination country.
    # These are general-goods averages. Electronics, clothing, food,
    # luxury items, etc. all have different rates. Use as rough guide.
    DUTY_RATES = {
        "US": 0.035,    # ~3.5% average (0-6% range for most consumer goods)
        "CA": 0.04,     # ~4% average
        "GB": 0.04,     # ~4% average post-Brexit
        "DE": 0.05,     # EU common external tariff
        "FR": 0.05,
        "IT": 0.05,
        "ES": 0.05,
        "NL": 0.05,
        "EU": 0.05,     # Generic EU fallback
        "JP": 0.04,     # ~4% average
        "KR": 0.08,     # ~8% average
        "CN": 0.10,     # ~10% average
        "IN": 0.12,     # ~12% average (can be much higher)
        "AU": 0.05,     # ~5% average
        "NZ": 0.05,
        "SG": 0.0,      # Singapore: duty-free on most goods
        "HK": 0.0,      # Hong Kong: duty-free on most goods
        "AE": 0.05,     # ~5%
        "BR": 0.14,     # ~14% average (high tariff regime)
        "MX": 0.08,     # ~8% average
        "TH": 0.08,     # ~8% average
        "MY": 0.06,     # ~6% average
        "PH": 0.07,     # ~7% average
        "ID": 0.08,     # ~8% average
        "VN": 0.08,     # ~8% average
        "TW": 0.06,     # ~6% average
        "TR": 0.10,     # ~10% average
        "SA": 0.05,     # ~5%
        "ZA": 0.08,     # ~8% average
    }

    # Sales tax / VAT rates by country (applied on top of product + duty).
    _TAX_RATES = {
        "US": 0.07,     # ~7% average state sales tax (varies 0-10.25%)
        "CA": 0.12,     # ~12% average (GST + provincial)
        "GB": 0.20,     # 20% VAT
        "DE": 0.19,     # 19% VAT
        "FR": 0.20,     # 20% VAT
        "IT": 0.22,     # 22% VAT
        "ES": 0.21,     # 21% VAT
        "NL": 0.21,     # 21% VAT
        "JP": 0.10,     # 10% consumption tax
        "KR": 0.10,     # 10% VAT
        "CN": 0.13,     # 13% VAT (standard rate)
        "IN": 0.18,     # 18% GST (standard rate)
        "AU": 0.10,     # 10% GST
        "NZ": 0.15,     # 15% GST
        "SG": 0.09,     # 9% GST
        "HK": 0.0,      # No sales tax
        "AE": 0.05,     # 5% VAT
        "BR": 0.17,     # ~17% ICMS average
        "MX": 0.16,     # 16% IVA
        "TH": 0.07,     # 7% VAT
        "MY": 0.06,     # 6% SST
        "PH": 0.12,     # 12% VAT
        "ID": 0.11,     # 11% VAT
        "VN": 0.10,     # 10% VAT
        "TW": 0.05,     # 5% VAT
        "TR": 0.20,     # 20% VAT
        "SA": 0.15,     # 15% VAT
        "ZA": 0.15,     # 15% VAT
        "SE": 0.25,     # 25% VAT
        "NO": 0.25,     # 25% VAT
        "DK": 0.25,     # 25% VAT
        "CH": 0.081,    # 8.1% VAT
    }

    def __init__(self):
        self._lock = threading.Lock()
        self._live_rates: Optional[Dict[str, float]] = None
        self._rates_fetched_at: Optional[datetime] = None
        self._rates_ttl = timedelta(hours=1)

    # ----------------------------------------------------------
    # Currency conversion
    # ----------------------------------------------------------

    def _get_rate_to_usd(self, currency: str) -> float:
        """
        Return the exchange rate for 1 unit of *currency* in USD.

        Attempts lazy import of the app's live exchange-rate helper first.
        Falls back to the built-in table.
        """
        currency = currency.upper()
        if currency == "USD":
            return 1.0

        # Try live rates (cached for 1 hour)
        with self._lock:
            if (self._live_rates is None
                    or self._rates_fetched_at is None
                    or datetime.utcnow() - self._rates_fetched_at > self._rates_ttl):
                self._try_refresh_live_rates()

            if self._live_rates and currency in self._live_rates:
                return self._live_rates[currency]

        # Fallback to built-in table
        rate = self._FALLBACK_RATES_TO_USD.get(currency)
        if rate is None:
            logger.warning("No exchange rate for %s — treating as 1:1 with USD", currency)
            return 1.0
        return rate

    def _try_refresh_live_rates(self):
        """Attempt to load live rates from the app's main module."""
        try:
            from main import analyze_currency_options  # noqa: F401
            # The main module stores converted prices keyed by currency;
            # if a dedicated exchange-rate function exists, prefer it.
            logger.debug("Live currency helpers available from main module")
        except ImportError:
            pass

        try:
            from main import app  # noqa: F401
            # Could query the app's DB or config for cached rates here.
            logger.debug("App context available for rate lookup")
        except ImportError:
            pass

        # Mark as attempted even if we failed, so we don't retry every call.
        self._rates_fetched_at = datetime.utcnow()

    def normalize_price(self, amount: float, from_currency: str,
                        to_currency: str = "USD") -> float:
        """
        Convert *amount* from *from_currency* to *to_currency*.

        Args:
            amount: The price value.
            from_currency: ISO 4217 currency code of the source.
            to_currency: ISO 4217 currency code of the target (default USD).

        Returns:
            The converted price as a float, rounded to 2 decimal places.
        """
        if from_currency.upper() == to_currency.upper():
            return round(amount, 2)

        # Convert to USD first, then to target
        usd_amount = amount * self._get_rate_to_usd(from_currency.upper())

        if to_currency.upper() == "USD":
            return round(usd_amount, 2)

        target_rate = self._get_rate_to_usd(to_currency.upper())
        if target_rate == 0:
            logger.error("Zero exchange rate for %s", to_currency)
            return round(usd_amount, 2)

        return round(usd_amount / target_rate, 2)

    # ----------------------------------------------------------
    # Landed cost estimation (physical goods)
    # ----------------------------------------------------------

    def estimate_landed_cost(self, price: float, shipping: float,
                             origin_country: str,
                             dest_country: str) -> Dict[str, Any]:
        """
        Estimate the total landed cost for a physical product.

        APPROXIMATION: duty and tax rates are country-level averages.
        Real costs depend on HS code, weight, trade agreements, and
        declared value. This gives users a rough comparison, not a
        customs invoice.

        Args:
            price: Product price in USD (already normalized).
            shipping: Shipping cost in USD (already normalized).
            origin_country: 2-letter ISO of the seller's country.
            dest_country: 2-letter ISO of the buyer's country.

        Returns:
            dict with product_price, shipping, duty_estimate,
            tax_estimate, total_landed_cost, and a disclaimer.
        """
        dest = dest_country.upper()

        # Duty is assessed on (price + shipping) in most countries
        dutiable_value = price + shipping
        duty_rate = self.DUTY_RATES.get(dest, 0.05)  # default 5%
        duty_estimate = round(dutiable_value * duty_rate, 2)

        # Tax (VAT/GST) is assessed on (price + shipping + duty) in
        # most countries.  In some (e.g. US) sales tax may not apply to
        # imports the same way, but we include it for consistency.
        tax_rate = self._TAX_RATES.get(dest, 0.10)  # default 10%
        taxable_value = dutiable_value + duty_estimate
        tax_estimate = round(taxable_value * tax_rate, 2)

        total = round(price + shipping + duty_estimate + tax_estimate, 2)

        return {
            "product_price": round(price, 2),
            "shipping": round(shipping, 2),
            "duty_estimate": duty_estimate,
            "duty_rate_used": duty_rate,
            "tax_estimate": tax_estimate,
            "tax_rate_used": tax_rate,
            "total_landed_cost": total,
            "origin_country": origin_country.upper(),
            "dest_country": dest,
            "disclaimer": (
                "Duty and tax figures are ESTIMATES based on country-level "
                "averages. Actual amounts depend on product classification, "
                "trade agreements, and customs assessment."
            ),
        }


# Shared normalizer instance
_normalizer = PriceNormalizer()


# ============================================================
# Fee Engine — Transaction Fee Calculation
# ============================================================

REWARDS_TIERS = {
    "standard":  {"min_transactions": 0,  "savings_rate": 0.25, "label": "Standard"},
    "silver":    {"min_transactions": 10, "savings_rate": 0.22, "label": "Silver"},
    "gold":      {"min_transactions": 25, "savings_rate": 0.20, "label": "Gold"},
    "platinum":  {"min_transactions": 50, "savings_rate": 0.17, "label": "Platinum"},
}

FLAT_FEE = 1.50       # Minimum flat fee (USD)
BASE_RATE = 0.01      # 1% for floor calculation + private market

# Consolidator cost — baked into displayed flight price (COGS, not shown to user)
# Typical range: $5-15 per ticket. This is the per-ticket fee charged by the
# airline consolidator who issues tickets on our behalf via Amadeus Self-Service.
CONSOLIDATOR_FEE_PER_TICKET = 10.00  # USD per ticket (configurable)


def get_user_tier(completed_transactions: int) -> dict:
    """Determine user's rewards tier based on total completed transactions.

    ALL transaction types count — arbitrage bookings, private market deals,
    marketplace purchases. Tier determines savings rate on arbitrage fees.
    """
    tier = "standard"
    for name, cfg in REWARDS_TIERS.items():
        if completed_transactions >= cfg["min_transactions"]:
            tier = name
    t = REWARDS_TIERS[tier]
    return {
        "tier": tier,
        "label": t["label"],
        "savings_rate": t["savings_rate"],
        "completed_transactions": completed_transactions,
        "next_tier": _next_tier_info(tier, completed_transactions),
    }


def _next_tier_info(current_tier: str, completed: int) -> Optional[dict]:
    """Return info about the next tier, or None if already at max."""
    tier_order = ["standard", "silver", "gold", "platinum"]
    idx = tier_order.index(current_tier)
    if idx >= len(tier_order) - 1:
        return None
    next_name = tier_order[idx + 1]
    next_cfg = REWARDS_TIERS[next_name]
    return {
        "tier": next_name,
        "label": next_cfg["label"],
        "savings_rate": next_cfg["savings_rate"],
        "transactions_needed": next_cfg["min_transactions"] - completed,
    }


def calculate_arbitrage_fee(savings_amount: float, deal_amount: float,
                            completed_transactions: int = 0,
                            consolidator_cost: float = 0.0) -> dict:
    """Calculate Phoenix fee for an arbitrage transaction.

    Fee = tier_rate * savings_amount, with a minimum floor of $1.50 + 1%.
    If savings_amount is 0 (no arbitrage found, user books anyway),
    charges the floor fee.

    The deal_amount should already include consolidator cost if applicable
    (for flights). The consolidator_cost param is tracked for transparency
    in the breakdown but does NOT change the fee calculation — it's COGS
    baked into the price the user sees.

    Args:
        savings_amount: USD savings Phoenix found for the user.
        deal_amount: Total deal/booking value in RLUSD (includes consolidator cost).
        completed_transactions: User's total completed transactions (for tier).
        consolidator_cost: Consolidator fee included in deal_amount (for breakdown only).

    Returns:
        Fee breakdown dict.
    """
    tier_info = get_user_tier(completed_transactions)
    savings_fee = round(savings_amount * tier_info["savings_rate"], 2)
    floor_fee = round(FLAT_FEE + (deal_amount * BASE_RATE), 2)
    total_fee = max(savings_fee, floor_fee)

    return {
        "fee_type": "arbitrage",
        "deal_amount": deal_amount,
        "savings_amount": savings_amount,
        "consolidator_cost": consolidator_cost,
        "savings_rate": tier_info["savings_rate"],
        "savings_fee": savings_fee,
        "floor_fee": floor_fee,
        "total_fee": total_fee,
        "net_amount": round(deal_amount - total_fee, 2),
        "tier": tier_info,
        "fee_description": (
            f"{tier_info['savings_rate'] * 100:.0f}% of savings "
            f"(min ${FLAT_FEE:.2f} + {BASE_RATE * 100:.0f}%)"
        ),
    }


def calculate_private_market_fee(deal_amount: float) -> dict:
    """Calculate Phoenix fee for a private market transaction.

    Flat $1.50 + 1% of deal value. No tier discounts (no savings to measure).

    Args:
        deal_amount: Total deal value in RLUSD.

    Returns:
        Fee breakdown dict.
    """
    percentage_fee = round(deal_amount * BASE_RATE, 2)
    total_fee = round(FLAT_FEE + percentage_fee, 2)

    return {
        "fee_type": "private_market",
        "deal_amount": deal_amount,
        "flat_fee": FLAT_FEE,
        "percentage_fee": percentage_fee,
        "percentage_rate": BASE_RATE,
        "total_fee": total_fee,
        "net_to_seller": round(deal_amount - total_fee, 2),
        "fee_description": f"${FLAT_FEE:.2f} + {BASE_RATE * 100:.0f}%",
    }


# Bundle fee constants
BUNDLE_FEE_DISCOUNT = 0.40   # 40% reduction on savings rate for bundles
BUNDLE_FLAT_FEE = 3.00       # Flat fee for entire bundle (vs $1.50 per item)
BUNDLE_BASE_RATE = 0.0075    # 0.75% floor (vs 1% per item)


def calculate_bundle_fee(
    component_amounts: List[float],
    component_savings: List[float],
    completed_transactions: int = 0,
    consolidator_cost: float = 0.0,
) -> dict:
    """Calculate Phoenix fee for a trip bundle (2+ verticals booked together).

    Bundle discount: savings rate reduced by 40% vs individual booking.
    Single flat fee for the entire bundle ($3.00 vs $1.50 × N items).
    Lower percentage floor (0.75% vs 1%).

    Component amounts should already include consolidator cost for flights.
    The consolidator_cost param is tracked for transparency in the breakdown.

    Args:
        component_amounts: USD amounts per component [flight, hotel, transfer].
            Omit or pass 0 for components not included.
            Flight amount should include consolidator fee.
        component_savings: USD savings per component [flight, hotel, transfer].
        completed_transactions: User's total completed transactions (for tier).
        consolidator_cost: Total consolidator fees included in amounts (breakdown only).

    Returns:
        Bundle fee breakdown dict.
    """
    tier_info = get_user_tier(completed_transactions)
    base_rate = tier_info["savings_rate"]

    # Bundle discount: reduce the savings rate by 40%
    bundle_rate = round(base_rate * (1 - BUNDLE_FEE_DISCOUNT), 4)

    total_amount = sum(a for a in component_amounts if a)
    total_savings = sum(s for s in component_savings if s)
    num_components = sum(1 for a in component_amounts if a and a > 0)

    # Savings-based fee
    savings_fee = round(total_savings * bundle_rate, 2)

    # Floor fee
    floor_fee = round(BUNDLE_FLAT_FEE + (total_amount * BUNDLE_BASE_RATE), 2)
    total_fee = max(savings_fee, floor_fee)

    # What they'd pay booking individually
    individual_total_fee = 0.0
    for amt, sav in zip(component_amounts, component_savings):
        if amt and amt > 0:
            ind = calculate_arbitrage_fee(sav or 0, amt, completed_transactions)
            individual_total_fee += ind["total_fee"]

    bundle_savings = round(individual_total_fee - total_fee, 2)

    return {
        "fee_type": "bundle",
        "num_components": num_components,
        "total_amount": round(total_amount, 2),
        "total_savings": round(total_savings, 2),
        "consolidator_cost": consolidator_cost,

        "bundle_rate": bundle_rate,
        "base_rate": base_rate,
        "discount_pct": BUNDLE_FEE_DISCOUNT,

        "savings_fee": savings_fee,
        "floor_fee": floor_fee,
        "total_fee": total_fee,

        "individual_total_fee": round(individual_total_fee, 2),
        "bundle_fee_savings": bundle_savings,
        "net_amount": round(total_amount - total_fee, 2),

        "tier": tier_info,
        "fee_description": (
            f"{bundle_rate * 100:.0f}% of savings "
            f"(min ${BUNDLE_FLAT_FEE:.2f} + {BUNDLE_BASE_RATE * 100:.2f}%) "
            f"— save ${bundle_savings:.2f} vs individual booking"
        ),
    }


# ============================================================
# Flight Pipeline
# ============================================================

class FlightPipeline:
    """
    Process flight search results from multiple markets into
    cross-market arbitrage data.

    Expects each task result dict to contain at minimum:
        market, currency, results (list of flight options).

    Each flight option should have:
        price, airline, duration_minutes, stops.
    """

    ARBITRAGE_THRESHOLD_PCT = 5.0  # Minimum savings % to flag as opportunity

    def process(self, task_results: List[dict], **kwargs) -> dict:
        """
        Process flight search results from multiple markets.

        Args:
            task_results: List of dicts, each representing results from
                one market/zone CitizenSERP task.

        Returns:
            Aggregated result with cheapest_market, savings info, and
            per-market breakdowns.
        """
        start = time.monotonic()
        home_market = kwargs.get("home_market", "US")
        by_market: Dict[str, dict] = {}

        for tr in task_results:
            market = tr.get("market", "unknown")
            currency = tr.get("currency", "USD")
            results = tr.get("results", [])

            market_prices = []
            for r in results:
                raw_price = r.get("price")
                if raw_price is None:
                    continue
                try:
                    usd_price = _normalizer.normalize_price(
                        float(raw_price), currency, "USD"
                    )
                except (ValueError, TypeError):
                    logger.warning("Skipping non-numeric price %r in market %s",
                                   raw_price, market)
                    continue

                market_prices.append({
                    "price_usd": usd_price,
                    "price_local": float(raw_price),
                    "currency": currency,
                    "airline": r.get("airline", "Unknown"),
                    "duration_minutes": r.get("duration_minutes"),
                    "stops": r.get("stops", 0),
                })

            if not market_prices:
                continue

            cheapest = min(market_prices, key=lambda x: x["price_usd"])
            by_market[market] = {
                "market": market,
                "prices": market_prices,
                "cheapest": cheapest["price_usd"],
                "cheapest_airline": cheapest["airline"],
                "result_count": len(market_prices),
            }

        if not by_market:
            elapsed = round(time.monotonic() - start, 3)
            logger.info("FlightPipeline: no valid results (%.3fs)", elapsed)
            return {
                "vertical": "flights",
                "cheapest_market": None,
                "cheapest_price": None,
                "home_price": None,
                "savings_usd": 0,
                "savings_pct": 0,
                "by_market": [],
                "opportunities": [],
                "processing_time_s": elapsed,
            }

        # Global cheapest
        cheapest_market_key = min(by_market, key=lambda m: by_market[m]["cheapest"])
        cheapest_price = by_market[cheapest_market_key]["cheapest"]

        # Home-market price for savings calculation
        home_data = by_market.get(home_market)
        home_price = home_data["cheapest"] if home_data else None
        savings_usd = round(home_price - cheapest_price, 2) if home_price else 0
        savings_pct = (
            round((savings_usd / home_price) * 100, 1)
            if home_price and home_price > 0 else 0
        )

        # Detect arbitrage opportunities (compared to home market)
        opportunities = []
        if home_price and home_price > 0:
            for mkt, data in by_market.items():
                if mkt == home_market:
                    continue
                mkt_savings = round(home_price - data["cheapest"], 2)
                mkt_pct = round((mkt_savings / home_price) * 100, 1)
                if mkt_pct >= self.ARBITRAGE_THRESHOLD_PCT:
                    opportunities.append({
                        "market": mkt,
                        "price_usd": data["cheapest"],
                        "savings_usd": mkt_savings,
                        "savings_pct": mkt_pct,
                        "airline": data["cheapest_airline"],
                    })
            opportunities.sort(key=lambda o: o["savings_pct"], reverse=True)

        elapsed = round(time.monotonic() - start, 3)
        logger.info(
            "FlightPipeline: %d markets, %d results, cheapest=%s ($%.2f), "
            "savings=%.1f%% (%.3fs)",
            len(by_market),
            sum(d["result_count"] for d in by_market.values()),
            cheapest_market_key,
            cheapest_price,
            savings_pct,
            elapsed,
        )

        return {
            "vertical": "flights",
            "cheapest_market": cheapest_market_key,
            "cheapest_price": cheapest_price,
            "home_market": home_market,
            "home_price": home_price,
            "savings_usd": savings_usd,
            "savings_pct": savings_pct,
            "by_market": list(by_market.values()),
            "opportunities": opportunities,
            "markets_searched": len(by_market),
            "total_results": sum(d["result_count"] for d in by_market.values()),
            "processing_time_s": elapsed,
        }


# ============================================================
# Hotel Pipeline
# ============================================================

class HotelPipeline:
    """
    Process hotel search results from multiple markets.

    Supports two data sources:
    1. CitizenSERP task results (cross-market web scraping)
    2. Amadeus Hotel API (GDS wholesale pricing)

    Matches the same hotel across markets using fuzzy name matching,
    then compares per-night rates.
    """

    WORD_OVERLAP_THRESHOLD = 0.80  # 80% common words = same hotel

    def process_amadeus(
        self,
        city_code: str,
        check_in: Optional[str] = None,
        check_out: Optional[str] = None,
        adults: int = 1,
        rooms: int = 1,
        currency: str = "USD",
        ratings: Optional[List[int]] = None,
        max_hotels: int = 20,
    ) -> dict:
        """
        Search hotels via Amadeus API and return results in pipeline format.

        Args:
            city_code: IATA city code (PAR, NYC, LON, TYO)
            check_in: YYYY-MM-DD
            check_out: YYYY-MM-DD
            adults: Adults per room
            rooms: Number of rooms
            currency: Price currency
            ratings: Star rating filter [3, 4, 5]
            max_hotels: Max hotels to price

        Returns:
            Pipeline-format result dict with matched hotels and pricing.
        """
        start = time.monotonic()

        try:
            from amadeus_hotel_client import AmadeusHotelClient
            client = AmadeusHotelClient()
        except ImportError:
            logger.error("HotelPipeline: amadeus_hotel_client not available")
            return {
                "vertical": "hotels",
                "source": "amadeus",
                "cheapest_market": None,
                "matched_hotels": [],
                "all_results_by_market": {},
                "markets_searched": 0,
                "total_results": 0,
                "processing_time_s": 0,
                "error": "Amadeus hotel client not installed",
            }

        if not client.is_configured():
            return {
                "vertical": "hotels",
                "source": "amadeus",
                "cheapest_market": None,
                "matched_hotels": [],
                "all_results_by_market": {},
                "markets_searched": 0,
                "total_results": 0,
                "processing_time_s": 0,
                "error": "Amadeus credentials not configured",
            }

        result = client.search_hotels(
            city_code=city_code,
            check_in=check_in,
            check_out=check_out,
            adults=adults,
            rooms=rooms,
            currency=currency,
            ratings=ratings,
            max_hotels=max_hotels,
        )

        if not result.get("success") or not result.get("hotels"):
            elapsed = round(time.monotonic() - start, 3)
            return {
                "vertical": "hotels",
                "source": "amadeus",
                "cheapest_market": None,
                "matched_hotels": [],
                "all_results_by_market": {},
                "markets_searched": 0,
                "total_results": 0,
                "processing_time_s": elapsed,
                "error": result.get("error", "No hotels found"),
            }

        # Convert Amadeus results to pipeline format
        hotels = []
        for h in result["hotels"]:
            price_per_night = h.get("price_per_night", 0)
            curr = h.get("currency", currency)

            try:
                usd_price = _normalizer.normalize_price(
                    float(price_per_night), curr, "USD"
                )
            except (ValueError, TypeError):
                continue

            hotels.append({
                "hotel_name": h.get("hotel_name", "Unknown Hotel"),
                "hotel_id": h.get("hotel_id"),
                "offer_id": h.get("offer_id"),
                "price_per_night_usd": usd_price,
                "price_per_night_local": float(price_per_night),
                "price_total": h.get("price_total", 0),
                "currency": curr,
                "rating": None,
                "amenities": [],
                "location": h.get("city_code", ""),
                "market": "amadeus",
                "room_type": h.get("room_type", "STANDARD"),
                "check_in": h.get("check_in"),
                "check_out": h.get("check_out"),
                "nights": h.get("nights", 1),
                "source": "amadeus",
                "raw_offer": h.get("raw_offer"),
            })

        # Sort by price
        hotels.sort(key=lambda h: h["price_per_night_usd"])

        elapsed = round(time.monotonic() - start, 3)
        logger.info(
            "HotelPipeline (Amadeus): %d hotels in %s (%.3fs)",
            len(hotels), city_code, elapsed,
        )

        return {
            "vertical": "hotels",
            "source": "amadeus",
            "cheapest_market": "amadeus",
            "matched_hotels": [],
            "all_results_by_market": {"amadeus": hotels},
            "hotels": hotels,
            "markets_searched": 1,
            "total_results": len(hotels),
            "processing_time_s": elapsed,
            "check_in": result.get("check_in"),
            "check_out": result.get("check_out"),
        }

    def process_combined(
        self,
        task_results: List[dict],
        city_code: Optional[str] = None,
        check_in: Optional[str] = None,
        check_out: Optional[str] = None,
        adults: int = 1,
        rooms: int = 1,
        currency: str = "USD",
        **kwargs,
    ) -> dict:
        """
        Combine CitizenSERP + Amadeus hotel results for maximum coverage.

        Runs both sources, merges into unified pipeline output, and
        cross-matches hotels between all markets (including Amadeus).

        Args:
            task_results: CitizenSERP per-market results.
            city_code: IATA city code for Amadeus search.
            check_in, check_out: Date range for Amadeus.
            adults, rooms, currency: Amadeus search params.

        Returns:
            Merged pipeline result with all sources.
        """
        start = time.monotonic()

        # Get CitizenSERP results
        serp_result = self.process(task_results, **kwargs)

        # Get Amadeus results if city_code provided
        amadeus_hotels = []
        if city_code:
            amadeus_result = self.process_amadeus(
                city_code=city_code,
                check_in=check_in,
                check_out=check_out,
                adults=adults,
                rooms=rooms,
                currency=currency,
            )
            amadeus_hotels = amadeus_result.get("hotels", [])

        # Merge: add Amadeus as another market in the by_market dict
        combined_by_market = dict(serp_result.get("all_results_by_market", {}))
        if amadeus_hotels:
            combined_by_market["amadeus"] = amadeus_hotels

        # Re-run cross-market matching with Amadeus included
        matched_hotels = self._match_hotels_across_markets(combined_by_market)

        # Find cheapest market
        all_prices_by_market = {}
        for mkt, hotels in combined_by_market.items():
            prices = [h["price_per_night_usd"] for h in hotels if h.get("price_per_night_usd")]
            if prices:
                all_prices_by_market[mkt] = prices

        cheapest_market = None
        if all_prices_by_market:
            cheapest_market = min(
                all_prices_by_market,
                key=lambda m: mean(all_prices_by_market[m]),
            )

        elapsed = round(time.monotonic() - start, 3)
        total_results = sum(len(h) for h in combined_by_market.values())

        logger.info(
            "HotelPipeline (combined): %d markets, %d hotels, %d matched (%.3fs)",
            len(combined_by_market), total_results, len(matched_hotels), elapsed,
        )

        return {
            "vertical": "hotels",
            "source": "combined",
            "cheapest_market": cheapest_market,
            "matched_hotels": matched_hotels,
            "all_results_by_market": combined_by_market,
            "markets_searched": len(combined_by_market),
            "total_results": total_results,
            "processing_time_s": elapsed,
            "sources": ["citizenserp", "amadeus"] if amadeus_hotels else ["citizenserp"],
        }

    def process(self, task_results: List[dict], **kwargs) -> dict:
        """
        Process hotel search results from multiple markets.

        Args:
            task_results: List of per-market result dicts, each containing
                market, currency, and results list.

        Returns:
            Aggregated result with matched hotels, per-market data,
            and cross-market savings.
        """
        start = time.monotonic()
        by_market: Dict[str, List[dict]] = defaultdict(list)

        # Normalize and group by market
        for tr in task_results:
            market = tr.get("market", "unknown")
            currency = tr.get("currency", "USD")
            for r in tr.get("results", []):
                raw_price = r.get("price_per_night") or r.get("price")
                if raw_price is None:
                    continue
                try:
                    usd_price = _normalizer.normalize_price(
                        float(raw_price), currency, "USD"
                    )
                except (ValueError, TypeError):
                    continue

                by_market[market].append({
                    "hotel_name": r.get("hotel_name", r.get("name", "Unknown Hotel")),
                    "price_per_night_usd": usd_price,
                    "price_per_night_local": float(raw_price),
                    "currency": currency,
                    "rating": r.get("rating"),
                    "amenities": r.get("amenities", []),
                    "location": r.get("location", ""),
                    "market": market,
                })

        # Cross-market hotel matching
        matched_hotels = self._match_hotels_across_markets(by_market)

        # Find overall cheapest market
        all_prices_by_market: Dict[str, List[float]] = {}
        for mkt, hotels in by_market.items():
            all_prices_by_market[mkt] = [h["price_per_night_usd"] for h in hotels]

        cheapest_market = None
        if all_prices_by_market:
            cheapest_market = min(
                all_prices_by_market,
                key=lambda m: mean(all_prices_by_market[m])
                if all_prices_by_market[m] else float("inf"),
            )

        # Serialize by-market results
        all_results_by_market = {
            mkt: hotels for mkt, hotels in by_market.items()
        }

        elapsed = round(time.monotonic() - start, 3)
        logger.info(
            "HotelPipeline: %d markets, %d hotels, %d matched groups (%.3fs)",
            len(by_market),
            sum(len(h) for h in by_market.values()),
            len(matched_hotels),
            elapsed,
        )

        return {
            "vertical": "hotels",
            "cheapest_market": cheapest_market,
            "matched_hotels": matched_hotels,
            "all_results_by_market": all_results_by_market,
            "markets_searched": len(by_market),
            "total_results": sum(len(h) for h in by_market.values()),
            "processing_time_s": elapsed,
        }

    def _match_hotels_across_markets(
        self, by_market: Dict[str, List[dict]]
    ) -> List[dict]:
        """
        Match the same hotel across different markets by fuzzy name
        comparison.  Returns list of matched-hotel groups with
        per-market prices and savings.
        """
        if len(by_market) < 2:
            return []

        markets = list(by_market.keys())
        matched: List[dict] = []
        # Use the first market as anchor; match others against it.
        anchor_market = markets[0]
        anchor_hotels = by_market[anchor_market]

        for ah in anchor_hotels:
            group = {
                "name": ah["hotel_name"],
                "prices_by_market": {anchor_market: ah["price_per_night_usd"]},
                "details_by_market": {anchor_market: ah},
            }
            for other_market in markets[1:]:
                for oh in by_market[other_market]:
                    if self._fuzzy_match_hotels(
                        ah["hotel_name"], oh["hotel_name"],
                        ah.get("location", ""), oh.get("location", ""),
                    ):
                        group["prices_by_market"][other_market] = oh["price_per_night_usd"]
                        group["details_by_market"][other_market] = oh
                        break  # one match per market

            # Only include if found in 2+ markets
            if len(group["prices_by_market"]) >= 2:
                prices = group["prices_by_market"]
                cheapest_mkt = min(prices, key=prices.get)
                most_expensive = max(prices.values())
                cheapest_val = prices[cheapest_mkt]
                savings_pct = (
                    round((1 - cheapest_val / most_expensive) * 100, 1)
                    if most_expensive > 0 else 0
                )
                group["cheapest_market"] = cheapest_mkt
                group["cheapest_price"] = cheapest_val
                group["savings_pct"] = savings_pct
                matched.append(group)

        matched.sort(key=lambda g: g.get("savings_pct", 0), reverse=True)
        return matched

    @staticmethod
    def _fuzzy_match_hotels(name1: str, name2: str,
                            location1: str = "", location2: str = "") -> bool:
        """
        Fuzzy match for hotel names with optional location constraint.
        Returns True if >80% of words are shared between the two names
        AND locations are compatible (both empty, or share a common word).

        No external dependencies — just set overlap on lowercased words.
        """
        def _clean_words(name: str) -> set:
            cleaned = name.lower().translate(
                str.maketrans("", "", string.punctuation)
            )
            words = set(cleaned.split())
            words.discard("")
            return words

        words1 = _clean_words(name1)
        words2 = _clean_words(name2)

        if not words1 or not words2:
            return False

        common = words1 & words2
        total = max(len(words1), len(words2))
        overlap = len(common) / total if total > 0 else 0

        if overlap < 0.80:
            return False

        # Location constraint: if both have locations, they must share
        # at least one word (city/area name)
        if location1 and location2:
            loc_words1 = _clean_words(location1)
            loc_words2 = _clean_words(location2)
            filler = {"hotel", "resort", "inn", "suites", "the", "at", "in", "on", "and"}
            loc_words1 -= filler
            loc_words2 -= filler
            if loc_words1 and loc_words2 and not (loc_words1 & loc_words2):
                return False

        return True


# ============================================================
# Product Pipeline
# ============================================================

class ProductPipeline:
    """
    Process product search results and calculate landed costs
    (price + shipping + duty + tax) for cross-market comparison.
    """

    # Rough average shipping costs (USD) by origin→dest pair.
    # These are for a typical 1-2 kg consumer package. Real costs
    # vary enormously by weight, dimensions, and carrier.
    SHIPPING_ESTIMATES = {
        # (origin, dest) → USD estimate
        ("CN", "US"): 12.00,
        ("CN", "GB"): 14.00,
        ("CN", "DE"): 14.00,
        ("CN", "JP"): 8.00,
        ("CN", "AU"): 15.00,
        ("CN", "CA"): 13.00,
        ("US", "GB"): 18.00,
        ("US", "DE"): 20.00,
        ("US", "JP"): 22.00,
        ("US", "AU"): 24.00,
        ("US", "CA"): 10.00,
        ("US", "CN"): 20.00,
        ("JP", "US"): 18.00,
        ("JP", "GB"): 20.00,
        ("JP", "CN"): 10.00,
        ("JP", "AU"): 18.00,
        ("GB", "US"): 16.00,
        ("GB", "DE"): 10.00,
        ("GB", "FR"): 10.00,
        ("DE", "US"): 18.00,
        ("DE", "GB"): 10.00,
        ("KR", "US"): 15.00,
        ("KR", "JP"): 8.00,
        ("IN", "US"): 14.00,
        ("IN", "GB"): 14.00,
    }

    # Default shipping when we don't have a specific pair
    DEFAULT_SHIPPING = 18.00

    def process(self, task_results: List[dict],
                destination_country: str = "US", **kwargs) -> dict:
        """
        Process product search results from multiple markets and
        compute landed costs.

        Args:
            task_results: Per-market result dicts.
            destination_country: Buyer's country for duty/tax calc.

        Returns:
            Aggregated result with matched products, landed costs,
            and cheapest options.
        """
        start = time.monotonic()
        dest = destination_country.upper()
        by_market: Dict[str, List[dict]] = defaultdict(list)

        for tr in task_results:
            market = tr.get("market", "unknown")
            currency = tr.get("currency", "USD")
            origin_country = tr.get("country", market[:2] if len(market) >= 2 else "US")

            for r in tr.get("results", []):
                raw_price = r.get("price")
                if raw_price is None:
                    continue
                try:
                    usd_price = _normalizer.normalize_price(
                        float(raw_price), currency, "USD"
                    )
                except (ValueError, TypeError):
                    continue

                # Shipping estimate
                shipping = self._estimate_shipping(origin_country, dest)

                # Landed cost
                landed = _normalizer.estimate_landed_cost(
                    usd_price, shipping, origin_country, dest
                )

                by_market[market].append({
                    "product_title": r.get("product_title", r.get("title", "Unknown")),
                    "price_usd": usd_price,
                    "price_local": float(raw_price),
                    "currency": currency,
                    "seller": r.get("seller", "Unknown"),
                    "rating": r.get("rating"),
                    "market": market,
                    "origin_country": origin_country,
                    "shipping_estimate": shipping,
                    "landed_cost": landed,
                })

        # Cross-market product matching
        matched_products = self._match_products_across_markets(by_market)

        # Find cheapest landed cost across all products
        all_landed = []
        for mkt, products in by_market.items():
            for p in products:
                all_landed.append((mkt, p))
        all_landed.sort(key=lambda x: x[1]["landed_cost"]["total_landed_cost"])

        cheapest_market = all_landed[0][0] if all_landed else None
        cheapest_landed_cost = (
            all_landed[0][1]["landed_cost"]["total_landed_cost"]
            if all_landed else None
        )

        elapsed = round(time.monotonic() - start, 3)
        logger.info(
            "ProductPipeline: %d markets, %d products, %d matched groups, "
            "dest=%s (%.3fs)",
            len(by_market),
            sum(len(p) for p in by_market.values()),
            len(matched_products),
            dest,
            elapsed,
        )

        return {
            "vertical": "products",
            "destination_country": dest,
            "cheapest_market": cheapest_market,
            "cheapest_landed_cost": cheapest_landed_cost,
            "matched_products": matched_products,
            "all_results_by_market": dict(by_market),
            "markets_searched": len(by_market),
            "total_results": sum(len(p) for p in by_market.values()),
            "processing_time_s": elapsed,
        }

    def _estimate_shipping(self, origin: str, dest: str) -> float:
        """Look up approximate shipping cost for origin→dest pair."""
        origin = origin.upper()[:2]
        dest = dest.upper()[:2]
        if origin == dest:
            return 0.0  # Domestic — no international shipping
        return self.SHIPPING_ESTIMATES.get(
            (origin, dest), self.DEFAULT_SHIPPING
        )

    def _match_products_across_markets(
        self, by_market: Dict[str, List[dict]]
    ) -> List[dict]:
        """
        Match the same product across different markets by fuzzy title
        comparison. Returns list of matched-product groups with
        per-market prices/landed costs.
        """
        if len(by_market) < 2:
            return []

        markets = list(by_market.keys())
        anchor_market = markets[0]
        matched: List[dict] = []

        for ap in by_market[anchor_market]:
            group = {
                "title": ap["product_title"],
                "prices_by_market": {anchor_market: ap["price_usd"]},
                "landed_costs_by_market": {
                    anchor_market: ap["landed_cost"]["total_landed_cost"]
                },
                "details_by_market": {anchor_market: ap},
            }

            for other_market in markets[1:]:
                for op in by_market[other_market]:
                    if self._fuzzy_match_titles(
                        ap["product_title"], op["product_title"]
                    ):
                        group["prices_by_market"][other_market] = op["price_usd"]
                        group["landed_costs_by_market"][other_market] = (
                            op["landed_cost"]["total_landed_cost"]
                        )
                        group["details_by_market"][other_market] = op
                        break

            if len(group["prices_by_market"]) >= 2:
                costs = group["landed_costs_by_market"]
                cheapest_mkt = min(costs, key=costs.get)
                most_expensive = max(costs.values())
                cheapest_val = costs[cheapest_mkt]
                savings_pct = (
                    round((1 - cheapest_val / most_expensive) * 100, 1)
                    if most_expensive > 0 else 0
                )
                group["cheapest_market"] = cheapest_mkt
                group["cheapest_landed_cost"] = cheapest_val
                group["savings_pct"] = savings_pct
                matched.append(group)

        matched.sort(key=lambda g: g.get("savings_pct", 0), reverse=True)
        return matched

    @staticmethod
    def _fuzzy_match_titles(title1: str, title2: str) -> bool:
        """
        Simple fuzzy match for product titles. Returns True if >80%
        of significant words overlap (case-insensitive, punctuation
        stripped, ignoring common filler words).
        """
        FILLER = {
            "the", "a", "an", "and", "or", "for", "with", "in", "of",
            "to", "by", "from", "new", "free", "shipping",
        }

        def _significant_words(text: str) -> set:
            cleaned = text.lower().translate(
                str.maketrans("", "", string.punctuation)
            )
            return {w for w in cleaned.split() if w and w not in FILLER}

        words1 = _significant_words(title1)
        words2 = _significant_words(title2)
        if not words1 or not words2:
            return False

        common = words1 & words2
        total = max(len(words1), len(words2))
        return (len(common) / total) >= 0.80 if total > 0 else False


# ============================================================
# Cruise Pipeline
# ============================================================

class CruisePipeline:
    """
    Process cruise search results from multiple markets into
    cross-market arbitrage data.

    Normalizes prices to per-person-per-night for fair comparison
    across different cruise durations. Fuzzy-matches cruise packages
    by cruise line + itinerary (ship name + ports).
    """

    ARBITRAGE_THRESHOLD_PCT = 5.0
    WORD_OVERLAP_THRESHOLD = 0.80

    def process(self, task_results: List[dict], **kwargs) -> dict:
        start = time.time()
        by_market = {}

        for tr in task_results:
            market = tr.get("market", "unknown")
            currency = tr.get("currency", "USD")
            results = tr.get("results", [])

            entries = []
            for r in results:
                price_pp = float(r.get("price_per_person", 0) or r.get("price", 0))
                if price_pp <= 0:
                    continue
                price_usd = _normalizer.normalize_price(price_pp, currency)
                nights = int(r.get("duration_nights", 1) or 1)
                if nights < 1:
                    nights = 1
                ppn = round(price_usd / nights, 2)

                entries.append({
                    "cruise_line": r.get("cruise_line", "Unknown"),
                    "ship_name": r.get("ship_name", ""),
                    "itinerary": r.get("itinerary", ""),
                    "duration_nights": nights,
                    "price_per_person_usd": round(price_usd, 2),
                    "price_per_night_usd": ppn,
                    "price_local": price_pp,
                    "currency": currency,
                    "cabin_class": r.get("cabin_class", "inside"),
                    "departure_port": r.get("departure_port", ""),
                    "market": market,
                })

            if entries:
                entries.sort(key=lambda x: x["price_per_night_usd"])
                by_market[market] = {
                    "market": market,
                    "cruises": entries,
                    "result_count": len(entries),
                    "cheapest": entries[0]["price_per_night_usd"],
                    "cheapest_line": entries[0]["cruise_line"],
                }

        # Cross-market matching
        matched = self._match_cruises_across_markets(by_market)

        # Find opportunities
        cheapest_market = None
        cheapest_ppn = float("inf")
        for mkt, data in by_market.items():
            if data["cheapest"] < cheapest_ppn:
                cheapest_ppn = data["cheapest"]
                cheapest_market = mkt

        home_ppn = by_market.get("US", {}).get("cheapest", cheapest_ppn)
        opportunities = []
        for mkt, data in by_market.items():
            if mkt == "US":
                continue
            savings = home_ppn - data["cheapest"]
            if home_ppn > 0 and savings > 0:
                pct = (savings / home_ppn) * 100
                if pct >= self.ARBITRAGE_THRESHOLD_PCT:
                    opportunities.append({
                        "market": mkt,
                        "cruise_line": data["cheapest_line"],
                        "price_per_night": data["cheapest"],
                        "savings_usd": round(savings, 2),
                        "savings_pct": round(pct, 2),
                    })

        opportunities.sort(key=lambda x: x["savings_pct"], reverse=True)
        total = sum(d["result_count"] for d in by_market.values())
        elapsed = round(time.time() - start, 3)

        return {
            "vertical": "cruises",
            "cheapest_market": cheapest_market,
            "cheapest_price_per_night": round(cheapest_ppn, 2) if cheapest_ppn < float("inf") else None,
            "matched_cruises": matched,
            "by_market": list(by_market.values()),
            "opportunities": opportunities,
            "markets_searched": len(by_market),
            "total_results": total,
            "processing_time_s": elapsed,
        }

    def _match_cruises_across_markets(self, by_market: dict) -> list:
        all_cruises = []
        for mkt, data in by_market.items():
            for c in data["cruises"]:
                all_cruises.append(c)

        matched = []
        used = set()

        for i, c1 in enumerate(all_cruises):
            if i in used:
                continue
            group = [c1]
            used.add(i)
            for j, c2 in enumerate(all_cruises):
                if j in used or c1["market"] == c2["market"]:
                    continue
                if self._fuzzy_match(c1, c2):
                    group.append(c2)
                    used.add(j)

            if len(group) > 1:
                prices = {g["market"]: g["price_per_night_usd"] for g in group}
                cheapest_mkt = min(prices, key=prices.get)
                cheapest_val = prices[cheapest_mkt]
                max_val = max(prices.values())
                savings_pct = round(((max_val - cheapest_val) / max_val) * 100, 2) if max_val > 0 else 0

                matched.append({
                    "cruise_line": c1["cruise_line"],
                    "ship_name": c1["ship_name"],
                    "itinerary": c1["itinerary"],
                    "duration_nights": c1["duration_nights"],
                    "prices_by_market": prices,
                    "cheapest_market": cheapest_mkt,
                    "cheapest_price_per_night": cheapest_val,
                    "savings_pct": savings_pct,
                })

        return matched

    @staticmethod
    def _fuzzy_match(c1: dict, c2: dict) -> bool:
        line1 = c1.get("cruise_line", "").lower().strip()
        line2 = c2.get("cruise_line", "").lower().strip()
        if not line1 or not line2:
            return False
        # Cruise line must match exactly (or close)
        line_words1 = set(line1.split())
        line_words2 = set(line2.split())
        if not line_words1 or not line_words2:
            return False
        line_overlap = len(line_words1 & line_words2) / max(len(line_words1), len(line_words2))
        if line_overlap < 0.80:
            return False
        # Itinerary overlap
        itin1 = c1.get("itinerary", "").lower().strip()
        itin2 = c2.get("itinerary", "").lower().strip()
        if itin1 and itin2:
            w1 = set(itin1.translate(str.maketrans("", "", string.punctuation)).split())
            w2 = set(itin2.translate(str.maketrans("", "", string.punctuation)).split())
            if w1 and w2:
                overlap = len(w1 & w2) / max(len(w1), len(w2))
                if overlap < 0.50:
                    return False
        # Duration must be similar (within 2 nights)
        d1 = c1.get("duration_nights", 0)
        d2 = c2.get("duration_nights", 0)
        if d1 and d2 and abs(d1 - d2) > 2:
            return False
        return True


# ============================================================
# E-Commerce Pipeline
# ============================================================

class ECommercePipeline:
    """
    Broad e-commerce product price comparison with landed cost.

    Covers all physical goods: fashion, electronics, home, beauty, sports.
    Extends the ProductPipeline pattern with category detection and
    broader product matching across Amazon, eBay, regional stores.
    """

    FILLER_WORDS = frozenset({
        "the", "a", "an", "and", "or", "for", "with", "in", "of",
        "to", "by", "from", "new", "free", "shipping",
    })

    CATEGORY_KEYWORDS = {
        "electronics": ["phone", "laptop", "computer", "tablet", "headphone", "speaker",
                        "camera", "tv", "monitor", "keyboard", "mouse", "gpu", "cpu",
                        "charger", "cable", "earbuds", "smartwatch", "console",
                        "router", "ssd", "hard drive", "ram", "motherboard", "printer"],
        "fashion": ["shirt", "dress", "shoes", "jacket", "pants", "jeans", "sneakers",
                    "handbag", "watch", "sunglasses", "boots", "coat", "hoodie",
                    "scarf", "belt", "wallet", "ring", "necklace", "bracelet"],
        "home": ["furniture", "sofa", "chair", "table", "lamp", "rug", "curtain",
                 "mattress", "pillow", "kitchen", "cookware", "blender", "vacuum",
                 "air purifier", "fan", "heater", "dishwasher", "microwave"],
        "beauty": ["skincare", "makeup", "perfume", "shampoo", "serum", "moisturizer",
                   "lipstick", "foundation", "hair", "lotion", "cream",
                   "sunscreen", "cleanser", "toner", "mascara", "concealer"],
        "sports": ["bike", "yoga", "gym", "running", "tennis", "golf", "football",
                   "basketball", "swim", "hiking", "camping", "fitness",
                   "treadmill", "weights", "protein", "cycling", "skateboard"],
        "toys": ["toy", "lego", "puzzle", "game", "doll", "figurine", "board game",
                 "plush", "action figure", "rc car", "nerf", "playset"],
        "automotive": ["car", "tire", "brake", "oil", "battery", "wiper", "headlight",
                       "spark plug", "filter", "dash cam", "gps", "seat cover",
                       "motor", "exhaust", "bumper", "steering"],
        "baby": ["stroller", "diaper", "crib", "pacifier", "baby monitor", "formula",
                 "car seat", "highchair", "onesie", "teething", "nursery", "bottle"],
        "pet": ["dog", "cat", "pet food", "collar", "leash", "aquarium", "bird",
                "litter", "pet bed", "chew toy", "kibble", "grooming"],
        "garden": ["plant", "seed", "garden", "lawn", "mower", "fertilizer", "hose",
                   "shovel", "pruner", "pot", "planter", "mulch", "compost"],
    }

    SHIPPING_ESTIMATES = {
        ("CN", "US"): 12.0, ("CN", "GB"): 14.0, ("CN", "DE"): 14.0,
        ("CN", "JP"): 8.0, ("CN", "AU"): 15.0, ("US", "GB"): 18.0,
        ("US", "DE"): 20.0, ("US", "JP"): 22.0, ("US", "AU"): 25.0,
        ("US", "CA"): 10.0, ("JP", "US"): 15.0, ("JP", "GB"): 18.0,
        ("DE", "US"): 20.0, ("DE", "GB"): 10.0, ("GB", "US"): 18.0,
        ("GB", "DE"): 10.0, ("KR", "US"): 14.0, ("IN", "US"): 16.0,
        ("BR", "US"): 22.0, ("MX", "US"): 12.0, ("TR", "US"): 18.0,
        ("PL", "US"): 16.0, ("PL", "DE"): 8.0, ("TH", "US"): 16.0,
        ("VN", "US"): 14.0, ("ID", "US"): 16.0, ("PH", "US"): 14.0,
    }
    DEFAULT_SHIPPING = 18.0

    def process(self, task_results: List[dict], destination_country: str = "US",
                **kwargs) -> dict:
        start = time.time()
        by_market = {}
        query = kwargs.get("query", "")
        detected_category = self._detect_category(query)

        for tr in task_results:
            market = tr.get("market", "unknown")
            currency = tr.get("currency", "USD")
            country = tr.get("country", market)
            results = tr.get("results", [])

            entries = []
            for r in results:
                price = float(r.get("price", 0))
                if price <= 0:
                    continue
                price_usd = _normalizer.normalize_price(price, currency)
                title = r.get("product_title", "") or r.get("title", "")
                shipping = self._estimate_shipping(country, destination_country)
                landed = _normalizer.estimate_landed_cost(
                    price_usd, shipping, country, destination_country
                )

                entries.append({
                    "product_title": title,
                    "price_usd": round(price_usd, 2),
                    "price_local": price,
                    "currency": currency,
                    "seller": r.get("seller", ""),
                    "rating": r.get("rating"),
                    "category": r.get("category", detected_category),
                    "availability": r.get("availability", ""),
                    "product_url": r.get("product_url", "") or r.get("url", ""),
                    "market": market,
                    "origin_country": country,
                    "shipping_estimate": shipping,
                    "landed_cost": landed,
                })

            if entries:
                entries.sort(key=lambda x: x["landed_cost"]["total_landed_cost"])
                by_market[market] = entries

        # Cross-market matching
        matched = self._match_products_across_markets(by_market)

        # Find cheapest
        cheapest_market = None
        cheapest_cost = float("inf")
        for mkt, entries in by_market.items():
            if entries and entries[0]["landed_cost"]["total_landed_cost"] < cheapest_cost:
                cheapest_cost = entries[0]["landed_cost"]["total_landed_cost"]
                cheapest_market = mkt

        total = sum(len(v) for v in by_market.values())
        elapsed = round(time.time() - start, 3)

        return {
            "vertical": "ecommerce",
            "destination_country": destination_country,
            "cheapest_market": cheapest_market,
            "cheapest_landed_cost": round(cheapest_cost, 2) if cheapest_cost < float("inf") else None,
            "detected_category": detected_category,
            "matched_products": matched,
            "all_results_by_market": {m: v for m, v in by_market.items()},
            "markets_searched": len(by_market),
            "total_results": total,
            "processing_time_s": elapsed,
        }

    def _detect_category(self, query: str) -> str:
        query_lower = query.lower()
        best_cat = "general"
        best_count = 0
        for cat, keywords in self.CATEGORY_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw in query_lower)
            if count > best_count:
                best_count = count
                best_cat = cat
        return best_cat

    def _estimate_shipping(self, origin: str, dest: str) -> float:
        return self.SHIPPING_ESTIMATES.get((origin, dest), self.DEFAULT_SHIPPING)

    def _match_products_across_markets(self, by_market: dict) -> list:
        all_items = []
        for mkt, entries in by_market.items():
            for e in entries:
                all_items.append(e)

        matched = []
        used = set()

        for i, p1 in enumerate(all_items):
            if i in used:
                continue
            group = [p1]
            used.add(i)
            for j, p2 in enumerate(all_items):
                if j in used or p1["market"] == p2["market"]:
                    continue
                if self._fuzzy_match_titles(p1["product_title"], p2["product_title"]):
                    group.append(p2)
                    used.add(j)

            if len(group) > 1:
                prices = {g["market"]: g["price_usd"] for g in group}
                costs = {g["market"]: g["landed_cost"]["total_landed_cost"] for g in group}
                cheapest_mkt = min(costs, key=costs.get)
                max_cost = max(costs.values())
                min_cost = costs[cheapest_mkt]
                savings_pct = round(((max_cost - min_cost) / max_cost) * 100, 2) if max_cost > 0 else 0

                matched.append({
                    "title": p1["product_title"],
                    "category": p1["category"],
                    "prices_by_market": prices,
                    "landed_costs_by_market": costs,
                    "details_by_market": {g["market"]: g for g in group},
                    "cheapest_market": cheapest_mkt,
                    "cheapest_landed_cost": round(min_cost, 2),
                    "savings_pct": savings_pct,
                })

        return matched

    @staticmethod
    def _fuzzy_match_titles(title1: str, title2: str) -> bool:
        if not title1 or not title2:
            return False
        t1 = title1.lower().translate(str.maketrans("", "", string.punctuation))
        t2 = title2.lower().translate(str.maketrans("", "", string.punctuation))
        words1 = set(t1.split()) - ECommercePipeline.FILLER_WORDS
        words2 = set(t2.split()) - ECommercePipeline.FILLER_WORDS
        if not words1 or not words2:
            return False
        common = words1 & words2
        total = max(len(words1), len(words2))
        return (len(common) / total) >= 0.80 if total > 0 else False


# ============================================================
# Digital / Software Pipeline
# ============================================================

class DigitalPipeline:
    """
    Digital goods price comparison — software licenses, subscriptions,
    game keys, digital media.

    NO shipping, NO duty — the entire arbitrage is regional pricing
    plus currency conversion. Tracks region-lock status per product.
    """

    ARBITRAGE_THRESHOLD_PCT = 3.0  # Lower threshold — digital goods have tighter margins

    # Standardized region-lock values
    REGION_LOCK_MAP = {
        "global": "Global",
        "worldwide": "Global",
        "none": "Global",
        "no": "Global",
        "region free": "Global",
        "region-free": "Global",
        "eu": "EU",
        "europe": "EU",
        "emea": "EU",
        "na": "NA",
        "north america": "NA",
        "us": "NA",
        "usa": "NA",
        "apac": "APAC",
        "asia": "APAC",
        "asia pacific": "APAC",
        "jp": "JP",
        "japan": "JP",
        "cn": "CN",
        "china": "CN",
        "latam": "LATAM",
        "south america": "LATAM",
        "ru": "CIS",
        "russia": "CIS",
        "cis": "CIS",
        "sea": "SEA",
        "southeast asia": "SEA",
        "row": "ROW",
        "rest of world": "ROW",
    }

    @classmethod
    def _normalize_region_lock(cls, raw: str) -> str:
        """Normalize region-lock value to a standard code."""
        if not raw:
            return "Global"
        return cls.REGION_LOCK_MAP.get(raw.lower().strip(), raw.strip())

    def process(self, task_results: List[dict], **kwargs) -> dict:
        start = time.time()
        by_market = {}

        for tr in task_results:
            market = tr.get("market", "unknown")
            currency = tr.get("currency", "USD")
            results = tr.get("results", [])

            entries = []
            for r in results:
                price = float(r.get("price", 0))
                if price <= 0:
                    continue
                price_usd = _normalizer.normalize_price(price, currency)
                title = r.get("product_title", "") or r.get("title", "")

                entries.append({
                    "product_title": title,
                    "price_usd": round(price_usd, 2),
                    "price_local": price,
                    "currency": currency,
                    "platform": r.get("platform", ""),
                    "license_type": r.get("license_type", ""),
                    "region_lock": self._normalize_region_lock(r.get("region_lock", "Global")),
                    "availability": r.get("availability", ""),
                    "product_url": r.get("product_url", "") or r.get("url", ""),
                    "market": market,
                })

            if entries:
                entries.sort(key=lambda x: x["price_usd"])
                by_market[market] = {
                    "market": market,
                    "products": entries,
                    "result_count": len(entries),
                    "cheapest": entries[0]["price_usd"],
                }

        # Cross-market matching
        matched = self._match_products_across_markets(by_market)

        # Cheapest overall
        cheapest_market = None
        cheapest_price = float("inf")
        for mkt, data in by_market.items():
            if data["cheapest"] < cheapest_price:
                cheapest_price = data["cheapest"]
                cheapest_market = mkt

        total = sum(d["result_count"] for d in by_market.values())
        elapsed = round(time.time() - start, 3)

        return {
            "vertical": "digital",
            "cheapest_market": cheapest_market,
            "cheapest_price": round(cheapest_price, 2) if cheapest_price < float("inf") else None,
            "matched_products": matched,
            "by_market": list(by_market.values()),
            "markets_searched": len(by_market),
            "total_results": total,
            "processing_time_s": elapsed,
        }

    def _match_products_across_markets(self, by_market: dict) -> list:
        all_items = []
        for mkt, data in by_market.items():
            for p in data["products"]:
                all_items.append(p)

        matched = []
        used = set()

        for i, p1 in enumerate(all_items):
            if i in used:
                continue
            group = [p1]
            used.add(i)
            for j, p2 in enumerate(all_items):
                if j in used or p1["market"] == p2["market"]:
                    continue
                if self._fuzzy_match_titles(p1["product_title"], p2["product_title"]):
                    group.append(p2)
                    used.add(j)

            if len(group) > 1:
                prices = {g["market"]: g["price_usd"] for g in group}
                region_locks = {g["market"]: g["region_lock"] for g in group}
                cheapest_mkt = min(prices, key=prices.get)
                max_price = max(prices.values())
                min_price = prices[cheapest_mkt]
                savings_pct = round(((max_price - min_price) / max_price) * 100, 2) if max_price > 0 else 0

                matched.append({
                    "title": p1["product_title"],
                    "platform": p1["platform"],
                    "prices_by_market": prices,
                    "region_locks": region_locks,
                    "cheapest_market": cheapest_mkt,
                    "cheapest_price": round(min_price, 2),
                    "savings_pct": savings_pct,
                })

        return matched

    @staticmethod
    def _fuzzy_match_titles(title1: str, title2: str) -> bool:
        if not title1 or not title2:
            return False
        filler = {"the", "a", "an", "and", "or", "for", "with", "in", "of",
                  "to", "by", "from", "new", "edition", "version", "key", "code"}
        t1 = title1.lower().translate(str.maketrans("", "", string.punctuation))
        t2 = title2.lower().translate(str.maketrans("", "", string.punctuation))
        words1 = set(t1.split()) - filler
        words2 = set(t2.split()) - filler
        if not words1 or not words2:
            return False
        common = words1 & words2
        total = max(len(words1), len(words2))
        return (len(common) / total) >= 0.80 if total > 0 else False


# ============================================================
# Marketplace Pipeline
# ============================================================

class MarketplacePipeline:
    """
    Process marketplace browse results (FB Marketplace, Craigslist,
    local equivalents). Unlike other verticals, marketplace listings
    are unique items — no cross-market matching.

    Instead, assess fair value using price distribution within the
    result set and flag potential bargains.
    """

    BARGAIN_THRESHOLD = 0.70  # Below 70% of median = potential bargain

    def process(self, task_results: List[dict], **kwargs) -> dict:
        """
        Process marketplace browse results.

        Args:
            task_results: Per-market result dicts.

        Returns:
            Aggregated result with listings by market, median prices,
            and flagged bargains.
        """
        start = time.monotonic()
        by_market: Dict[str, dict] = {}

        for tr in task_results:
            market = tr.get("market", "unknown")
            currency = tr.get("currency", "USD")
            listings = []

            for r in tr.get("results", []):
                raw_price = r.get("price")
                if raw_price is None:
                    continue
                try:
                    usd_price = _normalizer.normalize_price(
                        float(raw_price), currency, "USD"
                    )
                except (ValueError, TypeError):
                    continue

                listings.append({
                    "listing_title": r.get("listing_title", r.get("title", "Untitled")),
                    "price_usd": usd_price,
                    "price_local": float(raw_price),
                    "currency": currency,
                    "location": r.get("location", ""),
                    "image_url": r.get("image_url", ""),
                    "listing_url": r.get("listing_url", r.get("url", "")),
                    "seller_name": r.get("seller_name", ""),
                    "condition": r.get("condition", ""),
                    "posted_date": r.get("posted_date", ""),
                    "market": market,
                })

            if not listings:
                continue

            # Price analysis
            prices = [l["price_usd"] for l in listings]
            med_price = round(median(prices), 2)
            avg_price = round(mean(prices), 2)
            bargain_cutoff = med_price * self.BARGAIN_THRESHOLD

            bargains = [
                l for l in listings if l["price_usd"] < bargain_cutoff
            ]
            bargains.sort(key=lambda l: l["price_usd"])

            # Mark bargains in the listings
            for l in listings:
                l["is_bargain"] = l["price_usd"] < bargain_cutoff
                l["pct_of_median"] = (
                    round((l["price_usd"] / med_price) * 100, 1)
                    if med_price > 0 else 0
                )

            by_market[market] = {
                "market": market,
                "listings": listings,
                "listing_count": len(listings),
                "median_price": med_price,
                "average_price": avg_price,
                "min_price": round(min(prices), 2),
                "max_price": round(max(prices), 2),
                "bargain_cutoff": round(bargain_cutoff, 2),
                "bargains": bargains,
                "bargain_count": len(bargains),
            }

        total_listings = sum(m["listing_count"] for m in by_market.values())
        total_bargains = sum(m["bargain_count"] for m in by_market.values())

        elapsed = round(time.monotonic() - start, 3)
        logger.info(
            "MarketplacePipeline: %d markets, %d listings, %d bargains (%.3fs)",
            len(by_market),
            total_listings,
            total_bargains,
            elapsed,
        )

        return {
            "vertical": "marketplace",
            "total_listings": total_listings,
            "total_bargains": total_bargains,
            "by_market": list(by_market.values()),
            "markets_searched": len(by_market),
            "processing_time_s": elapsed,
        }


# ============================================================
# Transfer Pipeline
# ============================================================

class TransferPipeline:
    """
    Process ground transportation search results.

    Supports two data sources:
    1. CitizenSERP task results (cross-market comparison)
    2. Amadeus Transfer API (GDS wholesale: private cars, taxis,
       shared shuttles, airport express, limos, jets, helicopters)

    Normalizes prices to USD, groups by transfer type, and finds
    cheapest options across providers.
    """

    ARBITRAGE_THRESHOLD_PCT = 5.0

    def process(self, task_results: List[dict], **kwargs) -> dict:
        """
        Process transfer search results from CitizenSERP nodes.

        Args:
            task_results: Per-market result dicts with transfer options.

        Returns:
            Aggregated result with cheapest transfers by type and market.
        """
        start = time.monotonic()
        by_market: Dict[str, List[dict]] = defaultdict(list)

        for tr in task_results:
            market = tr.get("market", "unknown")
            currency = tr.get("currency", "USD")

            for r in tr.get("results", []):
                raw_price = r.get("price")
                if raw_price is None:
                    continue
                try:
                    usd_price = _normalizer.normalize_price(
                        float(raw_price), currency, "USD"
                    )
                except (ValueError, TypeError):
                    continue

                by_market[market].append({
                    "provider_name": r.get("provider_name", r.get("provider", "Unknown")),
                    "transfer_type": r.get("transfer_type", "PRIVATE"),
                    "vehicle_category": r.get("vehicle_category", ""),
                    "vehicle_description": r.get("vehicle_description", ""),
                    "price_usd": usd_price,
                    "price_local": float(raw_price),
                    "currency": currency,
                    "max_passengers": r.get("max_passengers"),
                    "max_bags": r.get("max_bags"),
                    "duration_minutes": r.get("duration_minutes"),
                    "distance_km": r.get("distance_km"),
                    "cancellation_policy": r.get("cancellation_policy"),
                    "market": market,
                })

        if not by_market:
            elapsed = round(time.monotonic() - start, 3)
            return {
                "vertical": "transfers",
                "cheapest_market": None,
                "transfers": [],
                "by_market": {},
                "markets_searched": 0,
                "total_results": 0,
                "processing_time_s": elapsed,
            }

        # Find cheapest per market
        market_cheapest = {}
        for mkt, transfers in by_market.items():
            cheapest = min(transfers, key=lambda t: t["price_usd"])
            market_cheapest[mkt] = cheapest["price_usd"]

        cheapest_market = min(market_cheapest, key=market_cheapest.get)

        # Detect arbitrage
        home_market = kwargs.get("home_market", "US")
        home_price = market_cheapest.get(home_market)
        opportunities = []
        if home_price and home_price > 0:
            for mkt, price in market_cheapest.items():
                if mkt == home_market:
                    continue
                savings = round(home_price - price, 2)
                savings_pct = round((savings / home_price) * 100, 1)
                if savings_pct >= self.ARBITRAGE_THRESHOLD_PCT:
                    opportunities.append({
                        "market": mkt,
                        "price_usd": price,
                        "savings_usd": savings,
                        "savings_pct": savings_pct,
                    })
            opportunities.sort(key=lambda o: o["savings_pct"], reverse=True)

        # Flatten all transfers sorted by price
        all_transfers = []
        for transfers in by_market.values():
            all_transfers.extend(transfers)
        all_transfers.sort(key=lambda t: t["price_usd"])

        elapsed = round(time.monotonic() - start, 3)
        logger.info(
            "TransferPipeline: %d markets, %d transfers, cheapest=%s (%.3fs)",
            len(by_market),
            len(all_transfers),
            cheapest_market,
            elapsed,
        )

        return {
            "vertical": "transfers",
            "cheapest_market": cheapest_market,
            "transfers": all_transfers,
            "by_market": {mkt: ts for mkt, ts in by_market.items()},
            "opportunities": opportunities,
            "markets_searched": len(by_market),
            "total_results": len(all_transfers),
            "processing_time_s": elapsed,
        }

    def process_amadeus(
        self,
        start_location_code: Optional[str] = None,
        end_location_code: Optional[str] = None,
        end_address: Optional[str] = None,
        end_city: Optional[str] = None,
        end_country: Optional[str] = None,
        start_datetime: Optional[str] = None,
        passengers: int = 1,
        transfer_type: str = "PRIVATE",
        currency: str = "USD",
    ) -> dict:
        """
        Search transfers via Amadeus API and return pipeline-format results.

        Args:
            start_location_code: IATA airport code (e.g., "JFK")
            end_location_code: IATA code for destination
            end_address: Street address for dropoff
            end_city, end_country: City/country for address
            start_datetime: ISO 8601 datetime
            passengers: Number of passengers
            transfer_type: PRIVATE, SHARED, TAXI, HOURLY, etc.
            currency: Price currency

        Returns:
            Pipeline-format result dict with transfer options.
        """
        start = time.monotonic()

        try:
            from amadeus_transfer_client import AmadeusTransferClient
            client = AmadeusTransferClient()
        except ImportError:
            logger.error("TransferPipeline: amadeus_transfer_client not available")
            return {
                "vertical": "transfers",
                "source": "amadeus",
                "cheapest_market": None,
                "transfers": [],
                "by_market": {},
                "markets_searched": 0,
                "total_results": 0,
                "processing_time_s": 0,
                "error": "Amadeus transfer client not installed",
            }

        if not client.is_configured():
            return {
                "vertical": "transfers",
                "source": "amadeus",
                "cheapest_market": None,
                "transfers": [],
                "by_market": {},
                "markets_searched": 0,
                "total_results": 0,
                "processing_time_s": 0,
                "error": "Amadeus credentials not configured",
            }

        result = client.search_transfers(
            start_location_code=start_location_code,
            end_location_code=end_location_code,
            end_address=end_address,
            end_city=end_city,
            end_country=end_country,
            start_datetime=start_datetime,
            passengers=passengers,
            transfer_type=transfer_type,
            currency=currency,
        )

        if not result.get("success") or not result.get("transfers"):
            elapsed = round(time.monotonic() - start, 3)
            return {
                "vertical": "transfers",
                "source": "amadeus",
                "cheapest_market": None,
                "transfers": [],
                "by_market": {},
                "markets_searched": 0,
                "total_results": 0,
                "processing_time_s": elapsed,
                "error": result.get("error", "No transfers found"),
            }

        # Convert Amadeus results to pipeline format
        transfers = []
        for t in result["transfers"]:
            price = t.get("price", 0)
            curr = t.get("currency", currency)

            try:
                usd_price = _normalizer.normalize_price(
                    float(price), curr, "USD"
                )
            except (ValueError, TypeError):
                continue

            transfers.append({
                "offer_id": t.get("offer_id"),
                "provider_name": t.get("provider_name", "Unknown"),
                "provider_code": t.get("provider_code", ""),
                "transfer_type": t.get("transfer_type", transfer_type),
                "vehicle_code": t.get("vehicle_code", ""),
                "vehicle_category": t.get("vehicle_category", ""),
                "vehicle_description": t.get("vehicle_description", ""),
                "price_usd": usd_price,
                "price_local": float(price),
                "price_base": t.get("price_base", 0),
                "currency": curr,
                "max_passengers": t.get("max_passengers"),
                "max_bags": t.get("max_bags"),
                "duration_minutes": t.get("duration_minutes"),
                "distance_km": t.get("distance_km"),
                "start_location": t.get("start_location"),
                "end_location": t.get("end_location"),
                "start_datetime": t.get("start_datetime"),
                "cancellation_policy": t.get("cancellation_policy"),
                "passengers": passengers,
                "market": "amadeus",
                "source": "amadeus",
                "raw_offer": t.get("raw_offer"),
            })

        transfers.sort(key=lambda t: t["price_usd"])

        elapsed = round(time.monotonic() - start, 3)
        logger.info(
            "TransferPipeline (Amadeus): %d transfers (%.3fs)",
            len(transfers), elapsed,
        )

        return {
            "vertical": "transfers",
            "source": "amadeus",
            "cheapest_market": "amadeus",
            "transfers": transfers,
            "by_market": {"amadeus": transfers},
            "markets_searched": 1,
            "total_results": len(transfers),
            "processing_time_s": elapsed,
        }

    def process_combined(
        self,
        task_results: List[dict],
        start_location_code: Optional[str] = None,
        end_location_code: Optional[str] = None,
        end_address: Optional[str] = None,
        end_city: Optional[str] = None,
        end_country: Optional[str] = None,
        start_datetime: Optional[str] = None,
        passengers: int = 1,
        transfer_type: str = "PRIVATE",
        currency: str = "USD",
        **kwargs,
    ) -> dict:
        """
        Combine CitizenSERP + Amadeus transfer results.

        Runs both sources, merges, and finds cheapest across all providers.
        """
        start = time.monotonic()

        # CitizenSERP results
        serp_result = self.process(task_results, **kwargs)

        # Amadeus results
        amadeus_transfers = []
        if start_location_code:
            amadeus_result = self.process_amadeus(
                start_location_code=start_location_code,
                end_location_code=end_location_code,
                end_address=end_address,
                end_city=end_city,
                end_country=end_country,
                start_datetime=start_datetime,
                passengers=passengers,
                transfer_type=transfer_type,
                currency=currency,
            )
            amadeus_transfers = amadeus_result.get("transfers", [])

        # Merge
        combined_by_market = dict(serp_result.get("by_market", {}))
        if amadeus_transfers:
            combined_by_market["amadeus"] = amadeus_transfers

        all_transfers = []
        for transfers in combined_by_market.values():
            all_transfers.extend(transfers)
        all_transfers.sort(key=lambda t: t["price_usd"])

        # Find cheapest market
        market_cheapest = {}
        for mkt, transfers in combined_by_market.items():
            if transfers:
                market_cheapest[mkt] = min(t["price_usd"] for t in transfers)

        cheapest_market = min(market_cheapest, key=market_cheapest.get) if market_cheapest else None

        elapsed = round(time.monotonic() - start, 3)
        logger.info(
            "TransferPipeline (combined): %d markets, %d transfers (%.3fs)",
            len(combined_by_market), len(all_transfers), elapsed,
        )

        return {
            "vertical": "transfers",
            "source": "combined",
            "cheapest_market": cheapest_market,
            "transfers": all_transfers,
            "by_market": combined_by_market,
            "markets_searched": len(combined_by_market),
            "total_results": len(all_transfers),
            "processing_time_s": elapsed,
            "sources": ["citizenserp", "amadeus"] if amadeus_transfers else ["citizenserp"],
        }


# ============================================================
# Pipeline Manager — Unified Entry Point
# ============================================================

class PipelineManager:
    """
    Routes task results to the appropriate vertical pipeline and
    provides a unified interface for all verticals.

    Usage:
        from vertical_pipelines import pipeline_manager

        result = pipeline_manager.process_results("flight_search", task_results)
        result = pipeline_manager.process_flight_results(task_results)
    """

    def __init__(self):
        self._flight = FlightPipeline()
        self._hotel = HotelPipeline()
        self._product = ProductPipeline()
        self._marketplace = MarketplacePipeline()
        self._cruise = CruisePipeline()
        self._ecommerce = ECommercePipeline()
        self._digital = DigitalPipeline()
        self._transfer = TransferPipeline()

        # Map task type strings → pipeline method
        self._dispatch: Dict[str, callable] = {
            "flight_search": self.process_flight_results,
            "hotel_search": self.process_hotel_results,
            "product_search": self.process_product_results,
            "marketplace_browse": self.process_marketplace_results,
            "cruise_search": self.process_cruise_results,
            "ecommerce_search": self.process_ecommerce_results,
            "digital_search": self.process_digital_results,
            "transfer_search": self.process_transfer_results,
        }

    def process_results(self, task_type: str, task_results: List[dict],
                        **kwargs) -> dict:
        """
        Route results to the correct pipeline based on task_type.

        Args:
            task_type: One of flight_search, hotel_search,
                product_search, marketplace_browse.
            task_results: List of per-market result dicts.
            **kwargs: Additional args forwarded to the pipeline.

        Returns:
            Pipeline-specific result dict.

        Raises:
            ValueError: If task_type is not a supported vertical.
        """
        handler = self._dispatch.get(task_type)
        if handler is None:
            supported = ", ".join(sorted(self._dispatch.keys()))
            raise ValueError(
                f"Unsupported task type '{task_type}'. "
                f"Supported: {supported}"
            )

        logger.info("PipelineManager: routing %s (%d task results)",
                     task_type, len(task_results))
        return handler(task_results, **kwargs)

    def process_flight_results(self, results: List[dict], **kwargs) -> dict:
        """Process flight search results through the flight pipeline."""
        return self._flight.process(results, **kwargs)

    def process_hotel_results(self, results: List[dict], **kwargs) -> dict:
        """Process hotel search results through the hotel pipeline."""
        return self._hotel.process(results, **kwargs)

    def process_product_results(self, results: List[dict], **kwargs) -> dict:
        """Process product search results through the product pipeline."""
        return self._product.process(results, **kwargs)

    def process_marketplace_results(self, results: List[dict], **kwargs) -> dict:
        """Process marketplace browse results through the marketplace pipeline."""
        return self._marketplace.process(results, **kwargs)

    def process_cruise_results(self, results: List[dict], **kwargs) -> dict:
        """Process cruise search results through the cruise pipeline."""
        return self._cruise.process(results, **kwargs)

    def process_ecommerce_results(self, results: List[dict], **kwargs) -> dict:
        """Process e-commerce search results through the ecommerce pipeline."""
        return self._ecommerce.process(results, **kwargs)

    def process_digital_results(self, results: List[dict], **kwargs) -> dict:
        """Process digital product results through the digital pipeline."""
        return self._digital.process(results, **kwargs)

    def process_transfer_results(self, results: List[dict], **kwargs) -> dict:
        """Process transfer search results through the transfer pipeline."""
        return self._transfer.process(results, **kwargs)

    def process_transfer_amadeus(self, **kwargs) -> dict:
        """Search transfers directly via Amadeus API."""
        return self._transfer.process_amadeus(**kwargs)

    def process_transfer_combined(self, results: List[dict], **kwargs) -> dict:
        """Combine CitizenSERP + Amadeus transfer results."""
        return self._transfer.process_combined(results, **kwargs)

    def process_hotel_amadeus(self, **kwargs) -> dict:
        """Search hotels directly via Amadeus API."""
        return self._hotel.process_amadeus(**kwargs)

    def process_hotel_combined(self, results: List[dict], **kwargs) -> dict:
        """Combine CitizenSERP + Amadeus hotel results."""
        return self._hotel.process_combined(results, **kwargs)

    def get_supported_verticals(self) -> List[dict]:
        """
        List all supported verticals with metadata.

        Returns:
            List of dicts with vertical name, task_type, and description.
        """
        return [
            {
                "name": "Flights",
                "task_type": "flight_search",
                "description": (
                    "Cross-market flight price comparison. Finds the cheapest "
                    "market to book the same route and calculates savings vs "
                    "your home market."
                ),
                "cross_market_matching": True,
                "landed_cost": False,
            },
            {
                "name": "Hotels",
                "task_type": "hotel_search",
                "description": (
                    "Hotel rate comparison across booking markets. Matches "
                    "the same property across markets and finds the cheapest "
                    "per-night rate."
                ),
                "cross_market_matching": True,
                "landed_cost": False,
            },
            {
                "name": "Products",
                "task_type": "product_search",
                "description": (
                    "Product price comparison with full landed-cost estimation "
                    "(price + shipping + duty + tax). Finds the cheapest market "
                    "to buy and ship a product to your country."
                ),
                "cross_market_matching": True,
                "landed_cost": True,
            },
            {
                "name": "Marketplace",
                "task_type": "marketplace_browse",
                "description": (
                    "Local marketplace listing discovery and fair-value "
                    "assessment. Flags listings priced below 70% of median "
                    "as potential bargains."
                ),
                "cross_market_matching": False,
                "landed_cost": False,
            },
            {
                "name": "Cruises",
                "task_type": "cruise_search",
                "description": (
                    "Cross-market cruise package comparison. Normalizes "
                    "to per-person-per-night rate and matches cruise lines "
                    "across booking markets."
                ),
                "cross_market_matching": True,
                "landed_cost": False,
            },
            {
                "name": "E-Commerce",
                "task_type": "ecommerce_search",
                "description": (
                    "Broad e-commerce product comparison with full landed-cost "
                    "estimation. Covers fashion, electronics, home goods, and "
                    "more across global markets."
                ),
                "cross_market_matching": True,
                "landed_cost": True,
            },
            {
                "name": "Digital",
                "task_type": "digital_search",
                "description": (
                    "Digital goods and software price comparison across markets. "
                    "No shipping or duty — pure regional pricing arbitrage with "
                    "region-lock tracking."
                ),
                "cross_market_matching": True,
                "landed_cost": False,
            },
            {
                "name": "Transfers",
                "task_type": "transfer_search",
                "description": (
                    "Ground transportation comparison: private cars, taxis, "
                    "shared shuttles, airport express, and more. Includes "
                    "Amadeus GDS wholesale pricing."
                ),
                "cross_market_matching": True,
                "landed_cost": False,
                "amadeus_enabled": True,
            },
        ]


# Module-level singleton
pipeline_manager = PipelineManager()
