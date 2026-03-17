"""
Mock Data Provider — Simulated flight, booking, and ancillary data for sandboxes.

Generates realistic but clearly-marked test data that mirrors real GDS
responses. Uses seeded randomness so identical inputs produce identical
outputs, making sandbox behavior reproducible for agency evaluations.

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import logging
import random
import string
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reference data — real airline codes, airports, and route characteristics
# ---------------------------------------------------------------------------

AIRLINES = {
    "AA": {"name": "American Airlines", "country": "US"},
    "DL": {"name": "Delta Air Lines", "country": "US"},
    "UA": {"name": "United Airlines", "country": "US"},
    "WN": {"name": "Southwest Airlines", "country": "US"},
    "B6": {"name": "JetBlue Airways", "country": "US"},
    "AS": {"name": "Alaska Airlines", "country": "US"},
    "NK": {"name": "Spirit Airlines", "country": "US"},
    "F9": {"name": "Frontier Airlines", "country": "US"},
    "HA": {"name": "Hawaiian Airlines", "country": "US"},
    "SY": {"name": "Sun Country Airlines", "country": "US"},
    "BA": {"name": "British Airways", "country": "GB"},
    "LH": {"name": "Lufthansa", "country": "DE"},
    "AF": {"name": "Air France", "country": "FR"},
    "KL": {"name": "KLM Royal Dutch Airlines", "country": "NL"},
    "IB": {"name": "Iberia", "country": "ES"},
    "AZ": {"name": "ITA Airways", "country": "IT"},
    "SK": {"name": "SAS Scandinavian Airlines", "country": "SE"},
    "LX": {"name": "Swiss International Air Lines", "country": "CH"},
    "OS": {"name": "Austrian Airlines", "country": "AT"},
    "TP": {"name": "TAP Air Portugal", "country": "PT"},
    "EK": {"name": "Emirates", "country": "AE"},
    "QR": {"name": "Qatar Airways", "country": "QA"},
    "EY": {"name": "Etihad Airways", "country": "AE"},
    "TK": {"name": "Turkish Airlines", "country": "TR"},
    "SQ": {"name": "Singapore Airlines", "country": "SG"},
    "CX": {"name": "Cathay Pacific", "country": "HK"},
    "QF": {"name": "Qantas", "country": "AU"},
    "NZ": {"name": "Air New Zealand", "country": "NZ"},
    "JL": {"name": "Japan Airlines", "country": "JP"},
    "NH": {"name": "All Nippon Airways", "country": "JP"},
    "KE": {"name": "Korean Air", "country": "KR"},
    "OZ": {"name": "Asiana Airlines", "country": "KR"},
    "AI": {"name": "Air India", "country": "IN"},
    "CA": {"name": "Air China", "country": "CN"},
    "CZ": {"name": "China Southern Airlines", "country": "CN"},
    "MU": {"name": "China Eastern Airlines", "country": "CN"},
    "SA": {"name": "South African Airways", "country": "ZA"},
    "ET": {"name": "Ethiopian Airlines", "country": "ET"},
    "MS": {"name": "EgyptAir", "country": "EG"},
    "AM": {"name": "Aeromexico", "country": "MX"},
    "AV": {"name": "Avianca", "country": "CO"},
    "LA": {"name": "LATAM Airlines", "country": "CL"},
    "AC": {"name": "Air Canada", "country": "CA"},
    "WS": {"name": "WestJet", "country": "CA"},
    "FR": {"name": "Ryanair", "country": "IE"},
    "U2": {"name": "easyJet", "country": "GB"},
    "W6": {"name": "Wizz Air", "country": "HU"},
    "VY": {"name": "Vueling", "country": "ES"},
    "DY": {"name": "Norwegian Air Shuttle", "country": "NO"},
    "FI": {"name": "Icelandair", "country": "IS"},
    "VS": {"name": "Virgin Atlantic", "country": "GB"},
    "G3": {"name": "Gol Linhas Aereas", "country": "BR"},
}

AIRPORTS = {
    "JFK": {"city": "New York", "country": "US", "timezone": "America/New_York"},
    "LAX": {"city": "Los Angeles", "country": "US", "timezone": "America/Los_Angeles"},
    "ORD": {"city": "Chicago", "country": "US", "timezone": "America/Chicago"},
    "ATL": {"city": "Atlanta", "country": "US", "timezone": "America/New_York"},
    "DFW": {"city": "Dallas", "country": "US", "timezone": "America/Chicago"},
    "DEN": {"city": "Denver", "country": "US", "timezone": "America/Denver"},
    "SFO": {"city": "San Francisco", "country": "US", "timezone": "America/Los_Angeles"},
    "SEA": {"city": "Seattle", "country": "US", "timezone": "America/Los_Angeles"},
    "MIA": {"city": "Miami", "country": "US", "timezone": "America/New_York"},
    "BOS": {"city": "Boston", "country": "US", "timezone": "America/New_York"},
    "EWR": {"city": "Newark", "country": "US", "timezone": "America/New_York"},
    "IAD": {"city": "Washington", "country": "US", "timezone": "America/New_York"},
    "PHX": {"city": "Phoenix", "country": "US", "timezone": "America/Phoenix"},
    "LAS": {"city": "Las Vegas", "country": "US", "timezone": "America/Los_Angeles"},
    "MCO": {"city": "Orlando", "country": "US", "timezone": "America/New_York"},
    "LHR": {"city": "London", "country": "GB", "timezone": "Europe/London"},
    "LGW": {"city": "London", "country": "GB", "timezone": "Europe/London"},
    "CDG": {"city": "Paris", "country": "FR", "timezone": "Europe/Paris"},
    "FRA": {"city": "Frankfurt", "country": "DE", "timezone": "Europe/Berlin"},
    "AMS": {"city": "Amsterdam", "country": "NL", "timezone": "Europe/Amsterdam"},
    "MAD": {"city": "Madrid", "country": "ES", "timezone": "Europe/Madrid"},
    "BCN": {"city": "Barcelona", "country": "ES", "timezone": "Europe/Madrid"},
    "FCO": {"city": "Rome", "country": "IT", "timezone": "Europe/Rome"},
    "MUC": {"city": "Munich", "country": "DE", "timezone": "Europe/Berlin"},
    "ZRH": {"city": "Zurich", "country": "CH", "timezone": "Europe/Zurich"},
    "IST": {"city": "Istanbul", "country": "TR", "timezone": "Europe/Istanbul"},
    "DXB": {"city": "Dubai", "country": "AE", "timezone": "Asia/Dubai"},
    "DOH": {"city": "Doha", "country": "QA", "timezone": "Asia/Qatar"},
    "SIN": {"city": "Singapore", "country": "SG", "timezone": "Asia/Singapore"},
    "HKG": {"city": "Hong Kong", "country": "HK", "timezone": "Asia/Hong_Kong"},
    "NRT": {"city": "Tokyo", "country": "JP", "timezone": "Asia/Tokyo"},
    "HND": {"city": "Tokyo", "country": "JP", "timezone": "Asia/Tokyo"},
    "ICN": {"city": "Seoul", "country": "KR", "timezone": "Asia/Seoul"},
    "SYD": {"city": "Sydney", "country": "AU", "timezone": "Australia/Sydney"},
    "MEX": {"city": "Mexico City", "country": "MX", "timezone": "America/Mexico_City"},
    "GRU": {"city": "Sao Paulo", "country": "BR", "timezone": "America/Sao_Paulo"},
    "YYZ": {"city": "Toronto", "country": "CA", "timezone": "America/Toronto"},
    "YVR": {"city": "Vancouver", "country": "CA", "timezone": "America/Vancouver"},
}

# Route type classification — determines pricing and duration ranges
ROUTE_TYPES = {
    "domestic_us": {
        "price_range": (80, 400),
        "duration_range": (60, 360),  # minutes
        "carriers": ["AA", "DL", "UA", "WN", "B6", "AS", "NK", "F9"],
    },
    "transatlantic": {
        "price_range": (300, 1500),
        "duration_range": (420, 600),
        "carriers": ["AA", "DL", "UA", "BA", "LH", "AF", "KL", "VS", "IB"],
    },
    "transpacific": {
        "price_range": (400, 2000),
        "duration_range": (660, 960),
        "carriers": ["UA", "DL", "AA", "JL", "NH", "SQ", "CX", "KE"],
    },
    "europe_internal": {
        "price_range": (40, 300),
        "duration_range": (60, 240),
        "carriers": ["LH", "AF", "BA", "FR", "U2", "W6", "VY", "SK"],
    },
    "middle_east": {
        "price_range": (350, 1800),
        "duration_range": (360, 720),
        "carriers": ["EK", "QR", "EY", "TK"],
    },
    "asia_internal": {
        "price_range": (80, 500),
        "duration_range": (90, 360),
        "carriers": ["SQ", "CX", "JL", "NH", "KE", "OZ"],
    },
    "latin_america": {
        "price_range": (150, 800),
        "duration_range": (180, 600),
        "carriers": ["AA", "DL", "UA", "AM", "AV", "LA", "G3"],
    },
    "generic": {
        "price_range": (150, 1000),
        "duration_range": (120, 600),
        "carriers": list(AIRLINES.keys())[:20],
    },
}

# Fare families with price multipliers relative to basic economy
FARE_FAMILIES = [
    {
        "name": "Basic Economy",
        "code": "BASIC",
        "cabin": "ECONOMY",
        "multiplier": 1.0,
        "features": ["carry_on_only", "no_changes", "no_refund", "last_to_board"],
    },
    {
        "name": "Main Cabin",
        "code": "MAIN",
        "cabin": "ECONOMY",
        "multiplier": 1.3,
        "features": [
            "checked_bag_included",
            "seat_selection",
            "change_fee_applies",
            "partial_refund",
        ],
    },
    {
        "name": "Comfort+",
        "code": "COMFORT",
        "cabin": "PREMIUM_ECONOMY",
        "multiplier": 1.8,
        "features": [
            "extra_legroom",
            "priority_boarding",
            "checked_bag_included",
            "free_changes",
            "refundable",
        ],
    },
    {
        "name": "Business",
        "code": "BUSINESS",
        "cabin": "BUSINESS",
        "multiplier": 3.5,
        "features": [
            "lie_flat_seat",
            "lounge_access",
            "priority_everything",
            "two_checked_bags",
            "fully_flexible",
            "fully_refundable",
        ],
    },
    {
        "name": "First",
        "code": "FIRST",
        "cabin": "FIRST",
        "multiplier": 6.0,
        "features": [
            "private_suite",
            "lounge_access",
            "chauffeur_service",
            "three_checked_bags",
            "fully_flexible",
            "fully_refundable",
            "onboard_shower",
        ],
    },
]

# Aircraft types weighted by route category
AIRCRAFT_TYPES = {
    "narrowbody": ["A320", "A321", "B737-800", "B737-MAX8", "A220-300", "E175"],
    "widebody": ["B777-300ER", "A350-900", "B787-9", "A330-300", "B777-200"],
    "ultra_long": ["A350-900ULR", "B777-200LR", "B787-9", "A380"],
}


def _seed_from_inputs(*args: str) -> int:
    """Create a deterministic seed from input strings."""
    combined = "|".join(str(a) for a in args)
    return int(hashlib.md5(combined.encode()).hexdigest()[:8], 16)


class MockDataProvider:
    """
    Generates realistic but simulated flight and booking data for sandbox
    environments.

    All outputs are deterministic: identical inputs always produce identical
    results (using seeded randomness). Every response is clearly marked as
    sandbox/test data to prevent confusion with live GDS data.

    Usage::

        provider = MockDataProvider()
        results = provider.search_flights("JFK", "LHR", "2026-04-15")
        booking = provider.get_mock_booking()
        seatmap = provider.get_mock_seatmap("AA100")
    """

    def __init__(self) -> None:
        """Initialize the mock data provider."""
        self._airlines = AIRLINES
        self._airports = AIRPORTS

    def _classify_route(self, origin: str, destination: str) -> str:
        """Classify a route to determine pricing and carrier selection."""
        origin_info = self._airports.get(origin, {})
        dest_info = self._airports.get(destination, {})
        o_country = origin_info.get("country", "")
        d_country = dest_info.get("country", "")

        if o_country == "US" and d_country == "US":
            return "domestic_us"

        us_codes = {"US"}
        eu_codes = {"GB", "FR", "DE", "NL", "ES", "IT", "CH", "AT", "PT", "SE",
                    "IE", "HU", "NO", "IS"}
        asia_codes = {"SG", "HK", "JP", "KR", "CN"}
        me_codes = {"AE", "QA", "TR"}
        latam_codes = {"MX", "BR", "CO", "CL"}

        if o_country in eu_codes and d_country in eu_codes:
            return "europe_internal"
        if (o_country in us_codes and d_country in eu_codes) or \
           (o_country in eu_codes and d_country in us_codes):
            return "transatlantic"
        if (o_country in us_codes and d_country in asia_codes) or \
           (o_country in asia_codes and d_country in us_codes):
            return "transpacific"
        if o_country in asia_codes and d_country in asia_codes:
            return "asia_internal"
        if d_country in me_codes or o_country in me_codes:
            return "middle_east"
        if d_country in latam_codes or o_country in latam_codes:
            return "latin_america"

        return "generic"

    def search_flights(
        self,
        origin: str,
        destination: str,
        date: str,
        **kwargs: Any,
    ) -> dict:
        """
        Generate realistic mock flight search results.

        Args:
            origin: Origin airport IATA code (e.g., ``"JFK"``).
            destination: Destination airport IATA code (e.g., ``"LHR"``).
            date: Departure date as ``"YYYY-MM-DD"`` string.
            **kwargs: Optional filters — ``cabin`` (str), ``max_results`` (int),
                      ``passengers`` (int), ``nonstop`` (bool).

        Returns:
            A dict containing:
            - ``sandbox``: Always ``True`` (marks data as simulated).
            - ``origin`` / ``destination``: Requested airport codes.
            - ``date``: Requested date.
            - ``results``: List of flight offer dicts (5-15 results).
            - ``result_count``: Number of results returned.
            - ``search_id``: Deterministic search identifier.
        """
        cabin_filter = kwargs.get("cabin", None)
        max_results = kwargs.get("max_results", None)
        passengers = kwargs.get("passengers", 1)
        nonstop_only = kwargs.get("nonstop", False)

        seed = _seed_from_inputs(origin, destination, date)
        rng = random.Random(seed)

        route_type = self._classify_route(origin, destination)
        route_config = ROUTE_TYPES.get(route_type, ROUTE_TYPES["generic"])
        price_min, price_max = route_config["price_range"]
        dur_min, dur_max = route_config["duration_range"]
        route_carriers = route_config["carriers"]

        num_results = rng.randint(5, 15)
        if max_results:
            num_results = min(num_results, max_results)

        origin_info = self._airports.get(origin, {"city": origin, "country": "XX"})
        dest_info = self._airports.get(destination, {"city": destination, "country": "XX"})

        try:
            dep_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            dep_date = datetime.now() + timedelta(days=30)

        results = []
        for i in range(num_results):
            carrier_code = rng.choice(route_carriers)
            carrier_info = self._airlines.get(
                carrier_code, {"name": f"Airline {carrier_code}", "country": "XX"}
            )

            # Flight number: carrier code + 3-4 digit number
            flight_num = f"{carrier_code}{rng.randint(100, 9999)}"

            # Departure time: spread across the day
            dep_hour = rng.randint(5, 23)
            dep_minute = rng.choice([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
            departure_time = dep_date.replace(hour=dep_hour, minute=dep_minute, second=0)

            # Duration with some randomness
            duration_minutes = rng.randint(dur_min, dur_max)
            arrival_time = departure_time + timedelta(minutes=duration_minutes)

            # Is this nonstop or connecting?
            is_nonstop = duration_minutes < 480 and rng.random() > 0.3
            if nonstop_only:
                is_nonstop = True

            # Number of stops
            stops = 0 if is_nonstop else rng.randint(1, 2)

            # Base price with some variation per result
            base_price = round(
                rng.uniform(price_min, price_max) * (0.85 + 0.3 * rng.random()), 2
            )

            # Stops add discount (connecting flights are cheaper)
            if stops > 0:
                base_price *= 0.75

            # Build fare options
            fares = []
            for fare in FARE_FAMILIES:
                if cabin_filter and fare["cabin"] != cabin_filter:
                    continue
                fare_price = round(base_price * fare["multiplier"], 2)
                fares.append({
                    "fare_id": f"SANDBOX-{flight_num}-{fare['code']}-{i}",
                    "name": fare["name"],
                    "code": fare["code"],
                    "cabin": fare["cabin"],
                    "price": {
                        "amount": fare_price,
                        "currency": "USD",
                        "per_passenger": fare_price,
                        "total": round(fare_price * passengers, 2),
                    },
                    "features": fare["features"],
                    "seats_remaining": rng.randint(1, 9),
                })

            if not fares:
                # If cabin filter excluded everything, include basic economy
                fares.append({
                    "fare_id": f"SANDBOX-{flight_num}-BASIC-{i}",
                    "name": "Basic Economy",
                    "code": "BASIC",
                    "cabin": "ECONOMY",
                    "price": {
                        "amount": base_price,
                        "currency": "USD",
                        "per_passenger": base_price,
                        "total": round(base_price * passengers, 2),
                    },
                    "features": FARE_FAMILIES[0]["features"],
                    "seats_remaining": rng.randint(1, 9),
                })

            # Aircraft selection
            if duration_minutes > 600:
                aircraft = rng.choice(AIRCRAFT_TYPES["ultra_long"])
            elif duration_minutes > 360:
                aircraft = rng.choice(AIRCRAFT_TYPES["widebody"])
            else:
                aircraft = rng.choice(AIRCRAFT_TYPES["narrowbody"])

            # Build segments
            segments = []
            if is_nonstop:
                segments.append({
                    "segment_number": 1,
                    "origin": origin,
                    "origin_city": origin_info["city"],
                    "destination": destination,
                    "destination_city": dest_info["city"],
                    "departure": departure_time.isoformat(),
                    "arrival": arrival_time.isoformat(),
                    "duration_minutes": duration_minutes,
                    "flight_number": flight_num,
                    "carrier": carrier_code,
                    "carrier_name": carrier_info["name"],
                    "aircraft": aircraft,
                    "cabin": fares[0]["cabin"],
                })
            else:
                # Build connecting segments through a hub
                hub_candidates = [
                    c for c in ["ORD", "ATL", "DFW", "FRA", "LHR", "DXB", "IST", "DOH"]
                    if c != origin and c != destination
                ]
                hub = rng.choice(hub_candidates)
                hub_info = self._airports.get(hub, {"city": hub, "country": "XX"})

                leg1_duration = rng.randint(
                    int(duration_minutes * 0.3), int(duration_minutes * 0.5)
                )
                layover = rng.randint(60, 180)
                leg2_duration = duration_minutes - leg1_duration - layover

                mid_arrival = departure_time + timedelta(minutes=leg1_duration)
                leg2_departure = mid_arrival + timedelta(minutes=layover)
                final_arrival = leg2_departure + timedelta(minutes=max(leg2_duration, 60))

                segments.append({
                    "segment_number": 1,
                    "origin": origin,
                    "origin_city": origin_info["city"],
                    "destination": hub,
                    "destination_city": hub_info["city"],
                    "departure": departure_time.isoformat(),
                    "arrival": mid_arrival.isoformat(),
                    "duration_minutes": leg1_duration,
                    "flight_number": flight_num,
                    "carrier": carrier_code,
                    "carrier_name": carrier_info["name"],
                    "aircraft": rng.choice(AIRCRAFT_TYPES["narrowbody"]),
                    "cabin": fares[0]["cabin"],
                })

                leg2_flight = f"{carrier_code}{rng.randint(100, 9999)}"
                segments.append({
                    "segment_number": 2,
                    "origin": hub,
                    "origin_city": hub_info["city"],
                    "destination": destination,
                    "destination_city": dest_info["city"],
                    "departure": leg2_departure.isoformat(),
                    "arrival": final_arrival.isoformat(),
                    "duration_minutes": max(leg2_duration, 60),
                    "flight_number": leg2_flight,
                    "carrier": carrier_code,
                    "carrier_name": carrier_info["name"],
                    "aircraft": aircraft,
                    "cabin": fares[0]["cabin"],
                })

            results.append({
                "sandbox": True,
                "offer_id": f"SANDBOX-OFFER-{seed}-{i}",
                "carrier": carrier_code,
                "carrier_name": carrier_info["name"],
                "flight_number": flight_num,
                "origin": origin,
                "origin_city": origin_info["city"],
                "destination": destination,
                "destination_city": dest_info["city"],
                "departure": departure_time.isoformat(),
                "arrival": arrival_time.isoformat() if is_nonstop else segments[-1]["arrival"],
                "duration_minutes": duration_minutes,
                "stops": stops,
                "nonstop": is_nonstop,
                "aircraft": aircraft,
                "segments": segments,
                "fares": fares,
                "lowest_price": {
                    "amount": fares[0]["price"]["amount"],
                    "currency": "USD",
                },
            })

        # Sort by lowest price
        results.sort(key=lambda r: r["lowest_price"]["amount"])

        search_id = f"SANDBOX-SEARCH-{seed}"

        return {
            "sandbox": True,
            "disclaimer": "SANDBOX DATA — simulated results for testing only.",
            "origin": origin,
            "origin_city": origin_info.get("city", origin),
            "destination": destination,
            "destination_city": dest_info.get("city", destination),
            "date": date,
            "passengers": passengers,
            "results": results,
            "result_count": len(results),
            "search_id": search_id,
        }

    def get_mock_booking(self, pnr: Optional[str] = None) -> dict:
        """
        Generate a realistic mock booking record.

        Args:
            pnr: Optional PNR to use. If not provided, one is generated.

        Returns:
            A dict representing a complete booking with PNR, passenger
            details, segments, pricing, ticketing info, and status.
        """
        if not pnr:
            pnr = self.generate_pnr()

        seed = _seed_from_inputs(pnr)
        rng = random.Random(seed)

        carrier_code = rng.choice(list(self._airlines.keys()))
        carrier_info = self._airlines[carrier_code]

        # Pick origin/destination
        airport_codes = list(self._airports.keys())
        origin = rng.choice(airport_codes)
        destination = rng.choice([c for c in airport_codes if c != origin])
        origin_info = self._airports[origin]
        dest_info = self._airports[destination]

        # Dates
        dep_date = datetime.now() + timedelta(days=rng.randint(7, 90))
        dep_hour = rng.randint(6, 22)
        dep_minute = rng.choice([0, 15, 30, 45])
        departure = dep_date.replace(hour=dep_hour, minute=dep_minute, second=0, microsecond=0)

        route_type = self._classify_route(origin, destination)
        route_config = ROUTE_TYPES.get(route_type, ROUTE_TYPES["generic"])
        dur_min, dur_max = route_config["duration_range"]
        duration = rng.randint(dur_min, dur_max)
        arrival = departure + timedelta(minutes=duration)

        flight_num = f"{carrier_code}{rng.randint(100, 9999)}"
        ticket_number = self.generate_ticket_number(rng=rng)
        base_price = round(
            rng.uniform(*route_config["price_range"]), 2
        )
        taxes = round(base_price * rng.uniform(0.08, 0.18), 2)
        total = round(base_price + taxes, 2)

        fare = rng.choice(FARE_FAMILIES[:3])  # Basic, Main, or Comfort+

        booking_status = rng.choice(["CONFIRMED", "CONFIRMED", "CONFIRMED", "TICKETED"])
        created_at = datetime.now() - timedelta(days=rng.randint(1, 30))

        # Passenger
        first_names = [
            "James", "Maria", "John", "Sarah", "David", "Emma",
            "Robert", "Olivia", "William", "Sophia",
        ]
        last_names = [
            "Smith", "Johnson", "Williams", "Brown", "Jones",
            "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
        ]

        return {
            "sandbox": True,
            "disclaimer": "SANDBOX DATA — simulated booking for testing only.",
            "pnr": pnr,
            "status": booking_status,
            "created_at": created_at.isoformat(),
            "passenger": {
                "first_name": rng.choice(first_names),
                "last_name": rng.choice(last_names),
                "type": "ADT",
                "title": rng.choice(["MR", "MS"]),
            },
            "contact": {
                "email": "sandbox.test@example.com",
                "phone": "+1-555-0100",
            },
            "segments": [
                {
                    "segment_number": 1,
                    "origin": origin,
                    "origin_city": origin_info["city"],
                    "destination": destination,
                    "destination_city": dest_info["city"],
                    "departure": departure.isoformat(),
                    "arrival": arrival.isoformat(),
                    "duration_minutes": duration,
                    "flight_number": flight_num,
                    "carrier": carrier_code,
                    "carrier_name": carrier_info["name"],
                    "aircraft": rng.choice(
                        AIRCRAFT_TYPES["widebody"] if duration > 360
                        else AIRCRAFT_TYPES["narrowbody"]
                    ),
                    "cabin": fare["cabin"],
                    "booking_class": rng.choice(["Y", "B", "M", "H", "K", "L"]),
                    "status": "HK",
                }
            ],
            "pricing": {
                "currency": "USD",
                "base_fare": base_price,
                "taxes_and_fees": taxes,
                "total": total,
                "fare_family": fare["name"],
                "fare_code": fare["code"],
                "fare_basis": f"{rng.choice(['Y', 'B', 'M', 'H'])}{rng.choice(['A', 'E', 'O', 'W'])}",
            },
            "ticketing": {
                "ticket_number": ticket_number,
                "ticket_status": "ISSUED" if booking_status == "TICKETED" else "PENDING",
                "time_limit": (departure - timedelta(days=3)).isoformat(),
                "issuing_carrier": carrier_code,
            },
        }

    def get_mock_seatmap(self, flight_number: Optional[str] = None) -> dict:
        """
        Generate a mock seatmap for a flight.

        Args:
            flight_number: Optional flight number. If not provided, one is
                           generated.

        Returns:
            A dict with cabin layout, rows, and seat availability.
        """
        if not flight_number:
            carrier = random.choice(list(self._airlines.keys()))
            flight_number = f"{carrier}{random.randint(100, 9999)}"

        seed = _seed_from_inputs(flight_number)
        rng = random.Random(seed)

        aircraft = rng.choice(AIRCRAFT_TYPES["narrowbody"] + AIRCRAFT_TYPES["widebody"])

        # Determine if widebody (2 aisles) or narrowbody (1 aisle)
        is_widebody = aircraft in AIRCRAFT_TYPES["widebody"]

        if is_widebody:
            economy_layout = "ABC-DEFG-HJK"
            seat_letters = ["A", "B", "C", "D", "E", "F", "G", "H", "J", "K"]
            total_rows = rng.randint(35, 55)
            business_rows = rng.randint(6, 10)
        else:
            economy_layout = "ABC-DEF"
            seat_letters = ["A", "B", "C", "D", "E", "F"]
            total_rows = rng.randint(25, 38)
            business_rows = rng.randint(3, 5)

        rows = []
        for row_num in range(1, total_rows + 1):
            cabin = "BUSINESS" if row_num <= business_rows else "ECONOMY"
            row_letters = seat_letters[:4] if cabin == "BUSINESS" and is_widebody else seat_letters

            seats = []
            for letter in row_letters:
                is_available = rng.random() > 0.35
                is_exit_row = row_num in [business_rows + 1, total_rows - 5]
                is_window = letter in ["A", seat_letters[-1]]
                is_aisle = letter in (["C", "D", "G", "H"] if is_widebody else ["C", "D"])

                seat = {
                    "seat": f"{row_num}{letter}",
                    "available": is_available,
                    "cabin": cabin,
                    "characteristics": [],
                }

                if is_window:
                    seat["characteristics"].append("WINDOW")
                if is_aisle:
                    seat["characteristics"].append("AISLE")
                if is_exit_row:
                    seat["characteristics"].append("EXIT_ROW")
                    seat["characteristics"].append("EXTRA_LEGROOM")
                if not is_available:
                    seat["characteristics"].append("OCCUPIED")
                if cabin == "BUSINESS":
                    seat["characteristics"].append("LIE_FLAT")

                # Price for seat selection
                if is_available:
                    if cabin == "BUSINESS":
                        seat["price"] = {"amount": 0, "currency": "USD"}
                    elif is_exit_row:
                        seat["price"] = {"amount": rng.choice([35, 45, 55]), "currency": "USD"}
                    elif is_window or is_aisle:
                        seat["price"] = {"amount": rng.choice([10, 15, 20]), "currency": "USD"}
                    else:
                        seat["price"] = {"amount": rng.choice([0, 5, 10]), "currency": "USD"}

                seats.append(seat)

            rows.append({
                "row_number": row_num,
                "cabin": cabin,
                "seats": seats,
            })

        return {
            "sandbox": True,
            "disclaimer": "SANDBOX DATA — simulated seatmap for testing only.",
            "flight_number": flight_number,
            "aircraft": aircraft,
            "layout": economy_layout,
            "cabins": [
                {
                    "cabin": "BUSINESS",
                    "rows": f"1-{business_rows}",
                    "layout": "AC-DF" if not is_widebody else "AC-DEFG-HK",
                },
                {
                    "cabin": "ECONOMY",
                    "rows": f"{business_rows + 1}-{total_rows}",
                    "layout": economy_layout,
                },
            ],
            "rows": rows,
            "total_seats": sum(len(r["seats"]) for r in rows),
            "available_seats": sum(
                1 for r in rows for s in r["seats"] if s["available"]
            ),
        }

    def get_mock_fare_rules(self, fare_id: Optional[str] = None) -> dict:
        """
        Generate realistic fare rule text for a fare.

        Args:
            fare_id: Optional fare identifier. If not provided, a generic
                     set of rules is returned.

        Returns:
            A dict containing structured fare rules covering cancellation,
            changes, baggage, and general conditions.
        """
        if not fare_id:
            fare_id = f"SANDBOX-FARE-{random.randint(10000, 99999)}"

        seed = _seed_from_inputs(fare_id)
        rng = random.Random(seed)

        fare_family = rng.choice(FARE_FAMILIES)
        is_refundable = "fully_refundable" in fare_family["features"]
        is_changeable = "free_changes" in fare_family["features"]
        change_fee = 0 if is_changeable else rng.choice([75, 100, 150, 200])
        cancel_fee = 0 if is_refundable else rng.choice([150, 200, 250, 300])

        return {
            "sandbox": True,
            "disclaimer": "SANDBOX DATA — simulated fare rules for testing only.",
            "fare_id": fare_id,
            "fare_family": fare_family["name"],
            "fare_code": fare_family["code"],
            "cabin": fare_family["cabin"],
            "rules": {
                "cancellation": {
                    "refundable": is_refundable,
                    "penalty": {
                        "amount": cancel_fee,
                        "currency": "USD",
                    },
                    "text": (
                        "Fully refundable. Cancel any time before departure for a "
                        "full refund to original form of payment."
                        if is_refundable
                        else f"Non-refundable. Cancellation penalty of USD {cancel_fee} "
                        f"applies. Residual value issued as travel credit valid for "
                        f"12 months from date of issue."
                    ),
                    "deadline": "Before scheduled departure",
                },
                "changes": {
                    "changeable": True,
                    "fee": {
                        "amount": change_fee,
                        "currency": "USD",
                    },
                    "text": (
                        "Free changes permitted. Fare difference may apply for "
                        "rebooking to a higher fare class."
                        if is_changeable
                        else f"Changes permitted with a fee of USD {change_fee} per "
                        f"passenger per direction, plus any fare difference. "
                        f"Changes must be made before scheduled departure."
                    ),
                },
                "baggage": {
                    "carry_on": {
                        "included": True,
                        "pieces": 1,
                        "max_weight_kg": 10,
                        "text": "One personal item and one carry-on bag included.",
                    },
                    "checked": {
                        "included": "checked_bag_included" in fare_family["features"],
                        "pieces": (
                            2 if "two_checked_bags" in fare_family["features"]
                            else 1 if "checked_bag_included" in fare_family["features"]
                            else 0
                        ),
                        "max_weight_kg": 23,
                        "first_bag_fee": (
                            0 if "checked_bag_included" in fare_family["features"]
                            else rng.choice([30, 35, 40])
                        ),
                        "second_bag_fee": (
                            0 if "two_checked_bags" in fare_family["features"]
                            else rng.choice([40, 45, 50])
                        ),
                    },
                },
                "seat_selection": {
                    "included": "seat_selection" in fare_family["features"],
                    "text": (
                        "Advance seat selection included at time of booking."
                        if "seat_selection" in fare_family["features"]
                        else "Seat assigned at check-in. Advance selection available "
                        "for a fee."
                    ),
                },
                "general": {
                    "advance_purchase": f"{rng.choice([3, 7, 14, 21])} days",
                    "minimum_stay": rng.choice(["None", "Saturday night", "3 days"]),
                    "maximum_stay": rng.choice(["12 months", "6 months", "None"]),
                    "combinability": "May be combined with other published fares.",
                    "blackout_dates": "Standard blackout dates may apply.",
                },
            },
        }

    def generate_pnr(self) -> str:
        """
        Generate a realistic 6-character PNR (Passenger Name Record).

        PNRs use uppercase letters and digits, following standard GDS format.
        The first character is always a letter.

        Returns:
            A 6-character alphanumeric PNR string.
        """
        chars = string.ascii_uppercase + string.digits
        # PNR always starts with a letter
        first = random.choice(string.ascii_uppercase)
        rest = "".join(random.choice(chars) for _ in range(5))
        return first + rest

    def generate_ticket_number(self, rng: Optional[random.Random] = None) -> str:
        """
        Generate a realistic 13-digit e-ticket number.

        Format: 3-digit airline numeric code + 10-digit serial.
        Common airline codes: 001 (AA), 006 (DL), 016 (UA), 125 (BA), etc.

        Args:
            rng: Optional seeded Random instance for deterministic output.

        Returns:
            A 13-digit ticket number string.
        """
        if rng is None:
            rng = random.Random()

        airline_codes = ["001", "006", "016", "125", "220", "057", "074", "176", "014"]
        prefix = rng.choice(airline_codes)
        serial = "".join(str(rng.randint(0, 9)) for _ in range(10))
        return prefix + serial
