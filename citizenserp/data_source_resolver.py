"""
MYSTES Data Source Resolution Layer (Build #77)

Three-tier priority chain for arbitrage scraping:

  Tier 1: CitizenSERP Node
    → dispatch task to a node in the target market
    → node scrapes locally (real browser, real IP, real location)
    → returns structured results
    → node gets paid via _record_node_task_completion()

  Tier 2: Paid Proxy (passthrough)
    → resolver returns None
    → _safe_scrape() falls through to existing Playwright + Webshare code

  Tier 3: External API
    → Amadeus (flights), future APIs for other verticals
    → structured data, no browser needed

Design:
  - Lazy-imported inside _safe_scrape() with try/except ImportError.
    If this module is missing or broken, Tier 2 runs as before.
  - Circuit breaker per market per tier: 3 consecutive failures → skip
    that tier for that market for 5 minutes.
  - dispatch_and_wait() polls _task_results with configurable timeout.

Usage:
    from data_source_resolver import data_source_resolver

    result = data_source_resolver.resolve(
        vertical="hotel", market="JP", params={...}, timeout_ms=45000,
    )
    if result and result.success and result.tier_used != 2:
        # Use resolved data
    else:
        # Fall through to Tier 2 (Playwright + proxy)
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# Vertical → Task Type Mapping
# ============================================================

VERTICAL_TO_TASK_TYPE: Dict[str, str] = {
    "hotel": "hotel_search",
    "cruise": "cruise_search",
    "rental": "ecommerce_search",
    "flight": "flight_search",
    "product": "product_search",
}


# ============================================================
# Result / Metrics Data Classes
# ============================================================

@dataclass
class ResolutionResult:
    """Outcome of a resolve() call."""

    success: bool
    tier_used: int                          # 1, 2, or 3
    tier_name: str                          # citizenserp_node | paid_proxy | external_api
    market: str
    vertical: str
    results: List[Dict[str, Any]]           # Normalised scrape results
    node_id: Optional[str] = None           # Tier 1 only
    node_user_id: Optional[int] = None      # Tier 1 only
    task_id: Optional[str] = None           # Tier 1 only
    zone_id: Optional[str] = None           # Build #78
    execution_time_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class ResolutionMetrics:
    """Aggregate statistics for the resolver."""

    total_resolutions: int = 0
    tier1_hits: int = 0
    tier2_hits: int = 0
    tier3_hits: int = 0
    tier1_failures: int = 0
    tier2_failures: int = 0
    tier3_failures: int = 0
    by_market: Dict[str, Dict[str, int]] = field(default_factory=dict)
    by_vertical: Dict[str, Dict[str, int]] = field(default_factory=dict)


# ============================================================
# Circuit Breaker
# ============================================================

class TierCircuitBreaker:
    """Per-market, per-tier circuit breaker.

    After *failure_threshold* consecutive failures the breaker opens and
    stays open for *recovery_seconds*, during which the tier is skipped
    for that market.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_seconds: int = 300,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        # _state[market][tier] = {"consecutive_failures": int, "opened_at": float | None}
        self._state: Dict[str, Dict[int, Dict[str, Any]]] = {}

    def _ensure(self, market: str, tier: int) -> Dict[str, Any]:
        self._state.setdefault(market, {})
        self._state[market].setdefault(tier, {
            "consecutive_failures": 0,
            "opened_at": None,
        })
        return self._state[market][tier]

    def record_success(self, market: str, tier: int) -> None:
        entry = self._ensure(market, tier)
        entry["consecutive_failures"] = 0
        entry["opened_at"] = None

    def record_failure(self, market: str, tier: int) -> None:
        entry = self._ensure(market, tier)
        entry["consecutive_failures"] += 1
        if entry["consecutive_failures"] >= self._failure_threshold:
            entry["opened_at"] = time.time()
            logger.warning(
                "Circuit breaker OPEN for market=%s tier=%d "
                "(failures=%d, recovery=%ds)",
                market, tier,
                entry["consecutive_failures"],
                self._recovery_seconds,
            )

    def is_open(self, market: str, tier: int) -> bool:
        entry = self._ensure(market, tier)
        opened_at = entry.get("opened_at")
        if opened_at is None:
            return False
        if time.time() - opened_at >= self._recovery_seconds:
            # Recovery window elapsed — half-open: allow one attempt
            entry["opened_at"] = None
            entry["consecutive_failures"] = 0
            logger.info(
                "Circuit breaker HALF-OPEN for market=%s tier=%d — "
                "allowing next attempt",
                market, tier,
            )
            return False
        return True

    def get_state(self) -> Dict[str, Any]:
        return {
            market: {
                f"tier_{tier}": {
                    "failures": s["consecutive_failures"],
                    "open": s["opened_at"] is not None,
                }
                for tier, s in tiers.items()
            }
            for market, tiers in self._state.items()
        }


# ============================================================
# Data Source Resolver
# ============================================================

class DataSourceResolver:
    """Three-tier data source resolution engine.

    The resolver does **not** run Playwright itself. When Tier 1 (node)
    and Tier 3 (API) both miss, it returns ``None`` — the caller falls
    through to the existing Playwright + Webshare proxy code path
    (Tier 2).
    """

    def __init__(self) -> None:
        self._metrics = ResolutionMetrics()
        self._breaker = TierCircuitBreaker(failure_threshold=3, recovery_seconds=300)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        vertical: str,
        market: str,
        params: Dict[str, Any],
        timeout_ms: int = 45_000,
        user_id: Optional[int] = None,
    ) -> Optional[ResolutionResult]:
        """Try Tier 1 then Tier 3.  Return None to fall through to Tier 2."""

        # Payment compatibility pre-check (Build #85)
        if user_id is not None:
            try:
                from payment_compatibility import payment_compat_engine
                compat = payment_compat_engine.assess_deal_compatibility(
                    deal_market=market[:2], user_id=user_id, vertical=vertical
                )
                if not compat['is_compatible']:
                    logger.info(
                        "Market %s filtered — payment incompatible for user %d",
                        market, user_id,
                    )
                    return ResolutionResult(
                        success=False, tier_used=0,
                        tier_name='payment_filter',
                        market=market, vertical=vertical, results=[],
                        error='payment_incompatible',
                    )
            except ImportError:
                pass

        self._metrics.total_resolutions += 1

        # --- Tier 1: CitizenSERP Node ---
        if not self._breaker.is_open(market, 1):
            t1 = self._try_citizenserp_node(vertical, market, params, timeout_ms)
            if t1 is not None and t1.success:
                self._breaker.record_success(market, 1)
                self._record_metrics(1, market, vertical, True)
                return t1
            if t1 is not None:
                # Attempted but failed
                self._breaker.record_failure(market, 1)
                self._record_metrics(1, market, vertical, False)
        else:
            logger.debug(
                "Tier 1 circuit open for market=%s — skipping node dispatch",
                market,
            )

        # --- Tier 3: External API ---
        if not self._breaker.is_open(market, 3):
            t3 = self._try_external_api(vertical, market, params)
            if t3 is not None and t3.success:
                self._breaker.record_success(market, 3)
                self._record_metrics(3, market, vertical, True)
                return t3
            if t3 is not None:
                self._breaker.record_failure(market, 3)
                self._record_metrics(3, market, vertical, False)

        # --- Tier 2: Paid Proxy (passthrough) ---
        # Return None so caller uses existing Playwright + Webshare code.
        self._record_metrics(2, market, vertical, True)
        return None

    def get_resolution_stats(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of resolution metrics."""
        m = self._metrics
        total = m.total_resolutions or 1  # avoid zero-division
        return {
            "total_resolutions": m.total_resolutions,
            "tier1_hits": m.tier1_hits,
            "tier2_hits": m.tier2_hits,
            "tier3_hits": m.tier3_hits,
            "tier1_hit_rate": round(m.tier1_hits / total, 4),
            "tier2_hit_rate": round(m.tier2_hits / total, 4),
            "tier3_hit_rate": round(m.tier3_hits / total, 4),
            "tier1_failures": m.tier1_failures,
            "tier2_failures": m.tier2_failures,
            "tier3_failures": m.tier3_failures,
            "by_market": dict(m.by_market),
            "by_vertical": dict(m.by_vertical),
            "circuit_breaker": self._breaker.get_state(),
        }

    # ------------------------------------------------------------------
    # Tier 1: CitizenSERP Node
    # ------------------------------------------------------------------

    def _try_citizenserp_node(
        self,
        vertical: str,
        market: str,
        params: Dict[str, Any],
        timeout_ms: int,
    ) -> Optional[ResolutionResult]:
        """Dispatch a task to a CitizenSERP node and wait for results."""

        task_type = VERTICAL_TO_TASK_TYPE.get(vertical)
        if not task_type:
            logger.debug("No task type mapping for vertical '%s'", vertical)
            return None

        try:
            from citizenserp_tasks import task_dispatcher, task_registry
        except ImportError:
            logger.debug("citizenserp_tasks not available — skipping Tier 1")
            return None

        start = time.time()

        # Find a node in the target market
        node = task_dispatcher.find_available_node(market, task_type)
        if node is None:
            logger.debug("No available nodes in market %s for %s", market, task_type)
            return None

        # Create and dispatch the task
        try:
            task = task_registry.create_task(
                task_type=task_type,
                params=params,
                market=market,
                priority=5,  # Normal priority
                requester_user_id=None,
                requester_type="resolver",
            )
            task_id = task_dispatcher.dispatch(task)
            if not task_id:
                return ResolutionResult(
                    success=False, tier_used=1, tier_name="citizenserp_node",
                    market=market, vertical=vertical, results=[],
                    error="dispatch returned None",
                )
        except Exception as e:
            logger.warning("Tier 1 dispatch error for %s/%s: %s", market, vertical, e)
            return ResolutionResult(
                success=False, tier_used=1, tier_name="citizenserp_node",
                market=market, vertical=vertical, results=[],
                error=str(e),
            )

        # Poll _task_results for completion
        result = self._poll_task_result(task_dispatcher, task_id, timeout_ms)
        elapsed = (time.time() - start) * 1000

        if result is None:
            logger.info(
                "Tier 1 timeout for %s/%s task=%s (%.0fms)",
                market, vertical, task_id, elapsed,
            )
            return ResolutionResult(
                success=False, tier_used=1, tier_name="citizenserp_node",
                market=market, vertical=vertical, results=[],
                task_id=task_id, execution_time_ms=elapsed,
                error="timeout",
            )

        if not result.success:
            return ResolutionResult(
                success=False, tier_used=1, tier_name="citizenserp_node",
                market=market, vertical=vertical, results=[],
                task_id=task_id, execution_time_ms=elapsed,
                error=result.error or "task_failed",
            )

        # Normalise results
        raw_data = result.data if isinstance(result.data, dict) else {}
        normalised = self._normalize_node_results(vertical, raw_data, market)

        logger.info(
            "Tier 1 success: %s/%s via node %s — %d results in %.0fms",
            market, vertical, node.get("user_id"), len(normalised), elapsed,
        )

        # Build #78 — Record price observations from Tier 1 node data
        try:
            from pricing_zones import zone_engine
            for item in normalised:
                price = item.get("price") or item.get("price_usd") or 0
                if price > 0:
                    zone_engine.record_observation(
                        vertical=vertical,
                        item_key=self._build_item_key(vertical, item),
                        price_usd=float(price),
                        country_code=market[:2] if market else "XX",
                        node_id=node.get("node_id"),
                        source_tier=1,
                    )
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("Zone observation recording failed: %s", exc)

        return ResolutionResult(
            success=True, tier_used=1, tier_name="citizenserp_node",
            market=market, vertical=vertical, results=normalised,
            node_id=node.get("node_id"),
            node_user_id=node.get("user_id"),
            task_id=task_id, execution_time_ms=elapsed,
        )

    @staticmethod
    def _poll_task_result(dispatcher: Any, task_id: str, timeout_ms: int) -> Any:
        """Synchronous poll of dispatcher._task_results for a completed task.

        This is called from the sync ``resolve()`` path.  For the async
        path, ``dispatch_and_wait()`` on the dispatcher is preferred.
        """
        timeout_s = timeout_ms / 1000.0
        poll_interval = 0.5
        start = time.time()

        while (time.time() - start) < timeout_s:
            result = dispatcher._task_results.get(task_id)
            if result is not None:
                return result

            # Check if the task failed/timed_out/cancelled
            task_obj = dispatcher._active_tasks.get(task_id)
            if task_obj and task_obj.status in ("failed", "timed_out", "cancelled"):
                return None

            time.sleep(poll_interval)

        return None  # Timeout

    # ------------------------------------------------------------------
    # Tier 3: External API
    # ------------------------------------------------------------------

    def _try_external_api(
        self,
        vertical: str,
        market: str,
        params: Dict[str, Any],
    ) -> Optional[ResolutionResult]:
        """Try external APIs as a tertiary data source.

        Amadeus Self-Service APIs cover flights, hotels, and transfers.
        All use the same credentials (AMADEUS_API_KEY/SECRET/ENV).
        """

        start = time.time()

        if vertical == "flight":
            return self._try_amadeus_flights(market, params, start)
        elif vertical == "hotel":
            return self._try_amadeus_hotels(market, params, start)
        elif vertical == "rental":
            return self._try_amadeus_transfers(market, params, start)

        return None

    def _try_amadeus_flights(
        self,
        market: str,
        params: Dict[str, Any],
        start: float,
    ) -> Optional[ResolutionResult]:
        """Tier 3 flight search via Amadeus Flight Offers API."""
        try:
            from amadeus_client import AmadeusClient

            client = AmadeusClient()
            if not client.is_configured():
                return None

            origin = params.get("origin")
            destination = params.get("destination")
            departure_date = params.get("date") or params.get("departure_date")
            return_date = params.get("return_date")
            cabin_class = (params.get("cabin_class") or "economy").upper()

            if not (origin and destination and departure_date):
                return None

            result = client.search_flights(
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                return_date=return_date,
                cabin_class=cabin_class,
            )

            if not result.get("success"):
                elapsed = (time.time() - start) * 1000
                return ResolutionResult(
                    success=False, tier_used=3, tier_name="external_api",
                    market=market, vertical="flight", results=[],
                    execution_time_ms=elapsed,
                    error=result.get("error", "Amadeus flight search failed"),
                )

            normalised = []
            for f in result.get("flights", []):
                normalised.append({
                    "airline": f.get("airline_name") or f.get("airline", ""),
                    "flight_number": f.get("flight_number"),
                    "price": f.get("price", 0),
                    "currency": f.get("currency", "USD"),
                    "origin": f.get("departure_airport", origin),
                    "destination": f.get("arrival_airport", destination),
                    "departure_time": f.get("departure_time", ""),
                    "arrival_time": f.get("arrival_time", ""),
                    "stops": f.get("stops", 0),
                    "duration_minutes": f.get("duration_minutes", 0),
                    "cabin_class": f.get("cabin_class", "economy"),
                    "segments": f.get("segments", []),
                    "raw_offer": f.get("raw_offer"),
                    "source_market": market,
                    "source_tier": 3,
                })

            elapsed = (time.time() - start) * 1000
            return ResolutionResult(
                success=bool(normalised), tier_used=3, tier_name="external_api",
                market=market, vertical="flight", results=normalised,
                execution_time_ms=elapsed,
            )

        except ImportError:
            logger.debug("amadeus_client not available for Tier 3 flights")
            return None
        except Exception as e:
            logger.exception("Amadeus flight search error: %s", e)
            return None

    def _try_amadeus_hotels(
        self,
        market: str,
        params: Dict[str, Any],
        start: float,
    ) -> Optional[ResolutionResult]:
        """Tier 3 hotel search via Amadeus Hotel Search v3 API."""
        try:
            from liteapi_client import LiteAPIHotelClient

            client = LiteAPIHotelClient()
            if not client.is_configured():
                return None

            city_code = params.get("city_code") or params.get("location")
            check_in = params.get("check_in") or params.get("checkin_date")
            check_out = params.get("check_out") or params.get("checkout_date")

            if not city_code:
                return None

            # City code should be IATA (3 letters). If it's a city name,
            # we can't use it directly — would need a lookup.
            if len(city_code) > 3:
                logger.debug("Hotel search needs IATA city code, got: %s", city_code)
                return None

            result = client.search_hotels(
                city_code=city_code,
                check_in=check_in,
                check_out=check_out,
                adults=params.get("guests", 1),
                rooms=params.get("rooms", 1),
                currency="USD",
                max_hotels=20,
            )

            if not result.get("success"):
                elapsed = (time.time() - start) * 1000
                return ResolutionResult(
                    success=False, tier_used=3, tier_name="external_api",
                    market=market, vertical="hotel", results=[],
                    execution_time_ms=elapsed,
                    error=result.get("error", "liteAPI hotel search failed"),
                )

            normalised = []
            for h in result.get("hotels", []):
                normalised.append({
                    "hotel_name": h.get("hotel_name", ""),
                    "name": h.get("hotel_name", ""),
                    "price": h.get("price_total", 0),
                    "price_per_night": h.get("price_per_night", 0),
                    "currency": h.get("currency", "USD"),
                    "star_rating": None,
                    "guest_rating": None,
                    "room_type": h.get("room_type", "standard"),
                    "amenities": [],
                    "location": h.get("city_code", ""),
                    "offer_id": h.get("offer_id"),
                    "raw_offer": h.get("raw_offer"),
                    "source_market": market,
                    "source_tier": 3,
                })

            elapsed = (time.time() - start) * 1000
            return ResolutionResult(
                success=bool(normalised), tier_used=3, tier_name="external_api",
                market=market, vertical="hotel", results=normalised,
                execution_time_ms=elapsed,
            )

        except ImportError:
            logger.debug("liteapi_client not available for Tier 3 hotels")
            return None
        except Exception as e:
            logger.exception("Amadeus hotel search error: %s", e)
            return None

    def _try_amadeus_transfers(
        self,
        market: str,
        params: Dict[str, Any],
        start: float,
    ) -> Optional[ResolutionResult]:
        """Tier 3 transfer/rental search via Amadeus Transfer API."""
        try:
            from amadeus_transfer_client import AmadeusTransferClient

            client = AmadeusTransferClient()
            if not client.is_configured():
                return None

            start_location = params.get("location") or params.get("pickup_location")
            end_location = params.get("dropoff_location") or params.get("destination")
            pickup_date = params.get("pickup_date") or params.get("date")

            if not start_location:
                return None

            # Build datetime string
            start_datetime = None
            if pickup_date:
                start_datetime = f"{pickup_date}T10:00:00"

            result = client.search_transfers(
                start_location_code=start_location if len(start_location) <= 3 else None,
                start_address=start_location if len(start_location) > 3 else None,
                end_location_code=end_location if end_location and len(end_location) <= 3 else None,
                end_address=end_location if end_location and len(end_location) > 3 else None,
                start_datetime=start_datetime,
                passengers=params.get("passengers", 1),
                transfer_type="PRIVATE",
            )

            if not result.get("success"):
                elapsed = (time.time() - start) * 1000
                return ResolutionResult(
                    success=False, tier_used=3, tier_name="external_api",
                    market=market, vertical="rental", results=[],
                    execution_time_ms=elapsed,
                    error=result.get("error", "Amadeus transfer search failed"),
                )

            normalised = []
            for t in result.get("transfers", []):
                normalised.append({
                    "rental_company": t.get("provider_name", ""),
                    "vehicle_class": t.get("vehicle_category", "standard"),
                    "vehicle_example": t.get("vehicle_description", ""),
                    "price": t.get("price", 0),
                    "price_per_day": t.get("price", 0),
                    "currency": t.get("currency", "USD"),
                    "pickup_location": t.get("start_location", ""),
                    "offer_id": t.get("offer_id"),
                    "raw_offer": t.get("raw_offer"),
                    "source_market": market,
                    "source_tier": 3,
                })

            elapsed = (time.time() - start) * 1000
            return ResolutionResult(
                success=bool(normalised), tier_used=3, tier_name="external_api",
                market=market, vertical="rental", results=normalised,
                execution_time_ms=elapsed,
            )

        except ImportError:
            logger.debug("amadeus_transfer_client not available for Tier 3 transfers")
            return None
        except Exception as e:
            logger.exception("Amadeus transfer search error: %s", e)
            return None

    # ------------------------------------------------------------------
    # Result Normalisation
    # ------------------------------------------------------------------

    def _normalize_node_results(
        self,
        vertical: str,
        raw_data: Dict[str, Any],
        market: str,
    ) -> List[Dict[str, Any]]:
        """Convert raw node task results into the format scrapers expect.

        Node results arrive as ``{"results": [...]}``.  Each item is
        already semi-structured by the node's extraction schema, but
        field names may differ per vertical.
        """
        items = raw_data.get("results", [])
        if not isinstance(items, list):
            return []

        normalised: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            if vertical == "hotel":
                normalised.append(self._normalize_hotel(item, market))
            elif vertical == "cruise":
                normalised.append(self._normalize_cruise(item, market))
            elif vertical == "rental":
                normalised.append(self._normalize_rental(item, market))
            elif vertical == "flight":
                normalised.append(self._normalize_flight(item, market))
            else:
                # Pass through unknown verticals as-is
                item["source_market"] = market
                item["source_tier"] = 1
                normalised.append(item)

        return normalised

    @staticmethod
    def _normalize_hotel(item: Dict[str, Any], market: str) -> Dict[str, Any]:
        return {
            "hotel_name": item.get("name") or item.get("hotel_name", ""),
            "price": item.get("price") or item.get("total_price", 0),
            "price_per_night": item.get("price_per_night", 0),
            "currency": item.get("currency", "USD"),
            "star_rating": item.get("star_rating") or item.get("stars"),
            "guest_rating": item.get("guest_rating") or item.get("rating"),
            "room_type": item.get("room_type", "standard"),
            "amenities": item.get("amenities", []),
            "source_url": item.get("url") or item.get("source_url", ""),
            "source_market": market,
            "source_tier": 1,
        }

    @staticmethod
    def _normalize_cruise(item: Dict[str, Any], market: str) -> Dict[str, Any]:
        return {
            "cruise_line": item.get("cruise_line") or item.get("line", ""),
            "ship_name": item.get("ship_name") or item.get("ship", ""),
            "price": item.get("price") or item.get("total_price", 0),
            "price_per_night": item.get("price_per_night", 0),
            "currency": item.get("currency", "USD"),
            "cabin_category": item.get("cabin_category") or item.get("cabin", "inside"),
            "departure_port": item.get("departure_port") or item.get("port", ""),
            "itinerary": item.get("itinerary", []),
            "duration_nights": item.get("duration_nights") or item.get("nights", 0),
            "source_url": item.get("url") or item.get("source_url", ""),
            "source_market": market,
            "source_tier": 1,
        }

    @staticmethod
    def _normalize_rental(item: Dict[str, Any], market: str) -> Dict[str, Any]:
        return {
            "rental_company": item.get("rental_company") or item.get("company", ""),
            "vehicle_class": item.get("vehicle_class") or item.get("class", "economy"),
            "vehicle_example": item.get("vehicle_example") or item.get("vehicle", ""),
            "price": item.get("price") or item.get("total_price", 0),
            "price_per_day": item.get("price_per_day", 0),
            "currency": item.get("currency", "USD"),
            "pickup_location": item.get("pickup_location") or item.get("location", ""),
            "source_url": item.get("url") or item.get("source_url", ""),
            "source_market": market,
            "source_tier": 1,
        }

    @staticmethod
    def _normalize_flight(item: Dict[str, Any], market: str) -> Dict[str, Any]:
        return {
            "airline": item.get("airline", ""),
            "price": item.get("price") or item.get("total_price", 0),
            "currency": item.get("currency", "USD"),
            "origin": item.get("origin", ""),
            "destination": item.get("destination", ""),
            "departure_time": item.get("departure_time", ""),
            "arrival_time": item.get("arrival_time", ""),
            "stops": item.get("stops", 0),
            "duration_minutes": item.get("duration_minutes", 0),
            "cabin_class": item.get("cabin_class", "economy"),
            "source_url": item.get("url") or item.get("source_url", ""),
            "source_market": market,
            "source_tier": 1,
        }

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _record_metrics(
        self,
        tier_used: int,
        market: str,
        vertical: str,
        success: bool,
    ) -> None:
        m = self._metrics

        tier_map = {1: "tier1", 2: "tier2", 3: "tier3"}
        tier_key = tier_map.get(tier_used, "tier2")

        if success:
            setattr(m, f"{tier_key}_hits", getattr(m, f"{tier_key}_hits") + 1)
        else:
            setattr(m, f"{tier_key}_failures", getattr(m, f"{tier_key}_failures") + 1)

        # Per-market
        m.by_market.setdefault(market, {"tier1": 0, "tier2": 0, "tier3": 0})
        if success:
            m.by_market[market][tier_key] += 1

        # Per-vertical
        m.by_vertical.setdefault(vertical, {"tier1": 0, "tier2": 0, "tier3": 0})
        if success:
            m.by_vertical[vertical][tier_key] += 1


    # Build #78 — Item key generation for zone price observations
    @staticmethod
    def _build_item_key(vertical: str, item: dict) -> str:
        """Generate a canonical item key for price observation grouping."""
        import hashlib

        def _slug(s: str) -> str:
            return (s or "unknown").lower().replace(" ", "-")[:40]

        if vertical == "hotel":
            name = item.get("hotel_name") or item.get("name") or "hotel"
            city = item.get("city") or item.get("destination_city") or ""
            return f"{_slug(name)}-{_slug(city)}"
        elif vertical == "flight":
            origin = item.get("origin") or item.get("departure_airport") or "XXX"
            dest = item.get("destination") or item.get("arrival_airport") or "XXX"
            date = item.get("departure_date") or item.get("date") or ""
            cabin = item.get("cabin_class") or "economy"
            return f"{origin}-{dest}:{date}:{cabin}"
        elif vertical == "cruise":
            ship = item.get("ship_name") or item.get("name") or "cruise"
            port = item.get("departure_port") or ""
            date = item.get("departure_date") or ""
            return f"{_slug(ship)}-{_slug(port)}:{date}"
        elif vertical == "rental":
            vehicle = item.get("vehicle_class") or item.get("vehicle_name") or "car"
            loc = item.get("pickup_location") or item.get("location") or ""
            return f"{_slug(vehicle)}-{_slug(loc)}"
        else:
            raw = json.dumps(sorted(item.items()), default=str)
            h = hashlib.md5(raw.encode()).hexdigest()[:10]
            return f"{vertical}-{h}"


# ============================================================
# Module Singleton
# ============================================================

data_source_resolver = DataSourceResolver()
