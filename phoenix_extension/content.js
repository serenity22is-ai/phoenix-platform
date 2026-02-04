// Phoenix Content Script — Consent-gated DOM extraction (Build #81)
(function() {
  "use strict";

  // Skip extension pages, about:, chrome: URLs
  if (window.location.protocol === "chrome-extension:" ||
      window.location.protocol === "about:" ||
      window.location.protocol === "chrome:") return;

  // ---------------------------------------------------------------------------
  // Configuration
  // ---------------------------------------------------------------------------

  const SEARCH_ENGINES = {
    "google.com": { queryParam: "q", resultSelector: "#search .g", countSelector: "#result-stats" },
    "bing.com": { queryParam: "q", resultSelector: ".b_algo", countSelector: ".sb_count" },
    "yahoo.com": { queryParam: "p", resultSelector: ".algo", countSelector: ".compPagination" },
    "duckduckgo.com": { queryParam: "q", resultSelector: ".result", countSelector: null }
  };

  const AD_SELECTORS = [
    "[data-text-ad]", ".ads-ad", "[class*='sponsor']", "[class*='Sponsor']",
    "[data-ad-slot]", "[id*='google_ads']", ".ad-container", ".advertisement",
    "iframe[src*='doubleclick']", "iframe[src*='googlesyndication']",
    "[data-ad]", ".promoted-post", "[class*='promoted']"
  ];

  const PRICE_SELECTORS = [
    "[itemprop='price']", "[data-price]", ".price", ".product-price",
    ".a-price .a-offscreen", "#priceblock_ourprice", ".price-current",
    "[class*='price']"
  ];

  // ---------------------------------------------------------------------------
  // Utility — send event to background service worker
  // ---------------------------------------------------------------------------

  function sendEvent(eventType, data) {
    try {
      chrome.runtime.sendMessage({
        type: "phoenix_event",
        data: { event_type: eventType, url: window.location.href, ...data }
      });
    } catch (e) {
      // Extension context invalidated — silently ignore
    }
  }

  // ---------------------------------------------------------------------------
  // Visual extraction indicator
  // ---------------------------------------------------------------------------

  function showExtractionIndicator() {
    if (document.getElementById("phoenix-indicator")) return;
    const dot = document.createElement("div");
    dot.id = "phoenix-indicator";
    dot.style.cssText =
      "position:fixed;bottom:8px;right:8px;width:8px;height:8px;" +
      "border-radius:50%;background:#1a73e8;opacity:0.7;z-index:2147483647;" +
      "pointer-events:none;transition:opacity 0.5s;";
    document.body.appendChild(dot);
    setTimeout(() => { dot.style.opacity = "0"; }, 1500);
    setTimeout(() => { dot.remove(); }, 2000);
  }

  // ---------------------------------------------------------------------------
  // Search query extraction
  // ---------------------------------------------------------------------------

  function extractSearchQuery() {
    const hostname = window.location.hostname.replace("www.", "");
    for (const [domain, config] of Object.entries(SEARCH_ENGINES)) {
      if (hostname.includes(domain)) {
        const params = new URLSearchParams(window.location.search);
        const query = params.get(config.queryParam);
        if (!query) return;

        let resultCount = null;
        if (config.countSelector) {
          const el = document.querySelector(config.countSelector);
          if (el) resultCount = el.textContent.trim();
        }

        const results = document.querySelectorAll(config.resultSelector);

        sendEvent("search_query", {
          query: query,
          engine: domain,
          result_count: resultCount,
          organic_results: results.length,
          title: document.title
        });
        return;
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Ad extraction
  // ---------------------------------------------------------------------------

  function extractAds() {
    const ads = [];
    for (const selector of AD_SELECTORS) {
      const elements = document.querySelectorAll(selector);
      for (const el of elements) {
        if (ads.length >= 20) break; // cap at 20 ads per page
        const link = el.querySelector("a[href]");
        const text = el.textContent?.substring(0, 500)?.trim();
        if (!text || text.length < 5) continue;

        ads.push({
          advertiser: link?.hostname || "unknown",
          ad_text: text,
          ad_destination_url: link?.href || null,
          ad_position: getAdPosition(el),
          ad_format: getAdFormat(el)
        });
      }
    }
    if (ads.length > 0) {
      sendEvent("ad_impression", {
        ads: ads,
        ad_count: ads.length,
        page_url: window.location.href,
        title: document.title
      });
    }
  }

  function getAdPosition(el) {
    const rect = el.getBoundingClientRect();
    if (rect.top < 300) return "top";
    if (rect.top > window.innerHeight) return "below_fold";
    return "middle";
  }

  function getAdFormat(el) {
    if (el.tagName === "IFRAME") return "iframe";
    if (el.querySelector("img")) return "display";
    if (el.querySelector("video")) return "video";
    return "text";
  }

  // ---------------------------------------------------------------------------
  // Price extraction
  // ---------------------------------------------------------------------------

  function extractPrices() {
    const prices = [];

    // Try schema.org Product microdata first
    const productSchema = document.querySelector('[itemtype*="schema.org/Product"]');
    if (productSchema) {
      const name = productSchema.querySelector('[itemprop="name"]')?.textContent?.trim();
      const priceEl = productSchema.querySelector('[itemprop="price"]');
      const price = priceEl?.content || priceEl?.textContent?.trim();
      const currency = productSchema.querySelector('[itemprop="priceCurrency"]')?.content;
      const seller = productSchema.querySelector('[itemprop="seller"] [itemprop="name"]')?.textContent?.trim();

      if (name && price) {
        prices.push({ product_title: name, price: price, currency: currency, seller: seller });
      }
    }

    // Try JSON-LD
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
            seller: data.brand?.name
          });
        }
      } catch (e) {
        // Ignore JSON parse errors
      }
    }

    // Fallback: CSS selectors
    if (prices.length === 0) {
      for (const selector of PRICE_SELECTORS) {
        const elements = document.querySelectorAll(selector);
        for (const el of elements) {
          if (prices.length >= 10) break;
          const text = el.textContent?.trim();
          const priceMatch = text?.match(/[\$\£\€\¥]?\s*[\d,]+\.?\d{0,2}/);
          if (priceMatch) {
            prices.push({
              product_title: document.title,
              price: priceMatch[0],
              selector_matched: selector
            });
          }
        }
      }
    }

    if (prices.length > 0) {
      sendEvent("price_observation", {
        prices: prices,
        price_count: prices.length,
        title: document.title
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Social signal extraction
  // ---------------------------------------------------------------------------

  function extractSocialSignals() {
    const hostname = window.location.hostname.replace("www.", "");
    const socialPlatforms = {
      "facebook.com": "facebook",
      "twitter.com": "twitter",
      "x.com": "twitter",
      "reddit.com": "reddit",
      "linkedin.com": "linkedin",
      "instagram.com": "instagram",
      "tiktok.com": "tiktok"
    };

    let platform = null;
    for (const [domain, name] of Object.entries(socialPlatforms)) {
      if (hostname.includes(domain)) { platform = name; break; }
    }
    if (!platform) return;

    // Extract engagement metrics based on platform
    const signals = { platform: platform, title: document.title };

    // Generic engagement selectors
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

    // Count visible posts/items
    const postSelectors = {
      facebook: "[role='article']",
      twitter: "article[data-testid='tweet']",
      reddit: ".Post, [data-testid='post-container']",
      linkedin: ".feed-shared-update-v2",
      instagram: "article",
      tiktok: "[data-e2e='recommend-list-item-container']"
    };

    const postSelector = postSelectors[platform];
    if (postSelector) {
      signals.visible_posts = document.querySelectorAll(postSelector).length;
    }

    sendEvent("social_signal", signals);
  }

  // ---------------------------------------------------------------------------
  // Main extraction — consent-gated
  // ---------------------------------------------------------------------------

  function runExtractions() {
    chrome.storage.local.get(["consent_state"], (data) => {
      const consent = data.consent_state || {};

      // Do nothing if onboarding not completed
      if (!consent.onboarding_completed) return;

      let extracted = false;

      if (consent.search_queries) {
        try { extractSearchQuery(); extracted = true; } catch (e) { /* silent */ }
      }
      if (consent.ad_impressions) {
        try { extractAds(); extracted = true; } catch (e) { /* silent */ }
      }
      if (consent.price_observations) {
        try { extractPrices(); extracted = true; } catch (e) { /* silent */ }
      }
      if (consent.social_signals) {
        try { extractSocialSignals(); extracted = true; } catch (e) { /* silent */ }
      }

      if (extracted) {
        showExtractionIndicator();
      }
    });
  }

  // Run after DOM is ready
  if (document.readyState === "complete" || document.readyState === "interactive") {
    setTimeout(runExtractions, 500);
  } else {
    document.addEventListener("DOMContentLoaded", () => setTimeout(runExtractions, 500));
  }

  // ---------------------------------------------------------------------------
  // SPA navigation detection via MutationObserver
  // ---------------------------------------------------------------------------

  let lastUrl = window.location.href;
  const observer = new MutationObserver(() => {
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      setTimeout(runExtractions, 1000);
    }
  });
  observer.observe(document.body || document.documentElement, { childList: true, subtree: true });
})();
