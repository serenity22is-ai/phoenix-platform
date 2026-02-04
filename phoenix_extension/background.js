// Phoenix Extension — Background Service Worker (Build #91)
// Manages connection to local node service, buffers events, syncs periodically,
// and handles consent-gated dynamic content script registration.
//
// Build #91: Added direct-backend fallback mode. When localhost:19750 (the
// local node daemon) is unreachable, the extension talks directly to the
// Phoenix backend using the user's helper_token. This enables the extension
// to function on devices without node_service.py installed.

const LOCAL_SERVICE_URL = "http://localhost:19750";
const MAX_BUFFER = 200;
const FLUSH_INTERVAL_MS = 10000;
const STATUS_CHECK_INTERVAL_MS = 60000;
const CONFIG_REFRESH_INTERVAL_MS = 300000;
const CONTENT_SCRIPT_ID = "phoenix-content";

// Direct-backend fallback keys (Build #91)
const BACKEND_URL_KEY = "phoenix_backend_url";
const HELPER_TOKEN_KEY = "phoenix_helper_token";
const DIRECT_MODE_CONSECUTIVE_FAILURES = 3;

// State
let eventBuffer = [];
let serviceConnected = false;
let directMode = false;            // Build #91: true = bypass local daemon
let directBackendUrl = "";         // Build #91: cached backend URL
let directHelperToken = "";        // Build #91: cached helper token
let localCheckFailures = 0;        // Build #91: consecutive local check failures
let extractionConfig = null;
let consentState = null;
let stats = { captured: 0, sent: 0, errors: 0 };

// ---------------------------------------------------------------------------
// Build #91 — Load direct-mode credentials from storage
// ---------------------------------------------------------------------------

async function loadDirectModeCredentials() {
  const data = await chrome.storage.local.get([BACKEND_URL_KEY, HELPER_TOKEN_KEY]);
  directBackendUrl = data[BACKEND_URL_KEY] || "";
  directHelperToken = data[HELPER_TOKEN_KEY] || "";
}

function canUseDirectMode() {
  return directBackendUrl && directHelperToken;
}

// ---------------------------------------------------------------------------
// Badge management
// ---------------------------------------------------------------------------

async function updateBadge() {
  const data = await chrome.storage.local.get(["consent_state"]);
  const consent = data.consent_state;

  if (!consent || !consent.onboarding_completed) {
    // Not onboarded yet
    chrome.action.setBadgeBackgroundColor({ color: "#FF9800" });
    chrome.action.setBadgeText({ text: "!" });
    return;
  }

  if (serviceConnected || directMode) {
    chrome.action.setBadgeBackgroundColor({ color: "#4CAF50" });
    chrome.action.setBadgeText({ text: directMode ? "D" : "ON" });
  } else {
    chrome.action.setBadgeBackgroundColor({ color: "#9E9E9E" });
    chrome.action.setBadgeText({ text: "OFF" });
  }
}

// ---------------------------------------------------------------------------
// Dynamic content script registration
// ---------------------------------------------------------------------------

async function registerContentScriptIfConsented() {
  const data = await chrome.storage.local.get(["consent_state"]);
  const consent = data.consent_state;
  consentState = consent;

  // Determine if any extraction category is enabled
  const extractionCategories = [
    "search_queries", "price_observations", "ad_impressions",
    "social_signals", "browsing_data", "business_data"
  ];
  const anyEnabled = consent && consent.onboarding_completed &&
    extractionCategories.some((key) => consent[key]);

  try {
    // Always try to unregister first (ignore error if not registered)
    await chrome.scripting.unregisterContentScripts({ ids: [CONTENT_SCRIPT_ID] })
      .catch(() => {});

    if (anyEnabled) {
      await chrome.scripting.registerContentScripts([{
        id: CONTENT_SCRIPT_ID,
        matches: ["<all_urls>"],
        js: ["content.js"],
        runAt: "document_idle",
        allFrames: false
      }]);
      console.log("[Phoenix] Content script registered (consent active)");
    } else {
      console.log("[Phoenix] Content script unregistered (no consent or onboarding incomplete)");
    }
  } catch (error) {
    console.warn("[Phoenix] Content script registration error:", error.message);
  }

  await updateBadge();
}

// ---------------------------------------------------------------------------
// First-run detection
// ---------------------------------------------------------------------------

chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    // Fresh install — open onboarding wizard
    chrome.tabs.create({ url: chrome.runtime.getURL("onboarding.html") });
    console.log("[Phoenix] First install — opening onboarding");
  }

  if (details.reason === "update") {
    console.log("[Phoenix] Extension updated to", chrome.runtime.getManifest().version);
  }

  // Register/unregister content script based on current consent
  registerContentScriptIfConsented();
});

// ---------------------------------------------------------------------------
// Status check — ping local service every 60 seconds
// ---------------------------------------------------------------------------

async function checkServiceStatus() {
  try {
    const response = await fetch(`${LOCAL_SERVICE_URL}/status`, {
      method: "GET",
      headers: { "Accept": "application/json" },
      signal: AbortSignal.timeout(5000)
    });

    if (!response.ok) {
      throw new Error(`Status check failed: ${response.status}`);
    }

    const data = await response.json();
    serviceConnected = true;
    directMode = false;
    localCheckFailures = 0;
    await updateBadge();

    // Store status data for popup
    await chrome.storage.local.set({ lastStatus: data, lastStatusTime: Date.now() });

    return data;
  } catch (error) {
    serviceConnected = false;
    localCheckFailures++;

    // Build #91: Switch to direct mode after consecutive failures
    if (localCheckFailures >= DIRECT_MODE_CONSECUTIVE_FAILURES && canUseDirectMode()) {
      if (!directMode) {
        directMode = true;
        console.log("[Phoenix] Switching to direct-backend mode (local daemon unreachable)");
      }
    }

    await updateBadge();
    console.warn("[Phoenix] Service unreachable:", error.message,
      directMode ? "(direct mode active)" : "");
    return null;
  }
}

// ---------------------------------------------------------------------------
// Config fetch — retrieve extraction config from local service or backend
// ---------------------------------------------------------------------------

async function fetchConfig() {
  // Build #91: Choose endpoint based on mode
  const configUrl = directMode
    ? `${directBackendUrl}/api/v1/node/config`
    : `${LOCAL_SERVICE_URL}/config`;

  const headers = { "Accept": "application/json" };
  if (directMode) {
    headers["X-Helper-Token"] = directHelperToken;
  }

  try {
    const response = await fetch(configUrl, {
      method: "GET",
      headers,
      signal: AbortSignal.timeout(5000)
    });

    if (!response.ok) {
      throw new Error(`Config fetch failed: ${response.status}`);
    }

    const data = await response.json();
    extractionConfig = data;

    // Persist config
    await chrome.storage.local.set({ extractionConfig: data });
    console.log("[Phoenix] Config refreshed" + (directMode ? " (direct)" : ""));

    return data;
  } catch (error) {
    console.warn("[Phoenix] Config fetch failed:", error.message);

    // Try to load cached config
    if (!extractionConfig) {
      const stored = await chrome.storage.local.get("extractionConfig");
      if (stored.extractionConfig) {
        extractionConfig = stored.extractionConfig;
      }
    }

    return null;
  }
}

// ---------------------------------------------------------------------------
// Event buffer flush — POST buffered events to local service or backend
// ---------------------------------------------------------------------------

async function flushBuffer() {
  if (eventBuffer.length === 0) return;
  if (!serviceConnected && !directMode) return;

  const batch = eventBuffer.splice(0, eventBuffer.length);
  const batchSize = batch.length;

  try {
    let response;

    if (directMode) {
      // Build #91: Direct-backend flush
      response = await fetch(`${directBackendUrl}/api/v1/node/data/ingest`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "X-Helper-Token": directHelperToken
        },
        body: JSON.stringify({
          events: batch,
          source: "extension_direct"
        }),
        signal: AbortSignal.timeout(10000)
      });
    } else {
      // Local daemon flush
      response = await fetch(`${LOCAL_SERVICE_URL}/events`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
        body: JSON.stringify({ events: batch, count: batchSize }),
        signal: AbortSignal.timeout(10000)
      });
    }

    if (!response.ok) {
      throw new Error(`Flush failed: ${response.status}`);
    }

    const result = await response.json();
    stats.sent += batchSize;
    console.log(`[Phoenix] Flushed ${batchSize} events${directMode ? " (direct)" : ""}. Total sent: ${stats.sent}`);

    // Persist stats
    await chrome.storage.local.set({ stats });

    return result;
  } catch (error) {
    // Put events back at the front of the buffer
    eventBuffer.unshift(...batch);

    // Trim if over max
    if (eventBuffer.length > MAX_BUFFER) {
      const dropped = eventBuffer.length - MAX_BUFFER;
      eventBuffer = eventBuffer.slice(0, MAX_BUFFER);
      console.warn(`[Phoenix] Buffer overflow, dropped ${dropped} oldest events`);
    }

    stats.errors++;
    console.warn("[Phoenix] Flush failed:", error.message);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Message handler — receives events from content.js + consent updates
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "phoenix_event") {
    const event = {
      ...message.data,
      tab_url: sender.tab?.url,
      tab_id: sender.tab?.id,
      captured_at: new Date().toISOString()
    };

    eventBuffer.push(event);
    stats.captured++;

    // Auto-flush if buffer is full
    if (eventBuffer.length >= MAX_BUFFER) {
      flushBuffer();
    }

    sendResponse({ accepted: true });
  }

  if (message.type === "get_status") {
    sendResponse({
      connected: serviceConnected,
      direct_mode: directMode,
      stats: { ...stats },
      config: extractionConfig,
      buffer_size: eventBuffer.length
    });
  }

  if (message.type === "consent_updated") {
    // Consent changed from onboarding or options page
    consentState = message.consent_state || null;
    registerContentScriptIfConsented();
    sendResponse({ ok: true });
  }

  // Build #91: Store backend credentials from onboarding
  if (message.type === "set_backend_credentials") {
    const { backend_url, helper_token } = message;
    if (backend_url && helper_token) {
      directBackendUrl = backend_url;
      directHelperToken = helper_token;
      chrome.storage.local.set({
        [BACKEND_URL_KEY]: backend_url,
        [HELPER_TOKEN_KEY]: helper_token
      });
      console.log("[Phoenix] Backend credentials stored for direct mode");
      sendResponse({ ok: true });
    } else {
      sendResponse({ ok: false, error: "Missing backend_url or helper_token" });
    }
  }

  return true; // keep channel open for async response
});

// ---------------------------------------------------------------------------
// Listen for consent changes via chrome.storage
// ---------------------------------------------------------------------------

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName === "local" && changes.consent_state) {
    consentState = changes.consent_state.newValue;
    registerContentScriptIfConsented();
  }
});

// ---------------------------------------------------------------------------
// Page visit tracking via webNavigation (consent-gated)
// ---------------------------------------------------------------------------

chrome.webNavigation.onCompleted.addListener((details) => {
  // Only track main frame navigations
  if (details.frameId !== 0) return;

  // Skip internal pages
  if (details.url.startsWith("chrome://") ||
      details.url.startsWith("chrome-extension://") ||
      details.url.startsWith("about:") ||
      details.url.startsWith("edge://")) {
    return;
  }

  // Consent gate — only track if browsing_data is enabled
  if (!consentState || !consentState.onboarding_completed || !consentState.browsing_data) {
    return;
  }

  eventBuffer.push({
    event_type: "page_visit",
    url: details.url,
    tab_id: details.tabId,
    captured_at: new Date().toISOString()
  });
  stats.captured++;

  if (eventBuffer.length >= MAX_BUFFER) {
    flushBuffer();
  }
});

// ---------------------------------------------------------------------------
// Alarms — periodic tasks
// ---------------------------------------------------------------------------

chrome.alarms.create("flush_buffer", { periodInMinutes: 0.17 });   // ~10s
chrome.alarms.create("check_status", { periodInMinutes: 1 });       // 60s
chrome.alarms.create("refresh_config", { periodInMinutes: 5 });     // 5 min

chrome.alarms.onAlarm.addListener((alarm) => {
  switch (alarm.name) {
    case "flush_buffer":
      flushBuffer();
      break;
    case "check_status":
      checkServiceStatus();
      break;
    case "refresh_config":
      fetchConfig();
      break;
  }
});

// ---------------------------------------------------------------------------
// Startup
// ---------------------------------------------------------------------------

console.log("[Phoenix] Background service worker starting...");

// Load direct-mode credentials, then consent state, then check service
loadDirectModeCredentials().then(() => {
  chrome.storage.local.get(["consent_state"], (data) => {
    consentState = data.consent_state || null;
    registerContentScriptIfConsented();
    checkServiceStatus();
    fetchConfig();
  });
});
