"""
SearchOrchestrator — Card-guided multi-source flight search with deduplication.

Replaces inline search orchestration in MYSTES's search.py with card-driven dispatch.
Zero Anthropic API cost — pure Python logic reading JSON knowledge cards.

Architecture:
    MYSTES passes: search params + client instances
    Orchestrator reads: knowledge cards for priority + cabin mapping
    Orchestrator calls: each client's search_flights() in parallel
    Orchestrator deduplicates: same airline + ±15 min departure = keep cheapest
    Returns: unified flight list with raw_offers ready for BookingDispatcher

The orchestrator does NOT calculate deals, fees, or savings — that's MYSTES template logic.
It produces raw search results that MYSTES enriches with pricing intelligence.
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Airline normalization for cross-source deduplication
# ---------------------------------------------------------------------------

_AIRLINE_STRIP = re.compile(
    r"\s*(airlines?|airways?|air\s*lines?|international|intl|" r"aviation|transport)\s*$",
    re.IGNORECASE,
)

_AIRLINE_CODES = {
    "AA": "american",
    "DL": "delta",
    "UA": "united",
    "WN": "southwest",
    "BA": "british",
    "LH": "lufthansa",
    "AF": "air france",
    "KL": "klm",
    "EK": "emirates",
    "QR": "qatar",
    "SQ": "singapore",
    "CX": "cathay",
    "NH": "ana",
    "JL": "japan",
    "QF": "qantas",
    "AC": "air canada",
    "IB": "iberia",
    "AY": "finnair",
    "SK": "sas",
    "TK": "turkish",
    "LX": "swiss",
    "OS": "austrian",
    "SN": "brussels",
    "AZ": "ita",
    "FR": "ryanair",
    "U2": "easyjet",
    "W6": "wizz",
    "VY": "vueling",
    "NK": "spirit",
    "F9": "frontier",
    "B6": "jetblue",
    "AS": "alaska",
    "HA": "hawaiian",
    "AM": "aeromexico",
    "AV": "avianca",
    "LA": "latam",
    "VS": "virgin atlantic",
    "EI": "aer lingus",
    "A3": "aegean",
    "ET": "ethiopian",
    "SA": "south african",
    "KE": "korean air",
    "OZ": "asiana",
    "CI": "china airlines",
    "BR": "eva air",
    "MH": "malaysia",
    "TG": "thai",
    "GA": "garuda",
    "AI": "air india",
}

# Cabin class mappings per source (from knowledge cards)
_CABIN_MAPS = {
    "picasso": {
        "economy": "ECONOMY",
        "premium_economy": "PREMIUM_ECONOMY",
        "business": "BUSINESS",
        "first": "FIRST",
    },
    "picasso_redbox": {
        "economy": "ECONOMY",
        "premium_economy": "PREMIUM_ECONOMY",
        "business": "BUSINESS",
        "first": "FIRST",
    },
    "duffel_ndc": {
        "economy": "economy",
        "premium_economy": "premium_economy",
        "business": "business",
        "first": "first",
    },
    "kiwi_tequila": {
        "economy": "M",
        "premium_economy": "W",
        "business": "C",
        "first": "F",
    },
    "airgateway_ndc": {
        "economy": "7",
        "premium_economy": "4",
        "business": "2",
        "first": "1",
    },
}


def _norm_airline(name: str) -> str:
    """Normalize airline name for cross-source comparison."""
    if not name:
        return ""
    name = name.strip()
    upper = name.upper()
    if len(name) <= 3 and upper in _AIRLINE_CODES:
        return _AIRLINE_CODES[upper]
    result = _AIRLINE_STRIP.sub("", name).strip().lower()
    return result or name.lower()


def _extract_minutes(time_str: str) -> Optional[int]:
    """Extract departure time as minutes since midnight for ±15 min comparison."""
    if not time_str:
        return None
    time_str = time_str.strip()
    try:
        match = re.match(r"(\d{1,2}):(\d{2})", time_str)
        if match:
            h, m = int(match.group(1)), int(match.group(2))
            if "pm" in time_str.lower() and h != 12:
                h += 12
            elif "am" in time_str.lower() and h == 12:
                h = 0
            return h * 60 + m
    except (ValueError, AttributeError):
        pass
    return None


class SearchOrchestrator:
    """
    Card-guided multi-source flight search with deduplication.

    Searches all available API sources in parallel, normalizes results into
    a standard format, deduplicates across sources (keep cheapest per route),
    and attaches raw_offer booking references for the BookingDispatcher.

    Usage from MYSTES:
        orchestrator = SearchOrchestrator()
        results = orchestrator.search(
            origin="JFK", destination="FCO", departure_date="2026-04-15",
            clients={"picasso": picasso_client, "duffel_ndc": duffel_client},
        )
        for flight in results["flights"]:
            print(flight["airline"], flight["price"], flight["raw_offer"])
    """

    _SOURCE_ALIASES = {
        "picasso": "picasso_redbox",
        "liteapi": "liteapi_hotels",
    }

    def __init__(self, cards_dir: Optional[str] = None):
        self.cards: Dict[str, dict] = {}
        self._load_cards(cards_dir)

    def _load_cards(self, cards_dir: Optional[str] = None):
        """Load knowledge cards from JSON files."""
        if cards_dir is None:
            cards_dir = os.path.join(
                os.path.dirname(__file__), "..", "modules", "cards"
            )
        cards_dir = os.path.abspath(cards_dir)
        if not os.path.isdir(cards_dir):
            return
        for fname in os.listdir(cards_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(cards_dir, fname)) as f:
                    card = json.load(f)
                mid = card.get("module_id", fname.replace(".json", ""))
                self.cards[mid] = card
            except Exception as e:
                logger.warning(f"Failed to load card {fname}: {e}")
        for alias, mid in self._SOURCE_ALIASES.items():
            if mid in self.cards and alias not in self.cards:
                self.cards[alias] = self.cards[mid]

    def search(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        clients: dict,
        return_date: Optional[str] = None,
        adults: int = 1,
        children: int = 0,
        infants: int = 0,
        cabin_class: str = "economy",
        max_results: int = 50,
        timeout_seconds: int = 30,
        credential_router=None,
        requester_tenant_id: Optional[str] = None,
    ) -> dict:
        """
        Search all registered flight sources in parallel with deduplication.

        Args:
            origin: IATA airport code (e.g., "JFK")
            destination: IATA airport code (e.g., "FCO")
            departure_date: "YYYY-MM-DD"
            clients: {source_name: client_instance} — injected by MYSTES
            return_date: Optional "YYYY-MM-DD" for round-trips
            adults/children/infants: Passenger counts
            cabin_class: "economy" | "premium_economy" | "business" | "first"
            max_results: Max flights per source
            timeout_seconds: Per-source search timeout
            credential_router: Optional CredentialRouter for network-routed clients
            requester_tenant_id: Tenant ID for credential routing (B2B/APAi)

        Returns:
            {
                success: bool,
                flights: [{airline, flight_number, departure_time, arrival_time,
                           duration, stops, price, currency, source, raw_offer,
                           segments, baggage, cabin_class, fare_family, layovers}],
                sources_searched: [str],
                sources_failed: [str],
                total_flights: int,
                source_metadata: {source: {fare_search_id, offer_request_id, ...}},
            }
        """
        # Credential network routing: merge network-routed clients
        self._routing_metadata = {}  # source → RoutingResult (for raw_offer injection)
        if credential_router and requester_tenant_id:
            try:
                routed = credential_router.get_routed_clients(
                    requester_tenant_id,
                    requested_sources=list(clients.keys()) + ["picasso", "duffel_ndc", "kiwi_tequila"],
                )
                for source, entry in routed.items():
                    if source not in clients and entry.get("client"):
                        clients[source] = entry["client"]
                    if entry.get("routing"):
                        self._routing_metadata[source] = entry["routing"]
                    logger.info(
                        "[SEARCH] Credential routing: %s → Tier %d (owner=%s)",
                        source, entry.get("tier", 0), entry.get("owner_tenant_id", "self"),
                    )
            except Exception as e:
                logger.warning("[SEARCH] Credential routing failed, using standard clients: %s", e)

        search_plan = self._build_plan(clients)

        if not search_plan:
            return {
                "success": False,
                "error": "No flight search sources available",
                "flights": [],
                "sources_searched": [],
                "sources_failed": [],
                "total_flights": 0,
                "source_metadata": {},
            }

        all_flights = []
        sources_searched = []
        sources_failed = []
        source_metadata = {}

        with ThreadPoolExecutor(max_workers=min(len(search_plan), 4)) as executor:
            futures = {}
            for source in search_plan:
                client = clients[source]
                cabin = _CABIN_MAPS.get(source, {}).get(
                    cabin_class.lower(), cabin_class
                )
                future = executor.submit(
                    self._search_one,
                    source,
                    client,
                    origin,
                    destination,
                    departure_date,
                    return_date,
                    adults,
                    children,
                    infants,
                    cabin,
                    max_results,
                )
                futures[future] = source

            for future in as_completed(futures, timeout=timeout_seconds + 5):
                source = futures[future]
                try:
                    result = future.result(timeout=timeout_seconds)
                    if result and result.get("success") and result.get("flights"):
                        # Store source-level metadata (fare_search_id, etc.)
                        source_metadata[source] = {
                            k: v
                            for k, v in result.items()
                            if k not in ("success", "flights", "source")
                        }
                        for flight in result["flights"]:
                            normalized = self._normalize_flight(
                                flight, source, result
                            )
                            if normalized:
                                all_flights.append(normalized)
                        sources_searched.append(source)
                        logger.info(
                            f"[SEARCH] {source}: {len(result['flights'])} flights"
                        )
                    else:
                        error = (
                            result.get("error", "No results")
                            if result
                            else "Empty response"
                        )
                        sources_failed.append(source)
                        logger.info(f"[SEARCH] {source}: {error}")
                except Exception as e:
                    sources_failed.append(source)
                    logger.warning(f"[SEARCH] {source} error: {e}")

        # Deduplicate across all sources — keep cheapest per route
        unified = self._deduplicate(all_flights)

        return {
            "success": len(unified) > 0,
            "flights": unified,
            "sources_searched": sources_searched,
            "sources_failed": sources_failed,
            "total_flights": len(unified),
            "source_metadata": source_metadata,
        }

    def _build_plan(self, clients: dict) -> List[str]:
        """Return available sources sorted by knowledge card priority."""
        available = []
        for source in clients:
            card = self.cards.get(source, {})
            if card.get("capabilities", {}).get("search"):
                priority = card.get("priority", 0)
                available.append((priority, source))
        available.sort(reverse=True)
        return [s for _, s in available]

    def _search_one(
        self,
        source,
        client,
        origin,
        destination,
        date,
        return_date,
        adults,
        children,
        infants,
        cabin,
        max_results,
    ):
        """Call a single client's search_flights() with normalized params."""
        try:
            kwargs = {
                "origin": origin,
                "destination": destination,
                "departure_date": date,
                "adults": adults,
                "children": children,
                "infants": infants,
                "cabin_class": cabin,
            }
            if return_date:
                kwargs["return_date"] = return_date

            # Source-specific max results parameter
            if source == "kiwi_tequila":
                kwargs["limit"] = max_results
            else:
                kwargs["max_results"] = max_results

            # Support both class instances and convenience functions
            if hasattr(client, "search_flights"):
                return client.search_flights(**kwargs)
            elif callable(client):
                return client(**kwargs)
            else:
                return {"success": False, "error": f"Client for {source} not callable"}

        except TypeError as te:
            # Handle parameter mismatches gracefully
            logger.warning(f"[SEARCH] {source} param error: {te}")
            # Retry with minimal params
            try:
                minimal = {
                    "origin": origin,
                    "destination": destination,
                    "departure_date": date,
                }
                if hasattr(client, "search_flights"):
                    return client.search_flights(**minimal)
            except Exception:
                pass
            return {"success": False, "error": str(te)}
        except Exception as e:
            logger.error(f"[SEARCH] {source} search error: {e}")
            return {"success": False, "error": str(e)}

    def _normalize_flight(self, flight: dict, source: str, result: dict) -> Optional[dict]:
        """Normalize a flight result into standard MYSTES format with raw_offer."""
        try:
            price = float(
                flight.get("price", flight.get("total_amount", flight.get("amount", 0)))
            )
            if price <= 0:
                return None

            airline = flight.get("airline", flight.get("airline_name", ""))
            flight_number = flight.get(
                "flight_number",
                flight.get("flightNumber", flight.get("flight_no", "")),
            )
            dep_time = flight.get(
                "departure_time",
                flight.get("departureTime", flight.get("dep_time", "")),
            )
            arr_time = flight.get(
                "arrival_time",
                flight.get("arrivalTime", flight.get("arr_time", "")),
            )
            duration = flight.get(
                "duration", flight.get("duration_formatted", flight.get("fly_duration", ""))
            )
            stops = int(flight.get("stops", flight.get("stop_count", flight.get("technical_stops", 0))))
            currency = flight.get("currency", "USD")

            raw_offer = self._build_raw_offer(flight, source, result)

            return {
                "airline": airline,
                "flight_number": flight_number,
                "departure_time": dep_time,
                "arrival_time": arr_time,
                "duration": duration,
                "stops": stops,
                "price": price,
                "currency": currency,
                "source": source,
                "raw_offer": raw_offer,
                # Pass-through detail fields
                "segments": flight.get("segments", []),
                "baggage": flight.get(
                    "baggage",
                    flight.get("baggages", flight.get("baggage_info", "")),
                ),
                "cabin_class": flight.get(
                    "cabin_class", flight.get("cabinClass", flight.get("cabin", ""))
                ),
                "fare_family": flight.get(
                    "fare_family", flight.get("fareFamily", flight.get("brand", ""))
                ),
                "layovers": flight.get(
                    "layovers",
                    flight.get("stop_airports", flight.get("via", [])),
                ),
                # Policies
                "cancellation_policy": flight.get("cancellation_policy", ""),
                "rebooking_policy": flight.get("rebooking_policy", ""),
                "ticket_deadline": flight.get("ticket_deadline", ""),
            }
        except Exception as e:
            logger.warning(f"Failed to normalize flight from {source}: {e}")
            return None

    def _build_raw_offer(self, flight: dict, source: str, result: dict) -> dict:
        """Build raw_offer dict with booking references for BookingDispatcher."""
        if source in ("picasso", "picasso_redbox"):
            raw = {
                "fare_id": flight.get("fare_id", flight.get("offer_id", "")),
                "fare_search_id": result.get("fare_search_id", ""),
                "source": "picasso",
            }
        elif source == "duffel_ndc":
            raw = {
                "offer_id": flight.get("offer_id", ""),
                "source": "duffel_ndc",
            }
        elif source == "kiwi_tequila":
            raw = {
                "booking_token": flight.get("booking_token", ""),
                "kiwi_id": flight.get("kiwi_id", flight.get("id", "")),
                "source": "kiwi_tequila",
            }
        elif source == "airgateway_ndc":
            raw = {
                "offer_id": flight.get("offer_id", ""),
                "shopping_response_id": result.get("shopping_response_id", ""),
                "source": "airgateway_ndc",
            }
        else:
            raw = {"source": source}

        # Inject credential routing metadata (survives dedup — travels with winner)
        routing_meta = getattr(self, "_routing_metadata", {}).get(source)
        if routing_meta:
            raw["_routing"] = {
                "result_id": getattr(routing_meta, "result_id", ""),
                "credential_id": getattr(routing_meta, "credential_id", ""),
                "owner_tenant_id": getattr(routing_meta, "owner_tenant_id", ""),
                "requester_tenant_id": getattr(routing_meta, "requester_tenant_id", ""),
                "routing_tier": getattr(routing_meta, "routing_tier", 0),
            }

        return raw

    def _deduplicate(self, flights: List[dict]) -> List[dict]:
        """
        Deduplicate flights across sources.

        Rule: Same normalized airline + departure time within ±15 minutes = duplicate.
        Action: Keep the cheapest price. Winner's raw_offer replaces loser's.

        Returns flights sorted by price (cheapest first).
        """
        if not flights:
            return []

        unique: List[dict] = []

        for flight in flights:
            airline_norm = _norm_airline(flight.get("airline", ""))
            dep_minutes = _extract_minutes(flight.get("departure_time", ""))
            price = flight.get("price", 0)

            is_dup = False
            for i, existing in enumerate(unique):
                ex_airline = _norm_airline(existing.get("airline", ""))
                ex_minutes = _extract_minutes(existing.get("departure_time", ""))

                if (
                    airline_norm
                    and ex_airline
                    and airline_norm == ex_airline
                    and dep_minutes is not None
                    and ex_minutes is not None
                    and abs(dep_minutes - ex_minutes) <= 15
                ):
                    is_dup = True
                    # Keep cheapest
                    ex_price = existing.get("price", 0)
                    if price > 0 and (ex_price <= 0 or price < ex_price):
                        unique[i] = flight
                    break

            if not is_dup:
                unique.append(flight)

        unique.sort(key=lambda f: f.get("price", float("inf")))
        return unique
