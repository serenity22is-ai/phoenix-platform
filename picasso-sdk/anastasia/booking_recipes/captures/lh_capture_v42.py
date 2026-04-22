#!/usr/bin/env python3
"""Lufthansa API capture v42 — Extract SPA config from sessionStorage + find real main.js.

Key findings from v41:
  - main.10d2511a.js was Pinterest, not LH — need real SPA bundle
  - sessionStorage has 'configuration', 'Ama-Client-Ref', 'contextData', etc.
  - Date picker opens on CMS form
  - 406 from shop proxy is Akamai WAF, not API
"""

import asyncio
import json
from pathlib import Path

CDP_URL = "wss://brd-customer-hl_890ca773-zone-scraping_browser1:xy22gst47vzm@brd.superproxy.io:9222"
CAPTURE_DIR = Path(__file__).parent


async def main():
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    print("[v42] Connecting to Bright Data CDP...")
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    page = await browser.new_page()

    # --- Step 1: Navigate to shop.lufthansa.com ---
    print("[v42] Navigating to shop.lufthansa.com...")
    await page.goto("https://shop.lufthansa.com/lh/us/en/homepage", timeout=60000, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # Cookie consent
    try:
        btn = page.locator("#cm-acceptAll")
        if await btn.count() > 0:
            await btn.click(timeout=5000)
            await page.wait_for_timeout(2000)
    except Exception:
        pass

    await page.wait_for_timeout(8000)
    print(f"[v42] URL: {page.url}, Title: {await page.title()}")

    # --- Step 2: Extract ALL sessionStorage values ---
    print("\n[v42] ===== SESSION STORAGE DUMP =====")
    session_data = await page.evaluate("""() => {
        const data = {};
        for (let i = 0; i < sessionStorage.length; i++) {
            const key = sessionStorage.key(i);
            const val = sessionStorage.getItem(key);
            data[key] = val;  // Full value, not truncated
        }
        return data;
    }""")

    # Print key values
    important_keys = ['configuration', 'Ama-Client-Ref', 'contextData', 'gateway-auth-tokens',
                      'publicFacts', 'entryPointURL', 'uiStatus', 'airOffersAdvancedSearch']
    for key in important_keys:
        val = session_data.get(key)
        if val:
            print(f"\n  [{key}] ({len(val)} chars):")
            # Try to parse as JSON for pretty printing
            try:
                parsed = json.loads(val)
                print(f"    {json.dumps(parsed, indent=2)[:1000]}")
            except (json.JSONDecodeError, TypeError):
                print(f"    {val[:500]}")
        else:
            print(f"\n  [{key}] NOT FOUND")

    # Print remaining keys
    remaining = [k for k in session_data.keys() if k not in important_keys]
    print(f"\n  Other keys: {remaining}")

    # --- Step 3: Find the REAL Lufthansa SPA main.js ---
    print("\n[v42] ===== FINDING REAL SPA BUNDLE =====")
    scripts_info = await page.evaluate("""() => {
        const scripts = Array.from(document.querySelectorAll('script'));
        return scripts.map((s, i) => ({
            index: i,
            src: s.src || null,
            type: s.type || null,
            // For inline scripts, get first 200 chars
            inline: !s.src ? s.textContent?.substring(0, 300) : null,
            isModule: s.type === 'module',
        })).filter(s => s.src || (s.inline && s.inline.length > 10));
    }""")

    print(f"[v42] Found {len(scripts_info)} scripts:")
    lh_scripts = []
    for s in scripts_info:
        if s.get('src'):
            is_lh = 'lufthansa' in s['src'] or 'shop.' in s['src'] or '/lh/' in s['src']
            marker = ' <<<' if is_lh else ''
            print(f"  [{s['index']}] {s['src'][:120]}{marker}")
            if is_lh:
                lh_scripts.append(s)
        else:
            inline_preview = (s.get('inline') or '')[:80].replace('\n', ' ')
            print(f"  [{s['index']}] INLINE: {inline_preview}")

    # Also check for scripts loaded as link[rel=modulepreload] or other patterns
    more_scripts = await page.evaluate("""() => {
        const links = Array.from(document.querySelectorAll('link[rel=modulepreload], link[as=script]'));
        return links.map(l => ({href: l.href, rel: l.rel}));
    }""")
    if more_scripts:
        print(f"\n  Module preloads: {json.dumps(more_scripts)[:500]}")

    # --- Step 4: Fetch the Lufthansa SPA bundle and search for API config ---
    print("\n[v42] ===== ANALYZING SPA BUNDLE =====")
    if lh_scripts:
        main_url = lh_scripts[0]['src']
        print(f"[v42] Fetching LH script: {main_url}")
    else:
        # Try to find it by looking at performance entries
        main_url = await page.evaluate("""() => {
            const entries = performance.getEntriesByType('resource');
            const jsEntries = entries.filter(e =>
                e.name.includes('.js') &&
                (e.name.includes('shop.lufthansa') || e.name.includes('main'))
            );
            return jsEntries.map(e => e.name);
        }""")
        print(f"[v42] Performance JS entries: {main_url}")
        if isinstance(main_url, list) and main_url:
            main_url = main_url[0]

    if main_url and isinstance(main_url, str):
        bundle_analysis = await page.evaluate("""async (url) => {
            try {
                const resp = await fetch(url);
                const text = await resp.text();
                const results = {size: text.length, url};

                // Search for gateway/API URLs
                const patterns = {
                    'https_urls': /https?:\\/\\/[a-zA-Z0-9._-]+(?:\\/[a-zA-Z0-9._\\/-]*)?/g,
                    'api_paths': /["']\\/(?:api|v[0-9]|booking|search|one-booking)[^"']*["']/g,
                    'gateway_config': /gateway[A-Za-z]*["'\\s]*[:=]\\s*["']([^"']+)["']/g,
                    'base_url': /baseUrl["'\\s]*[:=]\\s*["']([^"']+)["']/g,
                    'air_offers': /air-offers/g,
                };

                for (const [name, regex] of Object.entries(patterns)) {
                    const matches = [...new Set((text.match(regex) || []).map(m => m.substring(0, 200)))];
                    if (matches.length) results[name] = matches.slice(0, 20);
                }

                // Get context around air-offers
                const idx = text.indexOf('air-offers');
                if (idx > -1) {
                    results.air_offers_context = text.substring(
                        Math.max(0, idx - 500), idx + 200
                    );
                }

                return results;
            } catch(e) {
                return {error: e.message};
            }
        }""", main_url)
        print(f"[v42] Bundle analysis:")
        for key, val in bundle_analysis.items():
            if key in ('size', 'url'):
                print(f"  {key}: {val}")
            elif isinstance(val, list):
                print(f"  {key}:")
                for v in val[:15]:
                    print(f"    {v}")
            elif isinstance(val, str):
                print(f"  {key}: {val[:300]}")
    else:
        print("[v42] Could not find SPA bundle URL")

    # --- Step 5: Check the 'configuration' for API endpoints ---
    print("\n[v42] ===== CONFIGURATION ANALYSIS =====")
    config_val = session_data.get('configuration')
    if config_val:
        try:
            config_obj = json.loads(config_val)
            # Deep search for URLs and paths
            def find_urls(obj, prefix=""):
                urls = []
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        urls.extend(find_urls(v, f"{prefix}.{k}"))
                elif isinstance(obj, list):
                    for i, v in enumerate(obj):
                        urls.extend(find_urls(v, f"{prefix}[{i}]"))
                elif isinstance(obj, str):
                    if '/' in obj or 'http' in obj:
                        urls.append((prefix, obj))
                return urls

            url_findings = find_urls(config_obj)
            print(f"  Found {len(url_findings)} URL-like values:")
            for path, val in url_findings:
                print(f"    {path}: {val}")
        except json.JSONDecodeError:
            print(f"  Could not parse: {config_val[:500]}")
    else:
        print("  No 'configuration' in sessionStorage")

    # --- Step 6: Check the contextData for gateway info ---
    print("\n[v42] ===== CONTEXT DATA =====")
    context_val = session_data.get('contextData')
    if context_val:
        try:
            ctx_obj = json.loads(context_val)
            print(f"  {json.dumps(ctx_obj, indent=2)[:1500]}")
        except json.JSONDecodeError:
            print(f"  {context_val[:500]}")

    # --- Step 7: Check Ama-Client-Ref ---
    print("\n[v42] ===== AMA-CLIENT-REF =====")
    ama_ref = session_data.get('Ama-Client-Ref')
    if ama_ref:
        print(f"  {ama_ref[:500]}")

    # --- Step 8: Try to read Angular state from DOM ---
    print("\n[v42] ===== ANGULAR TRANSFER STATE =====")
    transfer = await page.evaluate("""() => {
        // Check for Angular TransferState in a script tag
        const stateScripts = document.querySelectorAll('script#serverApp-state, script[type="application/json"]');
        const results = [];
        for (const s of stateScripts) {
            results.push({
                id: s.id,
                type: s.type,
                text: s.textContent?.substring(0, 2000),
            });
        }

        // Also check for __NEXT_DATA__ or similar
        const nextData = document.querySelector('script#__NEXT_DATA__');
        if (nextData) results.push({id: '__NEXT_DATA__', text: nextData.textContent?.substring(0, 2000)});

        // Check for Angular-specific elements
        const appRoot = document.querySelector('app-root, lh-app, [ng-version]');
        if (appRoot) {
            results.push({
                tagName: appRoot.tagName,
                ngVersion: appRoot.getAttribute('ng-version'),
                attrs: Array.from(appRoot.attributes).map(a => `${a.name}=${a.value}`).join(', '),
            });
        }

        return results;
    }""")
    for t in transfer:
        print(f"  {json.dumps(t)[:500]}")

    # --- Step 9: Try calling api-shop with Ama-Client-Ref header from session ---
    if ama_ref and token:
        print("\n[v42] ===== TRYING WITH AMA-CLIENT-REF =====")
        body = json.dumps({
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

        search_result = await page.evaluate("""async (args) => {
            const {token, amaRef, body} = args;
            const urls = [
                'https://api-shop.lufthansa.com/v2/search/air-offers',
                'https://api-shop.lufthansa.com/v1/one-booking/search/air-offers',
            ];
            const results = [];

            for (const url of urls) {
                try {
                    const resp = await fetch(url, {
                        method: 'POST',
                        headers: {
                            'Authorization': 'Bearer ' + token,
                            'Content-Type': 'application/json',
                            'Accept': 'application/json',
                            'Ama-Client-Ref': amaRef,
                        },
                        body,
                    });
                    const text = await resp.text();
                    results.push({
                        url,
                        status: resp.status,
                        ct: resp.headers.get('content-type'),
                        preview: text.substring(0, 500),
                    });
                } catch(e) {
                    results.push({url, error: e.message});
                }
            }

            return results;
        }""", {"token": token, "amaRef": ama_ref, "body": body})

        for r in search_result:
            print(f"  {r.get('url', '')[:80]} → {r.get('status', 'ERR')}")
            if r.get('preview'):
                print(f"    {r['preview'][:200]}")
            if r.get('error'):
                print(f"    ERROR: {r['error']}")

    # --- Save ---
    output = {
        "version": "v42",
        "session_storage_keys": list(session_data.keys()),
        "session_storage": {k: v[:2000] if isinstance(v, str) else v for k, v in session_data.items()},
        "scripts": scripts_info,
        "transfer_state": transfer,
    }
    out_path = CAPTURE_DIR / "lufthansa_v42_2026-04-21.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n[v42] Saved to {out_path}")

    await browser.close()
    await pw.stop()
    print("[v42] Done.")


if __name__ == "__main__":
    asyncio.run(main())
