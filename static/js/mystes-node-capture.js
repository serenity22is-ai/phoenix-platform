/**
 * MYSTES WebView Event Capture (Build #91)
 *
 * Simplified port of mystes_extension/content.js extraction logic
 * for the Capacitor WebView context. Instead of chrome.runtime.sendMessage(),
 * events are routed to MystesNodeClient.captureEvent().
 *
 * Requires: mystes-node-client.js loaded first (window.MystesNodeClient)
 *
 * Usage:
 *   const capture = new MystesNodeCapture(nodeClient);
 *   capture.start();   // Begin monitoring page navigations + DOM
 *   capture.stop();    // Stop monitoring
 */

(function (root) {
  "use strict";

  // -------------------------------------------------------------------------
  // Extraction configuration (mirrors content.js)
  // -------------------------------------------------------------------------

  const SEARCH_ENGINES = {
    "google.com": { queryParam: "q", resultSelector: "#search .g", countSelector: "#result-stats" },
    "bing.com": { queryParam: "q", resultSelector: ".b_algo", countSelector: ".sb_count" },
    "yahoo.com": { queryParam: "p", resultSelector: ".algo", countSelector: ".compPagination" },
    "duckduckgo.com": { queryParam: "q", resultSelector: ".result", countSelector: null },
  };

  const AD_SELECTORS = [
    "[data-text-ad]", ".ads-ad", "[class*='sponsor']", "[class*='Sponsor']",
    "[data-ad-slot]", "[id*='google_ads']", ".ad-container", ".advertisement",
    "iframe[src*='doubleclick']", "iframe[src*='googlesyndication']",
    "[data-ad]", ".promoted-post", "[class*='promoted']",
  ];

  const PRICE_SELECTORS = [
    "[itemprop='price']", "[data-price]", ".price", ".product-price",
    ".a-price .a-offscreen", "#priceblock_ourprice", ".price-current",
    "[class*='price']",
  ];

  const SOCIAL_PLATFORMS = {
    "facebook.com": "facebook",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "reddit.com": "reddit",
    "linkedin.com": "linkedin",
    "instagram.com": "instagram",
    "tiktok.com": "tiktok",
  };

  const POST_SELECTORS = {
    facebook: "[role='article']",
    twitter: "article[data-testid='tweet']",
    reddit: ".Post, [data-testid='post-container']",
    linkedin: ".feed-shared-update-v2",
    instagram: "article",
    tiktok: "[data-e2e='recommend-list-item-container']",
  };

  // -------------------------------------------------------------------------
  // MystesNodeCapture
  // -------------------------------------------------------------------------

  class MystesNodeCapture {
    /**
     * @param {MystesNodeClient} nodeClient  The node client to send events to
     * @param {object} [options]
     * @param {object} [options.consent]  Consent flags: { search_queries, price_observations, ad_impressions, social_signals, browsing_data }
     */
    constructor(nodeClient, options = {}) {
      this._client = nodeClient;
      this._consent = options.consent || {};
      this._running = false;
      this._lastUrl = null;
      this._observer = null;
      this._popstateHandler = null;
    }

    /**
     * Update consent flags dynamically (e.g., after user changes settings).
     * @param {object} consent
     */
    updateConsent(consent) {
      this._consent = consent || {};
    }

    /**
     * Start monitoring page navigations and extracting data.
     */
    start() {
      if (this._running) return;
      this._running = true;
      this._lastUrl = window.location.href;

      // Run initial extraction after short delay (DOM settle)
      setTimeout(() => this._runExtractions(), 500);

      // Monitor URL changes (SPA navigation)
      this._popstateHandler = () => {
        if (window.location.href !== this._lastUrl) {
          this._lastUrl = window.location.href;
          setTimeout(() => this._runExtractions(), 1000);
        }
      };
      window.addEventListener("popstate", this._popstateHandler);

      // MutationObserver for SPA route changes that don't fire popstate
      if (document.body || document.documentElement) {
        this._observer = new MutationObserver(() => {
          if (window.location.href !== this._lastUrl) {
            this._lastUrl = window.location.href;
            setTimeout(() => this._runExtractions(), 1000);
          }
        });
        this._observer.observe(document.body || document.documentElement, {
          childList: true,
          subtree: true,
        });
      }

      console.log("[MystesCapture] Started WebView event capture");
    }

    /**
     * Stop monitoring.
     */
    stop() {
      if (!this._running) return;
      this._running = false;

      if (this._popstateHandler) {
        window.removeEventListener("popstate", this._popstateHandler);
        this._popstateHandler = null;
      }

      if (this._observer) {
        this._observer.disconnect();
        this._observer = null;
      }

      console.log("[MystesCapture] Stopped WebView event capture");
    }

    // -----------------------------------------------------------------------
    // Extraction orchestrator
    // -----------------------------------------------------------------------

    _runExtractions() {
      if (!this._running) return;

      const url = window.location.href;

      // Skip internal/extension pages
      if (url.startsWith("about:") || url.startsWith("blob:") || url.startsWith("data:")) {
        return;
      }

      // Page visit (requires browsing_data consent)
      if (this._consent.browsing_data) {
        this._capturePageVisit();
      }

      // Search query extraction
      if (this._consent.search_queries) {
        try { this._extractSearchQuery(); } catch (e) { /* silent */ }
      }

      // Ad extraction
      if (this._consent.ad_impressions) {
        try { this._extractAds(); } catch (e) { /* silent */ }
      }

      // Price extraction
      if (this._consent.price_observations) {
        try { this._extractPrices(); } catch (e) { /* silent */ }
      }

      // Social signals
      if (this._consent.social_signals) {
        try { this._extractSocialSignals(); } catch (e) { /* silent */ }
      }
    }

    // -----------------------------------------------------------------------
    // Page visit capture
    // -----------------------------------------------------------------------

    _capturePageVisit() {
      this._client.captureEvent({
        event_type: "page_visit",
        url: window.location.href,
        title: document.title,
        domain: window.location.hostname,
      });
    }

    // -----------------------------------------------------------------------
    // Search query extraction (mirrors content.js extractSearchQuery)
    // -----------------------------------------------------------------------

    _extractSearchQuery() {
      const hostname = window.location.hostname.replace("www.", "");
      for (const [domain, config] of Object.entries(SEARCH_ENGINES)) {
        if (!hostname.includes(domain)) continue;

        const params = new URLSearchParams(window.location.search);
        const query = params.get(config.queryParam);
        if (!query) return;

        let resultCount = null;
        if (config.countSelector) {
          const el = document.querySelector(config.countSelector);
          if (el) resultCount = el.textContent.trim();
        }

        const results = document.querySelectorAll(config.resultSelector);

        this._client.captureEvent({
          event_type: "search_query",
          url: window.location.href,
          query: query,
          engine: domain,
          result_count: resultCount,
          organic_results: results.length,
          title: document.title,
        });
        return;
      }
    }

    // -----------------------------------------------------------------------
    // Ad extraction (mirrors content.js extractAds)
    // -----------------------------------------------------------------------

    _extractAds() {
      const ads = [];
      for (const selector of AD_SELECTORS) {
        const elements = document.querySelectorAll(selector);
        for (const el of elements) {
          if (ads.length >= 20) break;
          const link = el.querySelector("a[href]");
          const text = el.textContent?.substring(0, 500)?.trim();
          if (!text || text.length < 5) continue;

          ads.push({
            advertiser: link?.hostname || "unknown",
            ad_text: text,
            ad_destination_url: link?.href || null,
            ad_position: this._getAdPosition(el),
            ad_format: this._getAdFormat(el),
          });
        }
      }
      if (ads.length > 0) {
        this._client.captureEvent({
          event_type: "ad_impression",
          url: window.location.href,
          ads: ads,
          ad_count: ads.length,
          title: document.title,
        });
      }
    }

    _getAdPosition(el) {
      const rect = el.getBoundingClientRect();
      if (rect.top < 300) return "top";
      if (rect.top > window.innerHeight) return "below_fold";
      return "middle";
    }

    _getAdFormat(el) {
      if (el.tagName === "IFRAME") return "iframe";
      if (el.querySelector("img")) return "display";
      if (el.querySelector("video")) return "video";
      return "text";
    }

    // -----------------------------------------------------------------------
    // Price extraction (mirrors content.js extractPrices)
    // -----------------------------------------------------------------------

    _extractPrices() {
      const prices = [];

      // Schema.org Product microdata
      const productSchema = document.querySelector('[itemtype*="schema.org/Product"]');
      if (productSchema) {
        const name = productSchema.querySelector('[itemprop="name"]')?.textContent?.trim();
        const priceEl = productSchema.querySelector('[itemprop="price"]');
        const price = priceEl?.content || priceEl?.textContent?.trim();
        const currency = productSchema.querySelector('[itemprop="priceCurrency"]')?.content;
        const seller = productSchema.querySelector('[itemprop="seller"] [itemprop="name"]')?.textContent?.trim();
        if (name && price) {
          prices.push({ product_title: name, price, currency, seller });
        }
      }

      // JSON-LD
      const scripts = document.querySelectorAll('script[type="application/ld+json"]');
      for (const script of scripts) {
        try {
          const data = JSON.parse(script.textContent);
          if (data["@type"] === "Product" && data.offers) {
            const offer = Array.isArray(data.offers) ? data.offers[0] : data.offers;
            prices.push({
              product_title: data.name,
              price: offer.price || offer.lowPrice,
              currency: offer.priceCurrency,
              seller: data.brand?.name,
            });
          }
        } catch (e) {
          // Ignore JSON parse errors
        }
      }

      // CSS selector fallback
      if (prices.length === 0) {
        for (const selector of PRICE_SELECTORS) {
          const elements = document.querySelectorAll(selector);
          for (const el of elements) {
            if (prices.length >= 10) break;
            const text = el.textContent?.trim();
            const priceMatch = text?.match(/[$£€¥]?\s*[\d,]+\.?\d{0,2}/);
            if (priceMatch) {
              prices.push({
                product_title: document.title,
                price: priceMatch[0],
                selector_matched: selector,
              });
            }
          }
        }
      }

      if (prices.length > 0) {
        this._client.captureEvent({
          event_type: "price_observation",
          url: window.location.href,
          prices: prices,
          price_count: prices.length,
          title: document.title,
        });
      }
    }

    // -----------------------------------------------------------------------
    // Social signal extraction (mirrors content.js extractSocialSignals)
    // -----------------------------------------------------------------------

    _extractSocialSignals() {
      const hostname = window.location.hostname.replace("www.", "");
      let platform = null;
      for (const [domain, name] of Object.entries(SOCIAL_PLATFORMS)) {
        if (hostname.includes(domain)) { platform = name; break; }
      }
      if (!platform) return;

      const signals = { platform, title: document.title };

      const likeEls = document.querySelectorAll(
        '[aria-label*="like"], [aria-label*="Like"], [data-testid*="like"]'
      );
      const shareEls = document.querySelectorAll(
        '[aria-label*="share"], [aria-label*="Share"], [aria-label*="retweet"], [aria-label*="Retweet"]'
      );
      const commentEls = document.querySelectorAll(
        '[aria-label*="comment"], [aria-label*="Comment"], [aria-label*="reply"], [aria-label*="Reply"]'
      );

      signals.like_elements = likeEls.length;
      signals.share_elements = shareEls.length;
      signals.comment_elements = commentEls.length;

      const postSelector = POST_SELECTORS[platform];
      if (postSelector) {
        signals.visible_posts = document.querySelectorAll(postSelector).length;
      }

      this._client.captureEvent({
        event_type: "social_signal",
        url: window.location.href,
        ...signals,
      });
    }
  }

  // -------------------------------------------------------------------------
  // Export
  // -------------------------------------------------------------------------

  root.MystesNodeCapture = MystesNodeCapture;

})(typeof window !== "undefined" ? window : globalThis);
