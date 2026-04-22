#!/usr/bin/env python3
"""Lufthansa API capture v48 — Fix "AIR-OFFERS RESOURCE NOT SUPPORTED" error.

Correct endpoint: POST /v1/one-booking/search/air-offers
Correct body: {itineraries: [{originLocationCode, destinationLocationCode, departureDateTime}], travelers: [{passengerTypeCode}]}

Blocker: "AIR-OFFERS RESOURCE NOT SUPPORTED for current configuration"
Hypothesis: The token's `fact` parameter needs search config, OR we need contextData headers,
OR the token obtained with fact={} doesn't have search permissions.
"""

import asyncio
import json
from pathlib import Path
from urllib.parse import quote

CDP_URL = "wss://brd-customer-hl_890ca773-zone-scraping_browser1:xy22gst47vzm@brd.superproxy.io:9222"
CAPTURE_DIR = Path(__file__).parent

SEARCH_URL = "https://api-shop.lufthansa.com/v1/one-booking/search/air-offers"


async def main():
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    print("[v48] Connecting...")
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

    # Get Ama-Client-Ref
    ama_ref = await page.evaluate("() => sessionStorage.getItem('Ama-Client-Ref')")
    print(f"[v48] Ama-Client-Ref: {ama_ref}")

    # --- Step 1: Search JS for how fact is constructed ---
    print("\n[v48] ===== SEARCHING JS FOR FACT CONSTRUCTION =====")
    fact_info = await page.evaluate("""async () => {
        const resp = await fetch('/statics/applications/booking/dist/28.4.0/main.4ade5f225e73e2b4.js');
        const text = await resp.text();
        const results = {};

        // Find all 'fact' references near token/oauth
        const factRefs = [];
        let pos = 0;
        while (factRefs.length < 10) {
            const idx = text.indexOf('"fact"', pos);
            if (idx === -1) break;
            factRefs.push(text.substring(Math.max(0, idx - 200), idx + 300));
            pos = idx + 1;
        }
        results.fact_refs = factRefs;

        // Find keyValuePairs construction
        const kvpRefs = [];
        pos = 0;
        while (kvpRefs.length < 5) {
            const idx = text.indexOf('keyValuePairs', pos);
            if (idx === -1) break;
            kvpRefs.push(text.substring(Math.max(0, idx - 200), idx + 300));
            pos = idx + 1;
        }
        results.kvp_refs = kvpRefs;

        // Find officeId construction/manipulation
        const officeRefs = [];
        pos = 0;
        while (officeRefs.length < 5) {
            const idx = text.indexOf('officeId', pos);
            if (idx === -1) break;
            officeRefs.push(text.substring(Math.max(0, idx - 100), idx + 200));
            pos = idx + 1;
        }
        results.office_refs = officeRefs;

        // Find contextData construction
        const ctxRefs = [];
        pos = 0;
        while (ctxRefs.length < 5) {
            const idx = text.indexOf('contextData', pos);
            if (idx === -1) break;
            ctxRefs.push(text.substring(Math.max(0, idx - 200), idx + 300));
            pos = idx + 1;
        }
        results.context_refs = ctxRefs;

        // Find error code 38601 context (resource not supported)
        const errIdx = text.indexOf('38601');
        if (errIdx > -1) {
            results.error_38601_context = text.substring(Math.max(0, errIdx - 500), errIdx + 500);
        }

        // Find what triggers the search (the effect/action)
        const searchEffects = text.match(/advancedAirShopping[^;]{0,500}/g) || [];
        results.search_effects = [...new Set(searchEffects)].slice(0, 5);

        return results;
    }""")

    for key, val in fact_info.items():
        print(f"\n  [{key}]:")
        if isinstance(val, list):
            for i, v in enumerate(val):
                print(f"    [{i}] {str(v)[:250]}")
        elif isinstance(val, str):
            print(f"    {val[:500]}")

    # --- Step 2: Try tokens with different fact values ---
    print("\n\n[v48] ===== TESTING DIFFERENT TOKEN FACTS =====")

    search_body = json.dumps({
        "itineraries": [
            {"originLocationCode": "JFK", "destinationLocationCode": "MUC", "departureDateTime": "2026-05-21"},
            {"originLocationCode": "MUC", "destinationLocationCode": "JFK", "departureDateTime": "2026-05-28"}
        ],
        "travelers": [{"passengerTypeCode": "ADT"}]
    })

    fact_variants = [
        # No fact at all
        ("no_fact", "client_id=k7zpj4s6k2qbrr4xhrzqa7yn&client_secret=rVXq%2305&grant_type=client_credentials"),

        # Empty fact
        ("empty_fact", "client_id=k7zpj4s6k2qbrr4xhrzqa7yn&client_secret=rVXq%2305&fact=%7B%7D&grant_type=client_credentials"),

        # Fact with market/locale
        ("market_fact", "client_id=k7zpj4s6k2qbrr4xhrzqa7yn&client_secret=rVXq%2305&fact=" +
         quote(json.dumps({"keyValuePairs": [{"key": "market", "value": "US"}, {"key": "language", "value": "en"}]})) +
         "&grant_type=client_credentials"),

        # Fact with country
        ("country_fact", "client_id=k7zpj4s6k2qbrr4xhrzqa7yn&client_secret=rVXq%2305&fact=" +
         quote(json.dumps({"keyValuePairs": [{"key": "countryOfResidence", "value": "US"}, {"key": "pointOfSale", "value": "US"}]})) +
         "&grant_type=client_credentials"),

        # Fact with all known fields
        ("full_fact", "client_id=k7zpj4s6k2qbrr4xhrzqa7yn&client_secret=rVXq%2305&fact=" +
         quote(json.dumps({
             "keyValuePairs": [
                 {"key": "market", "value": "US"},
                 {"key": "language", "value": "en"},
                 {"key": "countryOfResidence", "value": "US"},
                 {"key": "pointOfSale", "value": "US"},
                 {"key": "currency", "value": "USD"},
             ]
         })) + "&grant_type=client_credentials"),

        # With context parameter
        ("with_context", "client_id=k7zpj4s6k2qbrr4xhrzqa7yn&client_secret=rVXq%2305&fact=%7B%7D" +
         "&context=" + quote(json.dumps({"officeId": "FRALH08BC"})) +
         "&grant_type=client_credentials"),

        # With contextData
        ("with_contextData", "client_id=k7zpj4s6k2qbrr4xhrzqa7yn&client_secret=rVXq%2305&fact=%7B%7D" +
         "&contextData=" + quote(json.dumps({"officeId": "FRALH08BC", "isForcedRefresh": False})) +
         "&grant_type=client_credentials"),
    ]

    token_results = await page.evaluate("""async (args) => {
        const {factVariants, searchBody, amaRef, searchUrl} = args;
        const results = [];

        for (const [name, tokenBody] of factVariants) {
            try {
                // Get token with this fact
                const tokenResp = await fetch('https://api-shop.lufthansa.com/v1/oauth2/token', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: tokenBody,
                });
                const tokenData = await tokenResp.json();

                if (!tokenData.access_token) {
                    results.push({name, token_status: tokenResp.status, token_error: JSON.stringify(tokenData).substring(0, 200)});
                    continue;
                }

                // Try search with this token
                const searchResp = await fetch(searchUrl, {
                    method: 'POST',
                    headers: {
                        'Authorization': 'Bearer ' + tokenData.access_token,
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'Ama-Client-Ref': amaRef || '',
                    },
                    body: searchBody,
                });
                const searchText = await searchResp.text();

                results.push({
                    name,
                    token_status: tokenResp.status,
                    search_status: searchResp.status,
                    search_response: searchText.substring(0, 1000),
                    is_success: searchResp.status === 200,
                });
            } catch(e) {
                results.push({name, error: e.message});
            }
        }
        return results;
    }""", {
        "factVariants": fact_variants,
        "searchBody": search_body,
        "amaRef": ama_ref,
        "searchUrl": SEARCH_URL,
    })

    for r in token_results:
        status = r.get('search_status', 'ERR')
        is_success = r.get('is_success', False)
        marker = ' <<< SUCCESS!' if is_success else (' <<<' if status != 400 else '')
        print(f"  [{r['name']}] token={r.get('token_status', '?')} search={status}{marker}")
        if r.get('search_response'):
            print(f"    {r['search_response'][:200]}")
        if r.get('token_error'):
            print(f"    Token error: {r['token_error']}")
        if r.get('error'):
            print(f"    ERROR: {r['error']}")

    # --- Step 3: Try with contextData as a request header ---
    print("\n[v48] ===== TESTING contextData HEADER =====")
    default_token = await page.evaluate("""async () => {
        const d = JSON.parse(sessionStorage.getItem('gateway-auth-tokens'));
        for (const v of Object.values(d)) if (v.token) return v.token;
        return null;
    }""")

    header_results = await page.evaluate("""async (args) => {
        const {token, amaRef, searchUrl, searchBody} = args;
        const results = [];

        const headerSets = [
            // With contextData header
            {name: 'contextData', extra: {'contextData': JSON.stringify({officeId: 'FRALH08BC', isForcedRefresh: false})}},
            // With X-Context-Data
            {name: 'x_context', extra: {'X-Context-Data': JSON.stringify({officeId: 'FRALH08BC'})}},
            // With office ID header
            {name: 'officeId', extra: {'officeId': 'FRALH08BC'}},
            // With X-Office-Id
            {name: 'x_office', extra: {'X-Office-Id': 'FRALH08BC'}},
            // With Flow-Type
            {name: 'flowType', extra: {'flowType': 'STANDARD'}},
            // With Tenant-Id
            {name: 'tenantId', extra: {'tenantId': 'LH', 'applicationId': 'LH_ONEBKGUI'}},
            // Combine several
            {name: 'combined', extra: {
                'contextData': JSON.stringify({officeId: 'FRALH08BC'}),
                'flowType': 'STANDARD',
                'tenantId': 'LH',
            }},
        ];

        for (const {name, extra} of headerSets) {
            try {
                const resp = await fetch(searchUrl, {
                    method: 'POST',
                    headers: {
                        'Authorization': 'Bearer ' + token,
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'Ama-Client-Ref': amaRef || '',
                        ...extra,
                    },
                    body: searchBody,
                });
                const text = await resp.text();
                results.push({name, status: resp.status, response: text.substring(0, 500)});
            } catch(e) {
                results.push({name, error: e.message});
            }
        }
        return results;
    }""", {
        "token": default_token,
        "amaRef": ama_ref,
        "searchUrl": SEARCH_URL,
        "searchBody": search_body,
    })

    for r in header_results:
        status = r.get('status', 'ERR')
        is_good = status == 200 or (status == 400 and '38601' not in r.get('response', ''))
        marker = ' <<<' if is_good else ''
        print(f"  [{r['name']}] → {status}{marker}")
        print(f"    {r.get('response', r.get('error', ''))[:200]}")

    # --- Step 4: Try the alternative search endpoint: air-bounds ---
    print("\n[v48] ===== TRYING ALTERNATIVE SEARCH ENDPOINTS =====")
    alt_results = await page.evaluate("""async (args) => {
        const {token, amaRef, searchBody} = args;
        const results = [];

        const endpoints = [
            '/v1/one-booking/search/air-bounds',
            '/v1/one-booking/search/air-calendars',
            '/v1/one-booking/search/air-offer-conditions',
        ];

        for (const path of endpoints) {
            try {
                const resp = await fetch('https://api-shop.lufthansa.com' + path, {
                    method: 'POST',
                    headers: {
                        'Authorization': 'Bearer ' + token,
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'Ama-Client-Ref': amaRef || '',
                    },
                    body: searchBody,
                });
                const text = await resp.text();
                results.push({path, status: resp.status, response: text.substring(0, 500)});
            } catch(e) {
                results.push({path, error: e.message});
            }
        }
        return results;
    }""", {"token": default_token, "amaRef": ama_ref, "searchBody": search_body})

    for r in alt_results:
        status = r.get('status', 'ERR')
        is_good = status not in (596, 400)
        marker = ' <<<' if is_good else ''
        print(f"  {r.get('path', '?')} → {status}{marker}")
        print(f"    {r.get('response', r.get('error', ''))[:200]}")

    # --- Save ---
    output = {
        "version": "v48",
        "fact_info": fact_info,
        "token_results": token_results,
        "header_results": header_results,
        "alt_endpoints": alt_results,
    }
    out_path = CAPTURE_DIR / "lufthansa_v48_2026-04-21.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n[v48] Saved to {out_path}")

    await browser.close()
    await pw.stop()
    print("[v48] Done.")


if __name__ == "__main__":
    asyncio.run(main())
