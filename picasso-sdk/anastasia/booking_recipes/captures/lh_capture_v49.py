#!/usr/bin/env python3
"""Lufthansa API capture v49 — Use /air-bounds endpoint (the SPA's actual search).

v48 findings:
  - /air-bounds → 400 "Invalid itinerary request for construction mode search"
    with source.parameter: "itinerary.isRequestedBound"
  - /air-calendars → 400 "Missing commercial fare family"
  - /air-offers → "resource not supported" (blocked)

Strategy: Fix the air-bounds body with isRequestedBound field.
"""

import asyncio
import json
from pathlib import Path

CDP_URL = "wss://brd-customer-hl_890ca773-zone-scraping_browser1:xy22gst47vzm@brd.superproxy.io:9222"
CAPTURE_DIR = Path(__file__).parent


async def main():
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    print("[v49] Connecting...")
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    page = await browser.new_page()

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
    print(f"[v49] Token: {'OK' if token else 'FAIL'}")

    # --- Step 1: Search JS for air-bounds body construction ---
    print("\n[v49] ===== SEARCHING JS FOR AIR-BOUNDS BODY =====")
    bounds_info = await page.evaluate("""async () => {
        const resp = await fetch('/statics/applications/booking/dist/28.4.0/main.4ade5f225e73e2b4.js');
        const text = await resp.text();
        const results = {};

        // Find "airBoundsShopping" context
        const refs = [];
        let pos = 0;
        while (refs.length < 10) {
            const idx = text.indexOf('airBoundsShopping', pos);
            if (idx === -1) break;
            refs.push(text.substring(Math.max(0, idx - 300), idx + 300));
            pos = idx + 1;
        }
        results.airBoundsShopping = refs;

        // Find "isRequestedBound" usage
        const brRefs = [];
        pos = 0;
        while (brRefs.length < 10) {
            const idx = text.indexOf('isRequestedBound', pos);
            if (idx === -1) break;
            brRefs.push(text.substring(Math.max(0, idx - 200), idx + 200));
            pos = idx + 1;
        }
        results.isRequestedBound = brRefs;

        // Find how the bounds search body is built
        const boundsSearch = [];
        pos = 0;
        while (boundsSearch.length < 5) {
            const idx = text.indexOf('airBoundsSearch', pos);
            if (idx === -1) break;
            boundsSearch.push(text.substring(Math.max(0, idx - 200), idx + 400));
            pos = idx + 1;
        }
        results.airBoundsSearch = boundsSearch;

        // Find "constructionMode" or "construction" references
        const constrRefs = [];
        pos = 0;
        while (constrRefs.length < 5) {
            const idx = text.indexOf('constructionMode', pos);
            if (idx === -1) break;
            constrRefs.push(text.substring(Math.max(0, idx - 200), idx + 200));
            pos = idx + 1;
        }
        results.constructionMode = constrRefs;

        return results;
    }""")

    for key, val in bounds_info.items():
        print(f"\n  [{key}]:")
        if isinstance(val, list):
            for i, v in enumerate(val[:5]):
                print(f"    [{i}] {str(v)[:250]}")

    # --- Step 2: Try air-bounds with various body formats ---
    print("\n\n[v49] ===== TESTING AIR-BOUNDS BODY VARIATIONS =====")
    bounds_url = "https://api-shop.lufthansa.com/v1/one-booking/search/air-bounds"

    bodies = [
        # With isRequestedBound: true on first itinerary
        ("req_bound_first", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTime": "2026-05-28"}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}]
        }),

        # With isRequestedBound on all itineraries
        ("req_bound_all", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTime": "2026-05-28", "isRequestedBound": True}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}]
        }),

        # With isRequestedBound false on second
        ("req_bound_mixed", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTime": "2026-05-28", "isRequestedBound": False}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}]
        }),

        # With commercialFareFamilies
        ("with_cff", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTime": "2026-05-28", "isRequestedBound": True}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}],
            "commercialFareFamilies": []
        }),

        # With cabin and searchPreferences
        ("full_search", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTime": "2026-05-28", "isRequestedBound": True}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}],
            "commercialFareFamilies": [],
            "searchPreferences": {}
        }),

        # One-way search
        ("one_way", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}]
        }),

        # With id field on itineraries
        ("with_ids", {
            "itineraries": [
                {"id": "1", "originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True},
                {"id": "2", "originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTime": "2026-05-28", "isRequestedBound": True}
            ],
            "travelers": [{"id": "1", "passengerTypeCode": "ADT"}]
        }),

        # Matching the NGRX store shape more exactly
        ("ngrx_shape", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTime": "2026-05-28", "isRequestedBound": False}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}],
            "commercialFareFamilies": [],
        }),
    ]

    bounds_results = await page.evaluate("""async (args) => {
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
                    response: text.substring(0, 5000),
                    is_success: resp.status === 200,
                });
            } catch(e) {
                results.push({name, error: e.message});
            }
        }
        return results;
    }""", {"token": token, "amaRef": ama_ref, "url": bounds_url, "bodies": bodies})

    for r in bounds_results:
        status = r.get('status', 'ERR')
        is_success = r.get('is_success', False)
        length = r.get('length', 0)
        marker = ' <<< SUCCESS!' if is_success else (' <<<' if status not in (400, 596) else '')
        print(f"  [{r['name']}] → {status} ({length}b){marker}")
        resp = r.get('response', '')
        if is_success:
            print(f"    RESPONSE (first 500): {resp[:500]}")
        else:
            print(f"    {resp[:300]}")
        if r.get('error'):
            print(f"    ERROR: {r['error']}")

    # If any succeeded, save the full response
    for r in bounds_results:
        if r.get('is_success'):
            print(f"\n\n[v49] ===== SUCCESS! Full response for [{r['name']}] =====")
            print(r.get('response', '')[:3000])

    # --- Save ---
    output = {
        "version": "v49",
        "bounds_url": bounds_url,
        "bounds_info": bounds_info,
        "bounds_results": bounds_results,
    }
    out_path = CAPTURE_DIR / "lufthansa_v49_2026-04-21.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n[v49] Saved to {out_path}")

    await browser.close()
    await pw.stop()
    print("[v49] Done.")


if __name__ == "__main__":
    asyncio.run(main())
