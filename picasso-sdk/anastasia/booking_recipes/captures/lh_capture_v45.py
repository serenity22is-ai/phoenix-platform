#!/usr/bin/env python3
"""Lufthansa API capture v45 — /v1/one-booking/search/air-offers works!

v44 breakthrough: POST /v1/one-booking/search/air-offers returned 400 with
{"errors":[{"code":"04926","detail":"Unexpected attribute"}]}

This means the endpoint EXISTS. We just need the correct request body.
This script:
  1. Searches main.js for advancedAirShopping request body construction
  2. Tries various body format variations against the working endpoint
"""

import asyncio
import json
from pathlib import Path

CDP_URL = "wss://brd-customer-hl_890ca773-zone-scraping_browser1:xy22gst47vzm@brd.superproxy.io:9222"
CAPTURE_DIR = Path(__file__).parent

SEARCH_URL = "https://api-shop.lufthansa.com/v1/one-booking/search/air-offers"


async def main():
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    print("[v45] Connecting to Bright Data CDP...")
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    page = await browser.new_page()

    # Navigate and get token
    await page.goto("https://shop.lufthansa.com/lh/us/en/homepage", timeout=60000, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    try:
        btn = page.locator("#cm-acceptAll")
        if await btn.count() > 0:
            await btn.click(timeout=5000)
            await page.wait_for_timeout(2000)
    except Exception:
        pass
    await page.wait_for_timeout(8000)

    token = await page.evaluate("""async () => {
        try {
            const authData = sessionStorage.getItem('gateway-auth-tokens');
            if (authData) {
                const parsed = JSON.parse(authData);
                for (const v of Object.values(parsed)) {
                    if (v.token) return v.token;
                }
            }
        } catch(e) {}
        const r = await fetch('https://api-shop.lufthansa.com/v1/oauth2/token', {
            method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'client_id=k7zpj4s6k2qbrr4xhrzqa7yn&client_secret=rVXq%2305&fact=%7B%7D&grant_type=client_credentials'
        });
        return (await r.json()).access_token;
    }""")
    print(f"[v45] Token: {'OK' if token else 'FAIL'}")

    ama_ref = await page.evaluate("() => sessionStorage.getItem('Ama-Client-Ref')")
    print(f"[v45] Ama-Client-Ref: {ama_ref}")

    # --- Step 1: Deep search main.js for advancedAirShopping body construction ---
    print("\n[v45] ===== SEARCHING FOR advancedAirShopping REQUEST BODY =====")
    body_search = await page.evaluate("""async () => {
        const resp = await fetch('/statics/applications/booking/dist/28.4.0/main.4ade5f225e73e2b4.js');
        const text = await resp.text();
        const results = {};

        // Find "advancedAirShopping" context
        const advIdx = text.indexOf('advancedAirShopping');
        if (advIdx > -1) {
            results.advancedAirShopping_context = text.substring(Math.max(0, advIdx - 1000), advIdx + 2000);

            // Also get all occurrences
            const all = [];
            let pos = 0;
            while (true) {
                const idx = text.indexOf('advancedAirShopping', pos);
                if (idx === -1 || all.length >= 10) break;
                all.push(text.substring(Math.max(0, idx - 200), idx + 300));
                pos = idx + 1;
            }
            results.all_advancedAirShopping = all;
        }

        // Find "airShopping" context (the GET endpoint)
        const airIdx = text.indexOf('"airShopping"');
        if (airIdx > -1) {
            results.airShopping_context = text.substring(Math.max(0, airIdx - 500), airIdx + 1000);
        }

        // Search for request body field names
        // Amadeus uses: originDestinations, travelers, searchCriteria
        // OneBooking might use: connections, segments, passengers
        const bodyFields = [
            'originDestination', 'travelDate', 'departureDate', 'originLocationCode',
            'destinationLocationCode', 'travelerType', 'searchCriteria',
            'originCode', 'destinationCode', 'segments', 'passengers',
            'airportCode', 'connections', 'itinerary', 'cabin',
            'journeyType', 'tripType', 'flightSegments',
        ];

        results.field_contexts = {};
        for (const field of bodyFields) {
            const idx = text.indexOf('"' + field + '"');
            if (idx > -1) {
                results.field_contexts[field] = text.substring(Math.max(0, idx - 200), idx + 200);
            }
        }

        // Search for the action/effect that triggers the search
        const searchTriggers = text.match(/airOffer[sA-Za-z]*Search[^;]{0,300}/g) || [];
        results.search_triggers = [...new Set(searchTriggers)].slice(0, 10);

        // Find the NGRX action for search
        const ngrxActions = text.match(/createAction\([^)]*search[^)]*\)/gi) || [];
        results.ngrx_search_actions = ngrxActions.slice(0, 5);

        // Find service/effect for search
        const searchService = text.match(/search[A-Za-z]*Service[^;]{0,200}/gi) || [];
        results.search_services = [...new Set(searchService)].slice(0, 10);

        return results;
    }""")

    for key, val in body_search.items():
        print(f"\n  [{key}]:")
        if isinstance(val, list):
            for i, v in enumerate(val):
                print(f"    [{i}] {str(v)[:250]}")
        elif isinstance(val, dict):
            for k2, v2 in val.items():
                print(f"    {k2}: {str(v2)[:200]}")
        elif isinstance(val, str):
            print(f"    {val[:500]}")

    # --- Step 2: Try different body formats ---
    print("\n\n[v45] ===== TRYING BODY VARIATIONS =====")

    bodies = [
        # 1. Empty body
        ("empty", "{}"),

        # 2. Minimal with just required fields
        ("minimal", json.dumps({
            "travelers": [{"id": "ADT1", "ptc": "ADT"}],
        })),

        # 3. OneBooking style connections
        ("connections_v1", json.dumps({
            "itinerary": {
                "connections": [
                    {"departureAirportCode": "JFK", "arrivalAirportCode": "MUC", "departureDate": "2026-05-21"},
                    {"departureAirportCode": "MUC", "arrivalAirportCode": "JFK", "departureDate": "2026-05-28"},
                ],
            },
            "travelers": [{"id": "ADT1", "ptc": "ADT"}],
        })),

        # 4. Simplified connections
        ("connections_v2", json.dumps({
            "connections": [
                {"origin": "JFK", "destination": "MUC", "date": "2026-05-21"},
                {"origin": "MUC", "destination": "JFK", "date": "2026-05-28"},
            ],
            "passengers": [{"type": "ADT", "count": 1}],
        })),

        # 5. IATA NDC standard
        ("ndc_standard", json.dumps({
            "originDestinations": [
                {"id": "1", "originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTimeRange": {"date": "2026-05-21"}},
                {"id": "2", "originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTimeRange": {"date": "2026-05-28"}},
            ],
            "travelers": [{"id": "1", "travelerType": "ADULT"}],
            "searchCriteria": {"maxFlightOffers": 50},
        })),

        # 6. OneBooking segments with origin/destination
        ("segments", json.dumps({
            "segments": [
                {"origin": {"code": "JFK"}, "destination": {"code": "MUC"}, "departureDate": "2026-05-21"},
                {"origin": {"code": "MUC"}, "destination": {"code": "JFK"}, "departureDate": "2026-05-28"},
            ],
            "travelers": [{"id": "1", "passengerTypeCode": "ADT"}],
            "cabin": "ECONOMY",
        })),

        # 7. flightSegments style (from CMS form field names)
        ("flightSegments", json.dumps({
            "flightSegments": [
                {"originCode": "JFK", "destinationCode": "MUC", "travelDatetime": "2026-05-21"},
                {"originCode": "MUC", "destinationCode": "JFK", "travelDatetime": "2026-05-28"},
            ],
            "passengers": {"adults": 1},
        })),

        # 8. Just travelers (to see if error changes)
        ("travelers_only", json.dumps({
            "travelers": [{"id": "1", "passengerTypeCode": "ADT"}],
        })),

        # 9. Try the SPA's hash params as body
        ("hash_params", json.dumps({
            "type": "rt",
            "from": "JFK",
            "to": "MUC",
            "dep": "2026-05-21",
            "ret": "2026-05-28",
            "pax": "a1",
            "cabin": "economy",
        })),

        # 10. Amadeus self-service style
        ("amadeus_self", json.dumps({
            "currencyCode": "USD",
            "originDestinations": [
                {"id": "1", "originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTimeRange": {"date": "2026-05-21", "dateWindow": "I3D"}},
            ],
            "travelers": [{"id": "1", "travelerType": "ADULT"}],
            "sources": ["GDS"],
            "searchCriteria": {
                "maxFlightOffers": 10,
                "flightFilters": {"cabinRestrictions": [{"cabin": "ECONOMY", "coverage": "MOST_SEGMENTS", "originDestinationIds": ["1"]}]},
            },
        })),
    ]

    body_results = await page.evaluate("""async (args) => {
        const {token, amaRef, url, bodies} = args;
        const results = [];

        for (const [name, body] of bodies) {
            try {
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Authorization': 'Bearer ' + token,
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'Ama-Client-Ref': amaRef || '',
                    },
                    body,
                });
                const text = await resp.text();
                results.push({
                    name, status: resp.status,
                    ct: resp.headers.get('content-type'),
                    length: text.length,
                    response: text.substring(0, 1000),
                });
            } catch(e) {
                results.push({name, error: e.message});
            }
        }
        return results;
    }""", {"token": token, "amaRef": ama_ref, "url": SEARCH_URL, "bodies": bodies})

    for r in body_results:
        status = r.get('status', 'ERR')
        resp = r.get('response', '')[:200]
        print(f"  [{r['name']}] → {status} | {r.get('ct', '?')}")
        if resp:
            print(f"    {resp}")
        if r.get('error'):
            print(f"    ERROR: {r['error']}")

    # --- Step 3: If we got useful field info, try refined body ---
    # Check if any response reveals expected format
    for r in body_results:
        if r.get('status') == 200 or (r.get('status') == 400 and 'required' in (r.get('response', '').lower())):
            print(f"\n[v45] PROMISING: [{r['name']}] returned {r['status']}!")
            print(f"  Full response: {r.get('response', '')[:1000]}")

    # --- Save ---
    output = {
        "version": "v45",
        "endpoint": SEARCH_URL,
        "body_search_results": body_search,
        "body_format_tests": body_results,
    }
    out_path = CAPTURE_DIR / "lufthansa_v45_2026-04-21.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n[v45] Saved to {out_path}")

    await browser.close()
    await pw.stop()
    print("[v45] Done.")


if __name__ == "__main__":
    asyncio.run(main())
