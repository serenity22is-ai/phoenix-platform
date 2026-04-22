#!/usr/bin/env python3
"""Lufthansa API capture v47 — Correct field names: departureDateTime (capital T), passengerTypeCode.

GET told us: Missing required parameter 'departureDateTime'
JS told us: itinerary has originLocationCode, destinationLocationCode, departureDateTime
JS told us: travelers have passengerTypeCode: "ADT"
"""

import asyncio
import json
from pathlib import Path

CDP_URL = "wss://brd-customer-hl_890ca773-zone-scraping_browser1:xy22gst47vzm@brd.superproxy.io:9222"
CAPTURE_DIR = Path(__file__).parent

SEARCH_URL = "https://api-shop.lufthansa.com/v1/one-booking/search/air-offers"
GET_SEARCH_URL = "https://api-shop.lufthansa.com/v1/one-booking/search/air-offers"


async def main():
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    print("[v47] Connecting...")
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
    print(f"[v47] Token: {'OK' if token else 'FAIL'}")

    # --- Test 1: GET with proper query params ---
    print("\n[v47] ===== GET WITH departureDateTime =====")
    get_results = await page.evaluate("""async (args) => {
        const {token, amaRef} = args;
        const results = [];

        // Build various GET query params
        const paramSets = [
            // Minimal: just departureDateTime
            {name: 'minimal', params: {departureDateTime1: '2026-05-21', departureDateTime2: '2026-05-28'}},
            // With origin/dest
            {name: 'with_locations', params: {
                originLocationCode1: 'JFK', destinationLocationCode1: 'MUC', departureDateTime1: '2026-05-21',
                originLocationCode2: 'MUC', destinationLocationCode2: 'JFK', departureDateTime2: '2026-05-28',
            }},
            // Without numbered suffix
            {name: 'no_suffix', params: {
                originLocationCode: 'JFK', destinationLocationCode: 'MUC', departureDateTime: '2026-05-21',
            }},
            // Array style
            {name: 'array_style', params: {
                'originLocationCode[]': 'JFK', 'destinationLocationCode[]': 'MUC', 'departureDateTime[]': '2026-05-21',
            }},
            // With cabin/pax
            {name: 'full', params: {
                originLocationCode1: 'JFK', destinationLocationCode1: 'MUC', departureDateTime1: '2026-05-21',
                originLocationCode2: 'MUC', destinationLocationCode2: 'JFK', departureDateTime2: '2026-05-28',
                nbAdt: '1', cabin: 'ECONOMY', tripType: 'R',
            }},
        ];

        for (const {name, params} of paramSets) {
            const qs = new URLSearchParams(params);
            const url = 'https://api-shop.lufthansa.com/v1/one-booking/search/air-offers?' + qs.toString();
            try {
                const resp = await fetch(url, {
                    headers: {
                        'Authorization': 'Bearer ' + token,
                        'Accept': 'application/json',
                        'Ama-Client-Ref': amaRef || '',
                    },
                });
                const text = await resp.text();
                results.push({name, status: resp.status, response: text.substring(0, 2000)});
            } catch(e) {
                results.push({name, error: e.message});
            }
        }
        return results;
    }""", {"token": token, "amaRef": ama_ref})

    for r in get_results:
        is_good = r.get('status', 0) not in (400, 596)
        marker = ' <<<' if is_good else ''
        print(f"  GET [{r['name']}] → {r.get('status', 'ERR')}{marker}")
        print(f"    {r.get('response', r.get('error', ''))[:200]}")

    # --- Test 2: POST with corrected field names ---
    print("\n[v47] ===== POST WITH CORRECTED FIELDS =====")
    post_results = await page.evaluate("""async (args) => {
        const {token, amaRef} = args;
        const url = 'https://api-shop.lufthansa.com/v1/one-booking/search/air-offers';
        const results = [];

        const bodies = [
            // Pure itineraries with departureDateTime
            ['pure_datetime', {
                itineraries: [
                    {originLocationCode: 'JFK', destinationLocationCode: 'MUC', departureDateTime: '2026-05-21'},
                    {originLocationCode: 'MUC', destinationLocationCode: 'JFK', departureDateTime: '2026-05-28'}
                ]
            }],
            // With travelers using passengerTypeCode
            ['with_ptc', {
                itineraries: [
                    {originLocationCode: 'JFK', destinationLocationCode: 'MUC', departureDateTime: '2026-05-21'},
                    {originLocationCode: 'MUC', destinationLocationCode: 'JFK', departureDateTime: '2026-05-28'}
                ],
                travelers: [{passengerTypeCode: 'ADT'}]
            }],
            // With travelers with id
            ['with_id', {
                itineraries: [
                    {originLocationCode: 'JFK', destinationLocationCode: 'MUC', departureDateTime: '2026-05-21'},
                    {originLocationCode: 'MUC', destinationLocationCode: 'JFK', departureDateTime: '2026-05-28'}
                ],
                travelers: [{id: '1', passengerTypeCode: 'ADT'}]
            }],
            // With commercialFareFamilies
            ['with_cff', {
                itineraries: [
                    {originLocationCode: 'JFK', destinationLocationCode: 'MUC', departureDateTime: '2026-05-21'},
                    {originLocationCode: 'MUC', destinationLocationCode: 'JFK', departureDateTime: '2026-05-28'}
                ],
                travelers: [{id: '1', passengerTypeCode: 'ADT'}],
                commercialFareFamilies: []
            }],
            // dateTime as ISO datetime string
            ['iso_datetime', {
                itineraries: [
                    {originLocationCode: 'JFK', destinationLocationCode: 'MUC', departureDateTime: '2026-05-21T00:00:00'},
                    {originLocationCode: 'MUC', destinationLocationCode: 'JFK', departureDateTime: '2026-05-28T00:00:00'}
                ],
                travelers: [{id: '1', passengerTypeCode: 'ADT'}]
            }],
            // nbAdt style from JS
            ['nb_style', {
                itineraries: [
                    {originLocationCode: 'JFK', destinationLocationCode: 'MUC', departureDateTime: '2026-05-21'},
                    {originLocationCode: 'MUC', destinationLocationCode: 'JFK', departureDateTime: '2026-05-28'}
                ],
                nbAdt: 1,
                cabin: 'ECONOMY',
                tripType: 'R',
            }],
            // From the metasearch store shape exactly
            ['metasearch', {
                travelers: [],
                itineraries: [
                    {originLocationCode: 'JFK', destinationLocationCode: 'MUC', departureDateTime: '2026-05-21'},
                    {originLocationCode: 'MUC', destinationLocationCode: 'JFK', departureDateTime: '2026-05-28'}
                ],
                offerPrice: {value: 0, currencyCode: 'USD'},
            }],
            // Try empty travelers array (from metasearch default)
            ['empty_travelers', {
                travelers: [],
                itineraries: [
                    {originLocationCode: 'JFK', destinationLocationCode: 'MUC', departureDateTime: '2026-05-21'},
                    {originLocationCode: 'MUC', destinationLocationCode: 'JFK', departureDateTime: '2026-05-28'}
                ]
            }],
            // Just try with correct ptc travelers
            ['ptc_travelers', {
                itineraries: [
                    {originLocationCode: 'JFK', destinationLocationCode: 'MUC', departureDateTime: '2026-05-21'},
                    {originLocationCode: 'MUC', destinationLocationCode: 'JFK', departureDateTime: '2026-05-28'}
                ],
                travelers: [{passengerTypeCode: 'ADT', id: 'ADT1'}],
                searchPreferences: {},
            }],
        ];

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
                    response: text.substring(0, 2000),
                });
            } catch(e) {
                results.push({name, error: e.message});
            }
        }
        return results;
    }""", {"token": token, "amaRef": ama_ref})

    for r in post_results:
        status = r.get('status', 'ERR')
        resp = r.get('response', '')[:200]
        is_good = status == 200 or (status == 400 and 'Unexpected attribute' not in resp)
        marker = ' <<<' if is_good else ''
        print(f"  POST [{r['name']}] → {status}{marker}")
        print(f"    {resp}")
        if r.get('error'):
            print(f"    ERROR: {r['error']}")

    # --- Test 3: Try the GET endpoint with exact field names from error ---
    print("\n[v47] ===== PROGRESSIVE GET PARAM DISCOVERY =====")
    # Start with just departureDateTime, add params until we stop getting "missing required"
    progressive = await page.evaluate("""async (args) => {
        const {token, amaRef} = args;
        const base = 'https://api-shop.lufthansa.com/v1/one-booking/search/air-offers';
        const results = [];

        const paramSets = [
            // Step 1: just the required param
            {departureDateTime: '2026-05-21'},
            // Step 2: add origin
            {departureDateTime: '2026-05-21', originLocationCode: 'JFK'},
            // Step 3: add destination
            {departureDateTime: '2026-05-21', originLocationCode: 'JFK', destinationLocationCode: 'MUC'},
            // Step 4: add return
            {departureDateTime: '2026-05-21', originLocationCode: 'JFK', destinationLocationCode: 'MUC',
             returnDateTime: '2026-05-28'},
            // Step 5: add pax
            {departureDateTime: '2026-05-21', originLocationCode: 'JFK', destinationLocationCode: 'MUC',
             returnDateTime: '2026-05-28', nbAdt: '1'},
            // Step 6: full from JS hints
            {departureDateTime: '2026-05-21', originLocationCode: 'JFK', destinationLocationCode: 'MUC',
             returnDateTime: '2026-05-28', nbAdt: '1', cabin: 'ECONOMY', tripType: 'R', airline: 'LH'},
            // Step 7: Without airline
            {departureDateTime: '2026-05-21', originLocationCode: 'JFK', destinationLocationCode: 'MUC',
             returnDateTime: '2026-05-28', nbAdt: '1', cabin: 'ECONOMY', tripType: 'R'},
            // Step 8: Date as just date (not datetime)
            {departureDateTime: '2026-05-21', originLocationCode: 'JFK', destinationLocationCode: 'MUC',
             nbAdt: '1'},
        ];

        for (const params of paramSets) {
            const qs = new URLSearchParams(params);
            try {
                const resp = await fetch(base + '?' + qs.toString(), {
                    headers: {
                        'Authorization': 'Bearer ' + token,
                        'Accept': 'application/json',
                        'Ama-Client-Ref': amaRef || '',
                    },
                });
                const text = await resp.text();
                results.push({
                    params: Object.keys(params).join(','),
                    status: resp.status,
                    response: text.substring(0, 1000),
                });
            } catch(e) {
                results.push({params: Object.keys(params).join(','), error: e.message});
            }
        }
        return results;
    }""", {"token": token, "amaRef": ama_ref})

    for r in progressive:
        status = r.get('status', 'ERR')
        is_good = status == 200
        marker = ' <<<' if is_good else ''
        resp = r.get('response', '')[:250]
        print(f"  [{r['params']}] → {status}{marker}")
        print(f"    {resp}")

    # --- Save ---
    output = {
        "version": "v47",
        "get_results": get_results,
        "post_results": post_results,
        "progressive_get": progressive,
    }
    out_path = CAPTURE_DIR / "lufthansa_v47_2026-04-21.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n[v47] Saved to {out_path}")

    await browser.close()
    await pw.stop()
    print("[v47] Done.")


if __name__ == "__main__":
    asyncio.run(main())
