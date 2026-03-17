"""
Universal Arbitrage Search Orchestrator — AI-Powered Intent Classification

Unified entry point for all travel verticals:
- Flights (delegates to existing search_global)
- Hotels (HotelScraper + CrossMarketComparator)
- Cruises (CruiseScraper + CrossMarketComparator)
- Car Rentals (RentalScraper + CrossMarketComparator)
- Vacation Packages (combines flight + hotel searches)

Workflow:
1. User submits a natural-language query (e.g. "hotels in Tokyo March 15-18")
2. classify_intent() parses the vertical + structured params via regex/keywords
3. Vertical-specific search is dispatched
4. Results are scored, fees calculated, deals persisted, and returned
"""

import logging
import re
import json
import secrets
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dateutil import — fall back to basic regex date parsing if missing
# ---------------------------------------------------------------------------

try:
    from dateutil import parser as dateutil_parser
    DATEUTIL_AVAILABLE = True
except ImportError:
    dateutil_parser = None
    DATEUTIL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Internal imports
# ---------------------------------------------------------------------------

from models import db, Deal


# ---------------------------------------------------------------------------
# Vertical Keyword Classifiers
# ---------------------------------------------------------------------------

VERTICAL_CLASSIFIERS = {
    "flight": {
        "keywords": [
            "flight", "flights", "fly", "flying", "airfare", "airline",
            "plane", "airplane", "air ticket", "plane ticket", "nonstop",
            "direct flight", "layover", "stopover", "one-way", "round-trip",
            "roundtrip", "one way", "round trip", "redeye", "red-eye",
        ],
        "patterns": [
            # Airport code to airport code (e.g. JFK to LHR, LAX-NRT)
            r'\b[A-Z]{3}\s*(?:to|->|-->|-)\s*[A-Z]{3}\b',
            # "fly to <place>"
            r'\bfly\s+to\b',
            # "from <airport> to <airport>"
            r'\bfrom\s+[A-Z]{3}\s+to\s+[A-Z]{3}\b',
        ],
    },
    "hotel": {
        "keywords": [
            "hotel", "hotels", "motel", "hostel", "resort", "accommodation",
            "lodging", "stay", "room", "suite", "inn", "bed and breakfast",
            "b&b", "airbnb", "booking", "check-in", "check in", "check-out",
            "check out", "night stay", "per night", "star hotel",
        ],
        "patterns": [
            # "stay in <place>"
            r'\bstay\s+(?:in|at)\b',
            # "nights in <place>"
            r'\b\d+\s*nights?\s+in\b',
            # "hotel in <place>"
            r'\bhotels?\s+(?:in|near|at)\b',
        ],
    },
    "cruise": {
        "keywords": [
            "cruise", "cruises", "cruising", "cruise line", "cruise ship",
            "sailing", "sail", "voyage", "ocean", "sea trip", "cabin",
            "balcony cabin", "interior cabin", "ocean view", "stateroom",
            "port", "ports of call", "embark", "disembark", "shore excursion",
            "carnival", "royal caribbean", "norwegian", "msc", "celebrity",
            "princess cruises", "holland america",
        ],
        "patterns": [
            # "cruise to <place>"
            r'\bcruise\s+(?:to|from|around)\b',
            # "<number> night cruise"
            r'\b\d+\s*(?:night|day)s?\s*cruise\b',
            # "caribbean cruise", "alaska cruise"
            r'\b(?:caribbean|alaska|mediterranean|bahamas|bermuda|hawaii)\s*cruise\b',
        ],
    },
    "rental": {
        "keywords": [
            "rental", "rent a car", "car rental", "rent car", "hire car",
            "car hire", "vehicle rental", "truck rental", "van rental",
            "suv rental", "economy car", "compact car", "midsize", "mid-size",
            "full-size", "fullsize", "convertible", "pickup truck",
            "minivan", "luxury car", "hertz", "avis", "enterprise",
            "budget", "national", "alamo", "sixt", "europcar",
        ],
        "patterns": [
            # "rent a <vehicle>"
            r'\brent\s+(?:a|an)\s+\w+\b',
            # "<vehicle_class> rental"
            r'\b(?:suv|sedan|compact|economy|luxury|convertible|van|truck|minivan)\s+rental\b',
            # "car at <airport>"
            r'\bcar\s+(?:at|from|in)\s+[A-Z]{3}\b',
        ],
    },
    "package": {
        "keywords": [
            "package", "vacation package", "bundle", "flight and hotel",
            "flight + hotel", "hotel and flight", "getaway", "all-inclusive",
            "all inclusive", "trip package", "travel package", "combo deal",
        ],
        "patterns": [
            # "flight and hotel to <place>"
            r'\bflight\s+and\s+hotel\b',
            # "hotel and flight"
            r'\bhotel\s+and\s+flight\b',
            # "fly and stay"
            r'\bfly\s+and\s+stay\b',
            # "trip to <place>" (general trip intent implies package)
            r'\btrip\s+to\b',
        ],
    },
}


# ---------------------------------------------------------------------------
# Arbitrage Fee Configuration — per vertical
# ---------------------------------------------------------------------------

ARBITRAGE_FEE_CONFIG = {
    "flight": {
        "fee_percent": 0.35,
    },
    "hotel": {
        "fee_percent": 0.35,
    },
    "cruise": {
        "fee_percent": 0.35,
    },
    "rental": {
        "fee_percent": 0.35,
    },
    "package": {
        "fee_percent": 0.30,
    },
}

# ---------------------------------------------------------------------------
# Common airport codes for parameter extraction
# ---------------------------------------------------------------------------

COMMON_AIRPORTS = {
    "JFK", "LAX", "SFO", "ORD", "MIA", "DFW", "SEA", "BOS", "ATL", "DEN",
    "LAS", "PHX", "IAH", "EWR", "MCO", "YYZ", "YVR", "YUL", "LHR", "LGW",
    "CDG", "FRA", "MUC", "FCO", "MXP", "MAD", "BCN", "AMS", "BRU", "ZRH",
    "NRT", "HND", "ICN", "PEK", "PVG", "HKG", "SIN", "BKK", "DEL", "BOM",
    "DXB", "DOH", "IST", "SYD", "MEL", "AKL", "GRU", "MEX", "CUN", "LIM",
    "BOG", "SCL", "CPT", "JNB", "NBO", "CAI", "ADD",
}

# Month name mapping for date extraction
MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}

# Vehicle class normalization
VEHICLE_CLASS_MAP = {
    "economy": "economy", "compact": "compact", "midsize": "midsize",
    "mid-size": "midsize", "fullsize": "fullsize", "full-size": "fullsize",
    "suv": "suv", "luxury": "luxury", "convertible": "convertible",
    "minivan": "minivan", "van": "van", "truck": "truck",
    "sedan": "midsize", "premium": "luxury",
}

# Cruise line normalization
CRUISE_LINE_MAP = {
    "carnival": "Carnival", "royal caribbean": "Royal Caribbean",
    "norwegian": "Norwegian", "ncl": "Norwegian",
    "msc": "MSC", "celebrity": "Celebrity",
    "princess": "Princess Cruises", "holland america": "Holland America",
    "disney": "Disney Cruise Line", "viking": "Viking",
    "cunard": "Cunard", "costa": "Costa",
}


# ---------------------------------------------------------------------------
# Date Extraction Helpers
# ---------------------------------------------------------------------------

def _parse_date_string(text):
    """Attempt to parse a date string into a date object.

    Tries dateutil first, then falls back to common formats.
    Returns None if parsing fails.
    """
    if not text:
        return None

    text = text.strip()

    if DATEUTIL_AVAILABLE:
        try:
            dt = dateutil_parser.parse(text, fuzzy=True)
            # If no year was specified and the date is in the past, bump to next year
            if dt.date() < date.today():
                dt = dt.replace(year=dt.year + 1)
            return dt.date()
        except (ValueError, OverflowError):
            pass

    # Manual fallback: try ISO format (2026-03-10)
    iso_match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', text)
    if iso_match:
        try:
            return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError:
            pass

    # Try "Month Day" or "Month Day, Year"
    month_day = re.search(
        r'(january|february|march|april|may|june|july|august|september|october|november|december'
        r'|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?',
        text, re.IGNORECASE,
    )
    if month_day:
        month_num = MONTH_NAMES.get(month_day.group(1).lower())
        day_num = int(month_day.group(2))
        year_num = int(month_day.group(3)) if month_day.group(3) else date.today().year
        try:
            d = date(year_num, month_num, day_num)
            if d < date.today() and not month_day.group(3):
                d = d.replace(year=d.year + 1)
            return d
        except ValueError:
            pass

    # Try MM/DD/YYYY or DD/MM/YYYY (assume US format)
    slash_match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', text)
    if slash_match:
        m, d, y = int(slash_match.group(1)), int(slash_match.group(2)), int(slash_match.group(3))
        if y < 100:
            y += 2000
        try:
            return date(y, m, d)
        except ValueError:
            pass

    return None


def _extract_date_range(query):
    """Extract a start and end date from a query string.

    Handles patterns like:
    - "March 15-18" / "March 15 - 18"
    - "March 15 to March 18"
    - "2026-03-10 to 2026-03-15"
    - "next week" / "next month"
    """
    query_lower = query.lower()

    # Pattern: "Month Day-Day" (e.g. "March 15-18")
    range_pattern = re.search(
        r'(january|february|march|april|may|june|july|august|september|october|november|december'
        r'|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})'
        r'(?:\s*,?\s*(\d{4}))?',
        query_lower,
    )
    if range_pattern:
        month_num = MONTH_NAMES.get(range_pattern.group(1))
        day_start = int(range_pattern.group(2))
        day_end = int(range_pattern.group(3))
        year = int(range_pattern.group(4)) if range_pattern.group(4) else date.today().year
        try:
            start = date(year, month_num, day_start)
            end = date(year, month_num, day_end)
            if start < date.today() and not range_pattern.group(4):
                start = start.replace(year=start.year + 1)
                end = end.replace(year=end.year + 1)
            return start, end
        except ValueError:
            pass

    # Pattern: "<date> to <date>"
    to_pattern = re.search(
        r'(\d{4}-\d{1,2}-\d{1,2})\s+to\s+(\d{4}-\d{1,2}-\d{1,2})',
        query,
    )
    if to_pattern:
        start = _parse_date_string(to_pattern.group(1))
        end = _parse_date_string(to_pattern.group(2))
        if start and end:
            return start, end

    # Pattern: "Month Day to Month Day"
    to_month_pattern = re.search(
        r'((?:january|february|march|april|may|june|july|august|september|october|november|december'
        r'|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+\d{1,2}(?:\s*,?\s*\d{4})?)'
        r'\s+to\s+'
        r'((?:january|february|march|april|may|june|july|august|september|october|november|december'
        r'|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+\d{1,2}(?:\s*,?\s*\d{4})?)',
        query_lower,
    )
    if to_month_pattern:
        start = _parse_date_string(to_month_pattern.group(1))
        end = _parse_date_string(to_month_pattern.group(2))
        if start and end:
            return start, end

    # "next week"
    if "next week" in query_lower:
        today = date.today()
        start = today + timedelta(days=(7 - today.weekday()))  # Next Monday
        end = start + timedelta(days=6)
        return start, end

    # "next month"
    if "next month" in query_lower:
        today = date.today()
        if today.month == 12:
            start = date(today.year + 1, 1, 1)
        else:
            start = date(today.year, today.month + 1, 1)
        # End = last day of next month
        if start.month == 12:
            end = date(start.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(start.year, start.month + 1, 1) - timedelta(days=1)
        return start, end

    # Single date extraction — return (date, None) for one-way / start-only
    single = _parse_date_string(query)
    if single:
        return single, None

    return None, None


def _extract_nights(query):
    """Extract number of nights from query (e.g. '3 nights', '7 night cruise')."""
    match = re.search(r'(\d+)\s*(?:night|nite)s?', query, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _extract_duration_days(query):
    """Extract duration in days from query (e.g. '5 days')."""
    match = re.search(r'(\d+)\s*days?', query, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _extract_location(query, exclude_airports=True):
    """Extract a city/location name from a query string.

    Looks for patterns like 'in <city>', 'to <city>', 'at <city>'.
    Strips out airport codes if exclude_airports is True.
    """
    # Try "in/to/at/near <location>" — capture 1-3 words after preposition
    loc_match = re.search(
        r'\b(?:in|to|at|near|around|from)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})',
        query,
    )
    if loc_match:
        location = loc_match.group(1).strip()
        if exclude_airports and location.upper() in COMMON_AIRPORTS:
            return None
        return location

    # Try capitalized multi-word (e.g. "New York", "San Francisco")
    cap_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})', query)
    if cap_match:
        location = cap_match.group(1).strip()
        # Filter out common non-location words
        skip_words = {"March", "April", "May", "June", "July", "August", "September",
                      "October", "November", "December", "January", "February",
                      "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                      "Saturday", "Sunday", "Carnival", "Royal", "Norwegian"}
        if location.split()[0] not in skip_words:
            return location

    return None


# ---------------------------------------------------------------------------
# ArbitrageSearchEngine
# ---------------------------------------------------------------------------

class ArbitrageSearchEngine:
    """Universal arbitrage search orchestrator.

    Accepts natural-language queries, classifies the travel vertical,
    extracts structured parameters, dispatches to the appropriate scraper
    pipeline, calculates fees, persists deals, and returns results.
    """

    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(self, query: str, user_id: Optional[int] = None, home_market: str = "US") -> Dict:
        """Universal entry point — classify intent, dispatch, return results.

        Args:
            query: Natural-language search query.
            user_id: Logged-in user ID (for consent economy tracking).
            home_market: 2-letter country code for the user's home market.

        Returns:
            dict with keys: vertical, query, params, deals, total_deals,
                            best_savings_usd, search_time_ms, error (if any).
        """
        start_ts = datetime.utcnow()
        result = {
            "vertical": None,
            "query": query,
            "params": {},
            "deals": [],
            "total_deals": 0,
            "best_savings_usd": 0.0,
            "search_time_ms": 0,
            "error": None,
        }

        try:
            # Step 1 — Classify intent
            intent = self.classify_intent(query)
            vertical = intent["vertical"]
            params = intent["params"]
            result["vertical"] = vertical
            result["params"] = params

            logger.info("Arbitrage search: vertical=%s params=%s home=%s",
                        vertical, json.dumps(params, default=str), home_market)

            # Step 2 — Dispatch to node-based search
            # All verticals resolved via Google Travel through onboarded
            # user nodes (Build #89 — Google-native architecture).
            if vertical not in ("flight", "hotel", "cruise", "rental", "package"):
                result["error"] = f"Unknown vertical: {vertical}"
                return result

            search_result = self._search_via_nodes(vertical, params, home_market)
            deals = search_result.get("deals", [])

            # Payment compatibility filter (Build #85)
            if user_id and deals:
            result["deals"] = deals
            result["total_deals"] = len(result["deals"])

            if result["deals"]:
                savings_values = [
                    d.get("user_savings_usd", 0) for d in result["deals"]
                    if d.get("user_savings_usd")
                ]
                result["best_savings_usd"] = max(savings_values) if savings_values else 0.0

            if search_result.get("error"):
                result["error"] = search_result["error"]

        except Exception as e:
            logger.exception("Arbitrage search failed for query: %s", query)
            result["error"] = str(e)

        elapsed = (datetime.utcnow() - start_ts).total_seconds() * 1000
        result["search_time_ms"] = round(elapsed, 1)
        return result

    # ------------------------------------------------------------------
    # Intent Classification
    # ------------------------------------------------------------------

    def classify_intent(self, query: str) -> Dict:
        """Classify the travel vertical and extract structured parameters.

        Uses a two-pass approach:
        1. Regex pattern matching (high confidence).
        2. Keyword frequency scoring (fallback).

        Returns:
            dict with keys: vertical (str), params (dict), confidence (float).
        """
        query_lower = query.lower()

        # --- Pass 1: Regex patterns (highest priority for packages) ---
        # Check package first since it often contains flight/hotel keywords
        for pattern_str in VERTICAL_CLASSIFIERS["package"]["patterns"]:
            if re.search(pattern_str, query_lower):
                return {
                    "vertical": "package",
                    "params": self._extract_package_params(query),
                    "confidence": 0.95,
                }

        # Check other verticals by pattern
        for vertical in ["flight", "cruise", "rental", "hotel"]:
            for pattern_str in VERTICAL_CLASSIFIERS[vertical]["patterns"]:
                if re.search(pattern_str, query, re.IGNORECASE):
                    extractor = {
                        "flight": self._extract_flight_params,
                        "hotel": self._extract_hotel_params,
                        "cruise": self._extract_cruise_params,
                        "rental": self._extract_rental_params,
                    }[vertical]
                    return {
                        "vertical": vertical,
                        "params": extractor(query),
                        "confidence": 0.90,
                    }

        # --- Pass 2: Keyword frequency scoring ---
        scores = {}
        for vertical, config in VERTICAL_CLASSIFIERS.items():
            score = 0
            for kw in config["keywords"]:
                # Use word boundary matching for short keywords to avoid false positives
                if len(kw) <= 3:
                    if re.search(r'\b' + re.escape(kw) + r'\b', query_lower):
                        score += 2
                else:
                    if kw in query_lower:
                        score += 1
            scores[vertical] = score

        # Pick the vertical with the highest score
        if scores:
            best_vertical = max(scores, key=scores.get)
            best_score = scores[best_vertical]

            if best_score > 0:
                extractor_map = {
                    "flight": self._extract_flight_params,
                    "hotel": self._extract_hotel_params,
                    "cruise": self._extract_cruise_params,
                    "rental": self._extract_rental_params,
                    "package": self._extract_package_params,
                }
                extractor = extractor_map.get(best_vertical, self._extract_flight_params)
                confidence = min(0.40 + (best_score * 0.10), 0.85)
                return {
                    "vertical": best_vertical,
                    "params": extractor(query),
                    "confidence": round(confidence, 2),
                }

        # Default to flight (most common travel search)
        return {
            "vertical": "flight",
            "params": self._extract_flight_params(query),
            "confidence": 0.20,
        }

    # ------------------------------------------------------------------
    # Parameter Extractors
    # ------------------------------------------------------------------

    def _extract_flight_params(self, query: str) -> Dict:
        """Extract origin, destination, date, and return_date from a flight query.

        Handles patterns:
        - "JFK to LHR March 15"
        - "LAX-NRT 2026-03-10"
        - "fly from SFO to CDG next month"
        """
        params = {"origin": None, "destination": None, "date": None, "return_date": None}

        # Airport code pair: "XXX to YYY" / "XXX-YYY" / "from XXX to YYY"
        pair_match = re.search(r'\b([A-Z]{3})\s*(?:to|->|-->|-)\s*([A-Z]{3})\b', query)
        if pair_match:
            params["origin"] = pair_match.group(1)
            params["destination"] = pair_match.group(2)
        else:
            # Try "from <code> to <code>"
            from_to = re.search(r'\bfrom\s+([A-Z]{3})\s+to\s+([A-Z]{3})\b', query)
            if from_to:
                params["origin"] = from_to.group(1)
                params["destination"] = from_to.group(2)
            else:
                # Extract any airport codes found
                codes = re.findall(r'\b([A-Z]{3})\b', query)
                airport_codes = [c for c in codes if c in COMMON_AIRPORTS]
                if len(airport_codes) >= 2:
                    params["origin"] = airport_codes[0]
                    params["destination"] = airport_codes[1]
                elif len(airport_codes) == 1:
                    params["destination"] = airport_codes[0]

        # Date extraction
        start_date, end_date = _extract_date_range(query)
        if start_date:
            params["date"] = start_date.isoformat()
        if end_date:
            params["return_date"] = end_date.isoformat()

        return params

    def _extract_hotel_params(self, query: str) -> Dict:
        """Extract location, check-in, check-out, and nights from a hotel query.

        Handles patterns:
        - "hotels in Tokyo March 15-18"
        - "3 nights in Paris"
        - "hotel near LAX check-in 2026-03-10"
        """
        params = {
            "location": None,
            "check_in": None,
            "check_out": None,
            "nights": None,
            "guests": 2,
            "room_type": "standard",
        }

        # Location
        params["location"] = _extract_location(query)

        # Nights
        nights = _extract_nights(query)
        if nights:
            params["nights"] = nights

        # Date range
        start_date, end_date = _extract_date_range(query)
        if start_date:
            params["check_in"] = start_date.isoformat()
        if end_date:
            params["check_out"] = end_date.isoformat()

        # If we have check_in and nights but no check_out, calculate it
        if params["check_in"] and params["nights"] and not params["check_out"]:
            ci = _parse_date_string(params["check_in"])
            if ci:
                params["check_out"] = (ci + timedelta(days=params["nights"])).isoformat()

        # If we have check_in and check_out but no nights, calculate
        if params["check_in"] and params["check_out"] and not params["nights"]:
            ci = _parse_date_string(params["check_in"])
            co = _parse_date_string(params["check_out"])
            if ci and co and co > ci:
                params["nights"] = (co - ci).days

        # Guest count
        guest_match = re.search(r'(\d+)\s*(?:guest|person|people|adult)s?', query, re.IGNORECASE)
        if guest_match:
            params["guests"] = int(guest_match.group(1))

        # Room type
        for room in ["suite", "deluxe", "standard", "executive", "penthouse", "family"]:
            if room in query.lower():
                params["room_type"] = room
                break

        return params

    def _extract_cruise_params(self, query: str) -> Dict:
        """Extract cruise_line, departure_port, duration, and date from a cruise query.

        Handles patterns:
        - "cruise caribbean 7 nights"
        - "Royal Caribbean Alaska cruise May 2026"
        - "cruise from Miami 5 nights"
        """
        params = {
            "cruise_line": None,
            "departure_port": None,
            "destination_region": None,
            "duration_nights": None,
            "date": None,
            "cabin_category": "inside",
        }

        query_lower = query.lower()

        # Cruise line detection
        for key, name in CRUISE_LINE_MAP.items():
            if key in query_lower:
                params["cruise_line"] = name
                break

        # Duration
        nights = _extract_nights(query)
        if nights:
            params["duration_nights"] = nights
        else:
            days = _extract_duration_days(query)
            if days:
                params["duration_nights"] = days - 1 if days > 1 else days

        # Departure port — look for airport/port codes
        port_match = re.search(r'\bfrom\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', query)
        if port_match:
            params["departure_port"] = port_match.group(1)
        else:
            codes = re.findall(r'\b([A-Z]{3})\b', query)
            airport_codes = [c for c in codes if c in COMMON_AIRPORTS]
            if airport_codes:
                params["departure_port"] = airport_codes[0]

        # Destination region
        regions = {
            "caribbean": "Caribbean", "alaska": "Alaska",
            "mediterranean": "Mediterranean", "bahamas": "Bahamas",
            "bermuda": "Bermuda", "hawaii": "Hawaii", "europe": "Europe",
            "transatlantic": "Transatlantic", "asia": "Asia",
            "south pacific": "South Pacific", "mexican riviera": "Mexican Riviera",
        }
        for key, name in regions.items():
            if key in query_lower:
                params["destination_region"] = name
                break

        # Date
        start_date, _ = _extract_date_range(query)
        if start_date:
            params["date"] = start_date.isoformat()

        # Cabin category
        cabins = {
            "balcony": "balcony", "ocean view": "ocean_view", "oceanview": "ocean_view",
            "interior": "inside", "inside": "inside", "suite": "suite",
            "stateroom": "inside",
        }
        for key, cat in cabins.items():
            if key in query_lower:
                params["cabin_category"] = cat
                break

        return params

    def _extract_rental_params(self, query: str) -> Dict:
        """Extract location, pickup/dropoff dates, and vehicle class from a rental query.

        Handles patterns:
        - "SUV rental LAX"
        - "rent a car in Miami March 10-15"
        - "economy car Los Angeles next week"
        """
        params = {
            "location": None,
            "pickup_date": None,
            "dropoff_date": None,
            "rental_days": None,
            "vehicle_class": "economy",
        }

        query_lower = query.lower()

        # Vehicle class
        for key, cls in VEHICLE_CLASS_MAP.items():
            if key in query_lower:
                params["vehicle_class"] = cls
                break

        # Location — try airport code first
        codes = re.findall(r'\b([A-Z]{3})\b', query)
        airport_codes = [c for c in codes if c in COMMON_AIRPORTS]
        if airport_codes:
            params["location"] = airport_codes[0]
        else:
            params["location"] = _extract_location(query)

        # Date range
        start_date, end_date = _extract_date_range(query)
        if start_date:
            params["pickup_date"] = start_date.isoformat()
        if end_date:
            params["dropoff_date"] = end_date.isoformat()

        # Duration in days
        days = _extract_duration_days(query)
        if days:
            params["rental_days"] = days
        elif not days:
            nights = _extract_nights(query)
            if nights:
                params["rental_days"] = nights

        # Calculate missing values
        if params["pickup_date"] and params["rental_days"] and not params["dropoff_date"]:
            pd = _parse_date_string(params["pickup_date"])
            if pd:
                params["dropoff_date"] = (pd + timedelta(days=params["rental_days"])).isoformat()

        if params["pickup_date"] and params["dropoff_date"] and not params["rental_days"]:
            pd = _parse_date_string(params["pickup_date"])
            dd = _parse_date_string(params["dropoff_date"])
            if pd and dd and dd > pd:
                params["rental_days"] = (dd - pd).days

        return params

    def _extract_package_params(self, query: str) -> Dict:
        """Extract combined flight + hotel params for vacation package queries."""
        flight_params = self._extract_flight_params(query)
        hotel_params = self._extract_hotel_params(query)

        # Merge — use flight destination as hotel location if not set
        location = hotel_params.get("location") or flight_params.get("destination")

        params = {
            "origin": flight_params.get("origin"),
            "destination": flight_params.get("destination"),
            "location": location,
            "date": flight_params.get("date") or hotel_params.get("check_in"),
            "return_date": flight_params.get("return_date") or hotel_params.get("check_out"),
            "nights": hotel_params.get("nights"),
            "guests": hotel_params.get("guests", 2),
        }

        # If we have date + nights but no return_date, calculate it
        if params["date"] and params["nights"] and not params["return_date"]:
            sd = _parse_date_string(params["date"])
            if sd:
                params["return_date"] = (sd + timedelta(days=params["nights"])).isoformat()

        return params

    # ------------------------------------------------------------------
    # Vertical Search Dispatchers
    # ------------------------------------------------------------------

    def _search_via_nodes(self, vertical: str, params: Dict, home_market: str) -> Dict:
        """Node-based search (CitizenSERP — archived in Build #168)."""
        return {"deals": [], "error": None}

    def _build_arbitrage_deals(
        self,
        vertical: str,
        home_results: List[Dict],
        home_market: str,
        market_results: Dict[str, List[Dict]],
        params: Dict,
    ) -> List[Dict]:
        """Compare home market prices against foreign markets to find deals.

        Matches items across markets by name/key, calculates savings,
        applies fees, and returns sorted deal list.
        """
        deals = []
        fee_config = ARBITRAGE_FEE_CONFIG.get(vertical, ARBITRAGE_FEE_CONFIG["flight"])

        for home_item in home_results:
            home_price = home_item.get("price") or home_item.get("price_usd", 0)
            if not home_price or home_price <= 0:
                continue

            item_key = self._item_key(vertical, home_item)

            # Find cheapest match across foreign markets
            best_foreign = None
            best_market = None
            best_price = home_price

            for market, items in market_results.items():
                for foreign_item in items:
                    foreign_price = foreign_item.get("price") or foreign_item.get("price_usd", 0)
                    if not foreign_price or foreign_price <= 0:
                        continue

                    # Match by item key (name, route, etc.)
                    if self._item_key(vertical, foreign_item) == item_key:
                        if foreign_price < best_price:
                            best_price = foreign_price
                            best_foreign = foreign_item
                            best_market = market

            if best_foreign and best_market:
                gross_savings = home_price - best_price
                if gross_savings <= 0:
                    continue

                fee_info = self._calculate_fee(vertical, gross_savings)
                user_savings = gross_savings - fee_info["platform_fee_usd"]
                if user_savings <= 0:
                    continue

                savings_pct = (gross_savings / home_price * 100) if home_price > 0 else 0

                deal = {
                    "vertical": vertical,
                    "deal_id": f"{vertical[0].upper()}D-{secrets.token_hex(6)}",
                    "item_name": home_item.get("hotel_name") or home_item.get("airline")
                                 or home_item.get("cruise_line") or home_item.get("rental_company")
                                 or item_key,
                    "home_market": home_market,
                    "home_price_usd": round(home_price, 2),
                    "arbitrage_market": best_market,
                    "arbitrage_price_usd": round(best_price, 2),
                    "gross_savings_usd": round(gross_savings, 2),
                    "platform_fee_usd": fee_info["platform_fee_usd"],
                    "user_savings_usd": round(user_savings, 2),
                    "savings_percent": round(savings_pct, 1),
                    "home_item": home_item,
                    "arbitrage_item": best_foreign,
                    "params": params,
                    "source_url": best_foreign.get("source_url", ""),
                    "created_at": datetime.utcnow().isoformat(),
                }
                deals.append(deal)

        # Sort by user savings descending
        deals.sort(key=lambda d: d.get("user_savings_usd", 0), reverse=True)
        return deals

    @staticmethod
    def _item_key(vertical: str, item: Dict) -> str:
        """Generate a matching key for cross-market item comparison."""
        if vertical == "flight":
            return f"{item.get('airline', '').lower()}:{item.get('origin', '')}>{item.get('destination', '')}"
        elif vertical == "hotel":
            return (item.get("hotel_name") or item.get("name", "")).lower().strip()
        elif vertical == "cruise":
            return f"{(item.get('cruise_line') or item.get('line', '')).lower()}:{item.get('duration_nights', '')}"
        elif vertical == "rental":
            return f"{(item.get('rental_company') or item.get('company', '')).lower()}:{(item.get('vehicle_class') or item.get('class', '')).lower()}"
        else:
            return json.dumps(sorted(item.items()), default=str)[:100]

    # ------------------------------------------------------------------
    # Fee Calculation
    # ------------------------------------------------------------------

    def _calculate_fee(self, vertical: str, gross_savings: float, user=None) -> Dict:
        """Calculate the platform fee for a given vertical and gross savings amount.

        Subscribers: 35% of gross savings. Non-subscribers: 50%.
        No minimum savings threshold — we sell tickets regardless.

        Returns:
            dict with keys: platform_fee_usd, fee_percent, gross_savings_usd.
        """
        from payments import get_fee_percent
        fee_percent = get_fee_percent(user)
        platform_fee = gross_savings * fee_percent

        return {
            "platform_fee_usd": round(platform_fee, 2),
            "fee_percent": fee_percent,
            "gross_savings_usd": round(gross_savings, 2),
        }



# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

arbitrage_engine = ArbitrageSearchEngine()
