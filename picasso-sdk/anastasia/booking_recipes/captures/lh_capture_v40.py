#!/usr/bin/env python3
"""Lufthansa API capture v40 — Extract Angular config + direct API call from SPA context.

Strategy:
  1. Navigate to shop.lufthansa.com
  2. Handle cookie consent
  3. Let SPA initialize (get OAuth token + public-facts)
  4. Extract the running Angular app's gatewayBaseUrl config
  5. Make the search API call directly using fetch() from page context
  6. Capture request/response
"""

import asyncio
import json
import time
from pathlib import Path

CDP_URL = "wss://brd-customer-hl_890ca773-zone-scraping_browser1:xy22gst47vzm@brd.superproxy.io:9222"
CAPTURE_DIR = Path(__file__).parent


async def main():
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    print("[v40] Connecting to Bright Data CDP...")
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    page = await browser.new_page()

    # Collect all API calls
    api_calls = []

    def on_response(response):
        url = response.url
        if "api-shop.lufthansa.com" in url or "/v2/" in url or "/v1/" in url:
            api_calls.append({
                "url": url,
                "status": response.status,
                "method": response.request.method,
            })

    page.on("response", on_response)

    # --- Step 1: Navigate to shop.lufthansa.com ---
    print("[v40] Navigating to shop.lufthansa.com...")
    await page.goto("https://shop.lufthansa.com/lh/us/en/homepage", timeout=60000)
    await page.wait_for_timeout(5000)
    print(f"[v40] Page title: {await page.title()}")
    print(f"[v40] Page URL: {page.url}")

    # --- Step 2: Cookie consent ---
    print("[v40] Handling cookie consent...")
    try:
        consent_btn = page.locator("#cm-acceptAll, button:has-text('Accept All'), button:has-text('Accept all')")
        if await consent_btn.count() > 0:
            await consent_btn.first.click(timeout=5000)
            print("[v40] Clicked consent button")
            await page.wait_for_timeout(2000)
        else:
            print("[v40] No consent button found")
    except Exception as e:
        print(f"[v40] Consent handling: {e}")

    # --- Step 3: Wait for SPA initialization (OAuth token + public-facts) ---
    print("[v40] Waiting for SPA initialization...")
    await page.wait_for_timeout(8000)
    print(f"[v40] API calls so far: {len(api_calls)}")
    for call in api_calls:
        print(f"  {call['method']} {call['url'][:80]} → {call['status']}")

    # --- Step 4: Extract OAuth token and Angular config ---
    print("[v40] Extracting OAuth token and SPA config...")
    config = await page.evaluate("""() => {
        const result = {
            token: null,
            sessionStorage: {},
            localStorage: {},
            angularConfig: null,
            windowVars: [],
        };

        // Check sessionStorage for token
        for (let i = 0; i < sessionStorage.length; i++) {
            const key = sessionStorage.key(i);
            const val = sessionStorage.getItem(key);
            result.sessionStorage[key] = val.substring(0, 500);
        }

        // Check localStorage
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            const val = localStorage.getItem(key);
            result.localStorage[key] = val.substring(0, 500);
        }

        // Look for Angular transfer state
        const transferState = document.getElementById('serverApp-state');
        if (transferState) {
            result.angularConfig = transferState.textContent.substring(0, 2000);
        }

        // Look for config in window
        const configKeys = Object.keys(window).filter(k =>
            k.toLowerCase().includes('config') ||
            k.toLowerCase().includes('env') ||
            k.toLowerCase().includes('setting') ||
            k === '__INITIAL_STATE__' ||
            k === '__APP_CONFIG__'
        );
        result.windowVars = configKeys;

        return result;
    }""")

    print(f"[v40] SessionStorage keys: {list(config['sessionStorage'].keys())}")
    print(f"[v40] LocalStorage keys: {list(config['localStorage'].keys())}")
    print(f"[v40] Window config vars: {config['windowVars']}")
    if config['angularConfig']:
        print(f"[v40] Angular transfer state: {config['angularConfig'][:300]}")

    # Extract token from sessionStorage
    token = None
    for key, val in config['sessionStorage'].items():
        if 'auth' in key.lower() or 'token' in key.lower():
            print(f"[v40] Auth key '{key}': {val[:200]}")
            try:
                parsed = json.loads(val)
                if isinstance(parsed, dict) and 'access_token' in parsed:
                    token = parsed['access_token']
                elif isinstance(parsed, dict):
                    for v in parsed.values():
                        if isinstance(v, dict) and 'access_token' in v:
                            token = v['access_token']
                            break
                        if isinstance(v, str) and v.startswith('eyJ'):
                            token = v
                            break
            except (json.JSONDecodeError, TypeError):
                if val.startswith('eyJ'):
                    token = val

    if token:
        print(f"[v40] Got token: {token[:60]}...")
    else:
        # Try getting token directly via API
        print("[v40] No token in storage — acquiring fresh token...")
        token_result = await page.evaluate("""async () => {
            try {
                const resp = await fetch('https://api-shop.lufthansa.com/v1/oauth2/token', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: 'client_id=k7zpj4s6k2qbrr4xhrzqa7yn&client_secret=rVXq%2305&fact=%7B%7D&grant_type=client_credentials'
                });
                const data = await resp.json();
                return {status: resp.status, token: data.access_token, error: null};
            } catch(e) {
                return {status: null, token: null, error: e.message};
            }
        }""")
        print(f"[v40] Token result: status={token_result['status']}, error={token_result['error']}")
        if token_result['token']:
            token = token_result['token']
            print(f"[v40] Fresh token: {token[:60]}...")

    if not token:
        print("[v40] FATAL: Could not obtain token")
        await browser.close()
        await pw.stop()
        return

    # --- Step 5: Try search API from multiple URL patterns ---
    print("\n[v40] ===== SEARCH API PROBING =====")

    # Amadeus OneBooking standard search body
    search_body = json.dumps({
        "commercialFareFamilies": [],
        "itinerary": {
            "type": "ROUND_TRIP",
            "connections": [
                {"departure": {"airportCode": "JFK"}, "arrival": {"airportCode": "MUC"}, "departureDate": "2026-05-21"},
                {"departure": {"airportCode": "MUC"}, "arrival": {"airportCode": "JFK"}, "departureDate": "2026-05-28"},
            ],
        },
        "cabin": "ECONOMY",
        "travelers": [{"id": "ADT1", "ptc": "ADT"}],
    })

    # Also try IATA NDC body format
    search_body_ndc = json.dumps({
        "originDestinations": [
            {"id": "1", "originLocationCode": "JFK", "destinationLocationCode": "MUC",
             "departureDateTimeRange": {"date": "2026-05-21"}},
            {"id": "2", "originLocationCode": "MUC", "destinationLocationCode": "JFK",
             "departureDateTimeRange": {"date": "2026-05-28"}},
        ],
        "travelers": [{"id": "1", "travelerType": "ADULT"}],
        "searchCriteria": {"maxFlightOffers": 50},
        "sources": ["GDS"],
    })

    url_patterns = [
        # Original patterns that returned 596
        "https://api-shop.lufthansa.com/v2/search/air-offers",
        # Maybe needs the dapi prefix differently
        "https://api-shop.lufthansa.com/dapi/v2/search/air-offers",
        # OneBooking context path
        "https://api-shop.lufthansa.com/v1/one-booking/v2/search/air-offers",
        # Maybe it's under the booking path
        "https://api-shop.lufthansa.com/v2/one-booking/search/air-offers",
        # Try without /v2/ prefix (it's in the path)
        "https://api-shop.lufthansa.com/search/air-offers",
        # Try the shop domain path that gave 406
        "https://shop.lufthansa.com/booking/api/v2/search/air-offers",
    ]

    results = await page.evaluate("""async (args) => {
        const {token, urlPatterns, body1, body2} = args;
        const results = [];

        for (const url of urlPatterns) {
            // Try POST with Amadeus body
            for (const [bodyName, body] of [['amadeus', body1], ['ndc', body2]]) {
                try {
                    const resp = await fetch(url, {
                        method: 'POST',
                        headers: {
                            'Authorization': 'Bearer ' + token,
                            'Content-Type': 'application/json',
                            'Accept': 'application/json',
                        },
                        body: body,
                    });
                    const text = await resp.text();
                    results.push({
                        url: url,
                        body_type: bodyName,
                        method: 'POST',
                        status: resp.status,
                        content_type: resp.headers.get('content-type'),
                        response_length: text.length,
                        response_preview: text.substring(0, 500),
                        is_html: text.includes('<!DOCTYPE') || text.includes('<html'),
                    });
                } catch(e) {
                    results.push({
                        url: url,
                        body_type: bodyName,
                        method: 'POST',
                        status: null,
                        error: e.message,
                    });
                }
            }

            // Try GET as well (airShopping operation)
            try {
                const params = new URLSearchParams({
                    type: 'ROUND_TRIP',
                    'origins[]': 'JFK',
                    'destinations[]': 'MUC',
                    'departureDates[]': '2026-05-21',
                    'returnDates[]': '2026-05-28',
                    cabin: 'ECONOMY',
                    adults: '1',
                });
                const resp = await fetch(url + '?' + params.toString(), {
                    method: 'GET',
                    headers: {
                        'Authorization': 'Bearer ' + token,
                        'Accept': 'application/json',
                    },
                });
                const text = await resp.text();
                results.push({
                    url: url,
                    body_type: 'query_params',
                    method: 'GET',
                    status: resp.status,
                    content_type: resp.headers.get('content-type'),
                    response_length: text.length,
                    response_preview: text.substring(0, 500),
                    is_html: text.includes('<!DOCTYPE') || text.includes('<html'),
                });
            } catch(e) {
                results.push({
                    url: url,
                    body_type: 'query_params',
                    method: 'GET',
                    status: null,
                    error: e.message,
                });
            }
        }

        return results;
    }""", {
        "token": token,
        "urlPatterns": url_patterns,
        "body1": search_body,
        "body2": search_body_ndc,
    })

    print(f"\n[v40] Probed {len(results)} URL/body combinations:")
    for r in results:
        status = r.get('status', 'ERR')
        is_html = r.get('is_html', False)
        ct = r.get('content_type', '?')
        length = r.get('response_length', 0)
        preview = r.get('response_preview', '')[:120] if not is_html else '[HTML page]'
        error = r.get('error', '')
        print(f"  {r['method']:4} {r['url'][:70]} [{r['body_type']}]")
        if error:
            print(f"       → ERROR: {error}")
        else:
            print(f"       → {status} | {ct} | {length} chars | {'HTML' if is_html else preview}")

    # --- Step 6: Extract Angular runtime config by probing JS ---
    print("\n[v40] ===== EXTRACTING ANGULAR RUNTIME CONFIG =====")
    angular_config = await page.evaluate("""() => {
        const result = {
            ngModules: [],
            injector: null,
            httpClient: null,
            envConfig: null,
        };

        // Try to find Angular's platform ref
        try {
            const appRef = window.ng?.getComponent?.(document.querySelector('app-root'));
            if (appRef) result.ngModules.push('Found app-root component');
        } catch(e) {
            result.ngModules.push('ng.getComponent failed: ' + e.message);
        }

        // Try to find config in the JS bundle's global scope
        try {
            // Look for environment config objects
            const scripts = Array.from(document.querySelectorAll('script[src]'));
            result.scriptCount = scripts.length;
            result.mainScripts = scripts
                .map(s => s.src)
                .filter(s => s.includes('main') || s.includes('runtime'))
                .map(s => s.split('/').pop());
        } catch(e) {
            result.ngModules.push('Script scan failed: ' + e.message);
        }

        // Check for Angular elements
        try {
            const allElements = document.querySelectorAll('[_ngcontent-ng-c]');
            result.angularElements = allElements.length;
            const appRoot = document.querySelector('app-root');
            if (appRoot) {
                result.appRootHTML = appRoot.innerHTML.substring(0, 500);
            }
        } catch(e) {}

        // Check for zone.js patches that reveal config
        try {
            const selectors = ['[ng-reflect-config]', '[ng-reflect-base-url]'];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el) {
                    result.envConfig = el.outerHTML.substring(0, 300);
                }
            }
        } catch(e) {}

        return result;
    }""")

    print(f"[v40] Angular config: {json.dumps(angular_config, indent=2)[:1000]}")

    # --- Step 7: Try to find gatewayBaseUrl in the main.js chunk ---
    print("\n[v40] ===== SEARCHING MAIN.JS FOR GATEWAY URL =====")
    gateway_info = await page.evaluate("""async () => {
        // Find the main bundle script
        const scripts = Array.from(document.querySelectorAll('script[src]'));
        const mainScript = scripts.find(s => s.src.includes('main.'));
        if (!mainScript) return {error: 'No main script found'};

        try {
            const resp = await fetch(mainScript.src);
            const text = await resp.text();

            const results = {};

            // Search for gateway URL patterns
            const patterns = [
                /gatewayBaseUrl\s*[:=]\s*"([^"]+)"/g,
                /gatewayBaseUrl\s*[:=]\s*'([^']+)'/g,
                /baseUrl\s*[:=]\s*"(https?:\/\/[^"]+)"/g,
                /apiBaseUrl\s*[:=]\s*"(https?:\/\/[^"]+)"/g,
                /api-shop[^"'\\s]*/g,
                /gatewayEndPoint\s*[:=]\s*"([^"]+)"/g,
                /contextPath\s*[:=]\s*"([^"]+)"/g,
                /oneBookingContextPath\s*[:=]\s*"([^"]+)"/g,
            ];

            for (const pattern of patterns) {
                const matches = [];
                let m;
                while ((m = pattern.exec(text)) !== null) {
                    matches.push(m[0].substring(0, 200));
                    if (matches.length >= 5) break;
                }
                if (matches.length > 0) {
                    results[pattern.source.substring(0, 40)] = matches;
                }
            }

            // Also look for the specific config block around "air-offers"
            const searchIdx = text.indexOf('air-offers');
            if (searchIdx > -1) {
                // Get 2000 chars before and 500 after
                const context = text.substring(Math.max(0, searchIdx - 2000), searchIdx + 500);
                // Find URLs in that context
                const urlMatches = context.match(/https?:\/\/[a-zA-Z0-9._-]+[^\s"'`,)};]*/g) || [];
                results['urls_near_air_offers'] = urlMatches.slice(0, 10);

                // Also find any basePath construction
                const basePathMatches = context.match(/basePath[^;]{0,200}/g) || [];
                results['basePath_near_search'] = basePathMatches.slice(0, 5);
            }

            // Look for the production environment config
            const envIdx = text.indexOf('production:!0');
            if (envIdx === -1) {
                const envIdx2 = text.indexOf('production:true');
            }
            const prodConfigStart = text.lastIndexOf('{', envIdx > -1 ? envIdx : text.indexOf('production'));
            if (prodConfigStart > -1) {
                const prodConfig = text.substring(prodConfigStart, prodConfigStart + 1000);
                // Find URLs in prod config
                const prodUrls = prodConfig.match(/https?:\/\/[^"'`,)};\\s]+/g) || [];
                results['prod_config_urls'] = prodUrls.slice(0, 10);
            }

            return results;
        } catch(e) {
            return {error: e.message};
        }
    }""")

    print("[v40] Gateway search results:")
    for key, val in gateway_info.items():
        print(f"  {key}:")
        if isinstance(val, list):
            for v in val:
                print(f"    {v}")
        else:
            print(f"    {val}")

    # --- Step 8: Try to use Angular's own HttpClient ---
    print("\n[v40] ===== TRYING ANGULAR INJECTOR =====")
    injector_result = await page.evaluate("""async () => {
        // Angular 19 exposes ng.getInjector on debug elements
        const appRoot = document.querySelector('app-root');
        if (!appRoot) return {error: 'No app-root'};

        try {
            // Try Angular DevTools API
            const injector = window.ng?.getInjector?.(appRoot);
            if (!injector) return {error: 'No injector (ng.getInjector unavailable — prod mode)'};

            // Try to get the HttpClient service
            const httpKeys = Object.keys(injector);
            return {injectorKeys: httpKeys.slice(0, 20), type: typeof injector};
        } catch(e) {
            return {error: e.message};
        }
    }""")
    print(f"[v40] Injector: {json.dumps(injector_result)[:500]}")

    # --- Step 9: Navigate to a search URL and intercept the real API call ---
    print("\n[v40] ===== APPROACH B: Navigate to search URL, intercept real API call =====")

    # Set up request interception to log ALL requests
    intercepted = []

    async def log_request(route):
        req = route.request
        url = req.url
        if any(x in url for x in ['api-shop', '/v2/', '/search', '/air-offers', '/offer']):
            body = req.post_data
            intercepted.append({
                "method": req.method,
                "url": url,
                "headers": dict(req.all_headers()),
                "body": body[:2000] if body else None,
            })
        await route.continue_()

    await page.route("**/*", log_request)

    # Navigate to the search URL with hash parameters
    search_url = "https://shop.lufthansa.com/lh/us/en/homepage#/search;type=rt;from=JFK;to=MUC;dep=2026-05-21;ret=2026-05-28;pax=a1;cabin=economy;li=en;co=us"
    print(f"[v40] Navigating to: {search_url}")
    try:
        await page.goto(search_url, timeout=30000, wait_until="load")
    except Exception as e:
        print(f"[v40] Navigation error (expected): {e}")

    # Wait for the SPA to process the hash route
    print("[v40] Waiting for SPA to process search hash...")
    await page.wait_for_timeout(15000)

    print(f"[v40] Current URL: {page.url}")
    print(f"[v40] Current title: {await page.title()}")
    print(f"[v40] Intercepted {len(intercepted)} API calls:")
    for req in intercepted:
        print(f"  {req['method']} {req['url'][:100]}")
        if req.get('body'):
            print(f"    body: {req['body'][:200]}")

    # Check page content for search results
    page_text = await page.evaluate("() => document.body?.innerText?.substring(0, 2000)")
    print(f"\n[v40] Page text (first 500 chars): {page_text[:500] if page_text else 'EMPTY'}")

    # --- Step 10: Last resort — check if recovery page has a retry/search mechanism ---
    if '/recovery' in page.url:
        print("\n[v40] ===== ON RECOVERY PAGE — Trying to extract error info =====")
        recovery_info = await page.evaluate("""() => {
            const result = {};
            // Check for error messages
            const errors = document.querySelectorAll('[class*=error], [class*=alert], [class*=message]');
            result.errors = Array.from(errors).map(e => e.textContent.substring(0, 200));

            // Check for retry buttons
            const buttons = document.querySelectorAll('button, a[class*=btn], maui-button');
            result.buttons = Array.from(buttons).map(b => ({
                tag: b.tagName,
                text: b.textContent?.trim().substring(0, 100),
                href: b.href || '',
            }));

            // Check sessionStorage for search context
            const searchCtx = sessionStorage.getItem('airOffersAdvancedSearch');
            result.searchContext = searchCtx ? searchCtx.substring(0, 500) : null;

            // Check for cached config
            const configKeys = [];
            for (let i = 0; i < sessionStorage.length; i++) {
                const key = sessionStorage.key(i);
                configKeys.push(key);
            }
            result.sessionKeys = configKeys;

            return result;
        }""")
        print(f"[v40] Recovery info: {json.dumps(recovery_info, indent=2)[:1500]}")

        # Try clicking "Back to search" if available
        back_btns = [b for b in recovery_info.get('buttons', [])
                     if 'back' in (b.get('text', '') or '').lower() or 'search' in (b.get('text', '') or '').lower()]
        if back_btns:
            print(f"[v40] Found back/search buttons: {back_btns}")

    # Remove route handler
    await page.unroute("**/*")

    # --- Save everything ---
    output = {
        "version": "v40",
        "token": token[:60] + "..." if token else None,
        "api_calls_observed": api_calls,
        "probe_results": results,
        "gateway_info": gateway_info,
        "angular_config": angular_config,
        "intercepted_during_nav": intercepted,
        "recovery_info": recovery_info if '/recovery' in page.url else None,
    }

    out_path = CAPTURE_DIR / "lufthansa_v40_2026-04-21.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n[v40] Saved capture to {out_path}")

    await browser.close()
    await pw.stop()
    print("[v40] Done.")


if __name__ == "__main__":
    asyncio.run(main())
