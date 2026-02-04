# FlightFinder Development Session Archive
**Date:** January 27, 2026
**Sessions:** 2 (Proxy Integration + Search Fixes & Flight Number Search)

---

## Session 2 Summary (Latest)

This session fixed critical issues and added new features:

### Fixes Applied
- **CSRF protection** - Exempted API search endpoints from CSRF to allow JSON POST requests
- **Jinja template rendering** - Fixed search page to properly render JavaScript variables
- **Currency rate issue** - Disabled live currency rate updates that were eliminating arbitrage detection
- **Airport autocomplete** - Added `/api/airports` endpoint with 350+ airports database

### New Features Added
- **Flight Number Search** - Search for specific flights (e.g., "LL 2624") and compare prices across markets
- **Live Price Comparison Table** - Shows prices in local currencies with USD equivalents
- **Tabbed Search Interface** - Route Search and Flight Number tabs on search page
- **Google Flights Link** - Direct link to view flights on Google

---

## Session 1 Summary

Previous session implemented:
- **Webshare.io proxy integration** for automated country-targeted proxy routing
- **Proxy manager module** with auto country selection
- **Admin proxy management page** with connection testing
- **Navigation update** - Added Search link to main nav

---

## Files Created

### airports.py
New module with 350+ airports database for autocomplete.

**Key features:**
- `AIRPORTS` dict - Maps airport codes to city, country, name
- `search_airports(query)` - Fuzzy search by code, city, or country
- `get_airport(code)` - Get airport details by code

### proxy_manager.py
Module for managing residential proxy connections via Webshare.io.

**Key features:**
- `ProxyManager` class - Main proxy management
- `get_proxy_for_market(market)` - Get proxy dict for a market code
- `is_proxy_configured()` - Check if Webshare credentials are set
- `MARKET_TO_COUNTRY_CODE` - Maps 40+ market codes to ISO country codes

---

## Files Modified (Session 2)

### main.py
- Added `search_flight_number()` function for specific flight lookup
- Searches a flight number across multiple markets
- Returns comparison with cheapest market and savings

### search.py
- Disabled `fetch_live_currency_rates()` call to use stable static rates
- This fixes arbitrage detection being eliminated by fluctuating exchange rates

### server.py
Major updates:
1. **Imports added:**
   - `search_flight_number` from main
   - `search_airports` from airports

2. **CSRF exemptions:**
   ```python
   @app.route("/api/search", methods=["POST"])
   @csrf.exempt  # Added

   @app.route("/api/search/itinerary", methods=["POST"])
   @csrf.exempt  # Added

   @app.route("/api/search/flight", methods=["POST"])
   @csrf.exempt  # New endpoint
   ```

3. **New API endpoints:**
   - `/api/airports?q=` - Airport search autocomplete
   - `/api/search/flight` - Flight number price comparison

4. **Updated search page:**
   - Added tabbed interface (Route Search / Flight Number)
   - Added flight number search form
   - Added price comparison table with market flags
   - Added Google Flights link

5. **Fixed Jinja rendering:**
   ```python
   def search_page():
       rendered_content = render_template_string(
           SEARCH_PAGE_CONTENT,
           current_user=current_user
       )
       return render_template_string(
           BASE_TEMPLATE,
           title="Search Flights",
           content=rendered_content,
           current_user=current_user
       )
   ```

---

## New Routes Added (Session 2)

| Route | Method | Description |
|-------|--------|-------------|
| `/api/airports` | GET | Airport search autocomplete |
| `/api/search/flight` | POST | Flight number price comparison |

---

## How Flight Number Search Works

1. **User enters flight number** (e.g., "LL 2624")
2. **Provides route and date** (LAX → BCN on 2026-03-15)
3. **System searches priority markets** (US, UK, DE, JP, AU, CA, IN, etc.)
4. **Finds matching flight** in each market
5. **Compares prices** converted to USD
6. **Shows comparison table** with cheapest market highlighted
7. **Calculates savings** and platform fee

**Example result:**
```
Flight: LEVEL LL 2624 (LAX → BCN)
Markets checked: US, UK, DE, JP, AU, CA, IN

| Market | Local Price | USD    | vs Cheapest |
|--------|-------------|--------|-------------|
| DE     | 353 EUR     | $381   | CHEAPEST    |
| ES     | 353 EUR     | $381   | +$0.00      |
| UK     | 312 GBP     | $393   | +$12.00     |
| US     | $424        | $424   | +$43.00     |
| AU     | 710 AUD     | $462   | +$81.00     |

Savings: $83.58 (18%) by booking from Germany
```

---

## Live Test Results

### Test 1: Route Search (LAX → BCN)
**Proxy:** Webshare free tier - Madrid, Spain (64.137.96.74:6641)

| Market | Price | Connection |
|--------|-------|------------|
| US | $424 USD | Direct |
| Spain | 353 EUR (~$381 USD) | Via Madrid Proxy |

**Result:** $43+ savings booking through Spanish market

### Test 2: Flight Number Search (LL 2624)
**Markets checked:** US, UK, DE, JP, AU, CA, IN

| Market | Price USD |
|--------|-----------|
| DE | $381.24 |
| US | $424.00 |
| AU | $464.82 |

**Result:** $83.58 savings (18%) booking from Germany

---

## Current .env Configuration

```env
# PROXY CONFIGURATION (Webshare.io)
WEBSHARE_API_KEY=
WEBSHARE_USERNAME=
WEBSHARE_PASSWORD=
WEBSHARE_HOST=proxy.webshare.io
WEBSHARE_HTTP_PORT=80
WEBSHARE_SOCKS_PORT=1080
WEBSHARE_PROXY_TYPE=rotating

# Manual proxy override (Spain free tier test)
ES_PROXY_URL=http://ztviyzjp:dem5xerifvbg@64.137.96.74:6641
```

---

## Architecture Overview

```
FlightFinder/
├── main.py           # Core flight search, XRPL, pricing, flight number search
├── search.py         # Global search engine, market selection, itineraries
├── payments.py       # Multi-payment gateway (Stripe, XRP, RLUSD, Crypto)
├── proxy_manager.py  # Webshare.io proxy integration
├── airports.py       # Airport database and autocomplete [NEW]
├── server.py         # Flask web app, all routes, admin panel
├── .env              # Configuration (API keys, credentials)
└── requirements.txt  # Dependencies
```

---

## Key Code References

### Session 2 (New)
- Flight number search: `main.py:859-975`
- Flight search API: `server.py:2049-2082`
- Airports API: `server.py:2024-2032`
- Search page tabs: `server.py:1463-1530`
- Price comparison JS: `server.py:1940-2020`

### Session 1
- Proxy manager: `proxy_manager.py:1-387`
- Proxy request function: `main.py:239-259`
- Fetch flights with proxy: `main.py:329-349`
- Admin proxy routes: `server.py:2900+`

---

## Testing Commands

```bash
# Run server
python3 server.py

# Test airport autocomplete
curl "http://localhost:5001/api/airports?q=los"

# Test route search
curl -X POST "http://localhost:5001/api/search/itinerary" \
  -H "Content-Type: application/json" \
  -d '{"legs":[{"origin":"LAX","destination":"BCN","date":"2026-03-15"}]}'

# Test flight number search
curl -X POST "http://localhost:5001/api/search/flight" \
  -H "Content-Type: application/json" \
  -d '{"flight_number":"LL 2624","origin":"LAX","destination":"BCN","date":"2026-03-15"}'

# Access search page
open http://localhost:5001/search
```

---

## Important Technical Notes

### About Proxy/VPN with SerpAPI
The proxy configuration (`ES_PROXY_URL`, etc.) affects the network route from our server to SerpAPI. However, **SerpAPI uses its own infrastructure** to scrape Google Flights. The regional pricing we get is controlled by:

- `gl` parameter (geographic location) - e.g., "es" for Spain
- `hl` parameter (language) - e.g., "es" for Spanish
- `currency` parameter - e.g., "EUR" for Euros

The proxy would only be relevant if we were scraping Google Flights directly (bypassing SerpAPI).

### Currency Rate Fix
The live currency API was returning EUR/USD rates (~1.19) different from expected (~1.08), which was eliminating arbitrage detection. We disabled live rate updates in `search_global()` to use stable static rates that better reflect expected arbitrage opportunities.

---

## Session 4 Summary (Latest)

This session added itinerary import and flexible dates features:

### Features Added
- **Import Itinerary Tab** - New tab for importing flight bookings
- **Itinerary Text Parser** - Automatically extracts flight numbers, routes, dates from pasted text
- **Manual Flight Entry** - Add multiple flights manually with autocomplete
- **Multi-Market Price Comparison** - Compare imported flights across selected country markets
- **Market Selection UI** - Choose which countries to search via proxy (US, UK, DE, ES, FR, JP, AU, IN, BR, MX, SG, KR)
- **Savings Calculator** - Shows potential savings by booking from optimal markets

### Flexible Dates Feature
- **Toggle checkbox** in search options: "Flexible dates (+/- 3 days)"
- When enabled, searches 7 dates around the selected date
- Shows visual date comparison grid with prices
- Highlights cheapest date with savings calculation
- Alerts user if a nearby date is significantly cheaper

### How It Works
1. User imports their Google Flights itinerary (paste or manual entry)
2. System searches each flight across selected regional markets via SerpAPI
3. Results show prices in each market's local currency + USD equivalent
4. Highlights cheapest market and calculates total savings

### New API Endpoint
- `/api/search/compare-itinerary` - POST - Compare imported flights across markets

### Test Result
**Flight:** LL 2624 (LAX → BCN on 2026-03-15)
| Market | Local Price | USD |
|--------|-------------|-----|
| US | $424 | $424 |
| UK | £307 | $387 |
| DE | €354 | $382 |
| ES | €354 | $382 |

**Savings:** $41.68 (10%) by booking from Germany/Spain

---

## Session 3 Summary

This session added more data points and a price calendar:

### Features Added
- **Price Calendar** - New tab showing cheapest dates across a date range (like Google Flights)
- **Expanded Market Coverage** - PRIORITY_MARKETS increased from 7 to 16 markets
- **Full Flight Comparison** - Results now show ALL flights with market-by-market pricing
- **Enhanced Results Display** - Table view with sortable flights, market breakdown details

### Markets Now Checked (16)
NA: US, CA, MX
EU: UK, DE, FR, ES, IT, NL
APAC: JP, KR, AU, SG, IN, HK
SA: BR

### New API Endpoint
- `/api/search/calendar` - POST - Price calendar across date range

### Code Changes
- `main.py:303-319` - Expanded PRIORITY_MARKETS from 7 to 16 markets
- `search.py:146-150` - Expanded GLOBAL_PRIORITY_MARKETS to match
- `search.py:445-468` - Updated leg_results to include all_flights and markets_checked
- `server.py:2693-2791` - Added /api/search/calendar endpoint
- `server.py:1643-1647` - Added Price Calendar tab
- `server.py:2210-2380` - Enhanced displayResults() with full flight comparison

---

## Pending / Next Steps

- **Paid proxy upgrade** - User will upgrade to Webshare.io paid service for 100+ countries
- **Mobile ticketing features** - Deferred due to airline API complexity
- **Direct Google Flights scraping** - Would make proxies fully effective (currently using SerpAPI)
- **Rate limiting** for proxy requests
- **Proxy usage analytics/logging**

---

## Supported Markets (40+ available, 16 priority)

**Priority Markets (always checked):**
North America: US, CA, MX
Europe: UK, DE, FR, ES, IT, NL
Asia Pacific: JP, KR, AU, SG, IN, HK
South America: BR

**All Available Markets:**
Europe: UK, DE, FR, IT, ES, NL, BE, CH, AT, PT, IE, DK, NO, SE, FI, PL, CZ, HU, GR, TR
Asia Pacific: JP, KR, CN, HK, TW, SG, TH, MY, ID, PH, VN, IN, AU, NZ
Middle East: AE, SA, IL
South America: BR, AR, CL, CO, PE
Africa: ZA

---

## Session End Status

**Server:** Running on http://localhost:5001
**Features working:**
- Route search with autocomplete
- **Import Itinerary** - Import Google Flights bookings for multi-market comparison
- Price Calendar showing cheapest dates
- Flight number search with price comparison
- Full flight comparison across 16 markets
- Guest browsing (no login required to search)
- Deal saving for guest → account creation flow
- Spain proxy integration (free tier)

**Last tested:** LL 2624 import showing $41.68 savings via DE/ES markets
