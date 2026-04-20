"""
AirGateway NDC API Client — ANASTASiA SDK

NDC aggregator connected to 25+ airlines via direct NDC connections, plus
AERTiCKET consolidator content (102 POS, GDS fares). JSON REST API.

AirGateway API v1.2:
    Sandbox: https://api.airgateway.net/v1.2/
    Production: https://api.airgateway.com/v1.2/
    Auth: API key in Authorization header
    Docs: https://support.airgateway.com/
    Swagger: https://api.airgateway.net/v1.2/swagger-ui/
    Postman: https://github.com/AirGateway/postman-json-api

Connected airlines (confirmed): A3, AA, AF, AV, AY, BA, EK, IB, KL, LH, QF, SQ
Plus AERTiCKET GDS content (Amadeus, Sabre, Travelport).

Usage:
    from clients.airgateway import AirGatewayClient

    client = AirGatewayClient(api_key="your_key")
    result = client.search_flights("JFK", "LHR", "2026-04-15")

    # Multi-POS arbitrage scan:
    cheapest = client.arbitrage_scan("JFK", "LHR", "2026-04-15",
                                     markets=["US", "DK", "ES", "DE"])

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
import re
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("picasso.airgateway")

SANDBOX_BASE = "https://api.airgateway.net/v1.2"
PRODUCTION_BASE = "https://api.airgateway.com/v1.2"

# Cabin class codes — AirGateway uses numeric codes
CABIN_MAP = {
    "economy": "7",
    "ECONOMY": "7",
    "premium_economy": "4",
    "PREMIUM_ECONOMY": "4",
    "business": "2",
    "BUSINESS": "2",
    "first": "1",
    "FIRST": "1",
}

CABIN_DISPLAY = {
    "7": "economy",
    "4": "premium_economy",
    "2": "business",
    "1": "first",
}

# Known NDC-direct airlines (validated against AirGateway docs)
KNOWN_PROVIDERS = {
    "A3", "AA", "AF", "AV", "AY", "BA", "EK", "IB",
    "KL", "LH", "QF", "SQ",
}

# Error classification by HTTP status
ERROR_TYPES = {
    400: "bad_request",
    401: "auth_failed",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "server_error",
    502: "gateway_error",
    503: "service_unavailable",
    504: "gateway_timeout",
}

# Retryable error types
RETRYABLE_ERRORS = {"rate_limited", "gateway_error", "service_unavailable", "gateway_timeout"}

# Shopping session max age before warning (seconds)
SESSION_MAX_AGE = 1800  # 30 minutes

# Retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY = 1.0  # seconds
DEFAULT_RETRY_MAX_DELAY = 30.0  # seconds

# Valid IATA airport code pattern (3 uppercase letters)
IATA_PATTERN = re.compile(r"^[A-Z]{3}$")

# Valid date pattern
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Valid passenger titles
VALID_TITLES = {"MR", "MRS", "MS", "MISS"}

# Valid passenger types
VALID_PAX_TYPES = {"ADT", "CHD", "CNN", "INF"}

# Required passenger fields
REQUIRED_PAX_FIELDS = {
    "nameGiven", "surname", "nameTitle", "gender",
    "birthdate", "passengerType", "emailContact", "phone",
    "travelerReference",
}

# Best POS markets for arbitrage (ordered by typical savings)
ARBITRAGE_MARKETS = ["US", "DK", "ES", "GB", "DE", "FR", "NL", "SE", "NO", "IT"]

# Booking statuses
BOOKING_STATUS = {
    "pending": "Order received, awaiting airline confirmation",
    "confirmed": "Airline confirmed, PNR issued",
    "ticketed": "Ticket issued, ready for travel",
    "failed": "Booking failed — airline rejected or timeout",
    "cancelled": "Order cancelled",
    "voided": "Order voided (within void window)",
}


# =========================================================================
# INPUT VALIDATION
# =========================================================================

class ValidationError(ValueError):
    """Raised when input validation fails before making an API call."""
    pass


def validate_iata(code: str, field_name: str = "airport") -> str:
    """Validate and normalize an IATA airport code."""
    if not code or not isinstance(code, str):
        raise ValidationError(f"{field_name}: IATA code is required")
    normalized = code.strip().upper()
    if not IATA_PATTERN.match(normalized):
        raise ValidationError(
            f"{field_name}: '{code}' is not a valid IATA code (expected 3 letters, e.g., 'JFK')"
        )
    return normalized


def validate_date(date_str: str, field_name: str = "date") -> str:
    """Validate a date string in YYYY-MM-DD format."""
    if not date_str or not isinstance(date_str, str):
        raise ValidationError(f"{field_name}: date is required (YYYY-MM-DD)")
    if not DATE_PATTERN.match(date_str):
        raise ValidationError(
            f"{field_name}: '{date_str}' is not valid (expected YYYY-MM-DD)"
        )
    # Verify it's a real date
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValidationError(f"{field_name}: '{date_str}' is not a valid calendar date")
    return date_str


def validate_passengers(passengers: list) -> List[str]:
    """
    Validate passenger data before sending to the API.

    Returns list of warnings (empty if clean). Raises ValidationError on
    hard failures that would definitely cause API rejection.
    """
    if not passengers or not isinstance(passengers, list):
        raise ValidationError("passengers: at least one passenger is required")

    warnings = []
    seen_refs = set()
    adult_count = 0
    infant_count = 0

    for i, pax in enumerate(passengers, 1):
        if not isinstance(pax, dict):
            raise ValidationError(f"passenger {i}: must be a dict, got {type(pax).__name__}")

        # Check required fields
        missing = REQUIRED_PAX_FIELDS - set(pax.keys())
        if missing:
            raise ValidationError(
                f"passenger {i}: missing required fields: {', '.join(sorted(missing))}"
            )

        # Validate title
        title = pax.get("nameTitle", "").upper()
        if title not in VALID_TITLES:
            raise ValidationError(
                f"passenger {i}: nameTitle '{pax.get('nameTitle')}' invalid "
                f"(expected: {', '.join(sorted(VALID_TITLES))})"
            )

        # Validate gender
        gender = pax.get("gender", "")
        if gender not in ("Male", "Female"):
            raise ValidationError(
                f"passenger {i}: gender must be 'Male' or 'Female', got '{gender}'"
            )

        # Validate passenger type
        pax_type = pax.get("passengerType", "")
        if pax_type not in VALID_PAX_TYPES:
            raise ValidationError(
                f"passenger {i}: passengerType '{pax_type}' invalid "
                f"(expected: {', '.join(sorted(VALID_PAX_TYPES))})"
            )

        if pax_type == "ADT":
            adult_count += 1
        elif pax_type == "INF":
            infant_count += 1

        # Validate birthdate
        birthdate = pax.get("birthdate", "")
        if birthdate:
            validate_date(birthdate, f"passenger {i} birthdate")

        # Validate traveler reference uniqueness
        ref = pax.get("travelerReference", "")
        if ref in seen_refs:
            raise ValidationError(
                f"passenger {i}: duplicate travelerReference '{ref}'"
            )
        seen_refs.add(ref)

        # Validate email format (basic)
        email = pax.get("emailContact", "")
        if email and "@" not in email:
            warnings.append(f"passenger {i}: emailContact '{email}' may be invalid")

        # Validate name length
        name_given = pax.get("nameGiven", "")
        surname = pax.get("surname", "")
        if len(name_given) < 2:
            warnings.append(f"passenger {i}: nameGiven '{name_given}' is very short")
        if len(surname) < 2:
            warnings.append(f"passenger {i}: surname '{surname}' is very short")

    # Business rules
    if infant_count > adult_count:
        raise ValidationError(
            f"passengers: {infant_count} infants exceed {adult_count} adults "
            "(each infant requires an accompanying adult)"
        )

    if adult_count == 0:
        raise ValidationError("passengers: at least one adult (ADT) is required")

    return warnings


# =========================================================================
# REQUEST METRICS
# =========================================================================

class RequestMetrics:
    """Track request latency, success/error rates per endpoint."""

    def __init__(self):
        self._metrics: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "total": 0,
            "success": 0,
            "errors": 0,
            "retries": 0,
            "total_latency_ms": 0.0,
            "min_latency_ms": float("inf"),
            "max_latency_ms": 0.0,
            "error_types": defaultdict(int),
            "last_error": None,
            "last_success_at": None,
        })

    def record_success(self, endpoint: str, latency_ms: float) -> None:
        m = self._metrics[endpoint]
        m["total"] += 1
        m["success"] += 1
        m["total_latency_ms"] += latency_ms
        m["min_latency_ms"] = min(m["min_latency_ms"], latency_ms)
        m["max_latency_ms"] = max(m["max_latency_ms"], latency_ms)
        m["last_success_at"] = time.time()

    def record_error(self, endpoint: str, latency_ms: float, error_type: str) -> None:
        m = self._metrics[endpoint]
        m["total"] += 1
        m["errors"] += 1
        m["total_latency_ms"] += latency_ms
        m["min_latency_ms"] = min(m["min_latency_ms"], latency_ms)
        m["max_latency_ms"] = max(m["max_latency_ms"], latency_ms)
        m["error_types"][error_type] += 1
        m["last_error"] = {"type": error_type, "at": time.time()}

    def record_retry(self, endpoint: str) -> None:
        self._metrics[endpoint]["retries"] += 1

    def get_stats(self, endpoint: Optional[str] = None) -> dict:
        """Get metrics for one endpoint or all endpoints."""
        if endpoint:
            m = self._metrics.get(endpoint)
            if not m:
                return {}
            return self._format_stats(endpoint, m)

        return {ep: self._format_stats(ep, m) for ep, m in self._metrics.items()}

    def _format_stats(self, endpoint: str, m: dict) -> dict:
        total = m["total"] or 1
        return {
            "endpoint": endpoint,
            "total_requests": m["total"],
            "success_count": m["success"],
            "error_count": m["errors"],
            "retry_count": m["retries"],
            "success_rate": round(m["success"] / total * 100, 1),
            "avg_latency_ms": round(m["total_latency_ms"] / total, 1),
            "min_latency_ms": round(m["min_latency_ms"], 1) if m["min_latency_ms"] != float("inf") else 0,
            "max_latency_ms": round(m["max_latency_ms"], 1),
            "error_types": dict(m["error_types"]),
            "last_error": m["last_error"],
            "last_success_at": m["last_success_at"],
        }

    def reset(self) -> None:
        self._metrics.clear()


# =========================================================================
# CLIENT
# =========================================================================

class AirGatewayClient:
    """
    AirGateway NDC API client for ANASTASiA.

    JSON REST API with API key auth. All endpoints use POST.
    11 NDC operations: AirShopping, OfferPrice, OrderCreate, OrderRetrieve,
    OrderCancel, OrderPoll, OrderReshopRefund, OrderReshopReprice,
    SeatAvailability, ServiceList, AirDocIssue.

    Production features:
        - Retry with exponential backoff on retryable errors
        - Input validation (IATA codes, dates, passenger data)
        - Shopping session expiry tracking (30-min TTL)
        - Provider validation against known NDC airlines
        - Error classification with retryable detection
        - Hold booking support via paymentMode
        - Booking response parsing (ticket#, PNR, status)
        - Async booking confirmation via OrderPoll + await_confirmation()
        - Multi-POS arbitrage scanning (parallel N-market search)
        - Request metrics (latency, success/error rates per endpoint)

    Args:
        api_key: AirGateway API key (or set AIRGATEWAY_API_KEY env var).
        sandbox: Use sandbox environment (default True).
        max_retries: Max retry attempts for retryable errors (default 3).
        retry_base_delay: Base delay in seconds for exponential backoff (default 1.0).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        sandbox: bool = True,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    ):
        self._key = api_key or os.environ.get("AIRGATEWAY_API_KEY", "")
        self._base_url = SANDBOX_BASE if sandbox else PRODUCTION_BASE
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": self._key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "AG-Consumer": "MYSTES",
        })
        # Track shopping sessions for expiry detection
        self._shopping_sessions: Dict[str, float] = {}
        # Request metrics
        self.metrics = RequestMetrics()

    def is_configured(self) -> bool:
        """Check if API key is set and looks valid."""
        return bool(self._key) and len(self._key) >= 10

    # =========================================================================
    # HTTP LAYER WITH RETRY
    # =========================================================================

    def _request(
        self,
        endpoint: str,
        body: dict,
        extra_headers: Optional[dict] = None,
        timeout: int = 90,
        max_retries: Optional[int] = None,
    ) -> dict:
        """
        Make a POST request to an AirGateway endpoint with automatic retry.

        Retries on retryable errors (429, 502, 503, 504, timeout, connection)
        with exponential backoff: delay = base * 2^attempt (capped at 30s).
        Non-retryable errors (400, 401, 403, 409, 422) fail immediately.

        Returns dict with:
            - success: bool
            - data: response JSON (on success)
            - error: error message (on failure)
            - error_type: classified error type (on failure)
            - status: HTTP status code (on failure)
            - retryable: whether the error is retryable (on failure)
            - attempts: number of attempts made
            - latency_ms: total time including retries
        """
        retries = max_retries if max_retries is not None else self._max_retries
        url = f"{self._base_url}/{endpoint}"
        headers = {}
        if extra_headers:
            headers.update(extra_headers)

        start_time = time.time()
        last_result = None

        for attempt in range(retries + 1):
            # Generate unique request ID per attempt (session ID stays same)
            headers["AG-Request-ID"] = str(uuid.uuid4())
            headers.setdefault("AG-Session-ID", str(uuid.uuid4()))

            attempt_start = time.time()
            result = self._do_request(url, body, headers, timeout)
            attempt_ms = (time.time() - attempt_start) * 1000

            if result["success"]:
                total_ms = (time.time() - start_time) * 1000
                self.metrics.record_success(endpoint, total_ms)
                result["attempts"] = attempt + 1
                result["latency_ms"] = round(total_ms, 1)
                return result

            last_result = result

            # Don't retry non-retryable errors
            if not result.get("retryable", False):
                total_ms = (time.time() - start_time) * 1000
                self.metrics.record_error(endpoint, total_ms, result.get("error_type", "unknown"))
                result["attempts"] = attempt + 1
                result["latency_ms"] = round(total_ms, 1)
                return result

            # Don't retry on last attempt
            if attempt >= retries:
                break

            # Exponential backoff with jitter
            delay = min(
                self._retry_base_delay * (2 ** attempt),
                DEFAULT_RETRY_MAX_DELAY,
            )
            self.metrics.record_retry(endpoint)
            logger.warning(
                "AirGateway %s retry %d/%d after %.1fs (error: %s)",
                endpoint, attempt + 1, retries, delay,
                result.get("error_type", "unknown"),
            )
            time.sleep(delay)

        # All retries exhausted
        total_ms = (time.time() - start_time) * 1000
        self.metrics.record_error(endpoint, total_ms, last_result.get("error_type", "unknown"))
        last_result["attempts"] = retries + 1
        last_result["latency_ms"] = round(total_ms, 1)
        return last_result

    def _do_request(self, url: str, body: dict, headers: dict, timeout: int) -> dict:
        """Execute a single HTTP request (no retry logic)."""
        try:
            resp = self._session.post(url, json=body, headers=headers, timeout=timeout)
            if resp.status_code >= 400:
                error_msg = resp.text[:500] if resp.text else f"HTTP {resp.status_code}"
                error_type = ERROR_TYPES.get(resp.status_code, "unknown_error")
                retryable = error_type in RETRYABLE_ERRORS

                logger.error(
                    "AirGateway %d (%s): %s",
                    resp.status_code, error_type, error_msg[:200],
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "error_type": error_type,
                    "status": resp.status_code,
                    "retryable": retryable,
                }
            return {"success": True, "data": resp.json()}
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "error": "Request timed out",
                "error_type": "timeout",
                "retryable": True,
            }
        except requests.exceptions.ConnectionError as e:
            return {
                "success": False,
                "error": f"Connection failed: {e}",
                "error_type": "connection_error",
                "retryable": True,
            }
        except Exception as e:
            logger.error("AirGateway request failed: %s", str(e))
            return {
                "success": False,
                "error": str(e),
                "error_type": "client_error",
                "retryable": False,
            }

    # =========================================================================
    # SESSION TRACKING
    # =========================================================================

    def _track_session(self, shopping_response_id: str) -> None:
        """Record when a shopping session was created."""
        if shopping_response_id:
            self._shopping_sessions[shopping_response_id] = time.time()

    def is_session_valid(self, shopping_response_id: str) -> bool:
        """Check if a shopping session is still within the valid window."""
        if not shopping_response_id:
            return False
        created_at = self._shopping_sessions.get(shopping_response_id)
        if created_at is None:
            logger.warning(
                "Unknown shopping session %s — not tracked, assuming valid",
                shopping_response_id[:16],
            )
            return True
        age = time.time() - created_at
        if age > SESSION_MAX_AGE:
            logger.warning(
                "Shopping session %s expired (age: %.0fs, max: %ds)",
                shopping_response_id[:16], age, SESSION_MAX_AGE,
            )
            return False
        return True

    def get_session_age(self, shopping_response_id: str) -> Optional[float]:
        """Get age of a shopping session in seconds, or None if unknown."""
        created_at = self._shopping_sessions.get(shopping_response_id)
        if created_at is None:
            return None
        return time.time() - created_at

    # =========================================================================
    # PROVIDER VALIDATION
    # =========================================================================

    def validate_providers(self, providers: str) -> Tuple[str, List[str]]:
        """
        Validate provider IATA codes against known NDC airlines.

        Returns:
            Tuple of (cleaned providers string, list of unknown codes).
            Unknown codes are still passed through — AERTiCKET GDS content
            covers airlines beyond the NDC-direct list.
        """
        if providers == "*":
            return "*", []

        codes = [c.strip().upper() for c in providers.split(",") if c.strip()]
        unknown = [c for c in codes if c not in KNOWN_PROVIDERS]

        if unknown:
            logger.info(
                "AirGateway: providers %s not in NDC-direct list "
                "(may still work via AERTiCKET GDS content)",
                ", ".join(unknown),
            )

        return ",".join(codes), unknown

    # =========================================================================
    # FLIGHT SEARCH
    # =========================================================================

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        adults: int = 1,
        children: int = 0,
        infants: int = 0,
        cabin_class: str = "economy",
        nonstop: bool = False,
        providers: str = "*",
        country: str = "US",
        currency: str = "USD",
        timeout_seconds: int = 60,
        max_per_provider: int = 30,
    ) -> dict:
        """
        Search for flights via AirGateway NDC.

        All inputs are validated before making the API call.

        Args:
            origin: Origin IATA code (e.g., "JFK")
            destination: Destination IATA code (e.g., "LHR")
            departure_date: "YYYY-MM-DD"
            return_date: "YYYY-MM-DD" (optional for round-trip)
            adults: Number of adults
            children: Number of children (2-11)
            infants: Number of infants (<2)
            cabin_class: economy, premium_economy, business, first
            nonstop: Direct flights only
            providers: "*" for all airlines, or comma-separated IATA codes
            country: POS country code (enables arbitrage — e.g., "DK", "ES")
            currency: Currency code for prices
            timeout_seconds: Max time to wait for airline responses
            max_per_provider: Max offers per cabin per airline

        Returns:
            dict with success, flights list, shopping_response_id

        Raises:
            ValidationError: If inputs are invalid (bad IATA codes, dates, etc.)
        """
        # Validate inputs
        origin = validate_iata(origin, "origin")
        destination = validate_iata(destination, "destination")
        departure_date = validate_date(departure_date, "departure_date")
        if return_date:
            return_date = validate_date(return_date, "return_date")

        if origin == destination:
            raise ValidationError(f"origin and destination cannot be the same ({origin})")

        if adults < 1:
            raise ValidationError("adults must be at least 1")
        if infants > adults:
            raise ValidationError(
                f"{infants} infants exceed {adults} adults "
                "(each infant needs an accompanying adult)"
            )

        cabin_key = cabin_class.lower()
        if cabin_key not in CABIN_MAP:
            raise ValidationError(
                f"cabin_class '{cabin_class}' invalid "
                f"(expected: economy, premium_economy, business, first)"
            )

        # Validate providers
        validated_providers, unknown = self.validate_providers(providers)

        # Build origin/destination list
        origin_dests = [{
            "departure": {
                "airportCode": origin,
                "date": departure_date,
            },
            "arrival": {
                "airportCode": destination,
            },
        }]

        if return_date:
            origin_dests.append({
                "departure": {
                    "airportCode": destination,
                    "date": return_date,
                },
                "arrival": {
                    "airportCode": origin,
                },
            })

        cabin = CABIN_MAP[cabin_key]

        body = {
            "metadata": {
                "country": country.upper(),
                "currency": currency.upper(),
                "locale": "en_US",
            },
            "originDestinations": origin_dests,
            "preferences": {
                "cabin": [cabin],
                "nonStop": nonstop,
            },
            "travelers": {
                "adt": adults,
                "chd": children,
                "inf": infants,
            },
        }

        headers = {
            "AG-Providers": validated_providers,
            "AG-Request-Timeout": str(timeout_seconds),
            "AG-Per-Provider-Limit": str(max_per_provider),
            "NDC-Method": "AirShopping",
        }

        result = self._request("AirShopping", body, extra_headers=headers)
        if not result["success"]:
            return result

        data = result["data"]
        flights = self._parse_shopping_response(data, currency)
        shopping_id = data.get("shoppingResponseID", data.get("id", ""))

        # Track session for expiry detection
        self._track_session(shopping_id)

        return {
            "success": True,
            "flights": flights,
            "shopping_response_id": shopping_id,
            "total_results": len(flights),
            "currency": currency,
            "source": "airgateway_ndc",
            "pos_country": country,
            "latency_ms": result.get("latency_ms"),
            "attempts": result.get("attempts"),
        }

    # =========================================================================
    # MULTI-POS ARBITRAGE SCANNER
    # =========================================================================

    def arbitrage_scan(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        markets: Optional[List[str]] = None,
        adults: int = 1,
        cabin_class: str = "economy",
        providers: str = "*",
        currency: str = "USD",
        max_workers: int = 4,
    ) -> dict:
        """
        Search multiple POS markets in parallel and return the cheapest per flight.

        This is the killer feature — same airline, same flight, different prices
        based on point-of-sale country. Searches N markets concurrently, deduplicates
        by airline+departure time, keeps the cheapest from any market.

        Args:
            origin: Origin IATA code
            destination: Destination IATA code
            departure_date: "YYYY-MM-DD"
            return_date: Optional return date
            markets: List of POS country codes to scan (default: top 10 arbitrage markets)
            adults: Number of adults
            cabin_class: Cabin class
            providers: Airline filter
            currency: Currency code
            max_workers: Max parallel search threads

        Returns:
            dict with:
                - flights: deduplicated cheapest flights (with pos_country on each)
                - market_results: per-market result counts and cheapest price
                - total_searched: total offers across all markets
                - savings: dict with best savings found
        """
        if markets is None:
            markets = ARBITRAGE_MARKETS[:6]  # Top 6 by default

        # Validate once
        origin = validate_iata(origin, "origin")
        destination = validate_iata(destination, "destination")
        departure_date = validate_date(departure_date, "departure_date")

        market_results = {}
        all_flights = []

        def _search_market(market: str) -> Tuple[str, dict]:
            try:
                result = self.search_flights(
                    origin=origin,
                    destination=destination,
                    departure_date=departure_date,
                    return_date=return_date,
                    adults=adults,
                    cabin_class=cabin_class,
                    providers=providers,
                    country=market,
                    currency=currency,
                )
                return market, result
            except Exception as e:
                return market, {"success": False, "error": str(e), "flights": []}

        # Search all markets in parallel
        with ThreadPoolExecutor(max_workers=min(max_workers, len(markets))) as executor:
            futures = {executor.submit(_search_market, m): m for m in markets}
            for future in as_completed(futures):
                market, result = future.result()
                flights = result.get("flights", [])

                # Tag each flight with its POS market
                for f in flights:
                    f["pos_country"] = market
                    f["shopping_response_id"] = result.get("shopping_response_id", "")

                market_results[market] = {
                    "success": result.get("success", False),
                    "count": len(flights),
                    "cheapest": min(
                        (float(f.get("price", "99999")) for f in flights),
                        default=None,
                    ),
                    "shopping_response_id": result.get("shopping_response_id", ""),
                }
                all_flights.extend(flights)

        # Deduplicate: keep cheapest per airline+departure_time
        deduped = self._dedup_arbitrage(all_flights)

        # Calculate savings stats
        savings = self._calc_arbitrage_savings(deduped, market_results)

        return {
            "success": True,
            "flights": deduped,
            "market_results": market_results,
            "markets_searched": len(markets),
            "total_searched": len(all_flights),
            "total_unique": len(deduped),
            "savings": savings,
            "source": "airgateway_ndc_arbitrage",
        }

    def _dedup_arbitrage(self, flights: list) -> list:
        """Keep the cheapest offer per airline+departure_time across markets."""
        best = {}  # key: "airline|dep_time" -> flight dict

        for f in flights:
            airline = f.get("airline", "")
            dep = f.get("departure_time", "")
            if not airline or not dep:
                continue

            key = f"{airline}|{dep}"
            price = float(f.get("price", "99999"))
            existing = best.get(key)

            if existing is None or price < float(existing.get("price", "99999")):
                best[key] = f

        return sorted(best.values(), key=lambda f: float(f.get("price", "99999")))

    def _calc_arbitrage_savings(self, deduped: list, market_results: dict) -> dict:
        """Calculate arbitrage savings statistics."""
        non_us = [f for f in deduped if f.get("pos_country") != "US"]
        us_flights = [f for f in deduped if f.get("pos_country") == "US"]

        if not non_us:
            return {"found": False, "reason": "No non-US market wins"}

        # Find max savings
        max_savings = 0
        max_savings_flight = None
        for f in non_us:
            price = float(f.get("price", "99999"))
            # This flight won dedup from a non-US market — it IS the cheapest
            max_savings_flight = f
            if price < max_savings or max_savings == 0:
                max_savings = price

        return {
            "found": len(non_us) > 0,
            "non_us_winners": len(non_us),
            "us_winners": len(us_flights),
            "cheapest_flight": min(
                (float(f.get("price", "99999")) for f in deduped),
                default=None,
            ),
            "winning_markets": list(set(f.get("pos_country") for f in non_us)),
        }

    # =========================================================================
    # PARSING
    # =========================================================================

    def _parse_shopping_response(self, data: dict, currency: str = "USD") -> list:
        """Parse AirGateway shopping response into normalized flight dicts."""
        flights = []
        offers = data.get("offers", data.get("data", []))
        if not isinstance(offers, list):
            return flights

        for offer in offers:
            try:
                flight = self._parse_offer(offer, currency)
                if flight:
                    flights.append(flight)
            except Exception as e:
                logger.warning("Failed to parse AirGateway offer: %s", str(e))
        return flights

    def _parse_offer(self, offer: dict, currency: str = "USD") -> Optional[dict]:
        """Parse a single offer into a normalized flight dict."""
        segments_data = offer.get("segments", offer.get("itinerary", []))
        if not segments_data:
            return None

        if isinstance(segments_data, list) and segments_data:
            first_seg = segments_data[0]
            last_seg = segments_data[-1]
        else:
            return None

        origin = first_seg.get("origin", first_seg.get("departureAirport", ""))
        destination = last_seg.get("destination", last_seg.get("arrivalAirport", ""))
        dep_time = first_seg.get("departureTime", first_seg.get("departure", ""))
        arr_time = last_seg.get("arrivalTime", last_seg.get("arrival", ""))
        airline = offer.get("owner", offer.get("airline", first_seg.get("airline", "")))

        price = offer.get("totalPrice", offer.get("price", 0))
        if isinstance(price, dict):
            price = price.get("total", price.get("amount", 0))

        base_fare = offer.get("baseFare", offer.get("basePrice", 0))
        if isinstance(base_fare, dict):
            base_fare = base_fare.get("amount", 0)
        tax = offer.get("tax", offer.get("taxes", 0))
        if isinstance(tax, dict):
            tax = tax.get("amount", 0)

        segments = []
        for seg in segments_data:
            segments.append({
                "flight_number": seg.get("flightNumber", ""),
                "origin": seg.get("origin", seg.get("departureAirport", "")),
                "destination": seg.get("destination", seg.get("arrivalAirport", "")),
                "departing_at": seg.get("departureTime", seg.get("departure", "")),
                "arriving_at": seg.get("arrivalTime", seg.get("arrival", "")),
                "operating_carrier": seg.get("operatingCarrier", seg.get("airline", "")),
                "marketing_carrier": seg.get("marketingCarrier", airline),
                "cabin": seg.get("cabin", ""),
                "aircraft": seg.get("aircraft", ""),
                "duration": seg.get("duration", ""),
            })

        return {
            "offer_id": offer.get("offerID", offer.get("id", "")),
            "shopping_response_id": offer.get("shoppingResponseID", offer.get("responseID", "")),
            "airline": airline,
            "airline_code": airline,
            "origin": origin,
            "destination": destination,
            "departure_time": dep_time,
            "arrival_time": arr_time,
            "stops": max(0, len(segments_data) - 1),
            "price": str(price),
            "base_fare": str(base_fare) if base_fare else None,
            "tax": str(tax) if tax else None,
            "currency": currency,
            "cabin_class": offer.get("cabin", "economy"),
            "segments": segments,
            "source": "airgateway_ndc",
            "fare_basis": offer.get("fareBasisCode", ""),
            "booking_class": offer.get("bookingClass", ""),
            "fare_type": offer.get("fareType", ""),
            "refundable": offer.get("refundable"),
            "changeable": offer.get("changeable"),
            "baggage": offer.get("baggageAllowance", offer.get("baggage")),
        }

    # =========================================================================
    # OFFER PRICE VERIFICATION
    # =========================================================================

    def verify_price(self, shopping_response_id: str, offer_ids: list) -> dict:
        """
        Verify offer pricing before booking (OfferPrice).

        Checks session validity before making the call.
        """
        if not self.is_session_valid(shopping_response_id):
            return {
                "success": False,
                "error": "Shopping session expired — search again",
                "error_type": "session_expired",
                "retryable": False,
            }

        body = {
            "shoppingResponseID": shopping_response_id,
            "offerIDs": offer_ids,
        }
        result = self._request("OfferPrice", body, extra_headers={
            "NDC-Method": "OfferPrice",
        })

        if result["success"] and "data" in result:
            verified = self._parse_price_verification(result["data"])
            result["verified_price"] = verified

        return result

    def _parse_price_verification(self, data: dict) -> dict:
        """Extract verified pricing from OfferPrice response."""
        price_info = {
            "total": None,
            "base_fare": None,
            "tax": None,
            "currency": None,
            "price_changed": False,
        }

        offer = data.get("offer", data.get("pricedOffer", data))
        if isinstance(offer, dict):
            total = offer.get("totalPrice", offer.get("price"))
            if isinstance(total, dict):
                price_info["total"] = total.get("total", total.get("amount"))
                price_info["currency"] = total.get("currency")
            elif total is not None:
                price_info["total"] = total

            base = offer.get("baseFare", offer.get("basePrice"))
            if isinstance(base, dict):
                price_info["base_fare"] = base.get("amount")
            elif base is not None:
                price_info["base_fare"] = base

            tax = offer.get("tax", offer.get("taxes"))
            if isinstance(tax, dict):
                price_info["tax"] = tax.get("amount")
            elif tax is not None:
                price_info["tax"] = tax

        return price_info

    # =========================================================================
    # BOOKING
    # =========================================================================

    def create_order(
        self,
        shopping_response_id: str,
        passengers: list,
        payment_method: str = "cash",
        hold_mode: bool = False,
        fake_ticket: bool = False,
    ) -> dict:
        """
        Create a booking (OrderCreate).

        Validates all passenger data before sending to API. Supports
        instant purchase and hold/reserve modes.

        Raises:
            ValidationError: If passenger data is invalid.
        """
        # Validate session
        if not self.is_session_valid(shopping_response_id):
            return {
                "success": False,
                "error": "Shopping session expired — search again",
                "error_type": "session_expired",
                "retryable": False,
            }

        # Validate passengers
        warnings = validate_passengers(passengers)
        if warnings:
            logger.warning("Passenger validation warnings: %s", "; ".join(warnings))

        body = {
            "shoppingResponseID": shopping_response_id,
            "passengers": passengers,
            "payment": {"method": payment_method},
        }

        if hold_mode:
            body["payment"]["paymentMode"] = "hold"

        if fake_ticket:
            body["payment"]["fakeTicket"] = True

        headers = {
            "NDC-Method": "OrderCreate",
            "NDC-Payment-Method": payment_method,
        }

        # Booking requests should NOT be retried (could double-book)
        result = self._request("OrderCreate", body, extra_headers=headers, max_retries=0)

        if result["success"] and "data" in result:
            booking = self._parse_booking_response(result["data"])
            result["booking"] = booking

        return result

    def _parse_booking_response(self, data: dict) -> dict:
        """Parse OrderCreate/Retrieve/Poll response into structured booking info."""
        booking = {
            "order_id": None,
            "pnr": None,
            "airline_pnr": None,
            "status": "pending",
            "tickets": [],
            "passengers": [],
            "total_price": None,
            "currency": None,
            "payment_status": None,
            "owner": None,
            "created_at": None,
            "hold_expiry": None,
        }

        booking["order_id"] = (
            data.get("id")
            or data.get("orderID")
            or data.get("orderId")
            or data.get("order", {}).get("id")
        )

        booking["pnr"] = (
            data.get("bookingReference")
            or data.get("pnr")
            or data.get("airlinePNR")
            or data.get("order", {}).get("bookingReference")
        )
        booking["airline_pnr"] = (
            data.get("airlinePNR")
            or data.get("airline_pnr")
            or data.get("order", {}).get("airlinePNR")
            or booking["pnr"]
        )

        raw_status = (
            data.get("status")
            or data.get("orderStatus")
            or data.get("order", {}).get("status")
            or "pending"
        )
        booking["status"] = raw_status.lower() if isinstance(raw_status, str) else "pending"

        booking["owner"] = (
            data.get("owner")
            or data.get("airline")
            or data.get("order", {}).get("owner")
        )

        price = data.get("totalPrice", data.get("price", data.get("order", {}).get("totalPrice")))
        if isinstance(price, dict):
            booking["total_price"] = price.get("total", price.get("amount"))
            booking["currency"] = price.get("currency")
        elif price is not None:
            booking["total_price"] = price

        tickets_data = data.get("tickets", data.get("order", {}).get("tickets", []))
        if isinstance(tickets_data, list):
            for ticket in tickets_data:
                if isinstance(ticket, dict):
                    booking["tickets"].append({
                        "ticket_number": ticket.get("ticketNumber", ticket.get("number", "")),
                        "passenger_ref": ticket.get("travelerReference", ticket.get("passengerRef", "")),
                        "status": ticket.get("status", ""),
                    })
                elif isinstance(ticket, str):
                    booking["tickets"].append({"ticket_number": ticket, "passenger_ref": "", "status": ""})

        pax_data = data.get("passengers", data.get("order", {}).get("passengers", []))
        if isinstance(pax_data, list):
            for pax in pax_data:
                if isinstance(pax, dict):
                    booking["passengers"].append({
                        "name": f"{pax.get('nameGiven', '')} {pax.get('surname', '')}".strip(),
                        "reference": pax.get("travelerReference", ""),
                        "type": pax.get("passengerType", ""),
                    })

        payment = data.get("payment", data.get("order", {}).get("payment", {}))
        if isinstance(payment, dict):
            booking["payment_status"] = payment.get("status", payment.get("paymentStatus"))

        booking["hold_expiry"] = (
            data.get("holdExpiry")
            or data.get("timeLimit")
            or data.get("order", {}).get("holdExpiry")
        )

        booking["created_at"] = (
            data.get("createdAt")
            or data.get("created")
            or data.get("order", {}).get("createdAt")
        )

        return booking

    def retrieve_order(self, order_id: str, owner: str = "") -> dict:
        """Retrieve an existing booking (OrderRetrieve)."""
        body = {"id": order_id}
        if owner:
            body["owner"] = owner

        result = self._request("OrderRetrieve", body, extra_headers={
            "NDC-Method": "OrderRetrieve",
        })

        if result["success"] and "data" in result:
            result["booking"] = self._parse_booking_response(result["data"])

        return result

    def cancel_order(self, order_id: str, cancel_type: str = "void") -> dict:
        """Cancel a booking (OrderCancel). No retry — cancellations must not be duplicated."""
        body = {"id": order_id, "type": cancel_type}
        return self._request("OrderCancel", body, extra_headers={
            "NDC-Method": "OrderCancel",
        }, max_retries=0)

    def poll_order(self, order_id: str, owner: str = "") -> dict:
        """Poll for async booking confirmation (OrderPoll)."""
        body = {"id": order_id}
        if owner:
            body["owner"] = owner

        result = self._request("OrderPoll", body, extra_headers={
            "NDC-Method": "OrderPoll",
        })

        if result["success"] and "data" in result:
            result["booking"] = self._parse_booking_response(result["data"])

        return result

    def await_confirmation(
        self,
        order_id: str,
        owner: str = "",
        poll_interval: float = 5.0,
        timeout: float = 120.0,
    ) -> dict:
        """
        Automated polling loop — waits for booking confirmation.

        Polls OrderPoll every `poll_interval` seconds until the booking
        status changes from "pending" or `timeout` is reached.

        Args:
            order_id: AirGateway order ID
            owner: Airline owner code (optional)
            poll_interval: Seconds between polls (default 5)
            timeout: Max seconds to wait (default 120)

        Returns:
            dict with final booking status. If timed out, falls back to
            OrderRetrieve for the latest state.
        """
        start = time.time()
        last_result = None

        while (time.time() - start) < timeout:
            result = self.poll_order(order_id, owner=owner)
            last_result = result

            if not result.get("success"):
                # Poll endpoint failed — try OrderRetrieve as fallback
                result = self.retrieve_order(order_id, owner=owner)
                last_result = result

            booking = result.get("booking", {})
            status = booking.get("status", "pending")

            if status != "pending":
                logger.info(
                    "AirGateway order %s confirmed: status=%s (%.1fs)",
                    order_id, status, time.time() - start,
                )
                return result

            time.sleep(poll_interval)

        # Timeout — get final state via OrderRetrieve
        logger.warning(
            "AirGateway order %s confirmation timed out after %.0fs",
            order_id, timeout,
        )
        result = self.retrieve_order(order_id, owner=owner)
        if result.get("success"):
            result["confirmation_timed_out"] = True
        return result

    # =========================================================================
    # ORDER MANAGEMENT
    # =========================================================================

    def reshop_refund(self, order_id: str) -> dict:
        """Request refund quote for an order (OrderReshopRefund)."""
        body = {"id": order_id, "type": "refund"}
        return self._request("OrderReshopRefund", body, extra_headers={
            "NDC-Method": "OrderReshopRefund",
        })

    def reshop_reprice(self, order_id: str, new_segments: Optional[list] = None) -> dict:
        """Reprice a reshop option for date/flight changes (OrderReshopReprice)."""
        body = {"id": order_id}
        if new_segments:
            body["segments"] = new_segments
        return self._request("OrderReshopReprice", body, extra_headers={
            "NDC-Method": "OrderReshopReprice",
        })

    def get_seat_availability(self, order_id: str) -> dict:
        """Get available seats for an order (SeatAvailability)."""
        body = {"id": order_id}
        return self._request("SeatAvailability", body, extra_headers={
            "NDC-Method": "SeatAvailability",
            "NDC-Sub-Method": "preSeatAvailability",
        })

    def get_service_list(self, order_id: str) -> dict:
        """Get available ancillary services — baggage, meals, etc. (ServiceList)."""
        body = {"id": order_id}
        return self._request("ServiceList", body, extra_headers={
            "NDC-Method": "ServiceList",
            "NDC-Sub-Method": "preServiceList",
        })

    def issue_ticket(self, order_id: str) -> dict:
        """
        Issue ticket for a booked order (AirDocIssue).

        No retry — ticketing must not be duplicated.
        """
        body = {"id": order_id}
        result = self._request("AirDocIssue", body, extra_headers={
            "NDC-Method": "AirDocIssue",
        }, max_retries=0)

        if result["success"] and "data" in result:
            result["booking"] = self._parse_booking_response(result["data"])

        return result
