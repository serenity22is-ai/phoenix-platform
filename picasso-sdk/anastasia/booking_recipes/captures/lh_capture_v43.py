#!/usr/bin/env python3
"""Lufthansa API capture v43 — Two parallel approaches:
  A) Complete CMS form with Playwright keyboard events + dates → redirect → capture
  B) Find SPA bundle via performance entries → extract gateway URL → direct API call
"""

import asyncio
import json
from pathlib import Path

CDP_URL = "wss://brd-customer-hl_890ca773-zone-scraping_browser1:xy22gst47vzm@brd.superproxy.io:9222"
CAPTURE_DIR = Path(__file__).parent


async def main():
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    print("[v43] Connecting to Bright Data CDP...")
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    page = await browser.new_page()

    all_api_calls = []

    # Track ALL network requests from the start
    async def on_response(response):
        url = response.url
        if any(x in url for x in ['api-shop', '/v2/search', '/air-offers', '/offer', 'oauth2']):
            try:
                body = None
                try:
                    body = await response.text()
                except Exception:
                    pass
                all_api_calls.append({
                    "url": url,
                    "status": response.status,
                    "method": response.request.method,
                    "post_data": response.request.post_data,
                    "response_preview": body[:3000] if body else None,
                })
            except Exception:
                pass

    page.on("response", on_response)

    # --- APPROACH B: Find SPA bundle first (quick) ---
    print("[v43] ===== APPROACH B: Find SPA bundle =====")
    print("[v43] Navigating to shop.lufthansa.com...")
    await page.goto("https://shop.lufthansa.com/lh/us/en/homepage", timeout=60000, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # Consent
    try:
        btn = page.locator("#cm-acceptAll")
        if await btn.count() > 0:
            await btn.click(timeout=5000)
            await page.wait_for_timeout(2000)
    except Exception:
        pass

    await page.wait_for_timeout(8000)

    # Get token
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

        // Fallback: get fresh
        try {
            const r = await fetch('https://api-shop.lufthansa.com/v1/oauth2/token', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: 'client_id=k7zpj4s6k2qbrr4xhrzqa7yn&client_secret=rVXq%2305&fact=%7B%7D&grant_type=client_credentials'
            });
            const d = await r.json();
            return d.access_token;
        } catch(e) {
            return null;
        }
    }""")
    print(f"[v43] Token: {token[:50] if token else 'NONE'}...")

    # Find ALL JS resources via performance API
    js_resources = await page.evaluate("""() => {
        const entries = performance.getEntriesByType('resource');
        return entries
            .filter(e => e.name.endsWith('.js') || e.initiatorType === 'script')
            .map(e => ({name: e.name, size: e.transferSize, duration: e.duration}))
            .sort((a, b) => (b.size || 0) - (a.size || 0));
    }""")

    print(f"[v43] Found {len(js_resources)} JS resources:")
    lh_js = [r for r in js_resources if 'shop.lufthansa' in r['name']]
    print(f"  LH-specific: {len(lh_js)}")
    for r in lh_js[:20]:
        print(f"    {r['name'][:100]} ({r.get('size', '?')} bytes)")

    # Fetch the LARGEST LH script — likely the SPA main bundle
    if lh_js:
        largest = lh_js[0]  # Already sorted by size desc
        print(f"\n[v43] Fetching largest LH script: {largest['name'][:100]} ({largest.get('size')} bytes)")

        gateway_search = await page.evaluate("""async (url) => {
            try {
                const resp = await fetch(url);
                const text = await resp.text();
                const results = {size: text.length};

                // Find air-offers
                let idx = text.indexOf('air-offers');
                if (idx > -1) {
                    results.air_offers_context = text.substring(Math.max(0, idx - 1000), idx + 500);
                    results.has_air_offers = true;
                } else {
                    results.has_air_offers = false;
                }

                // Find gateway URLs
                const gatewayMatches = text.match(/gateway[A-Za-z]*\s*[=:]\s*["'][^"']+["']/g) || [];
                results.gateway_matches = [...new Set(gatewayMatches)].slice(0, 10);

                // Find base URL assignments
                const baseMatches = text.match(/baseUrl\s*[=:]\s*["'][^"']+["']/g) || [];
                results.base_url_matches = [...new Set(baseMatches)].slice(0, 10);

                // Find all lufthansa/amadeus URLs
                const urlMatches = text.match(/https?:\/\/[a-zA-Z0-9._-]*(?:lufthansa|amadeus)[^\s"'`,)};]*/g) || [];
                results.lh_urls = [...new Set(urlMatches)].slice(0, 20);

                // Find api-shop references
                const apiShopMatches = text.match(/api-shop[^\s"'`,)};]*/g) || [];
                results.api_shop_refs = [...new Set(apiShopMatches)].slice(0, 10);

                return results;
            } catch(e) {
                return {error: e.message};
            }
        }""", largest['name'])

        print(f"[v43] Gateway search in largest script:")
        for key, val in gateway_search.items():
            if isinstance(val, list):
                print(f"  {key}: {val[:10]}")
            elif isinstance(val, str) and len(val) > 200:
                print(f"  {key}: {val[:300]}...")
            else:
                print(f"  {key}: {val}")

        # If no air-offers in largest, check others
        if not gateway_search.get('has_air_offers'):
            print("\n[v43] Air-offers not in largest script, checking others...")
            for r in lh_js[1:10]:
                check = await page.evaluate("""async (url) => {
                    try {
                        const resp = await fetch(url);
                        const text = await resp.text();
                        if (text.includes('air-offers')) {
                            const idx = text.indexOf('air-offers');
                            return {
                                url,
                                size: text.length,
                                found: true,
                                context: text.substring(Math.max(0, idx - 500), idx + 300),
                            };
                        }
                        return {url, size: text.length, found: false};
                    } catch(e) {
                        return {url, error: e.message};
                    }
                }""", r['name'])
                found = check.get('found', False)
                print(f"  {r['name'].split('/')[-1][:50]} ({check.get('size', '?')}b) — {'FOUND' if found else 'no'}")
                if found:
                    print(f"    Context: {check.get('context', '')[:400]}")
                    # Deep dive into this script
                    deep = await page.evaluate("""async (url) => {
                        const resp = await fetch(url);
                        const text = await resp.text();
                        const results = {};

                        // Find all URL-like strings near air-offers
                        const idx = text.indexOf('air-offers');
                        const neighborhood = text.substring(Math.max(0, idx - 5000), idx + 2000);

                        // Find URL construction patterns
                        results.basePath = (neighborhood.match(/basePath[^;]{0,300}/g) || []).slice(0, 5);
                        results.urls = (neighborhood.match(/https?:\/\/[^\s"'`,)};]+/g) || []).slice(0, 10);
                        results.gateway = (neighborhood.match(/gateway[A-Za-z]*[^;]{0,200}/g) || []).slice(0, 5);
                        results.fetch_calls = (neighborhood.match(/fetch\([^)]{0,200}/g) || []).slice(0, 5);

                        // Also search entire file for gatewayBaseUrl
                        results.all_gateway = (text.match(/gatewayBaseUrl[^;]{0,200}/g) || []).slice(0, 10);
                        results.all_apiBase = (text.match(/apiBaseUrl[^;]{0,200}/g) || []).slice(0, 10);

                        return results;
                    }""", r['name'])
                    print(f"    Deep dive:")
                    for dk, dv in deep.items():
                        if dv:
                            print(f"      {dk}: {dv}")
                    break  # Found it

    # --- APPROACH A: CMS form with dates ---
    print("\n\n[v43] ===== APPROACH A: CMS form with dates =====")
    print("[v43] Navigating to www.lufthansa.com...")

    # Set up monkey-patching before navigation
    await page.evaluate("""() => {
        window.__apiCalls = [];

        const origFetch = window.fetch;
        window.fetch = async function(...args) {
            const url = typeof args[0] === 'string' ? args[0] : args[0]?.url;
            const method = args[1]?.method || 'GET';
            const body = args[1]?.body;

            const entry = {t: Date.now(), m: method, u: url, b: typeof body === 'string' ? body?.substring(0, 3000) : null};
            window.__apiCalls.push(entry);

            try {
                const resp = await origFetch.apply(this, args);
                entry.s = resp.status;
                try {
                    const clone = resp.clone();
                    entry.r = (await clone.text()).substring(0, 5000);
                } catch(e) {}
                return resp;
            } catch(e) {
                entry.err = e.message;
                throw e;
            }
        };
    }""")

    try:
        await page.goto("https://www.lufthansa.com/us/en/homepage", timeout=30000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"[v43] Nav: {e}")

    await page.wait_for_timeout(5000)
    print(f"[v43] CMS page: {page.url}")

    # Consent
    try:
        for sel in ["#cm-acceptAll", "button:has-text('Accept All')", "button:has-text('I agree')"]:
            btn = page.locator(sel)
            if await btn.count() > 0:
                await btn.first.click(timeout=3000)
                print(f"[v43] CMS consent clicked: {sel}")
                break
    except Exception:
        pass

    await page.wait_for_timeout(3000)

    # Step A1: Fill origin using Playwright keyboard
    print("[v43] Filling origin...")
    try:
        from_input = page.locator("input[placeholder='From']")
        if await from_input.count() > 0:
            await from_input.click()
            await page.wait_for_timeout(500)

            # Clear existing value
            await from_input.fill("")
            await page.wait_for_timeout(300)

            # Type "New York" to trigger autocomplete
            await from_input.type("New York", delay=100)
            await page.wait_for_timeout(2000)

            # Find and click the autocomplete suggestion
            origin_result = await page.evaluate("""() => {
                const dcep = document.querySelector('.dcep-flight-manager');
                if (!dcep) return {error: 'No DCEP'};

                const options = dcep.querySelectorAll('li, [role=option], [class*=suggestion], [class*=autocomplete] li');
                const items = Array.from(options).map(o => ({
                    text: o.textContent?.trim().substring(0, 100),
                    visible: o.offsetParent !== null,
                })).filter(o => o.visible);

                // Click the one with JFK or "New York"
                for (const opt of options) {
                    const text = opt.textContent || '';
                    if ((text.includes('JFK') || text.includes('New York')) && opt.offsetParent !== null) {
                        opt.click();
                        return {success: true, clicked: text.substring(0, 80), allOptions: items};
                    }
                }

                return {error: 'No matching option', allOptions: items};
            }""")
            print(f"[v43] Origin result: {json.dumps(origin_result)[:300]}")
        else:
            print("[v43] No 'From' input found")
    except Exception as e:
        print(f"[v43] Origin error: {e}")

    await page.wait_for_timeout(1000)

    # Step A2: Fill destination
    print("[v43] Filling destination...")
    try:
        to_input = page.locator("input[placeholder='To']")
        if await to_input.count() > 0:
            await to_input.click()
            await page.wait_for_timeout(500)
            await to_input.fill("")
            await page.wait_for_timeout(300)
            await to_input.type("Munich", delay=100)
            await page.wait_for_timeout(2000)

            dest_result = await page.evaluate("""() => {
                const dcep = document.querySelector('.dcep-flight-manager');
                if (!dcep) return {error: 'No DCEP'};

                const options = dcep.querySelectorAll('li, [role=option], [class*=suggestion], [class*=autocomplete] li');
                const items = Array.from(options).map(o => ({
                    text: o.textContent?.trim().substring(0, 100),
                    visible: o.offsetParent !== null,
                })).filter(o => o.visible);

                for (const opt of options) {
                    const text = opt.textContent || '';
                    if ((text.includes('MUC') || text.includes('Munich')) && opt.offsetParent !== null) {
                        opt.click();
                        return {success: true, clicked: text.substring(0, 80), allOptions: items};
                    }
                }

                return {error: 'No matching option', allOptions: items};
            }""")
            print(f"[v43] Dest result: {json.dumps(dest_result)[:300]}")
        else:
            print("[v43] No 'To' input found")
    except Exception as e:
        print(f"[v43] Dest error: {e}")

    await page.wait_for_timeout(1000)

    # Step A3: Open and fill date picker
    print("[v43] Opening date picker...")
    try:
        date_input = page.locator(".date-input")
        if await date_input.count() > 0:
            await date_input.first.click()
            await page.wait_for_timeout(2000)

            # Check what the calendar looks like
            calendar_state = await page.evaluate("""() => {
                const result = {};
                const calendar = document.querySelector('.date-picker-with-prices, .calendar, [class*=calendar]');
                if (!calendar) return {error: 'No calendar found'};

                result.calendarHTML = calendar.innerHTML.length;
                result.calendarClass = calendar.className;

                // Find month navigation
                const navBtns = calendar.querySelectorAll('button, [role=button]');
                result.navButtons = Array.from(navBtns).map(b => ({
                    text: b.textContent?.trim().substring(0, 50),
                    class: b.className?.substring(0, 50),
                    ariaLabel: b.getAttribute('aria-label'),
                }));

                // Find day cells
                const days = calendar.querySelectorAll('td, [role=gridcell], .day, [class*=day]');
                result.dayCells = Array.from(days).slice(0, 5).map(d => ({
                    text: d.textContent?.trim().substring(0, 20),
                    class: d.className?.substring(0, 50),
                    ariaLabel: d.getAttribute('aria-label'),
                    dataDate: d.getAttribute('data-date'),
                }));

                // Find all visible text
                result.visibleText = calendar.innerText?.substring(0, 500);

                return result;
            }""")
            print(f"[v43] Calendar state: {json.dumps(calendar_state, indent=2)[:1000]}")

            # Navigate to May 2026 and click day 21
            if not calendar_state.get('error'):
                # The calendar might need month navigation
                # First check current month displayed
                navigate_result = await page.evaluate("""async () => {
                    const calendar = document.querySelector('.date-picker-with-prices, [class*=calendar]');
                    if (!calendar) return {error: 'No calendar'};

                    const result = {};

                    // Check current month text
                    const monthTexts = calendar.querySelectorAll('[class*=month], th, .month-title, .month-name, h3, h4');
                    result.monthHeaders = Array.from(monthTexts).map(m => m.textContent?.trim()).filter(Boolean).slice(0, 5);

                    // Find "next month" button
                    const nextBtns = calendar.querySelectorAll('button, [role=button]');
                    let nextBtn = null;
                    for (const btn of nextBtns) {
                        const label = (btn.getAttribute('aria-label') || btn.textContent || '').toLowerCase();
                        const cls = (btn.className || '').toLowerCase();
                        if (label.includes('next') || cls.includes('next') || label.includes('forward') || label.includes('>')) {
                            nextBtn = btn;
                            break;
                        }
                    }

                    if (nextBtn) {
                        result.hasNextBtn = true;
                        result.nextBtnText = nextBtn.textContent?.trim().substring(0, 30);

                        // Click next until we reach May 2026
                        for (let i = 0; i < 6; i++) {
                            const headers = Array.from(calendar.querySelectorAll('[class*=month], th, .month-title, h3, h4'))
                                .map(m => m.textContent?.trim())
                                .filter(Boolean);
                            const headerText = headers.join(' ');

                            if (headerText.includes('May') && headerText.includes('2026')) {
                                result.reachedMay = true;
                                result.currentHeaders = headers;
                                break;
                            }

                            nextBtn.click();
                            await new Promise(r => setTimeout(r, 500));
                        }

                        if (!result.reachedMay) {
                            // Check again
                            const headers = Array.from(calendar.querySelectorAll('[class*=month], th, .month-title, h3, h4'))
                                .map(m => m.textContent?.trim())
                                .filter(Boolean);
                            result.finalHeaders = headers;
                        }
                    } else {
                        result.hasNextBtn = false;
                        result.allButtons = Array.from(nextBtns).map(b => ({
                            text: b.textContent?.trim().substring(0, 50),
                            aria: b.getAttribute('aria-label'),
                            class: b.className?.substring(0, 50),
                        })).slice(0, 10);
                    }

                    // Try to find and click day 21
                    const allDays = calendar.querySelectorAll('td, [role=gridcell], .day, [class*=day-cell]');
                    result.totalDays = allDays.length;

                    for (const day of allDays) {
                        const text = day.textContent?.trim();
                        const ariaLabel = day.getAttribute('aria-label') || '';
                        if (text === '21' || ariaLabel.includes('21 May') || ariaLabel.includes('May 21')) {
                            day.click();
                            result.clickedDep = true;
                            result.clickedDepText = text + ' ' + ariaLabel;
                            break;
                        }
                    }

                    // Wait and check for return date picker
                    await new Promise(r => setTimeout(r, 1000));

                    // Try to find and click return date (28)
                    const allDays2 = calendar.querySelectorAll('td, [role=gridcell], .day, [class*=day-cell]');
                    for (const day of allDays2) {
                        const text = day.textContent?.trim();
                        const ariaLabel = day.getAttribute('aria-label') || '';
                        if (text === '28' || ariaLabel.includes('28 May') || ariaLabel.includes('May 28')) {
                            day.click();
                            result.clickedRet = true;
                            result.clickedRetText = text + ' ' + ariaLabel;
                            break;
                        }
                    }

                    return result;
                }""")
                print(f"[v43] Calendar navigation: {json.dumps(navigate_result, indent=2)[:800]}")
    except Exception as e:
        print(f"[v43] Date error: {e}")

    await page.wait_for_timeout(2000)

    # Step A4: Check form state and click "Find flights"
    print("[v43] Checking form state and submitting...")
    form_state = await page.evaluate("""() => {
        const dcep = document.querySelector('.dcep-flight-manager');
        if (!dcep) return {error: 'No DCEP'};

        const inputs = dcep.querySelectorAll('input');
        const formValues = Array.from(inputs).map(i => ({
            name: i.name,
            value: i.value,
            placeholder: i.placeholder,
        }));

        // Find "Find flights" button
        const mauiButtons = dcep.querySelectorAll('maui-button');
        const findBtn = Array.from(mauiButtons).find(b =>
            b.textContent?.toLowerCase().includes('find flight')
        );

        return {
            formValues,
            findBtnFound: !!findBtn,
            findBtnText: findBtn?.textContent?.trim().substring(0, 50),
        };
    }""")
    print(f"[v43] Form state: {json.dumps(form_state, indent=2)[:500]}")

    if form_state.get('findBtnFound'):
        print("[v43] Clicking 'Find flights'...")

        # Click and monitor for redirect
        click_result = await page.evaluate("""async () => {
            const dcep = document.querySelector('.dcep-flight-manager');
            const mauiButtons = dcep.querySelectorAll('maui-button');
            const findBtn = Array.from(mauiButtons).find(b =>
                b.textContent?.toLowerCase().includes('find flight')
            );
            if (!findBtn) return {error: 'No button'};

            // Click the button
            findBtn.click();

            // Also try clicking inner elements
            const inner = findBtn.querySelector('button, a, span');
            if (inner) inner.click();

            // Wait a bit
            await new Promise(r => setTimeout(r, 3000));

            return {
                clicked: true,
                newUrl: location.href,
                apiCalls: window.__apiCalls?.length || 0,
            };
        }""")
        print(f"[v43] Click result: {json.dumps(click_result)[:300]}")

        # Wait for potential navigation
        print("[v43] Waiting for potential redirect...")
        await page.wait_for_timeout(10000)

        print(f"[v43] Current URL after wait: {page.url}")
        print(f"[v43] Current title: {await page.title()}")

        # Check intercepted calls
        api_calls = await page.evaluate("() => window.__apiCalls || []")
        print(f"\n[v43] Intercepted {len(api_calls)} API calls:")
        for c in api_calls:
            url = c.get('u', '')[:120]
            print(f"  {c.get('m', '?')} {url} → {c.get('s', '?')}")
            if any(x in url for x in ['search', 'air-offers', 'offer', 'air', 'flight']):
                print(f"    BODY: {c.get('b', '')[:300]}")
                print(f"    RESP: {c.get('r', '')[:300]}")

    # Check all_api_calls from the response listener too
    print(f"\n[v43] Response listener captured {len(all_api_calls)} API calls:")
    for c in all_api_calls:
        print(f"  {c['method']} {c['url'][:100]} → {c['status']}")
        if c.get('post_data'):
            print(f"    POST: {c['post_data'][:200]}")
        if c.get('response_preview'):
            print(f"    RESP: {c['response_preview'][:200]}")

    # --- Save everything ---
    output = {
        "version": "v43",
        "js_resources": lh_js[:20] if 'lh_js' in dir() else [],
        "gateway_search": gateway_search if 'gateway_search' in dir() else {},
        "form_state": form_state if 'form_state' in dir() else {},
        "api_calls_intercepted": api_calls if 'api_calls' in dir() else [],
        "api_calls_response_listener": all_api_calls,
    }
    out_path = CAPTURE_DIR / "lufthansa_v43_2026-04-21.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n[v43] Saved to {out_path}")

    await browser.close()
    await pw.stop()
    print("[v43] Done.")


if __name__ == "__main__":
    asyncio.run(main())
