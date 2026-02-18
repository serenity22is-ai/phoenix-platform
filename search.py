"""
MYSTES Global Search Engine

Features:
- Smart market/proxy auto-selection based on route
- Search from anywhere to anywhere globally
- Multi-flight itinerary builder
- Optimal market detection for any origin/destination pair
"""

import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import hashlib

# Import from main module
from main import (
    compare_markets,
    calculate_deal,
    get_xrp_price,
    fetch_live_currency_rates,
    CURRENCY_RATES_TO_USD,
    PLATFORM_FEE_CONFIG,
    MIN_USER_SAVINGS_USD,
    search_hybrid,
    DIRECT_SCRAPER_AVAILABLE,
    search_amadeus_with_proxy_prices,
    AMADEUS_AVAILABLE,
    AMADEUS_CONFIGURED,
)


# --- AIRPORT TO COUNTRY/MARKET MAPPING ---

# Major airports and their country codes
AIRPORT_COUNTRY_MAP = {
    # North America
    "LAX": "US", "JFK": "US", "SFO": "US", "ORD": "US", "MIA": "US",
    "DFW": "US", "SEA": "US", "BOS": "US", "ATL": "US", "DEN": "US",
    "LAS": "US", "PHX": "US", "IAH": "US", "EWR": "US", "MCO": "US",
    "YYZ": "CA", "YVR": "CA", "YUL": "CA", "YYC": "CA",
    "MEX": "MX", "CUN": "MX", "GDL": "MX",

    # Europe
    "LHR": "UK", "LGW": "UK", "MAN": "UK", "EDI": "UK",
    "CDG": "FR", "ORY": "FR", "NCE": "FR", "LYS": "FR",
    "FRA": "DE", "MUC": "DE", "TXL": "DE", "DUS": "DE", "HAM": "DE",
    "FCO": "IT", "MXP": "IT", "VCE": "IT", "NAP": "IT",
    "MAD": "ES", "BCN": "ES", "AGP": "ES", "PMI": "ES",
    "AMS": "NL", "BRU": "BE", "ZRH": "CH", "VIE": "AT",
    "LIS": "PT", "DUB": "IE", "CPH": "DK", "OSL": "NO",
    "ARN": "SE", "HEL": "FI", "WAW": "PL", "PRG": "CZ",
    "BUD": "HU", "ATH": "GR", "IST": "TR",

    # Asia Pacific
    "HND": "JP", "NRT": "JP", "KIX": "JP", "NGO": "JP", "FUK": "JP",
    "ICN": "KR", "GMP": "KR", "PUS": "KR",
    "PEK": "CN", "PVG": "CN", "CAN": "CN", "SZX": "CN", "CTU": "CN",
    "HKG": "HK", "TPE": "TW", "KHH": "TW",
    "SIN": "SG", "BKK": "TH", "DMK": "TH", "HKT": "TH",
    "KUL": "MY", "CGK": "ID", "DPS": "ID",
    "MNL": "PH", "SGN": "VN", "HAN": "VN",
    "DEL": "IN", "BOM": "IN", "BLR": "IN", "MAA": "IN", "CCU": "IN",
    "SYD": "AU", "MEL": "AU", "BNE": "AU", "PER": "AU",
    "AKL": "NZ", "CHC": "NZ", "WLG": "NZ",

    # Middle East
    "DXB": "AE", "AUH": "AE", "DOH": "QA", "RUH": "SA", "JED": "SA",
    "TLV": "IL", "AMM": "JO", "CAI": "EG",

    # South America
    "GRU": "BR", "GIG": "BR", "BSB": "BR",
    "EZE": "AR", "AEP": "AR", "SCL": "CL",
    "BOG": "CO", "LIM": "PE", "UIO": "EC",

    # Africa
    "JNB": "ZA", "CPT": "ZA", "NBO": "KE", "ADD": "ET",
    "CMN": "MA", "CAI": "EG", "LOS": "NG",
}

# Country code to market configuration
COUNTRY_TO_MARKET = {
    # North America
    "US": {"label": "US", "currency": "USD", "gl": "us", "hl": "en"},
    "CA": {"label": "CA", "currency": "CAD", "gl": "ca", "hl": "en"},
    "MX": {"label": "MX", "currency": "MXN", "gl": "mx", "hl": "es"},

    # Europe
    "UK": {"label": "UK", "currency": "GBP", "gl": "uk", "hl": "en"},
    "GB": {"label": "UK", "currency": "GBP", "gl": "uk", "hl": "en"},
    "FR": {"label": "FR", "currency": "EUR", "gl": "fr", "hl": "fr"},
    "DE": {"label": "DE", "currency": "EUR", "gl": "de", "hl": "de"},
    "IT": {"label": "IT", "currency": "EUR", "gl": "it", "hl": "it"},
    "ES": {"label": "ES", "currency": "EUR", "gl": "es", "hl": "es"},
    "NL": {"label": "NL", "currency": "EUR", "gl": "nl", "hl": "nl"},
    "BE": {"label": "BE", "currency": "EUR", "gl": "be", "hl": "nl"},
    "CH": {"label": "CH", "currency": "CHF", "gl": "ch", "hl": "de"},
    "AT": {"label": "AT", "currency": "EUR", "gl": "at", "hl": "de"},
    "PT": {"label": "PT", "currency": "EUR", "gl": "pt", "hl": "pt"},
    "IE": {"label": "IE", "currency": "EUR", "gl": "ie", "hl": "en"},
    "DK": {"label": "DK", "currency": "DKK", "gl": "dk", "hl": "da"},
    "NO": {"label": "NO", "currency": "NOK", "gl": "no", "hl": "no"},
    "SE": {"label": "SE", "currency": "SEK", "gl": "se", "hl": "sv"},
    "FI": {"label": "FI", "currency": "EUR", "gl": "fi", "hl": "fi"},
    "PL": {"label": "PL", "currency": "PLN", "gl": "pl", "hl": "pl"},
    "CZ": {"label": "CZ", "currency": "CZK", "gl": "cz", "hl": "cs"},
    "HU": {"label": "HU", "currency": "HUF", "gl": "hu", "hl": "hu"},
    "GR": {"label": "GR", "currency": "EUR", "gl": "gr", "hl": "el"},
    "TR": {"label": "TR", "currency": "TRY", "gl": "tr", "hl": "tr"},

    # Asia Pacific
    "JP": {"label": "JP", "currency": "JPY", "gl": "jp", "hl": "ja"},
    "KR": {"label": "KR", "currency": "KRW", "gl": "kr", "hl": "ko"},
    "CN": {"label": "CN", "currency": "CNY", "gl": "cn", "hl": "zh-CN"},
    "HK": {"label": "HK", "currency": "HKD", "gl": "hk", "hl": "zh-HK"},
    "TW": {"label": "TW", "currency": "TWD", "gl": "tw", "hl": "zh-TW"},
    "SG": {"label": "SG", "currency": "SGD", "gl": "sg", "hl": "en"},
    "TH": {"label": "TH", "currency": "THB", "gl": "th", "hl": "th"},
    "MY": {"label": "MY", "currency": "MYR", "gl": "my", "hl": "ms"},
    "ID": {"label": "ID", "currency": "IDR", "gl": "id", "hl": "id"},
    "PH": {"label": "PH", "currency": "PHP", "gl": "ph", "hl": "en"},
    "VN": {"label": "VN", "currency": "VND", "gl": "vn", "hl": "vi"},
    "IN": {"label": "IN", "currency": "INR", "gl": "in", "hl": "en"},
    "AU": {"label": "AU", "currency": "AUD", "gl": "au", "hl": "en"},
    "NZ": {"label": "NZ", "currency": "NZD", "gl": "nz", "hl": "en"},

    # Middle East
    "AE": {"label": "AE", "currency": "AED", "gl": "ae", "hl": "en"},
    "QA": {"label": "QA", "currency": "QAR", "gl": "qa", "hl": "en"},
    "SA": {"label": "SA", "currency": "SAR", "gl": "sa", "hl": "ar"},
    "IL": {"label": "IL", "currency": "ILS", "gl": "il", "hl": "he"},
    "EG": {"label": "EG", "currency": "EGP", "gl": "eg", "hl": "ar"},

    # South America
    "BR": {"label": "BR", "currency": "BRL", "gl": "br", "hl": "pt"},
    "AR": {"label": "AR", "currency": "ARS", "gl": "ar", "hl": "es"},
    "CL": {"label": "CL", "currency": "CLP", "gl": "cl", "hl": "es"},
    "CO": {"label": "CO", "currency": "COP", "gl": "co", "hl": "es"},
    "PE": {"label": "PE", "currency": "PEN", "gl": "pe", "hl": "es"},

    # Africa
    "ZA": {"label": "ZA", "currency": "ZAR", "gl": "za", "hl": "en"},
    "KE": {"label": "KE", "currency": "KES", "gl": "ke", "hl": "en"},
    "NG": {"label": "NG", "currency": "NGN", "gl": "ng", "hl": "en"},
    "MA": {"label": "MA", "currency": "MAD", "gl": "ma", "hl": "fr"},
}

# High-value arbitrage markets (always check these)
# Expanded to include more markets for better price comparison
GLOBAL_PRIORITY_MARKETS = [
    "US", "UK", "DE", "FR", "ES", "IT", "NL",  # NA + EU
    "JP", "KR", "AU", "SG", "IN", "HK",         # APAC
    "CA", "MX", "BR"                             # Americas
]


def get_country_from_airport(airport_code: str) -> Optional[str]:
    """Get country code from airport code."""
    return AIRPORT_COUNTRY_MAP.get(airport_code.upper())


def get_market_config(country_code: str) -> Optional[Dict]:
    """Get market configuration for a country."""
    return COUNTRY_TO_MARKET.get(country_code.upper())


# --- SMART MARKET SELECTION ---

def select_markets_for_route(origin: str, destination: str, include_global: bool = True) -> List[Dict]:
    """
    Intelligently select which markets to check for a given route.

    Strategy:
    1. Always check origin country market (where traveler is)
    2. Always check destination country market (local pricing)
    3. Add regional hub markets
    4. Add global priority markets for arbitrage

    Args:
        origin: Origin airport code
        destination: Destination airport code
        include_global: Whether to include global priority markets

    Returns:
        List of market configurations to check
    """
    markets = []
    seen_labels = set()

    # 1. Origin country market (primary - what user would normally see)
    origin_country = get_country_from_airport(origin)
    if origin_country:
        origin_market = get_market_config(origin_country)
        if origin_market and origin_market["label"] not in seen_labels:
            markets.append({**origin_market, "priority": "origin"})
            seen_labels.add(origin_market["label"])

    # 2. Destination country market (often has better local prices)
    dest_country = get_country_from_airport(destination)
    if dest_country:
        dest_market = get_market_config(dest_country)
        if dest_market and dest_market["label"] not in seen_labels:
            markets.append({**dest_market, "priority": "destination"})
            seen_labels.add(dest_market["label"])

    # 3. Regional markets based on route
    regional_markets = get_regional_markets(origin, destination)
    for country in regional_markets:
        market = get_market_config(country)
        if market and market["label"] not in seen_labels:
            markets.append({**market, "priority": "regional"})
            seen_labels.add(market["label"])

    # 4. Global priority markets for arbitrage opportunities
    # Always include core arbitrage markets (EU often has best prices)
    core_arbitrage_markets = ["UK", "DE", "FR", "ES"]
    for country in core_arbitrage_markets:
        market = get_market_config(country)
        if market and market["label"] not in seen_labels:
            markets.append({**market, "priority": "arbitrage"})
            seen_labels.add(market["label"])

    # Add remaining global markets if include_global is True
    if include_global:
        for country in GLOBAL_PRIORITY_MARKETS:
            market = get_market_config(country)
            if market and market["label"] not in seen_labels:
                markets.append({**market, "priority": "global"})
                seen_labels.add(market["label"])

    return markets


def get_regional_markets(origin: str, destination: str) -> List[str]:
    """
    Get relevant regional markets based on route geography.

    For Europe routes: add UK, DE, FR
    For Asia routes: add JP, SG, HK
    etc.
    """
    origin_country = get_country_from_airport(origin)
    dest_country = get_country_from_airport(destination)

    regions = set()

    # Determine regions
    europe = {"UK", "FR", "DE", "IT", "ES", "NL", "CH", "AT", "IE", "PT", "DK", "NO", "SE", "FI", "PL", "CZ", "HU", "GR", "TR"}
    asia = {"JP", "KR", "CN", "HK", "TW", "SG", "TH", "MY", "ID", "PH", "VN", "IN"}
    north_america = {"US", "CA", "MX"}
    south_america = {"BR", "AR", "CL", "CO", "PE"}
    middle_east = {"AE", "QA", "SA", "IL"}
    oceania = {"AU", "NZ"}

    # Add regional hubs based on origin/destination
    for country in [origin_country, dest_country]:
        if country in europe:
            regions.update(["UK", "DE", "FR"])
        elif country in asia:
            regions.update(["JP", "SG", "HK"])
        elif country in north_america:
            regions.update(["US", "CA"])
        elif country in south_america:
            regions.update(["BR"])
        elif country in middle_east:
            regions.update(["AE"])
        elif country in oceania:
            regions.update(["AU"])

    # Remove origin and destination (already added)
    regions.discard(origin_country)
    regions.discard(dest_country)

    return list(regions)


# --- GLOBAL FLIGHT SEARCH ---

def search_global(
    origin: str,
    destination: str,
    date: str,
    return_date: Optional[str] = None,
    cabin_class: str = "economy",
    fast_mode: bool = True,
    search_options: dict = None,
    use_direct_scraping: bool = True
) -> Dict:
    """
    Search for flights from anywhere to anywhere with smart market selection.

    Uses HYBRID search when direct scraping is available:
    - Proxy scraping for real regional prices (US, ES, PT)
    - SerpAPI for full flight details (airline, times, stops)
    - Both run in parallel, then merge results

    Args:
        origin: Origin airport code (e.g., "CDG" for Paris)
        destination: Destination airport code (e.g., "HND" for Tokyo)
        date: Outbound date (YYYY-MM-DD)
        return_date: Optional return date for round-trip
        fast_mode: If True, check fewer markets for speed
        search_options: Optional dict with passengers, cabin_class, stops
        use_direct_scraping: If True, use residential proxies for real pricing

    Returns:
        dict with flight comparisons, deals, and complete flight details
    """
    # Determine trip type
    is_round_trip = bool(return_date)
    trip_type_str = "ROUND-TRIP" if is_round_trip else "ONE-WAY"

    print(f"\n{'='*60}")
    print(f"GLOBAL SEARCH ({trip_type_str}): {origin} → {destination}")
    print(f"Outbound: {date}")
    if is_round_trip:
        print(f"Return: {return_date}")
    print(f"{'='*60}")

    # Use AMADEUS + PROXY search when both are available (best experience)
    # Falls back to PROXY-ONLY if Amadeus not configured
    hybrid_result = None
    cabin_class = search_options.get("cabin_class", "economy") if search_options else "economy"

    if use_direct_scraping and DIRECT_SCRAPER_AVAILABLE:
        try:
            # Prefer Amadeus + Proxy for rich flight details + price arbitrage
            if AMADEUS_AVAILABLE and AMADEUS_CONFIGURED:
                print(f"\n[AMADEUS + PROXY MODE] Best of both worlds:")
                print(f"  → Amadeus API → Full flight details (numbers, layovers, aircraft)")
                print(f"  → Proxies → Real regional prices (US, ES, UK)")

                hybrid_result = search_amadeus_with_proxy_prices(
                    origin=origin,
                    destination=destination,
                    date=date,
                    cabin_class=cabin_class,
                    return_date=return_date,
                    markets=["DE", "ES", "IT", "CA", "NL"]
                )

                if hybrid_result:
                    print(f"\n[AMADEUS + PROXY MODE] Search complete:")
                    print(f"  Flights with details: {len(hybrid_result.get('flights', []))}")
                    print(f"  Data sources: {', '.join(hybrid_result.get('data_sources', []))}")

            else:
                # Fallback: Proxy-only search (no Amadeus configured)
                # Note: Without Amadeus, we need US proxy for baseline
                print(f"\n[PROXY-ONLY MODE] Opening parallel browser windows...")
                print(f"  → US proxy → google.com (USD baseline)")
                print(f"  → DE proxy → google.de (EUR prices)")
                print(f"  → ES proxy → google.es (EUR prices)")
                print(f"  → IT proxy → google.it (EUR prices)")
                print(f"  → CA proxy → google.ca (CAD prices)")
                if not AMADEUS_CONFIGURED:
                    print(f"  (Tip: Add AMADEUS_API_KEY to .env for full flight details)")

                from main import search_proxy_only
                hybrid_result = search_proxy_only(
                    origin=origin,
                    destination=destination,
                    date=date,
                    cabin_class=cabin_class,
                    return_date=return_date,
                    markets=["US", "DE", "ES", "IT", "CA"]
                )

                if hybrid_result:
                    print(f"\n[PROXY-ONLY MODE] Search complete:")
                    flights_by_market = hybrid_result.get('proxy_flights_by_market', {})
                    total_flights = sum(m.get('flight_count', 0) for m in flights_by_market.values())
                    print(f"  Total flights scraped: {total_flights}")
                    print(f"  Markets: {', '.join(flights_by_market.keys())}")

        except Exception as e:
            print(f"[SEARCH MODE] Error: {e}")
            hybrid_result = None

    # Refresh XRP price only - use static currency rates for more stable arbitrage detection
    get_xrp_price()

    # If hybrid search succeeded, use those results
    if hybrid_result and (hybrid_result.get("flights") or hybrid_result.get("price_comparison")):
        # Build converted_prices dict from proxy price_comparison
        # Keep only the CHEAPEST price per market (scraper returns multiple prices per market)
        converted_prices = {}
        for price_entry in hybrid_result.get("price_comparison", []):
            market = price_entry.get("market", "")
            price_usd = price_entry.get("price_usd", 0)
            if market and price_usd:
                # Keep the cheapest price for each market
                if market not in converted_prices or price_usd < converted_prices[market]:
                    converted_prices[market] = round(price_usd, 2)

        # Calculate arbitrage from aggregated prices
        us_price = converted_prices.get("US", 0)
        if converted_prices:
            cheapest_market = min(converted_prices, key=converted_prices.get)
            cheapest_price = converted_prices[cheapest_market]
        else:
            cheapest_market = hybrid_result.get("cheapest_market", "US")
            cheapest_price = hybrid_result.get("cheapest_price_usd", 0)

        # Calculate savings vs US price
        if us_price and cheapest_price and us_price > cheapest_price:
            savings_vs_us = round(us_price - cheapest_price, 2)
            savings_pct = round((savings_vs_us / us_price) * 100, 1)
        else:
            savings_vs_us = 0
            savings_pct = 0

        print(f"\n[PRICE COMPARISON] Cheapest per market:")
        for m, p in sorted(converted_prices.items(), key=lambda x: x[1]):
            marker = " ← CHEAPEST" if m == cheapest_market else ""
            print(f"    {m}: ${p:.2f}{marker}")
        if savings_vs_us > 0:
            print(f"  ARBITRAGE: ${savings_vs_us:.2f} savings ({savings_pct:.1f}%) via {cheapest_market}")

        # Format flights for frontend display
        # PROXY-ONLY APPROACH: Use US proxy flights as base, match to ES/PT for real prices
        formatted_flights = []

        # Get raw proxy flight data per market
        proxy_flights_by_market = hybrid_result.get("proxy_flights_by_market", {})

        # Import currency rates for conversion
        from main import CURRENCY_RATES_TO_USD

        def normalize_time(time_str):
            """Normalize time string for comparison. Handles:
               - '8:30 AM' / '8:30 PM' (12-hour format)
               - '20:30' (24-hour format)
               - '2026-03-15 20:30' (date + time from SerpAPI)
            Returns: '20:30' format (HH:MM)
            """
            if not time_str:
                return None
            time_str = str(time_str).strip()

            # If it has a date prefix like "2026-03-15 20:30", extract just the time
            if " " in time_str and "-" in time_str.split(" ")[0]:
                parts = time_str.split(" ")
                time_str = parts[-1] if len(parts) > 1 else time_str

            time_str = time_str.upper().replace(" ", "")

            # Handle 12-hour format (AM/PM)
            if "AM" in time_str or "PM" in time_str:
                try:
                    is_pm = "PM" in time_str
                    time_str = time_str.replace("AM", "").replace("PM", "")
                    parts = time_str.split(":")
                    hour = int(parts[0])
                    minute = int(parts[1]) if len(parts) > 1 else 0
                    if is_pm and hour != 12:
                        hour += 12
                    elif not is_pm and hour == 12:
                        hour = 0
                    return f"{hour:02d}:{minute:02d}"
                except:
                    return time_str

            # Already in 24-hour format like "20:30"
            if ":" in time_str:
                try:
                    parts = time_str.split(":")
                    hour = int(parts[0])
                    minute = int(parts[1]) if len(parts) > 1 else 0
                    return f"{hour:02d}:{minute:02d}"
                except:
                    pass

            return time_str

        def normalize_airline(airline_str):
            """Normalize airline name for matching"""
            if not airline_str:
                return ""
            name = airline_str.lower().strip()
            name = name.replace("airlines", "").replace("airline", "").replace("airways", "")
            name = name.replace("air ", " ").replace(" air", " ")
            return name.strip()

        def find_matching_flight(base_flight, target_flights, target_currency):
            """
            Find a flight in target_flights that matches base_flight.

            Strategy 1 (high confidence): Match by airline + departure time.
            Strategy 2 (fallback): Match by sorted index when no time data
            is available (common when DOM extraction fails and only prices
            are scraped). Flights are sorted by price in both markets, so
            index N in US should correspond to index N in ES.

            Returns the matching flight's price in USD, or None if no match.
            """
            base_airline = normalize_airline(base_flight.get("airline", ""))
            base_dep_time = normalize_time(base_flight.get("departure_time", ""))
            base_index = base_flight.get("index")

            rate = CURRENCY_RATES_TO_USD.get(target_currency, 1.0)

            # Strategy 1: Match by time + airline (high confidence)
            if base_dep_time:
                best_match = None
                best_score = 0

                for tf in target_flights:
                    target_airline = normalize_airline(tf.get("airline", ""))
                    target_dep_time = normalize_time(tf.get("departure_time", ""))

                    score = 0

                    # Time match (most important)
                    if target_dep_time and base_dep_time:
                        if target_dep_time == base_dep_time:
                            score += 10  # Exact time match
                        else:
                            try:
                                base_h, base_m = map(int, base_dep_time.split(":"))
                                target_h, target_m = map(int, target_dep_time.split(":"))
                                base_mins = base_h * 60 + base_m
                                target_mins = target_h * 60 + target_m
                                diff = abs(base_mins - target_mins)
                                if diff <= 15:
                                    score += 8  # Very close time match
                                elif diff <= 30:
                                    score += 5  # Close time match
                            except:
                                pass

                    # Airline match
                    if target_airline and base_airline:
                        if target_airline == base_airline:
                            score += 5  # Exact airline match
                        elif target_airline in base_airline or base_airline in target_airline:
                            score += 3  # Partial airline match

                    if score > best_score:
                        best_score = score
                        best_match = tf

                if best_match and best_score >= 8:
                    local_price = best_match.get("price", 0)
                    price_usd = round(local_price * rate, 2)
                    return {
                        "price_usd": price_usd,
                        "local_price": local_price,
                        "currency": target_currency,
                        "matched_airline": best_match.get("airline"),
                        "matched_time": best_match.get("departure_time"),
                        "match_score": best_score
                    }

            # Strategy 2: Index-based matching (when no time data available)
            # Both markets show the same Google Flights results sorted by
            # "Best" or price, so flight at index 0 in US ≈ index 0 in ES.
            if base_index is not None and not base_dep_time:
                # Sort target flights by price to align with base sort order
                sorted_targets = sorted(target_flights, key=lambda x: x.get("price", 9999))
                if base_index < len(sorted_targets):
                    tf = sorted_targets[base_index]
                    local_price = tf.get("price", 0)
                    price_usd = round(local_price * rate, 2)
                    return {
                        "price_usd": price_usd,
                        "local_price": local_price,
                        "currency": target_currency,
                        "matched_airline": tf.get("airline"),
                        "matched_time": tf.get("departure_time"),
                        "match_score": 3  # Lower confidence
                    }

            return None

        # Check if we have Amadeus-enriched flights (best data)
        amadeus_flights = hybrid_result.get("flights", [])
        has_amadeus_data = amadeus_flights and any(f.get("flight_number") for f in amadeus_flights)

        if has_amadeus_data:
            # AMADEUS MODE: Use pre-merged flights with full details + proxy prices
            print(f"\n[AMADEUS + PROXY] Using {len(amadeus_flights)} flights with full details...")
            base_flights = []
            for af in amadeus_flights:
                # Extract prices_by_market for converted_prices
                prices_by_market = af.get("prices_by_market", {})
                flight_converted_prices = {m: p.get("price_usd", 0) for m, p in prices_by_market.items()}

                # Amadeus USD price is the baseline when no proxy data
                amadeus_usd = af.get("amadeus_price") or af.get("us_price_usd") or 0
                us_price = af.get("us_price_usd") or flight_converted_prices.get("US", 0) or amadeus_usd

                base_flights.append({
                    "airline": af.get("airline", "Various"),
                    "flight_number": af.get("flight_number"),
                    "departure_time": af.get("departure_time"),
                    "arrival_time": af.get("arrival_time"),
                    "duration": af.get("duration"),
                    "stops": af.get("stops", 0),
                    "us_price": us_price,
                    "amadeus_price": amadeus_usd,
                    "layovers": af.get("layovers", []),
                    "segments": af.get("segments", []),
                    "legs": af.get("segments", []),  # Alias for compatibility
                    "aircraft": af.get("aircraft"),
                    "cabin_class": af.get("cabin_class"),
                    "baggage_info": af.get("baggage_info"),
                    "is_codeshare": af.get("is_codeshare", False),
                    "operating_carrier": af.get("operating_carrier"),
                    "return_flight": af.get("return_flight"),
                    "is_round_trip": af.get("is_round_trip", bool(return_date)),
                    # Pre-computed prices from Amadeus search
                    "converted_prices": flight_converted_prices,
                    "cheapest_market": "Mystes",  # Never expose proxy market codes to frontend
                    "cheapest_price": af.get("cheapest_price_usd"),
                    # Raw Amadeus offer for booking
                    "raw_offer": af.get("raw_offer"),
                })

        else:
            # PROXY-ONLY: Use US proxy flights as BASE for flight identification
            # Each proxy captures: airline, departure_time, arrival_time, stops, duration, price
            # We match each US flight to ES/PT flights by airline + departure time to compare prices
            base_flights = []

            if proxy_flights_by_market.get("US", {}).get("flights"):
                print(f"\n[PROXY-ONLY] Using US proxy flights as base for matching...")
                us_proxy_flights = proxy_flights_by_market["US"]["flights"]
                for pf in us_proxy_flights:
                    base_flights.append({
                        "airline": pf.get("airline", "Various"),
                        "departure_time": pf.get("departure_time"),
                        "arrival_time": pf.get("arrival_time"),
                        "duration": pf.get("duration"),
                        "stops": pf.get("stops"),
                        "us_price": pf.get("price", 0),
                        "flight_number": pf.get("flight_number"),
                        "index": pf.get("index", len(base_flights)),
                        "layovers": [],
                        "legs": [],
                    })
            else:
                # If no US flights, use whichever market has the most flights as base
                best_market = max(proxy_flights_by_market.keys(),
                                key=lambda m: len(proxy_flights_by_market[m].get("flights", [])),
                                default=None)
                if best_market:
                    print(f"\n[PROXY-ONLY] No US flights - using {best_market} proxy flights as base...")
                    for pf in proxy_flights_by_market[best_market]["flights"]:
                        base_flights.append({
                            "airline": pf.get("airline", "Various"),
                            "departure_time": pf.get("departure_time"),
                            "arrival_time": pf.get("arrival_time"),
                            "duration": pf.get("duration"),
                            "stops": pf.get("stops"),
                            "us_price": pf.get("price", 0),
                            "flight_number": pf.get("flight_number"),
                            "index": pf.get("index", len(base_flights)),
                            "layovers": [],
                            "legs": [],
                        })

        print(f"[FLIGHT MATCHING] Using {len(base_flights)} base flights" +
              (", prices pre-computed" if has_amadeus_data else ", matching across markets..."))

        for flight in base_flights:
            # For Amadeus mode, skip flights with no departure time (incomplete data)
            # For proxy-only mode, we keep flights even without departure times since
            # the scraper only extracts prices from the page text
            if has_amadeus_data and not flight.get("departure_time"):
                continue

            # Base flight gives us flight details + US price (from proxy scraping)
            us_proxy_price = flight.get("us_price", 0)

            # Check if prices are already computed (Amadeus mode)
            if has_amadeus_data and flight.get("converted_prices"):
                flight_converted_prices = flight.get("converted_prices", {})
                flight_cheapest_market = flight.get("cheapest_market") or "US"
                flight_cheapest_price = flight.get("cheapest_price") or us_proxy_price

                # Log pre-computed prices
                airline_name = (flight.get('airline') or 'Unknown')[:20]
                flight_num = flight.get('flight_number') or ''
                dep_time = flight.get('departure_time') or '?'
                price_strs = [f"{m}:${p:.0f}" for m, p in sorted(flight_converted_prices.items(), key=lambda x: x[1])]
                print(f"    {airline_name:15} {flight_num:8} @ {dep_time:16} → {', '.join(price_strs) or 'no prices'}")

            elif has_amadeus_data:
                # Amadeus mode but no proxy prices — use Amadeus USD price as baseline
                amadeus_price = us_proxy_price or flight.get("amadeus_price", 0)
                flight_converted_prices = {"US": amadeus_price} if amadeus_price else {}
                flight_cheapest_market = "US"
                flight_cheapest_price = amadeus_price

                airline_name = (flight.get('airline') or 'Unknown')[:20]
                flight_num = flight.get('flight_number') or ''
                dep_time = flight.get('departure_time') or '?'
                print(f"    {airline_name:15} {flight_num:8} @ {dep_time:16} → US:${amadeus_price:.0f} (Amadeus baseline)")

            else:
                # PROXY-ONLY: Match flight across markets to get prices
                flight_converted_prices = {}
                matched_markets = []

                for market, market_data in proxy_flights_by_market.items():
                    market_flights = market_data.get("flights", [])
                    market_currency = market_data.get("currency", "USD")

                    match = find_matching_flight(flight, market_flights, market_currency)
                    if match:
                        flight_converted_prices[market] = match["price_usd"]
                        matched_markets.append(f"{market}:${match['price_usd']:.0f}")

                # If no US proxy match, use SerpAPI US price as fallback
                if "US" not in flight_converted_prices and us_proxy_price:
                    flight_converted_prices["US"] = round(us_proxy_price, 2)
                    matched_markets.insert(0, f"US:${us_proxy_price:.0f}(base)")

                # Log the match
                airline_name = (flight.get('airline') or 'Unknown')[:20]
                dep_time = flight.get('departure_time') or '?'
                if matched_markets:
                    print(f"    {airline_name:20} @ {dep_time:8} → {', '.join(matched_markets)}")
                else:
                    print(f"    {airline_name:20} @ {dep_time:8} → (no matches in other markets)")
                    if us_proxy_price:
                        flight_converted_prices["US"] = round(us_proxy_price, 2)

                # Determine cheapest for this flight
                if flight_converted_prices:
                    flight_cheapest_market = min(flight_converted_prices, key=flight_converted_prices.get)
                    flight_cheapest_price = flight_converted_prices[flight_cheapest_market]
                else:
                    flight_cheapest_market = "US"
                    flight_cheapest_price = us_proxy_price or 0

            # Calculate deal for this flight
            # US = Amadeus booking price (what user actually pays through Mystes)
            # Proxy markets = Google Flights prices (what user would pay elsewhere)
            # Savings = highest Google price minus Amadeus price (Mystes advantage)
            amadeus_booking_price = flight_converted_prices.get("US", us_proxy_price or 0)
            foreign_prices = {m: p for m, p in flight_converted_prices.items() if m != "US" and m != "Mystes"}

            if foreign_prices:
                # The comparison: what Google shows vs what Mystes charges
                # Use the cheapest foreign Google price as the "market rate"
                google_market_price = min(foreign_prices.values())
                google_market_name = min(foreign_prices, key=foreign_prices.get)
            else:
                google_market_price = 0
                google_market_name = None

            # Savings = Google best price - Amadeus booking price
            if amadeus_booking_price and google_market_price and google_market_price > amadeus_booking_price:
                flight_savings = google_market_price - amadeus_booking_price
                flight_savings_pct = round((flight_savings / google_market_price) * 100, 1)
            else:
                flight_savings = 0
                flight_savings_pct = 0

            # For display: cheapest price is what user pays (Amadeus)
            flight_cheapest_price = amadeus_booking_price if amadeus_booking_price else flight_cheapest_price
            flight_cheapest_market = "Mystes" if amadeus_booking_price and (not google_market_price or amadeus_booking_price <= google_market_price) else flight_cheapest_market

            flight_deal = None
            if flight_savings >= 10:
                platform_fee = round(flight_savings * 0.25, 2)
                flight_deal = {
                    "deal_id": f"deal_{origin}_{destination}_{date}_{flight.get('flight_number', '')}",
                    "home_price": round(google_market_price, 2) if google_market_price else round(amadeus_booking_price, 2),
                    "arbitrage_price": round(amadeus_booking_price, 2),
                    "gross_savings": round(flight_savings, 2),
                    "price_difference": round(flight_savings, 2),
                    "user_savings": round(flight_savings - platform_fee, 2),
                    "platform_fee_usd": platform_fee,
                    "user_saves_pct": flight_savings_pct,
                    "cheapest_market": "Mystes",
                    "is_good_deal": True,
                    "proxy_verified": True,
                }

            formatted_flight = {
                # Flight identity
                "flight_id": f"{flight.get('airline', 'Unknown')}_{origin}_{destination}_{date}_{dep_time}",
                "airline": flight.get("airline", "Various Airlines"),
                "flight_number": flight.get("flight_number"),

                # Schedule info
                "departure_time": flight.get("departure_time"),
                "arrival_time": flight.get("arrival_time"),
                "duration": flight.get("duration") or flight.get("duration_formatted"),
                "stops": flight.get("stops"),

                # Detailed leg info (Amadeus provides rich data here)
                "layovers": flight.get("layovers", []),
                "legs": flight.get("legs", []),
                "segments": flight.get("segments", []),  # Full segment breakdown from Amadeus

                # Price info - REAL prices from proxy scraping
                "cheapest_price": flight_cheapest_price,
                "cheapest_market": "Mystes",  # Never expose proxy market codes
                "converted_prices": {},  # Scrubbed — internal data only

                # Route info
                "origin": origin,
                "destination": destination,
                "route": f"{origin} → {destination}",
                "date": date,
                "return_date": return_date,
                "is_round_trip": is_round_trip,

                # Deal info
                "deal": flight_deal,
                "savings": flight_savings,
                "savings_pct": flight_savings_pct,

                # Rich details (from Amadeus when available)
                "travel_class": flight.get("cabin_class") or flight.get("travel_class", "Economy"),
                "airplane": flight.get("aircraft") or flight.get("airplane"),
                "baggage_info": flight.get("baggage_info"),
                "is_codeshare": flight.get("is_codeshare", False),
                "operating_carrier": flight.get("operating_carrier"),
                "carbon_kg": flight.get("carbon_kg"),
                "category": flight.get("category"),  # "best" or "other"

                # Return flight details (for round-trips from Amadeus)
                "return_flight": flight.get("return_flight"),

                # Raw Amadeus offer for booking API
                "raw_offer": flight.get("raw_offer"),
            }
            formatted_flights.append(formatted_flight)

        # Add EXCLUSIVE flights - cheap flights that don't exist in US market
        # These are still valuable deals even without direct US price comparison
        cheapest_us_matched = min([f.get('converted_prices', {}).get('US', 9999) for f in formatted_flights] or [9999])

        for market in ["ES", "UK"]:
            if market not in proxy_flights_by_market:
                continue
            market_data = proxy_flights_by_market[market]
            market_flights = market_data.get("flights", [])
            market_currency = market_data.get("currency", "EUR")
            rate = CURRENCY_RATES_TO_USD.get(market_currency, 1.0)

            # Find the cheapest flight in this market (ALWAYS include it)
            cheapest_in_market = None
            cheapest_in_market_price = float('inf')
            for mf in market_flights:
                if mf.get("price"):
                    price_usd = mf.get("price", 0) * rate
                    if price_usd < cheapest_in_market_price:
                        cheapest_in_market = mf
                        cheapest_in_market_price = price_usd

            for mf_idx, mf in enumerate(market_flights):
                mf_dep = normalize_time(mf.get("departure_time", ""))
                mf_price_usd = round(mf.get("price", 0) * rate, 2)

                # Skip if already matched (by time+airline or by index if no times)
                if mf_dep:
                    already_matched = any(
                        normalize_time(f.get("departure_time", "")) == mf_dep and
                        normalize_airline(f.get("airline", "")) == normalize_airline(mf.get("airline", ""))
                        for f in formatted_flights
                    )
                else:
                    # No departure time — match by index (flight already included as base)
                    already_matched = mf_idx < len(base_flights)

                if already_matched:
                    continue

                # ALWAYS include the cheapest flight from each market (so users can select it)
                # Also include others if significantly cheaper than cheapest US option (15% threshold)
                is_cheapest_in_market = (mf == cheapest_in_market)
                is_significantly_cheaper = (mf_price_usd < cheapest_us_matched * 0.85)

                if is_cheapest_in_market or is_significantly_cheaper:
                    savings_vs_cheapest_us = round(cheapest_us_matched - mf_price_usd, 2)
                    savings_pct_vs_us = round((savings_vs_cheapest_us / cheapest_us_matched) * 100, 1) if cheapest_us_matched > 0 else 0

                    print(f"    [EXCLUSIVE] {mf.get('airline', 'Unknown'):20} @ {mf.get('departure_time'):8} → {market}:${mf_price_usd:.0f} (no US equiv, {savings_pct_vs_us:.0f}% cheaper)")

                    exclusive_flight = {
                        "flight_id": f"{mf.get('airline', 'Unknown')}_{origin}_{destination}_{date}_{mf.get('departure_time')}",
                        "airline": mf.get("airline", "Various Airlines"),
                        "flight_number": None,
                        "departure_time": mf.get("departure_time"),
                        "arrival_time": mf.get("arrival_time"),
                        "duration": mf.get("duration"),
                        "stops": mf.get("stops"),
                        "cheapest_price": mf_price_usd,
                        "cheapest_market": "Mystes",
                        "converted_prices": {},  # Scrubbed
                        "origin": origin,
                        "destination": destination,
                        "route": f"{origin} → {destination}",
                        "date": date,
                        "return_date": return_date,
                        "deal": {
                            "deal_id": f"exclusive_mystes_{origin}_{destination}_{date}_{mf.get('departure_time')}",
                            "home_price": cheapest_us_matched,
                            "arbitrage_price": mf_price_usd,
                            "gross_savings": savings_vs_cheapest_us,
                            "user_savings": round(savings_vs_cheapest_us * 0.75, 2),
                            "platform_fee_usd": round(savings_vs_cheapest_us * 0.25, 2),
                            "user_saves_pct": savings_pct_vs_us,
                            "is_good_deal": True,
                            "proxy_verified": True,
                            "cheapest_market": "Mystes",
                        },
                        "savings": savings_vs_cheapest_us,
                        "savings_pct": savings_pct_vs_us,
                    }
                    formatted_flights.append(exclusive_flight)

        # If no flights from SerpAPI but we have proxy prices, create a generic flight entry
        if not formatted_flights and converted_prices and savings_vs_us > 10:
            generic_flight = {
                "flight_id": f"proxy_{origin}_{destination}_{date}",
                "airline": "Various Airlines",
                "flight_number": None,
                "departure_time": None,
                "arrival_time": None,
                "duration": None,
                "stops": None,
                "cheapest_price": cheapest_price,
                "cheapest_market": "Mystes",
                "converted_prices": {},  # Scrubbed
                "origin": origin,
                "destination": destination,
                "route": f"{origin} → {destination}",
                "date": date,
                "return_date": return_date,
                "deal": {
                    "deal_id": f"proxy_{origin}_{destination}_{date}",
                    "home_price": us_price,
                    "arbitrage_price": cheapest_price,
                    "gross_savings": savings_vs_us,
                    "user_savings": round(savings_vs_us * 0.75, 2),
                    "platform_fee_usd": round(savings_vs_us * 0.25, 2),
                    "user_saves_pct": savings_pct,
                    "is_good_deal": True,
                    "proxy_verified": True,
                },
                "savings": savings_vs_us,
                "savings_pct": savings_pct,
            }
            formatted_flights.append(generic_flight)

        # Build deals list from flights with arbitrage
        deals = [f for f in formatted_flights if f.get("deal") and f["deal"].get("is_good_deal")]
        deals.sort(key=lambda x: x['deal']['user_savings'], reverse=True)

        print(f"\n{'='*60}")
        print(f"HYBRID RESULTS: {len(deals)} deals / {len(formatted_flights)} flights with details")
        if savings_vs_us > 0:
            print(f"[ARBITRAGE] Save ${savings_vs_us:.2f} ({savings_pct:.1f}%) via {cheapest_market}")
        print(f"{'='*60}")

        # Scrub market codes — never expose proxy markets to frontend
        num_markets = len(converted_prices) if converted_prices else 0
        return {
            "origin": origin,
            "destination": destination,
            "date": date,
            "return_date": return_date,
            "is_round_trip": is_round_trip,
            "markets_checked": num_markets,  # Count only, no codes
            "total_flights": len(formatted_flights),
            "deals": deals,
            "flights": formatted_flights,
            "all_flights": formatted_flights,
            "price_comparison": [],  # Scrubbed — was per-market breakdown
            "proxy_results": {
                "cheapest_market": "Mystes",
                "cheapest_price_usd": cheapest_price,
                "savings_vs_us": savings_vs_us,
                "savings_pct": savings_pct,
                "markets_checked": num_markets,
            },
            "data_sources": hybrid_result.get("data_sources", {}),
        }

    # Hybrid search failed — no Amadeus or proxy data available
    print(f"\n[NO DATA] Amadeus + Proxy search unavailable.")
    print(f"  Ensure AMADEUS_API_KEY and AMADEUS_API_SECRET are set in .env")
    print(f"  and/or proxy scraper (playwright) is installed.")

    return {
        "origin": origin,
        "destination": destination,
        "date": date,
        "return_date": return_date,
        "is_round_trip": is_round_trip,
        "markets_checked": [],
        "total_flights": 0,
        "deals": [],
        "all_flights": [],
        "proxy_results": None,
        "data_sources": {"prices": "none", "flight_details": "none"},
        "error": "No search providers available. Configure Amadeus API keys or install playwright for proxy scraping.",
    }


# --- MULTI-FLIGHT ITINERARY ---

class FlightLeg:
    """Represents a single flight leg in an itinerary."""

    def __init__(
        self,
        origin: str,
        destination: str,
        date: str,
        deal: Optional[Dict] = None
    ):
        self.origin = origin
        self.destination = destination
        self.date = date
        self.deal = deal
        self.search_results = None

    def to_dict(self) -> Dict:
        return {
            "origin": self.origin,
            "destination": self.destination,
            "date": self.date,
            "deal": self.deal,
            "has_deal": self.deal is not None,
        }


class Itinerary:
    """
    Multi-flight travel itinerary builder.

    Allows users to build complex trips like:
    LAX → HND → BKK → SIN → SYD

    Calculates total savings across all legs.
    """

    def __init__(self, name: str = "My Trip"):
        self.name = name
        self.legs: List[FlightLeg] = []
        self.id = hashlib.md5(f"{name}:{datetime.utcnow().isoformat()}".encode()).hexdigest()[:12]
        self.created_at = datetime.utcnow()

    def add_leg(self, origin: str, destination: str, date: str) -> FlightLeg:
        """Add a flight leg to the itinerary."""
        leg = FlightLeg(origin, destination, date)
        self.legs.append(leg)
        return leg

    def remove_leg(self, index: int) -> bool:
        """Remove a leg by index."""
        if 0 <= index < len(self.legs):
            self.legs.pop(index)
            return True
        return False

    def search_all_legs(self, fast_mode: bool = True, search_options: dict = None) -> dict:
        """
        Search for deals on all legs of the itinerary.

        Args:
            fast_mode: If True, check fewer markets for speed
            search_options: Optional dict with passengers, cabin_class, stops

        Returns combined results with total savings.
        """
        print(f"\n{'='*70}")
        print(f"ITINERARY SEARCH: {self.name}")
        print(f"{'='*70}")

        if search_options:
            pax = search_options.get('passengers', {})
            total_pax = pax.get('adults', 1) + pax.get('children', 0) + pax.get('infants_seat', 0)
            print(f"Passengers: {total_pax} | Class: {search_options.get('cabin_class', 'economy')} | Stops: {search_options.get('stops', 'any')}")

        results = []
        total_savings = 0
        total_platform_fee = 0
        total_gross_savings = 0

        for i, leg in enumerate(self.legs):
            print(f"\nLeg {i+1}: {leg.origin} → {leg.destination} on {leg.date}")
            print("-" * 40)

            # Search this leg with options
            leg_results = search_global(
                origin=leg.origin,
                destination=leg.destination,
                date=leg.date,
                fast_mode=fast_mode,
                search_options=search_options
            )

            leg.search_results = leg_results

            # Get best deal for this leg
            if leg_results["deals"]:
                best_deal = leg_results["deals"][0]  # Already sorted by savings
                leg.deal = best_deal

                deal_info = best_deal.get("deal", {})
                total_savings += deal_info.get("user_savings", 0)
                total_platform_fee += deal_info.get("platform_fee_usd", 0)
                total_gross_savings += deal_info.get("gross_savings", 0)

                results.append({
                    "leg": i + 1,
                    "route": f"{leg.origin} → {leg.destination}",
                    "date": leg.date,
                    "deal": best_deal,
                    "savings": deal_info.get("user_savings", 0),
                    "all_flights": leg_results.get("all_flights", []),
                    "markets_checked": leg_results.get("markets_checked", []),
                    "proxy_results": leg_results.get("proxy_results"),
                })
            else:
                results.append({
                    "leg": i + 1,
                    "route": f"{leg.origin} → {leg.destination}",
                    "date": leg.date,
                    "deal": None,
                    "savings": 0,
                    "note": "No arbitrage deals found - book at standard price",
                    "all_flights": leg_results.get("all_flights", []),
                    "markets_checked": leg_results.get("markets_checked", []),
                    "proxy_results": leg_results.get("proxy_results"),
                })

        # Calculate combined platform fee (potential discount for multi-leg)
        # 10% discount on platform fees for 3+ legs
        fee_discount = 0
        if len(self.legs) >= 3:
            fee_discount = total_platform_fee * 0.10
            total_platform_fee -= fee_discount

        print(f"\n{'='*70}")
        print(f"ITINERARY SUMMARY")
        print(f"{'='*70}")
        print(f"Total legs: {len(self.legs)}")
        print(f"Gross savings: ${total_gross_savings:.2f}")
        print(f"Platform fees: ${total_platform_fee:.2f}")
        if fee_discount > 0:
            print(f"Multi-leg discount: -${fee_discount:.2f}")
        print(f"YOUR TOTAL SAVINGS: ${total_savings:.2f}")

        # Calculate total flights found
        total_flights_found = sum(len(r.get("all_flights", [])) for r in results)
        all_markets = set()
        for r in results:
            all_markets.update(r.get("markets_checked", []))

        return {
            "itinerary_id": self.id,
            "name": self.name,
            "legs": [leg.to_dict() for leg in self.legs],
            "leg_results": results,
            "summary": {
                "total_legs": len(self.legs),
                "total_flights_found": total_flights_found,
                "legs_with_deals": sum(1 for r in results if r["deal"]),
                "gross_savings_usd": round(total_gross_savings, 2),
                "platform_fee_usd": round(total_platform_fee, 2),
                "fee_discount_usd": round(fee_discount, 2),
                "total_savings_usd": round(total_savings, 2),
                "markets_checked": list(all_markets),
            }
        }

    def to_dict(self) -> Dict:
        """Convert itinerary to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "legs": [leg.to_dict() for leg in self.legs],
            "total_legs": len(self.legs),
        }


# --- QUICK SEARCH HELPERS ---

def quick_search(origin: str, destination: str, date: str) -> Dict:
    """
    Quick search with default settings.

    Args:
        origin: Origin airport code
        destination: Destination airport code
        date: Date string (YYYY-MM-DD)

    Returns:
        Search results with deals
    """
    return search_global(origin, destination, date, fast_mode=True)


def search_round_trip(origin: str, destination: str, depart_date: str, return_date: str) -> Dict:
    """
    Search for round-trip flights.

    Creates a 2-leg itinerary and searches both legs.
    """
    itinerary = Itinerary(name=f"Round Trip: {origin} ↔ {destination}")
    itinerary.add_leg(origin, destination, depart_date)
    itinerary.add_leg(destination, origin, return_date)

    return itinerary.search_all_legs(fast_mode=True)


def search_multi_city(legs: List[Tuple[str, str, str]]) -> Dict:
    """
    Search for multi-city itinerary.

    Args:
        legs: List of (origin, destination, date) tuples

    Example:
        search_multi_city([
            ("LAX", "HND", "2026-03-01"),
            ("HND", "BKK", "2026-03-05"),
            ("BKK", "SYD", "2026-03-10"),
            ("SYD", "LAX", "2026-03-15"),
        ])
    """
    # Create readable name
    cities = [legs[0][0]] + [leg[1] for leg in legs]
    name = " → ".join(cities)

    itinerary = Itinerary(name=f"Multi-City: {name}")

    for origin, destination, date in legs:
        itinerary.add_leg(origin, destination, date)

    return itinerary.search_all_legs(fast_mode=True)


# --- AIRPORT SEARCH ---

def search_airports(query: str) -> List[Dict]:
    """
    Search for airports by code or city name.

    Args:
        query: Search query (e.g., "LAX", "Tokyo", "London")

    Returns:
        List of matching airports
    """
    query = query.upper()
    results = []

    # Common city names to airport codes
    CITY_TO_AIRPORTS = {
        "TOKYO": ["HND", "NRT"],
        "NEW YORK": ["JFK", "EWR", "LGA"],
        "LONDON": ["LHR", "LGW", "STN", "LTN"],
        "PARIS": ["CDG", "ORY"],
        "LOS ANGELES": ["LAX"],
        "SAN FRANCISCO": ["SFO"],
        "CHICAGO": ["ORD", "MDW"],
        "MIAMI": ["MIA"],
        "SEOUL": ["ICN", "GMP"],
        "SINGAPORE": ["SIN"],
        "HONG KONG": ["HKG"],
        "BANGKOK": ["BKK", "DMK"],
        "SYDNEY": ["SYD"],
        "DUBAI": ["DXB"],
        "FRANKFURT": ["FRA"],
        "AMSTERDAM": ["AMS"],
    }

    # Search by airport code
    if query in AIRPORT_COUNTRY_MAP:
        country = AIRPORT_COUNTRY_MAP[query]
        results.append({
            "code": query,
            "country": country,
            "type": "airport"
        })

    # Search by city name
    for city, airports in CITY_TO_AIRPORTS.items():
        if query in city:
            for code in airports:
                country = AIRPORT_COUNTRY_MAP.get(code, "")
                results.append({
                    "code": code,
                    "city": city.title(),
                    "country": country,
                    "type": "airport"
                })

    return results


# --- EXAMPLE USAGE ---

if __name__ == "__main__":
    # Example 1: Simple global search
    print("\n" + "="*70)
    print("EXAMPLE 1: Paris to Tokyo")
    print("="*70)
    results = quick_search("CDG", "HND", "2026-03-15")
    print(f"Found {len(results['deals'])} deals")

    # Example 2: Round trip search
    print("\n" + "="*70)
    print("EXAMPLE 2: Round trip NYC to London")
    print("="*70)
    results = search_round_trip("JFK", "LHR", "2026-04-01", "2026-04-10")
    print(f"Total savings: ${results['summary']['total_savings_usd']}")

    # Example 3: Multi-city trip
    print("\n" + "="*70)
    print("EXAMPLE 3: Multi-city Asia trip")
    print("="*70)
    results = search_multi_city([
        ("LAX", "HND", "2026-05-01"),
        ("HND", "BKK", "2026-05-05"),
        ("BKK", "SIN", "2026-05-08"),
        ("SIN", "LAX", "2026-05-12"),
    ])
    print(f"Total savings: ${results['summary']['total_savings_usd']}")
