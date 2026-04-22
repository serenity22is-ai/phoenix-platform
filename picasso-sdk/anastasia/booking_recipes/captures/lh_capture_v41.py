#!/usr/bin/env python3
"""Lufthansa API capture v41 — Two approaches:
  A) Probe shop.lufthansa.com/booking/api/ with various header combos
  B) Fetch main.js and extract gateway config
  C) Complete CMS form with dates to trigger natural search redirect

Key insight from v40:
  - shop.lufthansa.com/booking/api/v2/search/air-offers → 406 (endpoint exists!)
  - api-shop.lufthansa.com/v2/search/air-offers → 596 (wrong gateway path)
  - The SPA likely uses RELATIVE paths through shop.lufthansa.com/booking/api/ proxy
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
    print("[v41] Connecting to Bright Data CDP...")
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    page = await browser.new_page()

    # --- Step 1: Navigate and get token ---
    print("[v41] Navigating to shop.lufthansa.com...")
    await page.goto("https://shop.lufthansa.com/lh/us/en/homepage", timeout=60000, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)

    # Cookie consent
    try:
        btn = page.locator("#cm-acceptAll")
        if await btn.count() > 0:
            await btn.click(timeout=5000)
            print("[v41] Clicked consent")
            await page.wait_for_timeout(2000)
    except Exception as e:
        print(f"[v41] Consent: {e}")

    await page.wait_for_timeout(8000)

    # Get token
    token_data = await page.evaluate("""async () => {
        // Try sessionStorage first
        for (let i = 0; i < sessionStorage.length; i++) {
            const key = sessionStorage.key(i);
            if (key.includes('auth') || key.includes('token')) {
                const val = sessionStorage.getItem(key);
                try {
                    const parsed = JSON.parse(val);
                    if (parsed.access_token) return {token: parsed.access_token, source: key};
                    for (const v of Object.values(parsed)) {
                        if (v && typeof v === 'object' && v.access_token) return {token: v.access_token, source: key};
                        if (typeof v === 'string' && v.startsWith('eyJ')) return {token: v, source: key};
                    }
                } catch(e) {}
            }
        }
        // Get fresh token
        try {
            const r = await fetch('https://api-shop.lufthansa.com/v1/oauth2/token', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: 'client_id=k7zpj4s6k2qbrr4xhrzqa7yn&client_secret=rVXq%2305&fact=%7B%7D&grant_type=client_credentials'
            });
            const d = await r.json();
            return {token: d.access_token, source: 'fresh'};
        } catch(e) {
            return {token: null, source: null, error: e.message};
        }
    }""")

    token = token_data.get('token')
    print(f"[v41] Token source: {token_data.get('source')}, token: {token[:50] if token else 'NONE'}...")

    if not token:
        print("[v41] FATAL: No token")
        await browser.close()
        await pw.stop()
        return

    # --- Step 2: Fetch and analyze main.js ---
    print("\n[v41] ===== FETCHING MAIN.JS =====")
    js_analysis = await page.evaluate("""async () => {
        const scripts = Array.from(document.querySelectorAll('script[src]'));
        const mainScript = scripts.find(s => s.src.includes('main.'));
        if (!mainScript) return {error: 'No main script', scripts: scripts.map(s=>s.src.split('/').pop()).slice(0,20)};

        const resp = await fetch(mainScript.src);
        const text = await resp.text();
        const results = {
            scriptUrl: mainScript.src,
            size: text.length,
            findings: {}
        };

        // Search for all URLs in the bundle
        const urlRegex = /https?:\/\/[a-zA-Z0-9._-]+(?:\/[a-zA-Z0-9._/-]*)?/g;
        const allUrls = [...new Set(text.match(urlRegex) || [])];
        results.findings.all_https_urls = allUrls.filter(u =>
            u.includes('lufthansa') || u.includes('amadeus') || u.includes('api')
        ).slice(0, 30);

        // Search for baseUrl assignments
        const baseUrlRegex = /baseUrl\s*[=:]\s*["']([^"']+)["']/g;
        const baseUrls = [];
        let m;
        while ((m = baseUrlRegex.exec(text)) !== null) {
            baseUrls.push(m[1]);
        }
        results.findings.baseUrl_values = [...new Set(baseUrls)];

        // Search for specific path patterns
        const pathPatterns = [
            {name: 'booking_api', regex: /["']\/booking\/api[^"']*["']/g},
            {name: 'v2_paths', regex: /["']\/v2\/[^"']*["']/g},
            {name: 'search_paths', regex: /["'][^"']*search[^"']*air[^"']*["']/g},
            {name: 'gateway', regex: /gateway[A-Za-z]*\s*[=:]\s*["']([^"']+)["']/g},
            {name: 'contextPath', regex: /contextPath\s*[=:]\s*["']([^"']+)["']/g},
            {name: 'oneBooking', regex: /oneBooking[A-Za-z]*\s*[=:]\s*["']([^"']+)["']/g},
        ];

        for (const {name, regex} of pathPatterns) {
            const matches = [];
            let m;
            while ((m = regex.exec(text)) !== null) {
                matches.push(m[0].substring(0, 200));
                if (matches.length >= 10) break;
            }
            if (matches.length) results.findings[name] = matches;
        }

        // Find the environment/config block - search for 'production' near URL configs
        const prodIdx = text.indexOf('production:!0');
        if (prodIdx > -1) {
            const ctx = text.substring(Math.max(0, prodIdx - 500), prodIdx + 1000);
            const urls = ctx.match(/https?:\/\/[^\s"',)};]+/g) || [];
            results.findings.prod_context_urls = [...new Set(urls)];
            results.findings.prod_context_snippet = ctx.substring(0, 300);
        }

        // Find the specific air-offers path context
        const airIdx = text.indexOf('/search/air-offers');
        if (airIdx > -1) {
            // Look backwards for the basePath or URL construction
            const before = text.substring(Math.max(0, airIdx - 3000), airIdx);
            // Find the last URL or basePath assignment before air-offers
            const lastBaseUrl = before.lastIndexOf('basePath');
            const lastGateway = before.lastIndexOf('gatewayBaseUrl');
            const lastUrl = before.lastIndexOf('https://');

            results.findings.air_offers_context = {
                position: airIdx,
                last_basePath_offset: lastBaseUrl > -1 ? airIdx - lastBaseUrl : -1,
                last_gateway_offset: lastGateway > -1 ? airIdx - lastGateway : -1,
                last_https_offset: lastUrl > -1 ? airIdx - lastUrl : -1,
            };

            // Get the URL construction context
            if (lastUrl > -1 && airIdx - lastUrl < 2000) {
                const urlCtx = text.substring(lastUrl, lastUrl + 200);
                results.findings.last_url_before_air_offers = urlCtx;
            }

            // Get immediate basePath context
            if (lastBaseUrl > -1 && airIdx - lastBaseUrl < 2000) {
                const bpCtx = text.substring(lastBaseUrl, lastBaseUrl + 300);
                results.findings.basePath_context = bpCtx;
            }

            if (lastGateway > -1 && airIdx - lastGateway < 2000) {
                const gwCtx = text.substring(lastGateway, lastGateway + 300);
                results.findings.gateway_context = gwCtx;
            }
        }

        // Find ALL occurrences of "air-offers" for full context
        const airOffersAll = [];
        let searchPos = 0;
        while (true) {
            const idx = text.indexOf('air-offers', searchPos);
            if (idx === -1 || airOffersAll.length >= 5) break;
            airOffersAll.push(text.substring(Math.max(0, idx - 100), idx + 100));
            searchPos = idx + 1;
        }
        results.findings.air_offers_occurrences = airOffersAll;

        return results;
    }""")

    print(f"[v41] Main.js: {js_analysis.get('scriptUrl', '?')}, size: {js_analysis.get('size', 0)}")
    findings = js_analysis.get('findings', {})
    for key, val in findings.items():
        print(f"\n  [{key}]:")
        if isinstance(val, list):
            for v in val[:10]:
                print(f"    {str(v)[:150]}")
        elif isinstance(val, dict):
            for k2, v2 in val.items():
                print(f"    {k2}: {str(v2)[:150]}")
        else:
            print(f"    {str(val)[:300]}")

    # --- Step 3: Try shop.lufthansa.com/booking/api/ with many header combos ---
    print("\n[v41] ===== PROBING PROXY ENDPOINT WITH HEADER VARIATIONS =====")
    proxy_url = "https://shop.lufthansa.com/booking/api/v2/search/air-offers"

    search_body = JSON_dumps = json.dumps({
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

    header_combos = await page.evaluate("""async (args) => {
        const {token, proxyUrl, body} = args;
        const results = [];

        // Various Accept + Content-Type combinations
        const combos = [
            {accept: 'application/json', ct: 'application/json', name: 'json/json'},
            {accept: 'application/xml', ct: 'application/xml', name: 'xml/xml'},
            {accept: 'application/xml', ct: 'application/json', name: 'xml/json'},
            {accept: 'text/xml', ct: 'application/json', name: 'text-xml/json'},
            {accept: 'application/json;charset=utf-8', ct: 'application/json;charset=utf-8', name: 'json-charset'},
            {accept: 'application/json', ct: 'application/json', extra: {'X-Requested-With': 'XMLHttpRequest'}, name: 'xhr'},
            {accept: 'application/json', ct: 'application/json', extra: {'Ama-Client-Ref': JSON.stringify({id: 'test-' + Date.now(), generatedTime: new Date().toISOString()})}, name: 'ama-ref'},
            {accept: 'application/json', ct: 'application/json', extra: {'X-Api-Key': 'k7zpj4s6k2qbrr4xhrzqa7yn'}, name: 'api-key'},
            {accept: 'application/hal+json', ct: 'application/json', name: 'hal-json'},
            {accept: 'application/json', ct: 'application/json', extra: {'Origin': 'https://shop.lufthansa.com', 'Referer': 'https://shop.lufthansa.com/lh/us/en/homepage'}, name: 'with-origin'},
        ];

        for (const combo of combos) {
            try {
                const headers = {
                    'Authorization': 'Bearer ' + token,
                    'Accept': combo.accept,
                    'Content-Type': combo.ct,
                    ...(combo.extra || {}),
                };
                const resp = await fetch(proxyUrl, {
                    method: 'POST',
                    headers,
                    body,
                });
                const text = await resp.text();
                results.push({
                    name: combo.name,
                    status: resp.status,
                    ct: resp.headers.get('content-type'),
                    length: text.length,
                    isHtml: text.includes('<!DOCTYPE') || text.includes('<html'),
                    preview: text.substring(0, 300),
                    respHeaders: Object.fromEntries(resp.headers.entries()),
                });
            } catch(e) {
                results.push({name: combo.name, error: e.message});
            }
        }

        // Also try without Authorization (in case it's the token format)
        try {
            const resp = await fetch(proxyUrl, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
                body,
            });
            const text = await resp.text();
            results.push({
                name: 'no-auth',
                status: resp.status,
                ct: resp.headers.get('content-type'),
                length: text.length,
                isHtml: text.includes('<!DOCTYPE') || text.includes('<html'),
                preview: text.substring(0, 300),
            });
        } catch(e) {
            results.push({name: 'no-auth', error: e.message});
        }

        return results;
    }""", {"token": token, "proxyUrl": proxy_url, "body": search_body})

    print(f"[v41] Proxy endpoint probe results ({len(header_combos)} combos):")
    for r in header_combos:
        if r.get('error'):
            print(f"  [{r['name']}] ERROR: {r['error']}")
        else:
            html_flag = ' [HTML]' if r.get('isHtml') else ''
            preview = r.get('preview', '')[:100] if not r.get('isHtml') else ''
            print(f"  [{r['name']}] {r['status']} | {r.get('ct', '?')} | {r.get('length', 0)} chars{html_flag}")
            if preview:
                print(f"    Preview: {preview}")

    # --- Step 4: Navigate to CMS and try the form with dates ---
    print("\n[v41] ===== CMS FORM APPROACH — WITH DATES =====")

    # Set up fetch/XHR interception BEFORE navigating
    intercepted_calls = []
    await page.evaluate("""() => {
        window.__intercepted = [];

        // Monkey-patch fetch
        const origFetch = window.fetch;
        window.fetch = async function(...args) {
            const url = typeof args[0] === 'string' ? args[0] : args[0]?.url;
            const method = args[1]?.method || 'GET';
            const body = args[1]?.body || null;

            const entry = {t: Date.now(), m: method, u: url, b: typeof body === 'string' ? body?.substring(0, 2000) : null};
            window.__intercepted.push(entry);

            try {
                const resp = await origFetch.apply(this, args);
                entry.s = resp.status;
                // Clone to read body
                try {
                    const clone = resp.clone();
                    const text = await clone.text();
                    entry.r = text.substring(0, 3000);
                } catch(e) {}
                return resp;
            } catch(e) {
                entry.err = e.message;
                throw e;
            }
        };

        // Monkey-patch XHR
        const origOpen = XMLHttpRequest.prototype.open;
        const origSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.open = function(method, url) {
            this.__method = method;
            this.__url = url;
            return origOpen.apply(this, arguments);
        };
        XMLHttpRequest.prototype.send = function(body) {
            const entry = {t: Date.now(), m: this.__method, u: this.__url, b: typeof body === 'string' ? body?.substring(0, 2000) : null, type: 'xhr'};
            window.__intercepted.push(entry);

            this.addEventListener('load', () => {
                entry.s = this.status;
                entry.r = this.responseText?.substring(0, 3000);
            });
            return origSend.apply(this, arguments);
        };
    }""")

    print("[v41] Navigating to www.lufthansa.com...")
    try:
        await page.goto("https://www.lufthansa.com/us/en/homepage", timeout=30000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"[v41] Nav timeout (expected): {e}")

    await page.wait_for_timeout(8000)
    print(f"[v41] Page: {page.url}, title: {await page.title()}")

    # Handle CMS cookie consent
    try:
        consent_selectors = [
            "#cm-acceptAll",
            "button:has-text('Accept All')",
            "button:has-text('Accept all')",
            "button:has-text('I agree')",
            "button[data-testid='uc-accept-all-button']",
        ]
        for sel in consent_selectors:
            btn = page.locator(sel)
            if await btn.count() > 0:
                await btn.first.click(timeout=3000)
                print(f"[v41] Clicked CMS consent: {sel}")
                break
    except Exception as e:
        print(f"[v41] CMS consent: {e}")

    await page.wait_for_timeout(3000)

    # Find and interact with the DCEP flight search form
    print("[v41] Looking for DCEP flight search form...")
    form_info = await page.evaluate("""() => {
        const result = {inputs: [], buttons: [], dcepConfig: null};

        // Check for DCEP widget
        const dcep = document.querySelector('.dcep-flight-manager');
        if (dcep) {
            result.dcepFound = true;
            result.dcepHTML = dcep.innerHTML.length;

            // Get all inputs
            const inputs = dcep.querySelectorAll('input');
            result.inputs = Array.from(inputs).map(i => ({
                type: i.type,
                placeholder: i.placeholder,
                value: i.value,
                id: i.id?.substring(0, 80),
                name: i.name,
            }));

            // Get all buttons
            const buttons = dcep.querySelectorAll('button, maui-button');
            result.buttons = Array.from(buttons).map(b => ({
                tag: b.tagName,
                text: b.textContent?.trim().substring(0, 50),
                class: b.className?.substring(0, 80),
            }));

            // Date inputs specifically
            const dateInputs = dcep.querySelectorAll('[class*=date], [data-date], [type=date]');
            result.dateElements = Array.from(dateInputs).map(d => ({
                tag: d.tagName,
                class: d.className?.substring(0, 80),
                text: d.textContent?.trim().substring(0, 100),
            }));
        } else {
            result.dcepFound = false;
            // Look for any flight search form
            const forms = document.querySelectorAll('form, [class*=search], [class*=flight]');
            result.otherForms = Array.from(forms).slice(0, 5).map(f => ({
                tag: f.tagName,
                class: f.className?.substring(0, 80),
                id: f.id,
                inputs: f.querySelectorAll('input').length,
            }));
        }

        return result;
    }""")

    print(f"[v41] Form info: {json.dumps(form_info, indent=2)[:1000]}")

    if form_info.get('dcepFound'):
        print("[v41] DCEP found! Filling form...")

        # Fill origin
        origin_filled = await page.evaluate("""async () => {
            const dcep = document.querySelector('.dcep-flight-manager');
            const inputs = dcep.querySelectorAll('input');
            const fromInput = Array.from(inputs).find(i => i.placeholder === 'From' || i.placeholder === 'From?');
            if (!fromInput) return {error: 'No From input'};

            fromInput.focus();
            fromInput.value = '';
            fromInput.dispatchEvent(new Event('input', {bubbles: true}));
            fromInput.dispatchEvent(new Event('change', {bubbles: true}));

            // Type "JFK"
            for (const char of 'JFK') {
                fromInput.value += char;
                fromInput.dispatchEvent(new Event('input', {bubbles: true}));
                await new Promise(r => setTimeout(r, 150));
            }

            // Wait for autocomplete
            await new Promise(r => setTimeout(r, 1500));

            // Find and click JFK option
            const options = dcep.querySelectorAll('li, [role=option], [class*=suggestion]');
            const jfk = Array.from(options).find(o =>
                o.textContent.includes('JFK') || o.textContent.includes('New York')
            );
            if (jfk) {
                jfk.click();
                return {success: true, selected: jfk.textContent.trim().substring(0, 80)};
            }
            return {error: 'No JFK option found', options: Array.from(options).map(o => o.textContent.trim().substring(0, 50)).slice(0, 10)};
        }""")
        print(f"[v41] Origin: {origin_filled}")

        await page.wait_for_timeout(1000)

        # Fill destination
        dest_filled = await page.evaluate("""async () => {
            const dcep = document.querySelector('.dcep-flight-manager');
            const inputs = dcep.querySelectorAll('input');
            const toInput = Array.from(inputs).find(i => i.placeholder === 'To' || i.placeholder === 'To?');
            if (!toInput) return {error: 'No To input'};

            toInput.focus();
            toInput.value = '';
            toInput.dispatchEvent(new Event('input', {bubbles: true}));

            for (const char of 'MUC') {
                toInput.value += char;
                toInput.dispatchEvent(new Event('input', {bubbles: true}));
                await new Promise(r => setTimeout(r, 150));
            }

            await new Promise(r => setTimeout(r, 1500));

            const options = dcep.querySelectorAll('li, [role=option], [class*=suggestion]');
            const muc = Array.from(options).find(o =>
                o.textContent.includes('MUC') || o.textContent.includes('Munich')
            );
            if (muc) {
                muc.click();
                return {success: true, selected: muc.textContent.trim().substring(0, 80)};
            }
            return {error: 'No MUC option found', options: Array.from(options).map(o => o.textContent.trim().substring(0, 50)).slice(0, 10)};
        }""")
        print(f"[v41] Destination: {dest_filled}")

        await page.wait_for_timeout(1000)

        # Find and fill DATE inputs
        print("[v41] Looking for date picker...")
        date_info = await page.evaluate("""() => {
            const dcep = document.querySelector('.dcep-flight-manager');
            const result = {elements: []};

            // Look for date-related elements
            const selectors = [
                'input[type=date]', 'input[placeholder*=date]', 'input[placeholder*=Date]',
                '.date-input', '.date-picker', '[class*=date]', '[data-date]',
                'button[class*=date]', 'div[class*=date]', 'span[class*=date]',
                '.departure-date', '.return-date', '.travel-date',
                '[class*=depart]', '[class*=return]',
            ];

            for (const sel of selectors) {
                const els = dcep ? dcep.querySelectorAll(sel) : document.querySelectorAll(sel);
                Array.from(els).forEach(el => {
                    result.elements.push({
                        selector: sel,
                        tag: el.tagName,
                        class: el.className?.substring(0, 100),
                        text: el.textContent?.trim().substring(0, 100),
                        value: el.value,
                        type: el.type,
                        role: el.getAttribute('role'),
                        ariaLabel: el.getAttribute('aria-label'),
                    });
                });
            }

            // Also check for all clickable elements in form
            if (dcep) {
                const clickables = dcep.querySelectorAll('[role=button], button, [tabindex="0"]');
                result.clickables = Array.from(clickables).map(c => ({
                    tag: c.tagName,
                    text: c.textContent?.trim().substring(0, 80),
                    class: c.className?.substring(0, 80),
                    role: c.getAttribute('role'),
                }));
            }

            return result;
        }""")
        print(f"[v41] Date elements: {json.dumps(date_info, indent=2)[:1500]}")

        # Try clicking on date area to open picker
        date_click_result = await page.evaluate("""async () => {
            const dcep = document.querySelector('.dcep-flight-manager');
            if (!dcep) return {error: 'No DCEP'};

            // Look for date input/button
            const dateEl = dcep.querySelector('.date-input, [class*=date-picker], [class*=departure], [aria-label*=date], [aria-label*=Date]');
            if (dateEl) {
                dateEl.click();
                await new Promise(r => setTimeout(r, 1000));

                // Check if a calendar appeared
                const calendar = document.querySelector('.calendar, [class*=calendar], [role=grid], [class*=datepicker], .date-picker-with-prices');
                return {
                    clicked: true,
                    clickedEl: dateEl.tagName + '.' + dateEl.className?.substring(0, 50),
                    calendarAppeared: !!calendar,
                    calendarClass: calendar?.className?.substring(0, 80),
                };
            }

            // Try clicking on text containing "Departure" or "Return" or "When"
            const allText = dcep.querySelectorAll('*');
            for (const el of allText) {
                const text = el.textContent?.trim();
                if (text && (text.includes('Departure') || text.includes('Return') || text.includes('When') || text.includes('Travel date'))) {
                    if (el.children.length < 3) {  // Likely a label/button, not container
                        el.click();
                        await new Promise(r => setTimeout(r, 1000));
                        const calendar = document.querySelector('.calendar, [class*=calendar], [role=grid], [class*=datepicker]');
                        return {
                            clicked: true,
                            clickedText: text.substring(0, 50),
                            calendarAppeared: !!calendar,
                        };
                    }
                }
            }

            return {error: 'No date element found to click'};
        }""")
        print(f"[v41] Date click: {json.dumps(date_click_result)[:500]}")

    else:
        print("[v41] DCEP not found — trying alternative approach")

        # Try to find the search form via different means
        alt_form = await page.evaluate("""() => {
            // Look for any booking widget
            const widgets = document.querySelectorAll('[class*=booking], [class*=search], [id*=booking], [id*=search]');
            return Array.from(widgets).slice(0, 10).map(w => ({
                tag: w.tagName,
                class: w.className?.substring(0, 100),
                id: w.id,
                text: w.textContent?.trim().substring(0, 200),
            }));
        }""")
        print(f"[v41] Alt forms: {json.dumps(alt_form, indent=2)[:1000]}")

    # --- Step 5: Try the search URL approach with proper session ---
    print("\n[v41] ===== APPROACH C: Direct SPA navigation with intercepted fetch =====")

    # Navigate to shop.lufthansa.com with search hash — but FIRST set the interceptors
    await page.evaluate("""() => {
        // Reset interception
        window.__intercepted = [];
    }""")

    # Navigate with search params
    search_url = "https://shop.lufthansa.com/lh/us/en/homepage#/search;type=rt;from=JFK;to=MUC;dep=2026-05-21;ret=2026-05-28;pax=a1;cabin=economy;li=en;co=us"
    print(f"[v41] Navigating to SPA search URL...")
    try:
        await page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"[v41] Nav: {e}")

    await page.wait_for_timeout(10000)

    # Check intercepted calls
    spa_calls = await page.evaluate("() => window.__intercepted || []")
    print(f"[v41] Intercepted {len(spa_calls)} calls during SPA nav:")
    for c in spa_calls:
        url = c.get('u', '')[:100]
        status = c.get('s', '?')
        method = c.get('m', '?')
        has_body = bool(c.get('b'))
        has_resp = bool(c.get('r'))
        print(f"  {method} {url} → {status} {'[body]' if has_body else ''} {'[resp]' if has_resp else ''}")
        if 'search' in url.lower() or 'offer' in url.lower() or 'air' in url.lower():
            print(f"    BODY: {c.get('b', '')[:200]}")
            print(f"    RESP: {c.get('r', '')[:200]}")

    # Check current page state
    current_state = await page.evaluate("""() => ({
        url: location.href,
        hash: location.hash,
        title: document.title,
        bodyText: document.body?.innerText?.substring(0, 500),
        sessionKeys: Array.from({length: sessionStorage.length}, (_, i) => sessionStorage.key(i)),
    })""")
    print(f"\n[v41] Current state:")
    print(f"  URL: {current_state['url']}")
    print(f"  Hash: {current_state['hash']}")
    print(f"  Title: {current_state['title']}")
    print(f"  Session keys: {current_state['sessionKeys']}")
    print(f"  Body: {current_state['bodyText'][:300]}")

    # --- Save results ---
    output = {
        "version": "v41",
        "js_analysis": js_analysis,
        "proxy_probe_results": header_combos,
        "form_info": form_info,
        "spa_intercepted_calls": spa_calls,
        "current_state": current_state,
    }

    out_path = CAPTURE_DIR / "lufthansa_v41_2026-04-21.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n[v41] Saved to {out_path}")

    await browser.close()
    await pw.stop()
    print("[v41] Done.")


if __name__ == "__main__":
    asyncio.run(main())
