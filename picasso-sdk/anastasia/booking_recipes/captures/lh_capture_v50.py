#!/usr/bin/env python3
"""Lufthansa API capture v50 — air-bounds with commercialFareFamilies.

v49 findings:
  - Only ONE itinerary can have isRequestedBound=true
  - Mixed true/false passes bound check but needs commercialFareFamilies
  - JS: DEMALLFPP="E" (Economy), DECALLFPP="B" (Business), etc.
"""

import asyncio
import json
from pathlib import Path

CDP_URL = "wss://brd-customer-hl_890ca773-zone-scraping_browser1:xy22gst47vzm@brd.superproxy.io:9222"
CAPTURE_DIR = Path(__file__).parent


async def main():
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    print("[v50] Connecting...")
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
    print(f"[v50] Token: {'OK' if token else 'FAIL'}")

    # --- First: Find commercialFareFamilies values from JS ---
    print("\n[v50] ===== SEARCHING FOR FARE FAMILY CODES =====")
    ff_info = await page.evaluate("""async () => {
        const resp = await fetch('/statics/applications/booking/dist/28.4.0/main.4ade5f225e73e2b4.js');
        const text = await resp.text();
        const results = {};

        // Find commercialFareFamilies references
        const refs = [];
        let pos = 0;
        while (refs.length < 10) {
            const idx = text.indexOf('commercialFareFamil', pos);
            if (idx === -1) break;
            refs.push(text.substring(Math.max(0, idx - 200), idx + 400));
            pos = idx + 1;
        }
        results.cff_refs = refs;

        // Find DEMALLFPP and similar codes
        const codeRefs = [];
        pos = 0;
        while (codeRefs.length < 5) {
            const idx = text.indexOf('DEMALLFPP', pos);
            if (idx === -1) break;
            codeRefs.push(text.substring(Math.max(0, idx - 100), idx + 300));
            pos = idx + 1;
        }
        results.fare_codes = codeRefs;

        // Find how CFF is constructed for the request
        const reqRefs = [];
        pos = 0;
        while (reqRefs.length < 5) {
            const idx = text.indexOf('FareFamil', pos);
            if (idx === -1) break;
            reqRefs.push(text.substring(Math.max(0, idx - 100), idx + 200));
            pos = idx + 1;
        }
        results.fare_family_refs = reqRefs.slice(0, 5);

        return results;
    }""")

    for key, val in ff_info.items():
        print(f"\n  [{key}]:")
        for i, v in enumerate(val[:5]):
            print(f"    [{i}] {str(v)[:250]}")

    # --- Try air-bounds with various CFF formats ---
    print("\n\n[v50] ===== AIR-BOUNDS WITH FARE FAMILIES =====")
    bounds_url = "https://api-shop.lufthansa.com/v1/one-booking/search/air-bounds"

    bodies = [
        # CFF as array of strings
        ("cff_strings", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTime": "2026-05-28", "isRequestedBound": False}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}],
            "commercialFareFamilies": ["DEMALLFPP"]
        }),

        # CFF as array of objects
        ("cff_objects", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTime": "2026-05-28", "isRequestedBound": False}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}],
            "commercialFareFamilies": [{"code": "DEMALLFPP"}]
        }),

        # CFF with cabin letter
        ("cff_cabin", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTime": "2026-05-28", "isRequestedBound": False}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}],
            "commercialFareFamilies": ["E"]
        }),

        # CFF with all economy codes
        ("cff_all_economy", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTime": "2026-05-28", "isRequestedBound": False}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}],
            "commercialFareFamilies": ["DEMALLFPP", "DEPALLFPP", "DECALLFPP", "DEFALLFPP"]
        }),

        # CFF with cabin inside itinerary
        ("cff_in_itin", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True, "cabin": "ECONOMY"},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTime": "2026-05-28", "isRequestedBound": False}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}],
            "commercialFareFamilies": ["DEMALLFPP"]
        }),

        # One-way with CFF
        ("one_way_cff", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}],
            "commercialFareFamilies": ["DEMALLFPP"]
        }),

        # With searchPreferences
        ("with_prefs", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTime": "2026-05-28", "isRequestedBound": False}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}],
            "commercialFareFamilies": ["DEMALLFPP"],
            "searchPreferences": {}
        }),

        # With ECONOMY as string
        ("cff_economy_string", {
            "itineraries": [
                {"originLocationCode": "JFK", "destinationLocationCode": "MUC",
                 "departureDateTime": "2026-05-21", "isRequestedBound": True},
                {"originLocationCode": "MUC", "destinationLocationCode": "JFK",
                 "departureDateTime": "2026-05-28", "isRequestedBound": False}
            ],
            "travelers": [{"passengerTypeCode": "ADT"}],
            "commercialFareFamilies": ["ECONOMY"]
        }),
    ]

    results = await page.evaluate("""async (args) => {
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

    for r in results:
        status = r.get('status', 'ERR')
        is_success = r.get('is_success', False)
        length = r.get('length', 0)
        marker = ' <<< SUCCESS!' if is_success else (' <<< NEW ERROR' if '39236' not in r.get('response', '') and '38411' not in r.get('response', '') and '04926' not in r.get('response', '') else '')
        print(f"  [{r['name']}] → {status} ({length}b){marker}")
        resp = r.get('response', r.get('error', ''))
        if is_success:
            print(f"    FIRST 1000: {resp[:1000]}")
        else:
            print(f"    {resp[:300]}")

    # --- Save ---
    output = {
        "version": "v50",
        "ff_info": ff_info,
        "bounds_results": results,
    }
    out_path = CAPTURE_DIR / "lufthansa_v50_2026-04-21.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n[v50] Saved to {out_path}")

    await browser.close()
    await pw.stop()
    print("[v50] Done.")


if __name__ == "__main__":
    asyncio.run(main())
