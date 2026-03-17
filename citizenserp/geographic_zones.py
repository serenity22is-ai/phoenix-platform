"""
MYSTES Geographic Zone System

Breaks the world into sub-regional zones for precision geographic arbitrage.
Instead of country-level only (US vs JP), Mystes can target US-NE (Northeast)
vs US-SW (Southwest) to capture intra-country price discrimination.

Hierarchy:
    Region → Country → Zone → Cities
    NA     → US      → US-NE → NYC, BOS, PHL

The proxy IP's physical location determines what prices a site shows — not
URL parameters. A node in NYC vs Dallas returns different prices for the
same Google Flights URL. The zone system routes tasks to the right nodes.

Zone codes: {country}-{zone_suffix}  e.g. US-NE, JP-KT, GB-LN
Country codes: 2-letter ISO  e.g. US, JP, GB (backwards compatible)

Usage:
    from geographic_zones import (
        get_zone, get_zones_for_country, get_zone_for_city,
        resolve_market, is_zone_code, get_all_zones
    )

    # Get all US zones
    us_zones = get_zones_for_country("US")
    # → [GeoZone(zone_code="US-NE", ...), GeoZone(zone_code="US-SE", ...), ...]

    # Resolve market code to zone codes
    zones = resolve_market("US")      # → ["US-NE", "US-SE", "US-MW", ...]
    zones = resolve_market("US-NE")   # → ["US-NE"]

    # Find zone for a city
    zone = get_zone_for_city("new york")  # → GeoZone(zone_code="US-NE", ...)
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# Zone Data Structure
# ============================================================

@dataclass
class GeoZone:
    """A geographic zone — a sub-region within a country."""
    zone_code: str          # e.g. "US-NE", "JP-KT"
    country: str            # 2-letter ISO e.g. "US"
    name: str               # Human-readable e.g. "Northeast"
    cities: List[str]       # Major cities in this zone (lowercase for matching)
    lat_center: float       # Center latitude (for distance calculations)
    lon_center: float       # Center longitude
    timezone: str           # Primary timezone e.g. "America/New_York"
    population_tier: str    # "major", "medium", "minor" — affects search priority


# ============================================================
# Zone Registry — all zones globally
# ============================================================

ZONE_REGISTRY: Dict[str, GeoZone] = {}


def _register(zone_code: str, country: str, name: str, cities: List[str],
              lat: float, lon: float, tz: str, tier: str = "medium"):
    """Register a zone in the global registry."""
    ZONE_REGISTRY[zone_code] = GeoZone(
        zone_code=zone_code,
        country=country,
        name=name,
        cities=[c.lower() for c in cities],
        lat_center=lat,
        lon_center=lon,
        timezone=tz,
        population_tier=tier,
    )


# ──────────────────────────────────────────────────────────────
# NORTH AMERICA
# ──────────────────────────────────────────────────────────────

# United States — 9 zones
_register("US-NE", "US", "Northeast", ["new york", "nyc", "boston", "philadelphia", "hartford", "newark", "jersey city", "providence", "stamford", "new haven"], 40.7, -74.0, "America/New_York", "major")
_register("US-SE", "US", "Southeast", ["atlanta", "miami", "charlotte", "nashville", "orlando", "tampa", "jacksonville", "raleigh", "richmond", "savannah"], 33.7, -84.4, "America/New_York", "major")
_register("US-MW", "US", "Midwest", ["chicago", "detroit", "minneapolis", "indianapolis", "milwaukee", "kansas city", "st louis", "omaha", "des moines"], 41.9, -87.6, "America/Chicago", "major")
_register("US-SW", "US", "Southwest", ["dallas", "houston", "san antonio", "austin", "mystes", "tucson", "el paso", "oklahoma city", "tulsa", "fort worth"], 32.8, -96.8, "America/Chicago", "major")
_register("US-NW", "US", "Northwest", ["seattle", "portland", "boise", "spokane", "tacoma", "eugene", "salem", "olympia", "anchorage"], 47.6, -122.3, "America/Los_Angeles", "medium")
_register("US-SC", "US", "Southern California", ["los angeles", "san diego", "long beach", "anaheim", "irvine", "riverside", "santa barbara", "pasadena", "burbank"], 34.1, -118.2, "America/Los_Angeles", "major")
_register("US-NC", "US", "Northern California", ["san francisco", "san jose", "sacramento", "oakland", "fremont", "palo alto", "berkeley", "santa cruz", "fresno", "stockton"], 37.8, -122.4, "America/Los_Angeles", "major")
_register("US-GL", "US", "Great Lakes", ["cleveland", "cincinnati", "columbus", "pittsburgh", "buffalo", "rochester", "akron", "dayton", "toledo", "erie"], 40.4, -82.0, "America/New_York", "medium")
_register("US-MT", "US", "Mountain", ["denver", "salt lake city", "las vegas", "albuquerque", "colorado springs", "reno", "boise", "billings", "cheyenne"], 39.7, -105.0, "America/Denver", "medium")

# Canada — 5 zones
_register("CA-ON", "CA", "Ontario", ["toronto", "ottawa", "mississauga", "hamilton", "london", "brampton", "markham", "kitchener"], 43.7, -79.4, "America/Toronto", "major")
_register("CA-QC", "CA", "Quebec", ["montreal", "quebec city", "laval", "gatineau", "sherbrooke", "trois-rivieres"], 45.5, -73.6, "America/Toronto", "major")
_register("CA-BC", "CA", "British Columbia", ["vancouver", "victoria", "surrey", "burnaby", "kelowna", "kamloops"], 49.3, -123.1, "America/Vancouver", "medium")
_register("CA-AB", "CA", "Alberta", ["calgary", "edmonton", "red deer", "lethbridge"], 51.0, -114.1, "America/Edmonton", "medium")
_register("CA-PR", "CA", "Prairies & Atlantic", ["winnipeg", "saskatoon", "regina", "halifax", "st john's", "fredericton", "charlottetown"], 49.9, -97.1, "America/Winnipeg", "minor")

# Mexico — 3 zones
_register("MX-CT", "MX", "Central", ["mexico city", "puebla", "toluca", "queretaro", "cuernavaca", "pachuca"], 19.4, -99.1, "America/Mexico_City", "major")
_register("MX-NR", "MX", "North", ["monterrey", "guadalajara", "tijuana", "juarez", "chihuahua", "leon", "saltillo"], 25.7, -100.3, "America/Monterrey", "medium")
_register("MX-SE", "MX", "Southeast & Coast", ["cancun", "merida", "veracruz", "acapulco", "oaxaca", "playa del carmen"], 21.2, -86.8, "America/Cancun", "medium")

# ──────────────────────────────────────────────────────────────
# EUROPE
# ──────────────────────────────────────────────────────────────

# United Kingdom — 4 zones
_register("GB-LN", "GB", "London & Southeast", ["london", "brighton", "cambridge", "oxford", "reading", "southampton", "canterbury"], 51.5, -0.1, "Europe/London", "major")
_register("GB-NW", "GB", "North & Midlands", ["manchester", "birmingham", "leeds", "liverpool", "sheffield", "nottingham", "bristol", "leicester", "newcastle", "york"], 53.5, -2.2, "Europe/London", "major")
_register("GB-SC", "GB", "Scotland", ["edinburgh", "glasgow", "aberdeen", "dundee", "inverness", "stirling"], 55.9, -3.2, "Europe/London", "medium")
_register("GB-WL", "GB", "Wales & Southwest", ["cardiff", "swansea", "newport", "exeter", "plymouth", "bath", "cornwall"], 51.5, -3.2, "Europe/London", "minor")

# Germany — 4 zones
_register("DE-NW", "DE", "Northwest", ["cologne", "dusseldorf", "dortmund", "essen", "hamburg", "bremen", "hannover", "bonn", "munster"], 51.0, 6.9, "Europe/Berlin", "major")
_register("DE-NE", "DE", "Northeast", ["berlin", "leipzig", "dresden", "potsdam", "rostock", "magdeburg"], 52.5, 13.4, "Europe/Berlin", "major")
_register("DE-SW", "DE", "Southwest", ["munich", "stuttgart", "nuremberg", "augsburg", "karlsruhe", "freiburg", "frankfurt", "mannheim", "wiesbaden"], 48.1, 11.6, "Europe/Berlin", "major")
_register("DE-SE", "DE", "Southeast", ["dresden", "chemnitz", "erfurt", "jena", "gera", "zwickau"], 51.1, 13.7, "Europe/Berlin", "minor")

# France — 3 zones
_register("FR-IF", "FR", "Île-de-France", ["paris", "versailles", "boulogne", "saint-denis", "montreuil", "nanterre"], 48.9, 2.3, "Europe/Paris", "major")
_register("FR-SE", "FR", "Southeast", ["lyon", "marseille", "nice", "toulouse", "montpellier", "grenoble", "bordeaux"], 43.3, 5.4, "Europe/Paris", "major")
_register("FR-NW", "FR", "North & West", ["lille", "nantes", "strasbourg", "rennes", "rouen", "reims", "le havre"], 48.6, -1.7, "Europe/Paris", "medium")

# Spain — 3 zones
_register("ES-MD", "ES", "Central", ["madrid", "toledo", "valladolid", "zaragoza", "salamanca"], 40.4, -3.7, "Europe/Madrid", "major")
_register("ES-CT", "ES", "Catalonia & East", ["barcelona", "valencia", "palma", "alicante", "tarragona", "girona"], 41.4, 2.2, "Europe/Madrid", "major")
_register("ES-AN", "ES", "Andalusia & South", ["seville", "malaga", "granada", "cordoba", "cadiz", "bilbao"], 37.4, -6.0, "Europe/Madrid", "medium")

# Italy — 3 zones
_register("IT-NR", "IT", "North", ["milan", "turin", "venice", "bologna", "genoa", "verona", "padua", "trieste"], 45.5, 9.2, "Europe/Rome", "major")
_register("IT-CT", "IT", "Central", ["rome", "florence", "pisa", "perugia", "siena", "ancona"], 41.9, 12.5, "Europe/Rome", "major")
_register("IT-SD", "IT", "South & Islands", ["naples", "palermo", "bari", "catania", "messina", "cagliari"], 40.9, 14.3, "Europe/Rome", "medium")

# Netherlands — 2 zones
_register("NL-RH", "NL", "Randstad", ["amsterdam", "rotterdam", "the hague", "utrecht", "leiden", "haarlem", "delft"], 52.4, 4.9, "Europe/Amsterdam", "major")
_register("NL-PR", "NL", "Provinces", ["eindhoven", "groningen", "maastricht", "nijmegen", "arnhem", "breda", "tilburg"], 51.4, 5.5, "Europe/Amsterdam", "minor")

# Single-zone European countries
_register("CH-ZH", "CH", "Switzerland", ["zurich", "geneva", "bern", "basel", "lausanne", "lucerne"], 47.4, 8.5, "Europe/Zurich", "medium")
_register("AT-VN", "AT", "Austria", ["vienna", "salzburg", "graz", "innsbruck", "linz"], 48.2, 16.4, "Europe/Vienna", "medium")
_register("SE-ST", "SE", "Sweden", ["stockholm", "gothenburg", "malmo", "uppsala", "linkoping"], 59.3, 18.1, "Europe/Stockholm", "medium")
_register("NO-OS", "NO", "Norway", ["oslo", "bergen", "trondheim", "stavanger", "tromso"], 59.9, 10.8, "Europe/Oslo", "medium")
_register("DK-CP", "DK", "Denmark", ["copenhagen", "aarhus", "odense", "aalborg"], 55.7, 12.6, "Europe/Copenhagen", "medium")
_register("FI-HK", "FI", "Finland", ["helsinki", "espoo", "tampere", "turku", "oulu"], 60.2, 24.9, "Europe/Helsinki", "medium")
_register("PL-WS", "PL", "Poland West", ["warsaw", "krakow", "wroclaw", "poznan", "lodz", "gdansk"], 52.2, 21.0, "Europe/Warsaw", "medium")
_register("PL-ES", "PL", "Poland East", ["lublin", "bialystok", "rzeszow", "katowice", "szczecin"], 51.2, 22.6, "Europe/Warsaw", "minor")
_register("PT-LS", "PT", "Portugal", ["lisbon", "porto", "braga", "coimbra", "funchal", "faro"], 38.7, -9.1, "Europe/Lisbon", "medium")
_register("GR-AT", "GR", "Greece", ["athens", "thessaloniki", "heraklion", "patras", "rhodes"], 37.9, 23.7, "Europe/Athens", "medium")
_register("CZ-PR", "CZ", "Czech Republic", ["prague", "brno", "ostrava", "plzen", "olomouc"], 50.1, 14.4, "Europe/Prague", "medium")
_register("RO-BC", "RO", "Romania", ["bucharest", "cluj-napoca", "timisoara", "iasi", "brasov", "constanta"], 44.4, 26.1, "Europe/Bucharest", "medium")
_register("IE-DB", "IE", "Ireland", ["dublin", "cork", "galway", "limerick", "waterford"], 53.3, -6.3, "Europe/Dublin", "medium")

# ──────────────────────────────────────────────────────────────
# ASIA-PACIFIC
# ──────────────────────────────────────────────────────────────

# Japan — 4 zones
_register("JP-KT", "JP", "Kanto", ["tokyo", "yokohama", "chiba", "saitama", "kawasaki", "sagamihara"], 35.7, 139.7, "Asia/Tokyo", "major")
_register("JP-KS", "JP", "Kansai", ["osaka", "kyoto", "kobe", "nara", "wakayama"], 34.7, 135.5, "Asia/Tokyo", "major")
_register("JP-CH", "JP", "Chubu", ["nagoya", "shizuoka", "hamamatsu", "niigata", "kanazawa"], 35.2, 137.0, "Asia/Tokyo", "medium")
_register("JP-KY", "JP", "Kyushu & West", ["fukuoka", "hiroshima", "sapporo", "sendai", "kitakyushu", "kumamoto", "nagasaki", "okinawa"], 33.6, 130.4, "Asia/Tokyo", "medium")

# India — 4 zones
_register("IN-NR", "IN", "North", ["delhi", "new delhi", "lucknow", "jaipur", "chandigarh", "agra", "varanasi", "amritsar"], 28.6, 77.2, "Asia/Kolkata", "major")
_register("IN-WS", "IN", "West", ["mumbai", "pune", "ahmedabad", "surat", "nagpur", "indore", "goa"], 19.1, 72.9, "Asia/Kolkata", "major")
_register("IN-SD", "IN", "South", ["bangalore", "chennai", "hyderabad", "kochi", "coimbatore", "thiruvananthapuram", "mysore"], 12.9, 77.6, "Asia/Kolkata", "major")
_register("IN-ES", "IN", "East", ["kolkata", "bhubaneswar", "patna", "guwahati", "ranchi"], 22.6, 88.4, "Asia/Kolkata", "medium")

# South Korea — 2 zones
_register("KR-SL", "KR", "Seoul & Capital", ["seoul", "incheon", "suwon", "seongnam", "goyang", "yongin"], 37.6, 127.0, "Asia/Seoul", "major")
_register("KR-PR", "KR", "Provinces", ["busan", "daegu", "daejeon", "gwangju", "ulsan", "jeju"], 35.2, 129.0, "Asia/Seoul", "medium")

# Australia — 3 zones
_register("AU-NS", "AU", "New South Wales", ["sydney", "newcastle", "wollongong", "central coast", "canberra"], -33.9, 151.2, "Australia/Sydney", "major")
_register("AU-VC", "AU", "Victoria & South", ["melbourne", "geelong", "adelaide", "hobart", "ballarat"], -37.8, 144.9, "Australia/Melbourne", "major")
_register("AU-QW", "AU", "Queensland & West", ["brisbane", "gold coast", "perth", "cairns", "darwin", "townsville", "sunshine coast"], -27.5, 153.0, "Australia/Brisbane", "medium")

# Single-zone APAC countries
_register("SG-SG", "SG", "Singapore", ["singapore", "changi", "jurong", "woodlands"], 1.3, 103.8, "Asia/Singapore", "major")
_register("HK-HK", "HK", "Hong Kong", ["hong kong", "kowloon", "new territories", "tsim sha tsui", "central"], 22.3, 114.2, "Asia/Hong_Kong", "major")
_register("TH-BK", "TH", "Thailand", ["bangkok", "chiang mai", "phuket", "pattaya", "hua hin", "krabi", "koh samui"], 13.8, 100.5, "Asia/Bangkok", "medium")
_register("MY-KL", "MY", "Malaysia", ["kuala lumpur", "penang", "johor bahru", "malacca", "kota kinabalu", "kuching"], 3.1, 101.7, "Asia/Kuala_Lumpur", "medium")
_register("PH-MN", "PH", "Philippines", ["manila", "cebu", "davao", "quezon city", "makati", "taguig", "clark"], 14.6, 121.0, "Asia/Manila", "medium")
_register("ID-JK", "ID", "Indonesia West", ["jakarta", "bandung", "surabaya", "yogyakarta", "semarang", "medan"], -6.2, 106.8, "Asia/Jakarta", "medium")
_register("ID-BL", "ID", "Indonesia East", ["bali", "denpasar", "makassar", "manado", "lombok"], -8.3, 115.2, "Asia/Makassar", "minor")
_register("VN-HN", "VN", "Vietnam", ["hanoi", "ho chi minh city", "da nang", "nha trang", "hue", "hai phong", "can tho"], 21.0, 105.8, "Asia/Ho_Chi_Minh", "medium")
_register("NZ-AK", "NZ", "New Zealand", ["auckland", "wellington", "christchurch", "queenstown", "hamilton", "dunedin"], -36.9, 174.8, "Pacific/Auckland", "medium")
_register("IL-TA", "IL", "Israel", ["tel aviv", "jerusalem", "haifa", "beer sheva", "eilat", "netanya"], 32.1, 34.8, "Asia/Jerusalem", "medium")

# ──────────────────────────────────────────────────────────────
# SOUTH AMERICA
# ──────────────────────────────────────────────────────────────

# Brazil — 3 zones
_register("BR-SE", "BR", "Southeast", ["sao paulo", "rio de janeiro", "belo horizonte", "campinas", "santos", "niteroi"], -23.5, -46.6, "America/Sao_Paulo", "major")
_register("BR-NE", "BR", "Northeast", ["salvador", "recife", "fortaleza", "natal", "maceio", "joao pessoa"], -12.9, -38.5, "America/Bahia", "medium")
_register("BR-SW", "BR", "South & West", ["porto alegre", "curitiba", "florianopolis", "brasilia", "goiania", "manaus"], -25.4, -49.3, "America/Sao_Paulo", "medium")

# Argentina — 2 zones
_register("AR-BA", "AR", "Buenos Aires", ["buenos aires", "la plata", "mar del plata", "rosario", "santa fe"], -34.6, -58.4, "America/Argentina/Buenos_Aires", "major")
_register("AR-IN", "AR", "Interior", ["cordoba", "mendoza", "tucuman", "salta", "bariloche", "ushuaia"], -31.4, -64.2, "America/Argentina/Cordoba", "minor")

# Single-zone South American countries
_register("CO-BG", "CO", "Colombia", ["bogota", "medellin", "cali", "barranquilla", "cartagena", "bucaramanga"], 4.7, -74.1, "America/Bogota", "medium")
_register("CL-SC", "CL", "Chile", ["santiago", "valparaiso", "concepcion", "temuco", "antofagasta", "vina del mar"], -33.4, -70.7, "America/Santiago", "medium")
_register("PE-LM", "PE", "Peru", ["lima", "cusco", "arequipa", "trujillo", "chiclayo", "piura"], -12.0, -77.0, "America/Lima", "medium")

# ──────────────────────────────────────────────────────────────
# MIDDLE EAST & AFRICA
# ──────────────────────────────────────────────────────────────

_register("AE-DB", "AE", "UAE", ["dubai", "abu dhabi", "sharjah", "ajman", "ras al khaimah", "al ain"], 25.2, 55.3, "Asia/Dubai", "major")
_register("SA-RY", "SA", "Saudi Arabia", ["riyadh", "jeddah", "mecca", "medina", "dammam", "khobar"], 24.7, 46.7, "Asia/Riyadh", "medium")
_register("TR-IS", "TR", "Turkey West", ["istanbul", "ankara", "izmir", "bursa", "antalya", "adana"], 41.0, 28.9, "Europe/Istanbul", "major")
_register("TR-ES", "TR", "Turkey East", ["gaziantep", "diyarbakir", "trabzon", "kayseri", "konya", "erzurum"], 37.1, 37.4, "Europe/Istanbul", "minor")
_register("ZA-GP", "ZA", "South Africa", ["johannesburg", "cape town", "durban", "pretoria", "port elizabeth", "bloemfontein"], -26.2, 28.0, "Africa/Johannesburg", "medium")
_register("NG-LG", "NG", "Nigeria", ["lagos", "abuja", "port harcourt", "kano", "ibadan", "benin city"], 6.5, 3.4, "Africa/Lagos", "medium")
_register("EG-CR", "EG", "Egypt", ["cairo", "alexandria", "giza", "sharm el sheikh", "luxor", "hurghada", "aswan"], 30.0, 31.2, "Africa/Cairo", "medium")


# ============================================================
# Country → Zones mapping (auto-built from registry)
# ============================================================

_COUNTRY_ZONES: Dict[str, List[str]] = {}
for _zc, _gz in ZONE_REGISTRY.items():
    _COUNTRY_ZONES.setdefault(_gz.country, []).append(_zc)

# Sort zones within each country for consistent ordering
for _c in _COUNTRY_ZONES:
    _COUNTRY_ZONES[_c].sort()


# ============================================================
# City → Zone reverse index (auto-built from registry)
# ============================================================

_CITY_TO_ZONE: Dict[str, str] = {}
for _zc, _gz in ZONE_REGISTRY.items():
    for _city in _gz.cities:
        _CITY_TO_ZONE[_city] = _zc


# ============================================================
# Public API
# ============================================================

def get_zone(zone_code: str) -> Optional[GeoZone]:
    """Get a zone by its code (e.g. 'US-NE')."""
    return ZONE_REGISTRY.get(zone_code.upper())


def get_zones_for_country(country: str) -> List[GeoZone]:
    """Get all zones for a country code (e.g. 'US' → 9 zones)."""
    zone_codes = _COUNTRY_ZONES.get(country.upper(), [])
    return [ZONE_REGISTRY[zc] for zc in zone_codes]


def get_zone_for_city(city: str) -> Optional[GeoZone]:
    """Find the zone containing a city name (case-insensitive)."""
    zone_code = _CITY_TO_ZONE.get(city.lower())
    if zone_code:
        return ZONE_REGISTRY.get(zone_code)
    # Partial match fallback
    city_lower = city.lower()
    for c, zc in _CITY_TO_ZONE.items():
        if city_lower in c or c in city_lower:
            return ZONE_REGISTRY.get(zc)
    return None


def get_all_zones() -> List[GeoZone]:
    """Get all registered zones globally."""
    return list(ZONE_REGISTRY.values())


def get_all_countries() -> List[str]:
    """Get all countries that have zones defined."""
    return sorted(_COUNTRY_ZONES.keys())


def resolve_market(market_code: str) -> List[str]:
    """
    Resolve a market code to zone codes.
    - Country code "US" → ["US-GL", "US-MT", "US-MW", "US-NC", ...]
    - Zone code "US-NE" → ["US-NE"]
    - Unknown → empty list
    """
    code = market_code.upper()
    # Check if it's a zone code
    if code in ZONE_REGISTRY:
        return [code]
    # Check if it's a country code
    if code in _COUNTRY_ZONES:
        return _COUNTRY_ZONES[code]
    return []


def is_zone_code(code: str) -> bool:
    """Check if a code is a zone code (contains '-') vs country code."""
    return "-" in code


def get_country_from_zone(zone_code: str) -> str:
    """Extract country code from zone code. 'US-NE' → 'US'."""
    return zone_code.split("-")[0].upper()


def get_zone_summary() -> Dict[str, any]:
    """Summary stats for the zone system."""
    return {
        "total_zones": len(ZONE_REGISTRY),
        "total_countries": len(_COUNTRY_ZONES),
        "total_cities": len(_CITY_TO_ZONE),
        "countries": {
            country: {
                "zone_count": len(zones),
                "zones": zones,
            }
            for country, zones in sorted(_COUNTRY_ZONES.items())
        },
    }


logger.info(
    f"Geographic zone system loaded: {len(ZONE_REGISTRY)} zones across "
    f"{len(_COUNTRY_ZONES)} countries, {len(_CITY_TO_ZONE)} cities indexed"
)
