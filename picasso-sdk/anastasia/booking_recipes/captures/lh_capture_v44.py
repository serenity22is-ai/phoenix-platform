#!/usr/bin/env python3
"""Lufthansa API capture v44 — Try oip/vas context paths + dismiss login modal for CMS form.

Key findings from v43:
  - SPA bundle at /statics/applications/booking/dist/28.4.0/main.4ade5f225e73e2b4.js (3.5MB)
  - contextPath is "oip" or "vas" (not "/v2")
  - dapiPremiumBasePath = E.baseUrl + "/" + contextPath (when p||h is false)
  - login modal class="login-flag-modal" blocks all pointer events on CMS
"""

import asyncio
import json
from pathlib import Path

CDP_URL = "wss://brd-customer-hl_890ca773-zone-scraping_browser1:xy22gst47vzm@brd.superproxy.io:9222"
CAPTURE_DIR = Path(__file__).parent


async def main():
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    print("[v44] Connecting to Bright Data CDP...")
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    page = await browser.new_page()

    # Track API calls
    api_calls = []

    async def on_response(response):
        url = response.url
        if any(x in url for x in ['api-shop', '/search', '/air-offers', '/offer', 'oauth2', '/oip/', '/vas/']):
            try:
                body = None
                try:
                    body = await response.text()
                except Exception:
                    pass
                api_calls.append({
                    "url": url, "status": response.status, "method": response.request.method,
                    "post_data": response.request.post_data,
                    "response": body[:5000] if body else None,
                })
            except Exception:
                pass

    page.on("response", on_response)

    # --- Step 1: Get token from shop.lufthansa.com ---
    print("[v44] Getting token from shop.lufthansa.com...")
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
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'client_id=k7zpj4s6k2qbrr4xhrzqa7yn&client_secret=rVXq%2305&fact=%7B%7D&grant_type=client_credentials'
        });
        const d = await r.json();
        return d.access_token;
    }""")
    print(f"[v44] Token: {'OK' if token else 'FAIL'}")

    # Get Ama-Client-Ref from session
    ama_ref = await page.evaluate("() => sessionStorage.getItem('Ama-Client-Ref')")
    print(f"[v44] Ama-Client-Ref: {ama_ref}")

    # --- Step 2: Try oip/vas/booking context paths ---
    print("\n[v44] ===== TESTING CONTEXT PATHS =====")

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

    # All URL patterns to try
    url_patterns = [
        # Context paths from code analysis
        "https://api-shop.lufthansa.com/oip/search/air-offers",
        "https://api-shop.lufthansa.com/vas/search/air-offers",
        # With v2 under context
        "https://api-shop.lufthansa.com/oip/v2/search/air-offers",
        "https://api-shop.lufthansa.com/vas/v2/search/air-offers",
        # Maybe the SPA path IS the context
        "https://api-shop.lufthansa.com/lh/us/en/v2/search/air-offers",
        "https://api-shop.lufthansa.com/booking/v2/search/air-offers",
        # From the code: oneBookingContextPath
        "https://api-shop.lufthansa.com/one-booking/v2/search/air-offers",
        "https://api-shop.lufthansa.com/v1/one-booking/search/air-offers",
        # Re-test v2 with Ama-Client-Ref
        "https://api-shop.lufthansa.com/v2/search/air-offers",
    ]

    results = await page.evaluate("""async (args) => {
        const {token, amaRef, urls, body} = args;
        const results = [];

        for (const url of urls) {
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
                    url, status: resp.status,
                    ct: resp.headers.get('content-type'),
                    length: text.length,
                    isHtml: text.includes('<!DOCTYPE') || text.includes('<html'),
                    preview: text.substring(0, 500),
                });
            } catch(e) {
                results.push({url, error: e.message});
            }
        }
        return results;
    }""", {"token": token, "amaRef": ama_ref, "urls": url_patterns, "body": search_body})

    for r in results:
        url_short = r.get('url', '').replace('https://api-shop.lufthansa.com', '')
        status = r.get('status', 'ERR')
        is_html = r.get('isHtml', False)
        length = r.get('length', 0)
        preview = r.get('preview', '')[:150] if not is_html else '[HTML]'
        error = r.get('error', '')

        print(f"  POST {url_short}")
        if error:
            print(f"    → ERROR: {error}")
        else:
            print(f"    → {status} | {r.get('ct', '?')} | {length}b {'[HTML]' if is_html else ''}")
            if not is_html and preview:
                print(f"    → {preview}")

    # --- Step 3: Deeper JS analysis — find E.baseUrl assignment ---
    print("\n[v44] ===== DEEPER JS ANALYSIS =====")
    js_deep = await page.evaluate("""async () => {
        const resp = await fetch('/statics/applications/booking/dist/28.4.0/main.4ade5f225e73e2b4.js');
        const text = await resp.text();
        const results = {};

        // Find the E object construction (production config)
        // Pattern: E = {baseUrl: "...", clientId: "...", ...}
        // Or: E = someFunction() that returns config

        // Search for "E.baseUrl" usage patterns
        const eBaseUrls = text.match(/E\.baseUrl[^;]{0,100}/g) || [];
        results.E_baseUrl_usages = [...new Set(eBaseUrls)].slice(0, 10);

        // Search for "E.clientId" usage
        const eClientIds = text.match(/E\.clientId[^;]{0,100}/g) || [];
        results.E_clientId_usages = [...new Set(eClientIds)].slice(0, 5);

        // Search for "E.tokenPath" usage
        const eTokenPaths = text.match(/E\.tokenPath[^;]{0,100}/g) || [];
        results.E_tokenPath_usages = [...new Set(eTokenPaths)].slice(0, 5);

        // Find the production environment block
        // Look for "production:!0" or "production:true" near baseUrl
        const prodIdx = text.indexOf('production:!0');
        if (prodIdx > -1) {
            // Search backwards and forwards for config object
            let start = text.lastIndexOf('{', prodIdx);
            // Find the start of this config object more carefully
            let braceCount = 1;
            let searchStart = prodIdx - 1;
            while (searchStart > 0 && braceCount > 0) {
                if (text[searchStart] === '}') braceCount++;
                if (text[searchStart] === '{') braceCount--;
                searchStart--;
            }
            results.prod_config_block = text.substring(Math.max(0, searchStart), searchStart + 2000);
        }

        // Find the key pattern: where E is assigned from environment config
        // Common Angular pattern: E = environment.production ? PROD_CONFIG : DEV_CONFIG
        const envAssignments = text.match(/=\s*\{[^}]*production:\s*!?[01][^}]*baseUrl[^}]*\}/g) || [];
        results.env_assignments = envAssignments.map(e => e.substring(0, 300)).slice(0, 5);

        // Look for "api-shop.lufthansa.com" directly
        const apiShopRefs = [];
        let searchPos = 0;
        while (true) {
            const idx = text.indexOf('api-shop.lufthansa.com', searchPos);
            if (idx === -1 || apiShopRefs.length >= 5) break;
            apiShopRefs.push(text.substring(Math.max(0, idx - 100), idx + 200));
            searchPos = idx + 1;
        }
        results.api_shop_context = apiShopRefs;

        // Look for the "oip" and "vas" strings in context
        const oipRefs = [];
        searchPos = 0;
        while (true) {
            const idx = text.indexOf('"oip"', searchPos);
            if (idx === -1 || oipRefs.length >= 5) break;
            oipRefs.push(text.substring(Math.max(0, idx - 200), idx + 200));
            searchPos = idx + 1;
        }
        results.oip_context = oipRefs;

        const vasRefs = [];
        searchPos = 0;
        while (true) {
            const idx = text.indexOf('"vas"', searchPos);
            if (idx === -1 || vasRefs.length >= 5) break;
            vasRefs.push(text.substring(Math.max(0, idx - 200), idx + 200));
            searchPos = idx + 1;
        }
        results.vas_context = vasRefs;

        return results;
    }""")

    for key, val in js_deep.items():
        print(f"\n  [{key}]:")
        if isinstance(val, list):
            for i, v in enumerate(val):
                print(f"    [{i}] {str(v)[:250]}")
        else:
            print(f"    {str(val)[:500]}")

    # --- Step 4: Navigate to CMS, dismiss modal, fill form ---
    print("\n\n[v44] ===== CMS FORM (with modal dismissal) =====")

    # Monkey-patch fetch before navigation
    await page.evaluate("""() => {
        window.__apiCalls = [];
        const origFetch = window.fetch;
        window.fetch = async function(...args) {
            const url = typeof args[0] === 'string' ? args[0] : args[0]?.url;
            const method = args[1]?.method || 'GET';
            const body = args[1]?.body;
            const entry = {t: Date.now(), m: method, u: url, b: typeof body === 'string' ? body?.substring(0,3000) : null};
            window.__apiCalls.push(entry);
            try {
                const resp = await origFetch.apply(this, args);
                entry.s = resp.status;
                try { entry.r = (await resp.clone().text()).substring(0, 5000); } catch(e) {}
                return resp;
            } catch(e) { entry.err = e.message; throw e; }
        };
    }""")

    print("[v44] Navigating to CMS...")
    try:
        await page.goto("https://www.lufthansa.com/us/en/homepage", timeout=30000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"[v44] Nav timeout: {e}")

    await page.wait_for_timeout(5000)

    # Consent
    try:
        for sel in ["#cm-acceptAll", "button:has-text('Accept All')"]:
            b = page.locator(sel)
            if await b.count() > 0:
                await b.first.click(timeout=3000)
                await page.wait_for_timeout(1000)
                break
    except Exception:
        pass

    await page.wait_for_timeout(3000)

    # DISMISS LOGIN MODAL via JavaScript
    print("[v44] Dismissing login modal...")
    modal_removed = await page.evaluate("""() => {
        const modals = document.querySelectorAll('maui-modal.login-flag-modal, .login-flag-modal-container, maui-modal[class*=login]');
        let removed = 0;
        for (const m of modals) {
            m.remove();
            removed++;
        }
        // Also remove any overlay that might block
        const overlays = document.querySelectorAll('.modal-backdrop, .overlay, [class*=overlay]');
        for (const o of overlays) {
            o.remove();
            removed++;
        }
        return {removed};
    }""")
    print(f"[v44] Modal removal: {modal_removed}")
    await page.wait_for_timeout(1000)

    # Now fill the form using Playwright keyboard actions
    print("[v44] Filling origin (New York)...")
    try:
        from_input = page.locator("input[placeholder='From']")
        await from_input.click(timeout=5000)
        await page.wait_for_timeout(500)
        await from_input.fill("")
        await from_input.type("New York", delay=80)
        await page.wait_for_timeout(2000)

        # Click autocomplete option
        origin_result = await page.evaluate("""() => {
            const dcep = document.querySelector('.dcep-flight-manager');
            if (!dcep) return {error: 'No DCEP'};
            const options = dcep.querySelectorAll('li');
            const items = Array.from(options).filter(o => o.offsetParent !== null).map(o => o.textContent?.trim().substring(0, 80));
            for (const opt of options) {
                const text = opt.textContent || '';
                if ((text.includes('JFK') || text.includes('all airports')) && opt.offsetParent !== null) {
                    opt.click();
                    return {success: true, clicked: text.substring(0, 80), options: items};
                }
            }
            return {error: 'No option', options: items};
        }""")
        print(f"[v44] Origin: {json.dumps(origin_result)[:300]}")
    except Exception as e:
        print(f"[v44] Origin error: {e}")

    await page.wait_for_timeout(1000)

    # Fill destination
    print("[v44] Filling destination (Munich)...")
    try:
        to_input = page.locator("input[placeholder='To']")
        await to_input.click(timeout=5000)
        await page.wait_for_timeout(500)
        await to_input.fill("")
        await to_input.type("Munich", delay=80)
        await page.wait_for_timeout(2000)

        dest_result = await page.evaluate("""() => {
            const dcep = document.querySelector('.dcep-flight-manager');
            if (!dcep) return {error: 'No DCEP'};
            const options = dcep.querySelectorAll('li');
            const items = Array.from(options).filter(o => o.offsetParent !== null).map(o => o.textContent?.trim().substring(0, 80));
            for (const opt of options) {
                const text = opt.textContent || '';
                if ((text.includes('MUC') || text.includes('Munich')) && opt.offsetParent !== null) {
                    opt.click();
                    return {success: true, clicked: text.substring(0, 80), options: items};
                }
            }
            return {error: 'No option', options: items};
        }""")
        print(f"[v44] Dest: {json.dumps(dest_result)[:300]}")
    except Exception as e:
        print(f"[v44] Dest error: {e}")

    await page.wait_for_timeout(1000)

    # Open date picker and fill dates
    print("[v44] Opening date picker...")
    try:
        date_div = page.locator(".date-input").first
        await date_div.click(timeout=5000)
        await page.wait_for_timeout(2000)

        # Navigate calendar and select dates
        calendar_result = await page.evaluate("""async () => {
            const dcep = document.querySelector('.dcep-flight-manager');
            const calendar = dcep?.querySelector('.date-picker-with-prices') || document.querySelector('.date-picker-with-prices, [class*=calendar]');
            if (!calendar) return {error: 'No calendar'};

            const result = {calendarText: calendar.innerText?.substring(0, 500)};

            // Find current month headers
            const allText = calendar.querySelectorAll('*');
            const monthHeaders = [];
            for (const el of allText) {
                if (el.children.length === 0) {
                    const text = el.textContent?.trim();
                    if (text && text.match(/^(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}$/)) {
                        monthHeaders.push(text);
                    }
                }
            }
            result.monthHeaders = monthHeaders;

            // Find next button
            const buttons = calendar.querySelectorAll('button');
            let nextBtn = null;
            for (const btn of buttons) {
                const text = (btn.textContent?.trim() + ' ' + (btn.getAttribute('aria-label') || '')).toLowerCase();
                if (text.includes('next') || text.includes('→') || text.includes('>') || btn.className?.includes('next')) {
                    nextBtn = btn;
                    break;
                }
            }
            result.hasNextBtn = !!nextBtn;
            result.allButtons = Array.from(buttons).map(b => ({
                text: b.textContent?.trim().substring(0, 30),
                aria: b.getAttribute('aria-label'),
                class: b.className?.substring(0, 50),
            }));

            // Navigate to May 2026
            if (nextBtn) {
                for (let i = 0; i < 12; i++) {
                    const headers = [];
                    for (const el of calendar.querySelectorAll('*')) {
                        if (el.children.length === 0) {
                            const text = el.textContent?.trim();
                            if (text && text.match(/^(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}$/)) {
                                headers.push(text);
                            }
                        }
                    }
                    if (headers.some(h => h.includes('May 2026'))) {
                        result.reachedMay = true;
                        result.currentHeaders = headers;
                        break;
                    }
                    nextBtn.click();
                    await new Promise(r => setTimeout(r, 300));
                }
            }

            // Click departure date (21)
            const days = calendar.querySelectorAll('td, [role=gridcell], button');
            for (const day of days) {
                const text = day.textContent?.trim();
                const aria = day.getAttribute('aria-label') || '';
                if (text === '21' && (aria.includes('May') || !aria)) {
                    day.click();
                    result.clickedDep = {text, aria};
                    break;
                }
            }

            await new Promise(r => setTimeout(r, 1000));

            // Click return date (28)
            const days2 = calendar.querySelectorAll('td, [role=gridcell], button');
            for (const day of days2) {
                const text = day.textContent?.trim();
                const aria = day.getAttribute('aria-label') || '';
                if (text === '28' && (aria.includes('May') || !aria)) {
                    day.click();
                    result.clickedRet = {text, aria};
                    break;
                }
            }

            await new Promise(r => setTimeout(r, 500));

            return result;
        }""")
        print(f"[v44] Calendar: {json.dumps(calendar_result, indent=2)[:800]}")
    except Exception as e:
        print(f"[v44] Date error: {e}")

    await page.wait_for_timeout(2000)

    # Check form state
    form_state = await page.evaluate("""() => {
        const dcep = document.querySelector('.dcep-flight-manager');
        if (!dcep) return {error: 'No DCEP'};
        const inputs = dcep.querySelectorAll('input');
        return {
            values: Array.from(inputs).map(i => ({name: i.name, value: i.value, placeholder: i.placeholder})),
        };
    }""")
    print(f"[v44] Form state: {json.dumps(form_state, indent=2)[:500]}")

    # Click "Find flights"
    print("[v44] Clicking 'Find flights'...")
    submit_result = await page.evaluate("""async () => {
        const dcep = document.querySelector('.dcep-flight-manager');
        if (!dcep) return {error: 'No DCEP'};

        // Find maui-button with "Find flights" text
        const mauiButtons = dcep.querySelectorAll('maui-button');
        for (const mb of mauiButtons) {
            if (mb.textContent?.toLowerCase().includes('find flight')) {
                mb.click();
                const inner = mb.querySelector('button, a, span');
                if (inner) inner.click();

                await new Promise(r => setTimeout(r, 5000));

                return {
                    clicked: true,
                    newUrl: location.href,
                    title: document.title,
                    apiCalls: window.__apiCalls?.length || 0,
                    lastCalls: (window.__apiCalls || []).slice(-5).map(c => ({
                        m: c.m, u: c.u?.substring(0, 100), s: c.s,
                        b: c.b?.substring(0, 200), r: c.r?.substring(0, 200),
                    })),
                };
            }
        }
        return {error: 'No Find flights button found'};
    }""")
    print(f"[v44] Submit result: {json.dumps(submit_result, indent=2)[:600]}")

    # Wait for potential redirect
    print("[v44] Waiting for redirect...")
    try:
        await page.wait_for_url("**/shop.lufthansa.com/**", timeout=15000)
        print(f"[v44] REDIRECTED to: {page.url}")
    except Exception:
        print(f"[v44] No redirect. Still at: {page.url}")

    await page.wait_for_timeout(5000)

    # Check all intercepted calls
    all_intercepted = await page.evaluate("() => window.__apiCalls || []")
    print(f"\n[v44] Total intercepted calls: {len(all_intercepted)}")
    for c in all_intercepted:
        url = c.get('u', '')
        if any(x in url for x in ['search', 'air-offers', 'offer', '/v2/', 'oauth2', 'oip', 'vas']):
            print(f"  {c.get('m', '?')} {url[:120]} → {c.get('s', '?')}")
            if c.get('b'):
                print(f"    BODY: {c['b'][:200]}")
            if c.get('r'):
                print(f"    RESP: {c['r'][:200]}")

    # Also check response listener
    print(f"\n[v44] Response listener calls: {len(api_calls)}")
    for c in api_calls:
        print(f"  {c['method']} {c['url'][:120]} → {c['status']}")
        if c.get('response'):
            print(f"    RESP: {c['response'][:200]}")

    # --- Save ---
    output = {
        "version": "v44",
        "context_path_results": results,
        "js_deep_analysis": js_deep,
        "form_result": {
            "origin": origin_result if 'origin_result' in dir() else None,
            "dest": dest_result if 'dest_result' in dir() else None,
            "calendar": calendar_result if 'calendar_result' in dir() else None,
            "submit": submit_result if 'submit_result' in dir() else None,
        },
        "all_api_calls": api_calls,
    }
    out_path = CAPTURE_DIR / "lufthansa_v44_2026-04-21.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n[v44] Saved to {out_path}")

    await browser.close()
    await pw.stop()
    print("[v44] Done.")


if __name__ == "__main__":
    asyncio.run(main())
