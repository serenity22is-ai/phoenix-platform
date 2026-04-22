#!/usr/bin/env python3
"""Lufthansa API capture v46 — Correct body with 'itineraries' field.

v45 breakthrough: Empty body error revealed source.parameter="/itineraries".
JS analysis: itinerary items have originLocationCode, destinationLocationCode.
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
    print("[v46] Connecting...")
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
            const d = JSON.parse(sessionStorage.getItem('gateway-auth-tokens'));
            for (const v of Object.values(d)) if (v.token) return v.token;
        } catch(e) {}
        const r = await fetch('https://api-shop.lufthansa.com/v1/oauth2/token', {
            method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'client_id=k7zpj4s6k2qbrr4xhrzqa7yn&client_secret=rVXq%2305&fact=%7B%7D&grant_type=client_credentials'
        });
        return (await r.json()).access_token;
    }""")
    ama_ref = await page.evaluate("() => sessionStorage.getItem('Ama-Client-Ref')")
    print(f"[v46] Token: {'OK' if token else 'FAIL'}")

    # --- First: search the JS for itinerary field details ---
    print("\n[v46] ===== SEARCHING JS FOR ITINERARY FIELDS =====")
    itinerary_fields = await page.evaluate("""async () => {
        const resp = await fetch('/statics/applications/booking/dist/28.4.0/main.4ade5f225e73e2b4.js');
        const text = await resp.text();
        const results = {};

        // Find what fields an itinerary has
        // Look for object constructions near "itineraries"
        const itinRefs = [];
        let pos = 0;
        while (itinRefs.length < 15) {
            const idx = text.indexOf('itinerar', pos);
            if (idx === -1) break;
            itinRefs.push(text.substring(Math.max(0, idx - 100), idx + 200));
            pos = idx + 10;
        }
        results.itinerary_contexts = itinRefs;

        // Look for date field patterns near search/itinerary
        const datePatterns = text.match(/departur[eE][A-Za-z]*["':][^;]{0,100}/g) || [];
        results.departure_fields = [...new Set(datePatterns)].slice(0, 10);

        // Look for how the search request is constructed
        // Find "itineraries:" as a property assignment
        const itinAssign = [];
        pos = 0;
        while (itinAssign.length < 5) {
            const idx = text.indexOf('itineraries:', pos);
            if (idx === -1) break;
            itinAssign.push(text.substring(Math.max(0, idx - 200), idx + 500));
            pos = idx + 1;
        }
        results.itineraries_assignments = itinAssign;

        // Find traveler/passenger field construction
        const travelerAssign = [];
        pos = 0;
        while (travelerAssign.length < 5) {
            const idx = text.indexOf('travelers:', pos);
            if (idx === -1) break;
            travelerAssign.push(text.substring(Math.max(0, idx - 100), idx + 300));
            pos = idx + 1;
        }
        results.travelers_assignments = travelerAssign;

        return results;
    }""")

    for key, val in itinerary_fields.items():
        print(f"\n  [{key}]:")
        if isinstance(val, list):
            for i, v in enumerate(val):
                print(f"    [{i}] {str(v)[:250]}")

    # --- Try body variations with itineraries ---
    print("\n\n[v46] ===== BODY VARIATIONS WITH 'itineraries' =====")

    bodies = [
        # 1. itineraries with originLocationCode/destinationLocationCode
        ("itin_location_codes", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC", "departureDate": "2026-05-21"},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK", "departureDate": "2026-05-28"}
            ],
            "travelers": [{"id": "ADT1", "ptc": "ADT"}],
            "commercialFareFamilies": []
        }),

        # 2. itineraries with departureDatetime
        ("itin_datetime", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC", "departureDatetime": "2026-05-21"},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK", "departureDatetime": "2026-05-28"}
            ],
            "travelers": [{"id": "ADT1", "ptc": "ADT"}],
        }),

        # 3. Just itineraries (no travelers)
        ("itin_only", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC", "departureDate": "2026-05-21"},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK", "departureDate": "2026-05-28"}
            ]
        }),

        # 4. itineraries with origin/destination as objects
        ("itin_objects", {
            "itineraries": [
                {"origin": {"code": "JFK"}, "destination": {"code": "MUC"}, "departureDate": "2026-05-21"},
                {"origin": {"code": "MUC"}, "destination": {"code": "JFK"}, "departureDate": "2026-05-28"}
            ],
            "travelers": [{"id": "1", "ptc": "ADT"}],
        }),

        # 5. itineraries with date as nested object
        ("itin_date_obj", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTimeRange": {"date": "2026-05-21"}},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTimeRange": {"date": "2026-05-28"}}
            ],
            "travelers": [{"id": "1", "travelerType": "ADULT"}],
        }),

        # 6. itineraries with type field
        ("itin_with_type", {
            "type": "ROUND_TRIP",
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC", "departureDate": "2026-05-21"},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK", "departureDate": "2026-05-28"}
            ],
            "travelers": [{"id": "1", "ptc": "ADT"}],
            "cabin": "ECONOMY",
        }),

        # 7. itineraries with just codes and travelDate
        ("itin_travelDate", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC", "travelDate": "2026-05-21"},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK", "travelDate": "2026-05-28"}
            ],
            "travelers": [{"id": "1", "ptc": "ADT"}],
        }),

        # 8. Minimal: just itineraries array of simple objects
        ("itin_minimal", {
            "itineraries": [
                {"origin": "JFK", "destination": "MUC", "date": "2026-05-21"},
                {"origin": "MUC", "destination": "JFK", "date": "2026-05-28"}
            ]
        }),

        # 9. itineraries with airport code fields
        ("itin_airport", {
            "itineraries": [
                {"departureAirportCode": "JFK", "arrivalAirportCode": "MUC", "departureDate": "2026-05-21"},
                {"departureAirportCode": "MUC", "arrivalAirportCode": "JFK", "departureDate": "2026-05-28"}
            ],
            "travelers": [{"ptc": "ADT"}],
        }),

        # 10. itineraries matching SPA's store shape more closely
        ("itin_store_shape", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDate": "2026-05-21", "id": "1"},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDate": "2026-05-28", "id": "2"}
            ],
            "travelers": [{"id": "1", "ptc": "ADT"}],
            "commercialFareFamilies": [],
            "cabin": "ECONOMY",
        }),
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
                    body: JSON.stringify(body),
                });
                const text = await resp.text();
                results.push({
                    name, status: resp.status,
                    ct: resp.headers.get('content-type'),
                    length: text.length,
                    response: text.substring(0, 2000),
                });
            } catch(e) {
                results.push({name, error: e.message});
            }
        }
        return results;
    }""", {"token": token, "amaRef": ama_ref, "url": SEARCH_URL, "bodies": bodies})

    for r in body_results:
        status = r.get('status', 'ERR')
        resp = r.get('response', '')
        # Highlight non-400 responses or different error messages
        is_promising = status != 400 or 'Unexpected attribute' not in resp
        marker = ' <<<' if is_promising else ''
        print(f"  [{r['name']}] → {status}{marker}")
        print(f"    {resp[:200]}")
        if r.get('error'):
            print(f"    ERROR: {r['error']}")

    # --- Also try GET endpoint ---
    print("\n\n[v46] ===== TRYING GET /v1/one-booking/search/air-offers =====")
    get_result = await page.evaluate("""async (args) => {
        const {token, amaRef} = args;
        const params = new URLSearchParams({
            type: 'ROUND_TRIP',
            origin: 'JFK',
            destination: 'MUC',
            departureDate: '2026-05-21',
            returnDate: '2026-05-28',
            adults: '1',
            cabin: 'ECONOMY',
        });
        const url = 'https://api-shop.lufthansa.com/v1/one-booking/search/air-offers?' + params.toString();
        try {
            const resp = await fetch(url, {
                headers: {
                    'Authorization': 'Bearer ' + token,
                    'Accept': 'application/json',
                    'Ama-Client-Ref': amaRef || '',
                },
            });
            const text = await resp.text();
            return {status: resp.status, ct: resp.headers.get('content-type'), response: text.substring(0, 2000)};
        } catch(e) {
            return {error: e.message};
        }
    }""", {"token": token, "amaRef": ama_ref})
    print(f"  GET → {get_result.get('status', 'ERR')}")
    print(f"    {get_result.get('response', get_result.get('error', ''))[:300]}")

    # --- Save ---
    output = {
        "version": "v46",
        "endpoint": SEARCH_URL,
        "itinerary_fields": itinerary_fields,
        "body_results": body_results,
        "get_result": get_result,
    }
    out_path = CAPTURE_DIR / "lufthansa_v46_2026-04-21.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n[v46] Saved to {out_path}")

    await browser.close()
    await pw.stop()
    print("[v46] Done.")


if __name__ == "__main__":
    asyncio.run(main())
